"""Collect every result into one JSON for the web report (results/report_data.json).

Includes: screening P(EVAL) per candidate, per-run importance (resampled + forced), category-level
aggregates across runs, cue ablation, register ablation, insertion effects and the refusal experiment.

Usage:
    python build_report_data.py
"""

import json

import numpy as np

from common import CANDIDATES_PATH, RESULTS_DIR, load_prompt
from judge import EXCLUDED_CATEGORIES


def load(path):
    return json.loads(path.read_text()) if path.exists() else None


def main():
    screening = load(RESULTS_DIR / "screening.json")
    candidates = {c["id"]: c for c in load(CANDIDATES_PATH)}
    out = {"screening": [
        {"id": r["id"], "source": r["source"], "ground_truth": candidates[r["id"]]["ground_truth"],
         "p_eval": r["p_eval"], "n": r["n"], "round": r.get("round", 1),
         "preview": (candidates[r["id"]]["messages"][-1]["content"] or "")[:160]}
        for r in screening.values() if "p_eval" in r
    ]}

    runs, by_cat = [], {}
    for path in sorted(RESULTS_DIR.glob("importance_*.json")):
        imp = load(path)
        forced = load(RESULTS_DIR / f"forced_{imp['run']}.json")
        chunks = []
        for i, c in enumerate(imp["chunks_labeled"]):
            tag = c["function_tags"][0]
            chunks.append({"i": i, "text": c["chunk"], "tag": tag, "dir": c["eval_awareness"],
                           "imp": c["counterfactual_importance"], "se": c["importance_se"],
                           "p_all": imp["p_target_all"][i], "n_kept": c["n_kept"],
                           "forced_imp": forced["forced_importance"][i] if forced else None})
            by_cat.setdefault(tag, []).append((imp["run"], c["counterfactual_importance"],
                                               forced["forced_importance"][i] if forced else None))
        record = load_prompt(imp["prompt"])
        transcript = record["metadata"].get("transcript_messages") or []
        runs.append({"run": imp["run"], "prompt": imp["prompt"], "title": imp["title"],
                     "source": record["source"].get("candidate_source") or record["condition"],
                     "short": (transcript[0]["content"] if transcript else "").strip().replace("\n", " ")[:300],
                     "screening_p_eval": record["metadata"].get("screening_p_eval"),
                     "ground_truth": imp["ground_truth"], "base_label": imp["base_label"],
                     "sample_idx": imp["sample_idx"], "n_per_pos": imp["n_rollouts_per_position"],
                     "p_all": imp["p_target_all"], "p_filtered": imp["p_target_filtered"],
                     "p_forced": forced["p_eval"] if forced else None, "chunks": chunks})
    out["runs"] = runs

    out["categories"] = []
    for tag, xs in by_cat.items():
        imps = np.array([x[1] for x in xs])
        forced = np.array([x[2] for x in xs if x[2] is not None])
        out["categories"].append({
            "tag": tag, "cue": tag not in EXCLUDED_CATEGORIES, "n_chunks": len(xs),
            "n_runs": len({x[0] for x in xs}),
            "mean_imp": float(imps.mean()), "mean_abs_imp": float(np.abs(imps).mean()),
            "se_imp": float(imps.std(ddof=1) / np.sqrt(len(imps))) if len(imps) > 1 else None,
            "mean_forced": float(forced.mean()) if len(forced) else None,
            "mean_abs_forced": float(np.abs(forced).mean()) if len(forced) else None,
        })
    out["categories"].sort(key=lambda c: -c["mean_abs_imp"])

    ablation = load(RESULTS_DIR / "cue_ablation.json")
    out["ablation"] = {src: [{"variant": k, "p_eval": v["p_eval"], "n": v["n"]} for k, v in vs.items()]
                       for src, vs in (ablation or {}).items()}
    register = load(RESULTS_DIR / "register_ablation.json") or {}
    out["register"] = {name: {"ground_truth": vs["_meta"]["ground_truth"],
                              "variants": {v: {"p_eval": x["p_eval"], "n": x["n"], "text": x["text"][:600]}
                                           for v, x in vs.items() if v != "_meta"}}
                       for name, vs in register.items()}
    behavior = load(RESULTS_DIR / "behavior.json") or {}
    out["behavior"] = [{**{k: v for k, v in b.items() if k != "conditions"},
                        "conditions": {k: {kk: vv for kk, vv in c.items() if kk != "samples"} for k, c in b["conditions"].items()}}
                       for b in behavior.values()]
    screen = load(RESULTS_DIR / "behavior_screen.json") or {}
    out["behavior_screen"] = [{"id": c["id"], "source": c["source"], "p_comply": c["p_comply"], "p_refuse": c["p_refuse"],
                               "n": c["n"], "request": c["request"][:200]} for c in screen.values() if "p_comply" in c]
    out["insertion"] = [
        {k: v for k, v in load(p).items() if k != "prefix"} for p in sorted(RESULTS_DIR.glob("insertion_*.json"))
    ]
    (RESULTS_DIR / "report_data.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(f"{len(runs)} runs, {len(out['categories'])} categories, {len(out['insertion'])} insertion runs")


if __name__ == "__main__":
    main()
