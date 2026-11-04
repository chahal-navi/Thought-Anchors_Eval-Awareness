"""Sample CoTs from the subject model on the probe prompts and parse its EVALUATION/DEPLOYMENT label.

Sampling settings follow thought anchors (temperature 0.6, top_p 0.95).
Saves results/cots_<probe name>.json:
    {"prompt": ..., "model": ..., "samples": [{"reasoning", "content", "label", "finish_reason"}, ...]}

Usage:
    python sample_cots.py                          # all three probes, 5 samples each
    python sample_cots.py --prompts probe_mmlu -n 20
"""

import argparse
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

from common import RESULTS_DIR, SUBJECT, SUBJECT_MODEL, load_prompt, openrouter_client, provider_body  # noqa: F401


def parse_label(content: str) -> str | None:
    labels = re.findall(r"<label>\s*(EVALUATION|DEPLOYMENT)\s*</label>", content or "", re.IGNORECASE)
    return labels[-1].upper() if labels else None


def sample_one(
    model: str, messages: list[dict], max_tokens: int, max_retries: int = 5, provider: str | None = None
) -> dict:
    extra_body = {"reasoning": {"enabled": True}}
    if provider or SUBJECT != "qwen":  # pinned providers for the subject model (see common.SUBJECTS)
        extra_body["provider"] = provider_body()
    for attempt in range(max_retries):
        try:
            resp = openrouter_client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.6,
                top_p=0.95,
                extra_body=extra_body,
            )
            if not resp.choices:  # OpenRouter sometimes returns an error body with no choices
                raise RuntimeError(f"empty/null choices: {getattr(resp, 'error', None)}")
            break
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            print(f"Retrying after error: {e}")
            time.sleep(2**attempt)
    choice = resp.choices[0]
    return {
        "reasoning": (getattr(choice.message, "reasoning", None) or "").strip(),
        "content": choice.message.content or "",
        "label": parse_label(choice.message.content),
        "finish_reason": choice.finish_reason,
        "provider": getattr(resp, "provider", None),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompts", nargs="+", default=["probe_mmlu", "probe_agentic", "probe_wildchat"])
    parser.add_argument("--model", default=SUBJECT_MODEL)
    parser.add_argument("-n", type=int, default=5, help="samples per prompt")
    parser.add_argument("--max-tokens", type=int, default=8000)
    args = parser.parse_args()

    RESULTS_DIR.mkdir(exist_ok=True)
    for name in args.prompts:
        record = load_prompt(name)
        with ThreadPoolExecutor(max_workers=args.n) as ex:
            samples = list(ex.map(lambda _: sample_one(args.model, record["messages"], args.max_tokens), range(args.n)))

        labels = [s["label"] for s in samples]
        n_eval = labels.count("EVALUATION")
        print(f"{name}: P(EVALUATION) = {n_eval}/{args.n}  labels={labels}  (ground truth {record['metadata']['ground_truth']})")
        for s in samples:
            if s["finish_reason"] != "stop" or not s["reasoning"]:
                print(f"  Warning: finish_reason={s['finish_reason']}, reasoning chars={len(s['reasoning'])}")

        out = RESULTS_DIR / f"cots_{name}.json"
        out.write_text(json.dumps({"prompt": name, "model": args.model, "samples": samples}, indent=2, ensure_ascii=False))
        print(f"Saved {out}")


if __name__ == "__main__":
    main()
