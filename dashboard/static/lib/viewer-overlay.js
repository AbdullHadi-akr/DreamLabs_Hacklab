// Interactive tools draw the JPEG and its own overlay state in the same browser paint.
const viewers = new WeakMap();

export function containedImage(rect, width, height) {
  const scale = Math.min(rect.width / width, rect.height / height);
  const w = width * scale, h = height * scale;
  return { rect, w, h, x: (rect.width - w) / 2, y: (rect.height - h) / 2 };
}

export function toPixels(box, [u, v]) {
  return [box.x + u * box.w, box.y + v * box.h];
}

export function toImage(box, clientX, clientY) {
  const clamp = (value) => Math.max(-0.5, Math.min(1.5, value));
  return [clamp((clientX - box.rect.left - box.x) / box.w), clamp((clientY - box.rect.top - box.y) / box.h)];
}

export function onImage([u, v]) { return u >= 0 && u <= 1 && v >= 0 && v <= 1; }

export function overlayViewer(viewer) {
  if (viewers.has(viewer)) return viewers.get(viewer);
  const img = viewer.querySelector("#main-view");
  const canvas = document.createElement("canvas");
  canvas.setAttribute("aria-label", img.alt);
  canvas.setAttribute("role", "img");
  canvas.className = "interactive-view";
  canvas.hidden = true;
  img.after(canvas);
  const context = canvas.getContext("2d");
  const callbacks = new Map();
  let tool = null, controller = null, frame = null, state = null;
  const box = () => containedImage(canvas.getBoundingClientRect(), canvas.width, canvas.height);
  const redraw = () => { if (frame !== null) callbacks.get(tool)?.(state); };
  new ResizeObserver(redraw).observe(canvas);

  async function read(kind, signal) {
    while (!signal.aborted) {
      try {
        const response = await fetch(`/api/view-frame/${kind}?after=${frame ?? -1}`, { signal });
        if (response.status === 204) continue;
        if (!response.ok) throw Error(`Frame unavailable (${response.status})`);
        const bitmap = await createImageBitmap(await response.blob());
        try {
          if (signal.aborted) return;
          const nextState = JSON.parse(response.headers.get("X-View-State"));
          if (canvas.width !== bitmap.width) canvas.width = bitmap.width;
          if (canvas.height !== bitmap.height) canvas.height = bitmap.height;
          context.drawImage(bitmap, 0, 0);
          frame = Number(response.headers.get("X-View-Frame"));
          state = nextState;
          canvas.hidden = false;
          redraw();
        } finally { bitmap.close(); }
      } catch (error) {
        if (signal.aborted) return;
        await new Promise((resolve) => setTimeout(resolve, 250));
      }
    }
  }

  const view = {
    box,
    frame(kind) { return tool === kind ? frame : null; },
    onFrame(kind, callback) { callbacks.set(kind, callback); },
    activate(kind, active) {
      if (active ? tool === kind : tool !== kind) return;
      controller?.abort();
      frame = state = null;
      tool = active ? kind : null;
      canvas.hidden = true;
      img.hidden = active;
      if (active) {
        img.removeAttribute("src");
        controller = new AbortController();
        read(kind, controller.signal);
      } else {
        img.src = "/stream/main.mjpg";
      }
    },
  };
  viewers.set(viewer, view);
  return view;
}
