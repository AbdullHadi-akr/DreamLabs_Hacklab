"""One restorable banana-to-plate checkpoint at a paused, full-chunk request boundary."""
from collections import deque
import copy
import gzip
import hashlib
import json
import math
import time
from uuid import uuid4

import mujoco
import numpy as np

from dreamtool import scene, sim
from .scenarios import STATE_SPEC, capture_start

TASK = "Put the banana on the plate"
SCHEMA = 1
DEMO_PREFIX = 104
STEP_LIMIT = 160
SIDES = ("left", "right")


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False,
                      default=lambda array: array.tolist()).encode()


def digest(value):
    return hashlib.sha256(encode(value)).hexdigest()


def model_signature(env):
    buffer = np.empty(mujoco.mj_sizeModel(env.model), dtype=np.uint8)
    mujoco.mj_saveModel(env.model, buffer=buffer)
    return hashlib.sha256(buffer).hexdigest()


def set_physics(env, state):
    state = np.asarray(state, dtype=np.float64)
    if state.shape != (mujoco.mj_stateSize(env.model, STATE_SPEC),) or not np.isfinite(state).all():
        raise ValueError("Checkpoint physics state does not match this simulator.")
    mujoco.mj_setState(env.model, env.data, state, STATE_SPEC)
    mujoco.mj_forward(env.model, env.data)
    # Forward reconstructs contacts and may modify solver warm-start data.
    mujoco.mj_setState(env.model, env.data, state, STATE_SPEC)
    if not np.array_equal(capture_start(env), state):
        raise ValueError("Checkpoint physics state did not restore exactly.")


def read_checkpoint(path, reference):
    try:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            saved = json.load(stream)
        if (saved["schema"] != SCHEMA or saved["mujoco"] != mujoco.__version__
                or saved["id"] != reference["id"] or digest(saved) != reference["sha256"]):
            raise ValueError("Checkpoint version or content does not match the report.")
    except (OSError, EOFError, KeyError, TypeError, ValueError) as error:
        raise ValueError("Checkpoint is missing, incomplete, or incompatible. Capture a new trial checkpoint.") from error
    return saved


def grasp_sides(evidence):
    return [side for side in SIDES if any(name.startswith((f"{side}_tip_", f"{side}_gripper"))
                                        for name in evidence.get("contacts", []))]


class ScriptedPolicy:
    """Supplies joint chunks to the production paused executor without opening an SDK session."""
    def __init__(self, chunks):
        self.chunks = iter(chunks)

    def set_observation(self, *args, **kwargs):
        pass

    def get_action(self):
        rows = next(self.chunks)
        return {f"q_{side[0]}_chunk": [row[i] for row in rows] for i, side in enumerate(SIDES)}

    def close(self):
        pass


def chunks(rows):
    return [rows[index:index + 48] for index in range(0, len(rows), 48)]


