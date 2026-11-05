"""Morning report for the overnight white-box experiments -> report/overnight.html.

Reads results/overnight_analysis.json (analyze_overnight.py) and results/probe_analysis.json (analyze_probe.py).
Charts are drawn in the page from those numbers; the narrative text is in NARRATIVE below (written after
looking at the results).

Usage:
    python build_report_overnight.py
"""

import json

from common import CAPSTONE_DIR

RES = CAPSTONE_DIR / "results"
REPORT_DIR = CAPSTONE_DIR / "report"
NAMES = {"gemma": "Gemma 4 26B-A4B", "qwen": "Qwen3-32B"}
EXP2 = [("cot_all", "Whole CoT, hidden from every later token"), ("user_and_cot_answer_only", "User prompt + CoT, hidden from the answer"),
        ("user", "User prompt, hidden from every later token"), ("user_answer_only", "User prompt, hidden from the answer only"),
        ("user_q1", "User prompt, 1st quarter"), ("user_q2", "User prompt, 2nd quarter"), ("user_q3", "User prompt, 3rd quarter"),
        ("user_q4", "User prompt, last quarter")]
EXP3 = [("last2", "Last 2 sentences"), ("opening", "First 2 sentences"), ("kl_top3", "Top-3 causal-graph anchors"),
        ("imp_top3", "Top-3 resampling importance"), ("checklist", "Checklist lines (defs + questions)"),
        ("pre_lock", "All sentences before lock-in"), ("post_lock", "Sentences after lock-in (minus last 2)")]


def r3(x):
    return None if x is None else round(float(x), 3)


def model_data(k, ov, pr):
    a = ov[k]
    d = {"name": NAMES[k]}
    d["exp2"] = [{"key": c, "label": lab, "share": r3(a["exp2"][c]["median_share"]), "flips": a["exp2"][c]["flips"],
                  "per_run": {r: r3(v) for r, v in a["exp2"][c]["per_run"].items()}} for c, lab in EXP2 if c in a["exp2"]]
    d["exp3"] = [{"key": g, "label": lab, "share": r3(a["exp3"][g]["median_share"]), "random": r3(a["exp3"][g]["median_random"]),
                  "beats": a["exp3"][g]["beats_random"], "n": a["exp3"][g]["n"], "p": a["exp3"][g]["p"], "size": r3(a["exp3"][g]["mean_size"])}
                 for g, lab in EXP3 if g in a["exp3"]]
    d["curves"] = {kind: [{"f": c["f"], "m": r3(c["median"]), "q25": r3(c.get("q25")), "q75": r3(c.get("q75"))} for c in cv if c["median"] is not None]
                   for kind, cv in a["curves"].items()}
    e = a["exp6"]
    d["exp6"] = {"layers": e["layers"], "n_layers": e["n_layers"], "r": r3(e["split_half_r"]), "dlo": {k2: r3(v) for k2, v in e["mean_abs_dlo"].items()},
                 "rho_imp": r3(e["rho_receiver_score_vs_importance"]), "rho_anchor": r3(e["rho_receiver_score_vs_anchor"]),
                 "groups": {g: {k2: r3(v) for k2, v in x.items()} for g, x in e["groups"].items()}}
    if "followup" in a:
        f = a["followup"]
        d["fu"] = {"splices": f["splices"], "groups": f["groups"],
                   "answer_only": {k2: v for k2, v in f["answer_only"].items() if k2 != "per_run"},
                   "layers": f["layers"]}
    if "readers" in a:
        d["readers"] = a["readers"]
    if k in pr:
        p = pr[k]
        bl = str(p["best_layer"])
        d["probe"] = {"best_layer": p["best_layer"], "layers": p["layers"], "n": p["n_samples"],
                      "by_layer": {l: {"deciles": [r3(x) for x in v["auc_by_decile"]], "within": [r3(x) for x in v["within_by_decile"]],
                                       "answer": r3(v["auc_answer"]), "all": r3(v["auc_all"])} for l, v in p["by_layer"].items()},
                      "best": [r3(x) for x in p["by_layer"][bl]["auc_by_decile"]],
                      "text_prefix": [r3(x) for x in p["text_baseline"]["auc_by_decile"]],
                      "text_current": [r3(x) for x in p["text_current"]["auc_by_decile"]],
                      "base_runs": [{"run": b["run"], "label": b["label"], "probe": [r3(x) for x in b["probe"]], "resampled": [r3(x) for x in b["resampled"]],
                                     "lock": b["lock"], "probe_lock": b["probe_lock"], "rho": r3(b["rho"])} for b in p["base_runs"]],
                      "fresh": p.get("fresh")}
    return d


