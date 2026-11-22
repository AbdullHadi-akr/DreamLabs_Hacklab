import { logPanel } from "/static/lib/log_panel.js";
import { request } from "/static/lib/api.js";
import { forkPanel } from "./fork_panel.js";
import { progressChart, runComparison, runDisplacement, runSelector, snapshotEntries } from "./run_analysis.js";

export async function mount(root, api) {
  const { h, toast } = api.ui;
  const find = (id) => document.getElementById(id);
  const results = find("test-suite-results");
  const monitor = find("test-suite-monitor");
  const dashboard = find("workspace-dashboard");
  const suite = find("workspace-test-suite");
  const path = "/api/ext/test_suite";
  const integer = (value, min, max) => h("input", { type: "number", value, min, max, required: true });
  const select = (choices) => h("select", {}, Object.entries(choices).map(([value, name]) => h("option", { value }, name)));
  const label = (text, input) => h("label", {}, text, input);
  const checkbox = (text, input) => h("label", { class: "suite-check" }, input, text);
  const button = (text, onclick, attrs = {}) => h("button", { type: "button", class: "btn btn-outline btn-sm", onclick, ...attrs }, text);
  const titles = { queued: "Queued", preparing: "Preparing", running: "Running", evaluating: "Evaluating",
    completed: "Completed", failed: "Failed", timed_out: "Timed out", error: "Error", cancelled: "Cancelled",
    task_deadline: "Task deadline", api_timeout: "API timeout", request_budget: "Request budget reached",
    task_completed: "Task completed", agent_idle: "No measurable movement",
    repeated_ineffective_actions: "Repeated actions without movement" };
  const status = (key) => titles[key] || key;
  const secondsText = (value) => value == null ? "—" : `${value.toFixed(1)} s`;
  const percent = (value) => value == null ? "Unavailable" : `${(100 * value).toFixed(1)}%`;
  const outcome = (run) => run.task_success == null ? "Unevaluated" : run.task_success ? "Success" : "Unsuccessful";
  const safetyOutcome = (value) => ({pass: "Pass", fail: "Violation", not_evaluated: "Not Evaluated"})[value] || "Not Evaluated";
  const scenarios = {reach: "Object offset", visibility: "Reduced visibility", combined: "Combined disturbance", baseline: "Baseline"};
  const signed = (value, unit) => `${value > 0 ? "+" : ""}${value}${unit}`;
  const direction = (item) => {
    if (item.stress_direction) return item.stress_direction;
    const value = item.stress_scenario === "visibility" ? item.tilt : item.offset;
    return value > 0 ? "positive" : value < 0 ? "negative" : "—";
  };
  const failure = (run) => run.failure_category?.replaceAll("_", " ").toLowerCase() ||
    (run.task_success === false ? status(run.termination_reason) || "Unavailable" : "—");
  const describe = {outcome, duration: secondsText, failure, safety: safetyOutcome, scene(run, campaignSeed) {
    const data = run.case || {};
    const seed = data.seed ?? campaignSeed;
    return [
      data.object && `Object ${data.object}`, Number.isFinite(data.offset) && signed(data.offset, " cm offset"),
      Number.isFinite(data.tilt) && signed(data.tilt, "° tilt"), Number.isFinite(data.light) && `${data.light}× light`,
      seed != null && `Seed ${seed}`, data.stress_scenario && (scenarios[data.stress_scenario] || data.stress_scenario),
      data.stress_direction && `${data.stress_direction} direction`,
    ].filter(Boolean).join(" · ") || "Unavailable";
  }};
  let activeId, selected, displayed, revision = 0, visible = false;
  let view = "build";
  let reportType = "";
  const reportRuns = new Map();
  const buildTab = find("suite-build-tab");
  const reportTab = find("suite-report-tab");
  const preview = find("simulation-preview");
  const latest = new Map();
  const logStates = new Map();
  const compareStates = new Map();
  const runStripScroll = new Map();
  const printMedia = window.matchMedia?.("print");
  let printPending = false;
  function resumeAfterPrint() {
    if (!printPending) return;
    printPending = false;
    window.dispatchEvent(new Event("dashboard:print-return"));
  }
  function printReport() {
    printPending = true;
    try { window.print(); }
    catch (error) { printPending = false; showError(error); }
  }
  window.addEventListener("afterprint", resumeAfterPrint);
  printMedia?.addEventListener("change", (event) => { if (!event.matches) resumeAfterPrint(); });
  window.addEventListener("focus", () => { if (!printMedia?.matches) resumeAfterPrint(); });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && !printMedia?.matches) resumeAfterPrint();
  });
  window.addEventListener("dashboard:print-return", () => {
    refreshRobustness();
    if (visible) refresh().catch(showError);
  });
  const notified = new Set();
  const loadedAt = Date.now() / 1000;

  function showReportType() {
    reportKind.value = reportType;
    regularReport.hidden = !!reportType;
    for (const [id, element] of Object.entries(extensionReports)) element.hidden = id !== reportType;
    extensions.find((ext) => ext.id === reportType)?.root.dispatchEvent(new Event("suite-show-report"));
  }

  function setView(next) {
    view = next;
    const report = visible && view === "report";
    for (const [tab, active] of [[buildTab, !report], [reportTab, report]]) {
      tab.classList.toggle("active", active);
      tab.setAttribute("aria-pressed", String(active));
    }
    root.hidden = !visible || report;
    results.hidden = !report;
    find("preview-summary").hidden = !report;
    preview.open = !report;
    document.querySelector(".layout").classList.toggle("suite-report-view", report);
    if (report) showReportType();
    renderLive();
  }

  function switchWorkspace(active, refreshReport = true) {
    visible = active;
    for (const [button, value] of [[suite, active], [dashboard, !active]]) {
      button.setAttribute("aria-pressed", String(value));
      button.classList.toggle("active", value);
    }
    monitor.hidden = !active;
    find("suite-view-nav").hidden = !active;
    for (const id of ["dashboard-tools", "taskbar", "right-slot"]) find(id).hidden = active;
    document.querySelector(".layout").classList.toggle("test-suite-layout", active);
    setView(view);
    if (active) {
      refreshRobustness();
      if (refreshReport) refresh().catch(showError);
    }
  }

  const modes = {
    quick: ["Quick Test", "Single task"], repeated: ["Repeated Runs", "Reliability"],
    sweep: ["Parameter Sweep", "Scene combinations"], safety: ["Safety Stress Test", "Challenging scenes"],
    ab: ["A/B Comparison", "Matched prompts"], reproduction: ["Failure Reproduction", "Replay a saved run"],
  };
  const mode = { value: "quick" };
  // Other extensions can add builder modes. Report selection is independent.
  const extensions = api.workspace?.extensions() || [];
  const robustnessRoot = extensions.find((ext) => ext.id === "robustness")?.root;
  // One dropdown (grouped: standard tests, then each extension's modes) instead of a grid of tiles.
  const modeInfo = Object.fromEntries([
    ...Object.entries(modes),
    ...extensions.flatMap((ext) => (ext.suite_modes || []).map((m) => [`${ext.id}:${m.id}`, [m.title, m.subtitle]])),
  ]);
  const modeSelect = h("select", { class: "suite-mode-select", "aria-label": "Test type" },
    h("optgroup", { label: "Standard tests" }, Object.entries(modes).map(([key, [name]]) => h("option", { value: key }, name))),
    extensions.filter((ext) => (ext.suite_modes || []).length).map((ext) => h("optgroup", { label: ext.title },
      ext.suite_modes.map((m) => h("option", { value: `${ext.id}:${m.id}` }, m.title)))));
  const modeHint = h("small", { class: "suite-mode-hint" });
  modeSelect.onchange = () => {
    mode.value = modeSelect.value;
    updatePlan();
    if (mode.value === "reproduction") loadFailures().catch(showError);
  };
  const extensionReports = Object.fromEntries(extensions.map((ext) =>
    [ext.id, h("div", { id: `${ext.id}-wide-report`, class: "suite-extension-report", hidden: true })]));
  const extensionOf = (key) => extensions.find((ext) => key.startsWith(`${ext.id}:`));
  const modeGrid = h("label", { class: "suite-mode-field" }, h("span", {}, "Test type"), modeSelect, modeHint);
  const task = h("textarea", { required: true, maxlength: 300, rows: 2, placeholder: "Put the banana on the plate" }, "Put the banana on the plate");
  const repeats = integer(1, 1, 100);
  const position = h("input", {type: "range", value: 0, min: 0, max: 20});
  const camera = h("input", {type: "range", value: 0, min: 0, max: 30});
  const positionValue = h("output");
  const cameraValue = h("output");
  const difficulty = select({ none: "None", low: "Low", medium: "Medium", high: "High" });
  const duration = integer(60, 1, 300);
  const seed = integer(0, 0, 4294967295);
  const requests = integer(30, 1, 200);
  const model = h("input", { value: find("model").value, required: true });
  const goal = h("input", { placeholder: "Put the banana on the plate" });
  const object = select({ "": "Infer from placement task", apple: "Apple", banana: "Banana", orange: "Orange", water_bottle: "Water bottle" });
  const record = h("input", { type: "checkbox" });
  const dry = h("input", { type: "checkbox" });
  const offsets = h("input", { placeholder: "Example: 0, 5, 10" });
  const tilts = h("input", { placeholder: "Example: 0, 10, 20" });
  const lights = h("input", { placeholder: "Example: 1, 0.65" });
  const candidate = h("textarea", {maxlength: 300, rows: 2, required: true});
  const candidateField = label("Prompt B", candidate);
  const taskField = label("Task", task);
  const repeatField = label("Repetitions", repeats);
  const stressChoices = [["reach", "Offset targets"], ["visibility", "Reduced light and camera tilt"], ["combined", "Combined disturbance"]]
    .map(([key, name]) => [key, name, h("input", {type: "checkbox", checked: key === "combined"})]);
  const baseline = h("input", {type: "checkbox"});
  const stressField = h("fieldset", {}, h("legend", {}, "Stress scenarios"),
    stressChoices.map(([, name, input]) => checkbox(name, input)), checkbox("Include an unperturbed baseline run", baseline));
  const failed = select({"": "Select a saved failed run"});
  const failedField = label("Previous failed run", failed);
  const variation = h("fieldset", {}, h("legend", {}, "Environment variation"),
    h("label", {}, h("span", {class: "suite-range-label"}, "Object position variation", positionValue), position),
    h("label", {}, h("span", {class: "suite-range-label"}, "Overhead camera variation", cameraValue), camera),
    label("Difficulty (scene lighting)", difficulty));
  const sweepInputs = h("fieldset", { hidden: true }, h("legend", {}, "Explicit sweep values"),
    h("p", { class: "muted" }, "Leave blank to use the variation controls. Separate values with commas."),
    label("Object X offsets (cm)", offsets), label("Overhead camera tilt (°)", tilts), label("Light multipliers", lights));
  const advanced = h("details", {}, h("summary", {}, "Advanced settings"), h("div", { class: "suite-form" },
    label("Maximum task duration (s)", duration), label("Maximum API requests per run", requests), label("Random seed", seed),
    label("Custom placement goal (optional)", goal), label("Object to move", object), label("Dream-1 model ID", model),
    sweepInputs, checkbox("Record camera video", record)));
  const plan = h("p", { class: "muted", role: "status" });
  const errorMessage = h("p", { role: "alert", hidden: true });
  const submit = h("button", { type: "submit", class: "btn primary" }, "Start campaign");
  const stop = button("Stop", () => control("stop"), { hidden: true, disabled: true, title: "Stop the current run and end the campaign" });
  const cancel = button("Cancel pending", () => control("cancel"), { hidden: true, disabled: true, title: "Finish the current run and cancel pending runs" });
  const dryField = checkbox("Dry run", dry);
  const form = h("form", { class: "suite-form" }, taskField, candidateField, repeatField, variation, stressField, failedField,
    advanced, h("div", {class: "campaign-actions"}, dryField, plan, errorMessage,
      h("div", { class: "suite-actions" }, submit, stop, cancel,
        button("Run Fork Here demo (offline)", async () => {
          try {
            selected = (await api.post("/fork-demo")).id;
            displayed = null;
            reportType = "";
            setView("report");
            await refresh();
          } catch (error) { showError(error); }
        }))));
  root.append(h("div", { class: "section-head" }, h("h2", { class: "pixel" }, "Test builder"),
    h("button", { type: "button", class: "fold-btn", title: "Hide the side panel (more room for the simulation)",
      onclick: () => find("left-collapse").click() }, "‹")), modeGrid, form, ...extensions.map((ext) => ext.root));

  const history = h("select", { "aria-label": "Campaign history" });
  results.tabIndex = -1;
  const content = h("div");
  const exportItems = h("div", {class: "export-items"});
  const exports = h("details", {class: "report-export", hidden: true}, h("summary", {}, "Export"), exportItems);
  const reportKind = h("select", {"aria-label": "Report type"}, h("option", {value: ""}, "Standard tests"),
    extensions.map((ext) => h("option", {value: ext.id}, ext.title)));
  const reportHead = h("div", { class: "section-head report-heading" }, h("h2", {}, "Test reports"), reportKind);
  const campaignTitle = h("h3", {}, "Campaign");
  const regularReport = h("div", {},
    h("div", {class: "section-head report-heading"}, campaignTitle, h("div", {class: "report-tools"}, history, exports)),
    content);
  results.append(reportHead, regularReport, ...Object.values(extensionReports));
  reportKind.addEventListener("change", () => { reportType = reportKind.value; showReportType(); });
  const liveTask = h("p");
  const liveStatus = h("p", { role: "status" });
  const elapsed = h("p", { class: "muted" });
  const liveProgress = h("progress", { max: 1, value: 0, "aria-label": "Campaign progress" });
  const monitorStop = button("Stop", async () => {
    if (current) return control("stop");
    if (!robustnessCampaign) return;
    try { await request("POST", "/api/ext/robustness/stop"); }
    catch (error) { showError(error); }
  });
  const monitorCancel = button("Cancel pending", () => control("cancel"));
  const monitorActions = h("div", {class: "suite-actions monitor-actions", hidden: true}, monitorStop, monitorCancel);
  monitor.append(h("div", { class: "section-head" }, h("h2", { class: "pixel" }, "Test execution")),
    liveTask, liveStatus, elapsed, liveProgress, monitorActions);
  let current;

  function showError(error) {
    let message = error.message;
    if (error.status === 422) {
      try { message = JSON.parse(message).map(({ msg }) => msg.replace(/^Value error, /, "")).join(" "); }
      catch { /* Use the original detail for other server errors. */ }
    }
    errorMessage.textContent = message;
    errorMessage.hidden = false;
    toast(message, "error");
  }

  function values(input) {
    const parts = input.value.trim() ? input.value.split(",") : [];
    if (parts.some((part) => !part.trim() || !Number.isFinite(Number(part)))) {
      throw new Error("Sweep values must be comma-separated numbers.");
    }
    return parts.length ? parts.map(Number) : null;
  }

  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
  function updatePlan() {
    const external = extensionOf(mode.value);
    modeSelect.value = mode.value;
    modeHint.textContent = (modeInfo[mode.value] || [])[1] || "";
    form.hidden = Boolean(external);
    for (const ext of extensions) {
      ext.root.hidden = ext !== external;
    }
    if (external) {
      external.root.dispatchEvent(new CustomEvent("suite-mode", { detail: mode.value.slice(external.id.length + 1) }));
      return;
    }
    const sweep = mode.value === "sweep";
    const replay = mode.value === "reproduction";
    const paired = mode.value === "ab";
    const safety = mode.value === "safety";
    const repeatsEnabled = sweep || paired || mode.value === "repeated";
    positionValue.textContent = `${position.value} cm`;
    cameraValue.textContent = `${camera.value}°`;
    repeatField.firstChild.textContent = paired ? "Paired scenarios" : sweep ? "Repetitions per combination" : "Repetitions";
    [repeatField.hidden, repeats.disabled] = [!repeatsEnabled, !repeatsEnabled];
    [candidateField.hidden, candidate.disabled] = [!paired, !paired];
    [taskField.hidden, task.disabled] = [replay, replay];
    [failedField.hidden, failed.disabled, failed.required] = [!replay, !replay, replay];
    [advanced.hidden, variation.hidden, stressField.hidden] = [replay, !repeatsEnabled, !safety];
    variation.disabled = !repeatsEnabled;
    for (const input of [duration, requests, seed, model, goal, object, record, dry]) input.disabled = replay;
    dryField.hidden = replay;
    const execution = dry.checked ? "Dry run · Setup and telemetry" : "Live API";
    object.parentElement.hidden = mode.value === "quick";
    seed.parentElement.hidden = !repeatsEnabled;
    sweepInputs.hidden = !sweep;
    repeats.setCustomValidity("");
    for (const [, , input] of stressChoices) input.setCustomValidity("");
    try {
      if (replay || mode.value === "quick" || safety) {
        const scenarios = stressChoices.filter(([, , input]) => input.checked).length;
        if (safety && scenarios === 0) stressChoices[0][2].setCustomValidity("Select a stress scenario.");
        plan.textContent = replay ? "One replay with the saved scene configuration."
          : safety ? `${plural(scenarios * 2 + Number(baseline.checked), "trial")} · ${execution}. Two directions per scenario${baseline.checked ? ", plus a baseline" : ""}.`
          : `1 trial · ${execution}`;
        return;
      }
      const count = Number(repeats.value);
      const n = sweep ? (values(offsets)?.length || (Number(position.value) ? 2 : 1)) *
        (values(tilts)?.length || (Number(camera.value) ? 2 : 1)) * (values(lights)?.length || 1) : 1;
      const total = n * count * (paired ? 2 : 1);
      if (total > 100) repeats.setCustomValidity("Reduce the campaign to 100 executions or fewer.");
      plan.textContent = sweep ? `${plural(total, "trial")} · ${execution}. ${plural(n, "scene combination")} × ${plural(count, "repetition")} (max 100).`
        : paired ? `${plural(total, "trial")} · ${execution}. ${plural(count, "pair")} × 2 prompts (max 100).`
        : `${plural(total, "trial")} · ${execution}`;
    } catch (error) {
      repeats.setCustomValidity(error.message);
      plan.textContent = error.message;
    }
  }
  form.addEventListener("input", updatePlan);
  updatePlan();

  async function loadFailures() {
    const chosen = failed.value;
    failed.replaceChildren(h("option", { value: "" }, "Loading saved runs…"));
    const items = await api.get("/failed-runs");
    failed.replaceChildren(h("option", {value: ""}, items.length ? "Select a failed run" : "No eligible failed runs"),
      ...items.map((item) => h("option", {value: `${item.id}/${item.number}`},
        `${new Date(item.created * 1000).toLocaleString()} · Run ${item.number} · ${item.prompt} · ${status(item.reason)}`)));
    if (items.some((item) => `${item.id}/${item.number}` === chosen)) failed.value = chosen;
  }

  function load(config) {
    mode.value = config.mode in modes ? config.mode : "repeated";
    task.value = config.prompt;
    candidate.value = config.prompt_b || "";
    for (const [key, , input] of stressChoices) input.checked = (config.stress_scenarios || ["combined"]).includes(key);
    baseline.checked = Boolean(config.stress_baseline);
    if (mode.value === "reproduction") loadFailures().catch(showError);
    model.value = config.model;
    repeats.value = config.repeats;
    position.value = config.position_variation ?? 0;
    camera.value = config.camera_variation ?? 0;
    difficulty.value = config.difficulty || "none";
    duration.value = config.seconds;
    requests.value = config.max_requests || 30;
    seed.value = config.seed;
    goal.value = config.goal;
    object.value = config.object || "";
    record.checked = config.record;
    dry.checked = config.dry_run;
    for (const [input, list] of [[offsets, config.positions], [tilts, config.tilts], [lights, config.lights]]) {
      input.value = list?.join(", ") || "";
    }
    updatePlan();
    setView("build");
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorMessage.hidden = true;
    submit.disabled = true;
    try {
      const config = { mode: mode.value, prompt: task.value, repeats: Number(repeats.value), model: model.value,
        position_variation: Number(position.value), camera_variation: Number(camera.value), difficulty: difficulty.value,
        seconds: Number(duration.value), max_requests: Number(requests.value), seed: Number(seed.value),
        goal: goal.value, object: object.value || null, record: record.checked, dry_run: dry.checked };
      if (config.mode === "sweep") Object.assign(config, { positions: values(offsets), tilts: values(tilts), lights: values(lights) });
      if (config.mode === "ab") config.prompt_b = candidate.value;
      if (config.mode === "safety") {
        config.stress_scenarios = stressChoices.filter(([, , input]) => input.checked).map(([key]) => key);
        config.stress_baseline = baseline.checked;
      }
      if (["quick", "safety"].includes(config.mode)) {
        Object.assign(config, {repeats: 1, seed: 0, position_variation: 0, camera_variation: 0, difficulty: "none"});
      }
      if (config.mode === "quick") config.object = null;
      if (config.mode === "reproduction") {
        const [id, number] = failed.value.split("/");
        selected = (await api.post(`/reports/${id}/repeat/${number}`)).id;
      } else {
        selected = (await api.post("/start", config)).id;
      }
      displayed = null;
      reportType = "";
      await refresh();
    } catch (error) { submit.disabled = Boolean(activeId); showError(error); }
  });

  async function control(command) {
    if (!activeId) return;
    try {
      await api.post(`/${command}`, { id: activeId });
      stop.disabled = command === "stop";
      cancel.disabled = true;
      toast(command === "stop" ? "Stopping at the next safe boundary." : "Pending runs will be cancelled.");
    } catch (error) { showError(error); }
  }

  const download = (url, text) => h("a", { class: "btn btn-outline btn-sm", href: url }, text);
  const detail = (title, value) => value == null ? null :
    h("details", {}, h("summary", {}, title), h("pre", {}, JSON.stringify(value, null, 2)));
  function bars(title, items, unit, fixedMax = null) {
    if (!items.length) return null;
    const max = fixedMax ?? Math.max(...items.map(([, value]) => value), 1);
    return h("section", { class: "suite-chart" }, h("h3", {}, title),
      items.map(([name, value]) => h("div", { class: "suite-bar" }, h("span", {}, name),
        h("meter", { min: 0, max, value, "aria-label": name }), h("span", {}, unit(value)))));
  }

  function latencyChart(samples) {
    if (!samples.length) return null;
    const canvas = h("canvas", { width: 720, height: 120, role: "img",
      "aria-label": "API response latency plotted in request order" });
    const context = canvas.getContext("2d");
    const max = Math.max(...samples, .01);
    context.strokeStyle = "#e76c29";
    context.fillStyle = "#e76c29";
    context.beginPath();
    samples.forEach((latency, i) => {
      const x = 5 + 710 * i / Math.max(1, samples.length - 1);
      const y = 115 - 110 * latency / max;
      if (samples.length === 1) context.fillRect(x, y, 4, 4);
      else if (i === 0) context.moveTo(x, y);
      else context.lineTo(x, y);
    });
    context.stroke();
    const edges = [.25, .5, 1, 2, Infinity];
    const counts = edges.map(() => 0);
    for (const latency of samples) counts[edges.findIndex((edge) => latency < edge)]++;
    const distribution = ["< 0.25 s", "0.25–0.5 s", "0.5–1 s", "1–2 s", "≥ 2 s"]
      .map((name, index) => [name, counts[index]]);
    return h("section", {}, h("h3", {}, "API latency per request"), canvas,
      bars("API latency distribution", distribution, String),
      h("p", { class: "muted" }, `${samples.length} requests in execution order · Scale 0–${secondsText(max)}`));
  }

  function inspect(report, run) {
    const base = `/reports/${report.id}`;
    const actionOutput = h("pre", {}, "Loading…");
    const timeline = h("details", {}, h("summary", {}, "Dream-1 action replies"), actionOutput);
    const evidence = run.evaluation_evidence;
    const phases = (run.timeline || []).filter((phase) => phase?.stage && Number.isFinite(phase.at));
    const events = (evidence?.events || []).filter((event) => event?.event && Number.isFinite(event.simulation_time));
    const checks = Object.entries(run.safety_checks || {}).filter(([name]) => name.trim());
    const coverage = checks.filter(([, result]) => result === "pass" || result === "fail").length;
    const displacement = runDisplacement(run);
    const frames = snapshotEntries(run, `${path}${base}`);
    const cm = (metres) => `${(metres * 100).toFixed(1)} cm`;
    const measures = [];
    if (displacement !== null) measures.push(["Object displacement", cm(displacement)]);
    if (Number.isFinite(evidence?.initial_planar_distance_m)) {
      measures.push(["Initial distance to target center (XY)", cm(evidence.initial_planar_distance_m)]);
    }
    if (Number.isFinite(evidence?.planar_distance_m)) {
      measures.push([`Final distance to ${evidence.target} center (XY)`, cm(evidence.planar_distance_m)]);
    }
    if (Number.isFinite(evidence?.best_planar_distance_m)) {
      measures.push(["Closest observed distance (XY)", cm(evidence.best_planar_distance_m)]);
    }
    if (Number.isFinite(evidence?.initial_planar_distance_m) && Number.isFinite(evidence?.best_planar_distance_m)) {
      measures.push(["Progress toward target (XY)", cm(Math.max(0, evidence.initial_planar_distance_m - evidence.best_planar_distance_m))]);
    }
    if (Number.isFinite(evidence?.target_radius_m)) measures.push(["Target radius", cm(evidence.target_radius_m)]);
    const fetchDetails = (element, loading, url, render) => {
      const load = async () => {
        if (!element.open) return;
        element.removeEventListener("toggle", load);
        try { loading.replaceChildren(render(await api.get(url))); }
        catch (error) {
          loading.textContent = error.message;
          element.addEventListener("toggle", load);
        }
      };
      element.addEventListener("toggle", load);
    };
    fetchDetails(timeline, actionOutput, `${base}/actions/${run.number}`, (actions) =>
      document.createTextNode(actions.length ? JSON.stringify(actions, null, 2) : "No action replies were recorded."));
    const progressBody = h("div", {}, "Loading…");
    const progress = h("details", {}, h("summary", {}, "Object-to-target progress"), progressBody);
    if (run.progress_available) {
      fetchDetails(progress, progressBody, `${base}/progress/${run.number}`, (data) => progressChart(h, data));
    }
    const snapshotTimeline = h("details", {}, h("summary", {}, `Snapshot timeline · ${frames.length} frames`));
    const renderSnapshots = () => {
      if (!snapshotTimeline.open) return;
      snapshotTimeline.removeEventListener("toggle", renderSnapshots);
      snapshotTimeline.append(h("div", {class: "suite-snapshot-grid"}, frames.map((frame) => h("figure", {class: "suite-frame"},
        h("img", {src: frame.url, alt: `${frame.title} for run ${run.number}`, loading: "lazy"}),
        h("figcaption", {}, frame.title, Number.isFinite(frame.simulation_time) &&
          ` · ${secondsText(frame.simulation_time)} simulation time`,
          frame.event && ` · ${frame.event.event} at ${secondsText(frame.event.simulation_time)}`)))));
    };
    snapshotTimeline.addEventListener("toggle", renderSnapshots);
    return h("section", { class: "suite-detail", id: "suite-inspector", tabindex: -1 }, h("h3", {}, `Run ${run.number} · ${outcome(run)}`),
      h("p", {}, run.case?.prompt || report.config.prompt),
      h("p", {}, `Execution · ${status(run.execution_status) || "Unavailable"} · Termination · ${status(run.termination_reason) || "Unavailable"}`),
      run.failure_category && h("p", {}, `Failure classification · ${run.failure_category.replaceAll("_", " ").toLowerCase()}`),
      run.last_verified_stage && h("p", {}, `Last verified stage · ${run.last_verified_stage}`),
      Number.isFinite(evidence?.last_progress_simulation_time) &&
        h("p", {}, `Last progress · ${secondsText(evidence.last_progress_simulation_time)} simulation time`),
      run.failure_reason && h("p", {}, run.failure_reason),
      h("p", {}, `${run.steps ?? "—"} control steps · ${run.api_request_count ?? run.requests ?? "—"} API requests`),
      h("p", {}, `Setup ${secondsText(run.setup_duration_seconds)} · Task ${secondsText(run.task_duration_seconds)}`),
      h("p", {}, `Monitored safety · ${safetyOutcome(run.safety_status)}`),
      h("p", {}, checks.length ? `Safety coverage · ${coverage} of ${checks.length} checks performed` : "Safety coverage unavailable for this report."),
      h("p", {}, `Scene · ${describe.scene(run, report.config.seed)}`),
      run.issues?.map((issue) => h("p", {}, `Scene diagnostic · ${issue.reason}${issue.preexisting ? " · Present before execution" : ""}`)),
      run.safety_violations?.map((issue) => h("p", {}, `Safety violation · ${issue.reason}`)),
      checks.length > 0 && h("ul", {}, checks.map(([check, result]) => h("li", {}, `${check} · ${safetyOutcome(result)}`))),
      run.action_diagnostics && h("p", {}, `${run.action_diagnostics.distinct_chunks} distinct action chunks · Robot movement ${run.action_diagnostics.robot_moved == null ? "unavailable" : run.action_diagnostics.robot_moved ? "observed" : "below threshold"}`),
      events.length > 0 ? h("ol", {}, events.map(({event, simulation_time}) =>
        h("li", {}, `${secondsText(simulation_time)} simulation time · ${event}`)))
        : h("p", {class: "muted"}, "No placement milestones recorded."),
      typeof evidence?.picked_up === "boolean" && h("p", {}, `Pickup ${evidence.picked_up ? "observed" : "not observed"} · Target entered ${evidence.entered_target_region ? "yes" : "no"} · Placement lost ${evidence.lost_candidate ? "yes" : "no"}`),
      evidence && h("p", {}, `${evidence.object} → ${evidence.target} · In target ${evidence.in_target_region ? "yes" : "no"} · Supported ${evidence.supported_by_target ? "yes" : "no"} · Robot contact at end ${evidence.released ? "no" : "yes"} · Stable ${secondsText(evidence.stable_seconds)} / ${secondsText(evidence.required_stable_seconds)}`),
      evidence?.released_after_pickup && h("p", {}, "Release observed after pickup."),
      measures.length ? h("dl", {class: "suite-motion"}, measures.flatMap(([name, value]) =>
        [h("dt", {}, name), h("dd", {}, value)])) : null,
      detail("Evaluation evidence", evidence), detail("Initial simulation state", run.initial_state),
      detail("Final simulation state", run.final_state),
      run.progress_available ? progress : h("p", {class: "muted"}, "No time-series target measurements were recorded."),
      phases.length > 0 && h("details", {}, h("summary", {}, "Execution timeline"), h("ol", {},
        phases.map(({stage, at}) => h("li", {}, `${status(stage)} · +${secondsText(at - phases[0].at)}`)))),
      run.api_events?.length ? detail("API requests, latencies and errors", run.api_events) : null, timeline,
      frames.length > 0 && snapshotTimeline,
      forkPanel({h, api, button, base, run}),
      run.video && h("details", {}, h("summary", {}, "Video replay"),
        h("video", {controls: true, preload: "none", src: `${path}${base}/video/${run.number}`})),
      !run.video && frames.length === 0 && h("p", { class: "muted" }, "No camera recording for this run."),
      button("Re-run identical settings", async () => {
        try { selected = (await api.post(`${base}/repeat/${run.number}`)).id; displayed = null; await refresh(); }
        catch (error) { showError(error); }
      }, { disabled: Boolean(activeId) || report.config.reset === false }));
  }

  const campaignState = (state) => ({done: "Completed", running: "Running", stopped: "Stopped",
    cancelled: "Cancelled", error: "Failed"})[state] || state;

  function render(report) {
    const base = `${path}/reports/${report.id}`;
    const stats = report.stats;
    const runs = report.trials;
    const runButtons = new Map();
    const selector = runs.length > 0 && runSelector(h, runs, displayed, describe, (run) => {
      displayed = run.number;
      reportRuns.set(report.id, run.number);
      for (const [number, control] of runButtons) {
        control.setAttribute("aria-pressed", String(number === displayed));
      }
      return inspect(report, run);
    });
    if (!compareStates.has(report.id)) compareStates.set(report.id, {});
    const compare = runs.length > 1 && runComparison(h, runs, {
      ...describe, scene: (run) => describe.scene(run, report.config.seed),
    }, compareStates.get(report.id));
    function openRun(run) {
      selector.select(run.number, {reveal: true});
      const inspector = find("suite-inspector");
      inspector.focus({ preventScroll: true });
      inspector.scrollIntoView({ block: "nearest" });
    }
    const summary = h("section", {class: "campaign-summary", "aria-label": "Campaign summary"},
      h("p", {}, `${campaignState(report.state)} · ${stats.trials} of ${report.total} runs recorded`),
      h("p", {}, `${stats.successes} successful · ${stats.failures} unsuccessful · ${stats.unevaluated} unevaluated`),
      h("p", {}, stats.evaluated ? `Evaluated success rate ${percent(stats.success_rate)} · Coverage ${percent(stats.coverage)}`
        : report.config.dry_run ? "Success rate unavailable because this dry run checks setup and telemetry." : "Success rate unavailable because no run received a task verdict."),
      Object.entries(report.reasons).sort((a, b) => b[1] - a[1]).map(([reason, count]) => {
        const first = report.trials.find((run) => run.failure_reason === reason);
        return h("p", { class: "suite-reason" }, h("span", {}, `${count} × ${reason}`),
          first && button(`Inspect run ${first.number}`, () => openRun(first)));
      }),
      h("p", {}, `Monitored safety · ${stats.safety.pass || 0} passed · ${stats.safety.fail || 0} with violations · ${stats.safety.not_evaluated || 0} not evaluated`));
    const config = h("section", {}, h("h3", {}, "Test configuration"),
      h("p", {}, `${modes[report.config.mode]?.[0] || "Historical campaign"} · ${report.config.model} · Seed ${report.config.seed}`),
      detail("Configuration values", report.config));
    const timing = h("section", {}, h("h3", {}, "Execution overview"),
      h("p", {}, `Observed task duration · average ${secondsText(stats.average_duration)} · median ${secondsText(stats.duration_p50)} · P95 ${secondsText(stats.duration_p95)} (${stats.duration_samples} runs)`),
      h("p", {}, `${report.execution.timed_out || 0} timed-out runs`),
      h("p", {}, `Successful completion average / P50 / P95: ${secondsText(stats.completion_average)} / ${secondsText(stats.completion_p50)} / ${secondsText(stats.completion_p95)}`),
      Object.entries(stats.durations_by_status).filter(([, times]) => times.length).map(([key, times]) =>
        h("p", {}, `${status(key)} durations: ${times.map(secondsText).join(", ")}`)),
      h("p", {}, `${stats.requests} API requests · Mean response latency ${secondsText(stats.mean_rtt)}`),
      h("p", { class: "muted" }, "Task time includes observation warm-up and API waits. Queuing, reset, final evaluation and recording cleanup are excluded. The API count includes SDK inference calls that failed."));
    const table = h("div", { class: "suite-table suite-report-trials" }, h("table", {},
      h("thead", {}, h("tr", {}, ["Run", "Execution", "Outcome", "Duration", "Reason"].map((name) => h("th", { scope: "col" }, name)))),
      h("tbody", {}, report.trials.map((run) => {
        const control = button(String(run.number), () => openRun(run), { "aria-label": `Inspect run ${run.number}`,
          "aria-pressed": String(run.number === displayed) });
        runButtons.set(run.number, control);
        return h("tr", {}, h("td", {}, control), h("td", {}, status(run.execution_status)),
          h("td", {}, outcome(run)), h("td", {}, secondsText(run.task_duration_seconds)),
          h("td", {}, run.failure_reason || "—"));
      }))));
    const latency = report.trials.flatMap((run) => run.rtts_s || []);
    const chartItems = [
      bars("Task duration per run", report.trials.filter((run) => run.task_duration_seconds != null)
        .map((run) => [`Run ${run.number} · ${status(run.execution_status)}`, run.task_duration_seconds]), secondsText),
      stats.requests > 0 && bars("API requests per run", report.trials.map((run) => [`Run ${run.number}`, run.api_request_count]), String),
      bars("Outcome distribution", stats.trials ? [["Successful", stats.successes], ["Unsuccessful", stats.failures], ["Unevaluated", stats.unevaluated]] : [], String),
      bars("Success by scene (offset / tilt / light)", Object.entries(report.conditions)
        .filter(([, row]) => row.evaluated).map(([name, row]) => [`${name} (n=${row.evaluated})`, row.success_rate]), percent, 1),
      latencyChart(latency),
    ].filter(Boolean);
    const charts = chartItems.length > 0 && h("details", {}, h("summary", {}, "Performance charts"), chartItems);
    const diagnostics = h("section", {}, h("h3", {}, "Campaign diagnostics"),
      Object.entries(report.diagnostics?.termination || {}).map(([reason, count]) => h("p", {}, `${count} runs · ${status(reason)}`)),
      Object.entries(report.diagnostics?.categories || {}).map(([reason, count]) =>
        h("p", {}, `${count} runs · ${reason.replaceAll("_", " ").toLowerCase()}`)),
      report.diagnostics?.outside_target > 0 && h("p", {}, `${report.diagnostics.outside_target} runs ended with the object outside its target region.`));
    const comparison = report.comparison && h("section", {}, h("h3", {}, "Matched prompt comparison"),
      ["A", "B"].map((variant) => {
        const group = report.comparison.variants[variant];
        const prompt = variant === "A" ? report.config.prompt : report.config.prompt_b;
        return h("div", {}, h("strong", {}, `${variant} · ${prompt}`),
          h("p", {}, `${group.successes}/${group.evaluated || "—"} evaluated successes · Mean completion ${secondsText(group.completion_average)} · ${group.safety.fail || 0} safety flags`),
          Object.entries(group.failures_by_stage).map(([key, n]) => h("p", {}, `${n} · ${key.replaceAll("_", " ").toLowerCase()}`)));
      }),
      h("p", {}, `${report.comparison.discordant} discordant pairs among ${report.comparison.evaluated_pairs} evaluated pairs`),
      report.comparison.pairs.length > 0 && h("div", {class: "suite-table"}, h("table", {},
        h("thead", {}, h("tr", {}, ["Pair", "Prompt A", "Prompt B", "Elapsed B − A"].map((title) => h("th", {scope: "col"}, title)))),
        h("tbody", {}, report.comparison.pairs.map((pair) => h("tr", {}, h("td", {}, pair.number),
          h("td", {}, outcome({task_success: pair.outcome_a})), h("td", {}, outcome({task_success: pair.outcome_b})),
          h("td", {}, secondsText(pair.duration_delta))))))));
    const replay = report.reproduction;
    const reproduced = report.trials[0];
    const targetObject = reproduced?.evaluation_evidence?.object || reproduced?.case?.object;
    const originalPosition = replay?.final_state?.positions_m?.[targetObject];
    const reproducedPosition = reproduced?.final_state?.positions_m?.[targetObject];
    const displacement = originalPosition && reproducedPosition &&
      Math.hypot(...reproducedPosition.map((position, axis) => position - originalPosition[axis]));
    const reproduction = replay && h("section", {}, h("h3", {}, "Original and reproduced run"),
      h("p", {}, replay.restored_physics
        ? "Recorded physics state and scene settings restored. Model responses can vary between runs."
        : "Recorded scene parameters and seed restored. The original report predates physics-state capture."),
      Number.isFinite(displacement) && h("p", {}, `Final ${targetObject} position differed by ${(100 * displacement).toFixed(1)} cm.`),
      button("View original report", () => {
        selected = replay.campaign;
        reportRuns.set(replay.campaign, replay.number);
        displayed = replay.number;
        refresh().catch(showError);
      }),
      [replay, reproduced].filter(Boolean).map((run, i) => h("div", {},
        h("strong", {}, i ? "Reproduced" : `Original run ${replay.number}`),
        h("p", {}, `${outcome(run)} · ${status(run.termination_reason)} · ${secondsText(run.task_duration_seconds)} · ${run.last_verified_stage || "Stage unavailable"}`),
        run.failure_category && h("p", {}, run.failure_category.replaceAll("_", " ").toLowerCase()),
        detail("Progress evidence", run.evaluation_evidence), detail("Final object positions", run.final_state?.positions_m))));
    const stress = report.stress;
    const rate = (successes, total) => total > 0 ? `${percent(successes / total)} (${successes}/${total})` : "Not Evaluated";
    const analysisRows = [...(stress?.baseline ? [["baseline", stress.baseline]] : []), ...Object.entries(stress?.scenarios || {})];
    const comparisonRate = (group) => {
      if (!stress.baseline?.evaluated || !group.evaluated) return "";
      const delta = 100 * (group.successes / group.evaluated - stress.baseline.successes / stress.baseline.evaluated);
      return ` · ${delta >= 0 ? "+" : ""}${delta.toFixed(1)} pp vs. baseline`;
    };
    const stressTable = (columns, rows) => h("div", {class: "suite-table"}, h("table", {},
      h("thead", {}, h("tr", {}, columns.map((column) => h("th", {scope: "col"}, column)))),
      h("tbody", {}, rows.map((row) => h("tr", {}, row.map((value) => h("td", {}, value)))))));
    const safety = stress && h("section", {}, h("h3", {}, "Stress findings"),
      h("p", {class: "muted"}, "Passing the monitored simulation checks does not establish physical robot safety."),
      report.trials.length === 0 ? h("p", {}, "Stress findings will appear after a run is recorded.") : [
        stressTable(["Scenario", "Task success", "Pickup", "Stable placement", "Timeout", "Mean target progress"],
          analysisRows.map(([name, group]) => [
            scenarios[name] || "Unlabeled", rate(group.successes, group.evaluated) + (name === "baseline" ? "" : comparisonRate(group)),
            rate(group.pickups, group.pickup_observed), rate(group.placements, group.placement_observed),
            rate(group.timeouts, group.runs), group.mean_progress_m == null ? "Not Evaluated" : `${(100 * group.mean_progress_m).toFixed(1)} cm`,
          ])),
        !stress.baseline && h("p", {class: "muted"}, "No baseline run was recorded for this campaign."),
        h("p", {class: "muted"}, "Target progress measures the mean reduction in closest planar distance from the starting position."),
        h("p", {}, `Safety coverage · ${Object.values(stress.total.checks).reduce((sum, count) => sum + count, 0)} run-level checks performed`),
        stress.total.check_names.map((name) => stress.total.checks[name]
          ? h("p", {}, `${name} · ${stress.total.checks[name]} runs monitored · ${stress.total.violations[name] || 0} runs with violations`)
          : h("p", {}, `${name} · Not Evaluated`)),
        stressTable(["Run", "Scenario", "Direction", "Object offset", "Camera tilt", "Lighting", "Seed", "Task", "Monitored safety", "Last verified stage"],
          report.trials.map((run) => [
            button(String(run.number), () => openRun(run), {"aria-label": `Inspect stress run ${run.number}`}),
            scenarios[run.case.stress_scenario] || "Unlabeled", direction(run.case),
            signed(run.case.offset, " cm"), signed(run.case.tilt, "°"), `${run.case.light}×`,
            run.case.seed ?? report.config.seed, outcome(run), safetyOutcome(run.safety_status), run.last_verified_stage || "Unavailable",
          ])),
      ].flat());
    const sensitivity = report.config.mode === "sweep" && stats.evaluated > 0 &&
      h("details", {}, h("summary", {}, "Parameter sensitivity"), [
        ["offset", "Object offset", " cm"], ["tilt", "Camera tilt", "°"], ["light", "Lighting", "×"],
      ].map(([key, name, unit]) => {
        const groups = new Map();
        for (const run of report.trials.filter((trial) => trial.task_success != null)) {
          const value = run.case[key];
          const group = groups.get(value) || { successes: 0, evaluated: 0 };
          group.successes += Number(run.task_success);
          group.evaluated++;
          groups.set(value, group);
        }
        return bars(name, [...groups.entries()].sort(([a], [b]) => a - b).map(([value, group]) =>
          [`${value}${unit} (n=${group.evaluated})`, group.successes / group.evaluated]), percent, 1);
      }));
    if (!logStates.has(report.id)) logStates.set(report.id, {});
    const campaignLog = logPanel("Execution log", logStates.get(report.id));
    campaignLog.update([...report.logs].sort((a, b) => (a.at || 0) - (b.at || 0)));
    campaignTitle.textContent = report.config.prompt;
    exports.hidden = false;
    exportItems.replaceChildren(download(`${base}/export/json`, "JSON"), download(`${base}/export/csv`, "CSV"),
      button("Print / PDF", () => { exports.open = false; printReport(); }));
    content.replaceChildren(summary, stats.trials > 0 ? table : h("p", {class: "muted"}, "No runs recorded yet."),
      ...[selector && selector.element, compare, comparison, reproduction, safety, sensitivity, charts].filter(Boolean),
      h("details", {}, h("summary", {}, "Campaign diagnostics"), config, timing, diagnostics,
        button("Load configuration", () => load(report.config), {class: "btn btn-outline btn-sm suite-no-print"})),
      campaignLog.panel);
    if (selector) {
      selector.strip.scrollLeft = runStripScroll.get(report.id) || 0;
      selector.strip.addEventListener("scroll", () => runStripScroll.set(report.id, selector.strip.scrollLeft));
    }
  }

  function completionBanner(id, type, title, summary, failed, open) {
    const notice = h("article", {class: `campaign-banner${failed ? " error" : ""}`,
      "data-report-type": type, "data-campaign-id": id},
      h("div", {}, h("strong", {}, title), h("p", {}, summary)),
      h("div", {class: "suite-actions"}, button("View report", async () => {
        try {
          await open();
          results.focus({preventScroll: true});
          results.scrollIntoView({block: "start"});
          notice.remove();
        } catch (error) { showError(error); }
      }), button("Dismiss", () => notice.remove())));
    find("campaign-notices").append(notice);
  }

  let robustnessCampaign = null;
  let robustnessRevision = 0;
  function updateRobustness(campaign) {
    robustnessRevision++;
    robustnessCampaign = campaign?.state === "running" ? campaign : null;
    if (visible) renderLive();
  }

  async function refreshRobustness() {
    if (!robustnessRoot) return;
    const requested = ++robustnessRevision;
    try {
      const campaign = await request("GET", "/api/ext/robustness/status");
      if (requested === robustnessRevision) updateRobustness(campaign);
    } catch (error) {
      console.error("Could not refresh the Robustness campaign status", error);
    }
  }

  function renderLive() {
    monitorActions.hidden = view !== "report" || !(current || robustnessCampaign);
    monitorCancel.hidden = !current;
    if (!current && robustnessCampaign) {
      const {mode, config, done, total, current: trial, started} = robustnessCampaign;
      const name = ({adaptive: "Breaking Point", sweep: "Robustness Sweep", random: "Random Mix"})[mode] || "Robustness";
      liveTask.textContent = trial?.index > done ? trial.prompt : config.task;
      liveStatus.textContent = `${name} · Trial ${Math.min(total, Math.max(done + 1, trial?.index || 0))} of ${total}${config.dry_run ? " · Dry run" : ""}`;
      elapsed.textContent = `Elapsed ${secondsText(Math.max(0, Date.now() / 1000 - started))}`;
      liveProgress.hidden = false;
      liveProgress.max = total;
      liveProgress.value = done;
      return;
    }
    const event = activeId && (latest.get(activeId) || current?.live);
    liveTask.textContent = event?.task || current?.config.prompt || "";
    liveStatus.textContent = current ? (event ? `Trial ${event.trial} of ${event.total} · ${status(event.status)}`
      : `${current.completed} of ${current.total} runs recorded`) : "No campaign running";
    elapsed.textContent = current?.created ? `Elapsed ${secondsText(Math.max(0, Date.now() / 1000 - current.created))}` : "";
    liveProgress.hidden = !current;
    if (current) { liveProgress.max = current.total; liveProgress.value = current.completed; }
  }

  async function refresh() {
    const request = ++revision;
    const items = await api.get("/history");
    if (request !== revision) return;
    current = items.find((item) => item.state === "running");
    activeId = current?.id;
    const streamed = latest.get(activeId);
    if (current?.live && (!streamed || (current.live.at ?? 0) >= (streamed.at ?? 0))) {
      latest.set(activeId, current.live);
    }
    submit.disabled = Boolean(current);
    stop.hidden = cancel.hidden = !current;
    stop.disabled = !current;
    cancel.disabled = !current;
    renderLive();
    selected ||= activeId || items[0]?.id;
    history.replaceChildren(...items.map((item) => h("option", { value: item.id },
      `${new Date(item.created * 1000).toLocaleString()} · ${item.config.prompt}`)));
    if (!selected) { content.textContent = "Start a campaign to see results."; return; }
    history.value = selected;
    const report = await api.get(`/reports/${selected}`);
    if (request !== revision) return;
    displayed = reportRuns.get(report.id) ?? displayed;
    render(report);
  }

  history.addEventListener("change", () => { selected = history.value; displayed = null; refresh().catch(showError); });
  api.on("progress", (event) => { latest.set(event.id, event); if (visible) renderLive(); });
  for (const name of ["trial", "ended"]) api.on(name, () => { if (visible) refresh().catch(showError); });
  api.on("ended", (event, envelope) => {
    if (!event.stats || !["done", "stopped", "cancelled", "error"].includes(event.state) ||
        notified.has(event.id) || envelope?.t < loadedAt) return;
    notified.add(event.id);
    const {trials, successes, failures, unevaluated} = event.stats;
    const title = {done: "Test Campaign Complete", stopped: "Campaign Stopped", cancelled: "Campaign Cancelled",
      error: "Campaign Failed"}[event.state];
    completionBanner(event.id, "test-suite", event.name ? `${event.name} · ${title}` : title,
      `${trials} of ${event.total} runs recorded · ${successes} successful · ${failures} unsuccessful · ${unevaluated} unevaluated`,
      event.state === "error", async () => {
        selected = event.id;
        reportType = "";
        view = "report";
        displayed = null;
        switchWorkspace(true, false);
        await refresh();
      });
  });
  robustnessRoot?.addEventListener("suite-campaign-started", (event) => updateRobustness(event.detail));
  api.onCore("ext.robustness.progress", (campaign, envelope) => {
    updateRobustness(campaign);
    if (!["done", "stopped", "error"].includes(campaign.state) || notified.has(campaign.id) ||
        !envelope || envelope.t < loadedAt) return;
    notified.add(campaign.id);
    const successes = campaign.rows.filter((row) => row.success).length;
    const unevaluated = campaign.rows.filter((row) => ["invalid", "aborted"].includes(row.outcome)).length;
    completionBanner(campaign.id, "robustness", `${campaign.config.task} · ${campaignState(campaign.state)}`,
      `${campaign.done} of ${campaign.total} trials recorded · ${successes} successful · ${campaign.done - successes - unevaluated} unsuccessful · ${unevaluated} unevaluated${campaign.config.dry_run ? " · Scripted replay" : ""}`,
      campaign.state === "error", () => {
        reportType = "robustness";
        view = "report";
        switchWorkspace(true, false);
        robustnessRoot?.dispatchEvent(new CustomEvent("suite-open-report", {detail: campaign.id}));
      });
  });
  api.onCore("ext.robustness.trial", (trial) => {
    if (robustnessCampaign) {
      updateRobustness({...robustnessCampaign, current: trial});
    } else if (visible) {
      refreshRobustness();
    }
  });
  api.onCore("ws.open", () => {
    if (visible) {
      refreshRobustness();
      refresh().catch(showError);
    }
  });
  window.setInterval(() => { if (visible && (activeId || robustnessCampaign)) renderLive(); }, 250);
  suite.hidden = false;
  buildTab.addEventListener("click", () => setView("build"));
  reportTab.addEventListener("click", () => setView("report"));
  suite.addEventListener("click", () => switchWorkspace(true));
  dashboard.addEventListener("click", () => switchWorkspace(false));
}
