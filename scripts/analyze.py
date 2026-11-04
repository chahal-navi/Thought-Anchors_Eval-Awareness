"""Counterfactual importance of each CoT chunk for the EVALUATION verdict, plus plots.

Follows `calculate_counterfactual_importance` from chapter4 part3 (thought anchors):
  - rollouts at position i resample chunk i onwards; keep only those whose first resampled
    chunk is dissimilar to the original (cosine sim < 0.8, all-MiniLM-L6-v2)
  - P_i = fraction of kept rollouts that end with <label>EVALUATION</label> (positions with < 5
    kept are filled from neighbours)
  - importance_i = P_{i+1} - P_i (positive: keeping chunk i makes the EVALUATION verdict more likely)
Additions: position N (whole CoT kept, no filtering) gives the last chunk a score too, and each
importance gets a binomial standard error so effects can be compared with noise.

Saves results/importance_<run>.json and results/plots/importance_<run>.png.

Usage:
    python analyze.py                                  # every results/rollouts_*.json
    python analyze.py --runs probe_mmlu probe_wildchat
"""

import argparse
import json

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sentence_transformers import SentenceTransformer

from common import RESULTS_DIR, load_prompt
from judge import CATEGORIES, split_solution_into_chunks

EMBEDDING_MODEL = "all-MiniLM-L6-v2"
SIMILARITY_THRESHOLD = 0.8
MIN_SAMPLES = 5
TARGET_LABEL = "EVALUATION"

# Fixed colour per category (dataviz reference palette, 8 slots); general/non-cue tags are neutral greys
CATEGORY_COLORS = {
    "explicit_framing": "#2a78d6",
    "task_format": "#eb6834",
    "known_benchmark": "#1baf7a",
    "problem_design": "#eda100",
    "input_authenticity": "#e87ba4",
    "scenario_realism": "#008300",
    "user_context": "#6250d6",
    "harmfulness": "#e34948",
    "meta_reasoning": "#52514e",
    "task_reasoning": "#a3a29b",
    "other": "#d5d4ce",
}
DIRECTION_MARK = {"toward_eval": " [E]", "toward_deployment": " [D]", "none": ""}

TITLES = {
    "probe_mmlu": "MMLU question (capability eval)",
    "probe_agentic": "InterCode CTF transcript (agentic eval)",
    "probe_wildchat": "WildChat question (real deployment)",
}


def binomial_se(p: float | None, n: int) -> float:
    if p is None or n == 0:
        return np.nan
    return float(np.sqrt(max(p * (1 - p), 1 / n) / n))  # floor avoids SE = 0 at p in {0, 1}


def calculate_counterfactual_importance(
    chunks: list[str],
    positions: list[list[dict]],
    target_label: str,
    embedding_model: SentenceTransformer,
    threshold: float = SIMILARITY_THRESHOLD,
    min_samples: int = MIN_SAMPLES,
) -> dict:
    n = len(chunks)
    first_resampled = [
        [(split_solution_into_chunks(r["reasoning"]) or [""])[0] for r in positions[i]] for i in range(n)
    ]
    emb_orig = embedding_model.encode(chunks, normalize_embeddings=True)

    probs, n_kept = [], []
    for i in range(n):
        emb_res = embedding_model.encode(first_resampled[i], normalize_embeddings=True)
        sims = emb_res @ emb_orig[i]
        sims[[s == "" for s in first_resampled[i]]] = 0.0  # empty resample counts as different
        kept = [r for r, s in zip(positions[i], sims) if s < threshold]
        n_kept.append(len(kept))
        probs.append(float(np.mean([r["label"] == target_label for r in kept])) if len(kept) >= min_samples else None)
    probs.append(float(np.mean([r["label"] == target_label for r in positions[n]])))  # whole CoT kept
    n_kept.append(len(positions[n]))

    probs_filled = pd.Series(probs, dtype=float).ffill().bfill().tolist()
    se = [binomial_se(p, k) for p, k in zip(probs, n_kept)]
    importance_se = [float(np.hypot(se[i], se[i + 1])) for i in range(n)]
    return {
        "importance": np.diff(probs_filled).tolist(),
        "importance_se": importance_se,
        "p_target_filtered": probs_filled,
        "p_target_filtered_raw": probs,
        "p_target_all": [float(np.mean([r["label"] == target_label for r in pos])) for pos in positions],
        "n_kept": n_kept,
    }


