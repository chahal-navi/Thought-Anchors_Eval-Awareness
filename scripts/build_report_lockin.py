"""Build report/lockin.html: the H3 before-vs-after-lock-in insertion test, Qwen3-32B and Gemma 4 26B-A4B.

Needs results/lockin_analysis.json and results/gemma/lockin_analysis.json (analyze_lockin.py), the insertion_lockin_*
files and both report_data.json. Reuses the CSS of report/template.html.

Usage:
    python build_report_lockin.py
"""

import json

from common import CAPSTONE_DIR

RES = CAPSTONE_DIR / "results"
REPORT_DIR = CAPSTONE_DIR / "report"
MODELS = {"gemma": ("Gemma 4 26B-A4B", RES / "gemma"), "qwen": ("Qwen3-32B", RES)}


def load(subject):
    name, d = MODELS[subject]
    an = json.loads((d / "lockin_analysis.json").read_text())
    rd = {r["run"]: r for r in json.loads((d / "report_data.json").read_text())["runs"]}
    before = {r["run"]: r for r in json.loads((d / "report_data.json").read_text())["insertion"]}
    runs = []
    for run in sorted({r["run"] for r in an["per_run"]}):
        after = json.loads((d / f"insertion_lockin_{run}.json").read_text())
        pos = after["positions"]["lock+2"]
        rows = [r for r in an["per_run"] if r["run"] == run]
        runs.append({
            "run": run, "title": rd[run].get("title") or rd[run]["prompt"], "p": rd[run]["p_filtered"],
            "chunks": [c["text"] for c in rd[run]["chunks"]],
            "before_cut": before[run]["insert_before_chunk"], "after_cut": pos["insert_before_chunk"],
            "lock": after["lock"], "n_chunks": after["n_chunks"],
            "before_ctl": rows[0]["before_ctl"], "after_ctl": rows[0]["after_ctl"],
            "before_effect": sum(r["before_effect"] for r in rows) / len(rows),
            "after_effect": sum(r["after_effect"] for r in rows) / len(rows),
            "rows": rows,
        })
    return {"name": name, "summary": an["summary"], "runs": runs,
            "n_before": before[runs[0]["run"]]["n"], "n_after": after["n"]}