def f2(x):
    return ("+" if x >= 0 else "−") + f"{abs(x):.2f}"


def pv(p):
    return "p < 0.001" if p < 0.001 else f"p = {p:.3f}" if p < 0.1 else f"p = {p:.2f}"


def tile(num, text):
    return f'<div class="finding"><div class="num">{num}</div><p>{text}</p></div>'


def narrative(ov, pr):
    q, g = ov["qwen"], ov["gemma"]
    q2, g2 = q["exp2"], g["exp2"]
    q3, g3 = q["exp3"], g["exp3"]
    qf, gf = q["followup"], g["followup"]
    qs, gs = qf["splices"], gf["splices"]
    qp, gp = pr["qwen"], pr["gemma"]
    med = lambda v: float(sorted(v)[len(v) // 2]) if len(v) % 2 else (sorted(v)[len(v) // 2 - 1] + sorted(v)[len(v) // 2]) / 2
    pl = {k: (med([b["lock"] for b in pr[k]["base_runs"]]), med([b["probe_lock"] for b in pr[k]["base_runs"]]),
              sum(b["probe_lock"] > b["lock"] for b in pr[k]["base_runs"])) for k in pr}
    dec = lambda k, kind, i: pr[k][kind]["auc_by_decile"][i] if kind != "probe" else pr[k]["by_layer"][str(pr[k]["best_layer"])]["auc_by_decile"][i]
    lw = {k: {x["layers"]: x["median_share"] for x in ov[k]["followup"]["layers"]["layers_window"]} for k in ov}
    lf = {k: {x["layers"]: x["median_share"] for x in ov[k]["followup"]["layers"]["layers_from"]} for k in ov}
    lu = {k: {x["layers"]: x["median_share"] for x in ov[k]["followup"]["layers"]["layers_upto"]} for k in ov}
    N = {}
    N["TILES"] = "".join([
        tile(f"{f2(g2['cot_all']['median_share'])} / {f2(q2['cot_all']['median_share'])}",
             f"Share of the verdict margin removed when the answer cannot see the CoT (Gemma / Qwen). Verdict flipped in {g2['cot_all']['flips']} / {q2['cot_all']['flips']} of 20 runs."),
        tile(f"{qs['tail_1']['follows_tail']}/20",
             f"Qwen runs where swapping in <b>only the last sentence</b> of the opposite-verdict CoT flips the answer. Gemma needs the last quarter swapped ({gs['frac_0.75']['follows_tail']}/20 flip; last sentence alone: {gs['tail_1']['follows_tail']}/20)."),
        tile("15–22 · 40–56", "Layers where the answer reads the CoT (Gemma of 30 · Qwen of 64). Hiding the CoT from the answer in only these layers removes most of the margin; anywhere else, almost nothing. Inside them, it is spread over dozens of heads."),
        tile("≈ random", "Receiver heads (the paper's broadcast heads) replicate (split-half r ≥ 0.84), but hiding sentences in only those heads moves the verdict no more than 20 random heads. They sit at or after the read-out layers."),
        tile(f"{dec('gemma', 'probe', 2):.2f} vs {dec('gemma', 'text_baseline', 2):.2f}",
             f"Gemma, 30% into the CoT: AUC of a residual-stream probe for the final verdict vs a bag-of-words on the text so far. For Gemma the words always win; for Qwen the two are tied in cross-validation, with the probe slightly ahead on fresh CoTs."),
        tile(f"{pl['gemma'][0]:.0f} vs {pl['gemma'][1]:.0f}",
             f"Gemma's median lock-in sentence by resampling vs by the probe. The future text is settled long before the verdict shows up linearly in the activations (Qwen: {pl['qwen'][0]:.0f} vs {pl['qwen'][1]:.0f})."),
    ])
    N["STORY"] = "".join(f"<li>{x}</li>" for x in [
        f"<b>The verdict is carried by the CoT text, not by the prompt directly.</b> Hide the CoT from the answer and the verdict goes to roughly 50/50 "
        f"(Qwen {f2(q2['cot_all']['median_share'])}, Gemma {f2(g2['cot_all']['median_share'])}; Gemma reaches {f2(g2['user_and_cot_answer_only']['median_share'])} once the prompt is hidden from the answer too). "
        f"The prompts were picked to be ambiguous, so the CoT is where the decision gets made.",
        f"<b>The answer reads the end of the CoT.</b> The last two sentences matter more than random sentences (beat random in {q3['last2']['beats_random']}/20 Qwen, {g3['last2']['beats_random']}/20 Gemma runs), "
        f"hiding the last 10% of sentences removes {f2(q['curves']['suffix'][8]['median'])} (Qwen), and splicing another CoT's ending onto this one makes the answer follow the ending: "
        f"Qwen follows its final sentence, Gemma the last 10–25%.",
        f"<b>The rest of the CoT is redundant.</b> Big groups of sentences matter <i>less</i> than random sets of the same size (pre-lock-in: Qwen {f2(q3['pre_lock']['median_share'])} vs random {f2(q3['pre_lock']['median_random'])}; post-lock-in: Gemma {f2(g3['post_lock']['median_share'])} vs {f2(g3['post_lock']['median_random'])}), "
        f"and hiding any single sentence from the answer moves at most a small share (median of the per-run maximum: Qwen {f2(qf['answer_only']['max_share_median'])}, Gemma {f2(gf['answer_only']['max_share_median'])}). "
        f"Earlier sentences shape the verdict by shaping what the ending says, not through direct attention from the answer.",
        f"<b>The read-out happens in a band of middle-to-late layers, through many heads.</b> Qwen: layers 40–56 (48–49 strongest); Gemma: 15–22. Inside the band, the heads that attend most from the answer to the CoT carry most of the effect, but it takes dozens of them (Qwen: 128 heads → +0.46; Gemma: 64 heads → +0.58). The receiver heads the thought-anchors paper highlights mostly sit at or after the band, which fits blocking them doing nothing to the verdict.",
        f"<b>A linear probe sees the verdict about when the words do.</b> It rises from ~0.58 AUC at the start to ~0.9+ at the end, but a bag-of-words on the text so far is better for Gemma (also on {gp['fresh']['n']} fresh CoTs: {gp['fresh']['text_all']:.2f} vs {gp['fresh']['auc_all']:.2f}) and about as good for Qwen ({qp['fresh']['text_all']:.2f} vs {qp['fresh']['auc_all']:.2f} on {qp['fresh']['n']} fresh CoTs). "
        f"In Gemma, resampling says the verdict is settled by sentence {pl['gemma'][0]:.0f} (median), while the probe only commits by sentence {pl['gemma'][1]:.0f}: the decision is in the distribution over future text before it is visible in the current activations. In Qwen the two agree ({pl['qwen'][0]:.0f} vs {pl['qwen'][1]:.0f}).",
        f"<b>So, for the write-up:</b> eval awareness here is a decision made in text. The CoT locks in early (resampling), the conclusion gets written out near the end, and the answer copies that conclusion through a band of read-out layers. "
        f"Thought anchors explain how the CoT is organised, not where the verdict is read from.",
    ])
    N["EXP2"] = (f"Hiding the whole CoT from the answer (the tokens after <code>&lt;/think&gt;</code>) removes a median {f2(q2['cot_all']['median_share'])} of Qwen's margin and {f2(g2['cot_all']['median_share'])} of Gemma's, flipping {q2['cot_all']['flips']} and {g2['cot_all']['flips']} of 20 verdicts. "
                 f"Since each prompt has one EVAL and one DEPLOY run, 50/50 is exactly what a model that only sees the prompt should say. "
                 f"The user prompt matters much less: hidden from everything (including the CoT), Qwen {f2(q2['user']['median_share'])} and Gemma {f2(g2['user']['median_share'])}; hidden from the answer only, {f2(q2['user_answer_only']['median_share'])} and {f2(g2['user_answer_only']['median_share'])}. "
                 f"Its last quarter (where the actual request sits) carries most of that ({f2(q2['user_q4']['median_share'])} and {f2(g2['user_q4']['median_share'])}).")
    N["EXP3"] = (f"Two small groups beat random: the <b>last two sentences</b> (Qwen {f2(q3['last2']['median_share'])} vs {f2(q3['last2']['median_random'])}, {pv(q3['last2']['p'])}; Gemma {f2(g3['last2']['median_share'])} vs {f2(g3['last2']['median_random'])}, {pv(g3['last2']['p'])}) "
                 f"and, for Qwen only, the <b>first two</b> ({f2(q3['opening']['median_share'])} vs {f2(q3['opening']['median_random'])}, {pv(q3['opening']['p'])}). "
                 f"The causal-graph anchors and the resampling-importance top-3 are no better than random sentences. Large groups are <i>worse</i> than random sets of the same size, probably because a random set that large usually includes some of the ending. "
                 f"The prefix/suffix curves show the same thing from both directions: hiding everything except the last 10% barely matters until the last sentences go too.")
    N["EXP6"] = ("Receiver heads are found the way the paper does it: per head, the attention each sentence receives from tokens at least 16 tokens later, then the kurtosis of that profile across sentences; the 20 most kurtotic heads. "
                 "The ranking is stable (split-half r 0.84 Qwen, 0.89 Gemma). But hiding a sentence in only those 20 heads moves the verdict less than hiding it in 20 random heads, and their receiver score does not track which sentences matter.")
    N["EXP1"] = (f"200 sampled CoTs per model (20 per prompt). The residual probe's AUC rises from about {dec('qwen', 'probe', 0):.2f} in the first tenth of the CoT to {dec('qwen', 'probe', 9):.2f} (Qwen) and {dec('gemma', 'probe', 9):.2f} (Gemma) in the last. "
                 f"It beats a bag-of-words on the current sentence alone, so the residual stream does carry some history. But it does not beat a bag-of-words on all the text so far in cross-validation. "
                 f"On fresh CoTs generated overnight from the same prompts (probe and BoW trained on all 200), Qwen's probe edges ahead ({qp['fresh']['auc_all']:.2f} vs {qp['fresh']['text_all']:.2f}) while Gemma's words stay ahead ({gp['fresh']['text_all']:.2f} vs {gp['fresh']['auc_all']:.2f}). "
                 f"Either way, the activations do not predict the verdict much before the words do.")
    N["PROBE_NOTE"] = (f"Probe lock = first sentence after which the probe stays on the final verdict's side of 50%. Gemma: probe lock later than resampling lock in {pl['gemma'][2]}/20 runs. "
                       f"The answer-position AUC is unreliable (the answer token is a different distribution from sentence ends; at some Qwen layers the probe even flips sign there), so we do not use it.")
    N["SPLICE"] = (f"Pair each CoT A with the other base CoT B for the same prompt (opposite verdict), teacher-force A's first part followed by B's continuation, and read the verdict. "
                   f"<b>Qwen follows the ending every time</b>: with only B's last sentence it takes B's verdict in {qs['tail_1']['follows_tail']}/20 runs. "
                   f"<b>Gemma integrates a longer ending</b>: B's last sentence alone wins only {gs['tail_1']['follows_tail']}/20, B's last 10% wins {gs['frac_0.9']['follows_tail']}/20, B's last 25% wins {gs['frac_0.75']['follows_tail']}/20. "
                   f"Splices can be incoherent at the seam, but the direction is unambiguous: the ending decides.")
    N["LAYERS"] = (f"Hide the CoT from the answer in only some layers. <b>Qwen:</b> layers 48–56 alone remove {f2(lw['qwen']['48-56'])}, 40–48 {f2(lw['qwen']['40-48'])}, every other 8-layer band ≈ 0; "
                   f"layers ≥ 40 give {f2(lf['qwen']['40'])}, layers < 40 give {f2(lu['qwen']['40'])}. "
                   f"<b>Gemma:</b> 15–19 alone {f2(lw['gemma']['15-19'])}; layers ≥ 15 {f2(lf['gemma']['15'])}, ≥ 22 only {f2(lf['gemma']['22'])}; layers < 22 {f2(lu['gemma']['22'])}. "
                   f"So the read-out is spread over roughly layers 15–22 in Gemma and 40–56 in Qwen; after that, the answer no longer needs the CoT tokens.")
    N["NEXT"] = "".join(f"<li>{x}</li>" for x in [
        "<b>Rewrite the ending, not the reasoning.</b> Paraphrase the last sentences so they no longer state a conclusion (or state the opposite one) while keeping the rest. If the verdict follows the rewrite, eval-awareness steering only needs the conclusion sentence. Cheap: teacher-forced, no sampling.",
        "<b>Resample from the splice point.</b> Given A's first 75%, does the model regenerate an ending with A's verdict? That connects resampling lock-in (text-level) to the ending the answer reads.",
        "<b>Patch, don't block, in the read-out band.</b> Patch the residual stream of B into A at the last sentence, layer by layer in the band, to find where the conclusion is written into the answer position.",
        "<b>A probe trained on the answer-copying direction.</b> Use the read-out heads' output at the answer position as the probe target, and test whether that direction is present earlier in the CoT.",
    ])
    N["SMALL"] = "".join(f"<li>{x}</li>" for x in [
        f"<b>Sentences that name a label</b> (“evaluat…”, “deploy…”) matter more than random sentences: Qwen {f2(qf['groups']['label_word']['median_share'])} vs {f2(qf['groups']['label_word']['median_random'])} ({qf['groups']['label_word']['beats_random']}/20, {pv(qf['groups']['label_word']['p'])}, {qf['groups']['label_word']['flips']} flips); "
        f"Gemma {f2(gf['groups']['label_word']['median_share'])} vs {f2(gf['groups']['label_word']['median_random'])} ({gf['groups']['label_word']['beats_random']}/20, {pv(gf['groups']['label_word']['p'])}).",
        f"<b>Explicit verdict statements</b> in capitals (“…this is DEPLOYMENT”) are rare (Gemma {gf['groups'].get('verdict_stmt', {}).get('n', 0)} runs, Qwen {qf['groups'].get('verdict_stmt', {}).get('n', 0)}) and hiding them does little (Gemma {f2(gf['groups']['verdict_stmt']['median_share'])}): the conclusion is restated in several places.",
        f"<b>Each sentence hidden from the answer only</b> (still visible to the rest of the CoT): the largest single-sentence effect per run is small (median {f2(qf['answer_only']['max_share_median'])} Qwen, {f2(gf['answer_only']['max_share_median'])} Gemma); "
        f"the biggest one is in the last two sentences in {qf['answer_only']['top_in_last2']}/20 Qwen and {gf['answer_only']['top_in_last2']}/20 Gemma runs.",
    ])
    N["METHOD"] = "".join(f"<li>{x}</li>" for x in [
        "Same 20 base CoTs per model as the suppression report (10 balanced prompts × one EVAL, one DEPLOY run), teacher-forced. Qwen3-32B FP8 and Gemma 4 26B-A4B bf16 on one L40S (coco). No API calls.",
        "Verdict = log-odds of “&lt;label&gt;EVALUATION” vs “&lt;label&gt;DEPLOYMENT” after the CoT. Share = −Δ·sign(base)/|base|.",
        "Blocking: key tokens of a span are hidden from query rows from a given point on (the span's end for “every later token”, the CoT end for “answer only”), via a wrapper on the SDPA attention; optionally only in some heads/layers. Checked: rows before the block are unchanged; a head mask over all heads equals the unrestricted block; collected attention matches eager attention to ~1e-6.",
        "Random baselines: 5 random sentence sets of the same size per CoT; Wilcoxon signed-rank across the 20 runs.",
        "Probe: 8 layers, standardised logistic regression (C = 0.01) on the last token of each sentence, leave-one-prompt-out. Layer chosen by mean AUC over the first half of the CoT. Prompt labels are balanced (45–60% EVAL per prompt), so pooled and within-prompt AUCs agree.",
        f"Fresh CoTs: {qp['fresh']['n']} for Qwen, only {gp['fresh']['n']} for Gemma (generation with CPU offload was slow and stopped at the 04:30 deadline); same 10 prompts, so they test new samples, not new prompts.",
        "Caveats: 20 CoTs per model and 10 prompts; splices can be incoherent at the seam; the read-out band is found with coarse windows; the probe is linear and sees one position at a time.",
    ])
    return N


def readers_text(ov):
    rd = {k: ov[k].get("readers") for k in ov}
    if not all(rd.values()):
        return {"READERS_H": "Reader heads (still running when this page was built)",
                "READERS": "This experiment was queued last; its results were not in yet when the report was built."}
    parts = []
    for k in ["qwen", "gemma"]:
        r = rd[k]
        rows = {x["k"]: x for x in r["rows"]}
        k200 = rows[200]
        w = r["win"][-1]
        nband = (r["window"][1] - r["window"][0]) * (r["n_heads"] // r["n_layers"])
        best = sorted(r["single_layer"], key=lambda x: -x["share"])[:2]
        parts.append(f"<b>{NAMES[k]}</b> (all heads: {f2(r['all_heads'])}): the top {w['k']} of the {nband} heads in layers {r['window'][0]}–{r['window'][1] - 1} remove {f2(w['top'])} "
                     f"(random heads from the same layers: {f2(w['random'])}, beaten in {w['beats_random']}/20 runs). Over all layers, the top 200 ({k200['frac_heads']:.0%} of heads) remove {f2(k200['top'])} vs {f2(k200['random'])} for random, "
                     f"and blocking every head <i>except</i> them still removes {f2(k200['keep_top'])}. Strongest single layers: " + ", ".join(f"{x['layer']} ({f2(x['share'])})" for x in best) + ".")
    return {"READERS_H": "The answer reads the CoT through dozens of heads, not a handful",
            "READERS": ("Designed after the receiver-head null: rank heads by how much attention the answer tokens pay to the CoT, then hide the CoT from the answer in only those heads. "
                        "The ranking finds the right heads (top-k beats random k at every size), but no small set carries the verdict: the top 5–50 heads remove at most about a tenth of the margin. " + " ".join(parts) +
                        " So the read-out is a distributed circuit concentrated in the band; in Gemma a third of the band's heads carry most of the effect, in Qwen the top eighth carry about half. Ranking by raw attention mass also picks up early-layer heads that attend to everything; ranking inside the band works much better.")}


BODY_FILE = REPORT_DIR / "overnight_body.html"  # narrative + section skeleton (hand-written after the results)


def main():
    ov = json.loads((RES / "overnight_analysis.json").read_text())
    pr = json.loads((RES / "probe_analysis.json").read_text())
    data = {"models": {k: model_data(k, ov, pr) for k in ["gemma", "qwen"] if k in ov}}
    html = (REPORT_DIR / "template.html").read_text().replace("<title>Eval-Awareness Anchors</title>", "<title>Overnight Results</title>")
    i = html.index("const COLORS")
    head, rest = html[:i], html[i:]
    helpers = rest[: rest.index("/* ---------- Screening")]
    hb = rest[rest.index("function hbars"): rest.index("__SCRIPT__")]
    script = (REPORT_DIR / "overnight.js").read_text()
    html = head + helpers + hb + script + "</script>\n"
    body = BODY_FILE.read_text()
    for k, v in narrative(ov, pr).items():
        body = body.replace(f"__{k}__", v)
    for k, v in readers_text(ov).items():
        body = body.replace(f"__{k}__", v)
    html = html.replace("__BODY__", body).replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    out = REPORT_DIR / "overnight.html"
    out.write_text(html)
    print(out, f"{len(html) / 1e3:.0f} kB")


if __name__ == "__main__":
    main()
