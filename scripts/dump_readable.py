"""Write human-readable Markdown views of the results to results/readable/.

  <run>.md         base CoT sentence by sentence (judge tag, direction, importance, P(EVAL)), then for
                   every position a few example rollouts: the sentence that replaced chunk i and the verdict
  screening.md     every screened prompt with P(EVAL) and two full example CoTs
  cue_ablation.md  each transcript variant with P(EVAL) and one example CoT
  insertion.md     every inserted sentence, its effect, and one example continuation

Usage:
    python dump_readable.py
"""

import json

from common import CANDIDATES_PATH, RESULTS_DIR, load_prompt
from judge import split_solution_into_chunks

OUT = RESULTS_DIR / "readable"
EXAMPLES_PER_POSITION = 3


def quote(text: str) -> str:
    return "\n".join("> " + line for line in text.strip().splitlines()) or "> (empty)"


def dump_run(run: str):
    imp = json.loads((RESULTS_DIR / f"importance_{run}.json").read_text())
    roll = json.loads((RESULTS_DIR / f"rollouts_{run}.json").read_text())
    record = load_prompt(imp["prompt"])
    lines = [f"# {imp['title']}", "",
             f"- run `{run}`, prompt `{imp['prompt']}`, ground truth **{imp['ground_truth']}**, "
             f"base CoT #{imp['sample_idx']} said **{imp['base_label']}**",
             f"- {len(roll['chunks'])} chunks x {imp['n_rollouts_per_position']} rollouts per position", "",
             "## Probe prompt shown to the model", "", "```", record["messages"][-1]["content"], "```", "",
             "## Base CoT, sentence by sentence", "",
             "Importance = P(EVAL) with the sentence kept minus P(EVAL) when it is replaced (dissimilar resamples). "
             "`P before` = P(EVAL) over all rollouts resampled from just before the sentence.", "",
             "| # | sentence | category | direction | importance ± SE | P before | kept |",
             "|---|---|---|---|---|---|---|"]
    for i, c in enumerate(imp["chunks_labeled"]):
        lines.append(f"| {i} | {c['chunk'].replace('|', '/')} | {c['function_tags'][0]} | {c['eval_awareness']} | "
                     f"{c['counterfactual_importance']:+.2f} ± {c['importance_se']:.2f} | {c['p_eval_all']:.2f} | {c['n_kept']} |")
    lines += ["", "## Example rollouts per position", ""]
    for i, pos in enumerate(roll["positions"]):
        orig = roll["chunks"][i] if i < len(roll["chunks"]) else "(end of CoT: nothing resampled)"
        p = sum(r["label"] == "EVALUATION" for r in pos) / len(pos)
        lines += [f"### Position {i}: P(EVAL) = {p:.2f}", "", f"Original sentence: *{orig}*", ""]
        for r in pos[:EXAMPLES_PER_POSITION]:
            first = (split_solution_into_chunks(r["reasoning"]) or [""])[0]
            lines += [f"- **{r['label']}**: replaced by *{first[:300]}*"]
        lines.append("")
    lines += ["## One full rollout from the empty prefix (position 0)", "", quote(roll["positions"][0][0]["reasoning"]),
              "", "Answer:", "", quote(roll["positions"][0][0]["text"])]
    (OUT / f"{run}.md").write_text("\n".join(lines))


def dump_screening():
    screening = json.loads((RESULTS_DIR / "screening.json").read_text())
    candidates = {c["id"]: c for c in json.loads(CANDIDATES_PATH.read_text())}
    lines = ["# Screening: 57 candidates x 20 samples", ""]
    for r in sorted(screening.values(), key=lambda r: abs(r["p_eval"] - 0.5)):
        c = candidates[r["id"]]
        lines += [f"## {r['id']} ({r['source']}): truth {r['ground_truth']}, P(EVAL) = {r['p_eval']:.2f} (n={r['n']})", "",
                  "Transcript (last message):", "", quote(c["messages"][-1]["content"] or "")[:3000], ""]
        for s in r["samples"][:2]:
            lines += [f"**Example CoT -> {s['label']}**", "", quote(s["reasoning"] or ""), ""]
    (OUT / "screening.md").write_text("\n".join(lines))


def dump_ablation():
    ablation = json.loads((RESULTS_DIR / "cue_ablation.json").read_text())
    lines = ["# Cue ablation: transcript variants x 20 samples", ""]
    for src, vs in ablation.items():
        for name, v in vs.items():
            msgs = v["transcript"]["messages"]
            lines += [f"## {src} / {name}: P(EVAL) = {v['p_eval']:.2f} (n={v['n']})", "",
                      "First user message of the variant:", "",
                      quote(next(m["content"] for m in msgs if m["role"] == "user"))[:2000], "",
                      f"**Example CoT -> {v['samples'][0]['label']}**", "", quote(v["samples"][0]["reasoning"] or ""), ""]
    (OUT / "cue_ablation.md").write_text("\n".join(lines))


def dump_insertion():
    lines = ["# Cue insertion", "",
             "Each sentence is inserted into the base CoT before its first cue chunk; 30 continuations each.", ""]
    for path in sorted(RESULTS_DIR.glob("insertion_*.json")):
        d = json.loads(path.read_text())
        lines += [f"## {d['run']} (inserted before chunk {d['insert_before_chunk']})", "",
                  "Prefix the sentence is appended to:", "", quote(d["prefix"]), "",
                  f"P(EVAL) resampling from the same point with no insertion: {d['p_eval_at_cut_no_insertion']:.2f}", "",
                  "| category | direction | inserted sentence | P(EVAL) | vs control |", "|---|---|---|---|---|"]
        for x in d["insertions"]:
            lines.append(f"| {x['category']} | {x['direction']} | {x['sentence']} | {x['p_eval']:.2f} | {x['effect_vs_control']:+.2f} |")
        lines.append("")
    (OUT / "insertion.md").write_text("\n".join(lines))


def main():
    OUT.mkdir(exist_ok=True)
    for path in sorted(RESULTS_DIR.glob("importance_*.json")):
        dump_run(path.stem.removeprefix("importance_"))
    dump_screening()
    dump_ablation()
    dump_insertion()
    print(f"wrote {len(list(OUT.glob('*.md')))} files to {OUT}")


if __name__ == "__main__":
    main()
