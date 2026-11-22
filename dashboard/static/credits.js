// Credits: the amount left in the top bar, the Credits panel (balance, today, month, chart, prices, limits,
// model and time limit), the estimate and confirm step before a run, and the cost of the running run.
import { h, request } from "./lib/api.js";

const $ = (id) => document.getElementById(id);
const usd = (v, digits = 2) => (v === null || v === undefined ? "-" : `$${Number(v).toFixed(digits)}`);
let refreshPanel = () => {};
let prices = {};

export function priceOf(model) {
  return prices[model] ?? null;
}

async function refreshTop() {
  try {
    const s = await request("GET", "/api/credits");
    prices = Object.fromEntries(s.models.map((m) => [m.id, m.price_usd]));
    const el = $("credit-left");
    el.textContent = `${usd(s.balance_usd)} left`;
    const out = s.month_left_usd <= 0 || s.balance_usd <= 0;
    el.classList.toggle("bad", out);
    el.hidden = !out;  // only when the money or the monthly limit is used up; Credits is in the Tools menu
    el.title = `Spent this month ${usd(s.spent_month_usd, 4)} of ${usd(s.monthly_limit_usd)}. Open Credits.`;
    return s;
  } catch { return null; }
}

// Before a run: estimate, refuse over the limit, ask for a second click above "confirm above".
let pending = null;
let buttonLabel = null;  // the Run button's own text and tooltip, restored after the confirm step
export async function gateRun(core, body) {
  const button = $("btn-run");
  buttonLabel ??= { text: button.textContent, title: button.title };
  const restore = () => { pending = null; button.textContent = buttonLabel.text; button.title = buttonLabel.title; };
  const est = await request("GET", `/api/credits/estimate?model=${encodeURIComponent(body.model)}&seconds=${body.seconds}`);
  if (est.refusal) { core.toast(est.refusal, "error", 8000); return false; }
  if (!est.needs_confirm) return true;
  const key = `${body.task}|${body.model}|${body.seconds}`;
  if (pending && pending.key === key && Date.now() - pending.time < 10000) {
    restore(); return true;
  }
  pending = { key, time: Date.now() };
  button.textContent = `Run: about ${usd(est.usd, 2)}?`;
  button.title = `About ${est.calls} calls (${est.basis}). At most ${usd(est.most_usd, 2)}. Click again within 10 seconds to start.`;
  core.toast(`This run costs about ${usd(est.usd, 2)} (at most ${usd(est.most_usd, 2)}). Click Run again to start.`, "info", 6000);
  setTimeout(() => { if (pending && pending.key === key) restore(); }, 10000);
  return false;
}

function drawDays(canvas, days) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, hgt = canvas.clientHeight;
  canvas.width = w * dpr; canvas.height = hgt * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  const css = getComputedStyle(document.documentElement);
  const color = (n) => css.getPropertyValue(n).trim();
  ctx.font = `11px ${color("--font-sans") || "sans-serif"}`;
  ctx.fillStyle = color("--text-3");
  if (!days.length) { ctx.fillText("No spending in the last 30 days", 4, hgt / 2); return; }
  const max = Math.max(...days.map((d) => d.usd), 0.0001);
  const bw = Math.max(3, Math.min(18, (w - 8) / days.length - 3));
  days.forEach((d, i) => {
    const bh = (d.usd / max) * (hgt - 18);
    ctx.fillStyle = color("--text-2");
    ctx.fillRect(4 + i * (bw + 3), hgt - 14 - bh, bw, bh);
  });
  ctx.fillStyle = color("--text-3");
  ctx.fillText(days[0].day.slice(5), 4, hgt - 2);
  ctx.textAlign = "right";
  ctx.fillText(`${days.at(-1).day.slice(5)}  max ${usd(max, 4)}`, w - 2, hgt - 2);
}

export function setupCredits(core) {
  $("credit-left").onclick = (e) => { e.preventDefault(); if (core.activate) core.activate("credits"); };
  refreshTop();
  core.events.on("run.ended", () => { refreshTop(); refreshPanel(); });
}

export function creditsPanel(root, core, action, settingsFields) {
  const body = h("div", {});
  const fields = {
    start_balance_usd: h("input", { type: "number", min: "0", step: "1" }),
    monthly_limit_usd: h("input", { type: "number", min: "0", step: "1" }),
    confirm_above_usd: h("input", { type: "number", min: "0", step: "0.01" }),
  };
  const save = h("button", { type: "button", class: "btn small btn-outline" }, "Save limits");
  save.onclick = async () => {
    const values = Object.fromEntries(Object.entries(fields).map(([k, el]) => [k, Number(el.value)]));
    if (await action(request("POST", "/api/credits/settings", values), "Saved.")) { refreshTop(); refreshPanel(); }
  };
  const canvas = h("canvas", { class: "cr-chart", height: "90" });
  root.append(
    body,
    h("h4", {}, "Spending per day, last 30 days"), canvas,
    ...(settingsFields.length ? [h("h4", {}, "Model and time limit"), ...settingsFields] : []),
    h("h4", {}, "Limits"),
    h("label", { class: "field" }, h("span", {}, "Starting balance in US dollars"), fields.start_balance_usd),
    h("label", { class: "field" }, h("span", {}, "Monthly limit in US dollars: runs stop when it is reached"), fields.monthly_limit_usd),
    h("label", { class: "field" }, h("span", {}, "Ask before a run that costs more than (US dollars)"), fields.confirm_above_usd),
    save,
    h("p", { class: "muted" }, "The Dream Labs API does not report the balance. The dashboard counts calls times the "
      + "price. Runs made outside this dashboard are not counted: correct the starting balance when needed."),
  );

  const render = (s) => {
    for (const [k, el] of Object.entries(fields)) if (document.activeElement !== el) el.value = s[k];
    const share = s.monthly_limit_usd ? Math.min(1, s.spent_month_usd / s.monthly_limit_usd) : 1;
    const last = s.last_run;
    body.replaceChildren(...[
      h("div", { class: "cr-big" }, h("span", { class: "muted" }, "Balance"), h("b", {}, usd(s.balance_usd))),
      h("dl", { class: "kv" },
        h("dt", {}, "Today"), h("dd", {}, usd(s.spent_today_usd, 4)),
        h("dt", {}, "This month"), h("dd", {}, `${usd(s.spent_month_usd, 4)} of ${usd(s.monthly_limit_usd)}`),
        h("dt", {}, "Last run"), h("dd", {}, last ? `${usd(last.cost_usd, 4)}, ${last.calls} calls, ${last.task}` : "-"),
        h("dt", {}, "All counted"), h("dd", {}, usd(s.spent_total_usd, 4))),
      h("div", { class: "cr-bar" }, h("i", { style: { width: `${share * 100}%` }, class: share >= 1 ? "full" : "" })),
      h("h4", {}, "Price per Dream-1 call"),
      h("dl", { class: "kv" }, ...s.models.flatMap((m) => [h("dt", {}, m.id.replace("dreamlabs/", "")), h("dd", {}, usd(m.price_usd, 4))])),
      s.unpriced_runs ? h("p", { class: "muted" }, `${s.unpriced_runs} runs with ${s.unpriced_calls} calls used a model without a known price; they are not counted.`) : null,
    ].filter(Boolean));
    drawDays(canvas, s.days);
  };

  let timer = null;
  refreshPanel = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => { const s = await refreshTop(); if (s) render(s); }, 200);
  };
  refreshPanel();
}
