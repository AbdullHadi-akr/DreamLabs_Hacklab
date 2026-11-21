// Shared rendering for the Robustness panel and the full report page (plain ES module, no build step).

import { h } from "/static/lib/api.js";

export const OUTCOME_COLORS = {
  success: "#2fbf5f",
  missed_container: "#9fe3ac",
  carry_failed: "#f5c451",
  no_grasp: "#ffb06c",
  pushed: "#fc9ea0",
  wrong_object: "#af98ef",
  no_reach: "#c9474a",
  off_table: "#7a2e30",
  aborted: "#c3c0c0",
  invalid: "#e4e2e2",
};

const NS = "http://www.w3.org/2000/svg";
export function svg(tag, attrs = {}, ...children) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== undefined && v !== null && v !== false) el.setAttribute(k, v);
  for (const c of children.flat()) if (c !== undefined && c !== null && c !== false) el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return el;
}

export const pct = (x) => (x === null || x === undefined ? "–" : `${Math.round(x * 100)}%`);

/** Strength label: "4 cm", "×2", "#3". */
export function strength(v, p) {
  if (p.unit === "#") return `#${v}`;
  if (p.unit === "×") return `×${+v.toFixed(2)}`;
  return `${+v.toFixed(2)} ${p.unit}`;
}

export function outcomeChip(outcome, labels) {
  return h("span", { class: "rb-chip", title: labels[outcome] || outcome },
    h("i", { style: { background: OUTCOME_COLORS[outcome] || "#ccc" } }), labels[outcome] || outcome);
}

/** Stacked bar of outcome counts. */
export function outcomeBar(outcomes, labels) {
  const total = Object.values(outcomes || {}).reduce((a, b) => a + b, 0);
  const bar = h("div", { class: "rb-stack" });
  if (!total) return bar;
  for (const key of Object.keys(OUTCOME_COLORS)) {
    const n = outcomes[key];
    if (!n) continue;
    bar.append(h("div", { style: { flex: n, background: OUTCOME_COLORS[key] }, title: `${labels[key]}: ${n}` }));
  }
  return bar;
}

export function outcomeLegend(rows, labels) {
  const used = new Set(rows.map((r) => r.outcome).filter(Boolean));
  return h("div", { class: "rb-legend" },
    Object.keys(OUTCOME_COLORS).filter((k) => used.has(k)).map((k) => outcomeChip(k, labels)));
}

/**
 * Sweep chart: success rate per strength (dots + 95% Wilson interval), progress score (dashed line),
 * baseline (dotted), breaking point (red marker). Strengths are spaced evenly (they are often not linear).
 */
export function sweepChart(summary, { width = 288, height = 170 } = {}) {
  const p = summary.perturbation;
  const stats = summary.analysis.per_value;
  const verdict = summary.analysis.verdict;
  const m = { l: 32, r: 10, t: 12, b: 30 };
  const W = width - m.l - m.r, H = height - m.t - m.b;
  const x = (i) => m.l + (stats.length === 1 ? W / 2 : (i * W) / (stats.length - 1));
  const y = (v) => m.t + H - v * H;
  const root = svg("svg", { viewBox: `0 0 ${width} ${height}`, class: "rb-chart", role: "img",
    "aria-label": `Success rate per ${p.label} strength` });

  for (const t of [0, 0.5, 1]) {
    root.append(svg("line", { x1: m.l, x2: width - m.r, y1: y(t), y2: y(t), class: "rb-grid" }),
      svg("text", { x: m.l - 6, y: y(t) + 4, class: "rb-axis", "text-anchor": "end" }, `${t * 100}%`));
  }
  stats.forEach((s, i) => root.append(svg("text", { x: x(i), y: height - 10, class: "rb-axis", "text-anchor": "middle" },
    strength(s.value, p))));

  const bp = verdict.breaking_point;
  const bpIndex = stats.findIndex((s) => s.value === bp);
  if (bpIndex >= 0) {
    root.append(svg("line", { x1: x(bpIndex), x2: x(bpIndex), y1: m.t, y2: m.t + H, class: "rb-break" }),
      svg("text", { x: x(bpIndex) + (bpIndex === stats.length - 1 ? -4 : 4), y: m.t + 9, class: "rb-break-label",
        "text-anchor": bpIndex === stats.length - 1 ? "end" : "start" }, "breaks"));
  }
  const base = summary.analysis.baseline;
  if (base && base.rate !== null) root.append(svg("line", { x1: m.l, x2: width - m.r, y1: y(base.rate), y2: y(base.rate), class: "rb-base" }));

  const prog = stats.map((s, i) => (s.progress === null ? null : [x(i), y(s.progress)])).filter(Boolean);
  if (prog.length > 1) root.append(svg("polyline", { points: prog.map((q) => q.join(",")).join(" "), class: "rb-progress" }));
  prog.forEach(([px, py]) => root.append(svg("rect", { x: px - 3, y: py - 3, width: 6, height: 6, class: "rb-progress-dot" })));

  stats.forEach((s, i) => {
    if (!s.n) return;
    if (s.ci) root.append(svg("line", { x1: x(i), x2: x(i), y1: y(s.ci[0]), y2: y(s.ci[1]), class: "rb-ci" }),
      svg("line", { x1: x(i) - 4, x2: x(i) + 4, y1: y(s.ci[0]), y2: y(s.ci[0]), class: "rb-ci" }),
      svg("line", { x1: x(i) - 4, x2: x(i) + 4, y1: y(s.ci[1]), y2: y(s.ci[1]), class: "rb-ci" }));
    root.append(svg("circle", { cx: x(i), cy: y(s.rate), r: 4.5, class: "rb-rate" },
      svg("title", {}, `${strength(s.value, p)}: ${s.successes}/${s.n} successful, progress ${pct(s.progress)}`)));
  });
  return root;
}

