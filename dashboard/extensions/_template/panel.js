// VORLAGE fuer das Browser-Panel einer Extension.
// mount(root, api) wird einmal aufgerufen. root = dein <div>, api = siehe dashboard/static/lib/api.js:
//   api.get(path) / api.post(path, body)   -> dein Backend unter /api/ext/<id>
//   api.on("event", fn)                    -> Events aus ctx.emit("event", data)
//   api.onCore("sim.state" | "run.started" | "run.reply" | "run.ended" | "log", fn)
//   api.core.run(task, {offline, seconds, model}), api.core.stop(), api.core.sim(), api.core.task()
//   api.ui.h(tag, attrs, ...children), api.ui.toast(text, "good"|"error")

export async function mount(root, api) {
  const { h } = api.ui;
  const counter = h("strong", {}, "0");
  const last = h("p", { class: "muted" }, "Noch kein Lauf.");

  root.append(
    h("p", {}, "Das ist die Vorlage. Bearbeite ", h("code", {}, `extensions/${api.id}/panel.js`), "."),
    h("div", { class: "row" },
      h("button", { class: "btn", onclick: async () => {
        const r = await api.post("/click");
        counter.textContent = r.clicks;
      } }, "Klick zählen"),
      h("span", {}, "Klicks: ", counter),
    ),
    last,
  );

  const hello = await api.get("/hello");
  counter.textContent = hello.clicks;
  api.on("run_done", (d) => (last.textContent = `Letzter Lauf: ${d.steps} Schritte, Erfolg: ${d.success}`));
}
