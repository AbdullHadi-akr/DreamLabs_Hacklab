# Extensions schreiben

Jede Funktion des Dashboards, die über „Task starten und zuschauen“ hinausgeht, ist eine **Extension**: ein Ordner in
`dashboard/extensions/`. Das Dashboard findet sie beim Start automatisch, es muss nichts registriert werden.

```
dashboard/extensions/mein_tool/
├── __init__.py   Backend (Python): Klasse, die von Extension erbt
├── panel.js      Frontend (optional): export function mount(root, api)
└── panel.css     optional, wird automatisch geladen
```

**Schnellstart:** `_template/` kopieren, den Ordner ohne `_` benennen, Dashboard neu starten. Der Tab erscheint links.

## Architektur in einem Bild

```
Browser ── HTTP /api/... ──────────► FastAPI (app.py) ── Extension.router() unter /api/ext/<id>/
   ▲   ◄── MJPEG /stream/*.mjpg ───┐        │
   │                               │        ▼
   └── WebSocket /ws (Events) ◄── EventBus ◄── SimWorker-Thread (simulation.py)
                                              besitzt env + Renderer, führt Läufe aus,
                                              ruft Extension.run_hooks() / decorate() auf
```

**Wichtigste Regel:** Nur der Sim-Thread darf `env` anfassen (MuJoCo und OpenGL sind nicht thread-sicher).
Aus einem HTTP-Handler oder eigenen Thread immer über `ctx.sim` gehen:

| Aufruf | Was passiert |
| --- | --- |
| `ctx.sim.call(lambda env: ...)` | Funktion läuft auf dem Sim-Thread (zwischen Läufen), gibt ein `Future` zurück |
| `ctx.sim.run_task(task, ...)` | Lauf einreihen, gibt `Future[RunResult]` zurück (Optionen unten) |
| `ctx.sim.stop()` / `ctx.sim.cancel_queued(ctx.id)` | aktuellen Lauf stoppen / eigene wartende Läufe verwerfen |
| `ctx.sim.busy`, `ctx.sim.status()` | läuft gerade etwas? |
| `ctx.sim.state_snapshot` | letzter Zustand: Zeit, Gelenke, Objekt-Positionen |

`run_task`-Optionen: `model`, `seconds`, `offline` (ohne API), `targets` (offline: Liste oder `env -> Liste` von
`(left, right)`), `setup` / `teardown` (`env -> None`, laufen auf dem Sim-Thread vor/nach dem Lauf),
`hooks` (nur für diesen Lauf), `stop_on_success`, `label`, `source`.

## Backend: `Extension`

```python
from fastapi import APIRouter
from dashboard.extension import Extension, overlay_sphere
from dreamtool.runner import Hooks

class MeinTool(Extension):
    title = "Mein Tool"
    icon = "🛡️"
    slot = "left"          # "left" = Tab links, "right" = Karte rechts
    order = 50

    def setup(self): ...                       # einmal beim Start

    def router(self):                          # HTTP-API unter /api/ext/mein_tool/
        r = APIRouter()
        @r.post("/start")
        def start(body: dict): ...
        return r

    def run_hooks(self, run):                  # für JEDEN Lauf (auch die anderer Extensions)
        return MeinHook(self)                  # oder None

    def decorate(self, env, scene):            # vor jedem Frame der 3D-Ansicht
        overlay_sphere(scene, env.data.body("apple").xpos, radius=0.02)

class MeinHook(Hooks):
    def on_start(self, env, task, model): ...
    def on_reply(self, env, reply, rtt_s): ...   # Action-Chunk: reply["q_l_chunk"], reply["q_r_chunk"] je [H, 7]
    def on_step(self, env, step, images): ...    # alle 50 ms; images = top/left/right RGB
    def on_wait(self, env): ...                  # während auf Dream-1 gewartet wird
    def should_stop(self, env): return None      # String zurückgeben -> Lauf endet mit diesem Grund
    def on_end(self, env, result): ...           # RunResult: success, stop_reason, steps, rtts_s ...
```

Weitere Helfer im Kontext: `self.ctx.emit("event", data)` (ans Panel), `self.ctx.log("Text")` (ins Log),
`self.ctx.data_dir` (Ergebnis-Ordner `out/extensions/<id>/`). Fehler in Hooks, `decorate` oder beim Laden werden
abgefangen und geloggt, eine kaputte Extension legt das Dashboard nicht lahm.

## Frontend: `panel.js`

Plain ES-Module, kein Build-Schritt. Nach dem Speichern genügt ein Browser-Reload (Backend-Änderungen brauchen einen
Neustart des Servers).

```js
export async function mount(root, api) {
  const { h } = api.ui;                                  // h(tag, attrs, ...children)
  const out = h("pre");
  root.append(h("button", { class: "btn", onclick: () => api.post("/start", {}) }, "Start"), out);

  api.on("progress", (d) => (out.textContent = JSON.stringify(d)));   // ctx.emit("progress", ...)
  api.onCore("run.ended", (d) => console.log(d.result));             // Core-Events
}
```

| `api.` | |
| --- | --- |
| `get(path)`, `post(path, body)`, `del(path)` | eigenes Backend unter `/api/ext/<id>` |
| `on(event, fn)` | eigene Events (`ctx.emit`) |
| `onCore(type, fn)` | `sim.state` (10 Hz), `run.queued`, `run.started`, `run.reply`, `run.ended`, `run.cancelled`, `log` |
| `core.run(task, {offline, seconds, model})`, `core.stop()`, `core.reset()`, `core.home()` | Steuerung |
| `core.sim()`, `core.task()` | letzter Sim-Zustand, Text im Task-Feld |
| `ui.h(...)`, `ui.toast(text, "good" \| "error")` | UI-Helfer |

Fertige CSS-Klassen aus `static/style.css`: `btn`, `btn primary`, `btn danger`, `btn small`, `field`, `row`, `check`,
`muted`, `table`, `bar`, `progress`, `good`, `bad`, `warn`.

## Beispiele im Repo

- `scene_inspector/`: Live-Werte aus `sim.state`, `decorate()`-Overlay, `ctx.sim.call()` für Debug-Aktionen, Run-Hook.
- `robustness/`: Hintergrund-Thread, der viele Läufe mit `setup`/`teardown` einreiht. Neue Störungen sind eine
  Funktion mit `@perturbation(...)` in `perturbations.py`.
- `_template/`: Minimalbeispiel zum Kopieren.
