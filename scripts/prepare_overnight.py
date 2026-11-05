"""Build the input bundles for the overnight white-box experiments (gpu/overnight.py runs them on the GPU machine).

ov_bundle_<model>.json   base CoTs (same 20 runs per model as the suppression study) + the blocks to suppress:
    exp 2  whole-CoT / user-prompt blocks (char spans)
    exp 3  sentence groups (pre-lock, post-lock, last 2, opening, checklist, top anchors, size-matched random sets,
           growing prefixes / suffixes)
probe_bundle_<model>.json  all 200 sampled CoTs per model (20 per prompt, ~half EVAL / half DEPLOY) with sentence
    spans and the parsed label, for the verdict probe (exp 1); plus the chat-template heads for fresh generations.

Usage:
    python prepare_overnight.py            # Qwen
    SUBJECT=gemma python prepare_overnight.py
"""

import json
import random

import build_report_causal as BC
from common import CFG, RESULTS_DIR, SUBJECT, chat_template, cot_prefixes, load_prompt
from judge import split_solution_into_chunks

LABEL_PREFILL = "<label>"
N_RANDOM = 5


def user_spans(text, messages):
    out, pos = [], 0
    for m in messages:
        if m["role"] != "user" or not isinstance(m["content"], str):
            continue
        s = text.find(m["content"].strip(), pos)
        if s >= 0:
            out.append((s, s + len(m["content"].strip())))
            pos = s + 1
    return out


def groups_for(r, anchors):
    N, L = len(r["spans"]), r["lock"]
    g = {
        "pre_lock": list(range(0, L)),
        "post_lock": list(range(L, N - 2)),
        "last2": [N - 2, N - 1],
        "opening": [0, 1],
        "kl_top3": anchors[:3],
        "imp_top3": sorted(range(len(r["importance"])), key=lambda j: -abs(r["importance"][j]))[:3],
        "checklist": [j for j, c in enumerate(r["chunks"]) if BC.DEFN.search(c.strip()) or BC.QUESTION.search(c.strip())],
    }
    g = {k: v for k, v in g.items() if v}
    rng = random.Random(hash(r["run"]) % 10**6)
    for k, v in list(g.items()):
        for t in range(N_RANDOM):
            g[f"rand_{k}_{t}"] = sorted(rng.sample(range(N), len(v)))
    for f in range(1, 11):
        k = max(1, round(f / 10 * N))
        g[f"prefix_{f}"] = list(range(0, k))
        if k < N:
            g[f"suffix_{f}"] = list(range(k, N))
    return g


def main():
    sup = json.loads((RESULTS_DIR / "suppression_bundle.json").read_text())["runs"]
    an = json.loads((BC.RES / "suppression_analysis.json").read_text())[SUBJECT]["runs"]
    anchors = {r["run"]: BC.per_run(r)["anchors"] for r in an}
    runs = []
    for r in sup:
        rec = load_prompt(r["prompt"])
        r["user_spans"] = user_spans(r["text"][: r["cot_start"]], rec["messages"])
        assert r["user_spans"], r["run"]
        r["groups"] = groups_for(r, anchors[r["run"]])
        runs.append(r)
        print(f"{r['run']:12s} user spans {r['user_spans']}  groups {len(r['groups'])}  checklist {r['groups'].get('checklist')}")
    name = "qwen" if SUBJECT == "qwen" else SUBJECT
    (RESULTS_DIR / f"ov_bundle_{name}.json").write_text(json.dumps({"subject": SUBJECT, "runs": runs}, ensure_ascii=False))

    base_idx = {(r["prompt"], json.loads((RESULTS_DIR / f"rollouts_{r['run']}.json").read_text())["sample_idx"]): r["run"] for r in sup}
    samples, heads = [], {}
    for p in sorted({r["prompt"] for r in sup}):
        rec = load_prompt(p)
        head = chat_template(rec["messages"]) + CFG["think_open"]
        heads[p] = head
        for i, s in enumerate(json.loads((RESULTS_DIR / f"cots_{p}.json").read_text())["samples"]):
            reasoning = (s.get("reasoning") or "").strip()
            if s["label"] not in ("EVALUATION", "DEPLOYMENT") or not reasoning:
                continue
            chunks = split_solution_into_chunks(reasoning)
            try:
                pref = cot_prefixes(reasoning, chunks)
            except ValueError as e:
                print("skip", p, i, e)
                continue
            base = len(head)
            samples.append({"prompt": p, "sample_idx": i, "label": s["label"], "base_run": base_idx.get((p, i)),
                            "text": head + reasoning + CFG["think_close"] + LABEL_PREFILL, "cot_start": base,
                            "spans": [(base + len(pref[k]), base + len(pref[k + 1])) for k in range(len(chunks))]})
    print(f"{len(samples)} probe samples, {sum(s['base_run'] is not None for s in samples)} of them base runs")
    (RESULTS_DIR / f"probe_bundle_{name}.json").write_text(json.dumps({"subject": SUBJECT, "think_close": CFG["think_close"],
                                                                         "heads": heads, "samples": samples}, ensure_ascii=False))


if __name__ == "__main__":
    main()
