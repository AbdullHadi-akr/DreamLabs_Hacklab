// Robustness panel: configure a sweep or a random mix, watch it live, open the full report.

import {
  adaptiveChart, adaptiveLegend, adaptiveStatus, chartLegend, compareChart, compareLegend, describeParams, factorTable,
  outcomeChip, outcomeLegend, pct, smoothnessChart, strategyTable, sweepChart, sweepTable,
} from "./charts.js";
import { renderReport } from "./report_view.js";

const MEASURES = [
  ["success", "Success (object in container)"],
  ["carried", "Carried to the container"],
  ["lifted", "Lifted the target"],
  ["reached", "Reached the target"],
];

const RANDOM_DEFAULTS = ["target_shift", "container_shift", "camera_tilt", "light_dim", "prompt_typos"];
const COMPARE_DEFAULTS = ["chunk", "crossfade-30", "receding-24"];  // baseline first; measured best of 22.11.2026
const VERDICT_TITLES = { sweep: null, adaptive: "Breaking point", random: "Random mix", compare: "Strategy A/B" };

export async function mount(root, api) {
  const { h } = api.ui;
  const { groups, items } = await api.get("/perturbations");
  const { presets } = await api.get("/strategies");
  const byId = Object.fromEntries(items.map((p) => [p.id, p]));
  let mode = "sweep";

  // ---------- configuration ----------
  const task = h("input", { value: api.core.task() || "put apple into the bowl" });
  const kind = h("select", {}, Object.entries(groups).map(([g, label]) =>
    h("optgroup", { label }, items.filter((p) => p.group === g).map((p) => h("option", { value: p.id }, p.label)))));
  const values = h("input", {});
  const desc = h("p", { class: "muted rb-desc" });
  const trials = h("input", { type: "number", min: 1, max: 100, value: 3 });
  const trialsLabel = h("span", {}, "Trials per strength");
  const seconds = h("input", { type: "number", min: 5, max: 600, value: 45 });
  const dry = h("input", { type: "checkbox", checked: true });
  const dryLabel = h("span", {}, "Dry run (scripted replay, no credits)");
  const record = h("input", { type: "checkbox", checked: true });
  const estimate = h("p", { class: "muted" });

  const factorInputs = {};
  const factorList = h("div", { class: "rb-factors" }, Object.entries(groups).flatMap(([g, label]) => [
    h("div", { class: "rb-factor-group" }, label),
    ...items.filter((p) => p.group === g).map((p) => {
      const check = h("input", { type: "checkbox", checked: RANDOM_DEFAULTS.includes(p.id) });
      const max = h("input", { type: "number", value: p.max, step: "any", min: p.neutral, title: "Maximum strength" });
      factorInputs[p.id] = { check, max };
      check.addEventListener("input", updateEstimate);
      return h("label", { class: "rb-factor", title: p.description }, check, h("span", {}, p.label),
        h("span", { class: "rb-factor-max" }, "≤", max, h("small", {}, p.unit)));
    }),
  ]));

  const valuesField = h("label", { class: "field" }, h("span", {}, "Strengths (comma-separated, baseline is added)"), values);
  const maxStrength = h("input", { type: "number", step: "any" });
  const maxUnit = h("span", {});
  const measure = h("select", {}, MEASURES.map(([v, t]) => h("option", { value: v }, t)));
  const baselineTrials = h("input", { type: "number", min: 1, max: 10, value: 3 });
  const adaptiveBox = h("div", { hidden: true },
    h("p", { class: "muted rb-desc" }, "Finds the strength where the model breaks with as few trials as possible: " +
      "baseline first, then every next strength is the one that tells the most about the breaking point. " +
      "Stops as soon as it is pinned down, or when nothing breaks."),
    h("div", { class: "row" },
      h("label", { class: "field" }, h("span", {}, "Search up to"), h("div", { class: "rb-inline" }, maxStrength, maxUnit)),
      h("label", { class: "field" }, h("span", {}, "Baseline trials"), baselineTrials)),
    h("label", { class: "field", title: "Dream-1 rarely succeeds unperturbed: then measure an earlier stage" },
      h("span", {}, "Stage that must hold"), measure));
  // inference strategy of a whole sweep / mix / search
  const strategy = h("select", {}, presets.map((x) => h("option", { value: x.id, title: x.description }, x.label)));
  const strategyField = h("label", { class: "field", title: "How Dream-1's 48-step action chunks are executed" },
    h("span", {}, "Execution strategy"), strategy);

  // strategy A/B
  const strategyChecks = {};
  const strategyList = h("div", { class: "rb-strategies" }, presets.map((x) => {
    const check = h("input", { type: "checkbox", checked: COMPARE_DEFAULTS.includes(x.id) });
    strategyChecks[x.id] = check;
    check.addEventListener("input", updateEstimate);
    return h("label", { class: "rb-strategy" }, check, h("span", {}, x.label, x.id === "chunk" ? " · default" : "",
      h("small", {}, x.description)));
  }));
  const extraStrategies = h("input", { placeholder: "e.g. ensemble-4, receding-24" });
  extraStrategies.addEventListener("input", updateEstimate);
  const condition = h("select", {}, h("option", { value: "none" }, "None (unperturbed scene)"),
    Object.entries(groups).map(([g, label]) =>
      h("optgroup", { label }, items.filter((p) => p.group === g).map((p) => h("option", { value: p.id }, p.label)))));
  const conditionStrength = h("input", { type: "number", step: "any" });
  const conditionUnit = h("span", {});
  const conditionStrengthField = h("label", { class: "field", hidden: true }, h("span", {}, "Strength"),
    h("div", { class: "rb-inline" }, conditionStrength, conditionUnit));
  condition.onchange = () => {
    const p = byId[condition.value];
    conditionStrengthField.hidden = !p;
    if (!p) return;
    const vals = p.defaults.filter((v) => v !== p.neutral);
    conditionStrength.value = vals.length ? vals[Math.floor((vals.length - 1) / 2)] : p.max;
    conditionUnit.textContent = p.unit;
  };
  const chosenStrategies = () => [...Object.entries(strategyChecks).filter(([, c]) => c.checked).map(([id]) => id),
    ...extraStrategies.value.split(/[,;\s]+/).map((x) => x.trim().toLowerCase()).filter(Boolean)]
    .filter((x, i, all) => all.indexOf(x) === i);
  const compareBox = h("div", { hidden: true },
    h("p", { class: "muted rb-desc" }, "Same trials, different ways of executing Dream-1's action chunks: pair i runs " +
      "under every strategy with the same seed, so differences come from the strategy, not from luck. The first " +
      "checked strategy is the baseline."),
    strategyList,
    h("label", { class: "field" }, h("span", {}, "More strategies"), extraStrategies),
    h("div", { class: "row" }, h("label", { class: "field" }, h("span", {}, "Under perturbation"), condition), conditionStrengthField));

  const sweepBox = h("div", {},
    h("label", { class: "field" }, h("span", {}, "Perturbation"), kind), desc, valuesField, adaptiveBox);
  const randomBox = h("div", { hidden: true },
    h("p", { class: "muted rb-desc" }, "Every trial draws a random strength (from none up to the maximum) for each " +
      "checked factor. Afterwards the factor whose strength correlates most with failure is named."),
    factorList);

  const modeButtons = {
    sweep: h("button", { class: "btn small", onclick: () => setMode("sweep") }, "Sweep"),
    random: h("button", { class: "btn small btn-outline", onclick: () => setMode("random") }, "Random mix"),
    adaptive: h("button", { class: "btn small btn-outline", onclick: () => setMode("adaptive"),
      title: "Bayesian search for the breaking point" }, "Breaking point"),
    compare: h("button", { class: "btn small btn-outline", onclick: () => setMode("compare"),
      title: "Compare inference strategies on paired trials" }, "Strategy A/B"),
  };
  function setMode(next) {
    mode = next;
    for (const [m, btn] of Object.entries(modeButtons)) btn.className = `btn small ${mode === m ? "" : "btn-outline"}`;
    sweepBox.hidden = mode === "random" || mode === "compare";
    valuesField.hidden = mode !== "sweep";
    adaptiveBox.hidden = mode !== "adaptive";
    randomBox.hidden = mode !== "random";
    compareBox.hidden = mode !== "compare";
    strategyField.hidden = mode === "compare";
    dryLabel.textContent = mode === "compare" ? "Dry run (scripted replay cut into noisy chunks, no credits)"
      : "Dry run (scripted replay, no credits)";
    trialsLabel.textContent = { sweep: "Trials per strength", random: "Trials in total", adaptive: "Budget (max. trials)",
      compare: "Pairs (trials per strategy)" }[mode];
    if ((mode === "random" || mode === "adaptive") && Number(trials.value) < 10) trials.value = 12;
    if (mode === "sweep" && Number(trials.value) > 10) trials.value = 3;
    if (mode === "compare" && (Number(trials.value) < 4 || Number(trials.value) > 20)) trials.value = 6;
    // categorical perturbations (prompt variants) have no order to search along
    for (const option of kind.querySelectorAll("option")) option.disabled = mode === "adaptive" && byId[option.value].discrete;
    if (mode === "adaptive" && byId[kind.value].discrete) { kind.value = "target_shift"; updateKind(); }
    updateEstimate();
  }

  const parseValues = () => values.value.split(/[,;\s]+/).filter(Boolean).map(Number).filter((v) => !Number.isNaN(v));
  function updateKind() {
    const p = byId[kind.value];
    values.value = p.defaults.join(", ");
    maxStrength.value = p.max;
    maxStrength.min = p.neutral;
    maxUnit.textContent = p.unit;
    desc.textContent = p.description;
    updateEstimate();
  }
  function trialCount() {
    if (mode === "compare") return chosenStrategies().length * Number(trials.value || 0);
    if (mode !== "sweep") return Number(trials.value || 0);
    const vals = parseValues(), p = byId[kind.value];
    const n = new Set(vals.includes(p.neutral) ? vals : [p.neutral, ...vals]).size;
    return n * Number(trials.value || 0);
  }
  function requestFactor() {
    const ids = mode === "compare" ? chosenStrategies() : [strategy.value];
    const factors = ids.map((id) => { const m = /-(\d+)$/.exec(id); return m ? 48 / Number(m[1]) : 1; });
    return factors.length ? factors.reduce((a, b) => a + b, 0) / factors.length : 1;
  }
  function updateEstimate() {
    const n = trialCount();
    const upTo = mode === "adaptive" ? "up to " : "";
    // simulated-time budget: each request adds its round trip (~1 s) on top of the motion time
    const wall = Number(seconds.value) * (1 + requestFactor() / 2.4) + 10;
    estimate.textContent = (dry.checked
      ? `${upTo}${n} trials with the scripted replay (no API, no credits, ~6 s each).`
      : `${upTo}${n} Dream-1 runs of ${seconds.value} s simulated time (~${Math.round(wall)} s each with request waits) → up to ~${Math.ceil((n * wall) / 60)} min. Uses credits!`)
      + (mode === "adaptive" ? " Usually stops earlier." : "")
      + (mode === "compare" && chosenStrategies().length < 2 ? " Pick at least two strategies." : "");
    estimate.className = dry.checked ? "muted" : "warn";
  }
  kind.onchange = updateKind;
  for (const el of [values, trials, seconds, dry, strategy]) el.addEventListener("input", updateEstimate);

  // ---------- run control ----------
  const startBtn = h("button", { class: "btn primary", onclick: start }, "Start");
  const stopBtn = h("button", { class: "btn danger", onclick: () => api.post("/stop"), disabled: true }, "Stop");
  const progressBar = h("div", { style: { width: "0%" } });
  const progressText = h("span", { class: "muted" });
  const currentText = h("div", { class: "rb-current muted" });
  const results = h("div", { class: "rb-results" });
  const history = h("select", { class: "rb-history" });

  async function start() {
    const body = {
      task: task.value.trim(), mode, trials: Number(trials.value), seconds: Number(seconds.value),
      dry_run: dry.checked, record: record.checked, strategy: strategy.value,
    };
    if (mode === "sweep") Object.assign(body, { perturbation: kind.value, values: parseValues() });
    else if (mode === "adaptive") Object.assign(body, { perturbation: kind.value, max_strength: Number(maxStrength.value),
      measure: measure.value, baseline_trials: Number(baselineTrials.value) });
    else if (mode === "compare") Object.assign(body, { strategies: chosenStrategies(), perturbation: condition.value,
      strength: byId[condition.value] ? Number(conditionStrength.value) : null });
    else body.factors = Object.fromEntries(Object.entries(factorInputs)
      .filter(([, f]) => f.check.checked).map(([id, f]) => [id, Number(f.max.value)]));
    if (!dry.checked && !confirm(`Start ${trialCount()} Dream-1 runs? This uses credits.`)) return;
    try { render(await api.post("/start", body)); } catch (e) { api.ui.toast(e.message, "error"); }
  }

  const reportUrl = (id, trial) => `${api.asset("report.html")}?id=${encodeURIComponent(id)}${trial ? `#trial-${trial}` : ""}`;

  // Inside the Test Suite the builder tiles pick the mode and the full report fills the wide report area.
  const embedded = root.classList.contains("suite-extension");
  const wideReport = () => document.getElementById("robustness-wide-report");
  let shown = null;

  function render(s) {
    if (!s) {
      const wide = wideReport();
      if (embedded && wide && !wide.childElementCount) {
        wide.append(h("div", { class: "rb-wide-empty" }, h("h2", { class: "pixel" }, "Robustness report"),
          h("p", { class: "muted" }, "Start a robustness test on the left, or open a past one from its history.")));
      }
      return;
    }
    shown = s;
    const wide = embedded ? wideReport() : null;
    if (wide) renderReport(wide, s, { standalone: false });
    const running = s.state === "running";
    startBtn.disabled = running;
    stopBtn.disabled = !running;
    progressBar.style.width = `${s.total ? (100 * s.done) / s.total : 0}%`;
    progressText.textContent = `${s.done}/${s.total} trials · ${s.state}${s.config.dry_run ? " · dry run" : ""}`;
    currentText.textContent = running && s.current ? `Now: ${s.current.label}` +
      (s.current.prompt !== s.config.task ? ` · prompt "${s.current.prompt}"` : "") : "";

    const a = s.analysis;
    const scored = s.rows.filter((r) => r.outcome !== "invalid");
    const invalid = s.rows.length - scored.length;
    if (wide) {  // the details are in the wide report; keep only the verdict here
      results.replaceChildren(h("div", { class: `rb-verdict ${a.verdict.breaking_point != null || a.verdict.most_harmful ? "bad" : ""}` },
        h("strong", {}, verdictTitle(s)),
        h("span", {}, a.verdict.text)),
        invalid ? h("p", { class: "muted" }, `${invalid} trial(s) not counted (no fair setup found, or the simulator glitched).`) : "");
      return;
    }
    results.replaceChildren(h("div", {},
      h("div", { class: `rb-verdict ${a.verdict.breaking_point !== null && a.verdict.breaking_point !== undefined || a.verdict.most_harmful ? "bad" : ""}` },
        h("strong", {}, verdictTitle(s)),
        h("span", {}, a.verdict.text)),
      s.mode === "compare" ? [compareChart(s), compareLegend(), smoothnessChart(s), strategyTable(s)]
      : s.mode === "sweep" ? [sweepChart(s), chartLegend(), sweepTable(s)]
        : s.mode === "adaptive" ? [adaptiveChart(s), adaptiveLegend(s), adaptiveStatus(s)]
          : factorTable(s),
      s.rows.length ? outcomeLegend(s.rows, s.outcome_labels) : null,
      invalid ? h("p", { class: "muted" }, `${invalid} trial(s) not counted (no fair setup found, or the simulator glitched).`) : null,
      h("h4", {}, "Trials"),
      h("div", { class: "rb-trials" }, [...s.rows].reverse().slice(0, 12).map((r) => h("a", {
        class: "rb-trial", href: reportUrl(s.id, r.index), target: "_blank",
        title: `${describeParams(r, s)}\n${r.prompt}\nprogress ${pct(r.progress)} · ${r.stop_reason}`,
      }, h("span", { class: "num" }, `#${r.index}`), h("span", { class: "rb-trial-param" }, describeParams(r, s)),
        outcomeChip(r.outcome, s.outcome_labels), r.video ? h("span", { class: "rb-cam", title: "video" }, "▶") : null))),
      h("div", { class: "row" },
        h("a", { class: "btn small btn-outline", href: reportUrl(s.id), target: "_blank" }, "Open full report ↗")),
    ));
  }

  function verdictTitle(s) {
    if (s.mode === "sweep") return s.perturbation.label;
    if (s.mode === "adaptive") return `Breaking point · ${s.perturbation.label}`;
    return VERDICT_TITLES[s.mode] || s.mode;
  }

  async function loadHistory() {
    try {
      const list = await api.get("/history");
      history.replaceChildren(h("option", { value: "" }, list.length ? "Past campaigns…" : "No past campaigns"),
        ...list.map((c) => h("option", { value: c.id }, `${c.id.slice(4, 8)} ${c.id.slice(9, 13)} · ${c.label} · ${c.done}/${c.total}${c.dry_run ? " · dry" : ""}`)));
    } catch { /* ignore */ }
  }
  history.onchange = async () => {
    if (!history.value) return;
    try { render(await api.get(`/results/${history.value}`)); } catch (e) { api.ui.toast(e.message, "error"); }
  };

  const modeRow = h("div", { class: "row rb-modes", hidden: embedded }, modeButtons.sweep, modeButtons.random, modeButtons.adaptive,
    modeButtons.compare);
  const modeTitle = h("h3", { class: "rb-suite-title", hidden: !embedded });
  const MODE_TITLES = { sweep: "Robustness sweep", adaptive: "Breaking point search", random: "Perturbation mix",
    compare: "Strategy A/B" };
  // The Test Suite's tiles send {detail: "sweep" | "adaptive" | "random"}; also re-show the last report.
  root.addEventListener("suite-mode", (event) => {
    setMode(event.detail);
    modeTitle.textContent = MODE_TITLES[event.detail] || "";
    if (shown) render(shown); else render(null);
  });

  root.append(
    modeTitle, modeRow,
    h("label", { class: "field" }, h("span", {}, "Task"), task),
    sweepBox, randomBox, compareBox, strategyField,
    h("div", { class: "row" },
      h("label", { class: "field" }, trialsLabel, trials),
      h("label", { class: "field", title: "Simulated time: waiting for Dream-1 does not count" },
        h("span", {}, "Seconds per trial (sim)"), seconds)),
    h("label", { class: "check", title: "Replays a pick-and-place planned once on the unperturbed scene. No API." },
      dry, dryLabel),
    h("label", { class: "check" }, record, "Record video of every trial"),
    estimate,
    h("div", { class: "row" }, startBtn, stopBtn),
    h("div", { class: "progress" }, h("div", { class: "bar" }, progressBar), progressText, currentText),
    results,
    h("h4", {}, "History"),
    h("div", { class: "rb-history-row" }, history,
      h("a", { class: "btn small btn-outline", href: api.asset("runs.html"), target: "_blank" }, "All runs, heatmap & downloads ↗")),
  );

  updateKind();
  render(await api.get("/status"));
  loadHistory();
  api.on("progress", (s) => { render(s); if (s.state !== "running") loadHistory(); });
  api.on("trial", (t) => { currentText.textContent = `Now: ${t.label}`; });
}