export function chartLegend() {
  return h("div", { class: "rb-chart-legend muted" },
    h("span", {}, h("i", { class: "rb-key-rate" }), "success rate ± 95% CI"),
    h("span", {}, h("i", { class: "rb-key-progress" }), "progress score"),
    h("span", {}, h("i", { class: "rb-key-break" }), "breaking point"));
}

/** Table per strength: strength, k/n, outcome mix. */
export function sweepTable(summary, { detailed = false } = {}) {
  const p = summary.perturbation, labels = summary.outcome_labels;
  const head = ["Strength", "Success", ...(detailed ? ["95% CI", "Progress", "Closest reach", "Max lift"] : []), "Outcomes"];
  return h("table", { class: "table rb-table" },
    h("thead", {}, h("tr", {}, head.map((t) => h("th", {}, t)))),
    h("tbody", {}, summary.analysis.per_value.map((s) => h("tr", { class: s.value === summary.analysis.verdict.breaking_point ? "rb-row-break" : "" },
      h("td", { class: "num" }, strength(s.value, p), s.value === p.neutral ? h("span", { class: "muted" }, " base") : ""),
      h("td", { class: "num" }, s.n ? `${s.successes}/${s.n}` : `– (${s.done})`),
      detailed && h("td", { class: "num" }, s.ci ? `${pct(s.ci[0])}–${pct(s.ci[1])}` : "–"),
      detailed && h("td", { class: "num" }, pct(s.progress)),
      detailed && h("td", { class: "num" }, s.min_reach_cm === null ? "–" : `${s.min_reach_cm} cm`),
      detailed && h("td", { class: "num" }, s.max_lift_cm === null ? "–" : `${s.max_lift_cm} cm`),
      h("td", { style: { width: detailed ? "30%" : "46%" } }, outcomeBar(s.outcomes, labels)),
    ))));
}

/** Random mix: one row per factor, sorted by harm (most negative correlation first). */
export function factorTable(summary, { detailed = false } = {}) {
  const byId = Object.fromEntries(summary.factors.map((f) => [f.id, f]));
  const rows = [...summary.analysis.per_factor].sort((a, b) => (a.rho ?? 0) - (b.rho ?? 0));
  const harmful = summary.analysis.verdict.most_harmful;
  return h("table", { class: "table rb-table" },
    h("thead", {}, h("tr", {},
      h("th", {}, "Factor"), h("th", {}, "ρ"),
      h("th", {}, "Weak half"), h("th", {}, "Strong half"),
      detailed && h("th", {}, "Mean strength: success / fail"))),
    h("tbody", {}, rows.map((f) => {
      const p = byId[f.id];
      return h("tr", { class: f.id === harmful ? "rb-row-break" : "" },
        h("td", {}, p.label, h("div", { class: "muted" }, `0–${strength(f.max, p)}`)),
        h("td", { class: "num" }, f.rho === null ? "–" : (f.rho > 0 ? "+" : "") + f.rho.toFixed(2),
          h("div", { class: "rb-rho" }, h("div", { style: { width: `${Math.abs(f.rho ?? 0) * 50}%`,
            [f.rho < 0 ? "right" : "left"]: "50%", background: f.rho < 0 ? "var(--error)" : "var(--live)" } }))),
        h("td", { class: "num" }, f.weak.n ? `${f.weak.successes}/${f.weak.n}` : "–"),
        h("td", { class: "num" }, f.strong.n ? `${f.strong.successes}/${f.strong.n}` : "–"),
        detailed && h("td", { class: "num" }, `${f.mean_success ?? "–"} / ${f.mean_failure ?? "–"}`),
      );
    })));
}

