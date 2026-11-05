"""Analyse the overnight white-box experiments (gpu/overnight.py): exp 2 (prompt / whole-CoT blocks),
exp 3 (sentence groups), exp 6 (receiver heads). Writes results/overnight_analysis.json.

"share" of a block = how much of the verdict margin it removes: -delta * sign(base) / |base|
  0 = no effect, 1 = verdict pushed to 50/50, > 1 = verdict flipped.

Usage:
    python analyze_overnight.py
"""

import json
import statistics as st

import numpy as np
from scipy.stats import spearmanr, wilcoxon

from common import CAPSTONE_DIR

RES = CAPSTONE_DIR / "results"
MODELS = {"qwen": (RES / "ov_white_qwen.json", RES / "ov_bundle_qwen.json"),
          "gemma": (RES / "gemma" / "ov_white_gemma.json", RES / "gemma" / "ov_bundle_gemma.json")}
GROUPS = ["pre_lock", "post_lock", "last2", "opening", "checklist", "kl_top3", "imp_top3"]


def share(delta, base):
    return -delta * np.sign(base) / abs(base)


def wil(a, b):
    a, b = np.array(a), np.array(b)
    if len(a) < 5 or np.allclose(a, b):
        return None
    return float(wilcoxon(a, b).pvalue)


def analyse(key):
    res_path, bundle_path = MODELS[key]
    if not res_path.exists():
        return None
    res = json.loads(res_path.read_text())
    bundle = {r["run"]: r for r in json.loads(bundle_path.read_text())["runs"]}
    sup = {r["run"]: r for r in json.loads((RES / "suppression_analysis.json").read_text())[key]["runs"]}
    runs = {k: v for k, v in res["runs"].items() if "exp2" in v}
    out = {"n_runs": len(runs)}

    # ---- exp 2 ----
    conds = list(next(iter(runs.values()))["exp2"])
    e2 = {}
    for c in conds:
        sh = [share(r["exp2"][c], r["base_logodds"]) for r in runs.values()]
        e2[c] = {"median_share": float(np.median(sh)), "mean_share": float(np.mean(sh)), "flips": int(sum(s > 1 for s in sh)),
                 "per_run": {k: float(share(r["exp2"][c], r["base_logodds"])) for k, r in runs.items()}}
    out["exp2"] = e2

    # ---- exp 3 ----
    e3 = {}
    for g in GROUPS:
        obs, rnd, sizes = [], [], []
        for k, r in runs.items():
            if g not in r["exp3"]:
                continue
            obs.append(share(r["exp3"][g], r["base_logodds"]))
            rr = [share(v, r["base_logodds"]) for n, v in r["exp3"].items() if n.startswith(f"rand_{g}_")]
            rnd.append(float(np.mean(rr)))
            sizes.append(len(bundle[k]["groups"][g]) / len(bundle[k]["spans"]))
        if obs:
            e3[g] = {"n": len(obs), "median_share": float(np.median(obs)), "median_random": float(np.median(rnd)),
                     "mean_share": float(np.mean(obs)), "mean_random": float(np.mean(rnd)),
                     "beats_random": int(sum(o > q for o, q in zip(obs, rnd))), "p": wil(obs, rnd),
                     "flips": int(sum(o > 1 for o in obs)), "mean_size": float(np.mean(sizes)),
                     "per_run": [[float(o), float(q)] for o, q in zip(obs, rnd)]}
    out["exp3"] = e3
    curve = {"prefix": [], "suffix": []}
    for kind in curve:
        for f in range(1, 11):
            v = [share(r["exp3"][f"{kind}_{f}"], r["base_logodds"]) for r in runs.values() if f"{kind}_{f}" in r["exp3"]]
            curve[kind].append({"f": f / 10, "median": float(np.median(v)) if v else None,
                                "q25": float(np.percentile(v, 25)) if v else None, "q75": float(np.percentile(v, 75)) if v else None,
                                "flips": int(sum(x > 1 for x in v)), "n": len(v)})
    out["curves"] = curve

    # ---- exp 6 ----
    if "receiver" in res and all("exp6" in r for r in runs.values()):
        rec = res["receiver"]
        e6 = {"top20": rec["top20"], "split_half_r": rec["split_half_r"]}
        nL = len(rec["kurtosis_mean"])
        e6["layers"] = sorted(l for l, _ in rec["top20"])
        e6["n_layers"] = nL
        hs = ["receiver", "random0", "random1"]
        e6["mean_abs_dlo"] = {h: float(np.mean([abs(x) for r in runs.values() for x in r["exp6"][h]["dlo"]])) for h in hs}
        e6["max_share_median"] = {h: float(np.median([max(share(x, r["base_logodds"]) for x in r["exp6"][h]["dlo"]) for r in runs.values()])) for h in hs}
        allh = [abs(x) for k in runs for x in sup[k]["delta_logodds"]]
        e6["mean_abs_dlo"]["all_heads"] = float(np.mean(allh))
        rho_all, rho_imp, rho_anchor = [], [], []
        for k, r in runs.items():
            d = np.abs(r["exp6"]["receiver"]["dlo"])
            rho_all.append(spearmanr(d, np.abs(sup[k]["delta_logodds"])).correlation)
            vert = np.array(res["vertical"][k])  # (layers, heads, N)
            rs = np.mean([vert[l, h] for l, h in rec["top20"]], axis=0)
            imp = np.abs(sup[k]["importance"][: len(rs)])
            n = len(rs) - 5
            rho_imp.append(spearmanr(rs[:n], imp[:n]).correlation)
            infl = [x if x is not None else np.nan for x in sup[k]["influence"]]
            ok = [j for j in range(n) if not np.isnan(infl[j])]
            rho_anchor.append(spearmanr(rs[ok], np.array(infl)[ok]).correlation)
        med = lambda xs: float(np.nanmedian(xs))
        e6["rho_receiver_dlo_vs_allheads_dlo"] = med(rho_all)
        e6["rho_receiver_score_vs_importance"] = med(rho_imp)
        e6["rho_receiver_score_vs_anchor"] = med(rho_anchor)
        g6 = {}
        for g in GROUPS + ["cot_all"]:
            vals = {h: [share(r["exp6"][h][f"group_{g}"], r["base_logodds"]) for r in runs.values() if f"group_{g}" in r["exp6"][h]] for h in hs}
            allv = [share(r["exp2"]["cot_all"] if g == "cot_all" else r["exp3"][g], r["base_logodds"]) for r in runs.values()
                    if (g == "cot_all" or g in r["exp3"])]
            if vals["receiver"]:
                g6[g] = {"receiver": float(np.median(vals["receiver"])), "random": float(np.median(vals["random0"] + vals["random1"])),
                         "all_heads": float(np.median(allv)), "p_receiver_vs_random": wil(vals["receiver"], [(a + b) / 2 for a, b in zip(vals["random0"], vals["random1"])])}
        e6["groups"] = g6
        out["exp6"] = e6
    return out


