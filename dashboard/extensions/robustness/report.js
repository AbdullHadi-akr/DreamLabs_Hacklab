// Full robustness report: /ext/robustness/report.html?id=<campaign id>

import { h, request } from "/static/lib/api.js";
import {
  adaptiveChart, adaptiveLegend, adaptiveStatus, chartLegend, describeParams, downloadButtons, factorScatter,
  factorTable, interactionHeatmap, outcomeBar, outcomeChip, outcomeGrid, outcomeLegend, pct, rampLegend, searchTable,
  strength, sweepChart, sweepTable,
} from "./charts.js";

const root = document.getElementById("report");
const id = new URLSearchParams(location.search).get("id");
let onlyFailures = false;
let last = null;
let scrolled = false;
let pair = null; // random mix: [x factor, y factor] of the interaction heatmap

async function load() {
  if (!id) {
    location.replace("runs.html");
    return;
  }
  const s = await request("GET", `/api/ext/robustness/results/${encodeURIComponent(id)}`);
  const signature = `${s.state}-${s.done}`;
  if (signature !== last) {
    last = signature;
    render(s);
  }
  if (s.state === "running") setTimeout(load, 3000);
}

function metric(label, value, unit = "") {
  return h("span", {}, label, " ", h("b", {}, value === null || value === undefined ? "–" : `${value}${unit}`));
}

function trialCard(r, s) {
  const m = r.metrics || {};
  const info = Object.entries(r.info || {}).map(([k, v]) => `${k}: ${Object.entries(v).map(([a, b]) => `${a} ${b}`).join(", ")}`);
  return h("article", { class: "rp-trial", id: `trial-${r.index}` },
    r.video
      ? h("video", { src: `/api/ext/robustness/video/${s.id}/${r.video}`, controls: true, preload: "metadata", muted: true, playsinline: true })
      : h("div", { class: "rp-novideo" }, r.outcome === "invalid" ? "Not run: no fair setup found" : "No video recorded"),
    h("div", { class: "rp-trial-body" },
      h("div", { class: "rp-trial-top" }, h("b", {}, `#${r.index}`), outcomeChip(r.outcome, s.outcome_labels)),
      h("div", {}, describeParams(r, s)),
      r.prompt !== s.config.task ? h("div", { class: "rp-prompt", title: "Prompt Dream-1 received" }, r.prompt) : null,
      h("div", { class: "rp-metrics" },
        metric("progress", pct(r.progress)),
        metric("reach", m.min_reach_cm, " cm"),
        metric("lift", m.max_lift_cm, " cm"),
        metric("to target", m.final_to_container_cm, " cm"),
        metric("others moved", m.others_moved_cm, " cm"),
        metric("success at", m.time_to_success_s, " s"),
      ),
      h("div", { class: "muted" }, `${r.stop_reason} · ${r.seconds}s · ${r.steps} steps` +
        (r.mean_rtt_s ? ` · RTT ${r.mean_rtt_s}s` : "") + (r.redraws ? ` · setup re-drawn ${r.redraws}×` : "")),
      info.length ? h("div", { class: "muted" }, info.join(" · ")) : null,
      r.note ? h("div", { class: "warn" }, r.note) : null,
    ));
}

