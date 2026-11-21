// Core UI of the dashboard: viewer, prompt bar, status, log, and loading the extension panels.
import { logPanel } from "./lib/log_panel.js";
import { EventHub, createExtensionApi, h, request } from "./lib/api.js";
import { episodesPanel, setupEpisodes } from "./episodes.js";
import { creditsPanel, gateRun, setupCredits } from "./credits.js";
import { playersPanel } from "./players.js";

const $ = (id) => document.getElementById(id);
const core = {
  events: new EventHub(),
  sim: null, // latest sim.state
  status: null,
  currentTask: () => $("task").value.trim(),
  toast,
};
window.dreamCore = core; // handy for debugging in the browser console

// ---------------- Toasts & Log ----------------

function toast(message, level = "info", ms = 4000) {
  const el = h("div", { class: `toast ${level}` }, message);
  $("toasts").append(el);
  setTimeout(() => el.remove(), ms);
}

const debugLog = logPanel("Application log", {}, {clear: true});
$("global-log").append(debugLog.panel);

function log(message, level = "info", source = "core") {
  debugLog.append({message, level, source, at: Date.now() / 1000});
}

const pills = {};
function setPill(id, state, text) {
  const el = $(id);
  el.className = state;
  el.lastChild.textContent = text;
  pills[id] = { state, text };
  // One dot: red if anything is broken, yellow while busy or waiting, green when everything works.
  const states = Object.values(pills).map((p) => p.state);
  const bad = Object.values(pills).find((p) => p.state === "bad");
  const waiting = Object.values(pills).find((p) => p.state === "warn" || p.state === "busy");
  const dot = bad ? "bad" : waiting ? "wait" : states.length && states.every((s) => s === "ok") ? "ok" : "";
  $("status-dot").className = `dot ${dot}`;
  $("status-text").textContent = bad ? bad.text : waiting ? waiting.text : dot === "ok" ? "Everything works" : "Starting";
}

function setupStatus() {
  const button = $("status-button"), details = $("status-details");
  const show = (open) => { details.hidden = !open; button.setAttribute("aria-expanded", String(open)); };
  button.onclick = (e) => { e.stopPropagation(); show(details.hidden); };
  document.addEventListener("click", (e) => { if (!details.contains(e.target)) show(false); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") show(false); });
}

async function action(promise, okMessage) {
  try {
    const result = await promise;
    if (okMessage) toast(okMessage, "good", 2000);
    return result;
  } catch (error) {
    toast(error.message, "error", 6000);
    log(error.message, "error");
  }
}

// ---------------- Viewer: orbit controls ----------------

function setupViewer(camera) {
  const viewer = $("viewer");
  const img = $("main-view");
  img.src = "/stream/main.mjpg";
  img.onerror = () => setTimeout(() => (img.src = `/stream/main.mjpg?r=${Date.now()}`), 1500);

  let cam = { ...camera };
  let drag = null;
  let pending = false;
  const send = () => {
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => {
      pending = false;
      core.events.send({ type: "camera", ...cam });
    });
  };

  viewer.addEventListener("contextmenu", (e) => e.preventDefault());
  viewer.addEventListener("pointerdown", (e) => {
    drag = { x: e.clientX, y: e.clientY, pan: e.button === 2 || e.shiftKey };
    viewer.setPointerCapture(e.pointerId);
    viewer.classList.add("dragging");
  });
  viewer.addEventListener("pointerup", () => { drag = null; viewer.classList.remove("dragging"); });
  viewer.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    drag.x = e.clientX; drag.y = e.clientY;
    if (drag.pan) {
      const az = (cam.azimuth * Math.PI) / 180, k = cam.distance * 0.0015;
      cam.lookat = [
        cam.lookat[0] - Math.sin(az) * dx * k,
        cam.lookat[1] + Math.cos(az) * dx * k,
        cam.lookat[2] + dy * k,
      ];
    } else {
      cam.azimuth -= dx * 0.3;
      cam.elevation = Math.max(-89, Math.min(89, cam.elevation - dy * 0.3));
    }
    send();
  });
  viewer.addEventListener("wheel", (e) => {
    e.preventDefault();
    cam.distance = Math.max(0.2, Math.min(6, cam.distance * (e.deltaY > 0 ? 1.1 : 0.9)));
    send();
  }, { passive: false });
  viewer.addEventListener("dblclick", async () => {
    cam = await request("POST", "/api/camera", { reset: true });
  });
}