def plot_importance(title: str, chunks_labeled: list[dict], res: dict, out_path):
    n = len(chunks_labeled)
    tags = [c["function_tags"][0] for c in chunks_labeled]
    x = np.arange(n)

    fig, (ax_p, ax_i) = plt.subplots(
        2, 1, figsize=(max(9, 0.42 * n + 3), 8.5), sharex=True, gridspec_kw={"height_ratios": [1, 2]}
    )
    for ax in (ax_p, ax_i):
        ax.spines[["top", "right"]].set_visible(False)
        ax.spines[["left", "bottom"]].set_color("#b5b4ad")
        ax.tick_params(colors="#52514e")
        ax.grid(axis="y", color="#ecebe7", linewidth=0.8)
        ax.set_axisbelow(True)

    # Top: P(EVALUATION) when resampling from before chunk i
    ax_p.plot(x, res["p_target_all"][:n], color="#2a78d6", linewidth=2, marker="o", markersize=4,
              label="all rollouts from before chunk i")
    ax_p.plot(x, res["p_target_filtered"][:n], color="#52514e", linewidth=2, linestyle="--",
              label="rollouts where chunk i was replaced by a different sentence")
    ax_p.set_ylim(-0.03, 1.03)
    ax_p.set_ylabel("P(EVALUATION verdict)", color="#0b0b0b")
    ax_p.legend(loc="lower left", frameon=False, fontsize=8)

    # Bottom: counterfactual importance (±1 SE), coloured by category
    imp = res["importance"]
    ax_i.bar(x, imp, width=0.8, color=[CATEGORY_COLORS[t] for t in tags], edgecolor="white", linewidth=1)
    ax_i.errorbar(x, imp, yerr=np.nan_to_num(res["importance_se"]), fmt="none", ecolor="#8a8984",
                  elinewidth=0.8, capsize=0)
    ax_i.axhline(0, color="#52514e", linewidth=0.8)
    ax_i.set_ylabel("Counterfactual importance\n(Δ P(EVALUATION) from keeping chunk, ±1 SE)", color="#0b0b0b")

    # "*": P at i or i+1 had < MIN_SAMPLES dissimilar resamples and was filled from a neighbour
    raw = res["p_target_filtered_raw"]
    filled = [raw[i] is None or raw[i + 1] is None for i in range(n)]
    ax_i.set_xticks(x)
    ax_i.set_xticklabels(
        [
            f"{'* ' if filled[i] else ''}{i}  {CATEGORIES[t]}{DIRECTION_MARK[c['eval_awareness']]}"
            for i, (t, c) in enumerate(zip(tags, chunks_labeled))
        ],
        rotation=90, fontsize=8,
    )
    ax_i.set_xlabel(
        "Chunk index, judge category and direction ([E] toward eval, [D] toward deployment)\n"
        f"* = too few dissimilar resamples (< {MIN_SAMPLES}); value filled from neighbouring position",
        color="#52514e",
    )

    present = [t for t in CATEGORIES if t in tags]
    handles = [plt.Rectangle((0, 0), 1, 1, color=CATEGORY_COLORS[t]) for t in present]
    ax_i.legend(handles, [CATEGORIES[t] for t in present], loc="upper left", bbox_to_anchor=(1.0, 1.0),
                frameon=False, fontsize=8, title="Category", title_fontsize=9)

    fig.suptitle(f"Counterfactual importance per CoT chunk: {title}", fontsize=13, x=0.01, ha="left", color="#0b0b0b")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def analyze_run(run: str, embedding_model: SentenceTransformer) -> dict:
    rollouts = json.loads((RESULTS_DIR / f"rollouts_{run}.json").read_text())
    prompt = rollouts["prompt"]
    judged = json.loads((RESULTS_DIR / f"judge_{prompt}.json").read_text())
    chunks_labeled = next(s for s in judged["samples"] if s["sample_idx"] == rollouts["sample_idx"])["chunks_labeled"]
    assert [c["chunk"] for c in chunks_labeled] == rollouts["chunks"], "judge and rollout chunks differ"

    res = calculate_counterfactual_importance(rollouts["chunks"], rollouts["positions"], TARGET_LABEL, embedding_model)
    for c, imp, se, p, k in zip(chunks_labeled, res["importance"], res["importance_se"], res["p_target_all"], res["n_kept"]):
        c.update({"counterfactual_importance": imp, "importance_se": se, "p_eval_all": p, "n_kept": k})

    record = load_prompt(prompt)
    title = TITLES.get(prompt) or f"{record['source'].get('id', prompt)} ({record['condition']})"
    if run != prompt:
        title += f", base CoT #{rollouts['sample_idx']} ({rollouts['base_label']})"
    out = {
        "run": run,
        "prompt": prompt,
        "title": title,
        "target_label": TARGET_LABEL,
        "ground_truth": rollouts["ground_truth"],
        "sample_idx": rollouts["sample_idx"],
        "base_label": rollouts["base_label"],
        "n_rollouts_per_position": len(rollouts["positions"][0]),
        "n_rollouts_total": sum(len(p) for p in rollouts["positions"]),
        "unparsed_labels": sum(r["label"] is None for pos in rollouts["positions"] for r in pos),
        **res,
        "chunks_labeled": chunks_labeled,
    }
    (RESULTS_DIR / f"importance_{run}.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    plot_path = RESULTS_DIR / "plots" / f"importance_{run}.png"
    plot_importance(title, chunks_labeled, res, plot_path)
    p = res["p_target_all"]
    print(f"{run}: P(EVAL) start={p[0]:.2f} end={p[-1]:.2f} range=[{min(p):.2f}, {max(p):.2f}]; saved {plot_path}")
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", nargs="+", help="run names (default: every results/rollouts_*.json)")
    args = parser.parse_args()
    runs = args.runs or sorted(p.stem.removeprefix("rollouts_") for p in RESULTS_DIR.glob("rollouts_*.json"))

    embedding_model = SentenceTransformer(EMBEDDING_MODEL)
    (RESULTS_DIR / "plots").mkdir(exist_ok=True)
    for run in runs:
        analyze_run(run, embedding_model)


if __name__ == "__main__":
    main()
