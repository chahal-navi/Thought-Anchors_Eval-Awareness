"""Build the input bundle for attention suppression (suppression_kl.py runs it on a GPU machine).

For every main run (10 prompts x EVAL/DEPL base CoT) of the subject model: the full text
    chat_template(probe) + think_open + original CoT + think_close + "<label>"
the character span of every CoT chunk (located verbatim in the original CoT, so tokens are on-policy),
and the black-box numbers to compare with (resampling curve, importance, lock-in).

Saves results/<subject>/suppression_bundle.json (Qwen: results/suppression_bundle.json).

Usage:
    python prepare_suppression.py               # Qwen
    SUBJECT=gemma python prepare_suppression.py
"""

import json

from common import CFG, RESULTS_DIR, SUBJECT, chat_template, cot_prefixes, load_prompt

QWEN_RUNS = [f"{p}_{l}" for p in ["a102", "a366", "a435", "a451", "a802", "m682", "w68", "w94b", "wacd", "wb6a"] for l in ["eval", "depl"]]
LABEL_PREFILL = "<label>"


def lock_in(p, tol=0.15):
    return next(i for i in range(len(p)) if all(abs(x - p[-1]) <= tol for x in p[i:]))


def main():
    report = {r["run"]: r for r in json.loads((RESULTS_DIR / "report_data.json").read_text())["runs"]}
    if SUBJECT == "gemma":
        runs = sorted(p.stem.removeprefix("rollouts_") for p in RESULTS_DIR.glob("rollouts_*.json"))
    else:
        runs = QWEN_RUNS
    out = []
    for run in runs:
        data = json.loads((RESULTS_DIR / f"rollouts_{run}.json").read_text())
        record = load_prompt(data["prompt"])
        if data.get("prefixes"):
            reasoning = data["prefixes"][-1]
        else:
            cots = json.loads((RESULTS_DIR / f"cots_{data['prompt']}.json").read_text())["samples"]
            reasoning = cots[data["sample_idx"]]["reasoning"].strip()
        prefixes = cot_prefixes(reasoning, data["chunks"])
        head = chat_template(record["messages"]) + CFG["think_open"]
        text = head + reasoning + CFG["think_close"] + LABEL_PREFILL
        base = len(head)
        spans = [(base + len(prefixes[i]), base + len(prefixes[i + 1])) for i in range(len(data["chunks"]))]
        p = report[run]["p_filtered"]
        out.append({
            "run": run, "prompt": data["prompt"], "base_label": data["base_label"], "ground_truth": data["ground_truth"],
            "text": text, "cot_start": base, "cot_end": base + len(reasoning), "spans": spans, "chunks": data["chunks"],
            "p_resampled": p, "importance": [p[i + 1] - p[i] for i in range(len(p) - 1)], "lock": lock_in(p),
            "tags": [c["tag"] for c in report[run]["chunks"]],
        })
        print(f"{run:12s} {len(data['chunks']):3d} chunks, {len(text):5d} chars, lock {out[-1]['lock']}")
    (RESULTS_DIR / "suppression_bundle.json").write_text(json.dumps({"subject": SUBJECT, "runs": out}, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
