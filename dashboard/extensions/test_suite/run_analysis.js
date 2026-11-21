/** Inline run navigation and comparison use the selected campaign's persisted rows. */
export function runSelector(h, runs, initialNumber, describe, onSelect) {
  const panel = h("div", { id: "suite-run-analysis", role: "tabpanel" });
  const cards = runs.map((run) => h("button", {
    type: "button", role: "tab", class: "suite-run-card",
    id: `suite-run-${run.number}`, "aria-controls": panel.id,
    onclick: () => select(run.number),
  }, h("strong", {}, `Run ${run.number}`),
    h("span", {class: "suite-run-outcome", "data-outcome": String(run.task_success)}, describe.outcome(run)),
    h("span", {}, describe.duration(run.task_duration_seconds)),
    h("small", {}, describe.failure(run))));
  const strip = h("div", { class: "suite-run-strip", role: "tablist", "aria-label": "Campaign runs" }, cards);
  let index = -1;
  function select(number, options = {}) {
    const next = runs.findIndex((run) => run.number === number);
    if (next < 0) return;
    if (next !== index) {
      if (index >= 0) {
        cards[index].tabIndex = -1;
        cards[index].setAttribute("aria-selected", "false");
      }
      index = next;
      cards[index].tabIndex = 0;
      cards[index].setAttribute("aria-selected", "true");
      panel.setAttribute("aria-labelledby", cards[index].id);
      panel.replaceChildren(onSelect(runs[index]));
    }
    if (options.focus) cards[index].focus({preventScroll: true});
    if (options.reveal) cards[index].scrollIntoView({block: "nearest", inline: "nearest"});
  }
  for (const card of cards) {
    card.tabIndex = -1;
    card.setAttribute("aria-selected", "false");
    card.addEventListener("keydown", (event) => {
      const keys = {ArrowLeft: Math.max(0, index - 1), ArrowRight: Math.min(runs.length - 1, index + 1),
        Home: 0, End: runs.length - 1};
      if (!(event.key in keys)) return;
      event.preventDefault();
      select(runs[keys[event.key]].number, {focus: true, reveal: true});
    });
  }
  select(runs.find((run) => run.number === initialNumber)?.number ??
    runs.find((run) => run.number === 1)?.number ?? runs[0].number);
  return { panel, strip, select, element: h("section", {class: "suite-run-analysis"},
    h("h3", {}, "Individual run analysis"), strip, panel) };
}

export function runDisplacement(run) {
  const object = run.evaluation_evidence?.object || run.case?.object;
  const a = run.initial_state?.positions_m?.[object];
  const b = run.final_state?.positions_m?.[object];
  return a?.length === 3 && b?.length === 3 && [...a, ...b].every(Number.isFinite)
    ? Math.hypot(...b.map((value, axis) => value - a[axis])) : null;
}

export function snapshotEntries(run, reportPath) {
  const titles = {first: "First recorded frame", contact: "Frame after contact", pickup: "Frame after pickup",
    closest: "Closest approach among recorded frames", final: "Last recorded frame"};
  const order = {first: 0, contact: 1, pickup: 2, closest: 3, final: 4};
  const entries = (run.snapshots || []).filter((frame) => frame.kind in titles && Number.isFinite(frame.simulation_time))
    .sort((a, b) => a.simulation_time - b.simulation_time || order[a.kind] - order[b.kind]);
  if (entries.length) {
    return entries.map((frame) => ({...frame, title: titles[frame.kind], url: `${reportPath}/snapshot/${run.number}/${frame.kind}`}));
  }
  return run.snapshot_available ? [{title: "Last recorded frame", simulation_time: run.snapshot_simulation_time,
    url: `${reportPath}/snapshot/${run.number}`}] : [];
}

