"""Build report/suppression.html: white-box attention suppression (Thought Anchors Fig. 6 + verdict effect), both models.

Needs results/suppression_analysis.json (analyze_suppression.py). Reuses the CSS and helpers of report/template.html.

Usage:
    python build_report_suppression.py
"""

import json

import numpy as np
from scipy.stats import mannwhitneyu, wilcoxon

from common import CAPSTONE_DIR

RES = CAPSTONE_DIR / "results"
REPORT_DIR = CAPSTONE_DIR / "report"


def lock_stats(m):
    pre, post, per_run = [], [], []
    for r in m["runs"]:
        d = np.abs(r["delta_logodds"])
        p, q = d[: r["lock"]], d[r["lock"]: r["N"] - 2]
        pre += list(p)
        post += list(q)
        if len(p) and len(q):
            per_run.append((p.mean(), q.mean()))
    pr = np.array(per_run)
    return {"pre": float(np.mean(pre)), "post": float(np.mean(post)), "n_pre": len(pre), "n_post": len(post),
            "runs_pre_gt_post": int((pr[:, 0] > pr[:, 1]).sum()), "n_runs": len(pr),
            "p_wilcoxon": float(wilcoxon(pr[:, 0], pr[:, 1], alternative="greater").pvalue),
            "p_mwu": float(mannwhitneyu(pre, post, alternative="greater").pvalue),
            "rel_margin_median": float(np.median([max(map(abs, r["delta_logodds"])) / abs(r["base_logodds"]) for r in m["runs"]])),
            "margin_median": float(np.median([abs(r["base_logodds"]) for r in m["runs"]]))}


