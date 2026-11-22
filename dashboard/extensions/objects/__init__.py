"""Objects: move the scene's objects with the mouse in the 3D view, the way Teleop moves the grippers.

Drag an object (or the dot above it) to slide it over the table, Shift + drag to lift or lower it, turn it with the
mouse wheel. While it is held, the object ignores gravity and collisions and stays above whatever lies below it
(table, plate, bowl, other objects), so it never ends up inside something. Let go and physics takes over: it drops
and settles.

The bowl and the plate are fixed to the world in the model (no joint), so physics cannot move them: dragging or
lifting one moves its body in the model and takes along whatever lies in or on it (objects, and the other container
stacked on it). Let go and it is put straight down onto whatever is below it.

How a move works: the browser sends drag positions, turns and releases; on the sim thread the newest ones are applied
with `ctx.sim.call(fn, hold=True)` returning no joint targets, so the arms keep holding (or driving to) their pose.
Only between runs, like Teleop: a run that starts drops a held object first.

`env.reset()` (the Reset button, and every test that resets the scene) restores the whole start layout, bowl and
plate included. "Reset layout" in the panel does the same for the objects only; the arms stay where they are.
"""

from __future__ import annotations

import math
import threading
import time
from typing import Literal

import mujoco
import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dashboard.extension import Extension, overlay_disk, overlay_line
from dashboard.extensions.teleop.kinematics import drag_point, project, view_from_scene
from dashboard.simulation import MAIN_SIZE
from dreamtool import scene

NAMES = (*scene.OBJECTS, *scene.CONTAINERS)
EDGE_M = 0.03  # objects stay this far inside the table's edge
LIFT_M = 0.45  # highest lift above the table top
CLEARANCE_M = 0.002  # gap kept between a held object and the surface below it
RAY_ABOVE_M = 0.25  # surfaces up to this far above a held object count (taller things: it is lifted onto them)
FOOTPRINT = 0.8  # share of an object's footprint (an ellipse in its bounding box) probed for surfaces below it
HIT_RADIUS = 0.8  # share of an object's bounding sphere that grabs it in the view
HANDLE_ABOVE_M = 0.012  # the handle dot floats this far above the object's top
STALE_S = 4.0  # a held object is dropped after this long without word from the browser (it sends every second)
DROP_RGBA, SHADOW_RGBA = (1.0, 1.0, 1.0, 0.7), (0.1, 0.1, 0.1, 0.22)
_SIGNS = np.array([[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)], float)
_DOWN = np.array([0.0, 0.0, -1.0])
_PROBES = [(0.0, 0.0)] + [(math.cos(k * math.pi / 4), math.sin(k * math.pi / 4)) for k in range(8)]  # center + ring


class DragBody(BaseModel):
    name: str
    u: float = Field(ge=-0.5, le=1.5)  # mouse position in the main view, 0..1 from the top left
    v: float = Field(ge=-0.5, le=1.5)
    mode: Literal["horizontal", "vertical"] = "horizontal"
    start: bool = False  # first event of a drag: the object is picked up, its position becomes the anchor
    frame: int | None = None


class TurnBody(BaseModel):
    name: str
    degrees: float = Field(ge=-90, le=90)  # about the vertical axis, + = counterclockwise seen from above


def _yaw(mat) -> float:
    """Heading seen from above (deg): direction of the body's x axis."""
    mat = np.asarray(mat).reshape(3, 3)
    return math.degrees(math.atan2(mat[1, 0], mat[0, 0]))


