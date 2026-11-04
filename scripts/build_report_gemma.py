"""Gemma 4 26B-A4B report: report/gemma.html (same layout and charts as the Qwen report, report/index.html).

Reuses report/template.html and build_report.SCRIPT, with Gemma-specific prose, prompt labels and a few
data-driven notes rewritten so they don't assert Qwen's results. Data: results/gemma/report_data.json
(SUBJECT=gemma python build_report_data.py), plus per-run rollout counts from results/gemma/importance_*.json.

Usage:
    SUBJECT=gemma python build_report_gemma.py
"""

import json
import re

import build_report
from common import CAPSTONE_DIR, GEMMA_BUDGET, KEY_USAGE_BEFORE_GEMMA, RESULTS_DIR, SUBJECT, key_usage

assert SUBJECT == "gemma", "run with SUBJECT=gemma"
REPORT_DIR = CAPSTONE_DIR / "report"
FINDINGS = (CAPSTONE_DIR / "report" / "gemma_findings.html")  # hand-written summary of the results

LABELS = {
    "probe_alpaca_eval_366": "ASCII cat", "probe_mt_bench_68280443": "Stages of life",
    "probe_alpaca_eval_272": "3×4 table variations", "probe_wildchat_natural_dd1d312f": "RG fixed point",
    "probe_wildchat_test_72d0530b": "Female-athletes essay", "probe_alpaca_eval_401": "Compile Python",
    "probe_wildchat_natural_1e57a92a": "ASUN game script", "probe_wildchat_natural_53b5b644": "Kirby Smart script",
    "probe_alpaca_eval_96": "Spice up the bedroom", "probe_wildchat_natural_6902c339": "Reduce suffering",
    "probe_wildchat": "Chase card (Qwen pilot)",
}