BODY = r"""
<header class="col" style="display:grid;gap:16px">
  <div class="eyebrow">Thought anchors for eval awareness · white-box</div>
  <h1>Blocking attention to one sentence</h1>
  <p class="lede">For each base CoT we ran the model locally and, one sentence at a time, stopped every later token from attending to that sentence (all heads, all layers).
  We measured how much the rest of the reasoning changes (the paper's sentence × sentence KL matrix) and how much the final EVALUATION/DEPLOYMENT verdict moves.</p>
</header>

<section>
  <div class="findings" id="tiles"></div>
  <p class="note col">Verdict effect = change in log-odds of <code>&lt;label&gt;EVALUATION</code> vs <code>&lt;label&gt;DEPLOYMENT</code> (whole words scored, so tokenizer merges don't matter).
  Log-odds are used because P(EVAL) is saturated at 0 or 1 in every run. “Before / after lock-in” leaves out the last two sentences, where the model states its conclusion and the answer can simply copy it.</p>
</section>

<section>
  <div class="eyebrow">Main result</div>
  <h2>No single sentence carries the verdict</h2>
  <ul class="col" style="display:grid;gap:10px;margin:0;padding-left:20px" id="main-list"></ul>
</section>

<section>
  <div class="eyebrow">Per run</div>
  <h2>Verdict effect of each sentence, and the resampling importance</h2>
  <p class="col">Top: change in EVAL log-odds when attention to that sentence is blocked (blue = toward EVALUATION, orange = toward DEPLOYMENT). Bottom: the black-box resampling importance of the same sentence from the main study (P<sub>i+1</sub> − P<sub>i</sub>). The shaded area is after lock-in.</p>
  <div class="tabs" id="model-tabs" role="tablist"></div>
  <div class="tabs" id="run-tabs" role="tablist"></div>
  <div class="panel">
    <h3 id="run-title"></h3>
    <div class="chart" id="bars"></div>
    <div class="chart" id="imp"></div>
    <div class="legend"><span><i class="sw" style="background:var(--eval)"></i>Toward EVALUATION</span><span><i class="sw" style="background:var(--depl)"></i>Toward DEPLOYMENT</span><span><i class="sw" style="background:var(--band);outline:1px solid var(--rule)"></i>After lock-in</span></div>
    <p class="note" id="run-note"></p>
  </div>
</section>

<section>
  <div class="eyebrow">Figure 6 replication</div>
  <h2>Sentence × sentence suppression matrix</h2>
  <p class="col">Row i, column j: mean KL divergence of the model's next-token predictions inside sentence i when attention to sentence j is blocked, minus the run's average KL at the same distance i − j
  (raw KL is dominated by the sentence right before i). Darker = later sentence i depends more on sentence j than is typical at that distance. A thought anchor would show up as a dark column. Hover for values and text.</p>
  <div class="panel"><div class="chart" id="heat"></div>
    <div class="legend" id="heat-legend"></div></div>
</section>

<section>
  <div class="eyebrow">Reading it</div>
  <h2>What this supports, and what it doesn't</h2>
  <ul class="col" style="display:grid;gap:10px;margin:0;padding-left:20px">
    <li><b>The verdict is redundantly encoded.</b> Blocking any one sentence never flipped either model's verdict (0 of 1,000 interventions). For Gemma the largest single-sentence shift is a median 7% of its verdict margin (Qwen 23%): information about the verdict is spread across many sentences, or re-derivable from the transcript itself, which is never blocked.</li>
    <li><b>Gemma's pre-lock-in sentences matter more, consistent with H3.</b> Per sentence, blocking one from before lock-in moves Gemma's verdict more than blocking one after it (mean |Δ log-odds| 0.90 vs 0.61, higher in 17 of 20 runs, Wilcoxon p = 0.002). Qwen shows the same direction more weakly (0.79 vs 0.66, 12/18, p = 0.015).</li>
    <li><b>White-box and black-box importance barely agree.</b> Ranking sentences by verdict effect vs by resampling importance gives a median Spearman ρ of +0.08 (Qwen) / +0.19 (Gemma); the distance-corrected KL column gives +0.16 / +0.14. Direction agrees on only 55% / 53% of sentences with a clear resampling effect. Resampling asks “what if the model had written something else here”; suppression asks “what if the model could not see this text”. A sentence can change what the model writes next without being needed later, and the reverse.</li>
    <li><b>The stated conclusion is often the biggest lever.</b> In 9/20 Qwen runs and 7/20 Gemma runs the largest verdict effect comes from one of the last two sentences, where the model writes its conclusion. That is copying, not reasoning, and is why the lock-in comparison excludes them.</li>
    <li><b>Not shown:</b> anything about specific heads (receiver heads were not run); that multi-sentence suppression would also fail to flip the verdict; that quantisation is harmless for Qwen (FP8 here, same as the API runs; Gemma is the exact bf16 model).</li>
  </ul>
</section>

<section>
  <details><summary>Method</summary><div><ul>
    <li><b>Models:</b> Qwen3-32B as <code>Qwen/Qwen3-32B-FP8</code> (official block-FP8, all on GPU) and Gemma 4 26B-A4B as <code>google/gemma-4-26B-A4B-it</code> in bf16 with 12 of 36 modules offloaded to CPU RAM, on one L40S (46 GB). transformers 5.18, sdpa attention.</li>
    <li><b>Input:</b> the 20 main base CoTs per model (10 prompts × EVAL/DEPL), as the original text: chat template + reasoning open + CoT + reasoning close + <code>&lt;label&gt;</code>, scored as two sequences ending in EVALUATION / DEPLOYMENT.</li>
    <li><b>Suppression:</b> a wrapper around transformers' sdpa attention function materialises each layer's own mask (causal or sliding-window) and sets the columns of sentence j to False for every query position after sentence j, in all heads of all layers. Checked on tiny Gemma 4 and Qwen3 models: identical logits when nothing is suppressed (also past Gemma's 1,024-token sliding window), and suppression changes only positions after the sentence.</li>
    <li><b>Matrix:</b> KL(baseline ‖ suppressed) of the next-token distribution at each position, averaged over the predictions of sentence i's tokens. Distance correction: subtract the run's mean KL over all pairs at the same distance i − j.</li>
    <li><b>Lock-in:</b> as in the lock-in report, the first sentence after which every resampled P(EVAL) stays within 0.15 of the final value.</li>
    <li><b>Code:</b> <code>prepare_suppression.py</code> → <code>suppression_kl.py</code> (GPU) → <code>analyze_suppression.py</code> → <code>build_report_suppression.py</code>. Raw results: <code>results/suppression_qwen.json</code>, <code>results/gemma/suppression_gemma.json</code>. Runtime: Qwen 4 min, Gemma 13 min.</li>
  </ul></div></details>
</section>
"""