const VIEW_LABELS = { main: "Free view", top: "Overhead", left: "Left wrist", right: "Right wrist" };

function streamImage(img, path) {
  img.onerror = () => setTimeout(() => { if (img.dataset.src === path) img.src = `${path}?r=${Date.now()}`; }, 1500);
  img.dataset.src = path;
  img.src = path;
}

// Which view is large: "main" (the free 3D view) or a robot camera. Each browser chooses for itself.
function setupCameras(names) {
  const viewer = $("viewer"), focus = $("focus-view"), thumbs = $("cams");
  const all = ["main", ...names];
  let large = "main";
  try { const saved = localStorage.getItem("dream.largeView"); if (all.includes(saved)) large = saved; } catch {}

  // The large robot picture lies on top of the free view, so the free view's own controls stay as they are.
  for (const type of ["pointerdown", "pointermove", "wheel", "dblclick", "contextmenu"]) {
    focus.addEventListener(type, (e) => e.stopPropagation());
  }

  const show = (name) => {
    large = name;
    try { localStorage.setItem("dream.largeView", name); } catch {}
    const robot = name !== "main";
    viewer.classList.toggle("robot-view", robot);
    focus.hidden = !robot;
    if (robot) streamImage(focus, `/stream/${name}-large.mjpg`);
    else { focus.removeAttribute("src"); focus.dataset.src = ""; }
    thumbs.replaceChildren(...all.filter((n) => n !== name).map((n) => {
      const img = h("img", { alt: "", draggable: "false" });
      streamImage(img, n === "main" ? "/stream/main.mjpg" : `/stream/${n}.mjpg`);
      return h("button", { type: "button", class: "thumb", title: `Show ${VIEW_LABELS[n] || n} large`,
        onclick: (e) => { e.stopPropagation(); show(n); },
        onpointerdown: (e) => e.stopPropagation() }, img, h("span", {}, VIEW_LABELS[n] || n));
    }));
  };
  show(large);
}

// ---------------- Prompt bar ----------------

function setupTaskbar(state) {
  for (const task of state.tasks) $("task-list").append(h("option", { value: task }));
  $("task").value = state.tasks[0];

  $("taskbar").addEventListener("submit", async (e) => {
    e.preventDefault();
    const task = core.currentTask();
    if (!task) return toast("Please enter a task.", "error");
    const body = { task, model: $("model").value.trim(), seconds: Number($("seconds").value) };
    try { if (!(await gateRun(core, body))) return; } catch (error) { return toast(error.message, "error"); }
    action(request("POST", "/api/run", body));
  });
  $("btn-stop").onclick = () => action(request("POST", "/api/stop"));
  $("btn-demo").onclick = () => action(request("POST", "/api/run", { task: core.currentTask() || "demo", offline: true }));
  $("btn-home").onclick = () => action(request("POST", "/api/home"));
  $("btn-reset").onclick = () => action(request("POST", "/api/reset"));
  if (!state.has_api_key) {
    $("btn-run").title = "No API key is set up. See the README.";
  }
}

