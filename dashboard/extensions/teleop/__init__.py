"""Teleop: move and turn the arms' grippers with the mouse or the keyboard, open and close them, and see the tool
center point (TCP) coordinates live, in the panel and next to the grippers in the 3D view.

The TCP is the simulator's own `left_tcp` / `right_tcp` site, between the fingertips (defined in yam_env.py). That
point is only valid in the simulator: a real arm's TCP has to be measured on the real gripper (see the Dream Labs docs).

How a move works: the browser sends jog steps (move/rotate/tilt), drag positions or gripper commands. On the sim
thread the newest commands become a TCP goal (position + orientation), inverse kinematics turns it into joint
targets, and the sim holds those (`ctx.sim.call(fn, hold=True)`); the arms' position servos drive there, physics and
contacts included. Teleop only works between runs: while Dream-1 or an offline run drives the arms, it is refused.
"""

from __future__ import annotations

import threading
from typing import Literal

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dashboard.extension import Extension, overlay_line, overlay_sphere
from dashboard.simulation import MAIN_SIZE

from .kinematics import (
    FINGER_AXIS,
    POINTING_AXIS,
    SIDES,
    ArmKinematics,
    angle_between,
    describe,
    drag_point,
    point_down,
    project,
    rotation,
    view_from_scene,
)

TABLE_TOP_Z = 0.76  # top of the table (yam_env.py: box at z .73, half-height .03)
MIN_TCP_Z = TABLE_TOP_Z + 0.005  # goals below this are lifted: the fingertips would push into the table
REACHED_M = 0.003  # an IK result closer than this to the goal position counts as reached
ROTATION_OK_RAD = float(np.radians(2.0))  # ... and closer than this to the goal orientation
FINGER_LINE_M = 0.06  # half-length of the line along the finger direction in the 3D view
COLORS = {"left": (0.25, 0.55, 1.0, 0.75), "right": (1.0, 0.55, 0.2, 0.75)}
GOAL_RGBA, UNREACHABLE_RGBA = (1.0, 1.0, 1.0, 0.6), (0.9, 0.15, 0.15, 0.85)
UP = np.array([0.0, 0.0, 1.0])
ROBOT_CAMERA = "top"  # the robot's overhead camera: its view defines forward/right for the keys

Side = Literal["left", "right"]


class JogBody(BaseModel):
    side: Side
    move: list[float] = Field(default=[0.0, 0.0, 0.0], min_length=3, max_length=3)  # forward, right, up
    step: float = Field(default=0.0, ge=0, le=0.05)  # metres along `move`
    rotate: float = Field(default=0.0, ge=-45, le=45)  # degrees about the gripper's own axis, + = counterclockwise
    tilt: float = Field(default=0.0, ge=-45, le=45)  # degrees, + = fingertips forward
    # whose forward/right: "robot" = as the robot's overhead camera sees it (fixed), "view" = the 3D view (orbits)
    frame: Literal["robot", "view"] = "robot"


class DragBody(BaseModel):
    side: Side
    u: float = Field(ge=-0.5, le=1.5)  # mouse position in the main view, 0..1 from the top left
    v: float = Field(ge=-0.5, le=1.5)
    mode: Literal["horizontal", "vertical"] = "horizontal"
    start: bool = False  # first event of a drag: the TCP's goal becomes the anchor
    frame: int | None = None


class GripperBody(BaseModel):
    side: Side
    action: Literal["toggle", "open", "close"] = "toggle"


class OrientationBody(BaseModel):
    mode: Literal["down", "free"]


def _horizontal(vector) -> np.ndarray:
    flat = np.array([vector[0], vector[1], 0.0])
    norm = np.linalg.norm(flat)
    return flat / norm if norm > 1e-6 else flat


