// Tutorial: short guided walkthroughs of the dashboard.
//
// The Tutorial button in the top bar opens a list of tours. Picking one starts a step-by-step walkthrough: each step
// highlights one part of the page and explains it in a small card (Back / Next, Esc to close). A step may first
// prepare the page (switch between Dashboard and Test Suite, open a tool, unfold a side panel). Tours only show
// things: no step starts a run, moves an arm or spends credits.
//
// A tour can also be started from the address: http://localhost:8000/?tour=basics (handy for a demo).
// A new tour is one entry in TOURS. A step whose target is missing or hidden is shown in the middle of the screen,
// or skipped when it is marked `optional` (for example a tool whose extension did not load).
import { h } from "./lib/api.js";

const $ = (id) => document.getElementById(id);
const SEEN_KEY = "dream.tutorialSeen";  // the "New here?" hint was shown or dismissed
const DONE_KEY = "dream.tutorialDone";  // ids of the tours finished to the end
const MARGIN = 12;  // px between the card and the window edge / the highlighted element

// ---------------- page preparation used by the steps ----------------

const settle = () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));

function dashboard() {
  const button = $("workspace-dashboard");
  if (button && !button.classList.contains("active")) button.click();
}

function testSuite(view = "build") {
  const button = $("workspace-test-suite");
  if (button && !button.hidden && !button.classList.contains("active")) button.click();
  const tab = $(view === "report" ? "suite-report-tab" : "suite-build-tab");
  if (tab && !tab.classList.contains("active")) tab.click();
}

function unfold(side) {
  const layout = document.querySelector(".layout");
  if (layout?.classList.contains(`${side}-collapsed`)) $(`${side}-rail`)?.click();
}

const tool = (id) => (core) => {
  dashboard();
  unfold("left");
  if (core.activate) core.activate(id);
};

function openSettings(open) {
  const details = document.querySelector(".run-settings");
  if (details) details.open = open;
}

// ---------------- the tours ----------------
// step: { target: CSS selector (none = centred card), title, text, before(core), host: hosts only,
//         optional: skip the step when the target is not on the page }