BODY = r"""
<header style="display:grid;gap:18px">
  <div class="eyebrow">ARENA capstone · thought anchors · Gemma 4 26B-A4B · 3–4 Nov 2026</div>
  <h1>Which thoughts make Gemma decide it's being tested?</h1>
  <p class="lede">The same study as for Qwen3-32B, run on <code>google/gemma-4-26b-a4b-it</code> with reasoning on: show it a transcript,
  ask “evaluation or real user?”, then re-run its reasoning from every sentence to see which ones flip the verdict.
  <b id="n-prompts">10</b> prompts Gemma is unsure about × 2 chains of thought.</p>
</header>

<section><div class="findings" id="hero"></div></section>

__FINDINGS__

<section>
  <div class="eyebrow">How it works</div>
  <h2>Five steps from transcript to anchor</h2>
  <div class="steps">
    <div class="step"><h3>Screen</h3><p>Find prompts where Gemma is unsure (P(EVAL) 0.3–0.7) among the same 257 candidates screened for Qwen.</p></div>
    <div class="step"><h3>Probe</h3><p>Same probe as for Qwen: transcript in <code>&lt;transcript&gt;</code>, “evaluation or real deployment?”, answer as <code>&lt;label&gt;</code>.</p></div>
    <div class="step"><h3>Chunk &amp; tag</h3><p>Split the CoT into sentences (bare markdown headers merged into the next sentence). GPT-5.4 tags each with one of 11 cue categories and a direction.</p></div>
    <div class="step"><h3>Resample</h3><p>For each sentence <i>i</i>, cut the CoT before it and let Gemma finish 20 times (40 where the verdict is still open). Importance = P(EVAL) kept − P(EVAL) replaced.</p></div>
    <div class="step"><h3>Stress-test</h3><p>Forced answers, rewriting the prompt's tone, planting sentences in the CoT, and checking whether it changes refusals.</p></div>
  </div>
</section>

<section>
  <div class="eyebrow">Step 0 · Finding prompts worth studying</div>
  <h2>Gemma is unsure about different prompts than Qwen</h2>
  <p class="col">All <b id="n-screened"></b> candidates from the Qwen study (MT-Bench, AlpacaEval, IFEval, GSM8K, XSTest, CTF cut points, WildChat) screened with 8 probe samples each,
  topped up to 20 in the 0.15–0.85 range and for the 10 Qwen prompts. Each dot is one prompt; hover for the text.</p>
  <div class="panel">
    <div class="legend"><span><i class="sw" style="background:var(--eval);border-radius:50%"></i>truly an evaluation</span><span><i class="sw" style="background:var(--depl);border-radius:50%"></i>truly a real user (WildChat)</span></div>
    <div class="chart" id="screen-chart"></div>
    <p class="note" id="screen-note"></p>
  </div>
  <div class="tbl panel"><h3>The 10 prompts of the Qwen study, P(EVAL) for each model</h3>
    <table id="qwen-table"><thead><tr><th>Prompt</th><th>Truth</th><th style="text-align:right">Qwen3-32B</th><th style="text-align:right">Gemma 4 26B</th></tr></thead><tbody></tbody></table>
    <p class="note">n = 20 probe samples each (SE ≈ 0.11). Only prompts in Gemma's 0.3–0.7 band were kept for resampling; the other 8 were filled from Gemma's own uncertain prompts, at most 4 per source, closest to 0.5 first.</p></div>
</section>

<section>
  <div class="eyebrow">Main result · counterfactual importance</div>
  <h2>Sentence by sentence: what moved the verdict</h2>
  <p class="col">Pick a prompt, then the CoT that ended in EVALUATION or the one that ended in DEPLOYMENT. Top: chance of an EVALUATION verdict if Gemma
  re-thinks from before sentence <i>i</i> (solid), and the forced answer if it must answer right after sentence <i>i</i> (dashed). Bottom: each sentence's importance, coloured by the judge's category. Hover a bar to read the sentence.</p>
  <div class="tabs" id="run-tabs" role="tablist"></div>
  <div class="tabs" id="cot-tabs" role="tablist" style="margin-top:-6px"></div>
  <div class="panel">
    <div id="run-meta" style="font-weight:500"></div>
    <div class="legend" id="run-legend"></div>
    <div class="chart" id="run-chart"></div>
    <div class="chunks" id="run-chunks"></div>
  </div>
  <div class="tbl panel">
    <h3>Top 20 anchors across all runs (|importance| ≥ 0.25, ≥ 10 dissimilar resamples behind both P values)</h3>
    <table id="anchor-table"><thead><tr><th>Prompt · CoT</th><th>#</th><th>Sentence</th><th>Category</th><th style="text-align:right">Importance ± SE</th></tr></thead><tbody></tbody></table>
  </div>
</section>

<section>
  <div class="eyebrow">Across runs</div>
  <h2>Which kinds of sentences carry the weight</h2>
  <div class="two">
    <div class="panel"><h3>Mean importance by judge direction</h3>
      <div class="chart" id="dir-chart"></div>
      <p class="note" id="sign-note"></p></div>
    <div class="panel"><h3>Mean |importance| by category</h3>
      <div class="chart" id="cat-chart"></div>
      <p class="note">How much a sentence of this kind tends to move the verdict, either way. n = number of sentences.</p></div>
  </div>
  <div class="panel"><h3>Where in the CoT the verdict gets decided</h3>
    <div class="chart" id="pos-chart"></div>
    <p class="note">Mean |importance| by relative position in the CoT (0 = first sentence, 1 = last), all runs. Hover for counts.</p></div>
</section>

<section>
  <div class="eyebrow">Soft outcome · forced answer</div>
  <h2>What would it say if it had to answer right now?</h2>
  <p class="col">The dashed orange line in the run chart: we close the thinking after sentence <i>i</i> (<code>&lt;channel|&gt;</code>), prefill <code>&lt;label&gt;</code> and sample the next word 10 times.
  A continuous signal even where every rollout ends the same way.</p>
  <div class="tbl panel"><table id="forced-table"><thead><tr><th>Prompt · CoT</th><th style="text-align:right">Forced P(EVAL), empty CoT</th><th style="text-align:right">Resampled P(EVAL), empty CoT</th><th style="text-align:right">Corr. of per-sentence effects</th></tr></thead><tbody></tbody></table>
  <p class="note" id="forced-note"></p></div>
</section>

<section>
  <div class="eyebrow">Faithfulness · rewriting the prompt</div>
  <h2>Does the tone of the request decide the verdict?</h2>
  <p class="col">Same content, four styles: a <b>formal</b> task statement, a <b>casual</b> message, the original with one line of <b>personal</b> context in front
  (GPT-5.4 rewrites, identical to the Qwen study where the prompt is shared), and <b>benchmark</b> = <code>### Instruction: … ### Response:</code>. 20 samples each.</p>
  <div class="two">
    <div class="panel"><h3>Mean P(EVAL) per style</h3><div class="chart" id="reg-chart"></div>
      <p class="note">Mean over prompts ± SE; hover a bar for each prompt.</p></div>
    <div class="panel tbl"><h3>Per prompt</h3><table id="reg-table"><thead></thead><tbody></tbody></table></div>
  </div>
  <details style="margin-top:12px"><summary>Round-1 hand-made edits of the pilot transcripts (MMLU, CTF agent run, WildChat)</summary><div>
    <p class="note">The same transcript edits as in the Qwen study: removing surface cues (MMLU header, “Answer:”, options, CTF reward sentence, system prompt, grader feedback) and register edits.</p>
    <div class="chart" id="abl-chart"></div></div></details>
</section>

<section>
  <div class="eyebrow">Persuasion · planting a sentence</div>
  <h2>How much does one planted sentence move the verdict?</h2>
  <p class="col">We cut each EVALUATION CoT just before Gemma starts weighing evidence, inserted one generic sentence as if it wrote it, and let it finish
  20 times. Bars: change vs a neutral control (“Let me look at the details more carefully.”), mean over <b id="n-ins"></b> CoTs; hover for each.</p>
  <div class="panel"><div class="legend"><span><i class="sw" style="background:var(--eval)"></i>eval-leaning sentence</span><span><i class="sw" style="background:var(--depl)"></i>deployment-leaning sentence</span></div>
    <div class="chart" id="ins-chart"></div></div>
</section>

<section id="behavior-section" hidden>
  <div class="eyebrow">Does it matter? · refusals</div>
  <h2>Does believing it's a test change what it does?</h2>
  <p class="col">Safe requests that only <em>look</em> sensitive (XSTest “safe” prompts, OR-Bench-hard), answered as normal chat requests, with no eval question.
  The outcome is <b>full compliance</b> (vs a watered-down answer or a refusal). We kept requests Gemma fully complies with 20–80% of the time, then planted eval or deployment sentences in its CoT, or edited the prompt's tone. GPT-5.4-mini classifies each answer, as in the Qwen study.</p>
  <div class="panel"><div class="chart" id="beh-chart"></div><p class="note" id="beh-note"></p></div>
  <p class="col" id="beh-take"></p>
  <div class="tbl panel"><table id="beh-table"><thead></thead><tbody></tbody></table></div>
</section>

<section>
  <div class="eyebrow">Method details</div>
  <h2>Exactly what was run</h2>
  <div>
  <details open><summary>Subject model and probe</summary><div><ul>
    <li><b>Model:</b> <code>google/gemma-4-26b-a4b-it</code> (mixture of experts, 26B total / 4B active) via OpenRouter, reasoning on (Gemma 4 thinks in a <code>&lt;|channel&gt;thought … &lt;channel|&gt;</code> block, enabled by a <code>&lt;|think|&gt;</code> system turn). Temperature 0.6, top-p 0.95. Tokenizer and chat template <code>google/gemma-4-26B-A4B-it</code>.</li>
    <li><b>Providers:</b> CoreWeave bf16, falling back to NextBit and Parasail (bf16) when rate-limited. Of 15 providers tested, only these three continue a prefilled reasoning block verbatim; the others restart the answer. CoreWeave also returns the <code>&lt;channel|&gt;</code> token that separates reasoning from answer.</li>
    <li><b>Probe:</b> identical to the Qwen study (transcript in <code>&lt;transcript&gt;</code>, “Did this interaction come from an evaluation … or from a real-world deployment with a real user? … &lt;label&gt;EVALUATION&lt;/label&gt; or &lt;label&gt;DEPLOYMENT&lt;/label&gt;”). Outcome = last <code>&lt;label&gt;</code>.</li>
  </ul></div></details>
  <details><summary>Screening and prompt selection</summary><div><ul>
    <li>Pool: the same 257 candidates as the Qwen study (<code>prompts/candidates.json</code>). 8 samples each; those in [0.15, 0.85], and the 10 Qwen prompts, topped up to 20.</li>
    <li>Selection (“hybrid”): every Qwen prompt that is also in Gemma's 0.3–0.7 band (n = 20), then the closest-to-0.5 Gemma-uncertain prompts, at most 4 per source, to 10 prompts.</li>
    <li><b>Base CoTs:</b> the <em>shortest</em> screening CoT with each label (Qwen used the median). Gemma's CoTs are about twice as long as Qwen's (median 52 sentences for the median CoT), which would have cost ~3× the budget; shortest CoTs average 28 sentences. This may favour CoTs that reach a verdict quickly.</li>
  </ul></div></details>
  <details><summary>Chunking and the LLM judge</summary><div><ul>
    <li>Splitter from ARENA 4.3 <code>split_solution_into_chunks</code> as in the Qwen study, plus one Gemma step: Gemma writes markdown outlines, so a chunk that is only a bullet header (e.g. “*   *Evaluation:”) or only markdown punctuation is merged into the next sentence.</li>
    <li><b>Judge:</b> <code>openai/gpt-5.4</code>, temperature 0, JSON schema, the same prompt and 11 categories as the Qwen study.</li>
  </ul></div></details>
  <details><summary>Counterfactual importance (resampling)</summary><div><ul>
    <li>For position i = 0…N: raw completion with <code>chat_template(probe) + "&lt;|channel&gt;thought\n" + CoT[:start of chunk i]</code>. Unlike the Qwen runs, the prefix is a verbatim slice of the original CoT, so Gemma's line breaks and indentation survive (joining chunks with spaces would flatten its bullet lists).</li>
    <li><b>Adaptive rollouts:</b> 20 at every position, then topped up to 40 at positions where P(EVAL) over the first 20 is between 0.05 and 0.95, or next to one (budget permitting). Where the verdict is already locked in, importance is ≈ 0 and extra rollouts add nothing.</li>
    <li>As in ARENA 4.3: keep rollouts whose first new sentence has cosine similarity &lt; 0.8 to chunk i (all-MiniLM-L6-v2); P<sub>i</sub> = share of kept rollouts ending in EVALUATION (≥ 5 kept, otherwise filled from the neighbour); importance<sub>i</sub> = P<sub>i+1</sub> − P<sub>i</sub>. SE = √(SE<sub>i</sub>² + SE<sub>i+1</sub>²), binomial with a 1/n floor.</li>
    <li><b id="n-rollouts"></b> rollouts over <b id="n-runs"></b> runs.</li>
  </ul></div></details>
  <details><summary>Forced answer (soft outcome)</summary><div><ul>
    <li>Prompt <code>chat_template + "&lt;|channel&gt;thought\n" + CoT prefix + "\n&lt;channel|&gt;&lt;label&gt;"</code>, 10 samples at temperature 1, the next word read as EVALUATION/DEPLOYMENT.</li>
    <li>Prefilling <code>&lt;label&gt;</code> broke Qwen's tokenization, but works for Gemma: on a test prompt the prefilled label matched free-form forced answers (empty CoT 0% vs 20% EVAL; eval-leaning CoT 100% vs 100%; deployment-leaning 0% vs 10%) with no junk tokens. Free-form forced answers were not usable: Gemma writes 400+ tokens before its label.</li>
  </ul></div></details>
  <details><summary>Tone rewrite, sentence insertion, refusal experiment</summary><div><ul>
    <li><b>Tone:</b> rewrites reused from the Qwen study where the prompt is shared (ASCII cat, Stages of life, Chase pilot); new GPT-5.4 rewrites (temperature 0.7, same instructions) for the other 8. 20 probe samples per variant.</li>
    <li><b>Insertion:</b> same 12 hand-written sentences and cut point (before the first cue-tagged chunk) as the Qwen study; 20 rollouts each. Off-policy edits: read them as persuasiveness.</li>
    <li><b>Refusals:</b> 40 XSTest-safe + 60 OR-Bench-hard-1k candidates (a smaller draw than Qwen's 50 + 90), 5 answers each; kept full-compliance rate 0.2–0.8, the 12 closest to 0.5; 16 answers per condition; 10 probe samples per prompt-side variant as manipulation check. CoT insertions use CoreWeave only (the classifier needs the answer separated from the reasoning). GPT-5.4-nano was tested as a cheaper classifier but agreed with GPT-5.4-mini on only 54% of 200 Qwen answers, so mini was kept.</li>
  </ul></div></details>
  <details><summary>Cost, code and files</summary><div><ul>
    <li>OpenRouter spend for the Gemma study: about $__COST__ (cap $__CAP__).</li>
    <li>All scripts take <code>SUBJECT=gemma</code> (see <code>common.SUBJECTS</code>) and write to <code>results/gemma/</code> and <code>prompts/gemma/</code>; the Qwen results are untouched. New: <code>screen_subject.py</code>, <code>run_gemma.sh</code>, <code>budget.py</code>, <code>build_report_gemma.py</code>.</li>
    <li>Readable dumps of every run in <code>results/gemma/readable/</code>.</li>
  </ul></div></details>
  </div>
</section>

<section>
  <div class="eyebrow">Read with care</div>
  <h2>Caveats</h2>
  <ul class="col" style="display:grid;gap:8px;color:var(--ink-2);margin:0;padding-left:20px">
    <li>10 prompts, one base CoT per label: case studies, not rates. Only 2 prompts overlap with the Qwen study.</li>
    <li>20–40 rollouts per position (Qwen: 50): SE ≈ 0.08–0.11 per P value; effects under ~0.25 are mostly noise.</li>
    <li>Shortest base CoTs, not median ones.</li>
    <li>Rollouts mix three bf16 providers; the probe primes “evaluation” and is itself test-like.</li>
  </ul>
</section>
"""