class Teleop(Extension):
    """Tool "Control": moves the grippers between runs (mouse, keyboard) through inverse kinematics (see module)."""

    title = "Control"
    icon = ""
    description = "Move and turn the grippers with mouse and keyboard, open/close them, see TCP coordinates."
    slot = "left"
    order = 15

    def setup(self):
        self.lock = threading.Lock()
        self.pending = self._no_commands()
        self.scheduled = False
        # "down": the gripper points straight down and only turns about its own axis; "free": it can also tilt
        self.orientation = "down"
        # Sim thread only:
        self.kin: ArmKinematics | None = None
        self.view: dict | None = None  # camera of the last main-view frame
        self.robot_forward: np.ndarray | None = None  # horizontal view direction of the robot's overhead camera
        self.goals: dict = {}  # side -> TCP goal of the last command
        self.info: dict = {}

    @staticmethod
    def _no_commands() -> dict:
        return {side: {"delta": np.zeros(3), "drag": None, "gripper": None, "rotate": 0.0, "tilt": np.zeros(3)}
                for side in SIDES}

    # ---------- HTTP API (any thread) ----------

    def router(self):
        r = APIRouter()

        @r.get("/state")
        def state():
            return {**self.info, "orientation": self.orientation}

        @r.post("/jog")
        def jog(body: JogBody):
            view = self.view
            if view is None or self.robot_forward is None:
                raise HTTPException(503, "The 3D view is not ready yet.")
            forward = self.robot_forward if body.frame == "robot" else _horizontal(view["forward"])
            right = np.cross(forward, UP)
            f, rt, up = body.move
            direction = f * forward + rt * right + up * UP
            norm = np.linalg.norm(direction)
            delta = direction / norm * body.step if norm > 1e-9 else None
            # tilting about the frame's right axis turns the fingertips forward (+) or back (-)
            self._queue(body.side, delta=delta, rotate=body.rotate, tilt=right * np.radians(body.tilt))
            return {"ok": True}

        @r.post("/drag")
        def drag(body: DragBody):
            view = self.ctx.sim.interaction_view(body.frame, self.id, self.view)
            self._queue(body.side, drag=(body.u, body.v, body.mode, body.start, view))
            return {"ok": True}

        @r.post("/gripper")
        def gripper(body: GripperBody):
            self._queue(body.side, gripper=body.action)
            return {"ok": True}

        @r.post("/orientation")
        def orientation(body: OrientationBody):
            self.orientation = body.mode
            return {"orientation": self.orientation}

        return r

    def _queue(self, side: str, delta=None, drag=None, gripper=None, rotate=0.0, tilt=None) -> None:
        """Merge a command into the pending ones; at most one teleop job waits on the sim thread at a time."""
        worker = self.ctx.sim
        with worker.controls_lock, self.lock:
            if worker.busy:
                raise HTTPException(409, "A run is active. Teleop works between runs: stop the run first.")
            cmd = self.pending[side]
            if delta is not None:
                cmd["delta"] = cmd["delta"] + delta
            if drag is not None:
                u, v, mode, start, view = drag
                # where the ball was grabbed: kept when later positions replace this one before it is applied
                grab = (view, u, v) if start else (cmd["drag"]["grab"] if cmd["drag"] else None)
                if cmd["drag"] and cmd["drag"]["mode"] != mode and not start:
                    grab = None
                cmd["drag"] = {"uv": (u, v), "mode": mode, "grab": grab, "view": view}
            if gripper is not None:
                cmd["gripper"] = None if gripper == cmd["gripper"] == "toggle" else gripper
            cmd["rotate"] += rotate
            if tilt is not None:
                cmd["tilt"] = cmd["tilt"] + tilt  # rotation vector (axis * rad); small steps add up fine
            if self.scheduled:
                return
            self.scheduled = True
            worker.call(self._apply, hold=True).add_done_callback(self._report)

    def _report(self, future) -> None:
        if not future.cancelled() and future.exception() is not None:
            self.ctx.log(f"Teleop failed: {future.exception()}", "error")

    # ---------- sim thread ----------

    def _apply(self, env) -> dict:
        """Turns the pending commands into joint targets the sim then holds (call(..., hold=True))."""
        with self.lock:
            pending, self.pending, self.scheduled = self.pending, self._no_commands(), False
        if self.kin is None:
            self.kin = ArmKinematics(env.model)
        targets = {}
        for side in SIDES:
            cmd = pending[side]
            if (cmd["drag"] is None and cmd["gripper"] is None and not cmd["delta"].any()
                    and not cmd["rotate"] and not cmd["tilt"].any()):
                continue
            goal = self._goal(side)
            self._move(goal, cmd)
            if cmd["gripper"] == "toggle":
                goal["gripper"] = 0.0 if goal["gripper"] > 0.5 else 1.0
            elif cmd["gripper"] is not None:
                goal["gripper"] = 1.0 if cmd["gripper"] == "open" else 0.0
            mat = self._orient(goal, cmd)

            # IK: position + full orientation; if that is out of reach, keep at least the pointing direction;
            # if even that is out of reach, the position wins and the gripper tilts.
            q0 = np.asarray(self.ctx.sim.hold[side][:6], float)
            q, error, _ = self.kin.solve(side, goal["pos"], mat, q0)
            if error > REACHED_M:
                q, error, _ = self.kin.solve(side, goal["pos"], q0=q, target_axis=mat[:, POINTING_AXIS])
                if error > REACHED_M:
                    q, error, _ = self.kin.solve(side, goal["pos"], q0=q)
            pos, achieved = self.kin.fk(side, q)
            goal["reached"] = bool(error <= REACHED_M)
            goal["rotation_ok"] = bool(angle_between(achieved, mat) <= ROTATION_OK_RAD)
            goal["mat"] = achieved  # at the wrist's limits the rotation stops instead of winding up
            if cmd["drag"] is None and not goal["reached"]:
                goal["pos"] = pos  # keys at the edge of the workspace: slide along it instead of running away
            goal["target"] = np.r_[q, goal["gripper"]]
            targets[side] = goal["target"]
        return targets

    def _move(self, goal: dict, cmd: dict) -> None:
        """New goal position from a drag and/or jog steps."""
        drag = cmd["drag"]
        if drag is not None and drag["view"] is not None:
            mode = drag["mode"]
            if drag["grab"] is not None or goal["anchor"] is None or goal["mode"] != mode:
                # new drag (or Shift pressed/released): anchor at the goal, remember where the ball was grabbed
                goal["anchor"], goal["mode"] = goal["pos"].copy(), mode
                view, u, v = drag["grab"] or (drag["view"], *drag["uv"])
                grabbed = drag_point(view, u, v, goal["anchor"], mode)
                goal["offset"] = goal["anchor"] - grabbed if grabbed is not None else np.zeros(3)
            point = drag_point(drag["view"], *drag["uv"], goal["anchor"], mode)
            if point is not None:
                goal["pos"] = point + goal["offset"]  # grabbed off-center: no jump on the first move
        goal["pos"] = goal["pos"] + cmd["delta"]
        goal["pos"][2] = max(goal["pos"][2], MIN_TCP_Z)

    def _orient(self, goal: dict, cmd: dict) -> np.ndarray:
        """Goal orientation: straight down (mode "down"), turned about the gripper's axis, tilted (mode "free")."""
        if cmd["tilt"].any():
            self.orientation = "free"  # tilting leaves "points straight down"
        mat = goal["mat"]
        if self.orientation == "down":
            mat = point_down(mat)
        if cmd["rotate"]:  # about the gripper's own axis; seen from above (pointing down) + is counterclockwise
            mat = rotation(-mat[:, POINTING_AXIS], np.radians(cmd["rotate"])) @ mat
        angle = np.linalg.norm(cmd["tilt"])
        if angle > 0:  # rotation vector, about the keys' horizontal right axis (see jog)
            mat = rotation(cmd["tilt"] / angle, angle) @ mat
        return mat

    def _goal(self, side: str) -> dict:
        """The arm's TCP goal; starts fresh from the held pose if something else moved the arm (run, Home, Reset)."""
        hold = np.asarray(self.ctx.sim.hold[side], float)
        goal = self.goals.get(side)
        if goal is None or not np.allclose(goal["target"], hold):
            pos, mat = self.kin.fk(side, hold[:6])
            goal = {"pos": pos, "mat": mat, "gripper": float(hold[6]), "target": hold.copy(), "anchor": None,
                    "mode": None, "offset": np.zeros(3), "reached": True, "rotation_ok": True}
            self.goals[side] = goal
        return goal

    def decorate(self, env, scene):
        """Send the TCP poses and projected label positions for the current main frame."""
        self.view = view_from_scene(scene, *MAIN_SIZE)
        if self.robot_forward is None:  # fixed camera: read once (camera looks along its -z)
            self.robot_forward = _horizontal(-env.data.cam(ROBOT_CAMERA).xmat.reshape(3, 3)[:, 2])
        idle = self.ctx.sim.current is None
        state = env.state()
        arms = {}
        for side in SIDES:
            site = env.data.site(f"{side}_tcp")
            pos, mat = site.xpos.copy(), site.xmat.reshape(3, 3).copy()
            goal = self.goals.get(side)
            active = idle and goal is not None and np.allclose(goal["target"], self.ctx.sim.hold[side])
            arms[side] = {
                "pos": pos.round(4).tolist(),
                **describe(mat),
                "screen": project(self.view, pos),
                "gripper": round(float(state[side][6]), 3),
                "goal": goal["pos"].round(4).tolist() if active else None,
                "reached": goal["reached"] if active else True,
                "rotation_ok": goal["rotation_ok"] if active else True,
            }
        self.info = {"arms": arms, "busy": self.ctx.sim.busy, "orientation": self.orientation}
        self.ctx.emit("tcp", self.info, keep=False)

    def decorate_teleop(self, env, scene):
        """Draw gripper markers into the Teleop-only image at the scene's current pose."""
        for side in SIDES:
            site = env.data.site(f"{side}_tcp")
            pos = site.xpos
            fingers = site.xmat.reshape(3, 3)[:, FINGER_AXIS] * FINGER_LINE_M
            overlay_line(scene, pos - fingers, pos + fingers, width=3.0, rgba=COLORS[side])
            overlay_sphere(scene, pos, radius=0.011, rgba=COLORS[side])
            arm = self.info["arms"][side]
            goal = arm["goal"]
            if goal is not None and np.linalg.norm(goal - pos) > 0.004:
                rgba = GOAL_RGBA if arm["reached"] else UNREACHABLE_RGBA
                overlay_sphere(scene, goal, radius=0.007, rgba=rgba)
                overlay_line(scene, pos, goal, width=2.0, rgba=rgba)
