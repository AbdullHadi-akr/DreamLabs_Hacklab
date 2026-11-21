"""Szene: Objekt-Positionen live, Erfolgszonen als 3D-Overlay, Debug-Aktionen (Objekt platzieren)."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dashboard.extension import Extension, overlay_disk, overlay_line, overlay_sphere
from dreamtool import scene
from dreamtool.runner import Hooks


class PlaceBody(BaseModel):
    object: str
    container: str


class LiftTracker(Hooks):
    """Merkt sich, wie hoch das Ziel-Objekt waehrend eines Laufs maximal angehoben wurde."""

    def __init__(self, ext, obj):
        self.ext, self.obj, self.start_z, self.max_lift = ext, obj, None, 0.0

    def on_start(self, env, task, model):
        self.start_z = scene.position(env, self.obj)[2]

    def on_step(self, env, step, images):
        if self.start_z is not None:
            self.max_lift = max(self.max_lift, scene.position(env, self.obj)[2] - self.start_z)

    def on_end(self, env, result):
        self.ext.ctx.emit("run_summary", {"object": self.obj, "max_lift_cm": round(self.max_lift * 100, 1)})


class SceneInspector(Extension):
    title = "Szene"
    icon = "🍎"
    description = "Objekt-Positionen, Erfolgszonen, Debug-Aktionen"
    order = 10

    def setup(self):
        self.show_zones = True
        self.target = None  # (objekt, ablage) des aktuellen Tasks, fuer das Overlay

    def router(self):
        r = APIRouter()

        @r.get("/info")
        def info():
            return {"objects": list(scene.OBJECTS), "containers": list(scene.CONTAINERS), "zones": self.show_zones}

        @r.post("/zones")
        def zones(body: dict):
            self.show_zones = bool(body.get("show", True))
            return {"zones": self.show_zones}

        @r.post("/target")
        def target(body: dict):
            self.target = scene.parse_task(body.get("task", ""))
            return {"target": self.target}

        @r.post("/place")
        def place(body: PlaceBody):
            if body.object not in scene.OBJECTS or body.container not in scene.CONTAINERS:
                raise HTTPException(400, "Unbekanntes Objekt/Ablage")
            if self.ctx.sim.busy:
                raise HTTPException(409, "Waehrend eines Laufs nicht moeglich.")
            self.ctx.sim.call(lambda env: scene.place(env, body.object, body.container)).result(timeout=5)
            self.ctx.log(f"{body.object} auf {body.container} gesetzt (Debug).")
            return {"ok": True}

        return r

    def run_hooks(self, run):
        parsed = scene.parse_task(run["task"])
        self.target = parsed or self.target
        return LiftTracker(self, parsed[0]) if parsed else None

    def decorate(self, env, mjscene):
        if not self.show_zones:
            return
        for name in scene.CONTAINERS:
            radius, _ = scene.CONTAINER_SIZE[name]
            active = self.target is not None and self.target[1] == name
            rgba = (0.25, 0.85, 0.45, 0.35) if active else (0.4, 0.6, 1.0, 0.18)
            overlay_disk(mjscene, scene.position(env, name) + [0, 0, 0.003], radius=radius, rgba=rgba)
        if self.target is not None:
            obj, container = self.target
            start, end = scene.position(env, obj), scene.position(env, container) + [0, 0, 0.03]
            overlay_sphere(mjscene, start + [0, 0, 0.06], radius=0.008, rgba=(1, 0.8, 0.2, 0.9))
            overlay_line(mjscene, start + [0, 0, 0.06], end, rgba=(1, 0.8, 0.2, 0.6))