const TOURS = [
  {
    id: "basics",
    title: "Dashboard basics",
    summary: "The parts of the page: 3D view, robot cameras, prompt bar, tools and the run panel.",
    guest: true,
    steps: [
      { title: "Welcome to DreamLab-Rat",
        text: "This dashboard runs Dream-1, Dream Labs' robot model, in a MuJoCo simulation: two YAM arms, three "
          + "cameras, fruit, a bowl and a plate. This tour shows the main parts of the page. Nothing in it starts a "
          + "run or spends credits.",
        before: dashboard },
      { target: "#viewer-frame", title: "The 3D view",
        text: "A live picture of the simulation. Drag to orbit, right-drag or Shift-drag to pan, hold Alt and scroll "
          + "to zoom, double-click to reset the camera." },
      { target: "#cams", title: "What Dream-1 sees",
        text: "The robot's three cameras: overhead, left wrist and right wrist. These are the images Dream-1 gets. "
          + "Click one to show it on the big screen; click the 3D view tile to swap back." },
      { target: "#taskbar", title: "The prompt bar", host: true,
        text: "Type a task in plain English, for example “put the apple in the bowl”, and press Run with Dream-1. "
          + "Stop ends the run after Dream-1's pending reply." },
      { target: ".scene-actions", title: "Free scene controls", host: true,
        text: "Offline demo moves the arms without calling Dream-1. Home brings the arms back to their start pose, "
          + "Reset puts every object back. None of these cost credits." },
      { target: "#dashboard-tools", title: "Tools", before: () => { dashboard(); unfold("left"); },
        text: "Pick a tool from this menu: Scene (object positions), Control (move the arms yourself), Objects, "
          + "Cameras, X-Ray, Brain, Episodes, Credits and Players. The ‹ button folds the panel away." },
      { target: "#col-right", title: "The run panel", before: () => unfold("right"),
        text: "The last run's outcome, duration and cost, Dream-1's response time per request, and the application "
          + "log. Hide panel gives the simulation more room." },
      { target: "#workspace-test-suite", title: "Test Suite", host: true, optional: true,
        text: "Switches to the Test Suite: many trials in a row, with a report at the end. It has its own tour." },
      { target: "#btn-tutorial", title: "That's it",
        text: "Open Tutorial any time to pick another tour, for example your first run or moving the arms yourself." },
    ],
  },
  {
    id: "first-run",
    title: "Your first run with Dream-1",
    summary: "Write a task, choose the settings, try it for free, then run Dream-1 and read the result.",
    steps: [
      { target: "#task", title: "Write a task", before: () => { dashboard(); openSettings(false); },
        text: "Name one object and where it should go, for example “put the banana on the plate”. The list under "
          + "the field shows task types the success check understands. Other wordings still run; their success is "
          + "then unknown." },
      { target: ".run-settings", title: "Settings", before: () => openSettings(true),
        text: "Model, duration (simulated seconds: waiting for Dream-1 does not count) and how Dream-1's action "
          + "chunks are executed. Crossfade (30), the default, blends each new plan into the old one; it measured "
          + "clearly better than running whole chunks." },
      { target: "#btn-demo", title: "Try it for free first", before: () => openSettings(false),
        text: "Offline demo plays a scripted motion without calling Dream-1: a quick check that the simulation "
          + "moves. It costs nothing." },
      { target: "#btn-run", title: "Run with Dream-1",
        text: "Every Dream-1 request costs credits. When a run would cost more than your confirm threshold, the "
          + "button first shows the estimate and needs a second click. A run that could pass the monthly limit is "
          + "refused." },
      { target: "#viewer-frame", title: "Watch it work",
        text: "While Dream-1 works the view shows Live and the task. The run ends on success, at the time limit, or "
          + "when you press Stop." },
      { target: "#run-card", title: "Read the result", before: () => unfold("right"),
        text: "Outcome (Success, Unsuccessful, or Unevaluated when no success check fits the task), duration and "
          + "source. Execution details holds the steps, requests, response time and cost." },
      { target: '.panel[data-id="credits"]', title: "Credits and limits", before: tool("credits"), optional: true,
        text: "The balance, today's and this month's spending, the price per call, and the limits: the monthly "
          + "limit and the amount above which Run asks first." },
    ],
  },
  {
    id: "control",
    title: "Move the arms yourself",
    summary: "The Control tool: drag the grippers, use the keyboard, open and close the gripper.",
    guest: true,
    steps: [
      { target: '.panel[data-id="teleop"]', title: "The Control tool", before: tool("teleop"), optional: true,
        text: "Moves the grippers between runs, with mouse or keyboard. It costs no credits and is refused while a "
          + "run is active. As a guest, first take an arm in Players." },
      { target: "#viewer-frame", title: "Drag a gripper ball",
        text: "Each gripper has a coloured ball in the 3D view. Drag it to move the gripper over the table; hold "
          + "Shift while dragging to move it up and down. Alt + scroll on a ball rotates the gripper." },
      { target: ".teleop-arm", title: "Pick an arm", optional: true,
        text: "Click a card (or press 1 / 2) to choose the arm the keys move. The card shows its tool centre point "
          + "(x, y, z in metres), the gripper opening, rotation and tilt, live." },
      { target: ".teleop-keys", title: "Keyboard", optional: true,
        text: "W A S D move, E / Q go up and down, Z / X rotate, R / F tilt, Space opens or closes the gripper. "
          + "Hold Shift to go slow. The keys work while no text field has the focus." },
    ],
  },
  {
    id: "teach",
    title: "Teach Dream-1: episodes",
    summary: "Take over when Dream-1 fails, save the episode, export it for a fine-tune.",
    steps: [
      { target: "#taskbar", title: "Every run is recorded", before: dashboard,
        text: "Each Dream-1 run started with Run is recorded as an episode, in the LeRobot format Dream Labs checks "
          + "before a fine-tune: three camera videos and the arm values, 10 frames per second." },
      { target: "#btn-takeover", title: "Take over",
        text: "If Dream-1 gets stuck, press Take over: Dream-1 stops, the scene stays as it is, and the Control tool "
          + "opens so you can finish the task yourself. Recording continues." },
      { target: "#taskbar", title: "Save or discard",
        text: "When you are done, Save episode keeps it (the success check marks it) and Discard deletes it. Both "
          + "buttons appear here as soon as there is an episode to save." },
      { target: '.panel[data-id="episodes"]', title: "The Episodes tool", before: tool("episodes"), optional: true,
        text: "What is ready for a fine-tune, success and cost per model, and where people took over. Export copies "
          + "the episodes of one task into out/exports/ and runs Dream Labs' own dataset check. Nothing is "
          + "uploaded." },
    ],
  },
  {
    id: "test-suite",
    title: "Test Suite and robustness",
    summary: "Run many trials automatically, try a dry run, and read the report.",
    steps: [
      { target: "#workspace-test-suite", title: "The Test Suite", before: () => testSuite("build"),
        text: "Runs many trials in a row and writes a report: success rate, why trials failed, timing, evidence "
          + "pictures and videos." },
      { target: ".suite-mode-select", title: "Choose a test", optional: true,
        text: "Quick Test, Repeated Runs, Parameter Sweep, Safety Stress Test, A/B Comparison, Failure "
          + "Reproduction, and the robustness tests: Robustness Sweep, Breaking Point, Perturbation Mix and "
          + "Strategy A/B." },
      { target: "#test-suite-config .suite-form", title: "Describe the trials", optional: true,
        text: "The task, and under Advanced settings the time limit, request budget and video recording. The "
          + "robustness tests also choose the perturbation and its strengths here." },
      { target: "#test-suite-config .campaign-actions", title: "Dry run first", optional: true,
        text: "Tick Dry run to check the whole workflow without calling Dream-1. The line under it says how many "
          + "trials will run and whether they use the live API." },
      { target: "#test-suite-monitor", title: "Test execution",
        text: "Progress of the running campaign. Campaigns are stopped here, not with the Stop button on the "
          + "Dashboard." },
      { target: "#suite-report-tab", title: "Reports",
        text: "Every campaign's report: outcome per trial, timing, evidence frames and downloads (JSON, CSV, print "
          + "or PDF)." },
      { target: "#workspace-dashboard", title: "Back to the Dashboard",
        text: "This button brings you back to the simulation and the prompt bar." },
    ],
  },
  {
    id: "insight",
    title: "Look inside Dream-1",
    summary: "Camera check, Model X-Ray and the second brain.",
    steps: [
      { target: '.panel[data-id="camera_check"]', title: "Camera check", before: tool("camera_check"),
        optional: true,
        text: "Compares every frame sent to Dream-1 with the simulation's own render: right camera on the right "
          + "key, upright, natural colours, current and not frozen. The self-test injects faults on purpose to "
          + "show the check catches them." },
      { target: '.panel[data-id="xray"]', title: "Model X-Ray", before: tool("xray"), optional: true,
        text: "Freezes one moment and asks Dream-1 about it again with one thing changed: which camera it relies on, "
          + "where in the picture it looks, and whether it follows the object named in the prompt." },
      { target: "#viewer-frame", title: "Live intent",
        text: "During a run, X-Ray draws Dream-1's plan into the 3D view: the orange path the gripper will take, a "
          + "red dot where it closes, and yellow for the object it heads for." },
      { target: '.panel[data-id="brain"]', title: "The second brain", before: tool("brain"), optional: true,
        text: "Every run, campaign and export also lands in brain/ as a small wiki (one page per task and model). "
          + "Click a point to read its page." },
    ],
  },
];

