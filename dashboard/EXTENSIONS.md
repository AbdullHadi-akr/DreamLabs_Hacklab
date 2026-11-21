# Writing extensions

Every dashboard feature beyond "start a task and watch" is an **extension**: a folder in `dashboard/extensions/`.
The dashboard discovers it automatically on startup; nothing needs to be registered.

```
dashboard/extensions/my_tool/
├── __init__.py   backend (Python): a class that inherits from Extension
├── panel.js      frontend (optional): export function mount(root, api)
└── panel.css     optional, loaded automatically
```

**Quick start:** copy `_template/`, name the folder without the leading `_`, restart the dashboard. The tab appears
on the left.

## Architecture at a glance

```
Browser ── HTTP /api/... ──────────► FastAPI (app.py) ── Extension.router() under /api/ext/<id>/
   ▲   ◄── MJPEG /stream/*.mjpg ───┐        │
   │                               │        ▼
   └── WebSocket /ws (events) ◄── EventBus ◄── SimWorker thread (simulation.py)
                                              owns env + renderers, executes runs,
                                              calls Extension.run_hooks() / decorate()
```

**Most important rule:** only the sim thread may touch `env` (MuJoCo and OpenGL are not thread-safe).
From an HTTP handler or your own thread, always go through `ctx.sim`:

| Call | What happens |
| --- | --- |
| `ctx.sim.call(lambda env: ...)` | runs the function on the sim thread (between runs), returns a `Future` |
| `ctx.sim.run_task(task, ...)` | queues a run, returns a `Future[RunResult]` (options below) |
| `ctx.sim.stop()` / `ctx.sim.cancel_queued(ctx.id)` | stop the current run / drop your own queued runs |
| `ctx.sim.busy`, `ctx.sim.status()` | is anything running? |
| `ctx.sim.state_snapshot` | latest state: time, joints, object positions |

`run_task` options: `model`, `seconds`, `offline` (no API), `targets` (offline: a list or `env -> list` of
`(left, right)`), `setup` / `teardown` (`env -> None`, run on the sim thread before/after the run),
`hooks` (only for this run), `stop_on_success`, `prompt` (text Dream-1 gets instead of the task; success is still
judged on the task), `realtime` (offline: False = as fast as possible), `label`, `source`.

## Backend: `Extension`

```python
from fastapi import APIRouter
from dashboard.extension import Extension, overlay_sphere
from dreamtool.runner import Hooks

class MyTool(Extension):
    title = "My tool"
    icon = ""
    slot = "left"          # "left" = tab in the left column, "right" = card in the right column
    order = 50

    def setup(self): ...                       # once on startup

    def router(self):                          # HTTP API under /api/ext/my_tool/
        r = APIRouter()
        @r.post("/start")
        def start(body: dict): ...
        return r

    def run_hooks(self, run):                  # for EVERY run (including other extensions' runs)
        return MyHook(self)                    # or None

    def decorate(self, env, scene):            # before every frame of the 3D view
        overlay_sphere(scene, env.data.body("apple").xpos, radius=0.02)

class MyHook(Hooks):
    def on_start(self, env, task, model): ...
    def on_reply(self, env, reply, rtt_s): ...   # action chunk: reply["q_l_chunk"], reply["q_r_chunk"], each [H, 7]
    def on_step(self, env, step, images): ...    # every 50 ms; images = top/left/right RGB
    def on_wait(self, env): ...                  # while waiting for Dream-1
    def should_stop(self, env): return None      # return a string -> the run ends with that reason
    def on_end(self, env, result): ...           # RunResult: success, stop_reason, steps, rtts_s ...
```

More helpers on the context: `self.ctx.emit("event", data)` (to the panel), `self.ctx.log("text")` (to the log),
`self.ctx.data_dir` (results folder `out/extensions/<id>/`). Errors in hooks, in `decorate` or while loading are
caught and logged; a broken extension does not take the dashboard down.

## Frontend: `panel.js`

Plain ES modules, no build step. After saving, a browser reload is enough (backend changes need a server restart).

```js
export async function mount(root, api) {
  const { h } = api.ui;                                  // h(tag, attrs, ...children)
  const out = h("pre");
  root.append(h("button", { class: "btn", onclick: () => api.post("/start", {}) }, "Start"), out);

  api.on("progress", (d) => (out.textContent = JSON.stringify(d)));   // ctx.emit("progress", ...)
  api.onCore("run.ended", (d) => console.log(d.result));             // core events
}
```

| `api.` | |
| --- | --- |
| `get(path)`, `post(path, body)`, `del(path)` | your own backend under `/api/ext/<id>` |
| `on(event, fn)` | your own events (`ctx.emit`) |
| `onCore(type, fn)` | `sim.state` (10 Hz), `run.queued`, `run.started`, `run.reply`, `run.ended`, `run.cancelled`, `log` |
| `core.run(task, {offline, seconds, model})`, `core.stop()`, `core.reset()`, `core.home()` | control |
| `core.sim()`, `core.task()` | latest sim state, text in the prompt field |
| `ui.h(...)`, `ui.toast(text, "good" \| "error")` | UI helpers |

Ready-made CSS classes from `static/style.css`: `btn`, `btn primary`, `btn danger`, `btn small`, `btn-outline`,
`field`, `row`, `check`, `muted`, `table`, `bar`, `progress`, `good`, `bad`, `warn`.

## Examples in the repo

- `scene_inspector/`: live values from `sim.state`, a `decorate()` overlay, `ctx.sim.call()` for debug actions, a run hook.
- `robustness/`: a background thread that queues many runs with run hooks and a `teardown`, plus a standalone report
  page (`report.html`). A new perturbation is one function decorated with `@perturbation(...)` in `perturbations.py`.
- `_template/`: minimal example to copy.
