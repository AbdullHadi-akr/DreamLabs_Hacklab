import { h } from "./api.js";

const levels = { info: "Info", warn: "Warning", error: "Error" };

export function logPanel(title, state = {}, { clear = false } = {}) {
  const count = h("summary");
  const rows = h("ol", {class: "log"});
  const empty = h("p", {class: "muted", hidden: true}, "No events for this filter.");
  const filter = h("select", {"aria-label": `${title} severity`},
    h("option", {value: "all"}, "All levels"),
    Object.entries(levels).map(([value, name]) => h("option", {value}, name)));
  const feedback = h("span", {role: "status", class: "muted"});
  const panel = h("details", {class: "log-panel", open: state.open}, count);
  let entries = [];
  filter.value = state.level || "all";
  const copy = h("button", {type: "button", class: "link", onclick: async () => {
    try {
      await navigator.clipboard.writeText(entries.filter(matches).map((event) =>
        [time(event), levels[event.level], event.source, event.message].filter(Boolean).join(" · ")).join("\n"));
      feedback.textContent = "Copied";
    } catch {
      feedback.textContent = "Clipboard unavailable";
    }
  }}, "Copy");
  const clearButton = clear && h("button", {type: "button", class: "link", onclick: () => update([])}, "Clear");
  panel.append(h("div", {class: "log-controls"}, filter, copy, ...(clearButton ? [clearButton] : []), feedback), rows, empty);
  panel.addEventListener("toggle", () => {
    state.open = panel.open;
    if (panel.open) render();
  });
  filter.addEventListener("change", () => { state.level = filter.value; render(); });
  const time = (event) => event.at ? new Date(event.at * 1000).toLocaleTimeString() : "";
  const matches = (event) => filter.value === "all" || event.level === filter.value;
  function render() {
    const visible = entries.filter(matches);
    empty.hidden = visible.length > 0;
    rows.hidden = visible.length === 0;
    rows.replaceChildren(...visible.map((event) => h("li", {class: event.level},
      time(event) && h("time", {}, time(event)), h("span", {class: "src"}, levels[event.level] || "Info"),
      event.source && h("span", {class: "src"}, event.source), event.message)));
    rows.scrollTop = rows.scrollHeight;
  }
  function update(next) {
    entries = next.map((event) => typeof event === "string" ? {message: event, level: "info"} : event)
      .filter((event) => typeof event?.message === "string" && event.message.trim());
    const warnings = entries.filter((event) => event.level === "warn" || event.level === "error").length;
    count.textContent = `${title} · ${entries.length} events${warnings ? ` · ${warnings} warnings/errors` : ""}`;
    if (panel.open) render();
  }
  update([]);
  return { panel, update, append(event) { update([...entries.slice(-399), event]); } };
}
