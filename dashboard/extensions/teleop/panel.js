// Teleop panel: live TCP coordinates, arm selection, gripper buttons, key legend.
// In the 3D view: coordinate labels at the grippers, dragging the colored balls with the mouse, keyboard control.
import { onImage, overlayViewer, toImage, toPixels } from "/static/lib/viewer-overlay.js";

const SIDES = ["left", "right"];
const NAMES = { left: "Left arm", right: "Right arm" };
const SHORT = { left: "L", right: "R" };
// Key -> direction relative to the view: [forward, right, up]
const MOVES = { w: [1, 0, 0], s: [-1, 0, 0], d: [0, 1, 0], a: [0, -1, 0], e: [0, 0, 1], q: [0, 0, -1] };
// Key -> [rotate about the gripper's axis (+ = counterclockwise from above), tilt (+ = tips away from you)]
const TURNS = { z: [1, 0], x: [-1, 0], r: [0, 1], f: [0, -1] };
const SPEEDS = { slow: 0.02, normal: 0.06, fast: 0.15 }; // m/s while a key is held
const TURN_SPEED = 60; // deg/s at "normal", scaled like SPEEDS
const WHEEL_DEG = 10; // rotation per mouse wheel notch over a ball
const MAX_TURN = 45; // deg per request (server limit)
const SLOW_FACTOR = 0.25; // with Shift held
const TICK_MS = 50;
const HANDLE_PX = 24; // grab radius around a TCP in the view
const MAX_STEP = 0.05; // m per request (server limit)

