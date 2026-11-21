// Model X-Ray panel: freeze a moment, then ask Dream-1 about it again (intent, where it looks, language).

const CAMS = [["top", "Overhead"], ["left", "Left wrist"], ["right", "Right wrist"]];
const nice = (name) => (name ? name.replace("water_bottle", "bottle") : "nothing");

export async function mount(root, api) {
  const { h } = api.ui;
  let status = await api.get("/status");
  let selected = status.snapshots[0]?.id || null;
  let detail = null;

  // ---------- live ----------
  const liveText = h("p", { class: "xr-live muted" }, "Start a Dream-1 run: its plan appears here and in the 3D view.");
  const overlay = h("input", { type: "checkbox", checked: status.overlay });
  overlay.onchange = () => api.post("/overlay", { enabled: overlay.checked, snapshot: selected });
  const moments = h("div", { class: "xr-moments" });

  // ---------- snapshot ----------
  const prompt = h("input", { value: api.core.task() || "put the banana on the plate" });
  const freeze = h("button", { class: "btn small", onclick: freezeScene }, "Freeze current scene");
  const list = h("select", { class: "xr-list" });
  list.onchange = () => select(list.value);
  const snapCard = h("div", { class: "xr-snap" });
  const fakeNote = h("p", { class: "warn", hidden: !status.fake },
    "Simulated stand-in instead of Dream-1 (DREAM_XRAY_FAKE=1): numbers show how the tool works, not the model.");

  // ---------- analyses ----------
  const masks = h("input", { type: "number", min: 8, max: 200, value: 40 });
  const repeats = h("input", { type: "number", min: 1, max: 5, value: 2 });
  const buttons = {
    intent: h("button", { class: "btn small", onclick: () => run("intent") }, "Ask Dream-1 (3 calls)"),
    rise: h("button", { class: "btn small", onclick: () => run("rise") }),
    language: h("button", { class: "btn small", onclick: () => run("language") }),
  };
  const out = { intent: h("div", {}), rise: h("div", {}), language: h("div", {}) };
  const progressBar = h("div", { style: { width: "0%" } });
  const progressText = h("span", { class: "muted" });
  const stopBtn = h("button", { class: "btn small danger", hidden: true, onclick: () => api.post("/stop") }, "Stop");
  const updateCounts = () => {
    buttons.rise.textContent = `Run (${Number(masks.value) + 6} calls)`;
    buttons.language.textContent = `Run (${5 * Number(repeats.value)} calls)`;
  };
  masks.oninput = repeats.oninput = updateCounts;
  updateCounts();

  async function freezeScene() {
    freeze.disabled = true;
    try {
      const r = await api.post("/snapshot", { prompt: prompt.value.trim() });
      status = r.status;
      await select(r.id);
      api.ui.toast("Scene frozen.", "good");
    } catch (e) { api.ui.toast(e.message, "error"); }
    freeze.disabled = false;
  }

  async function keepMoment(index) {
    try {
      const r = await api.post(`/moments/${index}/keep`);
      status = r.status;
      await select(r.id);
    } catch (e) { api.ui.toast(e.message, "error"); }
  }

  async function run(kind) {
    if (!selected) return api.ui.toast("Freeze a moment first.", "error");
    const n = kind === "intent" ? 3 : kind === "rise" ? Number(masks.value) + 6 : 5 * Number(repeats.value);
    if (!status.fake && !confirm(`Ask Dream-1 ${n} times about this moment? This uses credits.`)) return;
    try {
      await api.post("/run", { snapshot: selected, kind, masks: Number(masks.value),
        repeats: kind === "language" ? Number(repeats.value) : 0 });
    } catch (e) { api.ui.toast(e.message, "error"); }
  }

  async function select(id) {
    selected = id;
    detail = id ? await api.get(`/snapshots/${id}`).catch(() => null) : null;
    if (overlay.checked) api.post("/overlay", { enabled: true, snapshot: selected });
    render();
  }

  // ---------- rendering ----------
  function renderList() {
    list.replaceChildren(h("option", { value: "" }, status.snapshots.length ? "Frozen moments…" : "No frozen moments yet"),
      ...status.snapshots.map((s) => h("option", { value: s.id, selected: s.id === selected },
        `${s.id.slice(9, 15).replace(/(..)(..)(..)/, "$1:$2:$3")} · ${s.source === "run" ? `run @ ${s.seconds}s` : "scene"} · ${s.prompt}` +
        (s.done.length ? ` · ${s.done.join(", ")}` : ""))));
    moments.replaceChildren(...status.moments.slice().reverse().map((m) => h("div", { class: "xr-moment" },
      h("span", { class: "num" }, `${m.seconds}s`), h("span", { class: "xr-moment-text" }, m.text),
      h("button", { class: "btn small btn-outline", onclick: () => keepMoment(m.index), title: "Freeze this moment for the analyses" }, "Freeze"))));
  }

  function renderSnap() {
    if (!detail) { snapCard.replaceChildren(h("p", { class: "muted" }, "Freeze the current scene or a moment of a run.")); return; }
    snapCard.replaceChildren(
      h("div", { class: "xr-thumbs" }, CAMS.map(([cam, label]) =>
        h("figure", {}, h("img", { src: `data:image/jpeg;base64,${detail.frames[cam]}`, alt: label }), h("figcaption", {}, label)))),
      h("div", { class: "muted" }, `“${detail.prompt}” · ${detail.source === "run" ? `run moment at ${detail.seconds} s` : "frozen scene"}`),
      h("button", { class: "btn small btn-outline xr-del", onclick: async () => {
        if (!confirm("Delete this frozen moment and its results?")) return;
        status = await api.del(`/snapshots/${detail.id}`); selected = status.snapshots[0]?.id || null; await select(selected);
      } }, "Delete"));
  }

  function renderIntent(r) {
    if (!r) return out.intent.replaceChildren();
    const i = r.intent;
    out.intent.replaceChildren(
      h("div", { class: "xr-verdict" }, i.text),
      h("dl", { class: "kv" },
        h("dt", {}, "Heading for"), h("dd", {}, nice(i.target)),
        h("dt", {}, "Acting arm"), h("dd", {}, i.arm),
        h("dt", {}, "Same answer?"), h("dd", {}, r.consistent_target ? `yes, ${r.targets.length}×` : `no: ${r.targets.map(nice).join(", ")}`),
        h("dt", {}, "Noise"), h("dd", { title: "Mean distance between the paths of repeated, identical questions" },
          r.noise_cm == null ? "–" : `${r.noise_cm} cm`),
        ...(r.recorded_change_cm != null ? [h("dt", {}, "Vs. the run"), h("dd", { title: "Re-asked plan vs. the plan Dream-1 sent during the run" }, `${r.recorded_change_cm} cm`)] : [])),
      h("p", { class: "muted" }, "Orange line in the 3D view: the planned path of the acting arm; red dot: where the gripper closes; yellow: the target."));
  }

  function heatCanvas(cam, r) {
    const canvas = h("canvas", { width: 320, height: 176, class: "xr-heat" });
    const ctx = canvas.getContext("2d");
    const img = new Image();
    img.onload = () => {
      ctx.drawImage(img, 0, 0, 320, 176);
      const grid = r.heat[cam], chance = r.chance_cm[cam];
      const peak = Math.max(...Object.values(r.peak_cm), chance + 1e-6);
      const ch = 176 / grid.length, cw = 320 / grid[0].length;
      grid.forEach((row, y) => row.forEach((v, x) => {
        if (v <= chance) { ctx.fillStyle = "rgba(255,255,255,.35)"; ctx.fillRect(x * cw, y * ch, cw, ch); return; }
        const a = Math.min(1, (v - chance) / (peak - chance));
        ctx.fillStyle = `rgba(255, ${Math.round(140 - 90 * a)}, 30, ${0.25 + 0.55 * a})`;
        ctx.fillRect(x * cw, y * ch, cw, ch);
      }));
    };
    img.src = `data:image/jpeg;base64,${detail.frames[cam]}`;
    return canvas;
  }

  function renderRise(r) {
    if (!r || !detail) return out.rise.replaceChildren();
    const maxRel = Math.max(...Object.values(r.reliance).map((x) => x.change_cm), r.noise_cm * 2, 0.1);
    out.rise.replaceChildren(
      h("div", { class: "xr-verdict" }, r.text),
      ...CAMS.map(([cam, label]) => h("figure", { class: "xr-heat-fig" }, heatCanvas(cam, r),
        h("figcaption", {}, h("b", {}, label), ` peak ${r.peak_cm[cam]} cm · chance ${r.chance_cm[cam]} cm`,
          r.looks_at.includes(cam) ? h("span", { class: "good" }, " · above chance") : h("span", { class: "muted" }, " · noise")))),
      h("p", { class: "muted" }, "Coloured cells: hiding them changes the planned path more than chance would (permutation test). " +
        "Washed-out cells: no evidence. Darker orange = stronger."),
      h("h4", {}, "Camera blanked completely"),
      h("div", { class: "xr-bars" }, CAMS.map(([cam, label]) => {
        const x = r.reliance[cam];
        return h("div", { class: "xr-bar" }, h("span", {}, label),
          h("div", { class: "xr-bar-track" }, h("i", { style: { width: `${(100 * (x?.change_cm || 0)) / maxRel}%` } }),
            h("u", { style: { left: `${(100 * r.noise_cm) / maxRel}%` }, title: `noise ${r.noise_cm} cm` })),
          h("span", { class: "num" }, x ? `${x.change_cm} cm` : "–"));
      })),
      h("p", { class: "muted" }, `Line = noise floor (${r.noise_cm} cm): how much the plan varies when nothing is changed. ` +
        `${r.masks} masks, ${r.calls} calls.`));
  }

  function renderLanguage(r) {
    if (!r) return out.language.replaceChildren();
    out.language.replaceChildren(
      h("div", { class: "xr-verdict" }, r.text),
      r.warning ? h("p", { class: "warn" }, r.warning) : null,
      h("table", { class: "table xr-table" },
        h("thead", {}, h("tr", {}, ["Word in the prompt", "Goes for", "Same each time", ""].map((t) => h("th", {}, t)))),
        h("tbody", {}, r.rows.map((row) => h("tr", { title: row.prompt },
          h("td", {}, row.word), h("td", {}, nice(row.mode)),
          h("td", { class: "num" }, `${Math.round(row.agreement * 100)}%`),
          h("td", {}, row.named == null ? h("span", { class: "muted" }, "made up") : row.followed ? h("span", { class: "good" }, "follows") : h("span", { class: "bad" }, "ignores")))))));
  }

  function renderJob(job) {
    const running = job && job.state === "running";
    for (const b of Object.values(buttons)) b.disabled = running || !selected;
    stopBtn.hidden = !running;
    progressBar.style.width = job && job.total ? `${(100 * job.done) / job.total}%` : running ? "5%" : "0%";
    progressText.textContent = job ? `${job.kind} · ${job.state} · ${job.done}/${job.total || "?"} · ${job.calls} calls` +
      (job.state === "error" ? ` · ${job.text}` : "") : "";
  }

  function render() {
    renderList();
    renderSnap();
    const res = detail?.results || {};
    renderIntent(res.intent);
    renderRise(res.rise);
    renderLanguage(res.language);
    renderJob(status.job);
    if (status.live) liveText.textContent = `${status.live.seconds} s: ${status.live.text}`;
  }

  root.append(
    h("p", { class: "muted xr-intro" }, "Why Dream-1 does what it does: freeze one moment, then ask Dream-1 about it again with one thing changed."),
    fakeNote,
    h("h4", {}, "Live"),
    liveText,
    h("label", { class: "check" }, overlay, "Show the planned path in the 3D view"),
    moments,
    h("h4", {}, "Frozen moment"),
    h("label", { class: "field" }, h("span", {}, "Prompt"), prompt),
    h("div", { class: "row" }, freeze),
    list,
    snapCard,
    h("div", { class: "progress" }, h("div", { class: "bar" }, progressBar), progressText, stopBtn),
    h("section", { class: "xr-section" }, h("h4", {}, "1 · Intent"),
      h("p", { class: "muted" }, "Where the gripper goes, where it closes, what it heads for, and how much that varies."),
      buttons.intent, out.intent),
    h("section", { class: "xr-section" }, h("h4", {}, "2 · Where it looks"),
      h("p", { class: "muted" }, "RISE: random masks grey out parts of all three camera windows; the heatmap shows which parts the plan depends on."),
      h("div", { class: "row" }, h("label", { class: "field" }, h("span", {}, "Masks"), masks), buttons.rise), out.rise),
    h("section", { class: "xr-section" }, h("h4", {}, "3 · Does it follow the words?"),
      h("p", { class: "muted" }, "Same images, only the object word in the prompt is swapped (apple, banana, orange, bottle, a made-up word)."),
      h("div", { class: "row" }, h("label", { class: "field" }, h("span", {}, "Asks per word"), repeats), buttons.language), out.language),
  );

  await select(selected);
  api.on("live", (d) => {
    liveText.textContent = `${d.seconds} s: ${d.text}`;
    status.moments = d.moments;
    renderList();
  });
  api.on("job", async (job) => {
    status.job = job;
    renderJob(job);
    if (job.state !== "running") {
      status = await api.get("/status");
      if (job.snapshot === selected) await select(selected); else renderList();
      if (job.state === "error") api.ui.toast(`X-Ray: ${job.text}`, "error");
    }
  });
  api.onCore("run.started", () => { liveText.textContent = "Waiting for Dream-1's first plan…"; });
}
