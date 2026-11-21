// Scene panel: live positions (from sim.state), success-zone overlay, object placement to test success detection.

export async function mount(root, api) {
  const { h } = api.ui;
  const info = await api.get("/info");

  const tbody = h("tbody");
  const rows = {};
  for (const name of [...info.objects, ...info.containers]) {
    const cells = [h("td", { class: "num" }), h("td", { class: "num" }), h("td", { class: "num" })];
    rows[name] = cells;
    tbody.append(h("tr", {}, h("td", {}, name), ...cells));
  }

  const zones = h("input", { type: "checkbox", checked: info.zones, onchange: () => api.post("/zones", { show: zones.checked }) });
  const objSel = h("select", {}, info.objects.map((o) => h("option", { value: o }, o)));
  const contSel = h("select", {}, info.containers.map((c) => h("option", { value: c }, c)));
  const summary = h("p", { class: "muted" }, "After a run, this shows how high the target object was lifted.");

  root.append(
    h("label", { class: "check" }, zones, "Show success zones + target in the 3D view"),
    h("table", { class: "table" },
      h("thead", {}, h("tr", {}, h("th", {}, "Object"), h("th", {}, "x"), h("th", {}, "y"), h("th", {}, "z"))),
      tbody),
    h("h4", {}, "Debug: place object"),
    h("p", { class: "muted" }, "Tests success detection without Dream-1 (no credits)."),
    h("div", { class: "row" }, objSel, "→", contSel,
      h("button", { class: "btn small", onclick: async () => {
        try {
          await api.post("/place", { object: objSel.value, container: contSel.value });
          api.ui.toast(`${objSel.value} is now on the ${contSel.value}`, "good");
        } catch (e) { api.ui.toast(e.message, "error"); }
      } }, "Place")),
    summary,
  );

  api.onCore("sim.state", (s) => {
    for (const [name, pos] of Object.entries(s.objects)) {
      const cells = rows[name];
      if (cells) pos.forEach((v, i) => (cells[i].textContent = v.toFixed(3)));
    }
  });
  api.on("run_summary", (d) => (summary.textContent = `Last run: ${d.object} lifted up to ${d.max_lift_cm} cm.`));

  // Use the prompt field's task as the target for the overlay
  const task = document.getElementById("task");
  const sync = () => api.post("/target", { task: task.value });
  task.addEventListener("change", sync);
  sync();
}
