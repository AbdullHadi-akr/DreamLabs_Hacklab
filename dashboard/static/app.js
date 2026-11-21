// Core-UI des Dashboards: Viewer, Taskleiste, Status, Log und das Laden der Extension-Panels.
import { EventHub, createExtensionApi, h, request } from "./lib/api.js";

const $ = (id) => document.getElementById(id);
const core = {
  events: new EventHub(),
  sim: null, // letzter sim.state
  status: null,
  currentTask: () => $("task").value.trim(),
  toast,
};
window.dreamCore = core; // praktisch zum Debuggen in der Browser-Konsole

// ---------------- Toasts & Log ----------------

function toast(message, level = "info", ms = 4000) {
  const el = h("div", { class: `toast ${level}` }, message);
  $("toasts").append(el);
  setTimeout(() => el.remove(), ms);
}

function log(message, level = "info", source = "core") {
  const time = new Date().toLocaleTimeString("de-DE");
  const item = h("li", { class: level }, h("time", {}, time), h("span", { class: "src" }, source), message);
  const list = $("log");
  list.append(item);
  while (list.children.length > 400) list.firstChild.remove();
  list.scrollTop = list.scrollHeight;
}

function setPill(id, state, text) {
  const el = $(id);
  el.className = `pill ${state}`;
  el.lastChild.textContent = text;
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

// ---------------- Viewer: Orbit-Steuerung ----------------

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

function setupCameras(names) {
  const labels = { top: "Overhead", left: "Handgelenk links", right: "Handgelenk rechts" };
  for (const name of names) {
    const img = h("img", { src: `/stream/${name}.mjpg`, alt: name });
    img.onerror = () => setTimeout(() => (img.src = `/stream/${name}.mjpg?r=${Date.now()}`), 1500);
    $("cams").append(h("div", { class: "cam" }, h("div", { class: "cam-inner" }, img, h("span", {}, labels[name] || name))));
  }
}

// ---------------- Taskleiste ----------------

function setupTaskbar(state) {
  $("model").value = state.default_model;
  for (const task of state.tasks) $("task-list").append(h("option", { value: task }));
  $("task").value = state.tasks[0];

  $("taskbar").addEventListener("submit", (e) => {
    e.preventDefault();
    const task = core.currentTask();
    if (!task) return toast("Bitte einen Task eingeben.", "error");
    action(request("POST", "/api/run", { task, model: $("model").value.trim(), seconds: Number($("seconds").value) }));
  });
  $("btn-stop").onclick = () => action(request("POST", "/api/stop"));
  $("btn-demo").onclick = () => action(request("POST", "/api/run", { task: core.currentTask() || "demo", offline: true }));
  $("btn-home").onclick = () => action(request("POST", "/api/home"));
  $("btn-reset").onclick = () => action(request("POST", "/api/reset"));
  $("btn-clear-log").onclick = () => ($("log").innerHTML = "");
  if (!state.has_api_key) {
    $("btn-run").title = "Kein API-Key konfiguriert – siehe README";
  }
}

function updateControls(status) {
  const busy = status.running || status.queued > 0;
  for (const id of ["btn-run", "btn-demo", "btn-home"]) $(id).disabled = busy;
  $("btn-stop").disabled = !busy;
  $("viewer-frame").classList.toggle("running", status.running);
  $("status-dot").className = `dot ${busy ? "wait" : "live"}`;
  if (status.running) {
    const r = status.run;
    const offline = r.model === "offline";
    setPill("pill-run", "busy", offline ? "Offline-Lauf" : "Dream-1 läuft");
    $("badge-run").hidden = false;
    $("badge-run").lastChild.textContent = offline ? "Offline" : "Live";
    $("status-text").textContent = offline ? "Offline-Lauf" : "Dream-1 arbeitet";
    $("status-sub").textContent = r.label || r.source;
    $("caption-label").textContent = offline ? "Offline · ohne API" : `Dream-1 · ${r.model}`;
    $("caption-task").textContent = `“${r.task}”`;
    $("ri-state").textContent = "läuft";
    $("ri-task").textContent = r.task;
    $("ri-source").textContent = r.source + (r.label ? ` · ${r.label}` : "");
    $("ri-steps").textContent = r.steps ?? 0;
    $("ri-requests").textContent = r.requests ?? 0;
    $("ri-rtt").textContent = r.last_rtt_s ? `${r.last_rtt_s.toFixed(2)} s` : "–";
  } else {
    setPill("pill-run", status.queued ? "warn" : "ok", status.queued ? `${status.queued} wartend` : "Bereit");
    $("badge-run").hidden = true;
    $("status-text").textContent = status.queued ? `${status.queued} wartend` : "Bereit";
    $("status-sub").textContent = "Dein Prompt läuft als Nächstes";
    $("caption-label").textContent = "Bereit";
    $("caption-task").textContent = "Warte auf den nächsten Prompt …";
  }
}

// ---------------- RTT-Chart ----------------

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
  ctx.fillStyle = color("--ink-3");
  if (!rtts.length) { ctx.fillText("Noch keine Requests", 4, hgt / 2); return; }
  const max = Math.max(1.5, ...rtts) * 1.15;
  const step = w / Math.max(1, rtts.length - 1);
  const y = (v) => hgt - (v / max) * (hgt - 4);
  ctx.strokeStyle = color("--grey-2");
  ctx.setLineDash([4, 4]);
  ctx.beginPath(); ctx.moveTo(0, y(1)); ctx.lineTo(w, y(1)); ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillText("1 s", 2, y(1) - 4);
  const gradient = ctx.createLinearGradient(0, 0, 0, hgt);
  gradient.addColorStop(0, "rgba(255, 184, 123, .45)");
  gradient.addColorStop(1, "rgba(255, 232, 133, 0)");
  ctx.beginPath();
  rtts.forEach((v, i) => (i ? ctx.lineTo(i * step, y(v)) : ctx.moveTo(0, y(v))));
  ctx.lineTo((rtts.length - 1) * step, hgt); ctx.lineTo(0, hgt); ctx.closePath();
  ctx.fillStyle = gradient; ctx.fill();
  ctx.strokeStyle = color("--creamsicle-deep"); ctx.lineWidth = 2; ctx.lineJoin = "round"; ctx.beginPath();
  rtts.forEach((v, i) => (i ? ctx.lineTo(i * step, y(v)) : ctx.moveTo(0, y(v))));
  ctx.stroke();
  const avg = rtts.reduce((a, b) => a + b, 0) / rtts.length;
  ctx.fillStyle = color("--ink");
  ctx.textAlign = "right";
  ctx.fillText(`Ø ${avg.toFixed(2)} s · letzte ${rtts.at(-1).toFixed(2)} s`, w - 2, 12);
}

