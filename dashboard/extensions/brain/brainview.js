// The Brain view: DreamLab-Rat and its second brain drawn as one see-through 3D brain (three.js).
// Used by panel.js (the "Brain" tool in the left column) and brain.html (the full page).
//
// Each brain part stands for a part of the project and lights up when that part works:
//   cortex        Dream-1, the model that plans the arm motion      a Dream-1 call (run.reply)
//   visual        the robot cameras and the 3D view                 while the simulation sends frames (sim.state)
//   cerebellum    the execution strategy that smooths each plan     a new plan is blended in (after run.reply)
//   brainstem     the MuJoCo simulation thread                      heartbeat while the simulation runs
//   hippocampus   brain/raw/: new memories (runs, summaries, notes) a run ends; new raw files appear
//   memory        brain/wiki/: long-term memory, a linked graph     the wiki script changes a page
//   amygdala      the Test Suite safety checks                      a case fails its safety check
//   sleep         the teaching loop: episodes -> fine-tune export   an export (episode.exported)

import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js";

export const REGIONS = [
  { id: "cortex", name: "Cortex", stands: "Dream-1, the model that moves the robot", color: 0x48d6ff },
  { id: "visual", name: "Visual cortex", stands: "the robot cameras and the 3D view", color: 0x9d7bff },
  { id: "cerebellum", name: "Cerebellum", stands: "the execution strategy that smooths each plan", color: 0x5cf0a0 },
  { id: "brainstem", name: "Brainstem", stands: "the MuJoCo simulation", color: 0xffb648 },
  { id: "hippocampus", name: "Hippocampus", stands: "brain/raw/: new memories of runs and notes", color: 0xff6fd0 },
  { id: "memory", name: "Long-term memory", stands: "brain/wiki/: the pages, linked like a graph", color: 0xffe27a },
  { id: "amygdala", name: "Amygdala", stands: "the Test Suite safety checks", color: 0xff4d5e },
  { id: "sleep", name: "Sleep", stands: "the teaching loop: saved episodes become a fine-tune export", color: 0xb8c4ff },
];

const ANCHOR = {  // where each part sits (x: left-right, y: up, z: front)
  cortex: [0, 0.55, 0.35], visual: [0, 0.15, -0.95], cerebellum: [0, -0.5, -0.85], brainstem: [0, -0.95, -0.45],
  hippocampus: [0, -0.2, -0.05], memory: [0, 0.12, 0.05], amygdala: [0, -0.3, 0.32],
};
const WIRES = [  // how the parts work together; a light runs along a wire when data moves
  ["visual", "cortex"], ["cortex", "cerebellum"], ["cerebellum", "brainstem"], ["brainstem", "visual"],
  ["brainstem", "hippocampus"], ["hippocampus", "memory"], ["brainstem", "amygdala"], ["memory", "cortex"],
];

// ---------- shapes ----------

function rand(seed) {  // small fixed random source, so the brain looks the same on every load
  let s = seed >>> 0;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
}
function hash(text) {
  let x = 2166136261;
  for (const c of text) x = Math.imul(x ^ c.charCodeAt(0), 16777619);
  return x >>> 0;
}

