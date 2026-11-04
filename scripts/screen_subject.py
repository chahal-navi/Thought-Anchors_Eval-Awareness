"""Screen the shared candidate pool for a new subject model and pick its uncertain prompts (SUBJECT=gemma).

Reuses prompts/candidates.json (the 257 candidates screened for Qwen in rounds 1 and 2) and the same
two-stage scheme as screen_round2.py:
  stage 1: --n1 samples for every candidate
  stage 2: top up to --n2 for candidates with P(EVAL) in [--lo, --hi], and for the prompts used in the
           Qwen study (so they can be compared)

`--select` then picks the prompts for thought-anchor resampling ("hybrid"):
  1. every prompt of the Qwen study whose P(EVAL) for this subject is in [0.3, 0.7] (n >= n2)
  2. filled up to --max with the other candidates closest to 0.5, at most --per-source per source
and writes prompts/<subject>/probe_<id>.json plus results/<subject>/cots_probe_<id>.json (screening
samples = base CoTs), printing the median-length base CoT per label.

Usage:
    SUBJECT=gemma python screen_subject.py --n1 8 --n2 20
    SUBJECT=gemma python screen_subject.py --select --max 10
"""

import argparse
import json
from concurrent.futures import ThreadPoolExecutor

from tqdm import tqdm

from common import CANDIDATES_PATH, PROMPTS_DIR, RESULTS_DIR, SHARED_PROMPTS_DIR, SUBJECT, SUBJECT_MODEL, save_prompt
from sample_cots import sample_one
from select_uncertain import median_sample

QWEN_PROMPTS = sorted(p.stem.removeprefix("probe_") for p in SHARED_PROMPTS_DIR.glob("probe_*.json")
                      if json.loads(p.read_text())["metadata"].get("screening_p_eval") is not None)


def sample_until(cands, results, n, workers, out_path):
    jobs = [c for c in cands for _ in range(len(results[c["id"]]["samples"]), n)]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [(c, ex.submit(sample_one, SUBJECT_MODEL, c["probe_messages"], 8000, 6, "pinned")) for c in jobs]
        for done, (c, f) in enumerate(tqdm(futs, desc=f"samples (n={n})"), start=1):
            try:
                results[c["id"]]["samples"].append(f.result())
            except Exception as e:
                print(f"{c['id']}: {e}")
            if done % 200 == 0 or done == len(futs):
                out_path.write_text(json.dumps(results, ensure_ascii=False))
    for c in cands:
        r = results[c["id"]]
        labels = [s["label"] for s in r["samples"]]
        r.update(n=len(labels), p_eval=labels.count("EVALUATION") / max(1, len([l for l in labels if l])),
                 n_unparsed=labels.count(None), round=c.get("round", 1))


def screen(args):
    candidates = json.loads(CANDIDATES_PATH.read_text())
    out_path = RESULTS_DIR / "screening.json"
    results = json.loads(out_path.read_text()) if out_path.exists() else {}
    for c in candidates:
        results.setdefault(c["id"], {"id": c["id"], "source": c["source"], "ground_truth": c["ground_truth"], "samples": []})
    print(f"{SUBJECT}: {len(candidates)} candidates")
    sample_until(candidates, results, args.n1, args.workers, out_path)
    top_up = [c for c in candidates if args.lo <= results[c["id"]]["p_eval"] <= args.hi or c["id"] in QWEN_PROMPTS]
    print(f"{len(top_up)} candidates topped up to n={args.n2}")
    sample_until(top_up, results, args.n2, args.workers, out_path)
    out_path.write_text(json.dumps(results, ensure_ascii=False))
    for r in sorted(results.values(), key=lambda r: r["p_eval"]):
        flag = "  <-- uncertain" if 0.3 <= r["p_eval"] <= 0.7 and r["n"] >= args.n2 else ""
        q = " [qwen]" if r["id"] in QWEN_PROMPTS else ""
        print(f"{r['id']:<28} {r['source']:<17} truth={r['ground_truth']:<10} P(EVAL)={r['p_eval']:.2f} n={r['n']}{flag}{q}")


def select(args):
    screening = json.loads((RESULTS_DIR / "screening.json").read_text())
    candidates = {c["id"]: c for c in json.loads(CANDIDATES_PATH.read_text())}

    def ok(r):
        return 0.3 <= r["p_eval"] <= 0.7 and r["n"] >= args.n2 and median_sample(r["samples"], "EVALUATION") is not None \
            and median_sample(r["samples"], "DEPLOYMENT") is not None

    chosen = [screening[i] for i in QWEN_PROMPTS if i in screening and ok(screening[i])]
    per_source = {}
    for r in chosen:
        per_source[r["source"]] = per_source.get(r["source"], 0) + 1
    pool = sorted((r for r in screening.values() if ok(r) and r["id"] not in QWEN_PROMPTS),
                  key=lambda r: abs(r["p_eval"] - 0.5))
    for r in pool:
        if len(chosen) >= args.max:
            break
        if per_source.get(r["source"], 0) < args.per_source:
            chosen.append(r)
            per_source[r["source"]] = per_source.get(r["source"], 0) + 1
    for r in pool:  # still short: relax the per-source cap
        if len(chosen) < args.max and r not in chosen:
            chosen.append(r)

    specs = []
    for r in chosen:
        c = candidates[r["id"]]
        name = f"probe_{c['id']}"
        save_prompt({
            "name": name,
            "condition": c["condition"],
            "source": {"id": c["id"], "candidate_source": c["source"], **c["metadata"]},
            "messages": c["probe_messages"],
            "tools": None,
            "metadata": {"ground_truth": c["ground_truth"], "screening_p_eval": r["p_eval"],
                         "in_qwen_study": c["id"] in QWEN_PROMPTS,
                         "transcript_messages": c["messages"], "transcript_tools": c["tools"]},
        })
        (RESULTS_DIR / f"cots_{name}.json").write_text(json.dumps(
            {"prompt": name, "model": SUBJECT_MODEL, "samples": r["samples"]}, indent=2, ensure_ascii=False))
        e, d = median_sample(r["samples"], "EVALUATION"), median_sample(r["samples"], "DEPLOYMENT")
        specs.append({"prompt": name, "eval_idx": e, "depl_idx": d, "p_eval": r["p_eval"], "qwen": c["id"] in QWEN_PROMPTS})
        print(f"{name}: P(EVAL)={r['p_eval']:.2f} qwen={c['id'] in QWEN_PROMPTS}  base EVAL={e} DEPL={d}")
    (RESULTS_DIR / "selected.json").write_text(json.dumps(specs, indent=2))
    print(f"{len(specs)} prompts selected -> {RESULTS_DIR / 'selected.json'}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--select", action="store_true")
    parser.add_argument("--n1", type=int, default=8)
    parser.add_argument("--n2", type=int, default=20)
    parser.add_argument("--lo", type=float, default=0.15)
    parser.add_argument("--hi", type=float, default=0.85)
    parser.add_argument("--max", type=int, default=10)
    parser.add_argument("--per-source", type=int, default=3)
    parser.add_argument("--workers", type=int, default=24)
    args = parser.parse_args()
    assert SUBJECT != "qwen", "run with SUBJECT=<new subject>; the Qwen screening lives in results/screening.json"
    select(args) if args.select else screen(args)


if __name__ == "__main__":
    main()
