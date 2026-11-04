/* Multi-turn pilot page. Relies on helpers + runChart copied from template.html. */
const PNAME = {a102: "“Whats the largest star in our galaxy?”", wb6a: "WildChat game-show script", m682: "MT-Bench: life stages & mortality"};
const SRCN = {alpaca_eval: "AlpacaEval", wildchat_natural: "WildChat", mt_bench: "MT-Bench"};

function promptTable() {
  const tb = document.querySelector("#p-table tbody");
  DATA.prompts.forEach(p => {
    const d = p.p_multi - p.p_single;
    tb.insertAdjacentHTML("beforeend", `<tr><td>${esc(PNAME[p.short])}<div class="note">${SRCN[p.source] || p.source}</div></td>
      <td><span class="pill ${p.ground_truth}">${p.ground_truth}</span></td>
      <td class="n">${pct(p.p_single)}</td><td class="n"><b>${pct(p.p_multi)}</b></td><td class="n">${sgn(d)}</td></tr>`);
  });
}

function summaryTable() {
  const tb = document.querySelector("#s-table tbody");
  ["a102", "wb6a", "m682"].forEach(s => ["EVALUATION", "DEPLOYMENT"].forEach(lab => {
    const row = f => DATA.summary.find(x => x.short === s && x.fmt === f && x.base_label === lab);
    const m = row("multi"), si = row("single");
    const cell = x => x ? `<td class="n">${pct(x.p_start)} → ${pct(x.p_end)}</td><td class="n">${x.n_sig}</td><td class="n">${x.max_abs.toFixed(2)}</td>` : `<td class="n">–</td><td class="n">–</td><td class="n">–</td>`;
    tb.insertAdjacentHTML("beforeend", `<tr><td>${esc(PNAME[s])}</td><td><span class="pill ${lab}">${lab}</span></td>${cell(m)}${cell(si)}</tr>`);
  }));
}

function explorer() {
  const ptabs = document.getElementById("p-tabs"), ltabs = document.getElementById("l-tabs");
  let cur = {short: "a102", lab: "EVALUATION"};
  try { const s = JSON.parse(localStorage.getItem("mt-cur")); if (s && s.short) cur = s; } catch (e) {}
  function render() {
    [...ptabs.children].forEach(b => b.setAttribute("aria-selected", b.dataset.k === cur.short));
    [...ltabs.children].forEach(b => b.setAttribute("aria-selected", b.dataset.k === cur.lab));
    const p = DATA.prompts.find(x => x.short === cur.short);
    document.getElementById("x-prompt").innerHTML = `<span style="font-family:var(--f-display)">“${esc(p.text.length > 220 ? p.text.slice(0, 220) + "…" : p.text)}”</span> <span class="pill ${p.ground_truth}">truth: ${p.ground_truth}</span>`;
    for (const fmt of ["multi", "single"]) {
      const r = DATA.runs.find(x => x.short === cur.short && x.fmt === fmt && x.base_label === cur.lab);
      const host = document.getElementById(`x-${fmt}`), list = document.getElementById(`x-${fmt}-chunks`), meta = document.getElementById(`x-${fmt}-meta`);
      if (!r) { host.innerHTML = '<p class="note">No run for this combination.</p>'; list.innerHTML = ""; meta.textContent = ""; continue; }
      meta.innerHTML = `base CoT #${r.sample_idx} · ${r.chunks.length} sentences × ${r.n_per_pos} rollouts · ${r.unparsed} unparsed`;
      runChart(host, list, r);
      if (fmt === "multi") document.getElementById("x-turn1").textContent = r.turn1_answer;
    }
    const tags = [...new Set(DATA.runs.filter(x => x.short === cur.short && x.base_label === cur.lab).flatMap(r => r.chunks.map(c => c.tag)))]
      .sort((a, b) => Object.keys(COLORS).indexOf(a) - Object.keys(COLORS).indexOf(b));
    document.getElementById("x-legend").innerHTML = `<span><i class="ln" style="background:var(--eval)"></i>resampled P(EVAL)</span>` +
      tags.map(t => `<span><i class="sw" style="background:${COLORS[t]}"></i>${NAMES[t]}</span>`).join("");
    try { localStorage.setItem("mt-cur", JSON.stringify(cur)); } catch (e) {}
  }
  const mk = (host, k, label, key) => { const b = document.createElement("button"); b.className = "tab"; b.dataset.k = k; b.textContent = label;
    b.setAttribute("role", "tab"); b.onclick = () => { cur[key] = k; render(); }; host.appendChild(b); };
  ["a102", "wb6a", "m682"].forEach(s => mk(ptabs, s, PNAME[s], "short"));
  mk(ltabs, "EVALUATION", "CoT that said EVALUATION", "lab"); mk(ltabs, "DEPLOYMENT", "CoT that said DEPLOYMENT", "lab");
  render();
}

function anchorTable() {
  const tb = document.querySelector("#a-table tbody");
  if (!DATA.anchors.length) { tb.innerHTML = `<tr><td colspan="5" class="note">No sentence passed the threshold.</td></tr>`; return; }
  DATA.anchors.forEach(a => tb.insertAdjacentHTML("beforeend", `<tr><td>${esc(PNAME[a.short])}<div class="note">CoT said ${a.base_label}</div></td>
    <td class="n">${a.i}</td><td>${esc(a.text)}</td><td><span class="sw" style="background:${COLORS[a.tag]}"></span> ${NAMES[a.tag]}${a.dir === "toward_eval" ? " [E]" : a.dir === "toward_deployment" ? " [D]" : ""}</td>
    <td class="n">${sgn(a.imp)} ± ${a.se.toFixed(2)}</td></tr>`));
}

function catChart() {
  const host = document.getElementById("c-chart");
  const tags = [...new Set(DATA.categories.map(c => c.tag))].sort((a, b) => Object.keys(COLORS).indexOf(a) - Object.keys(COLORS).indexOf(b));
  const get = (f, t) => DATA.categories.find(c => c.fmt === f && c.tag === t);
  const W = 900, L = 170, R = 60, rowH = 34, T = 10, H = T + tags.length * rowH + 28;
  const m = Math.max(0.05, ...DATA.categories.map(c => c.mean_abs)) * 1.1;
  const svg = el("svg", {viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Mean absolute importance by category, multi-turn vs single-turn"}, host);
  const x = v => L + v / m * (W - L - R);
  for (const t of [0, m / 2, m]) { el("line", {x1: x(t), x2: x(t), y1: T, y2: T + tags.length * rowH, class: "grid"}, svg); txt(svg, x(t), H - 8, t.toFixed(2), {"text-anchor": "middle"}); }
  tags.forEach((t, r) => {
    const y = T + r * rowH;
    txt(svg, L - 10, y + rowH / 2 + 4, NAMES[t], {"text-anchor": "end", style: "fill:var(--ink)"});
    [["multi", 0, css("--eval")], ["single", 1, css("--ink-3")]].forEach(([f, k, col]) => {
      const c = get(f, t); if (!c) return;
      const yy = y + 5 + k * 12;
      el("rect", {x: L, y: yy, width: Math.max(1, x(c.mean_abs) - L), height: 10, rx: 2, fill: col}, svg);
      txt(svg, x(c.mean_abs) + 6, yy + 9, `${c.mean_abs.toFixed(3)} (n=${c.n})`, {style: "font-size:10px"});
    });
  });
}

promptTable(); summaryTable(); explorer(); anchorTable(); catChart();