/** Small scatter: strength (x) vs progress (y) for one factor, colored by outcome. */
export function factorScatter(summary, factor, { width = 220, height = 120 } = {}) {
  const m = { l: 26, r: 8, t: 8, b: 22 };
  const W = width - m.l - m.r, H = height - m.t - m.b;
  const lo = factor.neutral, hi = factor.max > lo ? factor.max : lo + 1;
  const x = (v) => m.l + ((v - lo) / (hi - lo)) * W;
  const y = (v) => m.t + H - v * H;
  const root = svg("svg", { viewBox: `0 0 ${width} ${height}`, class: "rb-chart" });
  for (const t of [0, 0.5, 1]) root.append(svg("line", { x1: m.l, x2: width - m.r, y1: y(t), y2: y(t), class: "rb-grid" }),
    svg("text", { x: m.l - 4, y: y(t) + 3, class: "rb-axis", "text-anchor": "end" }, t));
  root.append(svg("text", { x: m.l, y: height - 6, class: "rb-axis" }, strength(lo, factor)),
    svg("text", { x: width - m.r, y: height - 6, class: "rb-axis", "text-anchor": "end" }, strength(hi, factor)));
  for (const r of summary.rows) {
    if (r.progress === null || r.progress === undefined) continue;
    const jitter = ((r.index * 37) % 11 - 5) * 0.012;
    root.append(svg("circle", { cx: x(r.params[factor.id]), cy: y(Math.min(1, Math.max(0, r.progress + jitter))), r: 4,
      fill: OUTCOME_COLORS[r.outcome], stroke: "rgba(0,0,0,.25)" },
      svg("title", {}, `trial ${r.index}: ${strength(r.params[factor.id], factor)} → ${summary.outcome_labels[r.outcome]}`)));
  }
  return root;
}

export function describeParams(row, summary) {
  const defs = summary.perturbation ? [summary.perturbation] : summary.factors;
  return defs.map((p) => `${p.label} ${strength(row.params[p.id], p)}`).join(" · ");
}

// ---------------- heatmaps ----------------

/** Sequential blue ramp (light = 0, dark = 1). */
const RAMP = ["#e8f1fc", "#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6",
  "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b"];
export function rampColor(v) {
  const i = Math.round(Math.max(0, Math.min(1, v)) * (RAMP.length - 1));
  return { bg: RAMP[i], fg: i >= 8 ? "#ffffff" : "var(--ink)" };
}

let tip = null;
/** Hover tooltip for any element; `content` returns a string or a node. */
export function tooltip(el, content) {
  if (!tip) {
    tip = h("div", { class: "rb-tip", role: "tooltip", hidden: true });
    document.body.append(tip);
  }
  const move = (e) => {
    const pad = 14, w = tip.offsetWidth, ht = tip.offsetHeight;
    let x = e.clientX + pad, y = e.clientY + pad;
    if (x + w > innerWidth - 8) x = e.clientX - w - pad;
    if (y + ht > innerHeight - 8) y = e.clientY - ht - pad;
    tip.style.transform = `translate(${x}px, ${y}px)`;
  };
  el.addEventListener("mouseenter", (e) => {
    const c = content();
    tip.replaceChildren(typeof c === "string" ? document.createTextNode(c) : c);
    tip.hidden = false;
    move(e);
  });
  el.addEventListener("mousemove", move);
  el.addEventListener("mouseleave", () => { tip.hidden = true; });
  return el;
}

