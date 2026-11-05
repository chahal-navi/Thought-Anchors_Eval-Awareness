/* ---------- Overnight report ---------- */
const M = DATA.models;
let CUR = "gemma";
const SER = ["--accent", "--depl", "--ink-3"];  // series colours: blue, orange, grey (fixed order)

/* Horizontal bars with an optional marker (e.g. the size-matched random baseline) and reference lines. */
function bars(host, rows, {domain, refs = [], fmt = sgn, L = 270, W = 900, label = "", ticks, R = 120}) {
  const rowH = 28, T = 8, H = T + rows.length * rowH + 28;
  const svg = el("svg", {viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": label}, host);
  const x = v => L + (Math.max(domain[0], Math.min(domain[1], v)) - domain[0]) / (domain[1] - domain[0]) * (W - L - R);
  ticks = ticks || [0, .25, .5, .75, 1].map(t => domain[0] + t * (domain[1] - domain[0]));
  ticks.forEach(t => { el("line", {x1: x(t), x2: x(t), y1: T, y2: T + rows.length * rowH, class: "grid"}, svg);
    txt(svg, x(t), H - 8, fmt(t), {"text-anchor": "middle"}); });
  const z = Math.max(domain[0], 0);
  el("line", {x1: x(z), x2: x(z), y1: T, y2: T + rows.length * rowH, stroke: css("--ink-3")}, svg);
  refs.forEach(r => { el("line", {x1: x(r.v), x2: x(r.v), y1: T - 4, y2: T + rows.length * rowH, stroke: css("--ink-2"), "stroke-dasharray": "4 3"}, svg);
    if (r.label) txt(svg, x(r.v) + 4, T + rows.length * rowH + 14, r.label, {style: "fill:var(--ink-3);font-size:10px"}); });
  rows.forEach((r, i) => {
    const y = T + i * rowH, v = r.value;
    txt(svg, L - 10, y + rowH / 2 + 4, r.label, {"text-anchor": "end", style: r.strong ? "fill:var(--ink);font-weight:600" : "fill:var(--ink)"});
    if (v == null) return;
    el("rect", {x: Math.min(x(z), x(v)), y: y + 6, width: Math.max(Math.abs(x(v) - x(z)), 1.5), height: rowH - 12, rx: 3, fill: r.color || css("--accent")}, svg);
    if (r.mark != null) el("path", {d: `M${x(r.mark)},${y + 3} l5,${rowH / 2 - 3} l-5,${rowH / 2 - 3} l-5,${-(rowH / 2 - 3)} z`, fill: css("--ink-2"),
      stroke: css("--surface"), "stroke-width": 2}, svg);
    const right = Math.max(x(z), x(v), r.mark != null ? x(r.mark) + 6 : 0);
    txt(svg, right + 8, y + rowH / 2 + 4, r.text ?? fmt(v), {style: "fill:var(--ink-2);font-family:var(--f-mono);font-size:10.5px;paint-order:stroke;stroke:var(--surface);stroke-width:4px"});
    if (r.tip) { const hit = el("rect", {x: 0, y, width: W, height: rowH, fill: "transparent"}, svg);
      hit.addEventListener("mousemove", ev => showTip(ev, r.tip)); hit.addEventListener("mouseleave", hideTip); }
  });
  return svg;
}

/* Line chart: series [{name, ys, color, dash, band:[lo,hi]}] over shared xs; crosshair tooltip. */
function lines(host, {xs, series, ydomain, yticks, xfmt = v => v, yfmt = sgn, refs = [], vlines = [], xlabel = "", label = "", W = 900, H = 300, xpos}) {
  const L = 56, R = W < 700 ? 118 : 130, T = 14, B = 42;
  const svg = el("svg", {viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": label}, host);
  const px = xpos || ((v, i) => i);
  const xv = xs.map(px), x0 = Math.min(...xv), x1 = Math.max(...xv);
  const x = v => L + (x1 === x0 ? 0.5 : (v - x0) / (x1 - x0)) * (W - L - R);
  const y = v => T + (1 - (Math.max(ydomain[0], Math.min(ydomain[1], v)) - ydomain[0]) / (ydomain[1] - ydomain[0])) * (H - T - B);
  for (const v of (yticks || [0, 1, 2, 3, 4].map(t => ydomain[0] + t / 4 * (ydomain[1] - ydomain[0])))) {
    el("line", {x1: L, x2: W - R, y1: y(v), y2: y(v), class: "grid"}, svg); txt(svg, L - 8, y(v) + 4, yfmt(v), {"text-anchor": "end"}); }
  const step = Math.max(1, Math.ceil(xs.length / 12));
  xs.forEach((v, i) => { if (i % step === 0 || i === xs.length - 1) txt(svg, x(xv[i]), H - B + 18, xfmt(v), {"text-anchor": "middle"}); });
  if (xlabel) txt(svg, L + (W - L - R) / 2, H - 6, xlabel, {"text-anchor": "middle", style: "fill:var(--ink-3)"});
  refs.forEach(r => { el("line", {x1: L, x2: W - R, y1: y(r.v), y2: y(r.v), stroke: css("--ink-3"), "stroke-dasharray": "4 3"}, svg);
    if (r.label) txt(svg, W - R + 6, y(r.v) + 4, r.label, {style: "fill:var(--ink-3);font-size:10px"}); });
  vlines.forEach(v => { el("line", {x1: x(px(v.x, xs.indexOf(v.x))), x2: x(px(v.x, xs.indexOf(v.x))), y1: T, y2: H - B, stroke: v.color, "stroke-dasharray": v.dash || "", "stroke-width": 1.5}, svg);
    txt(svg, x(px(v.x, xs.indexOf(v.x))) + 4, H - B - 8 - (v.row || 0) * 14, v.label, {style: `fill:${v.color};font-size:10.5px;paint-order:stroke;stroke:var(--surface);stroke-width:4px`}); });
  const ends = [];
  series.forEach(s => {
    if (s.band) { const pts = xs.map((_, i) => s.band[0][i] == null ? null : [x(xv[i]), y(s.band[0][i]), y(s.band[1][i])]).filter(Boolean);
      el("path", {d: "M" + pts.map(p => `${p[0]},${p[1]}`).join("L") + "L" + pts.reverse().map(p => `${p[0]},${p[2]}`).join("L") + "Z",
        fill: s.color, opacity: 0.12}, svg); }
    let d = "", pen = false, last = null;
    s.ys.forEach((v, i) => { if (v == null) { pen = false; return; } d += (pen ? "L" : "M") + x(xv[i]) + "," + y(v); pen = true; last = [x(xv[i]), y(v)]; });
    el("path", {d, fill: "none", stroke: s.color, "stroke-width": 2, "stroke-dasharray": s.dash || "", "stroke-linejoin": "round"}, svg);
    if (s.dots !== false) s.ys.forEach((v, i) => { if (v != null) el("circle", {cx: x(xv[i]), cy: y(v), r: 3.5, fill: s.color, stroke: css("--surface"), "stroke-width": 1.5}, svg); });
    if (last) ends.push({y: last[1], s});
  });
  ends.sort((a, b) => a.y - b.y); let prev = -1e9;
  ends.forEach(e => { const yy = Math.max(e.y + 4, prev + 13); prev = yy; txt(svg, W - R + 8, yy, e.s.name, {style: `fill:var(--ink);font-size:11px`}); });
  const cross = el("line", {y1: T, y2: H - B, stroke: css("--ink-3"), visibility: "hidden"}, svg);
  const hit = el("rect", {x: L, y: T, width: W - L - R, height: H - T - B, fill: "transparent"}, svg);
  hit.addEventListener("mousemove", ev => {
    const pt = svg.createSVGPoint(); pt.x = ev.clientX; pt.y = ev.clientY; const p = pt.matrixTransform(svg.getScreenCTM().inverse());
    let bi = 0; xv.forEach((v, i) => { if (Math.abs(x(v) - p.x) < Math.abs(x(xv[bi]) - p.x)) bi = i; });
    cross.setAttribute("x1", x(xv[bi])); cross.setAttribute("x2", x(xv[bi])); cross.setAttribute("visibility", "visible");
    showTip(ev, `<b>${esc(xlabel || "x")}: ${esc(xfmt(xs[bi]))}</b><br>` + series.map(s => `<span style="color:${s.color}">■</span> ${esc(s.name)}: ${s.ys[bi] == null ? "–" : yfmt(s.ys[bi])}`).join("<br>"));
  });
  hit.addEventListener("mouseleave", () => { cross.setAttribute("visibility", "hidden"); hideTip(); });
  return svg;
}

function legend(host, items) {
  host.innerHTML = items.map(i => `<span>${i.marker === "diamond" ? `<svg width="12" height="12" viewBox="0 0 12 12"><path d="M6,0 l6,6 l-6,6 l-6,-6z" fill="${i.color}"/></svg>` :
    i.dash ? `<i class="ln" style="background:repeating-linear-gradient(90deg,${i.color} 0 4px,transparent 4px 7px)"></i>` :
    i.line ? `<i class="ln" style="background:${i.color}"></i>` : `<i class="sw" style="background:${i.color}"></i>`}${esc(i.name)}</span>`).join("");
}

const $ = id => document.getElementById(id);
const clear = id => { const h = $(id); if (h) h.innerHTML = ""; return h; };
const pv = p => p == null ? "" : p < 0.001 ? "p < 0.001" : "p = " + p.toFixed(3);
const sh = v => v == null ? "–" : (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(2);

function render() {
  const m = M[CUR], acc = css("--accent"), org = css("--depl"), gry = css("--ink-3");
  document.querySelectorAll(".mname").forEach(e => e.textContent = m.name);

  // exp2
  bars(clear("exp2"), m.exp2.map(r => ({label: r.label, value: r.share, text: `${sh(r.share)}  · ${r.flips}/20 flip`,
    color: r.key.startsWith("user_q") ? gry : acc,
    tip: `<b>${esc(r.label)}</b><br>median share of the verdict margin removed: ${sh(r.share)}<br>verdict flipped in ${r.flips} of 20 runs`})),
    {domain: [-0.25, 1.25], ticks: [-0.25, 0, 0.25, 0.5, 0.75, 1, 1.25], refs: [{v: 1}], label: "Share of verdict margin removed per block"});

  // exp3
  bars(clear("exp3"), m.exp3.map(r => ({label: r.label, value: r.share, mark: r.random, color: r.share > r.random ? acc : gry,
    text: `${sh(r.share)} vs ${sh(r.random)} · ${r.beats}/${r.n}`,
    tip: `<b>${esc(r.label)}</b> (${pct(r.size)} of sentences)<br>blocked: ${sh(r.share)} · random sets of the same size: ${sh(r.random)}<br>beats random in ${r.beats}/${r.n} runs, Wilcoxon ${pv(r.p)}`})),
    {domain: [-0.1, 0.5], ticks: [-0.1, 0, 0.1, 0.2, 0.3, 0.4, 0.5], label: "Group block vs size-matched random"});
  legend($("exp3-leg"), [{name: "Group blocked (median share)", color: acc}, {name: "Same-size random sets", color: css("--ink-2"), marker: "diamond"}]);

  const cv = m.curves, fs = cv.prefix.map(c => c.f);
  const sufx = fs.map(f => { const c = cv.suffix.find(c => Math.abs(c.f - f) < 1e-6); return c; });
  lines(clear("curves"), {xs: fs, xpos: v => v, xfmt: v => Math.round(v * 100) + "%", xlabel: "cut point (fraction of sentences)", ydomain: [-0.2, 1.3], yticks: [0, 0.5, 1],
    refs: [{v: 1, label: "50/50"}, {v: 0}], label: "Prefix and suffix blocks",
    series: [{name: "first f blocked", ys: cv.prefix.map(c => c.m), color: acc, band: [cv.prefix.map(c => c.q25), cv.prefix.map(c => c.q75)]},
             {name: "last 1−f blocked", ys: sufx.map(c => c ? c.m : null), color: org, band: [sufx.map(c => c ? c.q25 : null), sufx.map(c => c ? c.q75 : null)]}]});

  // exp6
  const e = m.exp6;
  bars(clear("exp6"), [
    {label: "20 receiver heads", value: e.dlo.receiver, color: acc}, {label: "20 random heads (set A)", value: e.dlo.random0, color: gry},
    {label: "20 random heads (set B)", value: e.dlo.random1, color: gry}, {label: `all ${e.n_layers === 64 ? "4096" : "480"} heads`, value: e.dlo.all_heads, color: css("--ink-2")}],
    {domain: [0, Math.max(1, e.dlo.all_heads * 1.15)], fmt: v => v.toFixed(2), label: "Mean |Δ log-odds| per sentence"});
  $("exp6-note").innerHTML = `Receiver heads (layers ${[...new Set(e.layers)].join(", ")} of ${e.n_layers}) replicate the paper's head-level pattern: split-half r = ${e.r.toFixed(2)}. Correlation of a sentence's receiver score with its resampling importance: ρ ${sh(e.rho_imp)}; with its causal-graph anchor score: ρ ${sh(e.rho_anchor)}. Blocking the whole CoT in only these heads: ${sh(e.groups.cot_all.receiver)} of the margin (all heads: ${sh(e.groups.cot_all.all_heads)}).`;

  // probe
  if (m.probe) {
    const p = m.probe, dec = [...Array(10).keys()].map(i => (i + 1) / 10);
    lines(clear("probe"), {xs: dec, xpos: v => v, xfmt: v => Math.round(v * 100) + "%", xlabel: "position in the CoT (decile)", ydomain: [0.4, 1], yticks: [0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1], yfmt: v => v.toFixed(2),
      refs: [{v: 0.5, label: "chance"}], label: "Probe AUC by position",
      series: [{name: `residual probe (L${p.best_layer})`, ys: p.best, color: acc},
               {name: "words so far (BoW)", ys: p.text_prefix, color: org},
               {name: "current sentence (BoW)", ys: p.text_current, color: gry, dash: "5 4"}]
               .concat(p.fresh ? [{name: "probe, fresh CoTs", ys: p.fresh.auc_by_decile, color: acc, dash: "2 3", dots: false}] : [])
               .concat(p.fresh && p.fresh.text_by_decile ? [{name: "BoW, fresh CoTs", ys: p.fresh.text_by_decile, color: org, dash: "2 3", dots: false}] : [])});
    const lay = Object.keys(p.by_layer).map(Number).sort((a, b) => a - b);
    bars(clear("probe-layers"), lay.map(l => ({label: `layer ${l}` + (l === p.best_layer ? " (picked)" : ""), value: p.by_layer[l].all, strong: l === p.best_layer,
      color: l === p.best_layer ? acc : gry, text: `${p.by_layer[l].all.toFixed(2)} · early ${(p.by_layer[l].deciles.slice(0, 3).reduce((a, b) => a + b, 0) / 3).toFixed(2)}`})),
      {domain: [0.5, 1], fmt: v => v.toFixed(2), L: 130, W: 520, R: 130, label: "AUC by layer"});
    const tabs = $("probe-runs"); tabs.innerHTML = "";
    p.base_runs.forEach((b, i) => { const t = document.createElement("button"); t.className = "tab"; t.textContent = b.run; t.setAttribute("role", "tab");
      t.onclick = () => { tabs.querySelectorAll(".tab").forEach(x => x.setAttribute("aria-selected", "false")); t.setAttribute("aria-selected", "true"); probeRun(b); };
      tabs.appendChild(t); if (i === 0) { t.setAttribute("aria-selected", "true"); probeRun(b); } });
    const br = p.base_runs, med = a => { const s = [...a].sort((x, y) => x - y); return s.length % 2 ? s[(s.length - 1) / 2] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2; };
    $("probe-lock").innerHTML = `Median lock-in, in sentences: <b>resampling ${med(br.map(b => b.lock))}</b>, <b>probe ${med(br.map(b => b.probe_lock))}</b>. Median Spearman ρ between the probe's P(EVAL) and the resampled P(EVAL), per run: <b>${sh(med(br.filter(b => b.rho != null).map(b => b.rho)))}</b>.` +
      (p.fresh ? ` On ${p.fresh.n} fresh CoTs generated overnight (probe and BoW trained on all 200): probe AUC ${p.fresh.auc_all.toFixed(2)}` + (p.fresh.text_all ? `, BoW ${p.fresh.text_all.toFixed(2)}.` : ".") : "");
  }

  // follow-ups
  if (m.fu) {
    const f = m.fu, sp = f.splices, order = ["frac_0.25", "frac_0.5", "frac_0.75", "frac_0.9", "tail_3", "tail_2", "tail_1"];
    const lab = {"frac_0.25": "A's first 25% + B's rest", "frac_0.5": "A's first 50% + B's rest", "frac_0.75": "A's first 75% + B's rest", "frac_0.9": "A's first 90% + B's rest",
      tail_3: "A with B's last 3 sentences", tail_2: "A with B's last 2 sentences", tail_1: "A with B's last sentence"};
    const mx = Math.max(25, Math.ceil(Math.max(...order.map(k => Math.abs(sp[k].median_toward_head))) * 1.1 / 5) * 5);
    bars(clear("splices"), order.map(k => ({label: lab[k], value: sp[k].median_toward_head, color: sp[k].median_toward_head < 0 ? org : acc,
      text: `${sp[k].median_toward_head.toFixed(1)} · tail wins ${sp[k].follows_tail}/${sp[k].n}`,
      tip: `<b>${esc(lab[k])}</b><br>median log-odds toward A's verdict: ${sp[k].median_toward_head.toFixed(1)}<br>answer takes B's verdict in ${sp[k].follows_tail} of ${sp[k].n} runs`})),
      {domain: [-mx, mx], ticks: [-20, -10, 0, 10, 20], fmt: v => v.toFixed(0), label: "Splices: log-odds toward the head's verdict"});
    const lw = f.layers.layers_window;
    bars(clear("layers"), lw.map(w => ({label: `layers ${w.layers.replace("-", "–")}`, value: w.median_share, color: w.median_share > 0.2 ? acc : gry,
      text: `${sh(w.median_share)} · ${w.flips} flip`})), {domain: [-0.1, 1.1], ticks: [0, 0.5, 1], refs: [{v: 1}], L: 110, W: 520, R: 100, label: "CoT hidden from the answer in a window of layers"});
    const cuts = f.layers.layers_from.map(x => +x.layers);
    lines(clear("layers-cum"), {xs: cuts, xpos: v => v, xlabel: "layer l", ydomain: [-0.2, 1.2], yticks: [0, 0.5, 1], refs: [{v: 1}, {v: 0}], W: 520, H: 300, label: "Cumulative layer blocks",
      series: [{name: "layers ≥ l blocked", ys: f.layers.layers_from.map(x => x.median_share), color: acc},
               {name: "layers < l blocked", ys: f.layers.layers_upto.map(x => x.median_share), color: org}]});
  }

  // reader heads
  if (m.readers) {
    const r = m.readers, rows = r.rows;
    lines(clear("readers"), {xs: rows.map(x => x.k), xlabel: "k heads (ranked by answer→CoT attention)", ydomain: [-0.2, 1.2], yticks: [0, 0.5, 1], refs: [{v: 1, label: "50/50"}, {v: 0}], H: 280,
      label: "Reader heads", series: [{name: "top-k blocked", ys: rows.map(x => x.top), color: acc}, {name: "random k blocked", ys: rows.map(x => x.random), color: gry, dash: "5 4"},
        {name: "all but top-k blocked", ys: rows.map(x => x.keep_top), color: org}]});
    if (r.single_layer) bars(clear("readers-layer"), r.single_layer.map(x => ({label: `layer ${x.layer}`, value: x.share, color: x.share > 0.1 ? acc : gry})),
      {domain: [-0.1, Math.max(0.5, ...r.single_layer.map(x => x.share)) * 1.1], L: 90, W: 520, R: 70, label: "Single-layer blocks"});
    if (r.win) lines(clear("readers-win"), {xs: r.win.map(x => x.k), xlabel: `k heads inside layers ${r.window[0]}–${r.window[1] - 1}`, ydomain: [-0.2, 1.2], yticks: [0, 0.5, 1], W: 520, H: 300,
      refs: [{v: 1, label: "50/50"}, {v: 0}], label: "Reader heads inside the window",
      series: [{name: "top-k in window", ys: r.win.map(x => x.top), color: acc}, {name: "random k in window", ys: r.win.map(x => x.random), color: gry, dash: "5 4"}]});
  }
}

function probeRun(b) {
  const acc = css("--accent"), org = css("--depl"), n = b.probe.length;
  const xs = [...Array(n).keys()];
  lines(clear("probe-run"), {xs, xlabel: "sentence", ydomain: [0, 1], yfmt: v => pct(v), H: 260, refs: [{v: 0.5}], label: `Probe vs resampling for ${b.run}`,
    vlines: [{x: Math.min(b.lock, n - 1), label: `resampling lock ${b.lock}`, color: org, dash: "4 3"}, {x: Math.min(b.probe_lock, n - 1), label: `probe lock ${b.probe_lock}`, color: acc, dash: "4 3", row: 1}],
    series: [{name: "probe P(EVAL)", ys: b.probe, color: acc, dots: n < 40}, {name: "resampled P(EVAL)", ys: b.resampled.slice(1, n + 1), color: org, dots: n < 40}]});
  $("probe-run-note").innerHTML = `<span class="pill ${b.label}">${b.label}</span> final verdict · ρ = ${b.rho == null ? "–" : sh(b.rho)}`;
}

document.querySelectorAll("#model-tabs .tab").forEach(t => t.addEventListener("click", () => {
  document.querySelectorAll("#model-tabs .tab").forEach(x => x.setAttribute("aria-selected", String(x === t)));
  CUR = t.dataset.m; render(); }));
render();
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", render);
