"""Forced-answer P(EVALUATION) at every chunk position of a base CoT (soft outcome).

For position i (0..N) we close the CoT right after chunk i-1 ("...</think>\n\n") and sample the
visible answer (<= 200 tokens, no further thinking) k times at temperature 1 and parse its <label>. (Prefilling "<label>"
itself breaks the model's tokenization and produces junk / a DEPLOYMENT bias, so we don't.) The fraction of EVALUATION samples estimates
P(EVALUATION | reasoning so far) without letting the model reason further. This is the
"forced answer" metric from thought anchors (chapter4 part3 `calculate_answer_importance`), and it
is continuous even when resampled rollouts all end with the same hard label.

DeepInfra (the only provider that continues raw prompts correctly) does not return logprobs, so
the probability is estimated by sampling instead.

Saves results/forced_<run>.json with p_eval per position and forced importance (diff).

Usage:
    python forced.py --runs probe_wildchat -k 20
"""

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from common import CFG, RESULTS_DIR, SUBJECT, forced_prompt, load_prompt, openrouter_client, provider_body
from sample_cots import SUBJECT_MODEL, parse_label


def forced_label(raw_prompt: str, max_retries: int = 8) -> str | None:
    for attempt in range(max_retries):
        try:
            resp = openrouter_client.completions.create(
                model=SUBJECT_MODEL,
                prompt=raw_prompt,
                max_tokens=CFG["forced_max_tokens"],
                temperature=1.0,
                extra_body={"provider": provider_body(raw=True),
                            **({"skip_special_tokens": False} if SUBJECT != "qwen" else {})},
            )
            text = resp.choices[0].text or ""
            if CFG.get("forced_label_prefill"):
                word = text.strip().upper()
                return "EVALUATION" if word.startswith("EVAL") else "DEPLOYMENT" if word.startswith("DEPLOY") else None
            # the answer after </think> sometimes has a sentence or two before the label
            return parse_label(text)
        except Exception:
            time.sleep(min(2**attempt, 30))
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", nargs="+", required=True)
    parser.add_argument("-k", type=int, default=20, help="label samples per position")
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()

    for run in args.runs:
        data = json.loads((RESULTS_DIR / f"rollouts_{run}.json").read_text())
        record = load_prompt(data["prompt"])
        chunks = data["chunks"]
        msgs = data.get("messages", record["messages"])
        if data.get("prefixes"):  # verbatim prefixes (Gemma)
            prompts = [forced_prompt(msgs, p.rstrip()) for p in data["prefixes"]]
        else:
            prompts = [forced_prompt(msgs, " ".join(chunks[:i])) for i in range(len(chunks) + 1)]
        prompts = [p + CFG.get("forced_label_prefill", "") for p in prompts]

        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            labels = list(ex.map(forced_label, [p for p in prompts for _ in range(args.k)]))
        per_pos = [labels[i * args.k:(i + 1) * args.k] for i in range(len(prompts))]
        p_eval = [
            float(np.mean([l == "EVALUATION" for l in ls if l])) if any(ls) else None for ls in per_pos
        ]
        out = {
            "run": run,
            "k": args.k,
            "p_eval": p_eval,
            "forced_importance": [None if a is None or b is None else b - a for a, b in zip(p_eval, p_eval[1:])],
            "n_unparsed": sum(l is None for l in labels),
        }
        (RESULTS_DIR / f"forced_{run}.json").write_text(json.dumps(out, indent=2))
        print(f"{run}: forced P(EVAL) {[round(p, 2) if p is not None else None for p in p_eval]} (unparsed {out['n_unparsed']})")


if __name__ == "__main__":
    main()