FU = {"qwen": (RES / "fu_qwen.json", RES / "fu_bundle_qwen.json"), "gemma": (RES / "gemma" / "fu_gemma.json", RES / "gemma" / "fu_bundle_gemma.json")}


def analyse_followup(key):
    res_path, bundle_path = FU[key]
    if not res_path.exists():
        return None
    res = json.loads(res_path.read_text())["runs"]
    bundle = {r["run"]: r for r in json.loads(bundle_path.read_text())["runs"]}
    out = {"n_runs": len(res)}
    # splices: does the answer follow the head (A) or the tail (B)?  toward_A = log-odds signed so + = A's verdict
    sp = {}
    names = list(next(iter(res.values()))["splices"])
    for n in names:
        tA = [r["splices"][n] * (1 if bundle[k]["base_label"] == "EVALUATION" else -1) for k, r in res.items()]
        sp[n] = {"follows_tail": int(sum(x < 0 for x in tA)), "n": len(tA), "median_toward_head": float(np.median(tA))}
    out["splices"] = sp
    out["base_toward_head_median"] = float(np.median([abs(r["base_logodds"]) for r in res.values()]))
    # verdict-statement / label-word blocks vs random
    g = {}
    for grp in ["verdict_stmt", "label_word"]:
        obs, rnd = [], []
        for k, r in res.items():
            if grp in r["groups"]:
                obs.append(share(r["groups"][grp], r["base_logodds"]))
                rnd.append(float(np.mean([share(v, r["base_logodds"]) for n, v in r["groups"].items() if n.startswith(f"rand_{grp}_")])))
        if obs:
            g[grp] = {"n": len(obs), "median_share": float(np.median(obs)), "median_random": float(np.median(rnd)),
                      "beats_random": int(sum(o > q for o, q in zip(obs, rnd))), "p": wil(obs, rnd), "flips": int(sum(o > 1 for o in obs))}
    out["groups"] = g
    # answer-only per sentence: where does the answer read directly?
    last2, word, tot, top_last2 = [], [], [], 0
    for k, r in res.items():
        a = np.abs(r["answer_only"])
        N = len(a)
        tot.append(a.sum())
        last2.append(a[-2:].sum() / max(a.sum(), 1e-9))
        lw = bundle[k]["groups"].get("label_word", [])
        word.append((a[lw].sum() / max(a.sum(), 1e-9), len(lw) / N))
        top_last2 += int(np.argmax(a) >= N - 2)
    out["answer_only"] = {"share_of_effect_in_last2_median": float(np.median(last2)), "top_in_last2": top_last2,
                          "label_word_share_median": float(np.median([w[0] for w in word])), "label_word_frac_median": float(np.median([w[1] for w in word])),
                          "max_share_median": float(np.median([max(share(x, r["base_logodds"]) for x in r["answer_only"]) for r in res.values()])),
                          "per_run": {k: [share(x, r["base_logodds"]) for x in r["answer_only"]] for k, r in res.items()}}
    # layers: block the CoT from the answer in a window of layers only
    lay = {}
    for kind in ["layers_window", "layers_from", "layers_upto"]:
        keys = list(next(iter(res.values()))[kind])
        lay[kind] = [{"layers": kk, "median_share": float(np.median([share(r[kind][kk], r["base_logodds"]) for r in res.values()])),
                      "flips": int(sum(share(r[kind][kk], r["base_logodds"]) > 1 for r in res.values()))} for kk in keys]
    out["layers"] = lay
    return out