SCRIPT = r"""
const M = DATA.models, KEYS = Object.keys(M);
const tiles = document.getElementById("tiles");
for (const k of KEYS) { const s = M[k].summary, l = M[k].lock;
  tiles.insertAdjacentHTML("beforeend", `
   <div class="finding"><div class="eyebrow">${esc(s.name)}</div><div class="num">${s.flips} / ${s.n_chunks}</div><p>Single-sentence suppressions that flip the verdict.</p></div>
   <div class="finding"><div class="eyebrow">${esc(s.name)} · lock-in</div><div class="num">${l.pre.toFixed(2)} → ${l.post.toFixed(2)}</div><p>Mean |Δ log-odds| before vs after lock-in; before is larger in <b>${l.runs_pre_gt_post}/${l.n_runs}</b> runs (p = ${l.p_wilcoxon.toFixed(3)}).</p></div>`); }
document.getElementById("main-list").innerHTML = KEYS.map(k => { const s = M[k].summary, l = M[k].lock;
  return `<li><b>${esc(s.name)}:</b> verdict margin median ${l.margin_median.toFixed(1)} log-odds; the largest single-sentence shift is a median ${pct(l.rel_margin_median)} of it.
   Verdict effect vs resampling importance: Spearman ρ ${sgn(s.median_rho_verdict_vs_importance)} (median over runs); same direction on ${s.sign_agree}/${s.n_big} sentences with |importance| ≥ 0.2.</li>`; }).join("");

let cm = "gemma", cr = 0;
function tabs(host, items, sel, pick) {
  host.replaceChildren(...items.map((t, i) => { const b = document.createElement("button"); b.className = "tab"; b.role = "tab";
    b.textContent = t; b.setAttribute("aria-selected", i === sel); b.onclick = () => pick(i); return b; })); }

function barChart(host, vals, r, opts) {
  const W = 960, H = opts.h, l = 52, rt = 12, t = 10, b = opts.xlab ? 30 : 10, N = vals.length;
  const svg = el("svg", {viewBox: `0 0 ${W} ${H}`, role: "img"});
  const lim = opts.lim || Math.max(0.5, ...vals.map(v => Math.abs(v || 0)));
  const bw = (W - l - rt) / N, x = i => l + i * bw, y = v => t + (1 - (v + lim) / (2 * lim)) * (H - t - b);
  el("rect", {x: x(r.lock), y: t, width: x(N) - x(r.lock), height: H - t - b, fill: css("--band")}, svg);
  for (const v of [-lim, 0, lim]) { el("line", {x1: l, x2: W - rt, y1: y(v), y2: y(v), class: "grid"}, svg);
    txt(svg, l - 8, y(v) + 4, (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(opts.dec), {"text-anchor": "end"}); }
  txt(svg, l + 6, t + 12, opts.label, {style: "font-weight:500"});
  vals.forEach((v, i) => { if (v == null) return;
    const up = v >= 0, h = Math.max(1, Math.abs(y(v) - y(0)));
    el("rect", {x: x(i) + 1, y: up ? y(v) : y(0), width: Math.max(2, bw - 2), height: h, rx: 2,
      fill: css(opts.color(v))}, svg);
    const hit = el("rect", {x: x(i), y: t, width: bw, height: H - t - b, fill: "transparent"}, svg);
    hit.addEventListener("mousemove", e => showTip(e, `<b>Sentence ${i}</b>${i >= r.lock ? " (after lock-in)" : ""}<br>${opts.name}: ${sgn(v)}<br>${esc(r.chunks[i].slice(0, 160))}`));
    hit.addEventListener("mouseleave", hideTip); });
  if (opts.xlab) for (let i = 0; i < N; i += Math.max(1, Math.round(N / 12))) txt(svg, x(i) + bw / 2, H - 10, i, {"text-anchor": "middle"});
  host.replaceChildren(svg);
}

function heat(r) {
  const N = r.N, W = 960, l = 40, t = 10, cell = Math.min(22, (W - l - 10) / N), H = t + N * cell + 34;
  const svg = el("svg", {viewBox: `0 0 ${W} ${H}`, role: "img"});
  const vals = r.matrix_dist.flat().filter(v => v != null), hi = Math.max(1e-6, ...vals.map(v => Math.max(0, v)));
  for (let i = 0; i < N; i++) for (let j = 0; j < i; j++) { const v = r.matrix_dist[i][j]; if (v == null) continue;
    const a = Math.max(0, v) / hi;
    el("rect", {x: l + j * cell, y: t + i * cell, width: cell - 1, height: cell - 1, fill: css("--accent"), "fill-opacity": (0.04 + 0.96 * a).toFixed(3)}, svg);
    const hit = el("rect", {x: l + j * cell, y: t + i * cell, width: cell, height: cell, fill: "transparent"}, svg);
    hit.addEventListener("mousemove", e => showTip(e, `<b>block ${j} → effect inside ${i}</b><br>KL ${r.matrix[i][j].toFixed(3)} (distance-corrected ${sgn(v)})<br><i>j:</i> ${esc(r.chunks[j].slice(0, 100))}<br><i>i:</i> ${esc(r.chunks[i].slice(0, 100))}`));
    hit.addEventListener("mouseleave", hideTip); }
  el("line", {x1: l + r.lock * cell, x2: l + r.lock * cell, y1: t, y2: t + N * cell, stroke: css("--ink-3"), "stroke-dasharray": "4 3"}, svg);
  txt(svg, l + r.lock * cell + 4, t + N * cell + 14, `lock-in L = ${r.lock}`, {});
  txt(svg, l, t + N * cell + 28, "blocked sentence j →", {}); txt(svg, 4, t + 10, "i ↓", {});
  for (let i = 0; i < N; i += Math.max(1, Math.round(N / 10))) { txt(svg, l - 6, t + i * cell + cell * 0.7, i, {"text-anchor": "end"}); txt(svg, l + i * cell + cell / 2, t + N * cell + 14 + (i === r.lock ? 0 : 0), "", {}); }
  document.getElementById("heat").replaceChildren(svg);
  document.getElementById("heat-legend").innerHTML = `<span><i class="sw" style="background:var(--accent);opacity:.1"></i>typical for that distance</span><span><i class="sw" style="background:var(--accent)"></i>${hi.toFixed(2)} nats above typical</span>`;
}

function draw() {
  const m = M[cm], r = m.runs[cr];
  tabs(document.getElementById("model-tabs"), KEYS.map(k => M[k].summary.name), KEYS.indexOf(cm), i => { cm = KEYS[i]; cr = 0; draw(); });
  tabs(document.getElementById("run-tabs"), m.runs.map(x => x.run), cr, i => { cr = i; draw(); });
  document.getElementById("run-title").textContent = `${r.run} · base verdict ${r.base_label} · log-odds ${sgn(r.base_logodds)}`;
  barChart(document.getElementById("bars"), r.delta_logodds, r, {h: 200, dec: 1, label: "Δ log-odds (suppression)", name: "Δ log-odds EVAL",
    color: v => v >= 0 ? "--eval" : "--depl"});
  barChart(document.getElementById("imp"), r.importance, r, {h: 150, dec: 2, lim: 1, xlab: true, label: "resampling importance", name: "importance",
    color: v => v >= 0 ? "--eval" : "--depl"});
  document.getElementById("run-note").textContent = `${r.N} sentences, lock-in at ${r.lock}. Largest suppression effect: sentence ${r.top_verdict_chunk} (${sgn(r.delta_logodds[r.top_verdict_chunk])}), ` +
    `${pct(Math.abs(r.delta_logodds[r.top_verdict_chunk]) / Math.abs(r.base_logodds))} of the margin. Spearman ρ with |importance|: ${sgn(r.rho_verdict_vs_importance)}.`;
  heat(r);
}
draw();
"""


