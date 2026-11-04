"""Thought-anchor resampling: regenerate the subject model's CoT from every chunk position.

For a base CoT split into chunks c_0..c_{N-1}, position i (0 <= i <= N) means: keep c_0..c_{i-1},
then let the model continue (so at i < N the chunk c_i is resampled). Position N keeps the whole
CoT and only resamples the rest of the reasoning + answer, so the last chunk also gets a score.

Continuations need a prefilled <think> block, so we use OpenRouter's raw completions endpoint with
Qwen3's chat template, pinned to DeepInfra (other providers re-wrap the prompt in their own
template instead of continuing it). OpenRouter returns the rest of the <think> block as
`reasoning` and the text after </think> as `text`.

Saves results/rollouts_<prompt>.json and resumes from it if it already exists.

Usage:
    python resample.py --prompt probe_mmlu -n 50
"""

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor

from tqdm import tqdm

from common import CFG, RESULTS_DIR, SUBJECT, cot_prefixes, load_prompt, use_exact_prefixes, openrouter_client, provider_body, raw_cot_prompt, split_raw_output
from judge import split_solution_into_chunks
from sample_cots import SUBJECT_MODEL, parse_label

PROVIDER = CFG["raw_providers"][0]


def pick_base_sample(prompt: str, label: str) -> int:
    """First sampled CoT with the given label."""
    samples = json.loads((RESULTS_DIR / f"cots_{prompt}.json").read_text())["samples"]
    return next(i for i, s in enumerate(samples) if s["label"] == label)


def continue_cot(raw_prompt: str, max_tokens: int, max_retries: int = 6, only_first_provider: bool = False) -> dict:
    for attempt in range(max_retries):
        try:
            resp = openrouter_client.completions.create(
                model=SUBJECT_MODEL,
                prompt=raw_prompt,
                max_tokens=max_tokens,
                temperature=0.6,
                top_p=0.95,
                extra_body={"provider": provider_body(raw=True, only_first=only_first_provider),
                            **({"skip_special_tokens": False} if SUBJECT != "qwen" else {})},
            )
            if not resp.choices:
                raise RuntimeError(f"empty/null choices: {getattr(resp, 'error', None)}")
            choice = resp.choices[0]
            reasoning = getattr(choice, "reasoning", None) or ""
            if SUBJECT == "qwen":
                return {"reasoning": reasoning, "text": choice.text or "", "label": parse_label(choice.text),
                        "finish_reason": choice.finish_reason}
            # Gemma: reasoning continuation and answer come back as one string, separated by <channel|>
            reasoning, answer, split = split_raw_output(choice.text or "", reasoning)
            return {"reasoning": reasoning, "text": answer, "label": parse_label(answer), "split": split,
                    "finish_reason": choice.finish_reason, "provider": getattr(resp, "provider", None)}
        except Exception as e:
            if attempt == max_retries - 1:
                return {"reasoning": "", "text": "", "label": None, "finish_reason": f"error: {e}"}
            time.sleep(2**attempt)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", required=True, help="probe prompt name, e.g. probe_mmlu")
    parser.add_argument("--sample-idx", type=int, help="base CoT index in cots_<prompt>.json")
    parser.add_argument("--base-label", help="pick the first CoT with this label (default: the ground truth)")
    parser.add_argument("--run-name", help="output results/rollouts_<run-name>.json (default: the prompt name)")
    parser.add_argument("-n", type=int, default=50, help="rollouts per chunk position")
    parser.add_argument("--max-tokens", type=int, default=6000)
    parser.add_argument("--workers", type=int, default=32)
    parser.add_argument("--adaptive", action="store_true",
                        help="top up to -n only at positions that are not saturated: P(EVAL) over existing rollouts "
                             "in (0.05, 0.95) at the position or a neighbour (elsewhere importance is ~0 anyway)")
    args = parser.parse_args()

    record = load_prompt(args.prompt)
    ground_truth = record["metadata"]["ground_truth"]
    run_name = args.run_name or args.prompt
    out_path = RESULTS_DIR / f"rollouts_{run_name}.json"

    if out_path.exists():
        data = json.loads(out_path.read_text())
        assert args.sample_idx in (None, data["sample_idx"]), "existing rollouts use a different base CoT"
        print(f"Resuming {out_path}")
    else:
        if args.sample_idx is not None:
            sample_idx = args.sample_idx
        else:
            sample_idx = pick_base_sample(args.prompt, args.base_label or ground_truth)
        base = json.loads((RESULTS_DIR / f"cots_{args.prompt}.json").read_text())["samples"][sample_idx]
        chunks = split_solution_into_chunks(base["reasoning"])
        data = {
            "run_name": run_name,
            "prompt": args.prompt,
            "model": SUBJECT_MODEL,
            "provider": PROVIDER,
            "ground_truth": ground_truth,
            "sample_idx": sample_idx,
            "base_label": base["label"],
            "chunks": chunks,
            "messages": base.get("messages", record["messages"]),  # multi-turn samples carry their own context
            "positions": [[] for _ in range(len(chunks) + 1)],
        }
        if use_exact_prefixes():
            data["prefixes"] = cot_prefixes(base["reasoning"], chunks)

    messages = data.get("messages", record["messages"])
    chunks = data["chunks"]

    unsaturated = set(range(len(data["positions"])))
    if args.adaptive:
        ps = [sum(r["label"] == "EVALUATION" for r in pos) / max(1, len(pos)) for pos in data["positions"]]
        mid = [i for i, p in enumerate(ps) if 0.05 < p < 0.95]
        unsaturated = {j for i in mid for j in (i - 1, i, i + 1) if 0 <= j < len(ps)}
        print(f"{run_name}: adaptive top-up at {len(unsaturated)}/{len(ps)} positions")

    jobs = []  # (position, raw prompt) for every missing rollout
    for i, rollouts in enumerate(data["positions"]):
        if data.get("prefixes"):
            raw = raw_cot_prompt(messages, data["prefixes"][i], exact=True)
        else:
            raw = raw_cot_prompt(messages, " ".join(chunks[:i]))
        if i in unsaturated:
            jobs += [(i, raw)] * (args.n - len(rollouts))
    print(f"{run_name}: base sample {data['sample_idx']}, {len(chunks)} chunks, {len(jobs)} rollouts to generate")

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = [(i, ex.submit(continue_cot, raw, args.max_tokens)) for i, raw in jobs]
        for n_done, (i, fut) in enumerate(tqdm(futures, desc="rollouts"), start=1):
            data["positions"][i].append(fut.result())
            if n_done % 200 == 0 or n_done == len(futures):
                out_path.write_text(json.dumps(data, ensure_ascii=False))

    labels = [r["label"] for pos in data["positions"] for r in pos]
    print(f"Saved {out_path}; unparsed labels: {labels.count(None)}/{len(labels)}")


if __name__ == "__main__":
    main()
