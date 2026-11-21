// Robustness panel: configure a sweep or a random mix, watch it live, open the full report.

import {
  adaptiveChart, adaptiveLegend, adaptiveStatus, chartLegend, describeParams, factorTable, outcomeChip, outcomeLegend,
  pct, sweepChart, sweepTable,
} from "./charts.js";

const MEASURES = [
  ["success", "Success (object in container)"],
  ["carried", "Carried to the container"],
  ["lifted", "Lifted the target"],
  ["reached", "Reached the target"],
];

const RANDOM_DEFAULTS = ["target_shift", "container_shift", "camera_tilt", "light_dim", "prompt_typos"];

export async function mount(root, api) {
  const { h } = api.ui;
  const { groups, items } = await api.get("/perturbations");
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
  };
  function setMode(next) {
    mode = next;
    for (const [m, btn] of Object.entries(modeButtons)) btn.className = `btn small ${mode === m ? "" : "btn-outline"}`;
    sweepBox.hidden = mode === "random";
    valuesField.hidden = mode !== "sweep";
    adaptiveBox.hidden = mode !== "adaptive";
    randomBox.hidden = mode !== "random";
    trialsLabel.textContent = { sweep: "Trials per strength", random: "Trials in total", adaptive: "Budget (max. trials)" }[mode];
    if (mode !== "sweep" && Number(trials.value) < 10) trials.value = 12;
    if (mode === "sweep" && Number(trials.value) > 10) trials.value = 3;
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
    if (mode !== "sweep") return Number(trials.value || 0);
    const vals = parseValues(), p = byId[kind.value];
    const n = new Set(vals.includes(p.neutral) ? vals : [p.neutral, ...vals]).size;
    return n * Number(trials.value || 0);
  }
  function updateEstimate() {
    const n = trialCount();
    const upTo = mode === "adaptive" ? "up to " : "";
    estimate.textContent = (dry.checked
      ? `${upTo}${n} trials with the scripted replay (no API, no credits, ~6 s each).`
      : `${upTo}${n} Dream-1 runs of up to ${seconds.value} s → up to ~${Math.ceil((n * (Number(seconds.value) + 10)) / 60)} min. Uses credits!`)
      + (mode === "adaptive" ? " Usually stops earlier." : "");
    estimate.className = dry.checked ? "muted" : "warn";
  }
  kind.onchange = updateKind;
  for (const el of [values, trials, seconds, dry]) el.addEventListener("input", updateEstimate);

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
      dry_run: dry.checked, record: record.checked,
    };
    if (mode === "sweep") Object.assign(body, { perturbation: kind.value, values: parseValues() });
    else if (mode === "adaptive") Object.assign(body, { perturbation: kind.value, max_strength: Number(maxStrength.value),
      measure: measure.value, baseline_trials: Number(baselineTrials.value) });
    else body.factors = Object.fromEntries(Object.entries(factorInputs)
      .filter(([, f]) => f.check.checked).map(([id, f]) => [id, Number(f.max.value)]));
    if (!dry.checked && !confirm(`Start ${trialCount()} Dream-1 runs? This uses credits.`)) return;
    try { render(await api.post("/start", body)); } catch (e) { api.ui.toast(e.message, "error"); }
  }

  const reportUrl = (id, trial) => `${api.asset("report.html")}?id=${encodeURIComponent(id)}${trial ? `#trial-${trial}` : ""}`;

  function render(s) {
    if (!s) return;
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
    results.replaceChildren(h("div", {},
      h("div", { class: `rb-verdict ${a.verdict.breaking_point !== null && a.verdict.breaking_point !== undefined || a.verdict.most_harmful ? "bad" : ""}` },
        h("strong", {}, s.mode === "sweep" ? s.perturbation.label : s.mode === "adaptive" ? `Breaking point · ${s.perturbation.label}` : "Random mix"),
        h("span", {}, a.verdict.text)),
      s.mode === "sweep" ? [sweepChart(s), chartLegend(), sweepTable(s)]
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

  root.append(
    h("div", { class: "row rb-modes" }, modeButtons.sweep, modeButtons.random, modeButtons.adaptive),
    h("label", { class: "field" }, h("span", {}, "Task"), task),
    sweepBox, randomBox,
    h("div", { class: "row" },
      h("label", { class: "field" }, trialsLabel, trials),
      h("label", { class: "field" }, h("span", {}, "Seconds per trial"), seconds)),
    h("label", { class: "check", title: "Replays a pick-and-place planned once on the unperturbed scene. No API." },
      dry, "Dry run (scripted replay, no credits)"),
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