function updateControls(status) {
  const busy = status.running || status.queued > 0;
  for (const id of ["btn-run", "btn-demo", "btn-home"]) $(id).disabled = busy;
  $("btn-stop").disabled = !busy;
  $("viewer-frame").classList.toggle("running", status.running);
  if (status.running) {
    const r = status.run;
    const offline = r.model === "offline";
    setPill("pill-run", "busy", offline ? "Test motion running" : "Dream-1 is working");
    $("badge-run").hidden = false;
    $("badge-run").textContent = offline ? "Test motion" : `Live, ${r.model}`;
    $("status-sub").textContent = r.label || r.source;
    $("caption-task").textContent = r.task;
    $("ri-state").textContent = "running";
    $("ri-task").textContent = r.task;
    $("ri-source").textContent = r.source + (r.label ? ` · ${r.label}` : "");
    $("ri-steps").textContent = r.steps ?? 0;
    $("ri-requests").textContent = r.requests ?? 0;
    $("ri-rtt").textContent = r.last_rtt_s ? `${r.last_rtt_s.toFixed(2)} s` : "-";
    $("ri-cost").textContent = offline ? "none" : r.cost_usd != null ? `$${r.cost_usd.toFixed(4)}` : "unknown price";
  } else {
    setPill("pill-run", status.queued ? "warn" : "ok", status.queued ? `${status.queued} waiting` : "Ready");
    $("badge-run").hidden = true;
    $("status-sub").textContent = status.queued ? `${status.queued} waiting` : "";
    $("caption-task").textContent = "Waiting for the next task";
  }
}

// ---------------- RTT chart ----------------

const rtts = [];
function drawRtt() {
  const canvas = $("rtt-chart");
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, hgt = canvas.clientHeight;
  canvas.width = w * dpr; canvas.height = hgt * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, hgt);
  const css = getComputedStyle(document.documentElement);
  const color = (name) => css.getPropertyValue(name).trim();
  ctx.font = `12px ${color("--font-sans")}`;
  ctx.fillStyle = color("--text-3");
  if (!rtts.length) { ctx.fillText("No calls yet", 4, hgt / 2); return; }
  const max = Math.max(1.5, ...rtts) * 1.15;
  const step = w / Math.max(1, rtts.length - 1);
  const y = (v) => hgt - (v / max) * (hgt - 4);
  ctx.strokeStyle = color("--surface-3");
  ctx.setLineDash([4, 4]);
  ctx.beginPath(); ctx.moveTo(0, y(1)); ctx.lineTo(w, y(1)); ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillText("1 s", 2, y(1) - 4);
  ctx.strokeStyle = color("--text-2"); ctx.lineWidth = 1.5; ctx.lineJoin = "round"; ctx.beginPath();
  rtts.forEach((v, i) => (i ? ctx.lineTo(i * step, y(v)) : ctx.moveTo(0, y(v))));
  ctx.stroke();
  const avg = rtts.reduce((a, b) => a + b, 0) / rtts.length;
  ctx.fillStyle = color("--text-2");
  ctx.textAlign = "right";
  ctx.fillText(`average ${avg.toFixed(2)} s, last ${rtts.at(-1).toFixed(2)} s`, w - 2, 12);
}

// ---------------- Events ----------------

function setupEvents() {
  const ev = core.events;
  ev.on("ws.open", () => setPill("pill-ws", "ok", "Connected"));
  ev.on("ws.close", () => { setPill("pill-ws", "bad", "Disconnected"); setPill("pill-sim", "", "Simulation"); });
  ev.on("sim.state", (s) => {
    core.sim = s;
    core.status = s.status;
    $("badge-time").textContent = `${s.time.toFixed(1)} s`;
    setPill("pill-sim", s.status.error ? "bad" : "ok", s.status.error ? "Simulation error" : "Simulation");
    updateControls(s.status);
  });
  ev.on("log", (d) => log(d.message, d.level, d.source));
  ev.on("run.queued", (d) => log(`Queued: ${d.label || d.task}`, "info", d.source));
  ev.on("run.started", (d) => {
    log(`Started: ${d.task} (${d.model})${d.label ? ", " + d.label : ""}`, "info", d.source);
    $("ri-result").textContent = "-";
    $("ri-result").className = "";
    if (!d.offline) { rtts.length = 0; drawRtt(); }
  });
  ev.on("run.cancelled", (d) => log(`Cancelled: ${d.label || d.task}`, "warn", d.source));
  ev.on("run.reply", (d) => { rtts.push(d.rtt_s); if (rtts.length > 60) rtts.shift(); drawRtt(); });
  ev.on("run.ended", (d) => {
    const r = d.result;
    const success = r.success === true ? "success" : r.success === false ? "no success" : "-";
    $("ri-state").textContent = r.stop_reason;
    $("ri-steps").textContent = r.steps;
    $("ri-requests").textContent = r.requests;
    $("ri-cost").textContent = r.cost_usd != null ? `$${r.cost_usd.toFixed(4)}` : "-";
    $("ri-result").textContent = `${success}, ${r.seconds.toFixed(1)} s`;
    $("ri-result").className = r.success ? "good" : r.success === false ? "bad" : "";
    const level = r.stop_reason.startsWith("error") ? "error" : "info";
    log(`Ended: ${r.stop_reason}, ${success}, ${r.steps} steps, ${r.requests} calls`, level, d.source);
  });
}

