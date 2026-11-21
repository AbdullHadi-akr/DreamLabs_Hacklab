"""TEMPLATE for a new extension.

1. Copy the folder:  dashboard/extensions/_template  ->  dashboard/extensions/my_tool
   (folders starting with "_" are not loaded; the copy without "_" is.)
2. Rename the class below, set title/icon.
3. Restart the dashboard (python -m dashboard). The tab appears on the left.

What an extension can do (all optional):
  router()         your own HTTP endpoints under /api/ext/<id>/...
  run_hooks(run)   hooks for every run: on_start, on_reply, on_step, on_wait, should_stop, on_end
  decorate(env, scene)   draw 3D markers into the main view (overlay_sphere / overlay_disk / overlay_line)
  self.ctx.sim     simulation: call(fn) -> Future, run_task(task, ...) -> Future[RunResult], stop(), busy
  self.ctx.emit()  send an event to the panel (panel.js: api.on("name", fn))
  self.ctx.log()   a line in the dashboard log
  self.ctx.data_dir  folder for results (out/extensions/<id>/)
"""

from fastapi import APIRouter

from dashboard.extension import Extension
from dreamtool.runner import Hooks


class CountSteps(Hooks):
    """Example hook: counts steps and reports them at the end."""

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
