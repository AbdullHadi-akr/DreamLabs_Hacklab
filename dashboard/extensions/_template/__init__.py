"""VORLAGE fuer eine neue Extension.

1. Ordner kopieren:  dashboard/extensions/_template  ->  dashboard/extensions/mein_tool
   (Ordner mit "_" am Anfang werden nicht geladen, die Kopie ohne "_" schon.)
2. Klasse unten umbenennen, title/icon setzen.
3. Dashboard neu starten (python -m dashboard). Der Tab erscheint links.

Was eine Extension kann (alles optional):
  router()         eigene HTTP-Endpunkte unter /api/ext/<id>/...
  run_hooks(run)   Hooks fuer jeden Lauf: on_start, on_reply, on_step, on_wait, should_stop, on_end
  decorate(env, scene)   3D-Marker in die Hauptansicht zeichnen (overlay_sphere / overlay_disk / overlay_line)
  self.ctx.sim     Simulation: call(fn) -> Future, run_task(task, ...) -> Future[RunResult], stop(), busy
  self.ctx.emit()  Event an das Panel schicken (panel.js: api.on("name", fn))
  self.ctx.log()   Zeile im Log des Dashboards
  self.ctx.data_dir  Ordner fuer Ergebnisse (out/extensions/<id>/)
"""

from fastapi import APIRouter

from dashboard.extension import Extension
from dreamtool.runner import Hooks


class CountSteps(Hooks):
    """Beispiel-Hook: zaehlt Schritte und meldet sie am Ende."""

    def __init__(self, ext):
        self.ext, self.steps = ext, 0

    def on_step(self, env, step, images):
        self.steps = step

    def on_end(self, env, result):
        self.ext.ctx.emit("run_done", {"steps": self.steps, "success": result.success if result else None})


class TemplateExtension(Extension):
    title = "Template"
    icon = "🧩"
    description = "Copy me to start a new extension."

    def setup(self):
        self.clicks = 0

    def router(self):
        r = APIRouter()

        @r.get("/hello")
        def hello():
            return {"message": "Hello from the backend", "clicks": self.clicks}

        @r.post("/click")
        def click():
            self.clicks += 1
            self.ctx.emit("clicked", {"clicks": self.clicks})
            return {"clicks": self.clicks}

        return r

    def run_hooks(self, run):
        return CountSteps(self)
