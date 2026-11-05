"""Slide figure: does late text in the CoT still move the answer? Two tests, two panels (different units).

Left  (black box, resampling): mean drop in P(EVAL) from a planted deployment-leaning sentence vs a neutral control,
      before lock-in (just before the first cue sentence) and after it (lock-in + 2). Same EVAL CoTs at both points.
Right (white box, teacher-forced): CoT A with its last m sentences replaced by the last m sentences of B, the other
      CoT for the same prompt with the opposite verdict; share of the 20 CoTs whose answer follows B's ending.

Usage:
    python plot_slide_start_end.py   -> report/plots_lockin/slide_start_vs_end.png
"""

import json

import matplotlib.pyplot as plt
import numpy as np

from common import CAPSTONE_DIR
from plot_lockin_slide import MODELS, boot_ci, per_run

RES = CAPSTONE_DIR / "results"
OUT = CAPSTONE_DIR / "report" / "plots_lockin"
GRAY, BLUE, INK, INK2 = "#8a909c", "#2456d8", "#1b1f27", "#5b6270"
ORANGE = ["#f3b57a", "#e07b26", "#a64d0c"]  # one hue, light -> dark = 1 -> 3 sentences swapped
KEYS = {"Gemma 4 26B-A4B": "gemma", "Qwen3-32B": "qwen"}


def style(ax, ylabel, ymax):
    ax.set_ylim(0, ymax)
    ax.set_ylabel(ylabel, color=INK2, fontsize=13)
    ax.tick_params(axis="y", colors=INK2, length=0, labelsize=12)
    ax.tick_params(axis="x", length=0, pad=8)
    ax.grid(axis="y", color="#e6e8ec", zorder=0)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color("#b9bec7")


def main():
    OUT.mkdir(exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans"})
    ov = json.loads((RES / "overnight_analysis.json").read_text())
    fig, (axL, axR) = plt.subplots(1, 2, figsize=(14, 7.2), gridspec_kw={"wspace": 0.28})

    # left: planting
    w = 0.36
    for i, (name, d) in enumerate(MODELS):
        runs = per_run(d)
        for j, col in enumerate((GRAY, BLUE)):
            vals = np.concatenate([v[j] for v in runs.values()])
            m, (lo, hi) = vals.mean() * 100, boot_ci(runs, j) * 100
            x = i + (j - 0.5) * (w + 0.04)
            axL.bar(x, m, w, color=col, zorder=2, label=("Before lock-in", "After lock-in")[j] if i == 0 else None)
            axL.errorbar(x, m, yerr=[[m - lo], [hi - m]], color=INK, lw=1.3, capsize=4, zorder=3)
            axL.text(x, hi + 2, f"{m:.0f}", ha="center", va="bottom", fontsize=19, fontweight="bold", color=INK)
    axL.set_xticks([0, 1], [n.split()[0] for n, _ in MODELS], fontsize=16, color=INK)
    axL.set_xlim(-0.6, 1.6)
    style(axL, "Drop in P(EVAL), percentage points", 75)
    axL.legend(loc="upper left", frameon=False, fontsize=12.5, ncol=2, bbox_to_anchor=(0, 1.0))
    axL.set_title("Plant a “looks like real use” sentence", loc="left", fontsize=16, fontweight="bold", color=INK, pad=12)

    # right: splices
    w = 0.26
    for i, (name, _) in enumerate(MODELS):
        sp = ov[KEYS[name]]["followup"]["splices"]
        for j, m in enumerate((1, 2, 3)):
            v = sp[f"tail_{m}"]
            pct = 100 * v["follows_tail"] / v["n"]
            x = i + (j - 1) * (w + 0.03)
            axR.bar(x, pct, w, color=ORANGE[j], zorder=2, label=f"last {m}" if i == 0 else None)
            axR.text(x, pct + 2, f"{v['follows_tail']}/{v['n']}", ha="center", va="bottom", fontsize=15, fontweight="bold", color=INK)
        print(name, {m: sp[f"tail_{m}"]["follows_tail"] for m in (1, 2, 3)})
    axR.set_xticks([0, 1], [n.split()[0] for n, _ in MODELS], fontsize=16, color=INK)
    axR.set_xlim(-0.6, 1.6)
    axR.axhline(50, color="#9aa0aa", lw=1, ls=(0, (4, 3)), zorder=1)
    style(axR, "CoTs whose answer follows the new ending (%)", 125)
    axR.set_yticks([0, 25, 50, 75, 100])
    axR.legend(loc="upper left", frameon=False, fontsize=12.5, ncol=3, bbox_to_anchor=(0, 1.0), title="Sentences swapped in:",
               title_fontsize=12.5, alignment="left")
    axR.set_title("Swap in the ending of an opposite-verdict CoT", loc="left", fontsize=16, fontweight="bold", color=INK, pad=12)

    fig.suptitle("Gemma's answer is fixed early; Qwen's answer follows how its CoT ends", x=0.06, y=0.985, ha="left",
                 fontsize=21, fontweight="bold", color=INK)
    fig.text(0.06, 0.012,
             "Left: resampling (black box). Same EVAL CoTs and 5 deployment-leaning sentences at both points (Gemma 10 CoTs, Qwen 8); "
             "before = just before the first cue sentence,\nafter = 2 sentences after lock-in; drop vs a neutral control at the same cut, "
             "20–30 resamples each; whiskers = 95% bootstrap CI over CoTs.\nRight: teacher-forced (white box). Each of 20 CoTs gets the last 1–3 "
             "sentences of the other CoT for the same prompt, which reached the opposite verdict.\nThe two panels use different units: compare bars within a panel.",
             fontsize=10, color=INK2, va="bottom")
    fig.subplots_adjust(left=0.06, right=0.99, top=0.86, bottom=0.22)
    path = OUT / "slide_start_vs_end.png"
    fig.savefig(path, dpi=200, facecolor="white")
    print("wrote", path)


if __name__ == "__main__":
    main()
