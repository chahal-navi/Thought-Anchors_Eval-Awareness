"""Build report/causal_graph.html: sentence-to-sentence causal graphs from attention suppression (both models).

Edge j -> i: how much the model's token predictions inside sentence i change (mean KL, nats) when no later token
may attend to sentence j, minus the run's mean KL at that distance i - j (so edges to the next sentence don't
dominate just for being close). Node size: the sentence's outgoing influence (mean of its distance-corrected
column) = its "thought anchor" score. Centre node V: the verdict; its edges are the sentences whose suppression
moves the EVAL/DEPLOY log-odds most.

Same idea as the notebook's sentence-to-sentence causal graph (utils.chunk_graph_html), but the edges come from
white-box suppression (paper Fig. 6) instead of resampling match rates.

Needs results/suppression_analysis.json (analyze_suppression.py).

Usage:
    python build_report_causal.py
"""

import json
import re
from collections import defaultdict

import numpy as np

from common import CAPSTONE_DIR

RES = CAPSTONE_DIR / "results"
REPORT_DIR = CAPSTONE_DIR / "report"
MIN_ROWS = 5  # an anchor needs at least this many later sentences, so its column mean isn't a 1-2 value fluke


def rnd(x, k=4):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), k)


def per_run(r):
    N = r["N"]
    M = np.array([[np.nan if x is None else x for x in row] for row in r["matrix"]])
    D = {d: np.nanmean([M[i, i - d] for i in range(d, N)]) for d in range(1, N)}
    Md = [[rnd(M[i, j] - D[i - j]) if j < i else None for j in range(N)] for i in range(N)]
    infl = [rnd(x) for x in r["influence"]]
    eligible = [j for j in range(N - MIN_ROWS) if infl[j] is not None]
    anchors = sorted(eligible, key=lambda j: -infl[j])[:5]
    return {
        "run": r["run"], "N": N, "lock": r["lock"], "base_label": r["base_label"], "base_logodds": rnd(r["base_logodds"], 2),
        "chunks": r["chunks"], "tags": r["tags"], "importance": [rnd(x, 3) for x in r["importance"]],
        "dlo": [rnd(x, 3) for x in r["delta_logodds"]], "influence": infl,
        "md": Md, "raw": [[rnd(x) for x in row] for row in M.tolist()], "anchors": anchors, "eligible": len(eligible),
    }


DEFN = re.compile(r"\*(Evaluation|Deployment)[^*]*:\s*\*|^\W*(Evaluation|Deployment)( characteristics)?:")
QUESTION = re.compile(r"^\W*(Does it look|Is (it|there|this)|Could it be|Does the|Is the)\b.*\?\s*$")
GROUPS = {  # which sentences are top-3 anchors more often than a random pick of 3 eligible sentences per run?
    "pre_lock": lambda r, j: j < r["lock"],
    "opening": lambda r, j: j < 2,
    "definition": lambda r, j: bool(DEFN.search(r["chunks"][j].strip())),   # "*Evaluation:* usually involves ..."
    "question": lambda r, j: bool(QUESTION.search(r["chunks"][j].strip())),  # "Does it look like a test?"
}


def aggregate(runs, n_perm=20000, seed=0):
    """Where the top-3 anchors sit, against a permutation null (3 random eligible sentences per run), and score by type."""
    rng = np.random.default_rng(seed)
    el = [[j for j in range(r["N"] - MIN_ROWS) if r["influence"][j] is not None] for r in runs]
    keep = [(r, e) for r, e in zip(runs, el) if len(e) >= 3]
    out = {"n_top": 3 * len(keep)}
    sims = {g: np.zeros(n_perm) for g in GROUPS}
    for r, e in keep:
        e = np.array(e)
        picks = np.argsort(rng.random((n_perm, len(e))), axis=1)[:, :3]
        for g, f in GROUPS.items():
            hit = np.array([f(r, j) for j in e])
            sims[g] += hit[picks].sum(1)
    for g, f in GROUPS.items():
        obs = sum(f(r, j) for r, _ in keep for j in r["anchors"][:3])
        out[g] = {"obs": int(obs), "null": float(sims[g].mean()),
                  "p_low": float((sims[g] <= obs).mean()), "p_high": float((sims[g] >= obs).mean())}
    by_tag = defaultdict(list)
    for r, e in zip(runs, el):
        for j in e:
            by_tag[r["tags"][j]].append(r["influence"][j])
    out["tags"] = sorted([{"tag": t, "n": len(v), "mean": float(np.mean(v)), "se": float(np.std(v, ddof=1) / np.sqrt(len(v)))}
                          for t, v in by_tag.items() if len(v) >= 10], key=lambda d: -d["mean"])
    return out


