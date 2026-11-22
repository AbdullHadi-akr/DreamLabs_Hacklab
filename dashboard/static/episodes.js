// Teaching loop in the page: the Take over / Save / Discard buttons under the view, and the Episodes panel.
// The records come from the lab database on the host laptop (GET /api/episodes).
import { h, request } from "./lib/api.js";

const $ = (id) => document.getElementById(id);
const MODE_TEXT = { dream: "Recording Dream-1", takeover: "Recording you", paused: "Episode paused" };
const verdict = (v) => (v === 1 ? "success" : v === 0 ? "not finished" : "no check");
const usd = (v) => (v === null || v === undefined ? "-" : `$${Number(v).toFixed(4)}`);

let refreshPanel = () => {};

export function setupEpisodes(core, action, initial) {
  const show = (s) => {
    const mode = s && s.mode;
    const takeover = $("btn-takeover");
    // Always visible, so people know it exists; usable only while Dream-1 works or after a failed try.
    const usable = mode === "dream" || mode === "paused";
    takeover.hidden = false;
    takeover.disabled = !usable || Boolean(s && s.take_over_requested);
    takeover.title = usable
      ? "Stop Dream-1 without resetting the scene, then finish the task with Control"
      : "Works while Dream-1 is working, or after Dream-1 failed. Start a run with Run first.";
    takeover.textContent = s && s.take_over_requested ? "Stopping Dream-1" : "Take over";
    $("btn-ep-save").hidden = $("btn-ep-discard").hidden = !(mode === "takeover" || mode === "paused");
    const badge = $("badge-rec");
    badge.hidden = !mode;
    badge.classList.toggle("rec", mode === "dream" || mode === "takeover");
    if (mode) badge.textContent = `${MODE_TEXT[mode]}, ${s.seconds.toFixed(1)} s`;
  };
  show(initial);
  let last = initial && initial.mode;
  core.events.on("episode.state", (s) => {
    show(s);
    if (s.mode !== last) refreshPanel(); // only when the state changes, not every recorded second
    last = s.mode;
  });
  core.events.on("run.ended", () => refreshPanel());

  $("btn-takeover").onclick = async () => {
    const result = await action(request("POST", "/api/episodes/take-over"));
    if (result && core.activate) core.activate("teleop"); // open Control: the person moves the arms from here
  };
  $("btn-ep-save").onclick = async () => {
    const result = await action(request("POST", "/api/episodes/save"));
    if (result && result.episode) {
      core.toast(`Episode ${result.episode.id} saved, ${verdict(result.episode.success)}.`, "good", 3000);
    }
  };
  $("btn-ep-discard").onclick = () => action(request("POST", "/api/episodes/discard"), "Episode discarded.");
}

function table(columns, rows) {
  return h("table", { class: "ep-table" },
    h("thead", {}, h("tr", {}, columns.map(([, title]) => h("th", {}, title)))),
    h("tbody", {}, rows.map((row) => h("tr", {}, columns.map(([key, , format]) =>
      h("td", {}, format ? format(row[key], row) : row[key] ?? "-"))))));
}

export function episodesPanel(root, core, action) {
  const record = h("input", { type: "checkbox" });
  record.onchange = () => action(request("POST", "/api/episodes/record", { enabled: record.checked }));
  const body = h("div", {});
  root.append(
    h("label", { class: "check" }, record, h("span", {}, "Record every Dream-1 run started from the task bar")),
    h("p", { class: "muted" }, "If Dream-1 fails, press Take over under the view, finish the task with Control, "
      + "then press Save episode. The success check marks each episode."),
    body,
  );

  const render = (data) => {
    record.checked = data.status.enabled;
    const s = data.summary;
    const name = h("input", { placeholder: "dataset name, for example banana-plate-1", autocomplete: "off" });
    const task = h("select", {}, s.trainable.map((r) => h("option", { value: r.task }, r.task)));
    const exportButton = h("button", { type: "button", class: "btn small btn-outline" }, "Export");
    exportButton.onclick = async () => {
      const result = await action(request("POST", "/api/episodes/export", { task: task.value, name: name.value.trim() }));
      if (result) {
        const extra = (result.notes || []).join(" ");  // e.g. episodes cut at the take-over, or left out as too short
        core.toast(`Exported ${result.episodes} episodes to ${result.folder}. Dream Labs' check passed. ${extra}`,
          "good", 10000);
        refreshPanel();
      }
    };
    body.replaceChildren(...[
      h("h4", {}, "Ready for a fine-tune"),
      s.trainable.length
        ? table([["task", "Task"], ["episodes", "Episodes"], ["seconds", "Seconds"]], s.trainable)
        : h("p", { class: "muted" }, "No successful episodes yet that an export has not used."),
      s.trainable.length ? h("div", { class: "ep-export" }, task, name, exportButton) : null,
      h("p", { class: "muted" }, "Export copies the episodes into one folder and runs Dream Labs' own dataset check. "
        + "Nothing is uploaded and no credits are spent."),

      h("h4", {}, "Success and cost per model"),
      s.by_model.length
        ? table([["model", "Model", (v) => v.replace("dreamlabs/", "")], ["task", "Task"], ["runs", "Runs"],
          ["successes", "Successes"], ["cost_per_success", "Cost per success", usd]], s.by_model)
        : h("p", { class: "muted" }, "No Dream-1 runs with a success check yet."),
      h("p", { class: "muted" }, `Spent on Dream-1 calls so far: ${usd(s.spent_usd)}, counted as calls times the price.`),

      h("h4", {}, "Where a person took over"),
      s.takeovers.length
        ? table([["task", "Task"], ["episodes", "Episodes"], ["took_over", "Taken over"]], s.takeovers)
        : h("p", { class: "muted" }, "No saved episodes yet."),

      h("h4", {}, "Recent episodes"),
      data.episodes.length
        ? table([["id", "No."], ["task", "Task"], ["seconds", "Seconds"],
          ["took_over", "Finished by", (v) => (v ? "person" : "Dream-1")],
          ["success", "Result", (v) => verdict(v)], ["finetune_id", "Exported", (v) => (v ? "yes" : "")]], data.episodes)
        : h("p", { class: "muted" }, "None yet."),
      h("h4", {}, "Task types the success check understands"),
      table([["example", "Example"], ["description", "Success when"]], data.rules),
      h("p", { class: "muted" }, "Other tasks still run; their success is then unknown. New task types are added in "
        + "dreamtool/scene.py, RULES."),
      data.finetunes.length ? h("h4", {}, "Exports") : null,
      data.finetunes.length
        ? table([["name", "Name"], ["task", "Task"], ["episodes", "Episodes"], ["status", "Status"]], data.finetunes)
        : null,
    ].filter(Boolean)); // replaceChildren would print an empty part as the word "null"
  };

  let timer = null;
  refreshPanel = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      try { render(await request("GET", "/api/episodes")); } catch (error) { body.replaceChildren(h("p", { class: "bad" }, error.message)); }
    }, 300);
  };
  refreshPanel();
}
