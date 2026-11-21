// TEMPLATE for an extension's browser panel.
// mount(root, api) is called once. root = your <div>, api = see dashboard/static/lib/api.js:
//   api.get(path) / api.post(path, body)   -> your backend under /api/ext/<id>
//   api.on("event", fn)                    -> events from ctx.emit("event", data)
//   api.onCore("sim.state" | "run.started" | "run.reply" | "run.ended" | "log", fn)
//   api.core.run(task, {offline, seconds, model}), api.core.stop(), api.core.sim(), api.core.task()
//   api.ui.h(tag, attrs, ...children), api.ui.toast(text, "good"|"error")

export async function mount(root, api) {
  const { h } = api.ui;
  const counter = h("strong", {}, "0");
  const last = h("p", { class: "muted" }, "No run yet.");

  root.append(
    h("p", {}, "This is the template. Edit ", h("code", {}, `extensions/${api.id}/panel.js`), "."),
    h("div", { class: "row" },
      h("button", { class: "btn", onclick: async () => {
        const r = await api.post("/click");
        counter.textContent = r.clicks;
      } }, "Count click"),
      h("span", {}, "Clicks: ", counter),
    ),
    last,
  );

  const hello = await api.get("/hello");
  counter.textContent = hello.clicks;
  api.on("run_done", (d) => (last.textContent = `Last run: ${d.steps} steps, success: ${d.success}`));
}