function cortexPoints(count) {
  const r = rand(7), cortex = [], visual = [];
  while (cortex.length + visual.length < count) {
    const u = r() * 2 - 1, phi = r() * Math.PI * 2, s = Math.sqrt(1 - u * u);
    let dx = s * Math.cos(phi), dy = u, dz = s * Math.sin(phi);
    const side = dx >= 0 ? 1 : -1;
    const wrinkle = 1 + 0.05 * Math.sin(9 * dy + 13 * dz + 4 * side) * Math.sin(11 * dz - 7 * dy);
    let x = side * 0.34 + dx * 0.5 * wrinkle, y = 0.08 + dy * 0.68 * wrinkle, z = dz * 1.0 * wrinkle;
    if (Math.abs(x) < 0.035) continue;  // the gap between the two halves
    if (y < -0.32) y = -0.32 + (y + 0.32) * 0.35;  // flatter underside
    (z < -0.68 && y > -0.35 ? visual : cortex).push(x, y, z);
  }
  return { cortex, visual };
}
function ellipsoidPoints(count, [cx, cy, cz], [rx, ry, rz], seed, folds = 0) {
  const r = rand(seed), out = [];
  for (let i = 0; i < count; i++) {
    const u = r() * 2 - 1, phi = r() * Math.PI * 2, s = Math.sqrt(1 - u * u);
    const k = folds ? 1 + 0.06 * Math.sin(folds * u * Math.PI) : 1;
    out.push(cx + s * Math.cos(phi) * rx * k, cy + u * ry * k, cz + s * Math.sin(phi) * rz * k);
  }
  return out;
}
function stemPoints(count) {
  const r = rand(11), out = [];
  for (let i = 0; i < count; i++) {
    const t = r(), a = r() * Math.PI * 2, rad = 0.15 - 0.05 * t;
    out.push(Math.cos(a) * rad, -0.55 - t * 0.85, -0.5 + t * 0.12 + Math.sin(a) * rad * 0.8);
  }
  return out;
}
function hippoCurve(side) {  // a bent tube on each side, inside the brain: the "seahorse"
  return new THREE.CatmullRomCurve3([
    new THREE.Vector3(side * 0.42, -0.3, 0.22), new THREE.Vector3(side * 0.47, -0.26, -0.05),
    new THREE.Vector3(side * 0.42, -0.15, -0.32), new THREE.Vector3(side * 0.3, 0.0, -0.45),
  ]);
}
function tubePoints(curve, count, seed) {
  const r = rand(seed), out = [];
  for (let i = 0; i < count; i++) {
    const p = curve.getPoint(r()), a = r() * Math.PI * 2, d = 0.05 * Math.sqrt(r());
    out.push(p.x + Math.cos(a) * d, p.y + Math.sin(a) * d, p.z + (r() - 0.5) * 0.04);
  }
  return out;
}

function glowTexture() {
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const g = c.getContext("2d"), grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grad.addColorStop(0, "rgba(255,255,255,1)");
  grad.addColorStop(0.35, "rgba(255,255,255,.55)");
  grad.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = grad;
  g.fillRect(0, 0, 64, 64);
  return new THREE.CanvasTexture(c);
}

// ---------- the view ----------

/**
 * root: element to draw into. options.get(path) -> Promise (the backend, relative to /api/ext/brain),
 * options.on(type, fn) -> listens to dashboard events, options.onSelect(page, text) when a point is clicked,
 * options.onStatus(map regionId -> text) when the state line of a part changes.
 */
