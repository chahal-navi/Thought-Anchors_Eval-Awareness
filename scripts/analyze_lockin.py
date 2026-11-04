"""Compare deployment-leaning insertions before lock-in (insertion.py) and after it (insertion_lockin.py).

For each run and each of the 5 deployment-leaning sentences:
  effect     = P(EVAL | sentence) - P(EVAL | control sentence) at the same cut
  rel_effect = effect / P(EVAL | control): share of the available drop that the sentence achieves
               (before lock-in the control sits near 0.5, after it near 1, so raw effects understate "before")

Usage:
    SUBJECT=gemma python analyze_lockin.py      # or without SUBJECT for Qwen
"""

import json
import statistics as st

from common import RESULTS_DIR, SUBJECT


def rows(insertions):
    ctl = next(x["p_eval"] for x in insertions if x["category"] == "control")
    return ctl, {x["category"]: x["p_eval"] for x in insertions if x["direction"] == "toward_deployment"}


def main():
    before_all = {r["run"]: r for r in json.loads((RESULTS_DIR / "report_data.json").read_text())["insertion"]}
    out, per_run = {}, []
    for path in sorted(RESULTS_DIR.glob("insertion_lockin_*.json")):
        after = json.loads(path.read_text())
        run = after["run"]
        if "lock+2" not in after["positions"] or run not in before_all:
            continue
        b_ctl, b = rows(before_all[run]["insertions"])
        a_ctl, a = rows(after["positions"]["lock+2"]["insertions"])
        for cat in b:
            if a.get(cat) is None:
                continue
            per_run.append({
                "run": run, "category": cat,
                "before_cut": before_all[run]["insert_before_chunk"], "after_cut": after["positions"]["lock+2"]["insert_before_chunk"],
                "lock": after["lock"], "n_chunks": after["n_chunks"],
                "before_ctl": b_ctl, "after_ctl": a_ctl,
                "before_effect": b[cat] - b_ctl, "after_effect": a[cat] - a_ctl,
                "before_rel": (b[cat] - b_ctl) / b_ctl if b_ctl else None,
                "after_rel": (a[cat] - a_ctl) / a_ctl if a_ctl else None,
            })
    runs = sorted({r["run"] for r in per_run})
    print(f"{SUBJECT}: {len(runs)} runs, {len(per_run)} run x sentence pairs")
    print(f"{'run':12s} {'cut b/a':>8s} {'lock':>7s} {'ctl b/a':>10s} {'mean effect b -> a':>20s}")
    for run in runs:
        rs = [r for r in per_run if r["run"] == run]
        print(f"{run:12s} {rs[0]['before_cut']:>3d}/{rs[0]['after_cut']:<4d} {rs[0]['lock']:>3d}/{rs[0]['n_chunks']:<3d} "
              f"{rs[0]['before_ctl']:.2f}/{rs[0]['after_ctl']:.2f}   {st.mean(r['before_effect'] for r in rs):+.2f} -> {st.mean(r['after_effect'] for r in rs):+.2f}")
    summary = {}
    for cat in ["all"] + sorted({r["category"] for r in per_run}):
        rs = [r for r in per_run if cat in ("all", r["category"])]
        rel_b = [r["before_rel"] for r in rs if r["before_rel"] is not None]
        rel_a = [r["after_rel"] for r in rs if r["after_rel"] is not None]
        summary[cat] = {
            "n": len(rs),
            "before_effect": st.mean(r["before_effect"] for r in rs), "after_effect": st.mean(r["after_effect"] for r in rs),
            "before_rel": st.mean(rel_b), "after_rel": st.mean(rel_a),
            "smaller_after": sum(abs(r["after_effect"]) < abs(r["before_effect"]) for r in rs),
            "smaller_after_rel": sum(abs(r["after_rel"]) < abs(r["before_rel"]) for r in rs if r["before_rel"] is not None and r["after_rel"] is not None),
        }
        s = summary[cat]
        print(f"  {cat:18s} n={s['n']:2d}  effect {s['before_effect']:+.2f} -> {s['after_effect']:+.2f}  "
              f"share of drop {s['before_rel']:+.2f} -> {s['after_rel']:+.2f}  "
              f"smaller after: {s['smaller_after']}/{s['n']} (raw), {s['smaller_after_rel']}/{s['n']} (share)")
    out = {"subject": SUBJECT, "summary": summary, "per_run": per_run}
    (RESULTS_DIR / "lockin_analysis.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
