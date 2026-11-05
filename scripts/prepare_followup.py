"""Follow-up bundle (designed after exp 2/3/6): what in the CoT does the answer read?

Per base run A (its partner B = the other base run of the same prompt, opposite verdict):
  splices     A's first f of sentences + B's remaining sentences (teacher-forced), f in 0.25 .. 0.9,
              and A with its last m sentences replaced by B's last m (m = 1, 2, 3)  -> does the answer follow the tail?
  verdict_stmt  sentences that state a verdict in capitals (EVALUATION / DEPLOYMENT), blocked from all later
              tokens, + 5 size-matched random sets
Plus, run on the GPU without bundle data: every sentence blocked from the answer only, and the whole CoT blocked
from the answer in a range of layers only.

Usage:
    python prepare_followup.py; SUBJECT=gemma python prepare_followup.py
"""

import json
import random
import re

from common import CFG, RESULTS_DIR, SUBJECT

STMT = re.compile(r"\b(EVALUATION|DEPLOYMENT)\b")
WORD = re.compile(r"evaluat|deploy", re.I)  # any sentence that names one of the two labels


def splice(A, B, kA, kB):
    close = CFG["think_close"] + "<label>"
    pre = A["text"][: A["spans"][kA][0]] if kA < len(A["spans"]) else A["text"][: A["cot_end"]]
    tail = B["text"][B["spans"][kB][0]: B["cot_end"]] if kB < len(B["spans"]) else ""
    d = len(pre) - (B["spans"][kB][0] if kB < len(B["spans"]) else 0)
    spans = [tuple(s) for s in A["spans"][:kA]] + [(s + d, e + d) for s, e in B["spans"][kB:]]
    spans = [(s, min(e, len(pre) + len(tail))) for s, e in spans]
    return {"text": pre + tail + close, "spans": spans, "cot_start": A["cot_start"], "user_spans": A["user_spans"]}


def main():
    name = "qwen" if SUBJECT == "qwen" else SUBJECT
    runs = json.loads((RESULTS_DIR / f"ov_bundle_{name}.json").read_text())["runs"]
    by_prompt = {}
    for r in runs:
        by_prompt.setdefault(r["prompt"], []).append(r)
    out = []
    for A in runs:
        B = next(r for r in by_prompt[A["prompt"]] if r["base_label"] != A["base_label"])
        NA, NB = len(A["spans"]), len(B["spans"])
        sp = {}
        for f in (0.25, 0.5, 0.75, 0.9):
            sp[f"frac_{f}"] = splice(A, B, round(f * NA), round(f * NB))
        for m in (1, 2, 3):
            sp[f"tail_{m}"] = splice(A, B, NA - m, NB - m)
        stmt = [j for j, c in enumerate(A["chunks"]) if STMT.search(c)]
        word = [j for j, c in enumerate(A["chunks"]) if WORD.search(c)]
        rng = random.Random(len(A["run"]) * 7919 + NA)
        groups = {}
        for g, v in (("verdict_stmt", stmt), ("label_word", word)):
            if v and len(v) < NA:
                groups[g] = v
                for t in range(5):
                    groups[f"rand_{g}_{t}"] = sorted(rng.sample(range(NA), len(v)))
        out.append({"run": A["run"], "partner": B["run"], "base_label": A["base_label"], "text": A["text"], "spans": A["spans"],
                    "user_spans": A["user_spans"], "cot_start": A["cot_start"], "splices": sp, "groups": groups,
                    "stmt_idx": stmt})
        print(f"{A['run']:12s} partner {B['run']:12s} verdict statements {stmt}, label-word sentences {len(word)} of {NA}")
    (RESULTS_DIR / f"fu_bundle_{name}.json").write_text(json.dumps({"subject": SUBJECT, "runs": out}, ensure_ascii=False))


if __name__ == "__main__":
    main()