export function mountBrain(root, { get, on, onSelect = () => {}, onStatus = () => {} }) {
  const started = Date.now() / 1000;
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setClearColor(0x060a14);
  root.classList.add("brain-stage");
  root.append(renderer.domElement);
  const tip = document.createElement("div");
  tip.className = "brain-tip";
  tip.hidden = true;
  root.append(tip);

  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0x060a14, 3.2, 6);
  const camera = new THREE.PerspectiveCamera(40, 1, 0.05, 20);
  const brain = new THREE.Group();
  scene.add(brain);
  const sprite = glowTexture();

  // --- the parts as glowing point clouds ---
  const parts = {};
  const addCloud = (id, positions, size, base = 0.6) => {
    const region = REGIONS.find((r) => r.id === id);
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
    const material = new THREE.PointsMaterial({ color: region.color, size, map: sprite, transparent: true,
      depthWrite: false, blending: THREE.AdditiveBlending, opacity: base, sizeAttenuation: true });
    const points = new THREE.Points(geometry, material);
    brain.add(points);
    parts[id] = { ...region, points, base, size, level: 0, active: false, beat: 0, status: "" };
  };
  const { cortex, visual } = cortexPoints(4200);
  addCloud("cortex", cortex, 0.045, 0.5);
  addCloud("visual", visual, 0.05, 0.6);
  addCloud("cerebellum", ellipsoidPoints(650, [0, -0.5, -0.82], [0.5, 0.24, 0.3], 5, 9), 0.035);
  addCloud("brainstem", stemPoints(260), 0.04);
  const hippo = [hippoCurve(1), hippoCurve(-1)];
  addCloud("hippocampus", [...tubePoints(hippo[0], 170, 3), ...tubePoints(hippo[1], 170, 4)], 0.04, 0.6);
  addCloud("amygdala", [...ellipsoidPoints(70, [0.42, -0.3, 0.32], [0.06, 0.06, 0.06], 8),
    ...ellipsoidPoints(70, [-0.42, -0.3, 0.32], [0.06, 0.06, 0.06], 9)], 0.04, 0.5);
  parts.memory = { ...REGIONS.find((r) => r.id === "memory"), level: 0, status: "" };
  parts.sleep = { ...REGIONS.find((r) => r.id === "sleep"), level: 0, status: "Awake" };

  // --- the wires between parts ---
  const wireCurves = {};
  for (const [a, b] of WIRES) {
    const p = new THREE.Vector3(...ANCHOR[a]), q = new THREE.Vector3(...ANCHOR[b]);
    const mid = p.clone().add(q).multiplyScalar(0.5).multiplyScalar(0.6);
    const curve = new THREE.QuadraticBezierCurve3(p, mid, q);
    wireCurves[`${a}>${b}`] = curve;
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(curve.getPoints(30)),
      new THREE.LineBasicMaterial({ color: 0x5f86b8, transparent: true, opacity: 0.16, blending: THREE.AdditiveBlending }));
    brain.add(line);
  }
  const sparks = [];
  const sparkGeometry = new THREE.SphereGeometry(0.022, 10, 10);
  function spark(from, to, color, delay = 0) {
    const forward = wireCurves[`${from}>${to}`], backward = wireCurves[`${to}>${from}`];
    const curve = forward || backward;
    if (!curve) return;
    const mesh = new THREE.Mesh(sparkGeometry, new THREE.MeshBasicMaterial({ color, transparent: true,
      blending: THREE.AdditiveBlending, depthWrite: false }));
    mesh.visible = false;
    brain.add(mesh);
    sparks.push({ mesh, curve, reverse: !forward, t: -delay, speed: 1.3 });
  }

  // --- the second brain: pages as points, links as lines ---
  const nodeGroup = new THREE.Group(), linkGroup = new THREE.Group();
  brain.add(nodeGroup, linkGroup);
  const nodeGeometry = new THREE.SphereGeometry(1, 14, 14);
  let nodes = new Map();  // id -> {page, mesh, pos, flash}
  let graph = { pages: [], links: [], alarms: 0 };

  function layout(pages, links) {
    const wiki = pages.filter((p) => p.kind === "wiki"), raw = pages.filter((p) => p.kind === "raw");
    const pos = new Map();
    for (const p of wiki) {  // start each wiki page at a fixed random spot in the middle of the brain
      const r = rand(hash(p.id));
      pos.set(p.id, new THREE.Vector3((r() - 0.5) * 0.7, 0.12 + (r() - 0.5) * 0.5, (r() - 0.5) * 0.8));
    }
    const wikiLinks = links.filter(([a, b]) => pos.has(a) && pos.has(b));
    for (let step = 0; step < 220; step++) {  // a small force layout, like Obsidian's graph
      const force = new Map(wiki.map((p) => [p.id, new THREE.Vector3()]));
      for (let i = 0; i < wiki.length; i++) {
        for (let j = i + 1; j < wiki.length; j++) {
          const a = pos.get(wiki[i].id), b = pos.get(wiki[j].id), d = a.clone().sub(b);
          const len = Math.max(d.length(), 0.05), push = d.multiplyScalar(0.0022 / (len * len * len));
          force.get(wiki[i].id).add(push);
          force.get(wiki[j].id).sub(push);
        }
      }
      for (const [a, b] of wikiLinks) {
        const d = pos.get(b).clone().sub(pos.get(a)), pull = d.multiplyScalar(0.03 * (d.length() - 0.22));
        force.get(a).add(pull);
        force.get(b).sub(pull);
      }
      for (const p of wiki) {
        const v = pos.get(p.id), home = new THREE.Vector3(0, 0.12, 0.05);
        force.get(p.id).add(home.sub(v).multiplyScalar(0.02));
        v.add(force.get(p.id).clampLength(0, 0.05));
        v.set(Math.max(-0.5, Math.min(0.5, v.x)), Math.max(-0.2, Math.min(0.55, v.y)), Math.max(-0.6, Math.min(0.65, v.z)));
      }
    }
    raw.forEach((p, i) => {  // new memories sit along the two hippocampus tubes
      const side = i % 2, t = ((i >> 1) * 0.618 + 0.1) % 1;
      pos.set(p.id, hippo[side].getPoint(0.08 + t * 0.84));
    });
    return pos;
  }

  function buildGraph(next) {
    const previous = nodes;
    nodeGroup.clear();
    linkGroup.clear();
    nodes = new Map();
    const pos = layout(next.pages, next.links);
    const changed = [];
    for (const page of next.pages) {
      const color = page.kind === "wiki" ? parts.memory.color : parts.hippocampus.color;
      const mesh = new THREE.Mesh(nodeGeometry, new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.9,
        blending: THREE.AdditiveBlending, depthWrite: false }));
      const scale = page.kind === "wiki" ? (page.group ? 0.022 : 0.028) : 0.018;
      mesh.scale.setScalar(scale);
      mesh.position.copy(pos.get(page.id));
      mesh.userData.id = page.id;
      nodeGroup.add(mesh);
      const old = previous.get(page.id);
      const flash = old && old.page.mtime !== page.mtime || (!old && previous.size) ? 1 : 0;
      if (flash) changed.push(page);
      nodes.set(page.id, { page, mesh, scale, flash });
    }
    const segments = [];
    for (const [a, b] of next.links) {
      if (pos.has(a) && pos.has(b)) segments.push(pos.get(a), pos.get(b));
    }
    const links = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(segments),
      new THREE.LineBasicMaterial({ color: 0xffe9a8, transparent: true, opacity: 0.22, blending: THREE.AdditiveBlending,
        depthWrite: false }));
    linkGroup.add(links);
    return changed;
  }

  async function refresh() {
    let next;
    try { next = await get("/graph"); } catch { return; }
    const changed = buildGraph(next);
    const wiki = next.pages.filter((p) => p.kind === "wiki").length, raw = next.pages.length - wiki;
    parts.memory.status = `${wiki} pages, ${next.links.filter(([a]) => a.startsWith("wiki/")).length} links between them`;
    parts.hippocampus.status = `${raw} raw files`;
    if (changed.some((p) => p.kind === "raw")) pulse("hippocampus");
    if (changed.some((p) => p.kind === "wiki")) {
      pulse("memory");
      spark("hippocampus", "memory", parts.memory.color);
      parts.memory.status += ` · just changed: ${changed.filter((p) => p.kind === "wiki").map((p) => p.title).join(", ")}`;
    }
    if (next.alarms > graph.alarms && graph.pages.length) {
      pulse("amygdala");
      spark("brainstem", "amygdala", parts.amygdala.color);
    }
    parts.amygdala.status = next.alarms ? `${next.alarms} Test Suite cases failed a safety check` : "No safety failures";
    graph = next;
    report();
  }

  // --- live activity from the dashboard's events ---
  const pulse = (id, amount = 1) => { parts[id].level = Math.min(1.4, parts[id].level + amount); };
  const report = () => onStatus(Object.fromEntries(Object.values(parts).map((p) => [p.id, p.status])));
  let calls = 0, refreshTimer = null;
  const refreshSoon = (ms) => { clearTimeout(refreshTimer); refreshTimer = setTimeout(refresh, ms); };
  const live = (fn) => (data, message) => { if (!message || !message.t || message.t >= started - 1) fn(data || {}); };
  parts.cortex.status = "Waiting for a task";
  parts.cerebellum.status = "Waiting for a plan";
  parts.brainstem.status = "Waiting for the simulation";
  parts.visual.status = "Waiting for frames";

  const offs = [
    on("run.started", live((d) => {
      calls = 0;
      parts.cortex.active = true;
      parts.cortex.status = `Working on "${d.task || "a task"}"`;
      pulse("cortex", 0.6);
      report();
    })),
    on("run.reply", live((d) => {
      calls += 1;
      pulse("cortex");
      spark("visual", "cortex", parts.visual.color);
      spark("cortex", "cerebellum", parts.cortex.color, 0.35);
      spark("cerebellum", "brainstem", parts.cerebellum.color, 0.8);
      setTimeout(() => pulse("cerebellum"), 350);
      parts.cortex.status = `${calls} Dream-1 calls in this run` + (d.rtt_s ? `, last answer in ${d.rtt_s.toFixed(2)} s` : "");
      parts.cerebellum.status = `Blending plan ${calls} into the arm motion`;
      report();
    })),
    on("run.ended", live((d) => {
      parts.cortex.active = false;
      const outcome = d.result && d.result.success === true ? "success" : d.result && d.result.success === false ? "no success" : "ended";
      parts.cortex.status = calls ? `Last run: ${outcome}, ${calls} Dream-1 calls` : "Last run used no Dream-1 calls (offline)";
      parts.cerebellum.status = "Waiting for a plan";
      pulse("hippocampus");
      spark("brainstem", "hippocampus", parts.hippocampus.color);
      parts.hippocampus.status = "A run ended: looking for new memories in brain/raw/";
      report();
      refreshSoon(2500);
    })),
    on("sim.state", live(() => {
      const now = performance.now();
      parts.brainstem.beat = now;
      parts.visual.beat = now;
    })),
    on("episode.exported", live((d) => {
      parts.sleep.status = `Moving the "${d.task || ""}" episodes into the export ${d.name || ""}`;
      parts.sleep.level = 1.4;
      for (let i = 0; i < 4; i++) {
        spark("hippocampus", "memory", parts.sleep.color, i * 0.5);
        spark("memory", "cortex", parts.sleep.color, 0.9 + i * 0.5);
      }
      report();
      refreshSoon(2000);
    })),
    on("ext.test_suite.trial", live(() => refreshSoon(1500))),
    on("ext.test_suite.ended", live(() => refreshSoon(1500))),
    on("ext.robustness.progress", live(() => refreshSoon(3000))),
  ];

  // --- mouse: drag to turn, wheel to zoom, hover and click the points ---
  let yaw = 0.6, pitch = 0.18, distance = 2.9, dragging = null, idleSince = 0, hovered = null;
  const el = renderer.domElement, ray = new THREE.Raycaster(), mouse = new THREE.Vector2();
  el.addEventListener("pointerdown", (e) => { dragging = { x: e.clientX, y: e.clientY, moved: 0 }; el.setPointerCapture(e.pointerId); });
  el.addEventListener("pointerup", (e) => {
    if (dragging && dragging.moved < 4 && hovered) select(hovered);
    dragging = null;
    idleSince = performance.now();
  });
  el.addEventListener("pointermove", (e) => {
    const box = el.getBoundingClientRect();
    mouse.set(((e.clientX - box.left) / box.width) * 2 - 1, -((e.clientY - box.top) / box.height) * 2 + 1);
    if (dragging) {
      const dx = e.clientX - dragging.x, dy = e.clientY - dragging.y;
      dragging.moved += Math.abs(dx) + Math.abs(dy);
      dragging.x = e.clientX; dragging.y = e.clientY;
      yaw -= dx * 0.008;
      pitch = Math.max(-1.2, Math.min(1.2, pitch + dy * 0.006));
    }
    ray.setFromCamera(mouse, camera);
    const hit = ray.intersectObjects(nodeGroup.children, false)[0];
    hovered = hit ? hit.object.userData.id : null;
    el.style.cursor = hovered ? "pointer" : dragging ? "grabbing" : "grab";
    if (hovered) {
      const node = nodes.get(hovered);
      tip.textContent = `${node.page.title} · ${node.page.id}`;
      tip.style.left = `${e.clientX - box.left + 12}px`;
      tip.style.top = `${e.clientY - box.top + 12}px`;
    }
    tip.hidden = !hovered;
  });
  el.addEventListener("pointerleave", () => { tip.hidden = true; hovered = null; });
  el.addEventListener("wheel", (e) => {
    e.preventDefault();
    distance = Math.max(1.6, Math.min(6, distance * (e.deltaY > 0 ? 1.08 : 0.92)));
  }, { passive: false });

  let selected = null;
  async function select(id) {
    const node = nodes.get(id);
    if (!node) return;
    selected = id;
    let text = "";
    try { text = (await get(`/page?path=${encodeURIComponent(id)}`)).text; } catch (error) { text = error.message; }
    onSelect(node.page, text);
  }

  // --- drawing loop ---
  const resize = () => {
    const w = root.clientWidth || 300, hgt = root.clientHeight || 300;
    renderer.setSize(w, hgt, false);
    camera.aspect = w / hgt;
    camera.updateProjectionMatrix();
  };
  const observer = new ResizeObserver(resize);
  observer.observe(root);
  resize();

  let frame = 0, last = performance.now(), stopped = false;
  function tick(now) {
    if (stopped) return;
    frame = requestAnimationFrame(tick);
    if (document.hidden || !root.offsetParent) return;  // not visible: do not spend time drawing
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    if (!dragging && now - idleSince > 2500) yaw += dt * 0.12;  // turns slowly by itself
    camera.position.set(Math.sin(yaw) * Math.cos(pitch) * distance, Math.sin(pitch) * distance + 0.05,
      Math.cos(yaw) * Math.cos(pitch) * distance);
    camera.lookAt(0, -0.2, -0.1);

    for (const part of Object.values(parts)) {
      part.level *= Math.exp(-dt * 1.6);  // a flash fades out in about two seconds
      if (!part.points) continue;
      let glow = part.level;
      if (part.active) glow = Math.max(glow, 0.35 + 0.15 * Math.sin(now / 300));
      if (part.beat && now - part.beat < 2000) {  // simulation alive: a heartbeat
        glow = Math.max(glow, part.id === "brainstem" ? 0.25 + 0.25 * Math.max(0, Math.sin(now / 160)) ** 8 : 0.2);
      }
      part.points.material.opacity = Math.min(1, part.base + glow * 0.6);
      part.points.material.size = part.size * (1 + glow * 0.6);
    }
    const alive = parts.brainstem.beat && now - parts.brainstem.beat < 2000;
    const stem = alive ? "Running" : parts.brainstem.beat ? "Stopped: no frames for 2 s" : "Waiting for the simulation";
    if (stem !== parts.brainstem.status) {
      parts.brainstem.status = stem;
      parts.visual.status = alive ? "Cameras streaming" : "No frames";
      report();
    }
    const memoryGlow = parts.memory.level + parts.sleep.level * 0.5;
    for (const node of nodes.values()) {
      node.flash *= Math.exp(-dt * 0.7);
      const grow = 1 + node.flash * 1.5 + (node.page.kind === "wiki" ? memoryGlow * 0.3 : parts.hippocampus.level * 0.4);
      node.mesh.scale.setScalar(node.scale * grow * (node.page.id === selected || node.page.id === hovered ? 1.6 : 1));
    }
    if (linkGroup.children[0]) linkGroup.children[0].material.opacity = 0.18 + memoryGlow * 0.3;
    if (parts.sleep.level < 0.05 && parts.sleep.status !== "Awake") { parts.sleep.status = "Awake"; report(); }

    for (let i = sparks.length - 1; i >= 0; i--) {
      const s = sparks[i];
      s.t += dt * s.speed;
      if (s.t >= 1) { brain.remove(s.mesh); s.mesh.material.dispose(); sparks.splice(i, 1); continue; }
      s.mesh.visible = s.t >= 0;
      if (s.t >= 0) s.mesh.position.copy(s.curve.getPoint(s.reverse ? 1 - s.t : s.t));
    }
    renderer.render(scene, camera);
  }
  frame = requestAnimationFrame(tick);
  refresh();
  report();

  return {
    refresh,
    open: select,  // open a page by id, e.g. "wiki/tasks/apple-into-the-bowl.md"
    highlight: (id) => pulse(id, 0.8),
    destroy() {
      stopped = true;
      cancelAnimationFrame(frame);
      observer.disconnect();
      for (const off of offs) if (typeof off === "function") off();
      renderer.dispose();
    },
  };
}