class Objects(Extension):
    """Tool "Objects": drag, lift, turn and drop the scene's objects (bowl and plate too) between runs."""

    title = "Objects"
    icon = "✋"
    description = "Move the scene's objects with the mouse: drag, lift, turn, drop. Bowl and plate too."
    slot = "left"
    order = 16  # after Teleop: its gripper balls get the mouse first where both overlap

    def setup(self):
        self.lock = threading.Lock()
        self.pending = self._no_commands()
        self.scheduled = False
        self.info: dict = {"items": {}, "held": None, "busy": False, "names": list(NAMES)}
        # Sim thread only:
        self.env = None
        self.view: dict | None = None  # camera of the last main-view frame
        self.held: dict | None = None  # the object being dragged

    @staticmethod
    def _no_commands() -> dict:
        return {"drag": None, "turn": {}, "release": False}

    # ---------- HTTP API (any thread) ----------

    def router(self):
        r = APIRouter()

        @r.get("/state")
        def state():
            return self.info

        @r.post("/drag")
        def drag(body: DragBody):
            self._check(body.name)
            if self.view is None:
                raise HTTPException(503, "The 3D view is not ready yet.")
            self._queue(drag=body)
            return {"ok": True}

        @r.post("/turn")
        def turn(body: TurnBody):
            self._check(body.name)
            if body.name in scene.CONTAINERS:
                raise HTTPException(400, f"The {body.name} is round: turning it changes nothing.")
            self._queue(turn=body)
            return {"ok": True}

        @r.post("/release")
        def release():
            if not self.ctx.sim.busy:  # a run that starts drops the object itself
                self._queue(release=True)
            return {"ok": True}

        @r.post("/reset")
        def reset():
            self._idle()
            self.ctx.sim.call(self._reset_layout, hold=True).result(timeout=5)
            self.ctx.log("Objects back in their start layout.")
            return {"ok": True}

        return r

    @staticmethod
    def _check(name: str) -> None:
        if name not in NAMES:
            raise HTTPException(400, f"Unknown object {name!r}. Movable: {', '.join(NAMES)}.")

    def _idle(self) -> None:
        if self.ctx.sim.busy:
            raise HTTPException(409, "A run is active. Objects can be moved between runs: stop the run first.")

    def _queue(self, drag: DragBody | None = None, turn: TurnBody | None = None, release: bool = False) -> None:
        """Merge a command into the pending ones; at most one job waits on the sim thread at a time."""
        self._idle()
        view = self.ctx.sim.interaction_view(drag.frame, self.id, self.view) if drag is not None else None
        with self.lock:
            cmd = self.pending
            if drag is not None:
                previous = cmd["drag"] if cmd["drag"] and cmd["drag"]["name"] == drag.name else None
                # where it was grabbed: kept when later positions replace this one before it is applied
                grab = (view, drag.u, drag.v) if drag.start else (
                    previous["grab"] if previous and previous["mode"] == drag.mode else None)
                cmd["drag"] = {"name": drag.name, "uv": (drag.u, drag.v), "mode": drag.mode, "grab": grab, "view": view}
                if drag.start:
                    cmd["release"] = False  # meant the previous grab, which a new one ends anyway
            if turn is not None:
                cmd["turn"][turn.name] = cmd["turn"].get(turn.name, 0.0) + turn.degrees
            if release:
                cmd["release"] = True
            if self.scheduled:
                return
            self.scheduled = True
        self.ctx.sim.call(self._apply, hold=True).add_done_callback(self._report)

    def _report(self, future) -> None:
        if not future.cancelled() and future.exception() is not None:
            self.ctx.log(f"Moving an object failed: {future.exception()}", "error")

    # ---------- sim thread ----------

    def _ensure(self, env) -> None:
        """Once: geometry lookups, the start layout, and env.reset() restoring it."""
        if self.env is env:
            return
        m = env.model
        self.env = env
        self.body = {name: m.body(name).id for name in NAMES}
        colliding = (m.geom_contype != 0) | (m.geom_conaffinity != 0)
        self.geoms = {name: np.flatnonzero((m.geom_bodyid == bid) & colliding) for name, bid in self.body.items()}
        self.collision = {name: (m.geom_contype[ids].copy(), m.geom_conaffinity[ids].copy())
                          for name, ids in self.geoms.items()}
        self.joint = {name: env.data.joint(scene.FREE_JOINTS[name]) for name in scene.OBJECTS}
        self.qpos_adr = {name: int(m.joint(scene.FREE_JOINTS[name]).qposadr[0]) for name in scene.OBJECTS}
        self.home = {name: m.body(name).pos.copy() for name in scene.CONTAINERS}
        # what an object can rest on: the table (world body), the containers and the other objects, not the arms
        self.supports = {0, *self.body.values()}
        table = m.geom("table")
        self.table_top = float(table.pos[2] + table.size[2])
        self.table_lo = table.pos[:2] - table.size[:2] + EDGE_M
        self.table_hi = table.pos[:2] + table.size[:2] - EDGE_M
        self.gravity = -float(m.opt.gravity[2])
        self.points = {name: self._body_points(m, ids) for name, ids in self.geoms.items()}
        # how far each container stands above the table in the start layout (the bowl's mesh: 3 mm), kept when it
        # is put down again, so lifting and letting go in place brings it back exactly where it was
        self.rest_gap = {name: max(0.0, float(self._bounds(env, name)[0][2]) - self.table_top)
                         for name in scene.CONTAINERS}

        original = env.reset

        def reset():
            self._release(env)
            for name, pos in self.home.items():
                env.model.body(name).pos[:] = pos
            return original()

        env.reset = reset

    def _apply(self, env) -> dict:
        """Applies the pending commands. Returns no joint targets: the arms keep what they hold."""
        with self.lock:
            pending, self.pending, self.scheduled = self.pending, self._no_commands(), False
        self._ensure(env)
        drag = pending["drag"]
        if drag is not None and drag["view"] is not None:
            if self.held is not None and self.held["name"] != drag["name"]:
                self._release(env)
            if self.held is None:
                self._pick_up(env, drag["name"])
            self._drag(env, drag)
        for name, degrees in pending["turn"].items():
            self._turn(env, name, degrees)
        if pending["release"]:
            self._release(env)
        return {}

    @staticmethod
    def _body_points(m, ids) -> np.ndarray:
        """Points in the body's frame whose bounds are the collision geometry's: a mesh's own vertices (a turned
        mesh's box would reach centimeters past it), the box corners of the other shapes."""
        points = []
        for g in ids:
            rot = np.zeros(9)
            mujoco.mju_quat2Mat(rot, m.geom_quat[g])
            if m.geom_type[g] == mujoco.mjtGeom.mjGEOM_MESH:
                mesh = m.geom_dataid[g]
                local = m.mesh_vert[m.mesh_vertadr[mesh]:m.mesh_vertadr[mesh] + m.mesh_vertnum[mesh]]
            else:
                local = m.geom_aabb[g, :3] + m.geom_aabb[g, 3:] * _SIGNS  # center and half size in the geom's frame
            points.append(m.geom_pos[g] + local @ rot.reshape(3, 3).T)
        return np.vstack(points)

    def _bounds(self, env, name: str) -> tuple[np.ndarray, np.ndarray]:
        """World-aligned box (low, high corner) around the object's collision geometry."""
        body = env.data.body(name)
        world = body.xpos + self.points[name] @ body.xmat.reshape(3, 3).T
        return world.min(axis=0), world.max(axis=0)

    def _pick_up(self, env, name: str) -> None:
        pos = env.data.body(name).xpos.copy()
        held = {"name": name, "anchor": None, "mode": None, "offset": np.zeros(3), "pos": pos, "last": 0.0, "carry": []}
        if name in scene.CONTAINERS:
            held["carry"] = self._contents(env, name)
        else:
            ids = self.geoms[name]
            env.model.geom_contype[ids] = 0  # passes through everything while held ...
            env.model.geom_conaffinity[ids] = 0
            body = self.body[name]
            env.data.xfrc_applied[body] = [0, 0, env.model.body_subtreemass[body] * self.gravity, 0, 0, 0]  # ... floats
            self.joint[name].qvel[:] = 0.0
        self.held = held

    def _release(self, env) -> None:
        """Let go: an object gets collisions and gravity back and physics takes over; a container is put down."""
        held, self.held = self.held, None
        if held is None:
            return
        name = held["name"]
        if name not in scene.CONTAINERS:
            ids = self.geoms[name]
            env.model.geom_contype[ids], env.model.geom_conaffinity[ids] = self.collision[name]
            env.data.xfrc_applied[self.body[name]] = 0.0
            self.joint[name].qvel[:] = 0.0
        # Containers cannot fall on their own: put each one down that now hangs in the air (the one let go, or one
        # that stood on the object just moved away), lowest first so a stacked one lands on the one below.
        for container in sorted(scene.CONTAINERS, key=lambda c: self._bounds(env, c)[0][2]):
            self._land(env, container)

    def _contents(self, env, name: str) -> list[str]:
        """What lies in or on a container: the other container stacked on it, and the objects in either."""
        below = env.data.body(name).xpos[2]
        stacked = [c for c in scene.CONTAINERS
                   if c != name and env.data.body(c).xpos[2] > below and scene.is_in(env, c, name)]
        holders = [name, *stacked]
        return stacked + [obj for obj in scene.OBJECTS if any(scene.is_in(env, obj, c) for c in holders)]

    def _land(self, env, name: str) -> None:
        """Put a container straight down onto whatever is below it (table, the other container, an object)."""
        carry = self._contents(env, name)
        low, high = self._bounds(env, name)
        pos = env.data.body(name).xpos.copy()
        surface = self._surface(env, name, pos, low - pos, high - pos, top=high[2] + RAY_ABOVE_M, ignore=carry)
        drop = low[2] - (surface + self.rest_gap[name])
        if drop > 1e-4:
            self._move_container(env, name, carry, np.array([0.0, 0.0, -drop]))

    def _drag(self, env, drag: dict) -> None:
        """New position from a drag: on the horizontal plane through the anchor, or only up/down (vertical)."""
        held, name = self.held, drag["name"]
        held["last"] = time.monotonic()
        mode = drag["mode"]
        if drag["grab"] is not None or held["anchor"] is None or held["mode"] != mode:
            # new drag (or Shift pressed/released): anchor where it is, remember where it was grabbed
            held["anchor"], held["mode"] = held["pos"].copy(), mode
            view, u, v = drag["grab"] or (drag["view"], *drag["uv"])
            grabbed = drag_point(view, u, v, held["anchor"], mode)
            held["offset"] = held["anchor"] - grabbed if grabbed is not None else np.zeros(3)
        point = drag_point(drag["view"], *drag["uv"], held["anchor"], mode)
        if point is None:
            return
        goal = point + held["offset"]  # grabbed off-center: no jump on the first move
        current = env.data.body(name).xpos.copy()
        low, high = self._bounds(env, name)
        container = name in scene.CONTAINERS
        if container:
            margin = (high[:2] - low[:2]) / 2  # the whole container stays above the table
            goal[:2] = np.clip(goal[:2], self.table_lo + margin - EDGE_M, self.table_hi - margin + EDGE_M)
        else:
            goal[:2] = np.clip(goal[:2], self.table_lo, self.table_hi)
        low, high = low - current, high - current  # relative to the body
        surface = self._surface(env, name, goal, low, high, top=goal[2] + high[2] + RAY_ABOVE_M, ignore=held["carry"])
        lowest = surface - low[2] + (self.rest_gap[name] if container else CLEARANCE_M)
        goal[2] = float(np.clip(goal[2], lowest, max(lowest, self.table_top + LIFT_M)))
        if container:
            self._move_container(env, name, held["carry"], goal - current)
            held["pos"] = env.data.body(name).xpos.copy()
            return
        held["pos"] = goal
        joint = self.joint[name]
        joint.qpos[:3] = goal
        joint.qvel[:] = 0.0
        mujoco.mj_forward(env.model, env.data)

    def _move_container(self, env, name: str, carry: list[str], delta) -> None:
        """Shift a container's body in the model; what lies in or on it comes along."""
        env.model.body(name).pos[:] += delta
        for item in carry:
            if item in scene.CONTAINERS:
                env.model.body(item).pos[:] += delta
            else:
                self.joint[item].qpos[:3] += delta
                self.joint[item].qvel[:] = 0.0
        mujoco.mj_forward(env.model, env.data)

    def _surface(self, env, name: str, goal, low, high, top: float, ignore=()) -> float:
        """Highest surface below `top` under the object's footprint at `goal` (table, containers, other objects).
        `ignore`: names that do not count (a container's contents, which move along with it)."""
        m, d = env.model, env.data
        half = (high[:2] - low[:2]) / 2 * FOOTPRINT
        center = goal[:2] + (high[:2] + low[:2]) / 2
        skip = {self.body[n] for n in ignore}
        best = self.table_top
        geom = np.zeros(1, np.int32)
        for px, py in _PROBES:
            start = np.array([center[0] + px * half[0], center[1] + py * half[1], top])
            for _ in range(8):  # skip what it cannot rest on (the arms, its contents): look further down
                distance = mujoco.mj_ray(m, d, start, _DOWN, None, True, self.body[name], geom)
                if distance < 0:
                    break
                hit = start[2] - distance
                body = int(m.geom_bodyid[geom[0]])
                if body in self.supports and body not in skip:
                    best = max(best, hit)
                    break
                start[2] = hit - 1e-4
        return best

    def _turn(self, env, name: str, degrees: float) -> None:
        """Turn about the vertical axis through the object's center of mass."""
        joint, body = self.joint[name], self.body[name]
        angle = math.radians(degrees)
        turn = np.zeros(4)
        mujoco.mju_axisAngle2Quat(turn, np.array([0.0, 0.0, 1.0]), angle)
        quat = np.zeros(4)
        mujoco.mju_mulQuat(quat, turn, joint.qpos[3:7].copy())
        center = env.data.xipos[body].copy()
        c, s = math.cos(angle), math.sin(angle)
        rel = joint.qpos[:3] - center
        moved = center + np.array([c * rel[0] - s * rel[1], s * rel[0] + c * rel[1], rel[2]])
        if self.held is not None and self.held["name"] == name:
            self.held["offset"] += moved - joint.qpos[:3]
            self.held["pos"] = moved.copy()
        joint.qpos[:3], joint.qpos[3:7] = moved, quat
        joint.qvel[:] = 0.0
        mujoco.mj_forward(env.model, env.data)

    def _reset_layout(self, env) -> dict:
        """Objects and containers to where they start; the arms stay."""
        self._ensure(env)
        self._release(env)
        for name, pos in self.home.items():
            env.model.body(name).pos[:] = pos
        for name, adr in self.qpos_adr.items():
            joint = self.joint[name]
            joint.qpos[:] = env.model.qpos0[adr:adr + 7]
            joint.qvel[:] = 0.0
        mujoco.mj_forward(env.model, env.data)
        return {}

    # ---------- hooks ----------

    def run_hooks(self, run):
        """Runs start with nothing held (called on the sim thread right before the run)."""
        env = self.ctx.sim.env
        if env is not None:
            self._ensure(env)
            self._release(env)
        return None

    def prepare_view(self, env):
        self._ensure(env)
        if self.held is not None and time.monotonic() - self.held["last"] > STALE_S:
            self._release(env)  # the browser went away mid-drag

    def decorate(self, env, mjscene):
        """Every main-view frame: positions + image positions to the panel, a drop marker under a held object."""
        self.view = view_from_scene(mjscene, *MAIN_SIZE)
        held = self.held
        width, height = MAIN_SIZE
        items = {}
        for name in NAMES:
            body = env.data.body(name)
            low, high = self._bounds(env, name)
            center = (low + high) / 2
            screen = project(self.view, center)
            reach = None
            if screen is not None:  # grab radius as a share of the image width
                edge = project(self.view, center + self.view["right"] * np.linalg.norm(high - low) / 2 * HIT_RADIUS)
                if edge is not None:
                    reach = round(math.hypot((edge[0] - screen[0]) * width, (edge[1] - screen[1]) * height) / width, 4)
            items[name] = {
                "kind": "container" if name in scene.CONTAINERS else "object",
                "pos": body.xpos.round(4).tolist(),
                "yaw": None if name in scene.CONTAINERS else round(_yaw(body.xmat), 1),
                "screen": screen,
                "handle": project(self.view, [center[0], center[1], high[2] + HANDLE_ABOVE_M]),
                "reach": reach,
            }
            if held is not None and held["name"] == name:
                self._draw_drop(env, name, low, high, mjscene, ignore=held["carry"])
        self.info = {"items": items, "held": held["name"] if held else None, "busy": self.ctx.sim.busy,
                     "names": list(NAMES)}
        self.ctx.emit("objects", self.info, keep=False)

    def _draw_drop(self, env, name, low, high, mjscene, ignore=()) -> None:
        """Where a held object will land: a line straight down to the surface and a shadow on it."""
        pos = env.data.body(name).xpos
        surface = self._surface(env, name, pos, low - pos, high - pos, top=high[2] + RAY_ABOVE_M, ignore=ignore)
        bottom = np.array([(low[0] + high[0]) / 2, (low[1] + high[1]) / 2, low[2]])
        if bottom[2] - surface > 0.01:
            overlay_line(mjscene, bottom, [bottom[0], bottom[1], surface], width=2.0, rgba=DROP_RGBA)
        radius = float(np.linalg.norm(high[:2] - low[:2]) / 2 * 0.6)
        overlay_disk(mjscene, [bottom[0], bottom[1], surface + 0.002], radius=radius, height=0.001, rgba=SHADOW_RGBA)
