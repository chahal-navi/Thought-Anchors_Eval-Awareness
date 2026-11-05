"""Analyse the attention-suppression results (suppression_kl.py) against the black-box resampling results.

Per run:
  - KL matrix M[i][j] (mean KL inside later chunk i when attention to chunk j is blocked); row-normalised as in the
    paper (subtract each row's mean over j < i)
  - outgoing influence of chunk j = mean over later rows of the raw M[i][j]  (how much later reasoning depends on j)
  - verdict effect of chunk j = change in log-odds EVAL vs DEPLOY at the answer when j is blocked
Comparisons:
  - Spearman correlation of |verdict effect| and outgoing influence with |resampling importance| (per run, then median)
  - sign: does blocking an eval-leaning chunk (importance > 0) lower the EVAL log-odds?
  - lock-in: influence of chunks before vs after the lock-in point L, with and without the last 2 chunks (where the
    model states its conclusion, which the answer can simply copy)

Usage:
    python analyze_suppression.py      # writes results/suppression_analysis.json (both models)
"""

import json
import statistics as st

import numpy as np
from scipy.stats import spearmanr

from common import CAPSTONE_DIR

RES = CAPSTONE_DIR / "results"
MODELS = {"qwen": ("Qwen3-32B (FP8)", RES / "suppression_qwen.json", RES / "suppression_bundle.json"),
          "gemma": ("Gemma 4 26B-A4B (bf16)", RES / "gemma" / "suppression_gemma.json", RES / "gemma" / "suppression_bundle.json")}


def analyse(key):
    name, res_path, bundle_path = MODELS[key]
    if not res_path.exists():
        return None
    res = json.loads(res_path.read_text())["runs"]
    bundle = {r["run"]: r for r in json.loads(bundle_path.read_text())["runs"]}
    runs, pooled = [], {"pre": [], "post": [], "post_wo_end": [], "infl_pre": [], "infl_post": [], "infl_post_wo_end": []}
    for run, r in res.items():
        b = bundle[run]
        N = len(r["matrix"])
        M = np.array([[np.nan if x is None else x for x in row] for row in r["matrix"]])
        with np.errstate(all="ignore"):
            Mn = M - np.nanmean(M, axis=1, keepdims=True)  # row-normalised (rows 1..N-1)
        # KL decays with distance i - j, so raw column means favour late chunks: subtract the run's mean KL at each distance
        D = {d: np.nanmean([M[i, i - d] for i in range(d, N)]) for d in range(1, N)}
        Md = np.array([[M[i, j] - D[i - j] if j < i else np.nan for j in range(N)] for i in range(N)])
        influence = [float(np.nanmean(Md[j + 1:, j])) if j < N - 1 else np.nan for j in range(N)]
        influence_raw = [float(np.nanmean(M[j + 1:, j])) if j < N - 1 else np.nan for j in range(N)]
        dlo = r["answer_delta_logodds"]
        imp = b["importance"][:N]
        L = b["lock"]
        ok = [j for j in range(N - 1) if not np.isnan(influence[j])]
        rho_v = spearmanr([abs(dlo[j]) for j in range(N)], [abs(x) for x in imp]).correlation
        rho_i = spearmanr([influence[j] for j in ok], [abs(imp[j]) for j in ok]).correlation
        # sign agreement on chunks with a clear black-box effect
        big = [j for j in range(N) if abs(imp[j]) >= 0.2]
        sign_ok = sum((imp[j] > 0) == (dlo[j] < 0) for j in big)
        end = N - 2  # last two chunks = stated conclusion
        for j in range(N):
            (pooled["pre"] if j < L else pooled["post"]).append(abs(dlo[j]))
            if j >= L and j < end:
                pooled["post_wo_end"].append(abs(dlo[j]))
            if not np.isnan(influence[j]):
                (pooled["infl_pre"] if j < L else pooled["infl_post"]).append(influence[j])
                if j >= L and j < end:
                    pooled["infl_post_wo_end"].append(influence[j])
        top_v = int(np.argmax(np.abs(dlo)))
        runs.append({
            "run": run, "base_label": b["base_label"], "N": N, "lock": L, "base_logodds": r["base_logodds"],
            "matrix": [[None if np.isnan(x) else float(x) for x in row] for row in M],
            "matrix_norm": [[None if np.isnan(x) else float(x) for x in row] for row in Mn],
            "influence": [None if np.isnan(x) else x for x in influence],
            "influence_raw": [None if np.isnan(x) else x for x in influence_raw],
            "kl_by_distance": [float(D[d]) for d in range(1, N)],
            "delta_logodds": dlo, "importance": imp, "chunks": b["chunks"], "tags": b["tags"],
            "rho_verdict_vs_importance": None if np.isnan(rho_v) else float(rho_v),
            "rho_influence_vs_importance": None if np.isnan(rho_i) else float(rho_i),
            "sign_agree": sign_ok, "n_big": len(big),
            "top_verdict_chunk": top_v, "top_verdict_in_last2": top_v >= end,
            "max_abs_delta_logodds": float(max(map(abs, dlo))),
            "flips": sum((r["base_logodds"] > 0) != (r["base_logodds"] + d > 0) for d in dlo),
        })
    med = lambda xs: float(st.median([x for x in xs if x is not None])) if any(x is not None for x in xs) else None
    mean = lambda xs: float(st.mean(xs)) if xs else None
    summary = {
        "name": name, "n_runs": len(runs), "n_chunks": sum(r["N"] for r in runs),
        "median_rho_verdict_vs_importance": med([r["rho_verdict_vs_importance"] for r in runs]),
        "median_rho_influence_vs_importance": med([r["rho_influence_vs_importance"] for r in runs]),
        "sign_agree": sum(r["sign_agree"] for r in runs), "n_big": sum(r["n_big"] for r in runs),
        "top_verdict_in_last2": sum(r["top_verdict_in_last2"] for r in runs),
        "flips": sum(r["flips"] for r in runs),
        "mean_abs_dlo_pre_lock": mean(pooled["pre"]), "mean_abs_dlo_post_lock": mean(pooled["post"]),
        "mean_abs_dlo_post_lock_wo_end": mean(pooled["post_wo_end"]),
        "mean_infl_pre_lock": mean(pooled["infl_pre"]), "mean_infl_post_lock": mean(pooled["infl_post"]),
        "mean_infl_post_lock_wo_end": mean(pooled["infl_post_wo_end"]),
        "n_pre": len(pooled["pre"]), "n_post": len(pooled["post"]), "n_post_wo_end": len(pooled["post_wo_end"]),
    }
    return {"summary": summary, "runs": runs}