// ---------------- storage ----------------

function stored(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; }
}
function store(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch {}
}

// ---------------- geometry ----------------

function visible(el) {
  if (!el || el.closest("[hidden]")) return false;
  const rect = el.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0;
}

/** Where the card goes: below, above, right of or left of the target, whichever fits first; else the bottom edge. */
function place(card, rect) {
  const vw = window.innerWidth, vh = window.innerHeight;
  const cw = card.offsetWidth, ch = card.offsetHeight;
  const clampX = (x) => Math.max(MARGIN, Math.min(vw - cw - MARGIN, x));
  const clampY = (y) => Math.max(MARGIN, Math.min(vh - ch - MARGIN, y));
  if (!rect) return { left: (vw - cw) / 2, top: Math.max(MARGIN, (vh - ch) / 2) };
  const centreX = rect.left + rect.width / 2 - cw / 2, centreY = rect.top + rect.height / 2 - ch / 2;
  const options = [
    [vh - rect.bottom >= ch + 2 * MARGIN, () => ({ left: clampX(centreX), top: rect.bottom + MARGIN })],
    [rect.top >= ch + 2 * MARGIN, () => ({ left: clampX(centreX), top: rect.top - ch - MARGIN })],
    [vw - rect.right >= cw + 2 * MARGIN, () => ({ left: rect.right + MARGIN, top: clampY(centreY) })],
    [rect.left >= cw + 2 * MARGIN, () => ({ left: rect.left - cw - MARGIN, top: clampY(centreY) })],
  ];
  const fit = options.find(([fits]) => fits);
  return fit ? fit[1]() : { left: clampX(centreX), top: vh - ch - MARGIN };
}

