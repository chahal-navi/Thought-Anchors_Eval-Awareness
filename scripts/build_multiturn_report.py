"""Multi-turn pilot report: report/multiturn.html.

Reuses report/template.html's stylesheet and run chart (runChart) so the page matches the main report.
Data: results/importance_mt_*.json (multi-turn), importance_<short>_{eval,depl}.json (single-turn
baseline for the same prompts), cots_mt_*.json (P(EVAL) over fresh two-turn conversations).

Usage:
    python build_multiturn_report.py            # prose lives in BODY below
"""

import json
import re

import numpy as np

from common import CAPSTONE_DIR, RESULTS_DIR, load_prompt
from judge import EXCLUDED_CATEGORIES

REPORT_DIR = CAPSTONE_DIR / "report"
# short name -> (multi-turn prompt, single-turn prompt)
PROMPTS = {
    "a102": ("mt_alpaca_eval_102", "probe_alpaca_eval_102"),
    "wb6a": ("mt_wildchat_natural_b6a54722", "probe_wildchat_natural_b6a54722"),
    "m682": ("mt_mt_bench_68280443", "probe_mt_bench_68280443"),
}
MIN_KEPT = 20  # anchors need this many dissimilar resamples behind both P values


def load(p):
    return json.loads(p.read_text()) if p.exists() else None


def run_record(run: str, fmt: str) -> dict | None:
    imp = load(RESULTS_DIR / f"importance_{run}.json")
    if imp is None:
        return None
    raw, kept = imp["p_target_filtered_raw"], imp["n_kept"]
    n = len(imp["chunks_labeled"])
    chunks = []
    for i, c in enumerate(imp["chunks_labeled"]):
        solid = raw[i] is not None and raw[i + 1] is not None and kept[i] >= MIN_KEPT and kept[i + 1] >= MIN_KEPT
        se = c["importance_se"]
        chunks.append({"i": i, "text": c["chunk"], "tag": c["function_tags"][0], "dir": c["eval_awareness"],
                       "imp": c["counterfactual_importance"], "se": se if se == se else None,
                       "p_all": imp["p_target_all"][i], "n_kept": kept[i], "solid": solid})
    rec = {"run": run, "fmt": fmt, "prompt": imp["prompt"], "base_label": imp["base_label"],
           "ground_truth": imp["ground_truth"], "sample_idx": imp["sample_idx"],
           "n_per_pos": imp["n_rollouts_per_position"], "unparsed": imp["unparsed_labels"],
           "p_all": imp["p_target_all"], "chunks": chunks, "title": imp["title"]}
    assert len(rec["p_all"]) == n + 1
    if fmt == "multi":
        s = load(RESULTS_DIR / f"cots_{imp['prompt']}.json")["samples"][imp["sample_idx"]]
        rec["turn1_answer"] = s["messages"][1]["content"]
    return rec


def summarize(rec: dict) -> dict:
    cs = rec["chunks"]
    sig = [c for c in cs if c["se"] and c["solid"] and abs(c["imp"]) >= 2 * c["se"]]
    top = max(cs, key=lambda c: abs(c["imp"]) if c["solid"] else -1)
    return {"run": rec["run"], "fmt": rec["fmt"], "short": rec["short"], "base_label": rec["base_label"],
            "n_chunks": len(cs), "p_start": rec["p_all"][0], "p_end": rec["p_all"][-1],
            "n_sig": len(sig), "max_abs": abs(top["imp"]), "top_i": top["i"], "top_imp": top["imp"],
            "top_text": top["text"], "top_tag": top["tag"], "top_se": top["se"]}


def main():
    data = {"prompts": [], "runs": [], "summary": [], "anchors": [], "categories": []}
    by_cat = {}
    for short, (mt, st) in PROMPTS.items():
        rec_mt = load_prompt(mt)
        samples = load(RESULTS_DIR / f"cots_{mt}.json")["samples"]
        labels = [s["label"] for s in samples]
        st_rec = load_prompt(st)
        data["prompts"].append({
            "short": short, "text": rec_mt["messages"][0]["content"], "ground_truth": rec_mt["metadata"]["ground_truth"],
            "source": st_rec["source"].get("candidate_source"),
            "p_single": st_rec["metadata"].get("screening_p_eval"),
            "p_multi": labels.count("EVALUATION") / max(1, sum(l is not None for l in labels)), "n_multi": len(labels),
        })
        for fmt, prefix in (("multi", f"mt_{short}"), ("single", short)):
            for lab in ("eval", "depl"):
                rec = run_record(f"{prefix}_{lab}", fmt)
                if rec is None:
                    continue
                rec["short"] = short
                data["runs"].append(rec)
                data["summary"].append(summarize(rec))
                for c in rec["chunks"]:
                    by_cat.setdefault((fmt, c["tag"]), []).append(c["imp"])
                    if c["solid"] and c["se"] and abs(c["imp"]) >= 2 * c["se"] and abs(c["imp"]) >= 0.2 and fmt == "multi":
                        data["anchors"].append({"run": rec["run"], "short": short, "base_label": rec["base_label"], **c})
    data["anchors"].sort(key=lambda a: -abs(a["imp"]))
    for (fmt, tag), xs in by_cat.items():
        xs = np.array(xs)
        data["categories"].append({"fmt": fmt, "tag": tag, "cue": tag not in EXCLUDED_CATEGORIES, "n": len(xs),
                                   "mean_abs": float(np.abs(xs).mean()), "mean": float(xs.mean())})

    template = (REPORT_DIR / "template.html").read_text()
    head = template[: template.index("<main>")].replace("<title>Eval-Awareness Anchors</title>", "<title>Multi-Turn Pilot</title>")
    js = template[template.index("const COLORS"): template.index("function runsSection")]
    body = (CAPSTONE_DIR / "report" / "multiturn_body.html").read_text()
    page = (head + "<main>\n" + body + "\n</main>\n<div class=\"tip\" id=\"tip\" hidden></div>\n<script>\nconst DATA = "
            + json.dumps(data, ensure_ascii=False) + ";\n" + js + "\n" + (CAPSTONE_DIR / "report" / "multiturn.js").read_text()
            + "\n</script>\n")
    out = REPORT_DIR / "multiturn.html"
    out.write_text(page)
    (RESULTS_DIR / "multiturn_report_data.json").write_text(json.dumps(data, indent=1, ensure_ascii=False))
    print(f"Saved {out} ({len(page) // 1024} KB), {len(data['runs'])} runs")
    for s in data["summary"]:
        print(f"{s['run']:<14} {s['fmt']:<6} chunks={s['n_chunks']:<3} P {s['p_start']:.2f}->{s['p_end']:.2f} sig={s['n_sig']} "
              f"top #{s['top_i']} {s['top_imp']:+.2f} [{s['top_tag']}] {s['top_text'][:80]}")


if __name__ == "__main__":
    main()
