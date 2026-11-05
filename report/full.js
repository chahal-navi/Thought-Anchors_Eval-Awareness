
/* ---------- Full report: charts (bars / lines / legend helpers come from overnight.js) ---------- */
const MD = DATA.models, MNAME = {gemma: "Gemma 4 26B-A4B", qwen: "Qwen3-32B"};
const $ = id => document.getElementById(id);
const sh = v => v == null ? "–" : (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(2);
const GL = {last2: "Last 2 sentences", opening: "First 2 sentences", kl_top3: "Top-3 causal-graph anchors", imp_top3: "Top-3 resampling importance",
  checklist: "Checklist lines", pre_lock: "All sentences before lock-in", post_lock: "After lock-in (minus last 2)",
  label_word: "Sentences naming a label", verdict_stmt: "Verdict in capitals"};

/* Lock-in explainer: one run, resampled curve with the ±0.15 band around its final value, and the probe. */
let LM = "qwen";
const DEF = {qwen: "m682_eval", gemma: "a272_eval"};  // clear examples first; a102_eval never locks in
function lockRun(r) {
  const acc = css("--accent"), org = css("--depl"), gry = css("--ink-3"), q = r.resampled, N = q.length - 1, fin = q[N];
  const xs = [...Array(N + 1).keys()], probe = [null, ...r.probe];
  const lo = xs.map(() => Math.max(0, fin - 0.15)), hi = xs.map(() => Math.min(1, fin + 0.15));
  const host = $("lock-chart"); host.innerHTML = "";
  lines(host, {xs, xlabel: "sentences kept (prefix length i)", xfmt: v => v, ydomain: [0, 1], yticks: [0, 0.25, 0.5, 0.75, 1], yfmt: v => pct(v), H: 300,
    refs: [{v: 0.5}], label: "Resampled and probe P(EVAL) for one run",
    vlines: [{x: r.lock_r15, label: `resampling lock-in ${r.lock_r15}`, color: acc}, {x: Math.min(r.lock_p50, N), label: `probe lock-in ${r.lock_p50}`, color: org, dash: "5 4", row: 1}],
    series: [{name: "resampled P(EVAL)", ys: q, color: acc, band: [lo, hi]}, {name: "probe P(EVAL)", ys: probe, color: org, dash: "5 4"}]});
  $("lock-note").innerHTML = `<b>${esc(r.title)}</b> · final verdict ${r.label} · ${N} sentences. Shaded band: final resampled value ${pct(fin)} ± 0.15. ` +
    `Resampling lock-in = first i after which the blue line never leaves the band (${r.lock_r15}${r.lock_r15 >= N ? ", i.e. it never settles before the end" : ""}). ` +
    `Probe lock-in = first i after which the orange line stays on the ${r.label === "EVALUATION" ? "upper" : "lower"} side of 50% (${r.lock_p50}).`;
  $("lock-sents").innerHTML = r.chunks.map((c, j) => `<div class="chunk" style="grid-template-columns:28px 1fr 120px"><span class="idx">${j}</span><span>${esc(c)}</span>` +
    `<span class="val">after: ${q[j + 1] == null ? "–" : pct(q[j + 1])}${r.probe[j] == null ? "" : " · " + pct(r.probe[j])}</span></div>`).join("");
}
function lockSection() {
  const m = MD[LM], tabs = $("lock-runs"); tabs.innerHTML = "";
  m.lock_runs.forEach((r, i) => { const t = document.createElement("button"); t.className = "tab"; t.textContent = r.title; t.setAttribute("role", "tab");
    t.onclick = () => { tabs.querySelectorAll(".tab").forEach(x => x.setAttribute("aria-selected", "false")); t.setAttribute("aria-selected", "true"); lockRun(r); };
    tabs.appendChild(t); if (r.run === DEF[LM]) { t.setAttribute("aria-selected", "true"); lockRun(r); } });
  $("lock-table").innerHTML = ["gemma", "qwen"].map(k => { const s = MD[k].lock; return `<tr><td>${MNAME[k]}</td><td class="n">${s.N}</td>` +
    `<td class="n">${s.r50}</td><td class="n">${s.p50}</td><td class="n">${s.later_p50_r50}/${s.n}</td>` +
    `<td class="n">${s.r15}</td><td class="n">${s.p15}</td><td class="n">${s.later_p15_r15}/${s.n}</td></tr>`; }).join("");
}
document.querySelectorAll("#lock-model .tab").forEach(t => t.onclick = () => {
  document.querySelectorAll("#lock-model .tab").forEach(x => x.setAttribute("aria-selected", String(x === t))); LM = t.dataset.m; lockSection(); });

/* Two-panel charts, one per model. */
function perModel(id, draw) { ["gemma", "qwen"].forEach(k => { const h = $(`${id}-${k}`); if (h) { h.innerHTML = ""; draw(h, MD[k], k); } }); }

function drawAll() {
  const acc = css("--accent"), org = css("--depl"), gry = css("--ink-3");
  perModel("groups", (h, m) => bars(h, m.groups.map(r => ({label: GL[r.g] || r.g, value: r.share, mark: r.random, color: r.p != null && r.p < 0.05 && r.share > r.random ? acc : gry,
    text: `${sh(r.share)} vs ${sh(r.random)} · ${r.beats}/${r.n}`,
    tip: `<b>${esc(GL[r.g] || r.g)}</b><br>blocked: ${sh(r.share)} · same-size random: ${sh(r.random)}<br>beats random in ${r.beats}/${r.n} runs${r.p == null ? "" : `, Wilcoxon p = ${r.p}`}`})),
    {domain: [-0.1, 0.5], ticks: [0, 0.25, 0.5], L: 190, W: 520, R: 130, label: "Group block vs size-matched random"}));
  legend($("groups-leg"), [{name: "Beats random (Wilcoxon p < 0.05)", color: acc}, {name: "Not significantly above random", color: gry}, {name: "Same-size random sets", color: css("--ink-2"), marker: "diamond"}]);

  perModel("layers", (h, m) => bars(h, m.layers_window.map(w => ({label: `layers ${w.layers.replace("-", "–")}`, value: w.share, color: w.share > 0.2 ? acc : gry,
    text: `${sh(w.share)} · ${w.flips}/20 flip`})), {domain: [-0.1, 1.1], ticks: [0, 0.5, 1], refs: [{v: 1, label: "50/50"}], L: 100, W: 520, R: 110, label: "CoT hidden from the answer in one band of layers"}));

  perModel("heads", (h, m) => lines(h, {xs: m.win.map(x => x.k), xlabel: `k heads inside layers ${m.window[0]}–${m.window[1] - 1}`, ydomain: [-0.1, 1.1], yticks: [0, 0.5, 1], W: 520, H: 280,
    refs: [{v: m.all_heads, label: "all heads"}, {v: 0}], label: "Top-k vs random heads inside the read-out band",
    series: [{name: "top-k heads", ys: m.win.map(x => x.top), color: acc}, {name: "random k heads", ys: m.win.map(x => x.random), color: gry, dash: "5 4"}]}));

  const SO = ["frac_0.25", "frac_0.5", "frac_0.75", "frac_0.9", "tail_3", "tail_2", "tail_1"];
  const SL = {"frac_0.25": "last 75% swapped", "frac_0.5": "last 50% swapped", "frac_0.75": "last 25% swapped", "frac_0.9": "last 10% swapped",
    tail_3: "last 3 sentences", tail_2: "last 2 sentences", tail_1: "last sentence only"};
  perModel("splice", (h, m) => bars(h, SO.map(k => ({label: SL[k], value: m.splices[k] / 20, color: m.splices[k] >= 10 ? org : gry, text: `${m.splices[k]}/20`})),
    {domain: [0, 1], ticks: [0, 0.5, 1], fmt: v => Math.round(v * 20) + "", L: 140, W: 520, R: 70, label: "Runs where the answer follows the swapped-in ending"}));

  const dec = [...Array(10).keys()].map(i => (i + 1) / 10);
  perModel("probe", (h, m) => lines(h, {xs: dec, xpos: v => v, xfmt: v => Math.round(v * 100) + "%", xlabel: "position in the CoT", ydomain: [0.4, 1], yticks: [0.5, 0.75, 1], yfmt: v => v.toFixed(2),
    W: 520, H: 280, refs: [{v: 0.5, label: "chance"}], label: "Probe vs bag-of-words AUC",
    series: [{name: `probe (L${m.probe.layer})`, ys: m.probe.probe, color: acc}, {name: "BoW, text so far", ys: m.probe.bow, color: org},
      {name: "BoW, this sentence", ys: m.probe.cur, color: gry, dash: "5 4"}]}));
}

lockSection(); drawAll();
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { lockSection(); drawAll(); });
