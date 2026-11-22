import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { Script } from "node:vm";

const source = await readFile(new URL("../dashboard/static/lib/viewer-overlay.js", import.meta.url), "utf8");
const test = `
(async () => {
  const center = [.23, .64];
  for (const [width, height] of [[1100, 450], [360, 720], [478.5, 268.75]]) {
    const rect = {left: 47.25, top: 115, width, height};
    const box = containedImage(rect, 960, 540);
    const [x, y] = toPixels(box, center);
    const [u, v] = toImage(box, x + rect.left, y + rect.top);
    assert(Math.hypot(u - center[0], v - center[1]) < 1e-10);
    if (box.y > 0) assert(!onImage(toImage(box, x + rect.left, rect.top)));
    if (box.x > 0) assert(!onImage(toImage(box, rect.left, y + rect.top)));
  }
  const img = { alt: "Simulation", after() {}, removeAttribute() { delete this.src; } };
  const canvas = {setAttribute() {}, getBoundingClientRect: () => ({width: 360, height: 720}),
    getContext: () => ({drawImage(bitmap) { seen.push(["paint", bitmap.id]); }})};
  document.createElement = () => canvas;
  const viewer = {querySelector: () => img};
  const view = overlayViewer(viewer);
  const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
  viewport.intersect([{isIntersecting: true}]);
  view.onFrame("teleop", (state) => seen.push(["overlay", state.id, view.frame("teleop")]));
  view.onFrame("objects", (state) => seen.push(["overlay", state.id, view.frame("objects")]));
  view.activate("teleop", true);
  await flush();
  assert.equal(view.frame("teleop"), null);
  view.activate("objects", true);
  await flush();
  decode[0]({id: 7, close() {}});
  decode[1]({id: 8, width: 960, height: 540, close() {}});
  await flush();
  assert.equal(JSON.stringify(seen), JSON.stringify([["paint", 8], ["overlay", 8, 8]]));
  assert.equal(view.frame("teleop"), null);
  view.activate("objects", false);
  assert(img.src.startsWith("/stream/main.mjpg"));
  viewport.intersect([{isIntersecting: false}]);
  assert.equal(img.src, undefined);
})();`;

const seen = [], decode = [];
const viewport = {};
let responses = 0;
await new Script(source.replaceAll(/^export /gm, "") + test).runInNewContext({
  assert, seen, decode, viewport, document: {addEventListener() {}}, AbortController, setTimeout,
  IntersectionObserver: class { constructor(callback) { viewport.intersect = callback; } observe() {} },
  ResizeObserver: class { observe() {} },
  createImageBitmap: () => new Promise((resolve) => decode.push(resolve)),
  fetch: () => {
    const id = ++responses + 6;
    if (id > 8) return new Promise(() => {});
    return Promise.resolve({ok: true, status: 200, blob: async () => ({}),
      headers: {get: (key) => key === "X-View-Frame" ? String(id) : JSON.stringify({id})}});
  },
});
console.log("Overlay frame ordering and letterboxed pointer mapping passed");

const app = await readFile(new URL("../dashboard/static/app.js", import.meta.url), "utf8");
const handlers = {}, messages = [];
new Script(app.slice(app.indexOf("function setupViewer("), app.indexOf("function setupCameras(")) +
  "setupViewer({distance: 1})").runInNewContext({
  $: () => ({addEventListener: (event, callback) => { handlers[event] = callback; }}),
  overlayViewer() {}, requestAnimationFrame: (callback) => callback(),
  core: {events: {send: (message) => messages.push(message)}},
});
let prevented = 0;
const wheel = {deltaY: 10, preventDefault() { prevented++; }};
handlers.wheel(wheel);
handlers.wheel({...wheel, altKey: true, ctrlKey: true});
assert.equal(prevented, 0);
handlers.wheel({...wheel, altKey: true});
assert.equal(prevented, 1);
assert.equal(messages[0].distance, 1.1);
console.log("Plain scrolling and browser zoom gestures remain native over the viewport");
