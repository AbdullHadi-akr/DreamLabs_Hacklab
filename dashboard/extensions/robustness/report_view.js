// Renders a full robustness report into any element: the standalone report page and the Test Suite use it.

import { h } from "/static/lib/api.js";
import {
  adaptiveChart, adaptiveLegend, adaptiveStatus, chartLegend, compareChart, compareLegend, describeParams,
  downloadButtons, factorScatter, factorTable, interactionHeatmap, outcomeBar, outcomeChip, outcomeGrid, outcomeLegend,
  pairGrid, pairTable, pct, rampLegend, searchTable, smoothnessChart, strategyTable, strength, sweepChart, sweepTable,
} from "./charts.js";


const BASE = "/ext/robustness/";
const states = new WeakMap();

/** View state that survives re-rendering (filter checkbox, chosen heatmap factors, scroll). */
function stateOf(root) {
  if (!states.has(root)) states.set(root, { onlyFailures: false, pair: null, scrolled: false });
  return states.get(root);
}

function metric(label, value, unit = "") {
  return h("span", {}, label, " ", h("b", {}, value === null || value === undefined ? "–" : `${value}${unit}`));
}

function trialCard(r, s, prefix) {
  const m = r.metrics || {};
  const info = Object.entries(r.info || {}).map(([k, v]) => `${k}: ${Object.entries(v).map(([a, b]) => `${a} ${b}`).join(", ")}`);
  return h("article", { class: "rp-trial", id: `${prefix}${r.index}` },
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
        r.requests ? metric("requests", r.requests) : null,
        r.commands && r.commands.seam_ratio != null ? metric("seams", r.commands.seam_ratio, "× step") : null,
        m.joint_speed != null ? metric("speed", m.joint_speed, " rad/s") : null,
        m.joint_jitter != null ? metric("jitter", Math.round(m.joint_jitter * 100), "%") : m.joint_jerk != null ? metric("jerk", m.joint_jerk, " rad/s³") : null,
      ),
      h("div", { class: "muted" }, `${r.stop_reason} · ${r.seconds}s · ${r.steps} steps` +
        (r.mean_rtt_s ? ` · RTT ${r.mean_rtt_s}s` : "") + (r.redraws ? ` · setup re-drawn ${r.redraws}×` : "")),
      (r.timing || info.length || r.note) && h("details", {}, h("summary", {}, "Trial diagnostics"),
        r.timing && h("div", { class: "muted" }, `Trial wall time ${r.timing.trial_wall_s}s · Setup ${r.timing.setup_wall_s}s · Replay loop ${r.timing.replay_loop_wall_s}s · Simulated ${r.timing.simulated_s}s · Recording processing ${r.timing.recording_wall_s}s (partly within replay loop)`),
        info.length ? h("div", { class: "muted" }, info.join(" · ")) : null,
        r.note ? h("div", { class: "warn" }, r.note) : null),
    ));
}