// ---------------- Events ----------------

function setupEvents() {
  const ev = core.events;
  ev.on("ws.open", () => setPill("pill-ws", "ok", "Verbunden"));
  ev.on("ws.close", () => { setPill("pill-ws", "bad", "Getrennt"); setPill("pill-sim", "", "Simulation"); });
  ev.on("sim.state", (s) => {
    core.sim = s;
    core.status = s.status;
    $("badge-time").textContent = `t = ${s.time.toFixed(1)} s`;
    setPill("pill-sim", s.status.error ? "bad" : "ok", s.status.error ? "Sim-Fehler" : "Simulation");
    updateControls(s.status);
  });
  ev.on("log", (d) => log(d.message, d.level, d.source));
  ev.on("run.queued", (d) => log(`Eingereiht: ${d.label || d.task}`, "info", d.source));
  ev.on("run.started", (d) => {
    log(`Start: ${d.task} (${d.model})${d.label ? " · " + d.label : ""}`, "info", d.source);
    $("ri-result").textContent = "–";
    $("ri-result").className = "";
    if (!d.offline) { rtts.length = 0; drawRtt(); }
  });
  ev.on("run.cancelled", (d) => log(`Verworfen: ${d.label || d.task}`, "warn", d.source));
  ev.on("run.reply", (d) => { rtts.push(d.rtt_s); if (rtts.length > 60) rtts.shift(); drawRtt(); });
  ev.on("run.ended", (d) => {
    const r = d.result;
    const success = r.success === true ? "✔ Erfolg" : r.success === false ? "✘ kein Erfolg" : "–";
    $("ri-state").textContent = r.stop_reason;
    $("ri-steps").textContent = r.steps;
    $("ri-requests").textContent = r.requests;
    $("ri-result").textContent = `${success} · ${r.seconds.toFixed(1)} s`;
    $("ri-result").className = r.success ? "good" : r.success === false ? "bad" : "";
    const level = r.stop_reason.startsWith("error") ? "error" : "info";
    log(`Ende: ${r.stop_reason} · ${success} · ${r.steps} Schritte · ${r.requests} Requests`, level, d.source);
  });
}