class ForkExecution:
    def __init__(self, evaluator, task, model, *, path=None, script=None, checkpoint=None, guarded=False,
                 max_requests=None, continuation=None):
        self.evaluator = evaluator
        self.task, self.model = task, model
        self.path = path
        self.script = script
        self.checkpoint = checkpoint
        self.guarded = guarded
        self.max_requests = max_requests
        self.continuation = continuation
        self.scripted = script is not None
        self.is_branch = checkpoint is not None
        self.last = None
        self.reference = None
        self.reason = "No inference boundary was reached with verified pickup and an active grasp."
        self.verified = False
        self.events = []
        self.replans = 0
        self.activations = 0
        self.waiting_for_replan = False
        self.release_allowed = False
        self.event_start = 0

    def policy(self):
        return ScriptedPolicy(self.script)

    def command_applied(self, left, right):
        self.last = [left.tolist(), right.tolist()]

    def boundary(self, env, windows, steps, result, deadline, poses):
        if self.is_branch:
            if self.waiting_for_replan:
                self.replans += 1
                self.note(env, "Replan requested")
            return
        if self.reference or self.last is None:
            return
        evidence = self.evaluator.latest or {}
        sides = grasp_sides(evidence)
        if not evidence.get("picked_up") or evidence.get("released_after_pickup") or len(sides) != 1:
            return
        # The SDK has already been fed this exact current state with the last kept frame.
        if (steps - 1) % sim.FRAME_EVERY_STEPS or poses != (self.model in sim.POSE_MODELS):
            self.reason = "Pickup was verified, but no supported camera-aligned request boundary was reached."
            return
        remaining_seconds = deadline - time.monotonic()
        if remaining_seconds < 2:
            self.reason = "Pickup was verified too close to the trial deadline."
            return
        checkpoint = dict(
            schema=SCHEMA, id=uuid4().hex, mujoco=mujoco.__version__, scene=model_signature(env),
            task=self.task, model=self.model, simulation_time=float(env.data.time), physics=capture_start(env),
            command=self.last, side=sides[0], windows=[(name, list(frames)) for name, frames in windows.items()],
            step=steps, strategy="chunk", latency="paused", station=poses,
            observation=digest(sim.observation(env, windows, self.task, self.model, poses)),
            evaluator=vars(self.evaluator), remaining_seconds=remaining_seconds,
            remaining_requests=self.max_requests - result.requests,
            script=self.continuation if self.scripted else None,
        )
        raw = encode(checkpoint)
        temporary = self.path.with_suffix(".tmp")
        try:
            with gzip.open(temporary, "wb") as stream:
                stream.write(raw)
            temporary.replace(self.path)
        except OSError:
            self.reason = "The checkpoint could not be saved to the campaign directory."
            return
        self.reference = dict(id=checkpoint["id"], sha256=hashlib.sha256(raw).hexdigest(),
                              simulation_time=checkpoint["simulation_time"], scripted=self.scripted)

    def restore_inputs(self, env):
        saved = self.checkpoint
        if saved is None:
            return None
        if saved["scene"] != model_signature(env):
            raise ValueError("Simulator model or scene settings changed. Reset the scene or capture a new checkpoint.")
        set_physics(env, saved["physics"])
        self.last = copy.deepcopy(saved["command"])
        controls = [env.data.actuator(f"{side}_finger_{finger}").ctrl[0] / .0475
                    for side in SIDES for finger in (-1, 1)]
        if not np.allclose(controls, np.repeat([row[6] for row in self.last], 2), atol=1e-12, rtol=0):
            raise ValueError("Restored gripper controller targets differ from the checkpoint.")
        if [name for name, _ in saved["windows"]] != list(sim.VIDEO_ROLES):
            raise ValueError("Camera ordering differs from the checkpoint.")
        windows = {name: deque(frames, maxlen=sim.FRAMES) for name, frames in saved["windows"]}
        observation = sim.observation(env, windows, self.task, self.model, saved["station"])
        if digest(observation) != saved["observation"]:
            raise ValueError("The next observation differs from the saved checkpoint.")
        state = copy.deepcopy(saved["evaluator"])
        state["pickup_position"] = np.asarray(state["pickup_position"])
        vars(self.evaluator).update(state)
        self.event_start = len(state["events"])
        self.hold_opening = self.last[SIDES.index(saved["side"])][6]
        self.verified = True
        return windows, saved["step"]

    def note(self, env, decision, **extra):
        evidence = self.evaluator.latest or {}
        self.events.append(dict(decision=decision, simulation_time=float(env.data.time),
                                in_target_region=evidence.get("in_target_region"),
                                grasp_contacts=grasp_sides(evidence),
                                target_distance_m=evidence.get("planar_distance_m"), **extra))

    def before_step(self, env, left, right):
        if not self.guarded or self.release_allowed:
            return None
        side = self.checkpoint["side"]
        evidence = self.evaluator.latest or {}
        if side not in grasp_sides(evidence):
            self.note(env, "Grasp lost before an allowed release")
            return "guard_lost_grasp"
        opening = float((left, right)[SIDES.index(side)][6])
        if opening <= self.hold_opening + .015:
            self.hold_opening = min(self.hold_opening, opening)
            return None
        if evidence["in_target_region"]:
            self.release_allowed = True
            self.note(env, "Release allowed inside plate region", opening=opening)
            return None
        self.activations += 1
        if self.activations > 1:
            self.note(env, "Repeated early release blocked", opening=opening, replan=False)
            return "guard_repeated_early_release"
        self.waiting_for_replan = True
        self.note(env, "Early release blocked; remaining chunk discarded", opening=opening, replan_scheduled=True)
        return "replan"

    def request_limit(self, limit):
        return limit - int(self.guarded and not self.activations)

    def request_error(self, env, error):
        if self.waiting_for_replan:
            self.note(env, "Replan failed", error_type=type(error).__name__)
            self.waiting_for_replan = False

    def reply(self, env):
        if self.waiting_for_replan:
            self.note(env, "Replan returned")
            self.waiting_for_replan = False


def budgets(checkpoint):
    base = min(math.ceil(STEP_LIMIT / 48), checkpoint["remaining_requests"])
    return base, base + 1
