"""Screening round 2: a larger pool from the sources that produced uncertain prompts in round 1.

New candidates (appended to prompts/candidates.json, results merged into results/screening.json):
  - alpaca_eval: items not used in round 1
  - ifeval: IFEval prompts (instruction-following eval that reads like real requests)
  - mt_bench: remaining first turns
  - wildchat_natural: ordinary prompts from a fresh WildChat shard

Two stages to save cost: --n1 samples for every new candidate, then top up to --n2 for candidates
whose stage-1 P(EVAL) is in [--lo, --hi].

Usage:
    python screen_round2.py --n-alpaca 60 --n-ifeval 30 --n-mt 20 --n-wildchat 90
"""

import argparse
import json
import random
from concurrent.futures import ThreadPoolExecutor

from datasets import load_dataset
from huggingface_hub import hf_hub_download
from tqdm import tqdm

from build_probe_prompts import probe_content
from common import CANDIDATES_PATH, RESULTS_DIR
from sample_cots import SUBJECT_MODEL, sample_one
from screen_candidates import PROVIDER, TEST_LIKE, user_candidate

SEED = 1


def new_candidates(args, used_ids: set) -> list[dict]:
    rng = random.Random(SEED)
    out = []
    alpaca = json.load(open(hf_hub_download("tatsu-lab/alpaca_eval", "alpaca_eval.json", repo_type="dataset")))
    pool = [i for i in range(len(alpaca)) if f"alpaca_eval_{i}" not in used_ids]
    for i in rng.sample(pool, args.n_alpaca):
        out.append(user_candidate(f"alpaca_eval_{i}", "alpaca_eval", "capability_eval", alpaca[i]["instruction"],
                                  {"dataset": alpaca[i]["dataset"]}))
    ife = load_dataset("google/IFEval", split="train")
    for i in rng.sample(range(len(ife)), args.n_ifeval):
        out.append(user_candidate(f"ifeval_{ife[i]['key']}", "ifeval", "capability_eval", ife[i]["prompt"]))
    mt = [r for r in load_dataset("HuggingFaceH4/mt_bench_prompts", split="train") if f"mt_bench_{r['prompt_id']}" not in used_ids]
    for r in rng.sample(mt, min(args.n_mt, len(mt))):
        out.append(user_candidate(f"mt_bench_{r['prompt_id']}", "mt_bench", "capability_eval", r["prompt"][0],
                                  {"category": r["category"]}))
    ds = load_dataset("allenai/WildChat-4.8M", data_files="data/train-00001-of-00086.parquet", split="train")
    natural, seen = [], set()
    for r in ds:
        if r["language"] != "English" or r["turn"] != 1 or r["toxic"] or r["redacted"]:
            continue
        u = r["conversation"][0]["content"]
        if not 40 <= len(u) <= 1200 or u in seen or TEST_LIKE.search(u):
            continue
        seen.add(u)
        natural.append((r["conversation_hash"], u))
    for h, u in rng.sample(natural, args.n_wildchat):
        out.append(user_candidate(f"wildchat_natural_{h[:8]}", "wildchat_natural", "deployment", u, {"conversation_hash": h}))
    out = [c for c in out if c["id"] not in used_ids]
    for c in out:
        c["probe_messages"] = [{"role": "user", "content": probe_content(c["messages"], c["tools"])}]
    return out


def sample_until(cands: list[dict], results: dict, n: int, workers: int, out_path):
    jobs = [c for c in cands for _ in range(len(results[c["id"]]["samples"]), n)]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [(c, ex.submit(sample_one, SUBJECT_MODEL, c["probe_messages"], 8000, 5, PROVIDER)) for c in jobs]
        for done, (c, f) in enumerate(tqdm(futs, desc=f"samples (n={n})"), start=1):
            try:
                results[c["id"]]["samples"].append(f.result())
            except Exception as e:
                print(f"{c['id']}: {e}")
            if done % 100 == 0 or done == len(futs):
                out_path.write_text(json.dumps(results, ensure_ascii=False))
    for c in cands:
        r = results[c["id"]]
        labels = [s["label"] for s in r["samples"]]
        r.update(n=len(labels), p_eval=labels.count("EVALUATION") / max(1, len([l for l in labels if l])),
                 n_unparsed=labels.count(None), round=2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-alpaca", type=int, default=60)
    parser.add_argument("--n-ifeval", type=int, default=30)
    parser.add_argument("--n-mt", type=int, default=20)
    parser.add_argument("--n-wildchat", type=int, default=90)
    parser.add_argument("--n1", type=int, default=8)
    parser.add_argument("--n2", type=int, default=20)
    parser.add_argument("--lo", type=float, default=0.15)
    parser.add_argument("--hi", type=float, default=0.85)
    parser.add_argument("--workers", type=int, default=32)
    args = parser.parse_args()

    cands_path, out_path = CANDIDATES_PATH, RESULTS_DIR / "screening.json"
    candidates = json.loads(cands_path.read_text())
    results = json.loads(out_path.read_text())
    new = [c for c in candidates if c.get("round") == 2]
    if not new:
        new = new_candidates(args, {c["id"] for c in candidates})
        for c in new:
            c["round"] = 2
        candidates += new
        cands_path.write_text(json.dumps(candidates, indent=2, ensure_ascii=False))
    print(f"{len(new)} round-2 candidates")
    for c in new:
        results.setdefault(c["id"], {"id": c["id"], "source": c["source"], "ground_truth": c["ground_truth"], "samples": []})

    sample_until(new, results, args.n1, args.workers, out_path)
    promising = [c for c in new if args.lo <= results[c["id"]]["p_eval"] <= args.hi]
    print(f"{len(promising)} promising after stage 1; topping up to n={args.n2}")
    sample_until(promising, results, args.n2, args.workers, out_path)
    out_path.write_text(json.dumps(results, ensure_ascii=False))

    for c in sorted(new, key=lambda c: results[c["id"]]["p_eval"]):
        r = results[c["id"]]
        flag = "  <-- uncertain" if 0.3 <= r["p_eval"] <= 0.7 and r["n"] >= args.n2 else ""
        print(f"{r['id']:<28} {r['source']:<17} truth={r['ground_truth']:<10} P(EVAL)={r['p_eval']:.2f} n={r['n']}{flag}")


if __name__ == "__main__":
    main()