function render(s) {
  document.title = `Robustness · ${s.perturbation ? s.perturbation.label : "Random mix"}`;
  const a = s.analysis;
  const trials = h("div", { class: "rp-trials" });
  const fillTrials = () => trials.replaceChildren(...s.rows.filter((r) => !onlyFailures || !r.success).map((r) => trialCard(r, s)));
  fillTrials();
  const filter = h("input", { type: "checkbox", checked: onlyFailures });
  filter.onchange = () => { onlyFailures = filter.checked; fillTrials(); };

  let left, right;
  if (s.mode === "adaptive") {
    left = h("section", { class: "card" }, h("h2", {}, `Where ${s.perturbation.label.toLowerCase()} breaks the model`),
      adaptiveChart(s, { width: 620, height: 330 }), adaptiveLegend(s), adaptiveStatus(s),
      h("p", { class: "rp-note" }, "Bayesian search (psi method): the curve is the estimated probability that the stage " +
        `“${a.measure.label}” holds; dots are trials (top: held, bottom: did not). Each next strength was the one ` +
        "expected to tell the most about the breaking point θ, the strength where the probability is half the baseline."),
      h("p", { class: "rp-note" }, s.perturbation.description));
    right = h("section", { class: "card" }, h("h2", {}, "Search path"), searchTable(s),
      h("h2", { style: { marginTop: "18px" } }, "All outcomes"),
      outcomeBar(countOutcomes(s.rows), s.outcome_labels), outcomeLegend(s.rows, s.outcome_labels));
  } else {
    left = s.mode === "sweep"
      ? h("section", { class: "card" }, h("h2", {}, `Success vs. ${s.perturbation.label.toLowerCase()}`),
        sweepChart(s, { width: 620, height: 280 }), chartLegend(),
        h("p", { class: "rp-note" }, s.perturbation.description))
      : h("section", { class: "card" }, h("h2", {}, "Strength vs. progress, per factor"),
        h("div", { class: "rp-scatter" }, s.factors.map((f) => h("div", {}, h("h3", {}, f.label), factorScatter(s, f)))),
        h("p", { class: "rp-note" }, "Each dot is one trial (progress 0 = never reached, .25 reached, .5 lifted, .75 carried to the container, 1 = success)."));
    right = h("section", { class: "card" },
      h("h2", {}, s.mode === "sweep" ? "Per strength" : "Per factor"),
      s.mode === "sweep" ? sweepTable(s, { detailed: true }) : factorTable(s, { detailed: true }),
      h("h2", { style: { marginTop: "18px" } }, "All outcomes"),
      outcomeBar(s.mode === "sweep" ? sumOutcomes(a.per_value) : a.overall.outcomes, s.outcome_labels),
      outcomeLegend(s.rows, s.outcome_labels));
  }

  const jump = (r) => {
    const card = document.getElementById(`trial-${r.index}`);
    if (!card) return;
    if (onlyFailures && r.success) { onlyFailures = false; filter.checked = false; fillTrials(); }
    document.getElementById(`trial-${r.index}`).scrollIntoView({ behavior: "smooth", block: "center" });
    history.replaceState(null, "", `#trial-${r.index}`);
  };
  let heat = null;
  if (s.mode === "sweep" && s.rows.length) {
    heat = h("section", { class: "card rp-section" },
      h("div", { class: "rp-section-head" }, h("h2", {}, "Every trial at a glance"),
        h("span", { class: "muted" }, "Row = trial number (same random direction at every strength), column = strength. Click a cell for its video.")),
      h("div", { class: "rp-heat-wrap" }, outcomeGrid(s, { onTrial: jump })),
      outcomeLegend(s.rows, s.outcome_labels));
  } else if (s.mode === "random" && s.factors.length >= 2) {
    const ids = s.factors.map((f) => f.id);
    if (!pair || !ids.includes(pair[0]) || !ids.includes(pair[1])) {
      const ranked = [...a.per_factor].sort((x, y) => (x.rho ?? 0) - (y.rho ?? 0)).map((f) => f.id);
      pair = [ranked[0], ranked[1]];
    }
    const box = h("div", { class: "rp-heat-wrap" });
    const draw = () => box.replaceChildren(interactionHeatmap(s, pair[0], pair[1]));
    const pick = (i) => {
      const el = h("select", {}, s.factors.map((f) => h("option", { value: f.id, selected: f.id === pair[i] }, f.label)));
      el.onchange = () => { pair[i] = el.value; draw(); };
      return el;
    };
    draw();
    heat = h("section", { class: "card rp-section" },
      h("div", { class: "rp-section-head" }, h("h2", {}, "Two factors together"),
        h("div", { class: "rp-filters", style: { marginTop: 0 } }, h("label", {}, "Across (x)", pick(0)), h("label", {}, "Down (y)", pick(1)))),
      h("p", { class: "rp-note" }, "Success rate when both factors are in a range — shows whether two harmless changes break the model together. " +
        "Few trials per cell: read it as a hint. Starts with the two most harmful factors."),
      box, rampLegend("Success rate"));
  }

  const started = new Date(s.started * 1000);
  root.replaceChildren(
    h("header", { class: "rp-head" },
      h("div", {},
        h("h1", {}, s.mode === "adaptive" ? `Breaking point: ${s.perturbation.label}` : s.mode === "sweep" ? s.perturbation.label : "Random perturbation mix"),
        h("div", { class: "rp-meta" },
          h("span", {}, "Task ", h("b", {}, `“${s.config.task}”`)),
          h("span", {}, "Policy ", h("b", {}, s.policy)),
          h("span", {}, h("b", {}, `${s.done}/${s.total}`), " trials · ", s.state),
          h("span", {}, started.toLocaleString()),
          s.mode === "adaptive" ? h("span", {}, "Measure ", h("b", {}, s.analysis.measure.label), " · searched ", h("b", {}, `${strength(s.perturbation.neutral, s.perturbation)}–${strength(s.perturbation.max, s.perturbation)}`)) : s.mode === "sweep" ? h("span", {}, "Strengths ", h("b", {}, s.values.map((v) => strength(v, s.perturbation)).join(", "))) : null,
        )),
      h("div", { class: "rp-head-actions" },
        downloadButtons(s.id),
        h("a", { class: "btn small btn-outline", href: "runs.html" }, "All runs"),
        h("a", { class: "btn small btn-outline", href: "/" }, "← Dashboard"))),
    h("div", { class: `rb-verdict ${a.verdict.breaking_point != null || a.verdict.most_harmful ? "bad" : ""}` }, a.verdict.text),
    h("div", { class: "rp-grid" }, left, right),
    ...(heat ? [heat] : []),
    h("div", { class: "rp-filter" }, h("h2", {}, "Trials"),
      h("label", { class: "check", style: { margin: 0 } }, filter, "Only failures"),
      h("span", { class: "muted" }, "Video: overhead camera + both wrist cameras — exactly what the policy saw.")),
    trials,
  );
  if (location.hash && !scrolled) {
    scrolled = true;
    document.querySelector(location.hash)?.scrollIntoView();
  }
}

function countOutcomes(rows) {
  const total = {};
  for (const r of rows) if (r.outcome) total[r.outcome] = (total[r.outcome] || 0) + 1;
  return total;
}

function sumOutcomes(perValue) {
  const total = {};
  for (const v of perValue) for (const [k, n] of Object.entries(v.outcomes)) total[k] = (total[k] || 0) + n;
  return total;
}

load().catch((e) => root.replaceChildren(h("p", { class: "bad" }, `Could not load the report: ${e.message}`)));
