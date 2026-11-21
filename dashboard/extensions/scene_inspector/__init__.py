"""Scene: live object positions, success zones as a 3D overlay, debug actions (place an object)."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dashboard.extension import Extension, overlay_disk, overlay_line, overlay_sphere
from dreamtool import scene
from dreamtool.runner import Hooks


class PlaceBody(BaseModel):
    object: str
    container: str


class LiftTracker(Hooks):
    """Remembers how high the target object was lifted at most during a run."""

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
    title = "Scene"
    icon = ""
    description = "Object positions, success zones, debug actions"
    order = 10

    def setup(self):
        self.show_zones = True
        self.target = None  # (object, container) of the current task, for the overlay

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
                raise HTTPException(400, "Unknown object or container")
            if self.ctx.sim.busy:
                raise HTTPException(409, "Not possible while a run is active.")
            self.ctx.sim.call(lambda env: scene.place(env, body.object, body.container)).result(timeout=5)
            self.ctx.log(f"{body.object} placed on {body.container} (debug).")
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
            # dreamlabs.ai palette: grass (#7de290) for the active target, sky (#8bc7fc) otherwise
            rgba = (0.49, 0.89, 0.56, 0.40) if active else (0.55, 0.78, 0.99, 0.22)
            overlay_disk(mjscene, scene.position(env, name) + [0, 0, 0.003], radius=radius, rgba=rgba)
        if self.target is not None:
            obj, container = self.target
            start, end = scene.position(env, obj), scene.position(env, container) + [0, 0, 0.03]
            # creamsicle (#ffb06c) for marker and path
            overlay_sphere(mjscene, start + [0, 0, 0.06], radius=0.008, rgba=(1.0, 0.69, 0.42, 0.95))
            overlay_line(mjscene, start + [0, 0, 0.06], end, rgba=(1.0, 0.69, 0.42, 0.7))