export function rampLegend(label) {
  return h("div", { class: "rb-ramp" },
    h("span", { class: "muted" }, label),
    h("span", { class: "muted" }, "0%"),
    h("div", { class: "rb-ramp-bar", style: { background: `linear-gradient(90deg, ${RAMP.join(",")})` } }),
    h("span", { class: "muted" }, "100%"),
    h("span", { class: "rb-cell-empty rb-ramp-empty" }), h("span", { class: "muted" }, "not tested"),
    h("span", { class: "rb-ramp-break" }), h("span", { class: "muted" }, "breaking point"));
}

function outcomeList(outcomes, labels) {
  return h("div", { class: "rb-tip-list" }, Object.entries(outcomes || {}).sort((a, b) => b[1] - a[1])
    .map(([k, n]) => h("div", {}, h("i", { style: { background: OUTCOME_COLORS[k] } }), `${labels[k] || k}: ${n}`)));
}

/**
 * Robustness map: one row per perturbation, one column per strength bin (share of the perturbation's maximum),
 * color = success rate or progress score of all pooled sweep trials. The first cell at half the baseline or
 * below is outlined as the breaking point.
 */
export function robustnessMap(map, { metric = "rate", onCell } = {}) {
  const cols = map.bins.length;
  const grid = h("div", { class: "rb-heat", style: { gridTemplateColumns: `minmax(150px, 1.3fr) repeat(${cols}, minmax(64px, 1fr))` } });
  grid.append(h("div", { class: "rb-heat-head" }, "Perturbation"), ...map.bins.map((b) => h("div", { class: "rb-heat-head num" }, b)));
  let group = null;
  for (const row of map.rows) {
    if (row.group !== group) {
      group = row.group;
      grid.append(h("div", { class: "rb-heat-group", style: { gridColumn: `1 / span ${cols + 1}` } }, row.group_label));
    }
    const base = row.cells[0];
    const baseValue = base ? (metric === "rate" ? base.rate : base.progress) : null;
    let broken = false;
    grid.append(h("div", { class: "rb-heat-label" }, row.label,
      h("span", { class: "muted" }, row.campaigns.length ? `${row.campaigns.length} run${row.campaigns.length > 1 ? "s" : ""}` : "not tested")));
    row.cells.forEach((c, i) => {
      if (!c) { grid.append(h("div", { class: "rb-cell rb-cell-empty", "aria-label": "not tested" })); return; }
      const v = metric === "rate" ? c.rate : c.progress;
      const isBreak = !broken && i > 0 && baseValue > 0 && v <= baseValue / 2;
      if (isBreak) broken = true;
      const { bg, fg } = rampColor(v);
      const values = c.values.map((x) => strength(x, row)).join(", ");
      const cell = h("button", { class: `rb-cell${isBreak ? " rb-cell-break" : ""}`, style: { background: bg, color: fg },
        "aria-label": `${row.label} ${values}: ${pct(v)}` },
        h("strong", {}, pct(v)), h("small", {}, `${c.successes}/${c.n} · ${values}`),
        isBreak ? h("em", {}, c.n < 5 || base.n < 5 ? "breaks?" : "breaks") : null);
      tooltip(cell, () => h("div", {},
        h("b", {}, `${row.label} · ${values}`),
        h("div", {}, `Success ${c.successes}/${c.n} (${pct(c.rate)}, 95% CI ${pct(c.ci[0])}–${pct(c.ci[1])})`),
        h("div", {}, `Progress score ${pct(c.progress)}`),
        outcomeList(c.outcomes, map.outcome_labels),
        isBreak ? h("div", { class: "bad" }, "Breaking point: half the baseline or below") : null,
        isBreak && (c.n < 5 || base.n < 5) ? h("div", { class: "muted" }, "Fewer than 5 trials here or in the baseline: treat as a hint.") : null,
        onCell ? h("div", { class: "muted" }, "click: open the newest report") : null));
      if (onCell) cell.onclick = () => onCell(row, i, c);
      grid.append(cell);
    });
  }
  return grid;
}