export function renderReport(root, s, { standalone = true, historyControl = null } = {}) {
  const st = stateOf(root);
  const prefix = standalone ? "trial-" : "rbx-trial-";
  if (!standalone) {
    root.classList.add("rp", "rp-embedded");
    if (!document.querySelector(`link[href="${BASE}pages.css"]`)) {
      document.head.append(h("link", { rel: "stylesheet", href: `${BASE}pages.css` }));
    }
  }
  if (standalone) document.title = `Robustness · ${s.mode === "compare" ? "Strategy A/B" : s.perturbation ? s.perturbation.label : "Random mix"}`;
  const a = s.analysis;
  const trials = h("div", { class: "rp-trials" });
  let selectTrial;
  const fillTrials = () => {
    const rows = s.rows.filter((row) => !st.onlyFailures || !row.success);
    if (standalone) {
      trials.replaceChildren(...rows.map((row) => trialCard(row, s, prefix)));
      return;
    }
    if (!rows.length) {
      trials.replaceChildren(h("p", {class: "muted"}, "No trials to display."));
      return;
    }
    st.selection ??= new Map();
    const chosen = rows.find((row) => row.index === st.selection.get(s.id)) || rows[0];
    const inspector = h("div", {}, trialCard(chosen, s, prefix));
    const controls = new Map();
    selectTrial = (index) => {
      const row = rows.find((item) => item.index === index);
      if (!row) return;
      st.selection.set(s.id, index);
      controls.forEach((control, key) => control.setAttribute("aria-pressed", String(key === index)));
      inspector.replaceChildren(trialCard(row, s, prefix));
    };
    const table = h("table", {},
      h("thead", {}, h("tr", {}, ["Trial", "Perturbations", "Outcome", "Duration"].map((title) => h("th", {scope: "col"}, title)))),
      h("tbody", {}, rows.map((row) => {
        const control = h("button", {class: "btn btn-outline btn-sm", type: "button", "aria-pressed": String(row === chosen),
          "aria-label": `Inspect trial ${row.index}`, onclick: () => selectTrial(row.index)}, String(row.index));
        controls.set(row.index, control);
        return h("tr", {}, h("td", {}, control), h("td", {}, describeParams(row, s)),
          h("td", {}, outcomeChip(row.outcome, s.outcome_labels)), h("td", {}, row.seconds == null ? "—" : `${row.seconds} s`));
      })));
    trials.replaceChildren(h("div", {class: "suite-table suite-report-trials"}, table), inspector);
  };
  fillTrials();
  const filter = h("input", { type: "checkbox", checked: st.onlyFailures });
  filter.onchange = () => { st.onlyFailures = filter.checked; fillTrials(); };

  let left, right;
  if (s.mode === "compare") {
    const cond = s.perturbation ? `${s.perturbation.label.toLowerCase()} ${strength(s.perturbation.strength, s.perturbation)}` : "the unperturbed scene";
    left = h("section", { class: "card" }, h("h2", {}, "Success per strategy"),
      compareChart(s, { width: 620 }), compareLegend(),
      ...smoothnessSection(s),
      h("p", { class: "rp-note" }, `Paired design: pair i runs under every strategy with the same seed (same scene, ` +
        `${cond}${s.config.dry_run ? ", same simulated plan noise" : ""}). Only pairs where the strategies disagree carry ` +
        "information, which is what McNemar's test uses. Trials are budgeted in simulated time, so asking Dream-1 more " +
        "often costs requests, not motion time."),
      ...s.strategies.map((x) => h("p", { class: "rp-note" }, h("b", {}, `${x.label}: `), x.description)),
      s.strategies.some((x) => x.blend && x.blend !== "none" && !x.gripper)
        ? h("p", { class: "warn" }, "Recorded before the gripper fix: the blended strategies here also averaged the " +
          "gripper command, which can leave it half closed.") : null);
    right = h("section", { class: "card" }, h("h2", {}, "Versus the default"), pairTable(s),
      h("h2", { style: { marginTop: "18px" } }, "All outcomes"),
      outcomeBar(countOutcomes(s.rows), s.outcome_labels), outcomeLegend(s.rows, s.outcome_labels));
  } else if (s.mode === "adaptive") {
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
    if (st.onlyFailures && r.success) { st.onlyFailures = false; filter.checked = false; fillTrials(); }
    if (!standalone) selectTrial?.(r.index);
    const card = root.querySelector(`#${prefix}${r.index}`);
    if (!card) return;
    card.scrollIntoView({ block: "nearest" });
    if (standalone) history.replaceState(null, "", `#${prefix}${r.index}`);
  };
  let heat = null;
  if (s.mode === "compare" && s.rows.length) {
    heat = [
      h("section", { class: "card rp-section" },
        h("div", { class: "rp-section-head" }, h("h2", {}, "Smoothness and cost"),
          h("span", { class: "muted" }, "What each strategy does to the motion and to the API bill. Hover a column head for its meaning.")),
        h("div", { class: "rp-heat-wrap" }, strategyTable(s, { detailed: true }))),
      h("section", { class: "card rp-section" },
        h("div", { class: "rp-section-head" }, h("h2", {}, "Every pair at a glance"),
          h("span", { class: "muted" }, "Row = pair (same seed), column = strategy. Click a cell for its video.")),
        h("div", { class: "rp-heat-wrap" }, pairGrid(s, { onTrial: jump })),
        outcomeLegend(s.rows, s.outcome_labels)),
    ];
  } else if (s.mode === "sweep" && s.rows.length) {
    heat = h("section", { class: "card rp-section" },
      h("div", { class: "rp-section-head" }, h("h2", {}, "Every trial at a glance"),
        h("span", { class: "muted" }, "Row = trial number (same random direction at every strength), column = strength. Click a cell for its video.")),
      h("div", { class: "rp-heat-wrap" }, outcomeGrid(s, { onTrial: jump })),
      outcomeLegend(s.rows, s.outcome_labels));
  } else if (s.mode === "random" && s.factors.length >= 2) {
    const ids = s.factors.map((f) => f.id);
    if (!st.pair || !ids.includes(st.pair[0]) || !ids.includes(st.pair[1])) {
      const ranked = [...a.per_factor].sort((x, y) => (x.rho ?? 0) - (y.rho ?? 0)).map((f) => f.id);
      st.pair = [ranked[0], ranked[1]];
    }
    const box = h("div", { class: "rp-heat-wrap" });
    const draw = () => box.replaceChildren(interactionHeatmap(s, st.pair[0], st.pair[1]));
    const pick = (i) => {
      const el = h("select", {}, s.factors.map((f) => h("option", { value: f.id, selected: f.id === st.pair[i] }, f.label)));
      el.onchange = () => { st.pair[i] = el.value; draw(); };
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

  const controls = h("div", { class: "rp-filter" }, h("h2", {}, "Trials"),
    h("label", { class: "check", style: { margin: 0 } }, filter, "Only failures"));
  const counts = countOutcomes(s.rows);
  const summary = h("div", {class: "rp-campaign-summary"},
    h("p", {}, `${counts.success || 0} successful · ${s.rows.filter((r) => !r.success && r.outcome !== "invalid" && r.outcome !== "aborted").length} unsuccessful · ${(counts.invalid || 0) + (counts.aborted || 0)} unevaluated trials`),
    s.config.dry_run && h("p", {class: "muted"}, "Dream-1 outcome: Unevaluated. Only scripted replay was executed."),
    !s.rows.some((row) => row.outcome !== "invalid" && row.outcome !== "aborted") &&
      h("p", {class: "muted"}, "Success rate unavailable because no recorded trial received a verdict."));
  const started = new Date(s.started * 1000);
  root.replaceChildren(
    h("header", { class: `rp-head${standalone ? "" : " rp-head-embedded"}` },
      h("div", {},
        h("h1", {}, s.mode === "compare" ? "Strategy A/B: how Dream-1's chunks are executed"
          : s.mode === "adaptive" ? `Breaking point: ${s.perturbation.label}` : s.mode === "sweep" ? s.perturbation.label : "Random perturbation mix"),
        h("div", { class: "rp-meta" },
          h("span", {}, h("b", {}, `${s.done} of ${s.total}`), " trials recorded · ", ({done: "Completed", running: "Running", error: "Failed", stopped: "Stopped"})[s.state] || s.state),
          h("span", {}, "Task ", h("b", {}, `“${s.config.task}”`)),
          h("span", {}, "Policy ", h("b", {}, s.policy)),
          s.strategy && s.strategy.id !== "chunk" ? h("span", {}, "Execution ", h("b", {}, s.strategy.label)) : null,
          s.mode === "compare" ? h("span", {}, "Condition ", h("b", {}, s.perturbation ? `${s.perturbation.label} ${strength(s.perturbation.strength, s.perturbation)}` : "unperturbed")) : null,
          h("span", {}, started.toLocaleString()),
          s.mode === "adaptive" ? h("span", {}, "Measure ", h("b", {}, s.analysis.measure.label), " · searched ", h("b", {}, `${strength(s.perturbation.neutral, s.perturbation)}–${strength(s.perturbation.max, s.perturbation)}`)) : s.mode === "sweep" ? h("span", {}, "Strengths ", h("b", {}, s.values.map((v) => strength(v, s.perturbation)).join(", "))) : null,
        )),
      h("div", { class: "rp-head-actions" },
        historyControl,
        standalone ? downloadButtons(s.id) : h("details", {class: "report-export"},
          h("summary", {}, "Export"), h("div", {class: "export-items"}, downloadButtons(s.id))),
        h("a", { class: "btn small btn-outline", href: `${BASE}runs.html`, target: standalone ? null : "_blank" }, "All runs"),
        standalone ? h("a", { class: "btn small btn-outline", href: "/" }, "Dashboard")
          : h("a", { class: "btn small btn-outline", href: `${BASE}report.html?id=${encodeURIComponent(s.id)}`, target: "_blank" }, "Full page"))),
    summary,
    ...(!standalone ? [controls, trials] : []),
    h("div", { class: `rb-verdict ${a.verdict.breaking_point != null || a.verdict.most_harmful ? "bad" : ""}` }, a.verdict.text),
    ...(s.rows.length ? [h("details", {open: standalone}, h("summary", {}, "Campaign diagnostics"),
      h("div", { class: "rp-grid" }, left, right), ...(heat ? [heat].flat() : []))] : []),
    ...(standalone ? [controls, trials] : []),
  );
  if (standalone && location.hash && !st.scrolled) {
    st.scrolled = true;
    root.querySelector(location.hash)?.scrollIntoView();
  }
}

function smoothnessSection(s) {
  const chart = smoothnessChart(s, { width: 620 });
  if (!chart) return s.rows.length ? [h("p", { class: "rp-note" }, "No jitter measurement in this campaign (recorded before it " +
    "existed); absolute jerk is not shown because it mostly reflects speed.")] : [];
  return [h("h3", { class: "rp-subhead" }, "Smoothness of the measured motion",
    h("span", { class: "muted" }, " · share of the joint motion that is jitter; slowing down does not help")), chart];
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
