// Full robustness report page: /ext/robustness/report.html?id=<campaign id>

import { h, request } from "/static/lib/api.js";
import { renderReport } from "./report_view.js";

const root = document.getElementById("report");
const id = new URLSearchParams(location.search).get("id");
let last = null;

async function load() {
  if (!id) {
    location.replace("runs.html");
    return;
  }
  const s = await request("GET", `/api/ext/robustness/results/${encodeURIComponent(id)}`);
  const signature = `${s.state}-${s.done}`;
  if (signature !== last) {
    last = signature;
    renderReport(root, s);
  }
  if (s.state === "running") setTimeout(load, 3000);
}

load().catch((e) => root.replaceChildren(h("p", { class: "bad" }, `Could not load the report: ${e.message}`)));