/** Sweep: every trial at a glance. Rows = trial number (same random draw), columns = strength, color = outcome. */
export function outcomeGrid(summary, { onTrial } = {}) {
  const p = summary.perturbation, labels = summary.outcome_labels;
  const trials = [...new Set(summary.rows.map((r) => r.trial))].sort((a, b) => a - b);
  const grid = h("div", { class: "rb-heat rb-heat-small", style: { gridTemplateColumns: `60px repeat(${summary.values.length}, minmax(40px, 1fr))` } });
  grid.append(h("div", { class: "rb-heat-head" }, "Trial"), ...summary.values.map((v) => h("div", { class: "rb-heat-head num" }, strength(v, p))));
  for (const t of trials) {
    grid.append(h("div", { class: "rb-heat-label" }, `#${t}`));
    for (const v of summary.values) {
      const r = summary.rows.find((x) => x.trial === t && x.value === v);
      if (!r) { grid.append(h("div", { class: "rb-cell rb-cell-empty" })); continue; }
      const cell = h("button", { class: "rb-cell", style: { background: OUTCOME_COLORS[r.outcome] },
        "aria-label": `trial ${t}, ${strength(v, p)}: ${labels[r.outcome]}` }, r.success ? "ok" : "");
      tooltip(cell, () => h("div", {}, h("b", {}, `Trial ${t} · ${strength(v, p)}`), h("div", {}, labels[r.outcome]),
        h("div", {}, `progress ${pct(r.progress)}`), r.prompt !== summary.config.task ? h("div", {}, `“${r.prompt}”`) : null,
        onTrial ? h("div", { class: "muted" }, "click: jump to the video") : null));
      if (onTrial) cell.onclick = () => onTrial(r);
      grid.append(cell);
    }
  }
  return grid;
}