RD = {"qwen": RES / "readers_qwen.json", "gemma": RES / "gemma" / "readers_gemma.json"}


def analyse_readers(key):
    """Reader heads: block the CoT from the answer in only the top-k heads by answer->CoT attention (vs random k),
    or in all heads except the top-k."""
    if not RD[key].exists():
        return None
    d = json.loads(RD[key].read_text())
    res = d["runs"]
    if not res:
        return None
    ks = list(next(iter(res.values()))["top"])
    S = np.array(list(d["scores"].values()))  # runs, L, H, 3
    score = S[..., 0].mean(0)
    rows = []
    for k in ks:
        top = [share(r["top"][k], r["base_logodds"]) for r in res.values()]
        rnd = [float(np.mean([share(x, r["base_logodds"]) for x in r["random"][k]])) for r in res.values()]
        keep = [share(r["keep_top"][k], r["base_logodds"]) for r in res.values()]
        rows.append({"k": int(k), "frac_heads": int(k) / score.size, "top": float(np.median(top)), "random": float(np.median(rnd)),
                     "keep_top": float(np.median(keep)), "beats_random": int(sum(a > b for a, b in zip(top, rnd))), "p": wil(top, rnd),
                     "flips_top": int(sum(x > 1 for x in top)), "flips_keep": int(sum(x > 1 for x in keep))})
    top_heads = d["top_heads"][:20]
    extra = {}
    r0 = next(iter(res.values()))
    if "single_layer" in r0:
        extra["window"] = d["window"]
        extra["single_layer"] = [{"layer": int(l), "share": float(np.median([share(r["single_layer"][l], r["base_logodds"]) for r in res.values()]))} for l in r0["single_layer"]]
        win = []
        for k in r0["win_top"]:
            top = [share(r["win_top"][k], r["base_logodds"]) for r in res.values()]
            rnd = [float(np.mean([share(x, r["base_logodds"]) for x in r["win_random"][k]])) for r in res.values()]
            win.append({"k": int(k), "top": float(np.median(top)), "random": float(np.median(rnd)), "beats_random": int(sum(a > b for a, b in zip(top, rnd))),
                        "p": wil(top, rnd), "flips_top": int(sum(x > 1 for x in top))})
        extra["win"] = win
        extra["win_top_heads"] = d["win_top_heads"][:16]
    return {**extra, "n_runs": len(res), "n_heads": int(score.size), "n_layers": int(score.shape[0]), "rows": rows,
            "all_heads": float(np.median([share(r["cot_all_answer_only"], r["base_logodds"]) for r in res.values()])),
            "top_heads": [[int(l), int(h), float(score[l, h])] for l, h in top_heads],
            "layer_mass": score.sum(1).tolist(), "mass_sorted": np.sort(score.ravel())[::-1][:200].tolist(),
            "last2_frac_of_cot_mass": float(np.median(S[..., 1].sum((1, 2)) / S[..., 0].sum((1, 2))))}


