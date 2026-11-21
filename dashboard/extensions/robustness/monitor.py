"""Watches one trial and says HOW it went, not only whether it succeeded.

A binary success rate needs many (expensive) trials before it shows anything. The stages below degrade gradually
under a perturbation, so a handful of trials already shows where the model starts to break:

    reached   a gripper came within 4 cm of the target          progress 0.25
    lifted    the target was at least 3 cm above its start      progress 0.50
    carried   while lifted, it got within reach of the container progress 0.75
    success   the target is in/on the container                 progress 1.00

The outcome names the first stage that was missed (plus a few typical failures: wrong object, pushed away,
knocked off the table). Optionally records the three robot cameras as MP4.
"""

from __future__ import annotations

from pathlib import Path
from time import perf_counter

import cv2
import mujoco
import numpy as np

from dreamtool import scene
from dreamtool.runner import Hooks

REACH_M = 0.04
LIFT_M = 0.03
PUSHED_M = 0.04
OFF_TABLE_Z = 0.70
## MuJoCo warnings that mean the physics blew up (the trial then says nothing about the model).
UNSTABLE = (mujoco.mjtWarning.mjWARN_BADQPOS, mujoco.mjtWarning.mjWARN_BADQVEL, mujoco.mjtWarning.mjWARN_BADQACC)


def _unstable_count(env) -> int:
    return int(sum(env.data.warning[int(w)].number for w in UNSTABLE))

OUTCOMES = {
    "success": "Success",
    "missed_container": "Placed next to container",
    "carry_failed": "Lifted, lost on the way",
    "no_grasp": "Reached, no grasp",
    "pushed": "Pushed target away",
    "wrong_object": "Went for wrong object",
    "no_reach": "Never reached target",
    "off_table": "Knocked off table",
    "aborted": "Aborted",
    "invalid": "Not counted (unfair setup / sim glitch)",
}


class TrialRecorder:
    """Top camera (640x360) with both wrist cameras stacked next to it (320x180 each) -> 960x360 MP4."""

    def __init__(self, path: Path):
        from dreamtool.recorder import VideoRecorder

        self.path = path
        self.video = VideoRecorder(path, fps=20, cameras=("frame",))

    def add(self, images):
        if not images:
            return
        wrists = np.concatenate([cv2.resize(images[n], (320, 180), interpolation=cv2.INTER_AREA)
                                 for n in ("left", "right")], axis=0)
        self.video.add({"frame": np.concatenate([images["top"], wrists], axis=1)})

    def close(self):
        self.video.close()
        return self.video.frames


class TrialMonitor(Hooks):
    def __init__(self, obj: str, container: str, video_path: Path | None = None):
        self.obj, self.container = obj, container
        self.video_path = video_path
        self.recorder = None
        self.started = False
        self.min_reach = np.inf
        self.max_lift = 0.0
        self.max_moved = 0.0
        self.min_container_while_lifted = np.inf
        self.others_lift = 0.0
        self.others_moved = 0.0
        self.off_table = False
        self.success_at = None
        self.t0 = 0.0
        self.frames = 0
        self.recording_seconds = 0.0
        self.simulation_seconds = 0.0
        self.warnings0 = 0
        self.metrics: dict = {}

    def on_start(self, env, task, model):
        self.started = True
        self.t0 = float(env.data.time)
        self.warnings0 = _unstable_count(env)
        self.start = {name: scene.position(env, name) for name in scene.OBJECTS}
        if self.video_path is not None:
            started = perf_counter()
            try:
                self.recorder = TrialRecorder(self.video_path)
            except Exception:
                self.recorder = None
            finally:
                self.recording_seconds += perf_counter() - started

    def on_step(self, env, step, images):
        if not self.started:
            return
        p = scene.position(env, self.obj)
        start = self.start[self.obj]
        tcp = [env.data.site(f"{side}_tcp").xpos for side in ("left", "right")]
        self.min_reach = min(self.min_reach, *(np.linalg.norm(t - p) for t in tcp))
        lift = p[2] - start[2]
        self.max_lift = max(self.max_lift, lift)
        self.max_moved = max(self.max_moved, float(np.linalg.norm(p[:2] - start[:2])))
        if lift > LIFT_M:
            c = scene.position(env, self.container)
            self.min_container_while_lifted = min(self.min_container_while_lifted, float(np.linalg.norm(p[:2] - c[:2])))
        for other in scene.OBJECTS:
            if other == self.obj:
                continue
            q, q0 = scene.position(env, other), self.start[other]
            self.others_lift = max(self.others_lift, q[2] - q0[2])
            self.others_moved = max(self.others_moved, float(np.linalg.norm(q[:2] - q0[:2])))
        if p[2] < OFF_TABLE_Z:
            self.off_table = True
        if self.success_at is None and scene.is_in(env, self.obj, self.container):
            self.success_at = float(env.data.time) - self.t0
        if self.recorder is not None:
            started = perf_counter()
            try:
                self.recorder.add(images)
            except Exception:
                self.recorder = None
            finally:
                self.recording_seconds += perf_counter() - started

    def should_stop(self, env):
        # A fallen target cannot be recovered: end the trial instead of paying for the rest of it.
        return "target fell off the table" if self.off_table else None

    def on_end(self, env, result):
        self.simulation_seconds = max(0., float(env.data.time) - self.t0)
        if self.recorder is not None:
            started = perf_counter()
            try:
                self.frames = self.recorder.close()
            except Exception:
                self.frames = 0
            finally:
                self.recording_seconds += perf_counter() - started
        success = result.success if result.success is not None else scene.is_in(env, self.obj, self.container)
        p, c = scene.position(env, self.obj), scene.position(env, self.container)
        radius, _ = scene.CONTAINER_SIZE[self.container]
        reached = self.min_reach < REACH_M
        lifted = self.max_lift > LIFT_M
        carried = self.min_container_while_lifted < radius + 0.05
        reason = result.stop_reason or ""

        unstable = _unstable_count(env) > self.warnings0
        if unstable:
            outcome = "invalid"
        elif success:
            outcome = "success"
        elif reason == "stopped" or reason.startswith("error") or not self.started:
            outcome = "aborted"
        elif self.off_table:
            outcome = "off_table"
        elif not reached:
            outcome = "wrong_object" if self.others_lift > LIFT_M or self.others_moved > PUSHED_M else "no_reach"
        elif not lifted:
            outcome = "pushed" if self.max_moved > PUSHED_M else "no_grasp"
        elif carried:
            outcome = "missed_container"
        else:
            outcome = "carry_failed"

        if unstable:
            success = False
        progress = None if unstable else 1.0 if success else 0.75 if (lifted and carried) else 0.5 if lifted else 0.25 if reached else 0.0
        finite = lambda v: None if not np.isfinite(v) else round(float(v) * 100, 1)  # noqa: E731
        self.metrics = {
            "outcome": outcome,
            "progress": progress,
            "success": bool(success),
            "min_reach_cm": finite(self.min_reach),
            "max_lift_cm": round(self.max_lift * 100, 1),
            "target_moved_cm": round(self.max_moved * 100, 1),
            "final_to_container_cm": round(float(np.linalg.norm(p[:2] - c[:2])) * 100, 1),
            "others_moved_cm": round(self.others_moved * 100, 1),
            "time_to_success_s": None if self.success_at is None else round(self.success_at, 1),
        }
        if unstable:
            self.metrics["note"] = "physics became unstable (simulator issue, not counted)"