BODY = r"""
<header class="col" style="display:grid;gap:16px">
  <div class="eyebrow">Thought anchors for eval awareness · H3 test</div>
  <h1>Does the reasoning after lock-in still count?</h1>
  <p class="lede">Each model's eval-vs-deployment verdict stops changing under resampling partway through its CoT (“lock-in”).
  We planted the same deployment-leaning sentences into the same EVALUATION CoTs once <b>before</b> lock-in and once <b>two sentences after</b> it,
  and measured how much each still pulls the verdict toward DEPLOYMENT.</p>
</header>

<section>
  <div class="findings" id="tiles"></div>
  <p class="note col">Effect = P(EVAL) with the planted sentence − P(EVAL) with a neutral control sentence (“Let me look at the details more carefully.”) at the same cut.
  “Share of the drop” divides by the control's P(EVAL), because before lock-in the control sits near 0.5 and after it near 1.0, so raw effects alone understate the “before” condition.</p>
</section>

<section>
  <div class="eyebrow">Result</div>
  <h2>Gemma stops listening after lock-in; Qwen only partly does</h2>
  <p class="col">Each row is one base CoT, averaged over the 5 deployment-leaning sentences. Gray = planted before lock-in, blue = planted two sentences after it; further left = stronger pull toward DEPLOYMENT.</p>
  <div class="legend"><span><i class="sw" style="background:var(--before)"></i>Before lock-in</span><span><i class="sw" style="background:var(--after)"></i>After lock-in (lock + 2)</span></div>
  <div class="two">
    <div class="panel"><h3>Gemma 4 26B-A4B · 10 runs</h3><div class="chart" id="db-gemma"></div></div>
    <div class="panel"><h3>Qwen3-32B · 8 runs</h3><div class="chart" id="db-qwen"></div></div>
  </div>
  <p class="note col">Single-run values rest on 20 (after) or 20–30 (before) rollouts per sentence, about ±0.1 noise. The counts across runs (how many get smaller) are the robust part.</p>
</section>

<section>
  <div class="eyebrow">By cue type</div>
  <h2>Qwen's late reasoning still responds to claims about the user, the scenario and benchmarks</h2>
  <p class="col">Same comparison, averaged over runs for each planted sentence. For Gemma every cue type collapses after lock-in. For Qwen, problem-design and task-format sentences lose their pull, but the user-context, scenario-realism and known-benchmark sentences pull about as hard as before.</p>
  <div class="legend"><span><i class="sw" style="background:var(--before)"></i>Before lock-in</span><span><i class="sw" style="background:var(--after)"></i>After lock-in (lock + 2)</span></div>
  <div class="two">
    <div class="panel"><h3>Gemma 4 26B-A4B</h3><div class="chart" id="cat-gemma"></div></div>
    <div class="panel"><h3>Qwen3-32B</h3><div class="chart" id="cat-qwen"></div></div>
  </div>
  <div class="tbl panel"><h3>The five planted sentences</h3><table><thead><tr><th>Cue type</th><th>Sentence (deployment-leaning)</th></tr></thead><tbody id="sent-table"></tbody></table></div>
</section>

<section>
  <div class="eyebrow">Where the cuts are</div>
  <h2>The two insertion points on each resampling curve</h2>
  <p class="col">P(EVAL) when the CoT is resampled from each sentence (the original thought-anchors curve). Lock-in L = the first sentence after which every point stays within 0.15 of the final value.
  The “before” cut is the original insertion point (just before the first sentence the judge tagged as a cue); the “after” cut is L + 2.</p>
  <div class="tabs" id="model-tabs" role="tablist"></div>
  <div class="tabs" id="run-tabs" role="tablist"></div>
  <div class="panel"><div class="chart" id="curve"></div>
    <div class="legend"><span><i class="ln" style="background:var(--ink)"></i>Resampled P(EVAL)</span><span><i class="sw" style="background:var(--before)"></i>Before cut</span><span><i class="sw" style="background:var(--after)"></i>After cut (L + 2)</span><span><i class="ln" style="background:var(--ink-3)"></i>Lock-in L</span></div>
    <p class="note" id="curve-note"></p></div>
</section>

<section>
  <div class="eyebrow">Reading it</div>
  <h2>What this supports, and what it doesn't</h2>
  <ul class="col" style="display:grid;gap:10px;margin:0;padding-left:20px">
    <li><b>Within Gemma: the reasoning after lock-in is post-hoc.</b> A contradicting sentence planted two sentences after lock-in moves the verdict by −0.10 on average (−0.38 before), smaller in 48/50 run×sentence pairs and in 50/50 as a share of the available drop. Gemma's “after” cut is still early in the CoT (sentence 4–14 of 19–59), so this is about having decided, not about being near the end.</li>
    <li><b>Between models: Gemma is much harder to sway once it has decided.</b> After lock-in both controls sit at P(EVAL) ≈ 1.0, so both had the same room to drop: Gemma −0.10, Qwen −0.31.</li>
    <li><b>For Qwen, lock-in is where the CoT happens to settle, not a commitment.</b> Late explicit claims that the user is real, the scenario is ordinary, or the item matches no benchmark still flip a large share of rollouts (−0.41 to −0.45).</li>
    <li><b>Not shown:</b> that this generalises beyond these prompts, or that the difference is a property of the models rather than of the base CoTs. Gemma used its shortest screening CoTs and 20–40 rollouts per position to find L; Qwen used median-length CoTs and 50. The planted sentences are off-policy text (persuasiveness, not what the model would write).</li>
  </ul>
  <div class="panel col"><h3>Next experiments</h3>
    <ul style="display:grid;gap:8px;margin:0;padding-left:20px">
      <li>Matched base CoTs: rerun one model with the other's CoT-length rule, so the cross-model gap is not a selection artefact.</li>
      <li>A “mid” cut (halfway from L to the end) for both models, to see whether Qwen's late sensitivity fades further.</li>
      <li>On-policy check: resample until the model itself writes a deployment-leaning sentence after L and measure its effect.</li>
    </ul></div>
</section>

<section>
  <details><summary>Method</summary><div><ul>
    <li><b>Base CoTs:</b> the EVALUATION base CoTs of the main thought-anchors runs (Gemma 10, Qwen 8 of 11: <code>a102_eval</code> never locks in, final P 0.54; <code>a366_eval</code> locks at sentence 24 of 25, so L + 2 is past the end; <code>probe_wildchat</code> ends in DEPLOYMENT).</li>
    <li><b>Before:</b> the existing sentence-insertion data (<code>insertion.py</code>): sentence planted just before the first cue-tagged chunk, __NB__ rollouts per sentence. In every run used this cut is before L.</li>
    <li><b>After:</b> <code>insertion_lockin.py</code>: the control and the 5 deployment-leaning sentences planted before chunk L + 2, __NA__ rollouts each, same providers, temperature and prefix construction as the main runs (verbatim prefix for Gemma, space-joined chunks for Qwen). Eval-leaning sentences were not used after lock-in: with P(EVAL) ≈ 1 they cannot move it up.</li>
    <li><b>Lock-in L:</b> first position i with |P<sub>j</sub> − P<sub>N</sub>| ≤ 0.15 for every j ≥ i, on the similarity-filtered resampling curve.</li>
    <li><b>Analysis:</b> <code>analyze_lockin.py</code> → <code>results/lockin_analysis.json</code> and <code>results/gemma/lockin_analysis.json</code>. 1 of 960 Qwen rollouts had no parseable label; none for Gemma.</li>
    <li><b>Cost:</b> Gemma $0.56 (this pushed the Gemma total to $8.12, $0.12 over its $8 cap), Qwen $0.29.</li>
  </ul></div></details>
  <details><summary>All numbers, per run and sentence</summary><div class="tbl"><table><thead><tr><th>Model</th><th>Run</th><th>Cue type</th><th style="text-align:right">Cut b / a</th><th style="text-align:right">Lock / N</th><th style="text-align:right">Control b / a</th><th style="text-align:right">Effect before</th><th style="text-align:right">Effect after</th></tr></thead><tbody id="all-table"></tbody></table></div></details>
</section>
"""

