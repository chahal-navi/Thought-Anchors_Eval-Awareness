"""Slide figure: how much a planted deployment-leaning sentence lowers P(EVAL), before vs after lock-in.

Before = insertion.py (planted just before the first cue-tagged sentence); after = insertion_lockin.py (lock-in + 2).
Same EVAL base CoTs and the same 5 deployment-leaning sentences at both points. Bar = mean drop in P(EVAL) vs the
neutral control at the same cut, over run x sentence pairs; whisker = 95% bootstrap CI over runs.

Usage:
    python plot_lockin_slide.py   -> report/plots_lockin/slide_lockin_planting.png
"""

import json

import matplotlib.pyplot as plt
import numpy as np

from common import CAPSTONE_DIR

RES = CAPSTONE_DIR / "results"
OUT = CAPSTONE_DIR / "report" / "plots_lockin"
MODELS = [("Gemma 4 26B-A4B", RES / "gemma"), ("Qwen3-32B", RES)]
GRAY, BLUE, INK, INK2 = "#8a909c", "#2456d8", "#1b1f27", "#5b6270"


def per_run(d):
    """{run: (before effects, after effects)} for the deployment-leaning sentences, as positive drops."""
    out = {}
    for f in sorted(d.glob("insertion_lockin_*_eval.json")):
        run = f.stem.replace("insertion_lockin_", "")
        before = json.loads((d / f"insertion_{run}.json").read_text())["insertions"]
        after = json.loads(f.read_text())["positions"]["lock+2"]["insertions"]
        pick = lambda xs: {x["category"]: -x["effect_vs_control"] for x in xs if x["direction"] == "toward_deployment"}
        b, a = pick(before), pick(after)
        keys = sorted(set(b) & set(a))
        out[run] = (np.array([b[k] for k in keys]), np.array([a[k] for k in keys]))
    return out


def boot_ci(runs, idx, n=5000, seed=0):
    rng = np.random.default_rng(seed)
    vals = [runs[r][idx] for r in runs]
    means = [np.concatenate([vals[i] for i in rng.integers(0, len(vals), len(vals))]).mean() for _ in range(n)]
    return np.percentile(means, [2.5, 97.5])


def main():
    OUT.mkdir(exist_ok=True)
    plt.rcParams.update({"font.size": 15, "font.family": "DejaVu Sans"})
    fig, ax = plt.subplots(figsize=(12, 6.75))
    w, gap = 0.36, 0.04
    for i, (name, d) in enumerate(MODELS):
        runs = per_run(d)
        b = np.concatenate([v[0] for v in runs.values()])
        a = np.concatenate([v[1] for v in runs.values()])
        smaller = int(np.sum(np.abs(a) < np.abs(b)))  # same rule as analyze_lockin.py
        for j, (vals, col, lab) in enumerate([(b, GRAY, "Before lock-in"), (a, BLUE, "After lock-in")]):
            x = i + (j - 0.5) * (w + gap)
            m = vals.mean()
            lo, hi = boot_ci(runs, j)
            ax.bar(x, m * 100, w, color=col, label=lab if i == 0 else None, zorder=2)
            ax.errorbar(x, m * 100, yerr=[[m * 100 - lo * 100], [hi * 100 - m * 100]], color=INK, lw=1.4, capsize=5, zorder=3)
            ax.text(x, hi * 100 + 2, f"{m * 100:.0f}", ha="center", va="bottom", fontsize=22, fontweight="bold", color=INK)
        ax.text(i, -9, f"smaller after lock-in in {smaller} of {len(b)} cases", ha="center", va="top", fontsize=13, color=INK2)
        print(name, f"before {b.mean():.3f} after {a.mean():.3f} smaller {smaller}/{len(b)} runs {len(runs)}")
    ax.set_xticks([0, 1], [n for n, _ in MODELS], fontsize=18, color=INK)
    ax.tick_params(axis="x", length=0, pad=10)
    ax.set_ylim(0, 70)
    ax.set_xlim(-0.6, 1.6)
    ax.set_yticks([0, 20, 40, 60])
    ax.set_ylabel("Drop in P(EVAL), percentage points", color=INK2)
    ax.tick_params(axis="y", colors=INK2, length=0)
    ax.grid(axis="y", color="#e6e8ec", zorder=0)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color("#b9bec7")
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2, frameon=False, fontsize=15)
    ax.set_title("A planted “this looks like real use” sentence\nstops working after lock-in in Gemma, only partly in Qwen",
                 loc="left", fontsize=20, fontweight="bold", color=INK, pad=52)
    fig.text(0.01, 0.015, "Same EVAL CoTs and 5 deployment-leaning sentences at both points (Gemma 10 CoTs, Qwen 8). Before = just before the first "
             "cue sentence;\nafter = 2 sentences after lock-in. Drop vs a neutral control sentence at the same cut, 20–30 resamples each. "
             "Whiskers: 95% bootstrap CI over CoTs.", fontsize=10.5, color=INK2, va="bottom")
    fig.tight_layout(rect=(0, 0.1, 1, 1))
    path = OUT / "slide_lockin_planting.png"
    fig.savefig(path, dpi=200, facecolor="white")
    print("wrote", path)


if __name__ == "__main__":
    main()