def main():
    out = {k: a for k in MODELS if (a := analyse(k))}
    for k in RD:
        if (f := analyse_readers(k)):
            out.setdefault(k, {})["readers"] = f
            print(f"===== {k} reader heads ({f['n_runs']} runs; CoT blocked from the answer in all heads: share {f['all_heads']:+.2f})")
            print(f"   top heads {f['top_heads'][:8]}")
            if "single_layer" in f:
                print("   single layers: " + " ".join(f"{x['layer']}:{x['share']:+.2f}" for x in f["single_layer"]))
                print("   window top-k vs random: " + " ".join(f"{x['k']}:{x['top']:+.2f}/{x['random']:+.2f}({x['beats_random']})" for x in f["win"]))
            for x in f["rows"]:
                print(f"   k={x['k']:4d} ({x['frac_heads']:.1%}) top {x['top']:+.2f} vs random {x['random']:+.2f} beats {x['beats_random']}/{f['n_runs']} p={x['p']} flips {x['flips_top']} | all-but-top {x['keep_top']:+.2f} flips {x['flips_keep']}")
    for k in FU:
        if (f := analyse_followup(k)):
            out.setdefault(k, {})["followup"] = f
    (RES / "overnight_analysis.json").write_text(json.dumps(out, indent=1))
    for k, a in out.items():
        if "followup" in a:
            f = a["followup"]
            print(f"===== {k} follow-up ({f['n_runs']} runs)")
            for n, v in f["splices"].items():
                print(f"   splice {n:9s} answer follows the tail in {v['follows_tail']}/{v['n']}  median log-odds toward head {v['median_toward_head']:+.1f}")
            for n, v in f["groups"].items():
                print(f"   block {n:12s} n={v['n']} share {v['median_share']:+.2f} vs random {v['median_random']:+.2f} beats {v['beats_random']}/{v['n']} p={v['p']} flips {v['flips']}")
            ao = f["answer_only"]
            print(f"   answer-only: last 2 sentences carry {ao['share_of_effect_in_last2_median']:.0%} of the summed effect (top in last 2: {ao['top_in_last2']}), "
                  f"label-word sentences {ao['label_word_share_median']:.0%} (they are {ao['label_word_frac_median']:.0%} of sentences); max single share {ao['max_share_median']:+.2f}")
            for kind, v in f["layers"].items():
                print(f"   {kind}: " + " ".join(f"{x['layers']}:{x['median_share']:+.2f}" for x in v))
        if "exp2" not in a:
            continue
        print(f"===== {k}: {a['n_runs']} runs")
        print("exp2 (median share of margin removed, flips):")
        for c, v in a["exp2"].items():
            print(f"   {c:26s} {v['median_share']:+.2f}  flips {v['flips']}")
        print("exp3 (group vs size-matched random: median share, beats random, p):")
        for g, v in a["exp3"].items():
            print(f"   {g:10s} n={v['n']:2d} size {v['mean_size']:.0%}  {v['median_share']:+.2f} vs {v['median_random']:+.2f}  beats {v['beats_random']}/{v['n']}  p={v['p']}  flips {v['flips']}")
        for kind, cv in a["curves"].items():
            print(f"   {kind}: " + " ".join(f"{c['f']:.1f}:{c['median']:+.2f}" for c in cv if c["median"] is not None))
        if "exp6" in a:
            e = a["exp6"]
            print(f"exp6 receiver heads layers {e['layers']} (of {e['n_layers']}), split-half r {e['split_half_r']:.2f}")
            print(f"   mean |dlo| per sentence: {e['mean_abs_dlo']}")
            print(f"   rho receiver-only dlo vs all-heads dlo {e['rho_receiver_dlo_vs_allheads_dlo']:+.2f}; receiver score vs importance {e['rho_receiver_score_vs_importance']:+.2f}, vs anchor {e['rho_receiver_score_vs_anchor']:+.2f}")
            for g, v in e["groups"].items():
                print(f"   {g:10s} receiver {v['receiver']:+.2f} random {v['random']:+.2f} all heads {v['all_heads']:+.2f}  p={v['p_receiver_vs_random']}")


if __name__ == "__main__":
    main()