/** The whole Brain tool: the 3D stage, the list of parts with their live state, and the page reader. */
export function mountBrainUI(root, { get, on, full = false }) {
  root.classList.add("brain-ui", full ? "brain-full" : "brain-compact");
  const stage = document.createElement("div");
  const side = document.createElement("div");
  side.className = "brain-side";
  const legend = document.createElement("ul");
  legend.className = "brain-legend";
  const reader = document.createElement("section");
  reader.className = "brain-reader";
  reader.innerHTML = '<p class="brain-hint">Click a point to read its page. Yellow points: the wiki (long-term memory). '
    + "Pink points: brain/raw/ (new memories). Drag to turn, wheel to zoom.</p>";
  side.append(legend, reader);
  root.append(stage, side);

  const rows = {};
  for (const region of REGIONS) {
    const li = document.createElement("li");
    const dot = document.createElement("i");
    dot.style.background = `#${region.color.toString(16).padStart(6, "0")}`;
    const name = document.createElement("strong");
    name.textContent = region.name;
    const stands = document.createElement("span");
    stands.className = "brain-stands";
    stands.textContent = region.stands;
    const state = document.createElement("span");
    state.className = "brain-state";
    li.append(dot, name, stands, state);
    li.addEventListener("mouseenter", () => view.highlight(region.id));
    legend.append(li);
    rows[region.id] = state;
  }

  const view = mountBrain(stage, {
    get, on,
    onStatus: (states) => { for (const [id, text] of Object.entries(states)) if (rows[id]) rows[id].textContent = text || ""; },
    onSelect: (page, text) => {
      const head = document.createElement("div");
      head.className = "brain-reader-head";
      const title = document.createElement("strong");
      title.textContent = page.title;
      const path = document.createElement("code");
      path.textContent = `brain/${page.id}`;
      head.append(title, path);
      reader.replaceChildren(head, renderMarkdown(text, (id) => view.open(id)));
      reader.scrollIntoView({ block: "nearest" });
    },
  });
  return view;
}