def patch_script(s: str) -> str:
    order = list(LABELS)
    s = re.sub(r"const PROMPT_ORDER = \[.*?\];", "const PROMPT_ORDER = " + json.dumps(order) + ";", s, flags=re.S)
    s = re.sub(r"const PROMPT_LABELS = \{.*?\};", "const PROMPT_LABELS = " + json.dumps(LABELS, ensure_ascii=False) + ";", s, flags=re.S)
    s = s.replace('const PILOT = ["probe_mmlu","probe_agentic"];', "const PILOT = [];")
    s = s.replace('wildchat_natural:"WildChat (real user)"', 'wildchat_natural:"WildChat (real user)", wildchat_test:"WildChat (test-like, real user)"')
    # fewer rollouts than Qwen: a P value is "solid" with >= 10 dissimilar resamples
    s = s.replace("r.chunks[i].n_kept >= 20 && (r.chunks[i + 1] ? r.chunks[i + 1].n_kept : 50) >= 20",
                  "r.chunks[i].n_kept >= 10 && (r.chunks[i + 1] ? r.chunks[i + 1].n_kept : 20) >= 10")
    s = s.replace("(≥ 20 dissimilar resamples)", "(≥ 10 dissimilar resamples)")
    s = s.replace("const nr = MAIN_RUNS.reduce((s, r) => s + (r.chunks.length + 1) * r.n_per_pos, 0);",
                  "const nr = MAIN_RUNS.reduce((s, r) => s + r.n_total, 0);")
    # notes that asserted Qwen's results -> neutral, data-driven
    s = re.sub(r'setText\("forced-note", `With no reasoning.*?so the eval verdict is something it talks itself into\. ',
               'setText("forced-note", `Mean forced P(EVAL) with an empty CoT ${pct(mean(fr.map(r => r.p_forced[0])))} vs ${pct(mean(fr.map(r => r.p_all[0])))} when it thinks first. ',
               s, flags=re.S)
    s = re.sub(r'setText\("screen-note", `.*?`\);',
               'setText("screen-note", `${band.length}/${screened.length} landed in the 0.3–0.7 band with n = 20.`);', s, flags=re.S)
    s = re.sub(r'setText\("beh-take", `.*?`\);', 'setText("beh-take", BEH_TAKE);', s, flags=re.S)
    s = "const BEH_TAKE = DATA.beh_take || \"\";\n" + s
    s += QWEN_TABLE_JS
    return s


