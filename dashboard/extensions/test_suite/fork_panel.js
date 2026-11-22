export function forkPanel({h, api, button, base, run}) {
  const point = run.checkpoint;
  if (!point) return h("p", {class: "muted"}, run.checkpoint_unavailable ||
    "No restorable checkpoint. Fork Here supports banana-to-plate Quick Tests using paused full chunks.");
  const path = `${base}/forks/${run.number}`;
  const status = h("p", {role: "status"});
  const results = h("div");
  const actions = h("div", {class: "suite-actions"});
  const section = h("details", {class: "suite-fork"},
    h("summary", {}, "Fork here"),
    h("p", {}, `Checkpoint ${point.id.slice(0, 8)} · ${point.simulation_time.toFixed(2)} s simulation time`),
    h("p", {class: "muted"}, point.scripted
      ? "Scripted offline comparison. Both branches use the real simulator and placement evaluator."
      : "Live comparison. Each branch opens a fresh provider session with the same saved observations. One pair cannot measure reliability."),
    status, actions, results);
  let timer;
  let quote;
  const value = (flag) => flag == null ? "Unavailable" : flag ? "Yes" : "No";
  const when = (time) => time == null ? "Unavailable" : `${time.toFixed(2)} s`;
  const spend = (cost) => cost == null ? "Unavailable" : `$${cost.toFixed(4)}`;

  function render(item) {
    if (!item) {
      results.replaceChildren();
      return;
    }
    const {baseline, guarded} = item.branches;
    results.replaceChildren(
      h("h4", {}, `Comparison ${item.id.slice(0, 8)} · ${item.state}`),
      item.restore_error && h("p", {role: "alert"}, item.restore_error),
      h("p", {}, `Added API requests: ${baseline.requests == null || guarded.requests == null
        ? "Unavailable" : guarded.requests - baseline.requests} · Added estimated cost: ${baseline.cost_usd == null ||
        guarded.cost_usd == null ? "Unavailable" : spend(guarded.cost_usd - baseline.cost_usd)}`),
      h("div", {class: "suite-fork-branches"}, Object.entries(item.branches).map(([name, branch]) => {
        const events = [
          ...(branch.guard_events || []).map((entry) => ({
            ...entry, event: `${entry.decision} · plate region ${value(entry.in_target_region)} · grasp ${entry.grasp_contacts.join(", ") || "none"}`,
          })), ...(branch.evaluation_events || []),
        ].sort((a, b) => a.simulation_time - b.simulation_time);
        return h("article", {class: "suite-detail"}, h("h4", {}, name === "baseline" ? "Baseline" : "Release guard"),
          h("p", {}, `${branch.status.replaceAll("_", " ")} · ${branch.outcome == null ? "Unevaluated" : branch.outcome ? "Success" : "Unsuccessful"}`),
          h("p", {}, `Start verified: ${value(branch.start_verified)} · Simulated time: ${when(branch.sim_seconds)}`),
          h("p", {}, `Target entry: ${value(branch.target_entry)} · Stable placement: ${value(branch.stable_placement)}`),
          h("p", {}, `API requests: ${branch.requests ?? "Unavailable"} · Activations: ${branch.guard_activations ?? "Unavailable"} · Replans: ${branch.replans ?? "Unavailable"}`),
          branch.scripted_chunks != null && h("p", {}, `Scripted chunks: ${branch.scripted_chunks}`),
          branch.reason && h("p", {}, `Termination: ${branch.reason}`),
          events.length > 0 && h("ol", {}, events.map((event) => h("li", {}, `${when(event.simulation_time)} · ${event.event}`))));
      })));
    if (item.state === "running") {
      actions.replaceChildren(button("Stop comparison", async (event) => {
        if (event) event.currentTarget.disabled = true;
        try {
          await api.post(`/forks/${item.id}/stop`);
          status.textContent = "Stopping at the next simulator boundary…";
        } catch (error) { status.textContent = error.message; }
      }));
      timer = window.setTimeout(refresh, 750);
    }
  }

  async function refresh() {
    if (!section.open || !section.isConnected) return;
    try {
      const [item] = await api.get(path);
      actions.replaceChildren();
      render(item);
      if (item?.state === "running") return;
      quote = await api.get(`${path}/quote`);
      status.textContent = `Pair limit: ${quote.api_request_limit} API requests · Estimated maximum ${spend(quote.max_cost_usd)} · Guard: up to one additional replan.`;
      actions.replaceChildren(button("Start comparison", async () => {
        if (!point.scripted && !window.confirm(status.textContent)) return;
        actions.replaceChildren();
        try {
          render(await api.post(path, {confirmed: !point.scripted}));
        } catch (error) { status.textContent = error.message; }
      }));
    } catch (error) { status.textContent = error.message; }
  }
  section.addEventListener("toggle", () => {
    window.clearTimeout(timer);
    if (section.open) refresh();
  });
  return section;
}