export async function mount(root, api) {
  const { h, toast } = api.ui;
  const viewer = document.getElementById("viewer");
  const view = overlayViewer(viewer);
  const isActive = () => root.isConnected && !root.closest("[hidden]");
  let savedFrame = null;
  try { savedFrame = localStorage.getItem("dream.teleop.frame"); } catch {}
  // frame: whose forward/left/right the keys use. "robot" = the robot's overhead camera, "view" = the 3D view.
  const state = { selected: "left", info: null, keyboard: true, speed: "normal", slow: false,
    frame: savedFrame === "view" ? "view" : "robot" };
  const initial = await api.get("/state");

  let lastError = 0;
  const report = (error) => {
    if (Date.now() - lastError < 2500) return;
    lastError = Date.now();
    toast(error.message, "error");
  };
  const busy = () => Boolean(state.info?.busy);
  const warnBusy = () => report(new Error("A run is active: teleop works between runs."));

  // ---------- panel ----------

  const cells = {}, cards = {};
  for (const side of SIDES) {
    const c = { x: h("td", { class: "num" }), y: h("td", { class: "num" }), z: h("td", { class: "num" }),
      grip: h("td", { class: "num" }), status: h("span", { class: "muted" }),
      rotation: h("span", { class: "mono" }), tilt: h("span", { class: "mono" }) };
    cells[side] = c;
    const button = (label, action) => h("button", { class: "btn small", type: "button",
      onclick: (e) => { e.stopPropagation(); e.currentTarget.blur(); gripper(side, action); } }, label);
    cards[side] = h("div", { class: `teleop-arm ${side}`, onclick: () => select(side) },
      h("div", { class: "teleop-arm-head" }, h("i", { class: `teleop-dot ${side}` }), h("strong", {}, NAMES[side]), c.status),
      h("table", { class: "table" },
        h("thead", {}, h("tr", {}, h("th", {}, "x (m)"), h("th", {}, "y (m)"), h("th", {}, "z (m)"), h("th", {}, "Gripper"))),
        h("tbody", {}, h("tr", {}, c.x, c.y, c.z, c.grip))),
      h("div", { class: "teleop-rot" }, "Rotation ", c.rotation, " · Tilt ", c.tilt),
      h("div", { class: "row" }, button("Open", "open"), button("Close", "close")));
  }

  const keyboardBox = h("input", { type: "checkbox", checked: true,
    onchange: () => { state.keyboard = keyboardBox.checked; pressed.clear(); } });
  const speedSelect = h("select", { onchange: () => (state.speed = speedSelect.value) },
    Object.keys(SPEEDS).map((k) => h("option", { value: k }, k)));
  speedSelect.value = state.speed;
  const orientSelect = h("select", { onchange: () => {
    if (isActive()) api.post("/orientation", { mode: orientSelect.value }).catch(report);
  } },
    h("option", { value: "down" }, "points straight down"), h("option", { value: "free" }, "free (tilt with R / F)"));
  orientSelect.value = initial.orientation || "down";

  const frameSelect = h("select", { onchange: () => setFrame(frameSelect.value) },
    h("option", { value: "robot" }, "the robot (overhead camera)"), h("option", { value: "view" }, "the 3D view"));
  frameSelect.value = state.frame;
  const seenFrom = h("span");
  const keys = [
    ["Drag a ball", "move the gripper (height stays)"],
    ["Shift + drag", "move it up / down"],
    ["W A S D", h("span", {}, "forward / left / back / right, as seen from ", seenFrom)],
    ["E / Q", "up / down"],
    ["Z / X", "rotate the gripper about its axis (left / right)"],
    ["Alt + scroll on ball", "rotate the gripper"],
    ["R / F", "tilt the fingertips forward / back"],
    ["Shift (held)", "slow"],
    ["Space", "open / close the gripper"],
    ["1 / 2", "select left / right arm"],
  ];
  function setFrame(frame) {
    state.frame = frame;
    seenFrom.textContent = frame === "robot" ? "the robot (its overhead camera)" : "the 3D view";
    try { localStorage.setItem("dream.teleop.frame", frame); } catch {}
  }
  setFrame(state.frame);

  root.append(
    h("p", { class: "muted" }, "Tool center point (TCP) = the simulator's point between the fingertips, world coordinates. ",
      "The colored line shows the direction the fingers open in. Works between runs, not while Dream-1 drives."),
    cards.left, cards.right,
    h("label", { class: "check" }, keyboardBox, "Keyboard control (not while typing in a field)"),
    h("div", { class: "row teleop-options" },
      h("label", {}, "Keys move as seen from ", frameSelect)),
    h("div", { class: "row teleop-options" },
      h("label", {}, "Speed ", speedSelect),
      h("label", {}, "Gripper ", orientSelect)),
    h("h4", {}, "Controls"),
    h("table", { class: "table teleop-keys" }, h("tbody", {}, keys.map(([k, d]) => h("tr", {}, h("td", {}, k), h("td", {}, d))))),
  );

  function select(side) {
    state.selected = side;
    for (const s of SIDES) cards[s].classList.toggle("selected", s === side);
  }
  select("left");

  async function gripper(side, action) {
    if (!isActive()) return;
    if (busy()) return warnBusy();
    try { await api.post("/gripper", { side, action }); } catch (error) { report(error); }
  }

  // ---------- 3D view: labels ----------

  const layer = h("div", { class: "teleop-layer" });
  const labels = {};
  for (const side of SIDES) layer.append((labels[side] = h("div", { class: `teleop-label ${side}` })));
  viewer.append(layer);
  const hint = document.querySelector(".viewer-hint");
  const teleopHint = h("span", {}, " · Ball: move gripper");
  if (hint) hint.append(teleopHint);

  const degrees = (value) => (value === null ? "–" : `${Math.round(value)}°`);

  view.onFrame("teleop", (info) => {
    if (!isActive()) return;
    state.info = info;
    layer.hidden = false;
    if (document.activeElement !== orientSelect) orientSelect.value = info.orientation;
    const box = view.box();
    for (const side of SIDES) {
      const arm = info.arms[side], c = cells[side];
      ["x", "y", "z"].forEach((axis, i) => (c[axis].textContent = arm.pos[i].toFixed(3)));
      c.grip.textContent = `${Math.round(arm.gripper * 100)} %`;
      c.rotation.textContent = degrees(arm.rotation);
      c.tilt.textContent = degrees(arm.tilt);
      const moving = arm.goal && Math.hypot(...arm.goal.map((v, i) => v - arm.pos[i])) > 0.004;
      const problem = !arm.goal ? "" : !arm.reached ? "out of reach" : !arm.rotation_ok ? "can't turn further here" : "";
      c.status.textContent = info.busy ? "run active" : problem || (moving ? "moving" : "");
      c.status.className = problem && !info.busy ? "bad" : "muted";

      const label = labels[side];
      const [x, y] = arm.screen ? toPixels(box, arm.screen) : [-1, -1];
      const inside = arm.screen && onImage(arm.screen);
      label.style.display = inside ? "" : "none";
      if (!inside) continue;
      label.style.left = `${x}px`;
      label.style.top = `${y}px`;
      label.textContent = `${SHORT[side]}  x ${arm.pos[0].toFixed(3)}  y ${arm.pos[1].toFixed(3)}  z ${arm.pos[2].toFixed(3)}`
        + `  turn ${degrees(arm.rotation)}${arm.tilt >= 1 ? `  tilt ${degrees(arm.tilt)}` : ""}`;
      label.classList.toggle("flip", x > box.rect.width - 230);
      label.classList.toggle("selected", side === state.selected);
      label.classList.toggle("unreachable", Boolean(arm.goal && !arm.reached));
    }
  });

  // ---------- 3D view: drag the TCP balls ----------

  function handleAt(e) {
    if (!isActive() || view.frame("teleop") === null || !state.info) return null;
    const box = view.box();
    if (!onImage(toImage(box, e.clientX, e.clientY))) return null;
    const mx = e.clientX - box.rect.left, my = e.clientY - box.rect.top;
    let best = null, bestDistance = HANDLE_PX;
    for (const side of SIDES) {
      const screen = state.info.arms[side].screen;
      if (!screen || !onImage(screen)) continue;
      const [x, y] = toPixels(box, screen);
      const distance = Math.hypot(x - mx, y - my);
      if (distance < bestDistance) [best, bestDistance] = [side, distance];
    }
    return best;
  }

  let drag = null, dragNext = null, dragSending = false;
  function queueDrag(e) {
    const frame = view.frame("teleop");
    if (frame === null) return;
    const [u, v] = toImage(view.box(), e.clientX, e.clientY);
    dragNext = { side: drag.side, u, v, frame, mode: e.shiftKey ? "vertical" : "horizontal",
      start: drag.start || Boolean(dragNext?.start) };
    drag.start = false;
    flushDrag();
  }
  async function flushDrag() {
    if (!isActive() || dragSending || !dragNext) return;
    const body = dragNext;
    dragNext = null;
    dragSending = true;
    try { await api.post("/drag", body); } catch (error) { report(error); } finally { dragSending = false; flushDrag(); }
  }

  // Capture phase: a press on a ball starts a TCP drag instead of orbiting the camera.
  viewer.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    const side = handleAt(e);
    if (!side) return;
    if (busy()) return warnBusy();
    e.stopPropagation();
    e.preventDefault();
    viewer.setPointerCapture(e.pointerId);
    select(side);
    drag = { side, pointerId: e.pointerId, start: true };
    queueDrag(e);
  }, { capture: true });
  viewer.addEventListener("pointermove", (e) => {
    if (!isActive()) return;
    if (drag) {
      if (e.pointerId !== drag.pointerId) return;
      e.stopPropagation();
      queueDrag(e);
      return;
    }
    viewer.style.cursor = !e.buttons && handleAt(e) && !busy() ? "move" : "";
  }, { capture: true });
  const endDrag = (e) => {
    if (!drag || e.pointerId !== drag.pointerId) return;
    drag = null;
    e.stopPropagation();
  };
  viewer.addEventListener("pointerup", endDrag, { capture: true });
  viewer.addEventListener("pointercancel", endDrag, { capture: true });

  // Mouse wheel on a ball rotates that gripper instead of zooming.
  viewer.addEventListener("wheel", (e) => {
    if (!e.altKey || e.ctrlKey || e.metaKey) return;
    const side = handleAt(e);
    if (!side) return;
    e.stopPropagation();
    e.preventDefault();
    if (busy()) return warnBusy();
    select(side);
    turn[0] += (e.deltaY < 0 ? 1 : -1) * WHEEL_DEG * (e.shiftKey ? SLOW_FACTOR : 1);
    flushJog();
  }, { capture: true, passive: false });

  // ---------- keyboard ----------

  const pressed = new Set();
  let loop = null, pending = [0, 0, 0], turn = [0, 0], jogSending = false;
  const typing = (el) => el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName));

  window.addEventListener("keydown", (e) => {
    if (!isActive()) return;
    state.slow = e.shiftKey;
    if (!state.keyboard || typing(e.target) || e.ctrlKey || e.metaKey || e.altKey) return;
    const key = e.key.toLowerCase();
    if (key in MOVES || key in TURNS) {
      if (e.repeat && !pressed.has(key)) return;
      e.preventDefault();
      if (busy()) return warnBusy();
      pressed.add(key);
      if (!loop) loop = setInterval(tick, TICK_MS);
    } else if (key === " ") {
      e.preventDefault();
      if (e.target.tagName === "BUTTON") e.target.blur(); // Space would also click the focused button
      if (!e.repeat) gripper(state.selected, "toggle");
    } else if (key === "1" || key === "2") {
      select(key === "1" ? "left" : "right");
    }
  });
  window.addEventListener("keyup", (e) => {
    state.slow = e.shiftKey;
    pressed.delete(e.key.toLowerCase());
  });
  function resetInput() {
    pressed.clear();
    state.slow = false;
    clearInterval(loop);
    loop = null;
    pending = [0, 0, 0];
    turn = [0, 0];
    dragNext = null;
    const pointerId = drag?.pointerId;
    drag = null;
    if (pointerId != null && viewer.hasPointerCapture(pointerId)) viewer.releasePointerCapture(pointerId);
    viewer.style.cursor = "";
  }
  window.addEventListener("blur", resetInput);

  function syncVisibility() {
    const active = isActive();
    view.activate("teleop", active);
    layer.hidden = !active || view.frame("teleop") === null;
    teleopHint.hidden = !active;
    if (!active) resetInput();
  }
  const visibility = new MutationObserver(syncVisibility);
  for (let element = root; element; element = element.parentElement) {
    visibility.observe(element, {attributes: true, attributeFilter: ["hidden"]});
  }
  syncVisibility();

  function tick() {
    if (!isActive()) { resetInput(); return; }
    if (!pressed.size) {
      clearInterval(loop);
      loop = null;
      return;
    }
    const scale = (state.slow ? SLOW_FACTOR : 1) * TICK_MS / 1000;
    const step = SPEEDS[state.speed] * scale;
    const turnStep = TURN_SPEED * (SPEEDS[state.speed] / SPEEDS.normal) * scale;
    for (const key of pressed) {
      if (key in MOVES) MOVES[key].forEach((value, i) => (pending[i] += value * step));
      else TURNS[key].forEach((value, i) => (turn[i] += value * turnStep));
    }
    flushJog();
  }
  async function flushJog() {
    if (!isActive()) return;
    const length = Math.hypot(...pending);
    if (jogSending || (length < 1e-6 && !turn[0] && !turn[1])) return;
    if (busy()) { pending = [0, 0, 0]; turn = [0, 0]; return warnBusy(); }
    const clampTurn = (value) => Math.max(-MAX_TURN, Math.min(MAX_TURN, value));
    const body = { side: state.selected, rotate: clampTurn(turn[0]), tilt: clampTurn(turn[1]), frame: state.frame };
    if (length >= 1e-6) Object.assign(body, { move: pending.map((v) => v / length), step: Math.min(length, MAX_STEP) });
    pending = [0, 0, 0];
    turn = [0, 0];
    jogSending = true;
    try { await api.post("/jog", body); } catch (error) { report(error); } finally { jogSending = false; flushJog(); }
  }
}