/** Random mix: success rate over two factors (bins x bins of each factor's range). Shows interactions. */
export function interactionHeatmap(summary, xId, yId, { bins = 4 } = {}) {
  const fx = summary.factors.find((f) => f.id === xId), fy = summary.factors.find((f) => f.id === yId);
  const scored = summary.rows.filter((r) => !["invalid", "aborted"].includes(r.outcome));
  const binOf = (f, v) => Math.max(0, Math.min(bins - 1, Math.floor(((v - f.neutral) / ((f.max - f.neutral) || 1)) * bins)));
  const edge = (f, i) => +(f.neutral + ((f.max - f.neutral) * i) / bins).toFixed(1);
  const grid = h("div", { class: "rb-heat", style: { gridTemplateColumns: `110px repeat(${bins}, minmax(56px, 1fr))` } });
  grid.append(h("div", { class: "rb-heat-head" }, `↓ ${fy.label} (${fy.unit})`),
    ...Array.from({ length: bins }, (_, i) => h("div", { class: "rb-heat-head num" }, `${edge(fx, i)}–${edge(fx, i + 1)}`)));
  for (let yi = bins - 1; yi >= 0; yi--) {
    grid.append(h("div", { class: "rb-heat-label num" }, `${edge(fy, yi)}–${edge(fy, yi + 1)}`));
    for (let xi = 0; xi < bins; xi++) {
      const rows = scored.filter((r) => binOf(fx, r.params[xId]) === xi && binOf(fy, r.params[yId]) === yi);
      if (!rows.length) { grid.append(h("div", { class: "rb-cell rb-cell-empty" })); continue; }
      const k = rows.filter((r) => r.success).length;
      const { bg, fg } = rampColor(k / rows.length);
      const cell = h("div", { class: "rb-cell", style: { background: bg, color: fg } },
        h("strong", {}, pct(k / rows.length)), h("small", {}, `${k}/${rows.length}`));
      tooltip(cell, () => h("div", {}, h("b", {}, `${k}/${rows.length} successful`),
        h("div", {}, `${fx.label} ${edge(fx, xi)}–${edge(fx, xi + 1)} ${fx.unit}`),
        h("div", {}, `${fy.label} ${edge(fy, yi)}–${edge(fy, yi + 1)} ${fy.unit}`),
        h("div", { class: "muted" }, `trials ${rows.map((r) => `#${r.index}`).join(", ")}`)));
      grid.append(cell);
    }
  }
  return h("div", {}, grid, h("div", { class: "rb-heat-foot muted" }, `${fx.label} (${fx.unit}) →`));
}

// ---------------- adaptive breaking-point search ----------------

/**
 * Estimated P(measure) over strength with its 80% band, every trial as a dot (top = stage reached, bottom = not),
 * the breaking point with its 80% interval, and below it the belief about where the break lies.
 */
export function adaptiveChart(summary, { width = 288, height = 210 } = {}) {
  const p = summary.perturbation, a = summary.analysis, labels = summary.outcome_labels;
  const lo = p.neutral, hi = p.max;
  const m = { l: 32, r: 12, t: 12, b: 26 }, beliefH = 34, gap = 14;
  const W = width - m.l - m.r, H = height - m.t - m.b - beliefH - gap;
  const x = (v) => m.l + ((Math.min(Math.max(v, lo), hi) - lo) / (hi - lo || 1)) * W;
  const y = (v) => m.t + H - v * H;
  const root = svg("svg", { viewBox: `0 0 ${width} ${height}`, class: "rb-chart", role: "img",
    "aria-label": `Estimated ${a.measure.label.toLowerCase()} probability over ${p.label} strength` });

  for (const t of [0, 0.5, 1]) root.append(svg("line", { x1: m.l, x2: width - m.r, y1: y(t), y2: y(t), class: "rb-grid" }),
    svg("text", { x: m.l - 6, y: y(t) + 4, class: "rb-axis", "text-anchor": "end" }, `${t * 100}%`));
  const ticks = 4;
  for (let i = 0; i <= ticks; i++) {
    const v = lo + ((hi - lo) * i) / ticks;
    root.append(svg("text", { x: x(v), y: height - 8, class: "rb-axis", "text-anchor": i === 0 ? "start" : i === ticks ? "end" : "middle" },
      strength(+v.toFixed(2), p)));
  }

  const bp = a.verdict.breaking_point;
  if (bp !== null && bp !== undefined) {
    const [cl, ch] = a.estimate.ci;
    root.append(svg("rect", { x: x(cl), y: m.t, width: Math.max(1, x(ch) - x(cl)), height: H, class: "rb-ad-ci" }),
      svg("line", { x1: x(bp), x2: x(bp), y1: m.t, y2: m.t + H, class: "rb-break" }),
      svg("text", { x: x(bp) + (x(bp) > m.l + W * 0.8 ? -4 : 4), y: m.t + 9, class: "rb-break-label",
        "text-anchor": x(bp) > m.l + W * 0.8 ? "end" : "start" }, `breaks ≈ ${strength(+bp.toFixed(2), p)}`));
  }

  const c = a.curve;
  const band = c.s.map((s, i) => `${x(s)},${y(c.hi[i])}`).concat([...c.s].reverse().map((s, i) => `${x(s)},${y(c.lo[c.s.length - 1 - i])}`));
  root.append(svg("polygon", { points: band.join(" "), class: "rb-ad-band" }),
    svg("polyline", { points: c.s.map((s, i) => `${x(s)},${y(c.mean[i])}`).join(" "), class: "rb-ad-mean" }));

  // trials: stacked at the top (stage reached) or bottom (not reached) so repeats stay visible
  const stacks = {};
  const level = a.measure.level;
  for (const r of summary.rows) {
    if (r.progress === null || r.progress === undefined || ["invalid", "aborted"].includes(r.outcome)) continue;
    const hit = r.progress >= level - 1e-9;
    const key = `${r.value}-${hit}`;
    const k = (stacks[key] = (stacks[key] || 0) + 1) - 1;
    const cy = hit ? y(1) + 6 + k * 7 : y(0) - 6 - k * 7;
    const dot = svg("circle", { cx: x(r.value), cy, r: 4.5, fill: OUTCOME_COLORS[r.outcome], class: "rb-ad-dot" });
    root.append(dot);
    tooltip(dot, () => h("div", {}, h("b", {}, `Trial #${r.index} · ${strength(r.value, p)}`),
      h("div", {}, labels[r.outcome]), h("div", { class: "muted" }, r.search?.why === "baseline" ? "baseline trial" :
        `chosen as most informative${r.search?.ci_before ? `; interval before: ${r.search.ci_before.map((v) => +v.toFixed(2)).join("–")}` : ""}`)));
  }
  if (summary.state === "running" && a.next && a.next.s !== undefined && summary.rows.length >= (summary.config.baseline_trials || 0)) {
    root.append(svg("path", { d: `M${x(a.next.s) - 5},${m.t + H + 9} l5,-7 l5,7 z`, class: "rb-ad-next" },
      svg("title", {}, `next trial: ${strength(a.next.s, p)}`)));
  }

  // belief about the breaking point (posterior of theta), same x axis
  const top = m.t + H + gap, inRange = a.theta.s.map((s, i) => [s, a.theta.mass[i]]).filter(([s]) => s <= hi + 1e-9);
  const peak = Math.max(...a.theta.mass, 1e-9);
  const area = [`${x(lo)},${top + beliefH}`, ...inRange.map(([s, v]) => `${x(s)},${top + beliefH - (v / peak) * beliefH}`), `${x(hi)},${top + beliefH}`];
  root.append(svg("line", { x1: m.l, x2: width - m.r, y1: top + beliefH, y2: top + beliefH, class: "rb-grid" }),
    svg("polygon", { points: area.join(" "), class: "rb-ad-belief" }),
    svg("text", { x: m.l - 6, y: top + beliefH - 2, class: "rb-axis", "text-anchor": "end" }, "θ"));
  if (a.estimate.p_beyond > 0.05) {
    root.append(svg("text", { x: width - m.r, y: top + 8, class: "rb-axis", "text-anchor": "end" },
      `${Math.round(a.estimate.p_beyond * 100)}% beyond →`));
  }
  return root;
}

export function adaptiveLegend(summary) {
  return h("div", { class: "rb-chart-legend muted" },
    h("span", {}, h("i", { class: "rb-key-ad" }), `P(${summary.analysis.measure.label.toLowerCase()}), 80% band`),
    h("span", {}, h("i", { class: "rb-key-break" }), "breaking point ± 80%"),
    h("span", {}, h("i", { class: "rb-key-belief" }), "θ: where the break lies"));
}

/** One line: interval, trials used, why it stopped / what comes next. */
export function adaptiveStatus(summary) {
  const a = summary.analysis, p = summary.perturbation, e = a.estimate;
  const parts = [];
  if (a.observations.length) parts.push(`80% interval ${strength(+e.ci[0].toFixed(2), p)}–${e.ci[1] > p.max ? `>${strength(p.max, p)}` : strength(+e.ci[1].toFixed(2), p)}`);
  parts.push(`${summary.rows.length} of max. ${a.budget} trials`);
  if (summary.state === "running" && a.next?.gain !== null && summary.rows.length >= summary.config.baseline_trials) parts.push(`next: ${strength(a.next.s, p)}`);
  if (a.stopped_because && summary.state !== "running") parts.push(`stopped: ${a.stopped_because}`);
  return h("p", { class: "muted rb-ad-status" }, parts.join(" · "));
}

/** Report: every step of the search and why it went there. */
export function searchTable(summary) {
  const p = summary.perturbation, labels = summary.outcome_labels;
  return h("table", { class: "table rb-table" },
    h("thead", {}, h("tr", {}, ["#", "Strength", "Why", "Interval before", "Outcome"].map((t) => h("th", {}, t)))),
    h("tbody", {}, summary.rows.map((r) => h("tr", {},
      h("td", { class: "num" }, r.index),
      h("td", { class: "num" }, strength(r.value, p)),
      h("td", {}, r.search?.why === "baseline" ? "baseline" : r.search?.gain !== undefined ? `info gain ${r.search.gain.toFixed(2)}` : "–"),
      h("td", { class: "num" }, r.search?.ci_before ? r.search.ci_before.map((v) => +v.toFixed(1)).join("–") : "–"),
      h("td", {}, outcomeChip(r.outcome, labels))))));
}

/** Download buttons for one campaign. */
export function downloadButtons(id) {
  const base = `/api/ext/robustness/download/${encodeURIComponent(id)}`;
  const link = (href, text, title) => h("a", { class: "btn small btn-outline", href, download: "", title }, text);
  return h("div", { class: "rb-downloads" },
    link(`${base}/trials.csv`, "CSV", "One row per trial (comma-separated, UTF-8)"),
    link(`${base}/trials.csv?excel=true`, "Excel CSV", "Semicolons and decimal commas for German Excel"),
    link(`${base}/result.json`, "JSON", "Everything: config, analysis, all trials"),
    link(`${base}/report.html`, "Report (one file)", "The whole report as one HTML file, without videos"),
    link(`${base}/report.html?videos=true`, "Report with videos", "One HTML file with every recorded trial video inside (large)"),
    link(`${base}/bundle.zip`, "ZIP + videos", "result.json, trials.csv and every trial video"));
}
