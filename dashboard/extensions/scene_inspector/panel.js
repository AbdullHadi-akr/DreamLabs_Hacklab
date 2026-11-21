// Szene-Panel: Live-Positionen (aus sim.state), Zonen-Overlay, Objekt-Platzierung zum Testen der Erfolgserkennung.

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
  const summary = h("p", { class: "muted" }, "Nach einem Lauf steht hier, wie hoch das Ziel-Objekt angehoben wurde.");

  root.append(
    h("label", { class: "check" }, zones, "Erfolgszonen + Ziel in der 3D-Ansicht zeigen"),
    h("table", { class: "table" },
      h("thead", {}, h("tr", {}, h("th", {}, "Objekt"), h("th", {}, "x"), h("th", {}, "y"), h("th", {}, "z"))),
      tbody),
    h("h4", {}, "Debug: Objekt platzieren"),
    h("p", { class: "muted" }, "Testet die Erfolgserkennung ohne Dream-1 (keine Credits)."),
    h("div", { class: "row" }, objSel, "→", contSel,
      h("button", { class: "btn small", onclick: async () => {
        try {
          await api.post("/place", { object: objSel.value, container: contSel.value });
          api.ui.toast(`${objSel.value} liegt jetzt auf ${contSel.value}`, "good");
        } catch (e) { api.ui.toast(e.message, "error"); }
      } }, "Setzen")),
    summary,
  );

  api.onCore("sim.state", (s) => {
    for (const [name, pos] of Object.entries(s.objects)) {
      const cells = rows[name];
      if (cells) pos.forEach((v, i) => (cells[i].textContent = v.toFixed(3)));
    }
  });
  api.on("run_summary", (d) => (summary.textContent = `Letzter Lauf: ${d.object} max. ${d.max_lift_cm} cm angehoben.`));

  // Ziel aus dem Task-Feld fuer das Overlay uebernehmen
  const task = document.getElementById("task");
  const sync = () => api.post("/target", { task: task.value });
  task.addEventListener("change", sync);
  sync();
}