def main():
    out = {k: a for k in MODELS if (a := analyse(k))}
    (RES / "suppression_analysis.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    for k, a in out.items():
        s = a["summary"]
        print(f"== {s['name']}: {s['n_runs']} runs, {s['n_chunks']} chunks")
        print(f"   verdict flips from blocking one chunk: {s['flips']}")
        print(f"   largest verdict effect falls in the last 2 chunks: {s['top_verdict_in_last2']}/{s['n_runs']} runs")
        print(f"   median Spearman |d-logodds| vs |resampling importance|: {s['median_rho_verdict_vs_importance']:+.2f}")
        print(f"   median Spearman outgoing KL influence (distance-corrected) vs |importance|:  {s['median_rho_influence_vs_importance']:+.2f}")
        print(f"   sign agreement (|importance|>=0.2): {s['sign_agree']}/{s['n_big']}")
        print(f"   mean |d-logodds|: before lock-in {s['mean_abs_dlo_pre_lock']:.2f} (n={s['n_pre']}), after {s['mean_abs_dlo_post_lock']:.2f} (n={s['n_post']}), "
              f"after excl. last 2 {s['mean_abs_dlo_post_lock_wo_end']:.2f} (n={s['n_post_wo_end']})")
        print(f"   mean outgoing KL (distance-corrected):  before lock-in {s['mean_infl_pre_lock']:+.3f}, after {s['mean_infl_post_lock']:+.3f}, after excl. last 2 {s['mean_infl_post_lock_wo_end']:+.3f}")
        for r in a["runs"]:
            print(f"     {r['run']:11s} N={r['N']:3d} L={r['lock']:3d} max|dlo|={r['max_abs_delta_logodds']:.2f}@{r['top_verdict_chunk']:<3d} "
                  f"rho_v={r['rho_verdict_vs_importance'] if r['rho_verdict_vs_importance'] is None else round(r['rho_verdict_vs_importance'], 2)} "
                  f"rho_i={r['rho_influence_vs_importance'] if r['rho_influence_vs_importance'] is None else round(r['rho_influence_vs_importance'], 2)} sign {r['sign_agree']}/{r['n_big']}")


if __name__ == "__main__":
    main()
