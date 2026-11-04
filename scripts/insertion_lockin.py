"""H3 test: does a sentence that contradicts the verdict still work once the verdict has locked in?

insertion.py planted 12 fixed sentences right before the first cue-tagged chunk, which for every Gemma EVAL run
is *before* the lock-in point. Here the control and the 5 deployment-leaning sentences (the only ones that can
move a CoT already at P(EVAL) ~ 1) are planted at later cut points of the same base CoTs:
  - "lock+2": two chunks after lock-in
  - "mid":    halfway between lock-in and the end of the CoT
Lock-in L = first position after which every P_i (filtered resampling) stays within 0.15 of the final P.

If later deliberation is post-hoc, the same sentence should move the verdict much less after lock-in than
before it, even though the CoT has more room to drop there (control P ~ 1 vs ~0.5 before).

Saves results/<subject>/insertion_lockin_<run>.json.

Usage:
    SUBJECT=gemma python insertion_lockin.py --runs a272_eval ... -n 20 --positions lock+2 mid
"""

import argparse
import json
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from tqdm import tqdm

from common import RESULTS_DIR, load_prompt, raw_cot_prompt
from insertion import INSERTIONS
from resample import continue_cot

KEYS = [k for k in INSERTIONS if k[1] in ("none", "toward_deployment")]


def lock_in(p: list[float], tol: float = 0.15) -> int:
    final = p[-1]
    return next(i for i in range(len(p)) if all(abs(x - final) <= tol for x in p[i:]))


def cut_points(p: list[float]) -> dict[str, int]:
    n = len(p) - 1
    lock = lock_in(p)
    return {"lock+2": min(lock + 2, n - 1), "mid": min((lock + n) // 2, n - 1), "_lock": lock, "_n": n}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", nargs="+", required=True)
    parser.add_argument("-n", type=int, default=20)
    parser.add_argument("--positions", nargs="+", default=["lock+2", "mid"])
    parser.add_argument("--workers", type=int, default=24)
    args = parser.parse_args()

    report = {r["run"]: r for r in json.loads((RESULTS_DIR / "report_data.json").read_text())["runs"]}
    for run in args.runs:
        out_path = RESULTS_DIR / f"insertion_lockin_{run}.json"
        out = json.loads(out_path.read_text()) if out_path.exists() else {"run": run, "positions": {}}
        data = json.loads((RESULTS_DIR / f"rollouts_{run}.json").read_text())
        record = load_prompt(data["prompt"])
        cuts = cut_points(report[run]["p_filtered"])
        out.update(lock=cuts["_lock"], n_chunks=cuts["_n"], n=args.n)
        for pos in args.positions:
            if pos in out["positions"]:
                continue
            cut = cuts[pos]
            if data.get("prefixes"):  # Gemma: verbatim prefix with its line breaks
                prefix = data["prefixes"][cut]
                build = lambda s: raw_cot_prompt(record["messages"], prefix + s + " ", exact=True)
            else:
                prefix = " ".join(data["chunks"][:cut])
                build = lambda s: raw_cot_prompt(record["messages"], (prefix + " " if prefix else "") + s)
            jobs = [(k, build(INSERTIONS[k])) for k in KEYS for _ in range(args.n)]
            with ThreadPoolExecutor(max_workers=args.workers) as ex:
                res = list(tqdm(ex.map(lambda j: continue_cot(j[1], 6000), jobs), total=len(jobs), desc=f"{run} {pos}"))
            labels = {}
            for (k, _), r in zip(jobs, res):
                labels.setdefault(k, []).append(r["label"])
            p = {k: float(np.mean([l == "EVALUATION" for l in ls if l])) if any(ls) else None for k, ls in labels.items()}
            ctl = p[("control", "none")]
            out["positions"][pos] = {
                "insert_before_chunk": cut,
                "p_eval_no_insertion": float(report[run]["p_filtered"][cut]),
                "insertions": [{"category": c, "direction": d, "sentence": INSERTIONS[(c, d)], "p_eval": p[(c, d)],
                                "effect_vs_control": None if p[(c, d)] is None or ctl is None else p[(c, d)] - ctl,
                                "n_unparsed": labels[(c, d)].count(None)} for c, d in KEYS],
            }
            out_path.write_text(json.dumps(out, indent=2))
            print(f"{run} {pos}: cut {cut} (lock {cuts['_lock']}/{cuts['_n']}), control P(EVAL)={ctl:.2f}, "
                  + ", ".join(f"{x['category']}={x['effect_vs_control']:+.2f}" for x in out["positions"][pos]["insertions"][1:]))


if __name__ == "__main__":
    main()
