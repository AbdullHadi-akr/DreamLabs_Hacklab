// Robustness panel: configure a sweep, start/stop it, show the success rate per perturbation strength live.

export async function mount(root, api) {
  const { h } = api.ui;
  const perturbations = await api.get("/perturbations");
  const byId = Object.fromEntries(perturbations.map((p) => [p.id, p]));

  const task = h("input", { value: api.core.task() || "put apple into the bowl" });
  const kind = h("select", {}, perturbations.map((p) => h("option", { value: p.id }, `${p.label} (${p.unit})`)));
  const values = h("input", {});
  const trials = h("input", { type: "number", min: 1, max: 50, value: 3 });
  const seconds = h("input", { type: "number", min: 5, max: 600, value: 45 });
  const dry = h("input", { type: "checkbox", checked: true });
  const desc = h("p", { class: "muted" });
  const estimate = h("p", { class: "muted" });
  const startBtn = h("button", { class: "btn primary", onclick: start }, "Start sweep");
  const stopBtn = h("button", { class: "btn danger", onclick: () => api.post("/stop"), disabled: true }, "Stop");
  const progressBar = h("div", { style: { width: "0%" } });
  const progressText = h("span", { class: "muted" });
  const results = h("div");

  const parseValues = () => values.value.split(/[,;\s]+/).filter(Boolean).map(Number).filter((v) => !Number.isNaN(v));
  const updateKind = () => {
    const p = byId[kind.value];
    values.value = p.defaults.join(", ");
    desc.textContent = p.description;
    updateEstimate();
  };
  const updateEstimate = () => {
    const n = parseValues().length * Number(trials.value || 0);
    estimate.textContent = dry.checked
      ? `${n} trials as a dry run (no API, ~2 s per trial).`
      : `${n} Dream-1 runs of up to ${seconds.value} s each → up to ~${Math.ceil((n * Number(seconds.value)) / 60)} min, uses credits.`;
  };
  kind.onchange = updateKind;
  for (const el of [values, trials, seconds, dry]) el.addEventListener("input", updateEstimate);

  async function start() {
    try {
      const summary = await api.post("/start", {
        task: task.value.trim(), perturbation: kind.value, values: parseValues(),
        trials: Number(trials.value), seconds: Number(seconds.value), dry_run: dry.checked,
      });
      render(summary);
    } catch (e) { api.ui.toast(e.message, "error"); }
  }

  function render(s) {
    if (!s) return;
    const running = s.state === "running";
    startBtn.disabled = running;
    stopBtn.disabled = !running;
    progressBar.style.width = `${(100 * s.done) / s.total}%`;
    progressText.textContent = `${s.done}/${s.total} trials · ${s.state}${s.config.dry_run ? " · dry run" : ""}`;
    results.replaceChildren(
      h("table", { class: "table" },
        h("thead", {}, h("tr", {}, h("th", {}, `${s.label}`), h("th", {}, "Success"), h("th", {}, ""))),
        h("tbody", {}, s.per_value.map((v) => h("tr", {},
          h("td", { class: "num" }, `${v.value} ${s.unit}`),
          h("td", { class: "num" }, v.rate === null ? `– (${v.done})` : `${v.successes}/${v.done}`),
          h("td", { style: { width: "45%" } },
            h("div", { class: "bar" }, h("div", { style: { width: `${(v.rate ?? 0) * 100}%` } }))),
        ))),
      ),
    );
  }

  root.append(
    h("label", { class: "field" }, h("span", {}, "Task"), task),
    h("label", { class: "field" }, h("span", {}, "Perturbation"), kind),
    desc,
    h("label", { class: "field" }, h("span", {}, "Strengths (comma-separated)"), values),
    h("div", { class: "row" },
      h("label", { class: "field" }, h("span", {}, "Trials per strength"), trials),
      h("label", { class: "field" }, h("span", {}, "Seconds per trial"), seconds)),
    h("label", { class: "check" }, dry, "Dry run (no API, no credits)"),
    estimate,
    h("div", { class: "row" }, startBtn, stopBtn),
    h("div", { class: "progress" }, h("div", { class: "bar" }, progressBar), progressText),
    results,
  );

  updateKind();
  render(await api.get("/status"));
  api.on("progress", render);
}