BODY = r"""
<header class="col" style="display:grid;gap:16px">
  <div class="eyebrow">Thought anchors for eval awareness · white-box causal graph</div>
  <h1>Which sentences the rest of the reasoning depends on</h1>
  <p class="lede">Each dot is a sentence of the CoT, clockwise from the top. An arrow j → i means: when the model cannot attend to sentence j,
  its predictions inside sentence i change more than is typical for sentences that far apart. Big dots are thought anchors, sentences many later sentences depend on.
  The centre dot is the verdict.</p>
</header>

<section>
  <div class="findings" id="tiles"></div>
  <p class="note col">Anchor score = mean distance-corrected KL over all later sentences. Only sentences with at least 5 later sentences can be ranked as anchors, so a score isn't an average of one or two values.</p>
</section>

<section>
  <div class="eyebrow">Per run</div>
  <h2>Causal graph</h2>
  <div class="tabs" id="model-tabs" role="tablist" aria-label="Model"></div>
  <div class="tabs" id="run-tabs" role="tablist" aria-label="Run"></div>
  <div class="panel">
    <div style="display:flex;flex-wrap:wrap;gap:10px 24px;align-items:center;justify-content:space-between">
      <h3 id="run-title"></h3>
      <div style="display:flex;gap:16px;align-items:center;flex-wrap:wrap;font-size:.85rem;color:var(--ink-2)">
        <div class="tabs" id="mode-tabs" role="tablist" aria-label="Edge weights"></div>
        <label>edges per sentence <input type="range" id="k" min="1" max="5" value="2" style="vertical-align:middle;width:90px"> <span id="kv" class="mono">2</span></label>
      </div>
    </div>
    <div class="two" style="grid-template-columns:minmax(0,1.35fr) minmax(260px,1fr)">
      <div class="chart" id="graph"></div>
      <div style="display:grid;gap:14px;align-content:start;min-width:0">
        <div id="card" style="display:grid;gap:8px"></div>
        <div><div class="eyebrow" style="margin-bottom:8px">Top anchors in this run</div><div class="chunks" id="anchors" style="max-height:none"></div></div>
      </div>
    </div>
    <div class="legend" id="legend"></div>
    <p class="note">Hover over a sentence to see its strongest incoming and outgoing edges; click one to pin it, or click an anchor in the list. The arc outside the ring marks sentences after lock-in.
    Grey arrows: sentence → sentence. Coloured arrows into the centre: the sentences whose suppression moves the verdict most (blue toward EVALUATION, orange toward DEPLOYMENT).</p>
  </div>
</section>

<section>
  <div class="eyebrow">Across runs</div>
  <h2>What kind of sentence is an anchor</h2>
  <p class="col">Mean anchor score by sentence type, over all sentences with at least 5 later sentences (±1 SE). Zero = a typical sentence.</p>
  <div class="two" id="tagbars"></div>
</section>

<section>
  <div class="eyebrow">Reading it</div>
  <h2>What the graphs show</h2>
  <ul class="col" style="display:grid;gap:10px;margin:0;padding-left:20px" id="reading"></ul>
</section>

<section>
  <details><summary>Method</summary><div><ul style="display:grid;gap:8px;margin:0;padding-left:20px">
    <li><b>Suppression:</b> for each sentence j, every token after j is blocked from attending to j's tokens, in all heads of all layers, in one forward pass over the original CoT (teacher-forced). Qwen3-32B in FP8; Gemma 4 26B-A4B in bf16. Same runs as the suppression report.</li>
    <li><b>Edge j → i:</b> mean over sentence i's tokens of KL(original ‖ suppressed) of the next-token distribution, minus the mean KL of all sentence pairs at the same distance i − j in that run. Raw KL mostly falls with distance, so without the correction every sentence's strongest edge is to the next sentence. The “raw KL” toggle shows the uncorrected values.</li>
    <li><b>Edges drawn:</b> as in the notebook's <code>chunk_graph_html</code>, each sentence's top k incoming and top k outgoing edges (positive only); the union is drawn.</li>
    <li><b>Verdict edges:</b> the 3 sentences with the largest |Δ log-odds| of <code>EVALUATION</code> vs <code>DEPLOYMENT</code> when suppressed. Different unit from the sentence edges, so they are scaled separately.</li>
    <li><b>Difference from the notebook's graph:</b> the notebook's edges are black-box (does sentence i still appear in resamples when j is resampled away). These are white-box: does the model use j's text when it writes i. A sentence can be needed to read later text without changing what gets written, and the reverse.</li>
    <li><b>Code:</b> <code>suppression_kl.py</code> (GPU) → <code>analyze_suppression.py</code> → <code>build_report_causal.py</code>.</li>
  </ul></div></details>
</section>
"""

