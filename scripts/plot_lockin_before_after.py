"""Planted-sentence effect before vs after lock-in, per planted sentence, both models.

Before: insertion.py (12 sentences planted just before the first cue-tagged chunk, i.e. before the CoT starts
weighing evidence). After: insertion_lockin.py (the 5 deployment-leaning sentences planted at lock-in + 2).
Same EVAL base CoTs for both (the runs that have lock-in data). Effect = P(EVAL | sentence) - P(EVAL | control)
at the same cut. Eval-leaning sentences were only planted before lock-in.

Usage:
    python plot_lockin_before_after.py   -> report/plots_lockin/4_before_vs_after_all_sentences.png
"""

import json

import matplotlib.pyplot as plt
import numpy as np

from common import CAPSTONE_DIR

RES = CAPSTONE_DIR / "results"
OUT = CAPSTONE_DIR / "report" / "plots_lockin"
MODELS = {"gemma": ("Gemma 4 26B-A4B", RES / "gemma"), "qwen": ("Qwen3-32B", RES)}
NICE = {"task_format": "Task format", "known_benchmark": "Known benchmark", "problem_design": "Problem design",
        "user_context": "User context", "scenario_realism": "Scenario realism", "meta_reasoning": "Meta reasoning"}
GRAY, BLUE, INK, INK2 = "#7b8190", "#2456d8", "#1b1f27", "#5b6270"


def load(d):
    rows, ctrl_b, ctrl_a, runs = {}, [], [], []
    for f in sorted(d.glob("insertion_lockin_*_eval.json")):
        run = f.stem.replace("insertion_lockin_", "")
        before = json.loads((d / f"insertion_{run}.json").read_text())
        after = json.loads(f.read_text())["positions"]["lock+2"]
        runs.append(run)
        for when, src in (("before", before), ("after", after)):
            for x in src["insertions"]:
                if x["direction"] == "none":
                    (ctrl_b if when == "before" else ctrl_a).append(x["p_eval"])
                    continue
                rows.setdefault((x["direction"], x["category"]), {"before": [], "after": []})[when].append(x["effect_vs_control"])
    return rows, runs, float(np.mean(ctrl_b)), float(np.mean(ctrl_a))


def main():
    OUT.mkdir(exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(15, 6.6), sharey=True)
    for ax, (key, (name, d)) in zip(axes, MODELS.items()):
        rows, runs, cb, ca = load(d)
        order = sorted([k for k in rows if k[0] == "toward_deployment"], key=lambda k: k[1]) + \
                sorted([k for k in rows if k[0] == "toward_eval"], key=lambda k: k[1])
        for y, k in enumerate(order):
            b, a = rows[k]["before"], rows[k]["after"]
            rng = np.random.default_rng(y)
            ax.scatter(b, y + rng.uniform(-0.12, 0.12, len(b)), s=12, color=GRAY, alpha=0.35, lw=0, zorder=2)
            if a:
                ax.scatter(a, y + rng.uniform(-0.12, 0.12, len(a)), s=12, color=BLUE, alpha=0.35, lw=0, zorder=2)
                ax.plot([np.mean(b), np.mean(a)], [y, y], color="#c9cdd6", lw=2, zorder=1)
                ax.scatter(np.mean(a), y, s=80, color=BLUE, zorder=4, edgecolor="white", lw=1.5)
            ax.scatter(np.mean(b), y, s=80, color=GRAY, zorder=4, edgecolor="white", lw=1.5)
            txt = f"{np.mean(b):+.2f} → {np.mean(a):+.2f}" if a else f"{np.mean(b):+.2f} → not tested"
            ax.text(1.02, y, txt, ha="left", va="center", fontsize=9.5, color=INK if a else INK2,
                    transform=ax.get_yaxis_transform())
        nd = sum(k[0] == "toward_deployment" for k in order)
        ax.axhline(nd - 0.5, color="#d5d8de", lw=1)
        ax.axvline(0, color="#9aa0aa", lw=1, zorder=0)
        ax.set_yticks(range(len(order)), [("→ DEPLOY · " if k[0] == "toward_deployment" else "→ EVAL · ") + NICE[k[1]] for k in order])
        ax.set_xlim(-1.05, 0.65)
        ax.text(1.02, -0.75, "before → after", ha="left", va="bottom", fontsize=9, color=INK2, transform=ax.get_yaxis_transform())
        ax.set_ylim(len(order) - 0.5, -0.7)
        ax.set_xlabel("Effect on P(EVAL) vs the neutral control sentence at the same cut")
        ax.set_title(f"{name} · {len(runs)} EVAL base CoTs\ncontrol P(EVAL): {cb:.0%} before, {ca:.0%} after lock-in",
                     loc="left", fontsize=11.5, color=INK)
        ax.grid(axis="x", color="#eceef2", lw=1)
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.tick_params(length=0, colors=INK2)
        print(name, runs)
    handles = [plt.Line2D([], [], marker="o", ls="", color=GRAY, ms=8, label="Before lock-in (just before the first cue sentence)"),
               plt.Line2D([], [], marker="o", ls="", color=BLUE, ms=8, label="After lock-in (lock-in + 2)")]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.01, 0.995), ncol=2, frameon=False, fontsize=10)
    fig.suptitle("Planted sentences before vs after lock-in (large dot = mean over runs, small dots = single runs)",
                 x=0.01, y=0.94, ha="left", fontsize=10, color=INK2)
    fig.tight_layout(rect=(0, 0, 1, 0.9), w_pad=9)
    path = OUT / "4_before_vs_after_all_sentences.png"
    fig.savefig(path, dpi=160, facecolor="white")
    print("wrote", path)


if __name__ == "__main__":
    main()
