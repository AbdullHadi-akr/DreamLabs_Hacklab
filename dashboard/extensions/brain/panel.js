// The "Brain" tool in the left column: a small 3D brain, its parts with their live state, and a page reader.
// The same view fills a whole page at /ext/brain/brain.html (button "Open full page").

import { mountBrainUI } from "./brainview.js";

export function mount(root, api) {
  const { h } = api.ui;
  root.append(h("p", { class: "brain-open" },
    h("a", { class: "btn btn-outline btn-sm", href: api.asset("brain.html"), target: "_blank", rel: "noopener" }, "Open full page")));
  const host = h("div");
  root.append(host);
  mountBrainUI(host, { get: (path) => api.get(path), on: (type, fn) => api.onCore(type, fn) });
}
