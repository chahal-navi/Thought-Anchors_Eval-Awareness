"""Turn the most uncertain screened candidates into probe prompts for thought-anchor resampling.

Picks candidates with lo <= P(EVALUATION) <= hi from results/screening.json, closest to 0.5 first,
at most --per-source per source, and writes for each:
  prompts/probe_<id>.json        (same schema as the pilot probes)
  results/cots_probe_<id>.json   (its screening samples, which serve as base CoTs)
Prints the base CoT chosen for each label (median-length sample with that label).

Usage:
    python select_uncertain.py --max 4
"""

import argparse
import json

import numpy as np

from common import CANDIDATES_PATH, PROMPTS_DIR, RESULTS_DIR, save_prompt
from judge import split_solution_into_chunks
from sample_cots import SUBJECT_MODEL
from screen_candidates import PROVIDER


def median_sample(samples: list[dict], label: str) -> int | None:
    idx = [i for i, s in enumerate(samples) if s["label"] == label and s["reasoning"]]
    if not idx:
        return None
    lengths = [len(split_solution_into_chunks(samples[i]["reasoning"])) for i in idx]
    return idx[int(np.argsort(lengths)[len(lengths) // 2])]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lo", type=float, default=0.3)
    parser.add_argument("--hi", type=float, default=0.7)
    parser.add_argument("--max", type=int, default=4)
    parser.add_argument("--per-source", type=int, default=1)
    parser.add_argument("--min-n", type=int, default=20, help="only candidates with at least this many samples")
    args = parser.parse_args()

    screening = json.loads((RESULTS_DIR / "screening.json").read_text())
    candidates = {c["id"]: c for c in json.loads(CANDIDATES_PATH.read_text())}

    existing = {p.stem.removeprefix("probe_") for p in PROMPTS_DIR.glob("probe_*.json")}
    pool = sorted((r for r in screening.values()
                   if args.lo <= r["p_eval"] <= args.hi and r.get("n", 0) >= args.min_n and r["id"] not in existing),
                  key=lambda r: abs(r["p_eval"] - 0.5))
    chosen, per_source = [], {}
    for r in pool:
        if per_source.get(r["source"], 0) < args.per_source and len(chosen) < args.max:
            chosen.append(r)
            per_source[r["source"]] = per_source.get(r["source"], 0) + 1

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
                         "transcript_messages": c["messages"], "transcript_tools": c["tools"]},
        })
        (RESULTS_DIR / f"cots_{name}.json").write_text(json.dumps(
            {"prompt": name, "model": SUBJECT_MODEL, "provider": PROVIDER, "samples": r["samples"]},
            indent=2, ensure_ascii=False))
        print(f"{name}: P(EVAL)={r['p_eval']:.2f}  base EVALUATION={median_sample(r['samples'], 'EVALUATION')}"
              f"  base DEPLOYMENT={median_sample(r['samples'], 'DEPLOYMENT')}")


if __name__ == "__main__":
    main()
