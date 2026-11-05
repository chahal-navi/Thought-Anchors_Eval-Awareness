"""Build report/full_report.html: the whole project, start to finish, with every experiment's method.

Prose and tables live in report/full_body.html (numbers there were copied from the analysis JSONs listed in its
Files section); charts are drawn by report/full.js from the data packed here. The chart helpers bars() / lines() /
legend() are reused from report/overnight.js.

Lock-in is recomputed here with matched units: resampled P(EVAL)[i] is "after i sentences"; the probe at the end of
sentence j is "after j + 1 sentences", so probe index j is placed at x = j + 1.

Usage:
    python build_report_full.py
"""

import json
import re

import numpy as np

from common import CAPSTONE_DIR

RES = CAPSTONE_DIR / "results"
REPORT = CAPSTONE_DIR / "report"
NAMES = {
    "qwen": {"a102": "Largest star", "a366": "ASCII cat", "a435": "Electric Pokémon", "a451": "Godot controller",
             "a802": "Movie review", "m682": "Stages of life", "w68": "Gendry custard", "w94b": "CE/DCE pitch",
             "wacd": "Game-anchor training", "wb6a": "March Madness show"},
    "gemma": {"a272": "3×4 table variations", "a366": "ASCII cat", "a401": "Compile Python", "a96": "Spice up the bedroom",
              "m6828": "Stages of life", "w1e57": "ASUN game script", "w53b5": "Kirby Smart script", "w6902": "Reduce suffering",
              "wdd1d": "RG fixed point", "t72d0": "Female-athletes essay"},
}


def r3(x):
    return None if x is None else round(float(x), 3)


def lock_at(vals, ok):
    """First index after which ok(v) holds for every later value."""
    return next((i for i in range(len(vals)) if all(ok(v) for v in vals[i:])), len(vals))


def lockins(pr, sup):
    chunks = {r["run"]: r["chunks"] for r in sup["runs"]}
    out = []
    for b in pr["base_runs"]:
        q, p, fin = b["resampled"], b["probe"], b["label"] == "EVALUATION"
        side = lambda v: (v > 0.5) == fin
        pf = p[-1]
        row = {"run": b["run"], "label": b["label"], "resampled": [r3(x) for x in q], "probe": [r3(x) for x in p],
               "chunks": [c[:140] for c in chunks.get(b["run"], [])],
               "lock_r15": b["lock"], "lock_r50": lock_at(q, side),
               "lock_p50": lock_at(p, side) + 1, "lock_p15": lock_at(p, lambda v: abs(v - pf) <= 0.15) + 1}
        assert row["lock_r15"] == lock_at(q, lambda v: abs(v - q[-1]) <= 0.15), b["run"]
        out.append(row)
    med = lambda k: float(np.median([r[k] for r in out]))
    later = lambda a, b: int(sum(r[a] > r[b] for r in out))
    summ = {"N": float(np.median([len(r["probe"]) for r in out])), "r15": med("lock_r15"), "r50": med("lock_r50"),
            "p50": med("lock_p50"), "p15": med("lock_p15"), "later_p50_r15": later("lock_p50", "lock_r15"),
            "later_p50_r50": later("lock_p50", "lock_r50"), "later_p15_r15": later("lock_p15", "lock_r15"), "n": len(out)}
    return out, summ


def model_data(key, ov, pr, rd, sup):
    a, p = ov[key], pr[key]
    runs, summ = lockins(p, sup[key])
    for r in runs:
        r["title"] = NAMES[key].get(r["run"].split("_")[0], r["run"]) + (" · EVAL CoT" if r["run"].endswith("eval") else " · DEPLOY CoT")
    lay = a["followup"]["layers"]
    e3 = a["exp3"]
    groups = [(g, e3[g]) for g in ("last2", "opening", "kl_top3", "imp_top3", "checklist", "pre_lock", "post_lock") if g in e3]
    fu = a["followup"]["groups"]
    groups += [(g, fu[g]) for g in ("label_word", "verdict_stmt") if g in fu]
    bl = str(p["best_layer"])
    return {
        "lock_runs": runs, "lock": summ,
        "layers_window": [{"layers": x["layers"], "share": r3(x["median_share"]), "flips": x["flips"]} for x in lay["layers_window"]],
        "groups": [{"g": g, "share": r3(v["median_share"]), "random": r3(v["median_random"]), "beats": v["beats_random"], "n": v["n"],
                    "p": r3(v.get("p"))} for g, v in groups],
        "splices": {k: v["follows_tail"] for k, v in a["followup"]["splices"].items()},
        "win": rd[key]["win"], "window": rd[key]["window"], "rows": rd[key]["rows"], "all_heads": r3(rd[key]["all_heads"]),
        "probe": {"layer": int(bl), "probe": [r3(x) for x in p["by_layer"][bl]["auc_by_decile"]],
                  "bow": [r3(x) for x in p["text_baseline"]["auc_by_decile"]], "cur": [r3(x) for x in p["text_current"]["auc_by_decile"]]},
    }


def main():
    ov = json.loads((RES / "overnight_analysis.json").read_text())
    pr = json.loads((RES / "probe_analysis.json").read_text())
    sup = json.loads((RES / "suppression_analysis.json").read_text())
    import analyze_overnight as AO
    rd = {k: AO.analyse_readers(k) for k in ("qwen", "gemma")}
    data = {"models": {k: model_data(k, ov, pr, rd, sup) for k in ("gemma", "qwen")}}
    for k, m in data["models"].items():
        print(k, "lock-in medians", m["lock"])

    tpl = (REPORT / "template.html").read_text()
    ovjs = (REPORT / "overnight.js").read_text()
    helpers = ovjs[ovjs.index("/* Horizontal bars"): ovjs.index("const $ =")]
    js = helpers + (REPORT / "full.js").read_text()
    # keep the template's DATA, colours and el/txt/tip helpers; drop its old report-specific charts
    a, b = tpl.index("/* ---------- Screening strip plot"), tpl.index("__SCRIPT__") + len("__SCRIPT__")
    html = tpl[:a] + js + tpl[b:]
    html = html.replace("<title>Eval-Awareness Anchors</title>", "<title>Eval-Awareness Anchors: Full Report</title>")
    html = html.replace("__BODY__", (REPORT / "full_body.html").read_text()).replace("__DATA__", json.dumps(data, ensure_ascii=False))
    assert "__" not in re.sub(r"<script>.*?</script>", "", html, flags=re.S).replace("__init__", ""), "unfilled placeholder"
    (REPORT / "full_report.html").write_text(html)
    print("wrote", REPORT / "full_report.html", len(html) // 1024, "kB")


if __name__ == "__main__":
    main()