export function runComparison(h, runs, describe, state = {}) {
  const unavailable = "Unavailable";
  const list = (name, initial) => {
    const input = h("select", {"aria-label": name},
      runs.map((run) => h("option", {value: run.number}, `Run ${run.number}`)));
    input.value = String(initial);
    return input;
  };
  const a = list("First run", state.a ?? runs[0].number);
  const b = list("Second run", state.b ?? runs[1].number);
  const table = h("div", {class: "suite-table"});
  const metres = (value) => Number.isFinite(value) ? `${(100 * value).toFixed(1)} cm` : unavailable;
  const value = (item) => item ?? unavailable;
  const safety = (run) => [describe.safety(run.safety_status),
    ...Object.entries(run.safety_checks || {}).map(([name, observed]) => `${name} (${describe.safety(observed)})`),
    ...(run.safety_violations || []).map((issue) => issue.reason)].join(" · ");
  const fields = [
    ["Task outcome", describe.outcome], ["Primary failure", describe.failure],
    ["Execution duration", (run) => describe.duration(run.task_duration_seconds)],
    ["API requests", (run) => value(run.api_request_count ?? run.requests)],
    ["Last verified stage", (run) => value(run.last_verified_stage)],
    ["Object displacement", (run) => metres(runDisplacement(run))],
    ["Closest target approach", (run) => metres(run.evaluation_evidence?.best_planar_distance_m)],
    ["Scene parameters", (run) => describe.scene(run)], ["Monitored safety", safety],
  ];
  function update() {
    state.a = Number(a.value);
    state.b = Number(b.value);
    const first = runs.find((run) => run.number === state.a);
    const second = runs.find((run) => run.number === state.b);
    if (!first || !second || first === second) {
      table.replaceChildren(h("p", {}, "Select two different runs."));
      return;
    }
    table.replaceChildren(h("table", {},
      h("thead", {}, h("tr", {}, h("th", {scope: "col"}, "Measure"), h("th", {scope: "col"}, `Run ${first.number}`),
        h("th", {scope: "col"}, `Run ${second.number}`))),
      h("tbody", {}, fields.map(([name, get]) => {
        const left = get(first);
        const right = get(second);
        const differs = left !== right && ![unavailable, "—", "Not evaluated", "Not Evaluated"].some(
          (missing) => left === missing || right === missing);
        return h("tr", {class: differs ? "suite-run-difference" : undefined}, h("th", {scope: "row"}, name),
          h("td", {}, left), h("td", {}, right));
      }))));
  }
  a.addEventListener("change", update);
  b.addEventListener("change", update);
  update();
  return h("details", {open: state.open, ontoggle: (event) => { state.open = event.target.open; }},
    h("summary", {}, "Compare Runs"), h("div", {class: "suite-compare-controls"},
      h("label", {}, "First run", a), h("label", {}, "Second run", b)), table);
}

export function progressChart(h, data) {
  const samples = (data.samples || []).filter(([time, distance]) => Number.isFinite(time) && Number.isFinite(distance));
  const markers = (data.markers || []).filter((marker) => marker.event && Number.isFinite(marker.simulation_time));
  if (!samples.length) return h("p", {}, "No target-distance samples were recorded.");
  const left = 65;
  const right = 685;
  const top = 15;
  const bottom = 155;
  const canvas = h("canvas", {width: 710, height: 188, role: "img",
    "aria-label": "Measured planar object-to-target distance over simulation time"});
  const context = canvas.getContext("2d");
  const start = samples[0][0];
  const end = Math.max(samples.at(-1)[0], ...markers.map((marker) => marker.simulation_time));
  const maxDistance = Math.max(.01, ...samples.map(([, distance]) => distance));
  const x = (time) => left + (right - left) * (time - start) / Math.max(.001, end - start);
  const y = (distance) => bottom - (bottom - top) * distance / maxDistance;
  context.font = "13px system-ui";
  context.strokeStyle = "#b4a89e";
  context.fillStyle = "#514740";
  context.beginPath();
  context.moveTo(left, top);
  context.lineTo(left, bottom);
  context.lineTo(right, bottom);
  context.stroke();
  context.fillText(`${(maxDistance * 100).toFixed(1)} cm`, 4, top + 5);
  context.fillText("0 cm", 10, bottom + 4);
  context.fillText(`${start.toFixed(2)} s`, left, bottom + 20);
  if (end > start) context.fillText(`${end.toFixed(2)} s`, right - 57, bottom + 20);
  context.strokeStyle = "#b86137";
  context.beginPath();
  samples.forEach(([time, distance], index) => {
    if (index) context.lineTo(x(time), y(distance));
    else context.moveTo(x(time), y(distance));
  });
  context.stroke();
  if (samples.length === 1) context.fillRect(x(start) - 2, y(samples[0][1]) - 2, 4, 4);
  for (const marker of markers) {
    context.strokeStyle = "#665b96";
    context.setLineDash([3, 4]);
    context.beginPath();
    context.moveTo(x(marker.simulation_time), top);
    context.lineTo(x(marker.simulation_time), bottom);
    context.stroke();
  }
  return h("div", {}, canvas,
    h("p", {class: "muted"}, "Planar distance in centimeters by simulation time. Dashed lines mark recorded events."),
    markers.length > 0 && h("ul", {}, markers.map((marker) => h("li", {},
      `${marker.simulation_time.toFixed(2)} s · ${marker.event}${marker.termination ? ` · ${marker.termination.replaceAll("_", " ")}` : ""}`))));
}