SCRIPT = r"""
const ROOT = document.documentElement.style;
ROOT.setProperty("--before", "var(--ink-3)"); ROOT.setProperty("--after", "var(--accent)");
const CATS = ["user_context","known_benchmark","scenario_realism","task_format","problem_design"];
const SENT = DATA.sentences;

// tiles
const tiles = document.getElementById("tiles");
for (const [k, m] of Object.entries(DATA.models)) {
  const s = m.summary.all;
  tiles.insertAdjacentHTML("beforeend", `<div class="finding"><div class="eyebrow">${esc(m.name)}</div>
    <div class="num">${sgn(s.before_effect)} → ${sgn(s.after_effect)}</div>
    <p>Mean effect of a deployment-leaning sentence, before vs after lock-in. Smaller after in <b>${s.smaller_after}/${s.n}</b> run×sentence pairs.</p></div>
    <div class="finding"><div class="eyebrow">${esc(m.name)} · share of the drop</div>
    <div class="num">${pct(-s.before_rel)} → ${pct(-s.after_rel)}</div>
    <p>Share of the control's P(EVAL) the sentence removes. Smaller after in <b>${s.smaller_after_rel}/${s.n}</b>.</p></div>`);
}

// dumbbell: rows of {label, sub, b, a, tipB, tipA}
function dumbbell(host, rows) {
  const W = 480, rowH = 30, top = 26, left = 120, right = 48, H = top + rows.length * rowH + 10;
  const svg = el("svg", {viewBox: `0 0 ${W} ${H}`, role: "img"});
  const x = v => left + (v + 1) / 1 * (W - left - right);   // domain −1 … 0
  for (const t of [-1, -0.75, -0.5, -0.25, 0]) {
    el("line", {x1: x(t), x2: x(t), y1: top - 6, y2: H - 6, class: "grid"}, svg);
    txt(svg, x(t), top - 12, t === 0 ? "0" : t.toFixed(2).replace("-", "−"), {"text-anchor": "middle"});
  }
  rows.forEach((r, i) => {
    const y = top + i * rowH + rowH / 2;
    txt(svg, left - 10, y + 4, r.label, {"text-anchor": "end"});
    el("line", {x1: x(Math.min(r.b, 0)), x2: x(Math.min(r.a, 0)), y1: y, y2: y, stroke: css("--rule"), "stroke-width": 2}, svg);
    for (const [v, col, t] of [[r.b, "--before", r.tipB], [r.a, "--after", r.tipA]]) {
      const c = el("circle", {cx: x(Math.max(-1, Math.min(0.05, v))), cy: y, r: 5.5, fill: css(col), stroke: css("--surface"), "stroke-width": 2}, svg);
      const hit = el("circle", {cx: x(Math.max(-1, Math.min(0.05, v))), cy: y, r: 12, fill: "transparent"}, svg);
      hit.addEventListener("mousemove", e => showTip(e, t)); hit.addEventListener("mouseleave", hideTip);
    }
    txt(svg, x(Math.min(r.a, 0)) + (r.a > r.b ? 10 : -10), y - 8, sgn(r.a), {"text-anchor": r.a > r.b ? "start" : "end", style: "font-size:10px"});
  });
  host.replaceChildren(svg);
}

for (const [k, m] of Object.entries(DATA.models)) {
  dumbbell(document.getElementById("db-" + k), m.runs.map(r => ({
    label: r.run.replace("_eval", ""), b: r.before_effect, a: r.after_effect,
    tipB: `<b>${esc(r.run)}</b> · before lock-in<br>cut at sentence ${r.before_cut} of ${r.n_chunks}<br>control P(EVAL) ${pct(r.before_ctl)}<br>mean effect ${sgn(r.before_effect)}`,
    tipA: `<b>${esc(r.run)}</b> · after lock-in<br>cut at sentence ${r.after_cut} (L = ${r.lock})<br>control P(EVAL) ${pct(r.after_ctl)}<br>mean effect ${sgn(r.after_effect)}`})));
  dumbbell(document.getElementById("cat-" + k), CATS.map(c => { const s = m.summary[c]; return {
    label: DATA.names[c], b: s.before_effect, a: s.after_effect,
    tipB: `<b>${esc(DATA.names[c])}</b> · before<br>mean effect ${sgn(s.before_effect)} over ${s.n} runs`,
    tipA: `<b>${esc(DATA.names[c])}</b> · after<br>mean effect ${sgn(s.after_effect)}; smaller after in ${s.smaller_after}/${s.n}`}; }));
}
document.getElementById("sent-table").innerHTML = CATS.map(c => `<tr><td>${esc(DATA.names[c])}</td><td>“${esc(SENT[c])}”</td></tr>`).join("");

// curve explorer
let curModel = "gemma", curRun = 0;
function tabs(host, items, sel, onPick) {
  host.replaceChildren(...items.map((it, i) => { const b = document.createElement("button"); b.className = "tab"; b.role = "tab";
    b.textContent = it; b.setAttribute("aria-selected", i === sel); b.onclick = () => onPick(i); return b; }));
}
function drawCurve() {
  const keys = Object.keys(DATA.models), m = DATA.models[curModel], r = m.runs[curRun];
  tabs(document.getElementById("model-tabs"), keys.map(k => DATA.models[k].name), keys.indexOf(curModel), i => { curModel = keys[i]; curRun = 0; drawCurve(); });
  tabs(document.getElementById("run-tabs"), m.runs.map(x => x.run.replace("_eval", "")), curRun, i => { curRun = i; drawCurve(); });
  const W = 960, H = 280, l = 44, rt = 16, t = 16, b = 34, N = r.p.length - 1;
  const svg = el("svg", {viewBox: `0 0 ${W} ${H}`, role: "img"});
  const x = i => l + i / N * (W - l - rt), y = v => t + (1 - v) * (H - t - b);
  for (const v of [0, 0.25, 0.5, 0.75, 1]) { el("line", {x1: l, x2: W - rt, y1: y(v), y2: y(v), class: "grid"}, svg); txt(svg, l - 8, y(v) + 4, pct(v), {"text-anchor": "end"}); }
  txt(svg, (l + W - rt) / 2, H - 6, "CoT position (sentence index)", {"text-anchor": "middle"});
  for (let i = 0; i <= N; i += Math.max(1, Math.round(N / 10))) txt(svg, x(i), H - b + 16, i, {"text-anchor": "middle"});
  el("rect", {x: x(r.lock), y: t, width: x(N) - x(r.lock), height: H - t - b, fill: css("--band")}, svg);
  el("line", {x1: x(r.lock), x2: x(r.lock), y1: t, y2: H - b, stroke: css("--ink-3"), "stroke-dasharray": "4 3"}, svg);
  txt(svg, x(r.lock) + 6, t + 28, `lock-in L = ${r.lock}`, {});
  for (const [c, col, lab] of [[r.before_cut, "--before", "before"], [r.after_cut, "--after", "after"]]) {
    el("line", {x1: x(c), x2: x(c), y1: t, y2: H - b, stroke: css(col), "stroke-width": 3}, svg);
    txt(svg, x(c) + 4, H - b - 8, lab, {});
  }
  el("polyline", {points: r.p.map((v, i) => `${x(i)},${y(v)}`).join(" "), fill: "none", stroke: css("--ink"), "stroke-width": 2}, svg);
  r.p.forEach((v, i) => {
    el("circle", {cx: x(i), cy: y(v), r: 3, fill: css("--ink")}, svg);
    const hit = el("rect", {x: x(i) - (W - l - rt) / N / 2, y: t, width: (W - l - rt) / N, height: H - t - b, fill: "transparent"}, svg);
    hit.addEventListener("mousemove", e => showTip(e, `<b>Sentence ${i}</b> · P(EVAL) ${pct(v)}<br>${esc((r.chunks[i] || "(end of CoT)").slice(0, 160))}`));
    hit.addEventListener("mouseleave", hideTip);
  });
  document.getElementById("curve").replaceChildren(svg);
  document.getElementById("curve-note").textContent = `${r.run}: ${r.n_chunks} sentences. Before cut ${r.before_cut} (control P(EVAL) ${pct(r.before_ctl)}, mean effect ${sgn(r.before_effect)}); after cut ${r.after_cut} (control ${pct(r.after_ctl)}, mean effect ${sgn(r.after_effect)}).`;
}
drawCurve();

document.getElementById("all-table").innerHTML = Object.values(DATA.models).flatMap(m => m.runs.flatMap(r => r.rows.map(x =>
  `<tr><td>${esc(m.name)}</td><td>${esc(r.run)}</td><td>${esc(DATA.names[x.category])}</td><td class="n">${x.before_cut} / ${x.after_cut}</td><td class="n">${x.lock} / ${x.n_chunks}</td>
   <td class="n">${pct(x.before_ctl)} / ${pct(x.after_ctl)}</td><td class="n">${sgn(x.before_effect)}</td><td class="n">${sgn(x.after_effect)}</td></tr>`))).join("");
"""