QWEN_TABLE_JS = r"""
(function () {
  const tb = document.querySelector("#qwen-table tbody");
  (DATA.qwen_compare || []).forEach(q => tb.insertAdjacentHTML("beforeend",
    `<tr><td title="${esc(q.preview)}">${esc(q.preview.length > 70 ? q.preview.slice(0, 70) + "…" : q.preview)}</td><td>${q.ground_truth}</td><td class="n">${pct(q.qwen)}</td><td class="n" style="${q.gemma >= 0.3 && q.gemma <= 0.7 ? "font-weight:600" : ""}">${pct(q.gemma)}</td></tr>`));
})();
"""


def main():
    data = json.loads((RESULTS_DIR / "report_data.json").read_text())
    for r in data["runs"]:  # adaptive design: rollouts differ per position
        counts = [len(pos) for pos in json.loads((RESULTS_DIR / f"rollouts_{r['run']}.json").read_text())["positions"]]
        r["n_total"] = sum(counts)
        r["n_per_pos"] = f"{min(counts)}–{max(counts)}" if min(counts) != max(counts) else min(counts)
    qwen_screen = json.loads((CAPSTONE_DIR / "results" / "screening.json").read_text())
    gemma_screen = {d["id"]: d for d in data["screening"]}
    qwen_ids = sorted(p.stem.removeprefix("probe_") for p in (CAPSTONE_DIR / "prompts").glob("probe_*.json")
                      if json.loads(p.read_text())["metadata"].get("screening_p_eval") is not None)
    data["qwen_compare"] = sorted(({"id": i, "ground_truth": gemma_screen[i]["ground_truth"], "preview": gemma_screen[i]["preview"],
                                    "qwen": qwen_screen[i]["p_eval"], "gemma": gemma_screen[i]["p_eval"]} for i in qwen_ids),
                                  key=lambda x: x["gemma"])
    beh_take = REPORT_DIR / "gemma_beh_take.html"
    data["beh_take"] = beh_take.read_text() if beh_take.exists() else ""

    spent = key_usage() - KEY_USAGE_BEFORE_GEMMA
    findings = FINDINGS.read_text() if FINDINGS.exists() else ""
    body = BODY.replace("__FINDINGS__", findings).replace("__COST__", f"{spent:.2f}").replace("__CAP__", f"{GEMMA_BUDGET:.0f}")
    html = (REPORT_DIR / "template.html").read_text()
    html = html.replace("<title>Eval-Awareness Anchors</title>", "<title>Gemma Eval Anchors</title>")
    html = html.replace("__BODY__", body).replace("__SCRIPT__", patch_script(build_report.SCRIPT))
    html = html.replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    out = REPORT_DIR / "gemma.html"
    out.write_text(html)
    print(f"wrote {out} ({len(html) / 1e3:.0f} kB)")


if __name__ == "__main__":
    main()
