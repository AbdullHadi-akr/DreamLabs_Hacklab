// Objects panel: live positions of the scene's objects, Reset layout, controls legend.
// In the 3D view (only while this tab is open): grab dots + labels, drag an object to slide it over the table,
// Shift + drag to lift / lower it, mouse wheel to turn it, let go to drop it. Bowl and plate take their contents along.

import { onImage, overlayViewer, toImage, toPixels } from "/static/lib/viewer-overlay.js";
const HANDLE_PX = 14; // grab radius around the dot above an object
const MIN_REACH_PX = 12; // smallest grab radius on the object itself (far away = tiny on screen)
const WHEEL_DEG = 15; // turn per mouse wheel notch over an object
const BUTTON_DEG = 15; // turn per button click in the panel
const MAX_TURN = 90; // deg per request (server limit)
const SLOW_FACTOR = 1 / 3; // wheel with Shift held
const KEEPALIVE_MS = 1000; // a held object is dropped after 4 s without word from the browser (backend STALE_S)

const label = (name) => (name.charAt(0).toUpperCase() + name.slice(1)).replace(/_/g, " ");

export async function mount(root, api) {
  const { h, toast } = api.ui;
  const viewer = document.getElementById("viewer");
  const view = overlayViewer(viewer);
  const isActive = () => root.isConnected && !root.closest("[hidden]");
  const initial = await api.get("/state");
  const names = initial.names;
  const state = { info: initial, selected: names[0], hover: null };

  let lastError = 0;
  const report = (error) => {
    if (Date.now() - lastError < 2500) return;
    lastError = Date.now();
    toast(error.message, "error");
  };
  const busy = () => Boolean(state.info?.busy);
  const warnBusy = () => report(new Error("A run is active: objects can be moved between runs."));
  const isContainer = (name) => state.info?.items?.[name]?.kind === "container";

  // ---------- panel ----------

  const rows = {};
  const tbody = h("tbody");
  for (const name of names) {
    const cells = { x: h("td", { class: "num" }), y: h("td", { class: "num" }), z: h("td", { class: "num" }),
      yaw: h("td", { class: "num" }) };
    const dot = h("i", { class: `objects-dot ${initial.items?.[name]?.kind || "object"}` });
    const row = h("tr", { class: "objects-row", onclick: () => select(name) },
      h("td", {}, dot, label(name)), cells.x, cells.y, cells.z, cells.yaw);
    rows[name] = { row, cells, dot };
    tbody.append(row);
  }

  const status = h("p", { class: "muted objects-status" });
  const turnButton = (text, degrees) => h("button", { class: "btn small", type: "button",
    onclick: (e) => { e.currentTarget.blur(); turnSelected(degrees); } }, text);
  const turnLeft = turnButton(`↺ ${BUTTON_DEG}°`, BUTTON_DEG);
  const turnRight = turnButton(`↻ ${BUTTON_DEG}°`, -BUTTON_DEG);
  const resetButton = h("button", { class: "btn small", type: "button", onclick: resetLayout }, "Reset layout");

  const keys = [
    ["Drag an object", "slide it over the table (its height stays, it stays above what lies below)"],
    ["Shift + drag", "lift / lower it"],
    ["Alt + scroll on object", "turn it (Shift: finer)"],
    ["Let go", "it drops and physics takes over"],
    ["Bowl / plate", "drag and lift them the same way: what lies in or on them comes along, and when you let go they are put straight down (they are fixed in the model, physics does not move them)"],
  ];

  root.append(
    h("p", { class: "muted" }, "Grab the objects in the 3D view while this tab is open. A held object floats ",
      "and passes through everything, then drops when you let go. Works between runs, not while Dream-1 drives."),
    h("table", { class: "table objects-table" },
      h("thead", {}, h("tr", {}, h("th", {}, "Object"), h("th", {}, "x (m)"), h("th", {}, "y (m)"), h("th", {}, "z (m)"),
        h("th", {}, "Turn"))),
      tbody),
    status,
    h("div", { class: "row objects-actions" }, turnLeft, turnRight, resetButton),
    h("p", { class: "muted" }, "Reset layout puts the objects, bowl and plate back where they start; the arms stay. ",
      "The Reset button above also resets the arms."),
    h("h4", {}, "Controls"),
    h("table", { class: "table objects-keys" }, h("tbody", {}, keys.map(([k, d]) => h("tr", {}, h("td", {}, k), h("td", {}, d))))),
  );

  function select(name) {
    state.selected = name;
    for (const [n, r] of Object.entries(rows)) r.row.classList.toggle("selected", n === name);
    syncTurnButtons();
  }
  function syncTurnButtons() {
    const round = isContainer(state.selected);
    turnLeft.disabled = turnRight.disabled = round;
    turnLeft.title = turnRight.title = round ? "Bowl and plate are round: turning changes nothing." : "";
  }
  select(state.selected);

  async function resetLayout() {
    if (busy()) return warnBusy();
    endDrag();
    try {
      await api.post("/reset");
      toast("Objects back in their start layout.", "good");
    } catch (error) { report(error); }
  }

  // ---------- 3D view: dots + labels ----------

  const layer = h("div", { class: "objects-layer" });
  const dots = {};
  for (const name of names) layer.append((dots[name] = h("div", { class: "objects-handle" })));
  const tag = h("div", { class: "objects-label" });
  layer.append(tag);
  viewer.append(layer);
  const hint = document.querySelector(".viewer-hint");
  const objectsHint = h("span", {}, " · Object: drag / Shift lift / Alt + scroll to turn");
  if (hint) hint.append(objectsHint);

  const fmt = (value) => value.toFixed(3);
  function render() {
    const info = state.info;
    if (!info?.items || view.frame("objects") === null) return;
    const box = view.box();
    for (const name of names) {
      const item = info.items[name];
      if (!item) continue;
      const { cells, dot: rowDot } = rows[name];
      rowDot.className = `objects-dot ${item.kind}`;
      ["x", "y", "z"].forEach((axis, i) => (cells[axis].textContent = fmt(item.pos[i])));
      cells.yaw.textContent = item.yaw === null ? "–" : `${Math.round(item.yaw)}°`;
      rows[name].row.classList.toggle("held", info.held === name);

      const dot = dots[name];
      const point = item.handle && toPixels(box, item.handle);
      const visible = Boolean(point && onImage(item.handle));
      dot.style.display = visible ? "" : "none";
      if (visible) {
        dot.style.left = `${point[0]}px`;
        dot.style.top = `${point[1]}px`;
      }
      dot.className = `objects-handle ${item.kind}`
        + (name === state.hover ? " hover" : "") + (name === info.held ? " held" : "")
        + (name === state.selected ? " selected" : "");
    }

    // One label: the held object, else the one under the mouse.
    const shown = info.held || state.hover;
    const item = shown && info.items[shown];
    const point = item?.handle && toPixels(box, item.handle);
    tag.style.display = point && onImage(item.handle) ? "" : "none";
    if (tag.style.display === "") {
      tag.style.left = `${point[0]}px`;
      tag.style.top = `${point[1]}px`;
      tag.textContent = `${label(shown)}  x ${fmt(item.pos[0])}  y ${fmt(item.pos[1])}  z ${fmt(item.pos[2])}`
        + (item.yaw === null ? "" : `  ↻ ${Math.round(item.yaw)}°`);
      tag.classList.toggle("flip", point[0] > box.rect.width - 260);
      tag.classList.toggle("held", info.held === shown);
    }

    syncTurnButtons();
    const held = info.held ? `Holding the ${label(info.held).toLowerCase()}.` : "";
    status.textContent = info.busy ? "Run active: objects are locked until it ends." : held;
  }

  view.onFrame("objects", (info) => {
    if (!isActive()) return;
    state.info = info;
    layer.hidden = false;
    render();
  });

  // What is under the mouse: a dot first, then an object's body before a container's, the closest one first.
  function itemAt(e) {
    const items = state.info?.items;
    if (!isActive() || view.frame("objects") === null || !items || busy()) return null;
    const box = view.box();
    if (!onImage(toImage(box, e.clientX, e.clientY))) return null;
    const mx = e.clientX - box.rect.left, my = e.clientY - box.rect.top;
    let best = null;
    for (const name of names) {
      const item = items[name];
      if (!item?.screen) continue;
      // Lower wins: a dot (0..1) before an object's body (1..2) before a container's body (2..3), so an apple
      // lying on the plate is grabbed on its body, and the plate under it on the plate's own dot.
      const scores = [];
      if (item.handle && onImage(item.handle)) {
        const [x, y] = toPixels(box, item.handle);
        const d = Math.hypot(x - mx, y - my);
        if (d <= HANDLE_PX) scores.push(d / HANDLE_PX);
      }
      const [x, y] = toPixels(box, item.screen);
      const reach = Math.max(MIN_REACH_PX, (item.reach || 0) * box.w);
      const d = Math.hypot(x - mx, y - my);
      if (d <= reach) scores.push(1 + d / reach + (item.kind === "container" ? 1 : 0));
      if (!scores.length) continue;
      const score = Math.min(...scores);
      if (!best || score < best.score) best = { name, score };
    }
    return best?.name ?? null;
  }

  // ---------- sending: in order, newest position only ----------

  // A grab is sent as its own request (it fixes where the object was grabbed), later positions replace each other,
  // turns add up, and a release always goes last so it cannot overtake the final position.
  const outbox = { start: null, drag: null, turn: {}, release: false };
  let sending = false;
  async function flush() {
    if (sending) return;
    let path, body;
    if (outbox.start) [path, body, outbox.start] = ["/drag", outbox.start, null];
    else if (outbox.drag) [path, body, outbox.drag] = ["/drag", outbox.drag, null];
    else if (Object.keys(outbox.turn).length) {
      const [name, degrees] = Object.entries(outbox.turn)[0];
      const step = Math.max(-MAX_TURN, Math.min(MAX_TURN, degrees));
      if (Math.abs(degrees - step) < 1e-9) delete outbox.turn[name];
      else outbox.turn[name] = degrees - step;
      [path, body] = ["/turn", { name, degrees: step }];
    } else if (outbox.release) [path, body, outbox.release] = ["/release", {}, false];
    else return;
    sending = true;
    try { await api.post(path, body); } catch (error) { report(error); } finally { sending = false; flush(); }
  }

  // ---------- 3D view: drag ----------

  let drag = null; // { name, pointerId, last: {u, v, mode}, sentAt, keepalive }
  function sendPosition(e, start = false) {
    const frame = view.frame("objects");
    if (frame === null) return;
    const [u, v] = toImage(view.box(), e.clientX, e.clientY);
    const mode = e.shiftKey ? "vertical" : "horizontal";
    drag.last = { u, v, mode };
    const body = { name: drag.name, u, v, mode, start, frame };
    if (start) {
      outbox.start = body;
      outbox.drag = null;
      outbox.release = false; // the server ends the previous grab itself
    } else {
      outbox.drag = body;
    }
    drag.sentAt = Date.now();
    flush();
  }

  // Capture phase: a press on an object starts an object drag instead of orbiting the camera.
  viewer.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || e.defaultPrevented || drag) return; // defaultPrevented: Teleop took it (a gripper ball)
    const name = itemAt(e);
    if (!name) return;
    e.stopPropagation();
    e.preventDefault();
    viewer.setPointerCapture(e.pointerId);
    select(name);
    drag = { name, pointerId: e.pointerId, last: null, sentAt: 0 };
    drag.keepalive = setInterval(() => {
      if (drag?.last && Date.now() - drag.sentAt >= KEEPALIVE_MS) {
        outbox.drag = outbox.drag || { name: drag.name, ...drag.last, frame: view.frame("objects") };
        drag.sentAt = Date.now();
        flush();
      }
    }, KEEPALIVE_MS / 2);
    viewer.classList.add("objects-dragging");
    sendPosition(e, true);
    render();
  }, { capture: true });

  let cursorSet = false;
  viewer.addEventListener("pointermove", (e) => {
    if (drag) {
      if (e.pointerId !== drag.pointerId) return;
      e.stopPropagation();
      sendPosition(e);
      return;
    }
    if (!isActive() || e.buttons) return;
    const name = itemAt(e);
    if (name !== state.hover) {
      state.hover = name;
      render();
    }
    if (name) {
      viewer.style.cursor = "move";
      cursorSet = true;
    } else if (cursorSet) {
      viewer.style.cursor = "";
      cursorSet = false;
    }
  }, { capture: true });

  viewer.addEventListener("pointerleave", () => {
    if (drag || !state.hover) return;
    state.hover = null;
    render();
  });

  function endDrag(e) {
    if (!drag || (e && e.pointerId !== drag.pointerId)) return;
    if (e) e.stopPropagation();
    clearInterval(drag.keepalive);
    if (viewer.hasPointerCapture(drag.pointerId)) viewer.releasePointerCapture(drag.pointerId);
    drag = null;
    viewer.classList.remove("objects-dragging");
    outbox.release = true;
    flush();
  }
  viewer.addEventListener("pointerup", endDrag, { capture: true });
  viewer.addEventListener("pointercancel", endDrag, { capture: true });
  window.addEventListener("blur", () => endDrag());

  viewer.addEventListener("dblclick", (e) => {
    if (itemAt(e)) e.stopPropagation();
  }, { capture: true });

  // Shift pressed / released mid-drag: switch between sliding and lifting without waiting for the next move.
  const shiftChanged = (e) => {
    if (!drag?.last || e.key !== "Shift") return;
    const mode = e.type === "keydown" ? "vertical" : "horizontal";
    if (mode === drag.last.mode) return;
    drag.last.mode = mode;
    outbox.drag = { name: drag.name, ...drag.last, frame: view.frame("objects") };
    drag.sentAt = Date.now();
    flush();
  };
  window.addEventListener("keydown", shiftChanged);
  window.addEventListener("keyup", shiftChanged);

  // ---------- turning ----------

  function queueTurn(name, degrees) {
    if (busy()) return warnBusy();
    if (isContainer(name)) return;
    outbox.turn[name] = (outbox.turn[name] || 0) + degrees;
    flush();
  }
  function turnSelected(degrees) {
    queueTurn(state.selected, degrees);
  }

  // Mouse wheel on an object turns it instead of zooming (bowl and plate are round: the wheel zooms there).
  viewer.addEventListener("wheel", (e) => {
    if (!e.altKey || e.ctrlKey || e.metaKey) return;
    if (e.defaultPrevented) return; // Teleop turned a gripper
    const name = drag?.name || itemAt(e);
    if (!name || isContainer(name)) return;
    e.stopPropagation();
    e.preventDefault();
    select(name);
    queueTurn(name, (e.deltaY < 0 ? 1 : -1) * WHEEL_DEG * (e.shiftKey ? SLOW_FACTOR : 1));
  }, { capture: true, passive: false });

  // ---------- only while this tab is open ----------

  function syncVisibility() {
    const active = isActive();
    view.activate("objects", active);
    layer.hidden = !active || view.frame("objects") === null;
    objectsHint.hidden = !active;
    if (active) {
      render();
      return;
    }
    endDrag();
    state.hover = null;
    if (cursorSet) {
      viewer.style.cursor = "";
      cursorSet = false;
    }
  }
  const visibility = new MutationObserver(syncVisibility);
  for (let element = root; element; element = element.parentElement) {
    visibility.observe(element, { attributes: true, attributeFilter: ["hidden"] });
  }
  syncVisibility();
}