SCRIPT = r"""
const M = DATA.models, KEYS = Object.keys(M), MIN_ROWS = DATA.min_rows;
let cm = "gemma", cr = 0, mode = "md", K = 2, hovered = -1, pinned = -1;

const pv = (x, side) => { const v = x[side]; return v < 0.001 ? "p < 0.001" : "p = " + v.toFixed(3); };
const tile = (name, x, n, what, side) => `<div class="finding"><div class="eyebrow">${esc(name)}</div><div class="num">${x.obs} / ${n}</div>
  <p>${what} (${x.null.toFixed(1)} expected for random picks, ${pv(x, side)}).</p></div>`;
document.getElementById("tiles").innerHTML =
  tile(M.gemma.name, M.gemma.agg.definition, M.gemma.agg.n_top, "Top-3 anchors that are a <b>definition</b> line of its checklist, such as “<i>Evaluation:</i> usually involves …”", "p_high") +
  tile(M.gemma.name, M.gemma.agg.pre_lock, M.gemma.agg.n_top, "Top-3 anchors that come <b>before</b> lock-in", "p_low") +
  tile(M.qwen.name, M.qwen.agg.opening, M.qwen.agg.n_top, "Top-3 anchors that are one of its <b>first two</b> sentences (“Okay, let's see.” and restating the user's request)", "p_high");

function tabs(host, items, sel, pick) {
  host.replaceChildren(...items.map((t, i) => { const b = document.createElement("button"); b.className = "tab"; b.role = "tab";
    b.textContent = t; b.setAttribute("aria-selected", i === sel); b.onclick = () => pick(i); return b; })); }

const S = 720, C = S / 2, R = 280;
function layout(r) {
  const pos = [];
  for (let i = 0; i < r.N; i++) { const a = 2 * Math.PI * i / r.N - Math.PI / 2; pos.push({x: C + R * Math.cos(a), y: C + R * Math.sin(a), a}); }
  const inf = r.influence.map((v, i) => v == null || i >= r.N - MIN_ROWS ? 0 : Math.max(0, v)), hi = Math.max(1e-6, ...inf);
  pos.forEach((p, i) => p.r = 5 + 15 * Math.sqrt(inf[i] / hi));
  return pos;
}
function weights(r) { const W = mode === "md" ? r.md : r.raw; return (j, i) => W[i] && W[i][j]; }
function topEdges(r, node, k) {
  const w = weights(r), out = [], inn = [];
  for (let i = node + 1; i < r.N; i++) { const v = w(node, i); if (v != null && v > 0) out.push({s: node, d: i, w: v}); }
  for (let j = 0; j < node; j++) { const v = w(j, node); if (v != null && v > 0) inn.push({s: j, d: node, w: v}); }
  const by = (a, b) => b.w - a.w; return [...out.sort(by).slice(0, k), ...inn.sort(by).slice(0, k)];
}
function verdictEdges(r) { return r.dlo.map((v, j) => ({j, v})).sort((a, b) => Math.abs(b.v) - Math.abs(a.v)).slice(0, 3); }

function curve(p, q) { const mx = (p.x + q.x) / 2, my = (p.y + q.y) / 2, cx = mx + (C - mx) * 0.45, cy = my + (C - my) * 0.45;
  return {d: `M${p.x},${p.y} Q${cx},${cy} ${q.x},${q.y}`, cx, cy}; }
function trim(p, q, rp, rq) { const dx = q.x - p.x, dy = q.y - p.y, L = Math.hypot(dx, dy) || 1;
  return [{x: p.x + dx / L * rp, y: p.y + dy / L * rp}, {x: q.x - dx / L * rq, y: q.y - dy / L * rq}]; }

function drawGraph() {
  const r = M[cm].runs[cr], pos = layout(r), act = pinned >= 0 ? pinned : hovered;
  const svg = el("svg", {viewBox: `0 0 ${S} ${S}`, role: "img", "aria-label": `Causal graph for ${r.run}`});
  const defs = el("defs", {}, svg);
  for (const [id, c] of [["ah", "--ink-2"], ["ahe", "--eval"], ["ahd", "--depl"]]) {
    const m = el("marker", {id, viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse"}, defs);
    el("path", {d: "M0,0 L10,5 L0,10 z", fill: css(c)}, m); }
  // lock-in arc
  if (r.lock < r.N) { const a0 = 2 * Math.PI * (r.lock - 0.4) / r.N - Math.PI / 2, a1 = 2 * Math.PI * (r.N - 0.6) / r.N - Math.PI / 2, RR = R + 34;
    const big = a1 - a0 > Math.PI ? 1 : 0;
    el("path", {d: `M${C + RR * Math.cos(a0)},${C + RR * Math.sin(a0)} A${RR},${RR} 0 ${big} 1 ${C + RR * Math.cos(a1)},${C + RR * Math.sin(a1)}`,
      fill: "none", stroke: css("--ink-3"), "stroke-width": 3, "stroke-linecap": "round", opacity: 0.5}, svg);
    const am = (a0 + a1) / 2; txt(svg, C + (RR + 14) * Math.cos(am), C + (RR + 14) * Math.sin(am) + 4, "after lock-in",
      {"text-anchor": Math.cos(am) > 0.2 ? "start" : Math.cos(am) < -0.2 ? "end" : "middle", style: "fill:var(--ink-3)"}); }
  // global edges: union of each node's top-K
  const all = new Map();
  for (let n = 0; n < r.N; n++) for (const e of topEdges(r, n, K)) all.set(e.s + "," + e.d, e);
  const edges = [...all.values()], hi = Math.max(1e-6, ...edges.map(e => e.w));
  const actSet = act >= 0 ? new Set(topEdges(r, act, Math.max(K, 3)).map(e => e.s + "," + e.d)) : null;
  for (const e of edges) { if (actSet && actSet.has(e.s + "," + e.d)) continue;
    el("path", {d: curve(pos[e.s], pos[e.d]).d, fill: "none", stroke: css("--ink-3"), "stroke-width": 0.8 + 1.4 * e.w / hi,
      opacity: actSet ? 0.07 : (0.15 + 0.5 * e.w / hi).toFixed(2)}, svg); }
  // verdict node + edges
  const V = {x: C, y: C, r: 16}, ve = verdictEdges(r), vhi = Math.max(1e-6, ...ve.map(e => Math.abs(e.v)));
  for (const e of ve) { const p = pos[e.j], [a, b] = trim(p, V, p.r + 2, V.r + 4), id = e.v >= 0 ? "ahe" : "ahd";
    const dim = act >= 0 && act !== e.j;
    el("line", {x1: a.x, y1: a.y, x2: b.x, y2: b.y, stroke: css(e.v >= 0 ? "--eval" : "--depl"), "stroke-width": 1.5 + 2.5 * Math.abs(e.v) / vhi,
      "marker-end": `url(#${id})`, opacity: dim ? 0.15 : 0.85}, svg); }
  el("circle", {cx: C, cy: C, r: V.r, fill: css("--surface"), stroke: css("--ink"), "stroke-width": 2}, svg);
  txt(svg, C, C + 4, "V", {"text-anchor": "middle", style: "fill:var(--ink);font-weight:600;font-size:13px"});
  txt(svg, C, C + V.r + 16, `verdict ${r.base_label === "EVALUATION" ? "EVAL" : "DEPLOY"}`, {"text-anchor": "middle", style: "fill:var(--ink-3)"});
  // highlighted edges
  const wl = {};
  if (actSet) { const ae = topEdges(r, act, Math.max(K, 3)), ahi = Math.max(1e-6, ...ae.map(e => e.w));
    for (const e of ae) { const c = curve(pos[e.s], pos[e.d]);
      const [a] = trim(pos[e.s], {x: c.cx, y: c.cy}, pos[e.s].r + 2, 0), [, b] = trim({x: c.cx, y: c.cy}, pos[e.d], 0, pos[e.d].r + 3);
      el("path", {d: `M${a.x},${a.y} Q${c.cx},${c.cy} ${b.x},${b.y}`, fill: "none", stroke: css("--ink"), "stroke-width": 1.5 + 2 * e.w / ahi,
        "marker-end": "url(#ah)", opacity: 0.9}, svg);
      wl[e.s === act ? e.d : e.s] = (mode === "md" ? "+" : "") + e.w.toFixed(2); } }
  // nodes
  pos.forEach((p, i) => { const conn = actSet && [...actSet].some(k => k.split(",").map(Number).includes(i));
    const dim = act >= 0 && i !== act && !conn;
    const g = el("g", {style: "cursor:pointer", opacity: dim ? 0.3 : 1}, svg);
    el("circle", {cx: p.x, cy: p.y, r: p.r + (i === act ? 3 : 0), fill: COLORS[r.tags[i]] || COLORS.other, stroke: css(i === act ? "--ink" : "--surface"), "stroke-width": i === act ? 2.5 : 2}, g);
    const c = Math.cos(p.a), lr = p.r + (wl[i] ? 16 : 11), anc = wl[i] ? (c > 0.3 ? "start" : c < -0.3 ? "end" : "middle") : "middle";
    const t = txt(g, p.x + c * lr, p.y + Math.sin(p.a) * lr + 4, wl[i] ? `${i}: ${wl[i]}` : i, {"text-anchor": anc,
      style: wl[i] || i === act ? "fill:var(--ink);font-size:11px;font-weight:700;font-family:var(--f-mono)" : "fill:var(--ink-2);font-size:10px"});
    if (wl[i]) t.setAttribute("paint-order", "stroke"), t.setAttribute("stroke", css("--surface")), t.setAttribute("stroke-width", 4);
    el("circle", {cx: p.x, cy: p.y, r: Math.max(p.r + 6, 12), fill: "transparent"}, g);
    g.addEventListener("mouseenter", ev => { if (hovered !== i) { hovered = i; drawGraph(); } showTip(ev, nodeTip(r, i)); });
    g.addEventListener("mousemove", ev => showTip(ev, nodeTip(r, i)));
    g.addEventListener("mouseleave", () => { hideTip(); if (hovered === i) { hovered = -1; drawGraph(); } });
    g.addEventListener("click", () => { pinned = pinned === i ? -1 : i; drawGraph(); card(); anchorList(); }); });
  document.getElementById("graph").replaceChildren(svg);
}
function nodeTip(r, i) { return `<b>Sentence ${i}</b> · ${esc(NAMES[r.tags[i]] || r.tags[i])}${i >= r.lock ? " · after lock-in" : ""}<br>${esc(r.chunks[i].slice(0, 160))}<br>anchor score ${sgn(r.influence[i])} · Δ log-odds ${sgn(r.dlo[i])}`; }

function card() {
  const r = M[cm].runs[cr], i = pinned >= 0 ? pinned : r.anchors[0], host = document.getElementById("card");
  if (i == null) { host.innerHTML = ""; return; }
  const e = topEdges(r, i, 3), outs = e.filter(x => x.s === i), ins = e.filter(x => x.d === i);
  const li = (k, w) => `<li><span class="mono">${k}</span> ${esc(r.chunks[k].slice(0, 70))}${r.chunks[k].length > 70 ? "…" : ""} <span class="mono" style="color:var(--ink-3)">${w.toFixed(2)}</span></li>`;
  host.innerHTML = `<div class="eyebrow">${pinned >= 0 ? "Selected" : "Strongest anchor"} · sentence ${i}</div>
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><i class="sw" style="background:${COLORS[r.tags[i]]}"></i><span style="font-size:.85rem">${esc(NAMES[r.tags[i]] || r.tags[i])}</span>
      ${i >= r.lock ? '<span class="pill" style="color:var(--ink-3)">after lock-in</span>' : '<span class="pill" style="color:var(--accent)">before lock-in</span>'}</div>
    <p style="color:var(--ink)">${esc(r.chunks[i])}</p>
    <table><tr><td>anchor score</td><td class="n">${sgn(r.influence[i])}</td></tr>
      <tr><td>verdict Δ log-odds when blocked</td><td class="n">${sgn(r.dlo[i])}</td></tr>
      <tr><td>resampling importance</td><td class="n">${sgn(r.importance[i])}</td></tr></table>
    ${outs.length ? `<div class="note">Drives later sentences</div><ul style="margin:0;padding-left:18px;font-size:.82rem;color:var(--ink-2)">${outs.map(x => li(x.d, x.w)).join("")}</ul>` : ""}
    ${ins.length ? `<div class="note">Depends on earlier sentences</div><ul style="margin:0;padding-left:18px;font-size:.82rem;color:var(--ink-2)">${ins.map(x => li(x.s, x.w)).join("")}</ul>` : ""}`;
}
function anchorList() {
  const r = M[cm].runs[cr], host = document.getElementById("anchors");
  host.replaceChildren(...r.anchors.map(j => { const d = document.createElement("div"); d.className = "chunk" + (j === pinned ? " hl" : ""); d.style.cursor = "pointer";
    d.innerHTML = `<span class="idx">${j}</span><i class="sw" style="background:${COLORS[r.tags[j]]}"></i><span>${esc(r.chunks[j].slice(0, 90))}${r.chunks[j].length > 90 ? "…" : ""}</span><span class="val">${sgn(r.influence[j])}</span>`;
    d.onclick = () => { pinned = pinned === j ? -1 : j; drawGraph(); card(); anchorList(); };
    d.onmouseenter = () => { if (hovered !== j) { hovered = j; drawGraph(); } }; d.onmouseleave = () => { hovered = -1; drawGraph(); }; return d; }));
}
function legend() { const r = M[cm].runs[cr], seen = [...new Set(r.tags)];
  document.getElementById("legend").innerHTML = seen.map(t => `<span><i class="sw" style="background:${COLORS[t]};border-radius:50%"></i>${esc(NAMES[t] || t)}</span>`).join("") +
    `<span><i class="ln" style="background:var(--eval)"></i>verdict edge, toward EVAL</span><span><i class="ln" style="background:var(--depl)"></i>verdict edge, toward DEPLOY</span>`; }

function drawAll() {
  const m = M[cm], r = m.runs[cr];
  tabs(document.getElementById("model-tabs"), KEYS.map(k => M[k].name), KEYS.indexOf(cm), i => { cm = KEYS[i]; cr = 0; pinned = -1; drawAll(); });
  tabs(document.getElementById("run-tabs"), m.runs.map(x => x.run), cr, i => { cr = i; pinned = -1; drawAll(); });
  tabs(document.getElementById("mode-tabs"), ["distance-corrected", "raw KL"], mode === "md" ? 0 : 1, i => { mode = i ? "raw" : "md"; drawAll(); });
  document.getElementById("run-title").textContent = `${r.run} · ${r.N} sentences · lock-in at ${r.lock} · verdict log-odds ${sgn(r.base_logodds)}`;
  drawGraph(); card(); anchorList(); legend();
}
const kin = document.getElementById("k");
kin.oninput = () => { K = +kin.value; document.getElementById("kv").textContent = K; drawGraph(); };
drawAll();

const tb = document.getElementById("tagbars");
for (const k of KEYS) { const d = document.createElement("div"); d.className = "panel";
  d.innerHTML = `<h3>${esc(M[k].name)}</h3>`; const c = document.createElement("div"); c.className = "chart"; d.appendChild(c); tb.appendChild(d);
  const rows = M[k].agg.tags.map(t => ({label: `${NAMES[t.tag] || t.tag} (n=${t.n})`, value: t.mean, se: t.se, color: COLORS[t.tag],
    tip: `<b>${esc(NAMES[t.tag] || t.tag)}</b><br>mean anchor score ${sgn(t.mean)} ± ${t.se.toFixed(2)} over ${t.n} sentences`}));
  const lim = Math.max(0.15, ...rows.map(r => Math.abs(r.value) + r.se)); hbars(c, rows, {domain: [-lim, lim], W: 520, L: 190, label: "anchor score by type"}); }

const q = M.qwen.agg, g = M.gemma.agg;
document.getElementById("reading").innerHTML = [
  `<b>Gemma builds a scaffold early and leans on it.</b> Its CoT usually opens with a checklist: what an evaluation looks like (“<i>Evaluation:</i> Benchmarks usually involve specific tasks…”), what deployment looks like (“<i>Deployment:</i> Real users ask all sorts of things…”), then diagnostic questions (“Does it look like a test?”). These definition lines are ${g.definition.obs} of its ${g.n_top} top-3 anchors (${g.definition.null.toFixed(1)} expected), and the diagnostic questions another ${g.question.obs} (${g.question.null.toFixed(1)} expected). Later sentences check the prompt against these lines, so blocking them changes the most downstream text.`,
  `<b>…but Gemma's anchors are not where its verdict is decided.</b> Only ${g.pre_lock.obs} of ${g.n_top} top-3 anchors come before the resampling lock-in point (${g.pre_lock.null.toFixed(1)} expected, ${pv(g.pre_lock, "p_low")}). Lock-in is at sentence 2–12, so the decision is made in the first sentences (reading the prompt), while the scaffold that organises the rest of the text comes just after. What the text depends on and what the verdict depends on are different sentences.`,
  `<b>Qwen's anchors are its opening.</b> ${q.opening.obs} of ${q.n_top} top-3 anchors are sentence 0 or 1 (${q.opening.null.toFixed(1)} expected): “Okay, let's see.” and the restatement of the user's request (“The user asked, ‘What's the largest star in our galaxy?’”). Qwen keeps referring back to its paraphrase of the prompt. Its anchors come before lock-in about as often as chance (${q.pre_lock.obs} vs ${q.pre_lock.null.toFixed(1)}). Qwen has no definition-style lines at all (${q.definition.obs}).`,
  `<b>Sentence type (our tags) does not predict anchors.</b> Per-type mean scores are within about ±0.05 of zero (right). The anchors are defined by their role in the CoT's structure (definition line, diagnostic question, restated prompt), which the eval-cue tags do not capture.`,
  `<b>Caveats.</b> The definition and question patterns were written after looking at the top anchors, so those two counts are descriptive, not a pre-registered test. White-box anchors barely track black-box resampling importance (median Spearman ρ +0.16 Qwen, +0.14 Gemma). Each graph is one CoT; read single graphs as examples.`,
].map(s => `<li>${s}</li>`).join("");
"""


def main():
    a = json.loads((RES / "suppression_analysis.json").read_text())
    data = {"models": {}, "min_rows": MIN_ROWS}
    for k in ["gemma", "qwen"]:
        runs = [per_run(r) for r in a[k]["runs"]]
        data["models"][k] = {"name": a[k]["summary"]["name"], "runs": runs, "agg": aggregate(runs)}
        ag = data["models"][k]["agg"]
        for g in GROUPS:
            print(k, g, ag[g], "of", ag["n_top"])
    html = (REPORT_DIR / "template.html").read_text().replace("<title>Eval-Awareness Anchors</title>", "<title>Causal Graphs</title>")
    i = html.index("const COLORS")
    head, rest = html[:i], html[i:]
    helpers = rest[: rest.index("/* ---------- Screening")]
    hb = rest[rest.index("function hbars"): rest.index("__SCRIPT__")]
    html = head + helpers + hb + SCRIPT + "</script>\n"
    html = html.replace("__BODY__", BODY).replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    out = REPORT_DIR / "causal_graph.html"
    out.write_text(html)
    print(out, f"{len(html) / 1e3:.0f} kB")


if __name__ == "__main__":
    main()