// ---------------- Extensions ----------------

async function loadExtensions(extensions) {
  const tabs = $("ext-tabs"), panels = $("ext-panels");
  const left = extensions.filter((e) => e.slot !== "right");
  const right = extensions.filter((e) => e.slot === "right");
  if (left.length) panels.innerHTML = "";

  const activate = (id) => {
    for (const t of tabs.children) t.classList.toggle("active", t.dataset.id === id);
    for (const p of panels.children) p.hidden = p.dataset.id !== id;
    try { localStorage.setItem("dream.activeTab", id); } catch {}
  };

  for (const ext of left) {
    tabs.append(h("button", { class: "tab", "data-id": ext.id, title: ext.description, onclick: () => activate(ext.id) },
      h("span", {}, ext.icon), ext.title));
    const root = h("div", { class: "panel", "data-id": ext.id, hidden: true });
    panels.append(root);
    await mountPanel(ext, root);
  }
  for (const ext of right) {
    const root = h("div");
    $("right-slot").append(h("section", { class: "card" }, h("h3", {}, `${ext.icon} ${ext.title}`), root));
    await mountPanel(ext, root);
  }
  let saved = null;
  try { saved = localStorage.getItem("dream.activeTab"); } catch {}
  if (left.length) activate(left.some((e) => e.id === saved) ? saved : left[0].id);
}

async function mountPanel(ext, root) {
  if (!ext.has_panel) {
    root.append(h("p", { class: "muted" }, ext.description || "Diese Extension hat kein Panel."));
    return;
  }
  try {
    if (ext.has_css) document.head.append(h("link", { rel: "stylesheet", href: `/ext/${ext.id}/panel.css` }));
    const module = await import(`/ext/${ext.id}/panel.js`);
    await module.mount(root, createExtensionApi(ext, core));
  } catch (error) {
    console.error(error);
    root.append(h("div", { class: "panel-error" }, `Panel "${ext.id}" konnte nicht geladen werden:\n${error.message}`));
    log(`Panel ${ext.id}: ${error.message}`, "error", ext.id);
  }
}

// ---------------- Start ----------------

async function main() {
  setupEvents();
  core.events.connect();
  const state = await request("GET", "/api/state");
  core.sim = state.sim;
  setPill("pill-key", state.has_api_key ? "ok" : "warn", state.has_api_key ? "API-Key" : "Kein API-Key");
  setupViewer(state.camera);
  setupCameras(state.cameras);
  setupTaskbar(state);
  updateControls(state.status);
  drawRtt();
  window.addEventListener("resize", drawRtt);
  await loadExtensions(state.extensions);
}

main().catch((error) => {
  console.error(error);
  toast(`Dashboard-Start fehlgeschlagen: ${error.message}`, "error", 10000);
});
