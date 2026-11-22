// All robustness runs: robustness map (heatmap over every sweep), run list, downloads.
// /ext/robustness/runs.html?task=...&policy=...&metric=rate|progress

import { h, request } from "/static/lib/api.js";
import { downloadButtons, pct, rampLegend, robustnessMap } from "./charts.js";

const root = document.getElementById("runs");
const API = "/api/ext/robustness";
const params = new URLSearchParams(location.search);
const state = { task: params.get("task"), policy: params.get("policy"), metric: params.get("metric") || "rate" };
let catalog = null;

const query = (extra = {}) => {
  const q = new URLSearchParams();
  if (state.task) q.set("task", state.task);
  if (state.policy) q.set("policy", state.policy);
  for (const [k, v] of Object.entries(extra)) q.set(k, v);
  const text = q.toString();
  return text ? `?${text}` : "";
};

async function load() {
  catalog = await request("GET", `${API}/runs`);
  // Defaults: the newest run's policy and task, so dry runs and Dream-1 are never pooled by accident.
  const newest = catalog.runs[0];
  if (state.policy === null) state.policy = newest ? newest.policy : "";
  if (state.task === null) state.task = newest ? newest.task : "";
  await render();
}

function select(label, value, options, onchange) {
  const el = h("select", {}, options.map(([v, text]) => h("option", { value: v, selected: v === value }, text)));
  el.onchange = () => onchange(el.value);
  return h("label", {}, label, el);
}

function syncUrl() {
  const q = new URLSearchParams();
  q.set("task", state.task);
  q.set("policy", state.policy);
  q.set("metric", state.metric);
  history.replaceState(null, "", `?${q}`);
}

async function render() {
  syncUrl();
  const [{ runs }, map] = await Promise.all([
    request("GET", `${API}/runs${query()}`),
    state.policy ? request("GET", `${API}/map${query()}`) : Promise.resolve(null),
  ]);

  const filters = h("div", { class: "rp-filters" },
    select("Task", state.task, [["", "All tasks"], ...catalog.tasks.map((t) => [t, t])], (v) => { state.task = v; render(); }),
    select("Policy", state.policy, [["", "All policies"], ...catalog.policies.map((p) => [p, p === "dry run" ? "Dry run (scripted replay)" : p])],
      (v) => { state.policy = v; render(); }),
    h("label", {}, "Color by", h("div", { class: "rp-seg" },
      ["rate", "progress"].map((m) => h("button", { class: state.metric === m ? "on" : "", onclick: () => { state.metric = m; render(); } },
        m === "rate" ? "Success rate" : "Progress score")))));

  const newestReport = (row) => {
    const id = row.campaigns[row.campaigns.length - 1];
    if (id) location.href = `report.html?id=${encodeURIComponent(id)}`;
  };
  const tested = map ? map.rows.filter((r) => r.campaigns.length).length : 0;
  const mapCard = h("section", { class: "card rp-section" },
    h("div", { class: "rp-section-head" },
      h("h2", {}, "Robustness map"),
      h("span", { class: "muted" }, map ? `${tested} of ${map.rows.length} perturbations tested` : "")),
    !state.policy
      ? h("p", { class: "rp-note" }, "Pick one policy to see the map. Pooling dry runs with Dream-1 would mix two different robots' behaviour.")
      : h("div", {},
        h("p", { class: "rp-note" }, "Every sweep and breaking-point search for this task and policy, pooled. Columns: strength as a share of each perturbation's " +
          "maximum (e.g. ≤ 50 % of 8 cm = up to 4 cm). Dark = robust, light = fails. Hover a cell for details, click it for the newest report." +
          (map.excluded_random ? ` ${map.excluded_random} random-mix run(s) are not included: they change several things at once.` : "")),
        h("div", { class: "rp-heat-wrap" }, robustnessMap(map, { metric: state.metric, onCell: newestReport })),
        rampLegend(state.metric === "rate" ? "Success rate" : "Progress score")));

  const table = h("table", { class: "rp-runs" },
    h("thead", {}, h("tr", {}, ["Started", "Test", "Task", "Policy", "Trials", "Success", "Verdict", "Files"].map((t) => h("th", {}, t)))),
    h("tbody", {}, runs.map((r) => h("tr", {},
      h("td", { class: "num" }, r.started ? new Date(r.started * 1000).toLocaleString([], { dateStyle: "short", timeStyle: "short" }) : r.id),
      h("td", {}, h("a", { href: `report.html?id=${encodeURIComponent(r.id)}` }, r.label),
        h("div", { class: "muted" }, r.mode === "random" ? `random: ${r.factors.join(", ")}` : r.mode === "adaptive" ? "breaking-point search" : r.mode === "compare" ? "inference strategy comparison" : "sweep")),
      h("td", {}, r.task),
      h("td", {}, h("span", { class: `rp-tag ${r.dry_run ? "" : "live"}` }, r.dry_run ? "dry run" : r.policy)),
      h("td", { class: "num" }, `${r.done}/${r.total}`, r.state !== "done" ? h("div", { class: "muted" }, r.state) : null),
      h("td", { class: "num" }, r.scored ? `${r.successes}/${r.scored}` : "–", h("div", { class: "muted" }, `progress ${pct(r.progress)}`)),
      h("td", { class: "rp-verdict-cell" }, r.verdict),
      h("td", {}, downloadButtons(r.id), h("div", { class: "muted" }, `${r.videos} video${r.videos === 1 ? "" : "s"} · ${(r.bytes / 1e6).toFixed(1)} MB`)),
    ))));

  root.replaceChildren(
    h("header", { class: "rp-head" },
      h("div", {},
        h("h1", {}, "Robustness runs"),
        h("div", { class: "rp-meta" }, h("span", {}, h("b", {}, catalog.runs.length), " runs stored in ", h("code", {}, "out/extensions/robustness/")))),
      h("div", { class: "rp-head-actions" },
        h("a", { class: "btn small btn-outline", href: `${API}/download/all-trials.csv${query()}`, download: "",
          title: "Every trial of the filtered runs, one row each" }, "All trials (CSV)"),
        h("a", { class: "btn small btn-outline", href: `${API}/download/all-trials.csv${query({ excel: "true" })}`, download: "",
          title: "Semicolons and decimal commas for German Excel" }, "Excel CSV"),
        h("a", { class: "btn small btn-outline", href: "/" }, "Dashboard"))),
    filters,
    mapCard,
    h("section", { class: "card rp-section" },
      h("div", { class: "rp-section-head" }, h("h2", {}, "Runs"), h("span", { class: "muted" }, `${runs.length} shown`)),
      runs.length ? h("div", { class: "rp-scroll" }, table) : h("p", { class: "muted" }, "No runs for this filter.")),
  );
}

load().catch((e) => root.replaceChildren(h("p", { class: "bad" }, `Could not load the runs: ${e.message}`)));