def main():
    a = json.loads((RES / "suppression_analysis.json").read_text())
    data = {"models": {}}
    for k in ["gemma", "qwen"]:
        m = a[k]
        for r in m["runs"]:
            M = np.array([[np.nan if x is None else x for x in row] for row in r["matrix"]])
            N = r["N"]
            D = {d: np.nanmean([M[i, i - d] for i in range(d, N)]) for d in range(1, N)}
            r["matrix_dist"] = [[float(M[i, j] - D[i - j]) if j < i else None for j in range(N)] for i in range(N)]
            r["matrix"] = [[None if np.isnan(x) else float(x) for x in row] for row in M]
            r.pop("matrix_norm", None)
        data["models"][k] = {"summary": m["summary"], "lock": lock_stats(m), "runs": m["runs"]}
    html = (REPORT_DIR / "template.html").read_text().replace("<title>Eval-Awareness Anchors</title>", "<title>Attention Suppression</title>")
    i = html.index("const COLORS")
    head, rest = html[:i], html[i:]
    helpers = rest[: rest.index("const css")]
    helpers += "const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();\n"
    helpers += 'const pct = p => p == null ? "–" : Math.round(p * 100) + "%";\n'
    helpers += 'const sgn = v => v == null ? "–" : (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(2);\n'
    html = head + helpers + SCRIPT + "</script>\n"
    html = html.replace("__BODY__", BODY).replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    out = REPORT_DIR / "suppression.html"
    out.write_text(html)
    print(out, f"{len(html) / 1e3:.0f} kB")


if __name__ == "__main__":
    main()
