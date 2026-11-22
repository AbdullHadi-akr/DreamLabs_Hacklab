// Run with: node tests/test_tutorial_ui.mjs
// The tutorial's tours (dashboard/static/tutorial.js): every tour is complete, every step points at something the page
// really has, and the step card always stays inside the window.
import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import { Script } from "node:vm";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");
const source = await read("dashboard/static/tutorial.js");
const html = await read("dashboard/static/index.html");

// Everything the page is built from: index.html, the core scripts and every extension's panel scripts.
const extensionIds = (await readdir(new URL("../dashboard/extensions/", import.meta.url), { withFileTypes: true }))
  .filter((entry) => entry.isDirectory() && !entry.name.startsWith("_") && !entry.name.startsWith("__"))
  .map((entry) => entry.name);
const scripts = [html];
for (const file of ["app.js", "credits.js", "episodes.js", "players.js", "lib/log_panel.js"]) {
  scripts.push(await read(`dashboard/static/${file}`));
}
for (const id of extensionIds) {
  for (const file of await readdir(new URL(`../dashboard/extensions/${id}/`, import.meta.url))) {
    if (file.endsWith(".js")) scripts.push(await read(`dashboard/extensions/${id}/${file}`));
  }
}
const page = scripts.join("\n");
const corePanels = ["episodes", "credits", "players"];

const context = { window: { innerWidth: 0, innerHeight: 0 }, result: null };
new Script(source.replace(/^import.*\r?\n/gm, "").replace(/^export /gm, "") +
  "\nresult = { TOURS, place };").runInNewContext(context);
const { TOURS, place } = context.result;

// ---------- the tours ----------

const ids = TOURS.map((tour) => tour.id);
assert.equal(new Set(ids).size, ids.length, "tour ids are unique");
assert(ids.includes("basics"), "the first-visit hint starts the basics tour");
assert(TOURS.some((tour) => tour.guest), "guests get at least one tour");
for (const tour of TOURS) {
  assert(tour.title && tour.summary, `${tour.id}: title and summary`);
  assert(tour.steps.length >= 3 && tour.steps.length <= 10, `${tour.id}: a short tour (3 to 10 steps)`);
  for (const [index, step] of tour.steps.entries()) {
    const where = `${tour.id} step ${index + 1}`;
    assert(typeof step.title === "string" && step.title.length > 0, `${where}: title`);
    assert(typeof step.text === "string" && step.text.length > 20, `${where}: text`);
    assert(!step.before || typeof step.before === "function", `${where}: before is a function`);
    if (!step.target) continue;
    // ids: in index.html (or made by tutorial.js itself); classes: somewhere in the page's sources;
    // panels: an extension folder or a built-in panel
    for (const [, id] of step.target.matchAll(/#([\w-]+)/g)) {
      assert(html.includes(`id="${id}"`), `${where}: #${id} is in index.html`);
    }
    for (const [, name] of step.target.matchAll(/\.([\w-]+)/g)) {
      if (name === "panel") continue;
      assert(page.includes(name), `${where}: .${name} is used by the page`);
    }
    for (const [, id] of step.target.matchAll(/data-id="([\w-]+)"/g)) {
      assert(extensionIds.includes(id) || corePanels.includes(id), `${where}: panel ${id} exists`);
      assert(step.optional, `${where}: a step on an extension's panel is optional (the extension may not load)`);
    }
  }
}
console.log(`${TOURS.length} tours, ${TOURS.reduce((n, t) => n + t.steps.length, 0)} steps: all targets exist`);

// ---------- where the card goes ----------

for (const [width, height] of [[1440, 900], [1024, 768], [375, 812], [320, 480]]) {
  context.window.innerWidth = width;
  context.window.innerHeight = height;
  const card = { offsetWidth: Math.min(360, width - 24), offsetHeight: 190 };
  const targets = [null, // no target: centred
    { left: 0, top: 0, right: width, bottom: height, width, height }, // fills the window
    { left: 40, top: 60, right: 300, bottom: 1400, width: 260, height: 1340 }, // taller than the window
    { left: width - 80, top: 10, right: width - 10, bottom: 40, width: 70, height: 30 }, // a top-bar button
    { left: 20, top: height - 60, right: width - 20, bottom: height - 10, width: width - 40, height: 50 }];
  for (const rect of targets) {
    const { left, top } = place(card, rect);
    const inside = left >= 0 && top >= 0 && left + card.offsetWidth <= width && top + card.offsetHeight <= height;
    assert(inside, `card inside a ${width}x${height} window for ${JSON.stringify(rect)}: ${left}, ${top}`);
  }
}
console.log("The step card stays inside the window at four sizes");