def main():
    from insertion import INSERTIONS
    data = {"models": {k: load(k) for k in MODELS},
            "sentences": {c: s for (c, d), s in INSERTIONS.items() if d == "toward_deployment"},
            "names": {"user_context": "User context", "known_benchmark": "Known benchmark", "scenario_realism": "Scenario realism",
                      "task_format": "Task format", "problem_design": "Problem design"}}
    g = data["models"]["gemma"]
    body = BODY.replace("__NB__", "20 (Gemma) / 30 (Qwen)").replace("__NA__", str(g["n_after"]))
    html = (REPORT_DIR / "template.html").read_text()
    html = html.replace("<title>Eval-Awareness Anchors</title>", "<title>Lock-in Insertion Test</title>")
    script_start = html.index("const COLORS")
    head, rest = html[:script_start], html[script_start:]
    # keep the template's helpers (el, txt, tips, css, pct, sgn) but none of its chart code
    helpers = rest[: rest.index("const css")]
    helpers += "const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();\n"
    helpers += 'const pct = p => p == null ? "–" : Math.round(p * 100) + "%";\n'
    helpers += 'const sgn = v => v == null ? "–" : (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(2);\n'
    html = head + helpers + SCRIPT + "</script>\n"
    html = html.replace("__BODY__", body).replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    out = REPORT_DIR / "lockin.html"
    out.write_text(html)
    print(out, f"{len(html) / 1e3:.0f} kB")


if __name__ == "__main__":
    main()