/** Very small Markdown to HTML for the page reader: headings, lists, tables, [[links]], bold, code. Text is escaped. */
export function renderMarkdown(text, onLink) {
  const box = document.createElement("div");
  box.className = "brain-md";
  const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const inline = (s) => esc(s)
    .replace(/\[\[([^\]|]+)\|([^\]]+)\]\]/g, '<a href="#" data-page="$1">$2</a>')
    .replace(/\[\[([^\]]+)\]\]/g, '<a href="#" data-page="$1">$1</a>')
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
  const html = [];
  let list = false, table = false;
  const close = () => { if (list) html.push("</ul>"); if (table) html.push("</table>"); list = table = false; };
  for (const line of text.split("\n")) {
    if (line.startsWith("<!--")) continue;
    const head = line.match(/^(#{1,4})\s+(.*)/);
    if (head) { close(); html.push(`<h${Math.min(6, head[1].length + 2)}>${inline(head[2])}</h${Math.min(6, head[1].length + 2)}>`); continue; }
    if (/^\s*[-*]\s+/.test(line)) { if (!list) { close(); html.push("<ul>"); list = true; } html.push(`<li>${inline(line.replace(/^\s*[-*]\s+/, ""))}</li>`); continue; }
    if (line.trim().startsWith("|")) {
      if (/^\s*\|[\s\-:|]+\|\s*$/.test(line)) continue;
      if (!table) { close(); html.push("<table>"); table = true; }
      html.push(`<tr>${line.trim().replace(/^\||\|$/g, "").split("|").map((c) => `<td>${inline(c.trim())}</td>`).join("")}</tr>`);
      continue;
    }
    close();
    if (line.trim()) html.push(`<p>${inline(line)}</p>`);
  }
  close();
  box.innerHTML = html.join("");
  box.addEventListener("click", (e) => {
    const a = e.target.closest("a[data-page]");
    if (!a) return;
    e.preventDefault();
    onLink(`wiki/${a.dataset.page}.md`);
  });
  return box;
}
