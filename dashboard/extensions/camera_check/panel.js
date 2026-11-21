// Camera check panel: a light per camera from the frames Dream-1 was really sent, the 9 frames of the last request,
// the fault self-test and the "does Dream-1 use them?" test.

const CAMS = [["top", "Overhead"], ["left", "Left wrist"], ["right", "Right wrist"]];
const LIGHT = { ok: "good", warn: "warn", fail: "bad", unchecked: "muted" };
const WORD = { ok: "OK", warn: "Check", fail: "Problem", unchecked: "Not checked yet" };

export async function mount(root, api) {
  const { h } = api.ui;
  let status = await api.get("/status");

  const cards = h("div", { class: "cc-cards" });
  const strip = h("div", { class: "cc-strip" });
  const stripCam = h("select", {}, CAMS.map(([c, l]) => h("option", { value: c }, l)));
  stripCam.onchange = loadStrip;
  const liveNote = h("p", { class: "muted cc-note" });

  const task = h("input", { value: api.core.task() || "put the banana on the plate" });
  const seconds = h("input", { type: "number", min: 5, max: 60, value: 12 });
  const testBtn = h("button", { class: "btn small", onclick: startSelfTest }, "Run self-test");
  const stopBtn = h("button", { class: "btn small danger", onclick: () => api.post("/stop") }, "Stop");
  const selfOut = h("div", {});
  const useBtn = h("button", { class: "btn small", onclick: startModelUse }, "Ask Dream-1 (7 calls)");
  const useOut = h("div", {});

  function card(cam, label, s, last) {
    const st = s ? s.status : "unchecked";
    const now = last && last.cameras[cam];
    const facts = [];
    if (s && s.lag_ms_median != null) facts.push(`lag ${Math.round(s.lag_ms_median)} ms (max ${Math.round(s.lag_ms_max)})`);
    if (s && s.fps_median) facts.push(`${s.fps_median} new frames/s`);
    if (s && s.score_median != null) facts.push(`match ${s.score_median.toFixed(3)}`);
    const issues = s ? Object.entries(s.issues) : [];
    return h("div", { class: `cc-card ${st}` },
      h("div", { class: "cc-card-head" }, h("b", {}, label), h("span", { class: LIGHT[st] }, WORD[st])),
      h("div", { class: "muted" }, facts.join(" · ") || "Start a Dream-1 run: every request is checked."),
      issues.length ? h("ul", { class: "cc-issues" }, issues.map(([text, n]) => h("li", {}, `${text} (${n} of ${s.checked} requests)`))) : null,
      now && now.issues && now.issues.length ? h("div", { class: "bad cc-now" }, `Last request: ${now.issues.join("; ")}`) : null);
  }

  function renderCards() {
    const src = status.live || status.report;
    const summary = src ? src.summary : null;
    const last = status.live ? status.live.last : null;
    cards.replaceChildren(...CAMS.map(([cam, label]) => card(cam, label, summary && summary[cam], last)));
    liveNote.textContent = status.live ? `${status.live.trips} requests checked in the current run.`
      : status.report ? `Last run: ${status.report.trips} requests, “${status.report.run.task}”.` : "";
  }

  async function loadStrip() {
    try {
      const t = await api.get("/last-trip");
      const cam = t.cameras[stripCam.value];
      strip.replaceChildren(...(cam.frames || []).map((f) => h("figure", { class: `cc-frame ${f.camera && f.camera !== stripCam.value ? "bad" : ""}` },
        f.jpeg ? h("img", { src: `data:image/jpeg;base64,${f.jpeg}`, alt: `frame ${f.index + 1}` }) : h("div", { class: "cc-missing" }, "unreadable"),
        h("figcaption", {}, `#${f.index + 1}`, f.lag_ms != null ? ` · ${f.lag_ms} ms` : "",
          f.camera && f.camera !== stripCam.value ? ` · is ${f.camera}` : "",
          f.transform && f.transform !== "upright" ? ` · ${f.transform}` : ""))));
    } catch { strip.replaceChildren(h("p", { class: "muted" }, "No request seen yet in this session.")); }
  }

  async function startSelfTest() {
    const n = Object.keys(status.faults).length + 1;
    if (!confirm(`Run ${n} short Dream-1 runs (${seconds.value} s each, one clean and one per fault)? This uses credits.`)) return;
    try { status.selftest = await api.post("/selftest", { task: task.value.trim(), seconds: Number(seconds.value) }); renderSelf(); }
    catch (e) { api.ui.toast(e.message, "error"); }
  }

  async function startModelUse() {
    if (!status.fake && !confirm("Ask Dream-1 7 times about the frozen current scene? This uses credits.")) return;
    try { status.model_use = await api.post("/model-use", { prompt: task.value.trim() }); renderUse(); }
    catch (e) { api.ui.toast(e.message, "error"); }
  }

  function renderSelf() {
    const st = status.selftest;
    testBtn.disabled = st && st.state === "running";
    if (!st) return selfOut.replaceChildren();
    selfOut.replaceChildren(
      h("div", { class: `cc-verdict ${st.state === "done" && st.caught === st.of ? "good" : ""}` },
        st.state === "running" ? `Running ${st.rows.length + 1} of ${st.total}: ${st.current ? (status.faults[st.current] || "no fault") : "…"}` : st.text),
      h("table", { class: "table cc-table" },
        h("thead", {}, h("tr", {}, ["Injected", "Found?", "What the check reported"].map((t) => h("th", {}, t)))),
        h("tbody", {}, st.rows.map((r) => h("tr", {},
          h("td", {}, r.label),
          h("td", {}, r.fault === "none" ? h("span", { class: r.clean ? "good" : "warn" }, r.clean ? "clean" : "findings")
            : h("span", { class: r.detected ? "good" : "bad" }, r.detected ? "yes" : "no")),
          h("td", { class: "cc-small" }, Object.entries(r.issues).map(([c, iss]) => `${c}: ${Object.keys(iss).join(", ")}`).join(" · ") || "–"))))));
  }

  function renderUse() {
    const mu = status.model_use;
    useBtn.disabled = mu && mu.state === "running";
    if (!mu) return useOut.replaceChildren();
    if (mu.state === "running") return useOut.replaceChildren(h("p", { class: "muted" }, `Asking… ${mu.done}/${mu.total}`));
    if (mu.state === "error") return useOut.replaceChildren(h("p", { class: "bad" }, mu.text));
    const rows = Object.values(mu.rows);
    const max = Math.max(mu.threshold_cm * 1.5, ...rows.map((r) => r.change_cm), 0.1);
    useOut.replaceChildren(
      h("div", { class: "cc-verdict" }, mu.text),
      h("div", { class: "cc-bars" }, rows.map((r) => h("div", { class: "cc-bar" },
        h("span", {}, r.kind === "blank" ? `${CAMS.find(([c]) => c === r.camera)[1]} blanked` : "Wrists swapped"),
        h("div", { class: "cc-track" }, h("i", { class: r.reacts ? "on" : "", style: { width: `${(100 * r.change_cm) / max}%` } }),
          h("u", { style: { left: `${(100 * mu.threshold_cm) / max}%` } })),
        h("span", { class: "num" }, `${r.change_cm} cm`)))),
      h("p", { class: "muted" }, `Path change of the plan vs. the unchanged moment. Line: ${mu.threshold_cm} cm = 3 × Dream-1's own noise ` +
        `(${mu.noise_cm} cm), at least 1 cm. Unchanged plan: ${mu.base_text}`));
  }

  root.append(...[
    h("p", { class: "muted cc-note" }, "Every frame Dream-1 is sent is compared with what the simulation's cameras really showed at that moment: right camera on the right key, upright, natural colours, current, not frozen."),
    status.fake ? h("p", { class: "warn" }, "DREAM_XRAY_FAKE=1: “Does Dream-1 use them?” asks a scripted stand-in.") : null,
    h("h4", {}, "Live"), cards, liveNote,
    h("div", { class: "row cc-strip-head" }, h("h4", {}, "Frames of the last request"), stripCam), strip,
    h("h4", {}, "Self-test: does the check catch real faults?"),
    h("p", { class: "muted cc-note" }, "A clean Dream-1 run, then one run per fault injected on purpose between the cameras and the model."),
    h("div", { class: "row" }, h("label", { class: "field" }, h("span", {}, "Task"), task),
      h("label", { class: "field cc-sec" }, h("span", {}, "Seconds"), seconds)),
    h("div", { class: "row" }, testBtn, stopBtn), selfOut,
    h("h4", {}, "Does Dream-1 use them?"),
    h("p", { class: "muted cc-note" }, "Freezes the current scene, then blanks each camera once and swaps the wrist cameras: does the planned path change more than Dream-1's own noise?"),
    useBtn, useOut,
  ].filter(Boolean));

  renderCards(); renderSelf(); renderUse(); loadStrip();
  api.on("trip", (t) => { status.live = status.live || { trips: 0, summary: null, last: null }; status.live.trips = t.index; status.live.last = t; });
  let timer = null;
  api.on("trip", () => { clearTimeout(timer); timer = setTimeout(async () => { status = await api.get("/status"); renderCards(); loadStrip(); }, 400); });
  api.on("report", async () => { status = await api.get("/status"); renderCards(); });
  api.on("selftest", (st) => { status.selftest = st; renderSelf(); });
  api.on("model_use", (mu) => { status.model_use = mu; renderUse(); });
}