// ---------------- the walkthrough ----------------

export function setupTutorial(core) {
  const guest = core.me?.role === "guest";
  const tours = TOURS.filter((t) => !guest || t.guest)
    .map((t) => ({ ...t, steps: t.steps.filter((s) => !(guest && s.host)) }));
  const button = $("btn-tutorial");
  if (!button) return;

  let active = null;  // { tour, index, returnFocus }
  let token = 0;  // a newer step wins over a step still preparing the page

  // the layer: a transparent backdrop (blocks clicks on the page), the spotlight and the card
  const spotlight = h("div", { class: "tour-spotlight", hidden: true });
  const titleEl = h("h2", { id: "tour-title" });
  const textEl = h("p", { id: "tour-text" });
  const countEl = h("span", { class: "tour-count muted" });
  const backButton = h("button", { type: "button", class: "btn btn-outline btn-sm" }, "Back");
  const nextButton = h("button", { type: "button", class: "btn primary btn-sm" }, "Next");
  const closeButton = h("button", { type: "button", class: "tour-close", "aria-label": "Close the tour" }, "×");
  const dots = h("div", { class: "tour-dots", "aria-hidden": "true" });
  const card = h("div", { class: "tour-card", role: "dialog", "aria-modal": "true", "aria-labelledby": "tour-title",
    "aria-describedby": "tour-text" },
  h("div", { class: "tour-card-head" }, countEl, closeButton), titleEl, textEl,
  h("div", { class: "tour-card-foot" }, dots, h("div", { class: "tour-buttons" }, backButton, nextButton)));
  const backdrop = h("div", { class: "tour-backdrop" });
  const layer = h("div", { class: "tour-layer", hidden: true }, backdrop, spotlight, card);
  document.body.append(layer);

  backButton.onclick = () => go(active.index - 1);
  nextButton.onclick = () => (active.index + 1 < active.tour.steps.length ? go(active.index + 1) : finish(true));
  closeButton.onclick = () => finish(false);

  let target = null;
  const position = () => {
    if (!active) return;
    const rect = visible(target) ? target.getBoundingClientRect() : null;
    spotlight.hidden = !rect;
    backdrop.classList.toggle("dim", !rect);  // no element to light up: dim the whole page instead
    if (rect) {
      const pad = 6;
      Object.assign(spotlight.style, { left: `${rect.left - pad}px`, top: `${rect.top - pad}px`,
        width: `${rect.width + 2 * pad}px`, height: `${rect.height + 2 * pad}px` });
    }
    const { left, top } = place(card, rect);
    Object.assign(card.style, { left: `${left}px`, top: `${top}px` });
  };
  let frame = 0;
  const reposition = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(position); };
  window.addEventListener("resize", reposition);
  document.addEventListener("scroll", reposition, true);

  async function go(index, direction = Math.sign(index - (active?.index ?? 0)) || 1) {
    const { tour } = active;
    const mine = ++token;
    if (index < 0) return go(0, 1);  // Back past optional steps that are not on the page
    const step = tour.steps[index];
    if (!step) return finish(true);
    try { await step.before?.(core); } catch (error) { console.warn("Tutorial step", error); }
    await settle();
    if (mine !== token || !active) return;
    const el = step.target ? document.querySelector(step.target) : null;
    if (step.optional && !visible(el)) return go(index + direction, direction);  // e.g. a tool that is not loaded
    active.index = index;
    target = el;
    countEl.textContent = `${tour.title} · ${index + 1} of ${tour.steps.length}`;
    titleEl.textContent = step.title;
    textEl.textContent = step.text;
    backButton.disabled = index === 0;
    nextButton.textContent = index === tour.steps.length - 1 ? "Done" : "Next";
    dots.replaceChildren(...tour.steps.map((_, i) => h("i", { class: i === index ? "on" : i < index ? "seen" : "" })));
    if (visible(el)) {
      const smooth = !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      el.scrollIntoView({ block: "nearest", inline: "nearest", behavior: smooth ? "smooth" : "auto" });
    }
    position();
    nextButton.focus({ preventScroll: true });
  }

  function start(id) {
    const tour = tours.find((t) => t.id === id);
    if (!tour) return;
    closeMenu();
    hideHint();
    active = { tour, index: 0, returnFocus: document.activeElement };
    layer.hidden = false;
    document.body.classList.add("touring");
    go(0, 1);
  }

  function finish(completed) {
    if (!active) return;
    if (completed) store(DONE_KEY, [...new Set([...stored(DONE_KEY, []), active.tour.id])]);
    const focus = active.returnFocus;
    active = null;
    target = null;
    token++;
    layer.hidden = true;
    document.body.classList.remove("touring");
    if (completed) core.toast?.("Tour finished. Tutorial has more tours.", "good", 3000);
    (visible(focus) ? focus : button).focus?.({ preventScroll: true });
  }

  // Keys while a tour or the menu is open: arrows / Enter / Esc steer it; nothing reaches the page (the Control tool
  // would move an arm on W A S D, or toggle the gripper on Space instead of pressing the focused button).
  // Tab stays inside the card.
  window.addEventListener("keydown", (e) => {
    if (menu.open) {
      if (e.key === "Escape") { e.preventDefault(); closeMenu(); }
      e.stopPropagation();
      return;
    }
    if (!active) return;
    if (e.key === "Tab") {
      const items = [...card.querySelectorAll("button:not(:disabled)")];
      const at = items.indexOf(document.activeElement);
      e.preventDefault();
      items[(at + (e.shiftKey ? -1 : 1) + items.length) % items.length]?.focus();
    } else if (e.key === "Escape") finish(false);
    else if (e.key === "ArrowRight") nextButton.click();
    else if (e.key === "ArrowLeft" && !backButton.disabled) backButton.click();
    else if (e.key !== "Enter" && e.key !== " ") e.preventDefault();  // Enter / Space press the focused button
    e.stopPropagation();
  }, true);

  // ---------------- the tour menu ----------------

  const list = h("div", { class: "tour-list" });
  const menu = h("dialog", { class: "tour-menu", "aria-labelledby": "tour-menu-title" },
    h("div", { class: "tour-menu-body" },  // fills the dialog: a click on the dialog itself is on the backdrop
      h("div", { class: "tour-menu-head" },
        h("h2", { id: "tour-menu-title" }, "Tutorial"),
        h("button", { type: "button", class: "tour-close", "aria-label": "Close", onclick: () => closeMenu() }, "×")),
      h("p", { class: "muted" }, "Pick a short tour. Each one takes about a minute; nothing in it starts a run or "
        + "spends credits. The arrow keys step through a tour, Esc closes it."),
      list));
  document.body.append(menu);
  menu.addEventListener("click", (e) => { if (e.target === menu) closeMenu(); });

  function renderMenu() {
    const done = new Set(stored(DONE_KEY, []));
    list.replaceChildren(...tours.map((t) => h("button", { type: "button", class: "tour-item", onclick: () => start(t.id) },
      h("span", { class: "tour-item-head" }, h("strong", {}, t.title),
        h("span", { class: "muted" }, `${t.steps.length} steps${done.has(t.id) ? " · done ✓" : ""}`)),
      h("span", { class: "muted" }, t.summary))));
  }
  function openMenu() {
    if (active) finish(false);
    hideHint();
    renderMenu();
    if (!menu.open) menu.showModal();
    list.querySelector("button")?.focus();
  }
  function closeMenu() { if (menu.open) menu.close(); }
  button.onclick = () => (menu.open ? closeMenu() : openMenu());

  // ---------------- "New here?" hint (first visit only, does not block the page) ----------------

  const hint = h("div", { class: "tour-hint", role: "status", hidden: true },
    h("span", {}, "New here? Take a one-minute tour."),
    h("button", { type: "button", class: "btn primary btn-sm", onclick: () => start(tours[0].id) }, "Start"),
    h("button", { type: "button", class: "btn btn-outline btn-sm", onclick: openMenu }, "All tours"),
    h("button", { type: "button", class: "tour-close", "aria-label": "Dismiss", onclick: () => hideHint() }, "×"));
  document.body.append(hint);
  function hideHint() {
    hint.hidden = true;
    store(SEEN_KEY, true);
  }

  const placeHint = () => {  // under the Tutorial button, which moves when the top bar wraps
    if (!hint.hidden) hint.style.top = `${Math.max(8, button.getBoundingClientRect().bottom + 8)}px`;
  };
  window.addEventListener("resize", placeHint);

  const requested = new URLSearchParams(location.search).get("tour");
  if (requested && tours.some((t) => t.id === requested)) start(requested);
  else if (!stored(SEEN_KEY, false)) {
    hint.hidden = false;
    placeHint();
  }

  core.tutorial = { start, open: openMenu, tours: tours.map((t) => t.id) };  // for the console and other panels
}