// ---------------- Extensions ----------------

// Menu names in plain words; the order here is the order in the menu. At most 6 entries.
// "Test Suite" opens the teammates' Test Suite workspace (dashboard/extensions/test_suite); Robustness lives inside it.
// Without the Test Suite, Robustness falls back to its own entry.
const MENU = [["teleop", "Control"], ["scene_inspector", "Scene"], ["test_suite", "Test Suite"], ["robustness", "Robustness"],
  ["episodes", "Episodes"], ["credits", "Credits"], ["players", "Players"]];
const GUEST_MENU = ["teleop", "scene_inspector", "players"]; // what a guest on another laptop sees
const MENU_LIMIT = 6;

function settingsPanel(state) {
  const model = h("input", { id: "model", value: state.default_model, autocomplete: "off" });
  const seconds = h("input", { id: "seconds", type: "number", min: "5", max: "3600", step: "5", value: "60" });
  return [
    h("label", { class: "field" }, h("span", {}, "Model"), model),
    h("label", { class: "field" }, h("span", {}, "Time limit per run, in simulated seconds"), seconds),
  ];
}

function setupFold() {
  const layout = $("layout"), button = $("btn-fold");
  const set = (folded) => {
    layout.classList.toggle("folded", folded);
    button.textContent = folded ? "Show" : "Hide";
    try { localStorage.setItem("dream.folded", folded ? "1" : "0"); } catch {}
  };
  button.onclick = () => set(!layout.classList.contains("folded"));
  let saved = null;
  try { saved = localStorage.getItem("dream.folded"); } catch {}
  set(saved === "1");
  return set;
}

async function loadExtensions(extensions, state) {
  const tabs = $("ext-tabs"), panels = $("ext-panels");
  // slot "suite" lives in the Test Suite builder; without a Test Suite it falls back to a normal tab
  const hasSuite = extensions.some((e) => e.slot === "workspace");
  const left = extensions.filter((e) => e.slot !== "right" && e.slot !== "workspace" && !(hasSuite && e.slot === "suite"));
  const right = extensions.filter((e) => e.slot === "right");
  const order = (id) => { const i = MENU.findIndex(([m]) => m === id); return i < 0 ? MENU.length : i; };
  const entries = [...left, { id: "episodes", title: "Episodes", core: true,
    description: "Recorded episodes, what is ready for a fine-tune, success and cost per model" },
    { id: "credits", title: "Credits", core: true, description: "Balance, spending, limits, model and time limit" },
    { id: "players", title: "Players", core: true, description: "Public link, access code, who holds which arm" },
    ...(hasSuite ? [{ id: "test_suite", title: "Test Suite", core: true, workspace: true,
      description: "Build and run tests: quick test, repeated runs, sweeps, safety, A/B, robustness" }] : []),
  ].sort((a, b) => order(a.id) - order(b.id));
  if (core.me && core.me.role === "guest") entries.splice(0, entries.length, ...entries.filter((e) => GUEST_MENU.includes(e.id)));
  if (entries.length > MENU_LIMIT) console.warn(`The menu holds at most ${MENU_LIMIT} entries; extra tools are left out.`);
  panels.innerHTML = "";
  const setFolded = setupFold();
  const startFolded = $("layout").classList.contains("folded");

  const markTab = (id) => { for (const t of tabs.children) t.classList.toggle("active", t.dataset.id === id); };
  const activate = (id) => {
    const inSuite = $("workspace-test-suite")?.getAttribute("aria-pressed") === "true";
    if (id === "test_suite") {
      $("workspace-test-suite")?.click(); // the Test Suite shows its own form, results and monitor
    } else {
      if (inSuite) $("workspace-dashboard").click();
      for (const p of panels.children) p.hidden = p.dataset.id !== id;
      try { localStorage.setItem("dream.activeTab", id); } catch {}
    }
    markTab(id);
    setFolded(false);
  };
  core.activate = activate;
  core.markTab = markTab;
  const label = (ext) => (MENU.find(([m]) => m === ext.id) || [])[1] || ext.title;

  for (const ext of entries.slice(0, MENU_LIMIT)) {
    tabs.append(h("button", { type: "button", class: "tab", "data-id": ext.id, title: ext.description || "",
      onclick: () => activate(ext.id) }, label(ext)));
    if (ext.workspace) continue; // no panel here: the Test Suite fills its own places on the page
    const root = h("div", { class: "panel", "data-id": ext.id, hidden: true });
    panels.append(root);
    if (ext.id === "credits") creditsPanel(root, core, action, settingsPanel(state));
    else if (ext.id === "players") playersPanel(root, core, action);
    else if (ext.id === "episodes") episodesPanel(root, core, action);
    else await mountPanel(ext, root);
  }
  for (const ext of right) {
    const root = h("div");
    $("right-slot").append(h("section", {}, h("h3", {}, ext.title), root));
    await mountPanel(ext, root);
  }
  let saved = null;
  try { saved = localStorage.getItem("dream.activeTab"); } catch {}
  const ids = [...tabs.children].map((t) => t.dataset.id);
  activate(ids.includes(saved) ? saved : ids[0]);
  setFolded(startFolded);
}

