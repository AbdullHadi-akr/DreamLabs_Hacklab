// Shared helpers for the core UI and extensions. No build step: plain ES modules.

/** DOM helper: h("div", {class: "x", onclick: fn}, "Text", h("span", {}, "...")) */
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2), value);
    else if (key === "class") el.className = value;
    else if (key === "style" && typeof value === "object") Object.assign(el.style, value);
    else if (key === "html") el.innerHTML = value;
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === undefined || child === null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

export async function request(method, url, body) {
  const response = await fetch(url, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await response.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!response.ok) {
    const detail = data && data.detail ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : text;
    const error = new Error(detail || `${response.status} ${response.statusText}`);
    error.status = response.status;
    throw error;
  }
  return data;
}

/** Event hub over the WebSocket /ws. on("run.ended", fn), on("*", fn) for everything. */
export class EventHub {
  constructor() {
    this.listeners = new Map();
    this.connected = false;
    this.ws = null;
  }

  on(type, fn) {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type).add(fn);
    return () => this.listeners.get(type)?.delete(fn);
  }

  dispatch(message) {
    for (const key of [message.type, "*"]) {
      for (const fn of this.listeners.get(key) || []) {
        try { fn(message.data, message); } catch (error) { console.error(`Listener for ${key}:`, error); }
      }
    }
  }

  connect() {
    const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
    this.ws = ws;
    ws.onopen = () => { this.connected = true; this.dispatch({ type: "ws.open" }); };
    ws.onmessage = (event) => this.dispatch(JSON.parse(event.data));
    ws.onclose = () => {
      if (this.connected) this.dispatch({ type: "ws.close" });
      this.connected = false;
      setTimeout(() => this.connect(), 1500);
    };
  }

  send(message) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(message));
  }
}

/** The API every extension receives in mount(root, api). */
export function createExtensionApi(ext, core) {
  const base = `/api/ext/${ext.id}`;
  return {
    id: ext.id,
    ext,
    // the extension's backend (router() in __init__.py), paths relative to /api/ext/<id>
    get: (path = "") => request("GET", base + path),
    post: (path = "", body = {}) => request("POST", base + path, body),
    del: (path = "") => request("DELETE", base + path),
    // events: your own (ctx.emit("progress") -> api.on("progress")) and core events (api.onCore("run.ended"))
    on: (event, fn) => core.events.on(`ext.${ext.id}.${event}`, fn),
    onCore: (type, fn) => core.events.on(type, fn),
    // simulation control
    core: {
      run: (task, options = {}) => request("POST", "/api/run", { task, ...options }),
      stop: () => request("POST", "/api/stop"),
      reset: () => request("POST", "/api/reset"),
      home: () => request("POST", "/api/home"),
      sim: () => core.sim, // latest sim state: time, arms, objects, status
      task: () => core.currentTask(), // text in the prompt field
    },
    ui: { h, toast: core.toast },
    // Test Suite workspace: extensions with slot "suite", each {id, title, suite_modes, root} (root = mounted panel)
    workspace: { extensions: () => core.suiteExtensions || [] },
    asset: (file) => `/ext/${ext.id}/${file}`,
  };
}