async function mountPanel(ext, root) {
  if (!ext.has_panel) {
    root.append(h("p", { class: "muted" }, ext.description || "This extension has no panel."));
    return;
  }
  try {
    if (ext.has_css) document.head.append(h("link", { rel: "stylesheet", href: `/ext/${ext.id}/panel.css` }));
    const module = await import(`/ext/${ext.id}/panel.js`);
    await module.mount(root, createExtensionApi(ext, core));
  } catch (error) {
    console.error(error);
    root.append(h("div", { class: "panel-error" }, `Panel "${ext.id}" failed to load:\n${error.message}`));
    log(`Panel ${ext.id}: ${error.message}`, "error", ext.id);
  }
}

// ---------------- Start ----------------

async function main() {
  setupStatus();
  setupEvents();
  core.events.connect();
  const state = await request("GET", "/api/state");
  core.sim = state.sim;
  core.me = state.me;
  if (state.me.role === "guest") document.body.classList.add("guest");
  setPill("pill-key", state.has_api_key ? "ok" : "warn", state.has_api_key ? "API key" : "No API key");
  setupViewer(state.camera);
  setupCameras(state.cameras);
  setupTaskbar(state);
  setupEpisodes(core, action, state.episode);
  if (state.me.role !== "guest") setupCredits(core);
  updateControls(state.status);
  drawRtt();
  window.addEventListener("resize", drawRtt);
  await loadExtensions(state.extensions, state);
  const suite = state.extensions.find((ext) => ext.id === "test_suite");
  if (suite && state.me.role !== "guest") {
    // Extensions that add test modes to the builder are mounted first; the Test Suite shows them as tiles.
    core.suiteExtensions = [];
    for (const ext of state.extensions.filter((e) => e.slot === "suite")) {
      const root = h("div", { class: "suite-extension", "data-id": ext.id, hidden: true });
      await mountPanel(ext, root);
      core.suiteExtensions.push({ ...ext, root });
    }
    await mountPanel(suite, $("test-suite-config"));
    // Menu entry "Test Suite" and the (hidden) workspace buttons stay in step.
    $("workspace-test-suite").addEventListener("click", () => core.markTab && core.markTab("test_suite"));
  }
}

main().catch((error) => {
  console.error(error);
  toast(`Dashboard failed to start: ${error.message}`, "error", 10000);
});
