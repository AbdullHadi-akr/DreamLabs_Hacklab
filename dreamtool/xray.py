"""Model X-Ray: why Dream-1 does what it does.

The robustness test answers WHEN the model fails; the X-Ray answers WHY. It freezes one moment of the simulation
(a Snapshot: the camera windows Dream-1 sees, the joint state and the MuJoCo state) and asks Dream-1 about that same
moment again and again, each time with one thing changed. The simulation does not move meanwhile. What is measured is
how the planned motion changes.

1. Intent        The 48 joint targets of a chunk become gripper paths (forward kinematics on a scratch copy of the
                 MuJoCo state): where the gripper goes, where it closes, which object it is heading for.
2. Where it looks  RISE (Petsiuk et al. 2018): random smooth masks grey out parts of all three camera windows. For
                 every mask the planned path is compared with the unmasked plan. Per pixel:
                     importance = mean change when the pixel was hidden - mean change when it was visible   (cm)
                 Plus camera reliance: the change when one camera is blanked completely.
3. Language      Same frozen images, only the object word in the prompt is swapped (apple, banana, orange, bottle and
                 a made-up word). Which object does the plan go for? Shows whether the model follows the words or just
                 takes the most salient object.

Dream-1 may not be deterministic, so the unmasked plan is asked several times: the spread between those repeats is the
noise floor every other number is read against.

Everything here is independent of the dashboard: a Prober only needs a function that opens a Dream-1 client.
"""

from __future__ import annotations

import base64
import io
import math
import queue
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Callable

import mujoco
import numpy as np
from PIL import Image

from . import scene, sim

CAMERAS = ("top", "left", "right")
CAMERA_LABELS = {"top": "Overhead", "left": "Left wrist", "right": "Right wrist"}
FRAME_W, FRAME_H = 320, 176
HEAT_W, HEAT_H = 40, 22  # resolution of the stored heatmaps (8 x 8 pixel cells)
GRIP_THRESHOLD = 0.5  # gripper command: 1 = open, 0 = closed
TARGET_RADIUS_M = 0.08  # a grasp counts as "at" an object within 8 cm
APPROACH_M = 0.02  # without a grasp in the chunk: the object the path gets at least 2 cm closer to
NONSENSE_WORD = "blicket"
PROBE_WORDS = {"apple": "apple", "banana": "banana", "orange": "orange", "bottle": "water_bottle", NONSENSE_WORD: None}


# ---------------------------------------------------------------------------------------------------------------------
# Snapshot: one frozen moment
# ---------------------------------------------------------------------------------------------------------------------

@dataclass
class Snapshot:
    prompt: str
    model: str
    state: dict  # {"left": 7 values, "right": 7 values}: joints + gripper opening, as Dream-1 gets them
    qpos: list  # full MuJoCo qpos: arms and objects, for the forward kinematics
    windows: dict  # camera -> list of base64 JPEG frames, oldest first (what Dream-1 sees)
    steps: int = 0  # control steps at the moment (timestamps of the frames)
    source: str = "scene"  # "scene" (frozen idle scene) or "run" (a moment of a Dream-1 run)
    reply: dict | None = None  # run moments: the chunk Dream-1 actually returned at that moment
    id: str = field(default_factory=lambda: time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4])
    created: float = field(default_factory=time.time)
    scene_positions: dict = field(default_factory=dict)  # includes containers stored in the model rather than qpos

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Snapshot":
        return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})

    def summary(self) -> dict:
        return {"id": self.id, "created": self.created, "prompt": self.prompt, "model": self.model,
                "source": self.source, "steps": self.steps, "seconds": round(self.steps / 20, 1),
                "gripper": {s: round(float(self.state[s][6]), 2) for s in ("left", "right")},
                "frames": {cam: self.windows[cam][-1] for cam in CAMERAS if self.windows.get(cam)}}


def encode_frame(rgb: np.ndarray) -> str:
    """Full-size camera image -> base64 JPEG at the size Dream-1 gets (as dream_control.capture does)."""
    buffer = io.BytesIO()
    Image.fromarray(rgb).resize((FRAME_W, FRAME_H), Image.BILINEAR).save(buffer, format="JPEG", quality=85)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def decode_frame(b64: str) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB"), dtype=np.float32)


def _encode_array(rgb: np.ndarray) -> str:
    buffer = io.BytesIO()
    Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8)).save(buffer, format="JPEG", quality=85)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class FrameWindow:
    """The last 9 frames of each camera, one every 4 control steps: the window Dream-1 sees, kept by a hook."""

    def __init__(self):
        self.frames = {cam: [] for cam in CAMERAS}

    def add(self, images: dict) -> None:
        if not images or any(cam not in images for cam in CAMERAS):
            return
        for cam in CAMERAS:
            self.frames[cam] = (self.frames[cam] + [encode_frame(images[cam])])[-sim.FRAMES:]

    @property
    def full(self) -> bool:
        return all(len(v) == sim.FRAMES for v in self.frames.values())

    def copy(self) -> dict:
        return {cam: list(v) for cam, v in self.frames.items()}


def capture_scene(env, prompt: str, model: str) -> Snapshot:
    """Freeze the current scene (call on the sim thread, between runs): the arms hold still for the 1.8 s it takes to
    fill the camera windows, exactly as a run starts."""
    window = FrameWindow()
    hold = env.state()
    steps = 0
    while not window.full:
        env.step(hold["left"], hold["right"])
        steps += 1
        if steps % sim.FRAME_EVERY_STEPS == 0:
            window.add(env.images())
    state = env.state()
    return Snapshot(prompt=prompt, model=model, state={s: np.asarray(state[s], float).tolist() for s in ("left", "right")},
                    qpos=env.data.qpos.tolist(), windows=window.copy(), steps=steps, source="scene",
                    scene_positions={name: pos.tolist() for name, pos in scene.positions(env).items()})


# ---------------------------------------------------------------------------------------------------------------------
# 1. Intent: forward kinematics of a chunk
# ---------------------------------------------------------------------------------------------------------------------

class Kinematics:
    """Gripper (TCP) positions for joint targets, on a scratch MjData: the live simulation is never touched."""

    def __init__(self, model):
        self.model = model
        self.data = mujoco.MjData(model)
        self.arm = {side: [model.joint(f"{side}_joint{i}").qposadr[0] for i in range(1, 7)] for side in ("left", "right")}

    def _set(self, qpos):
        self.data.qpos[:] = qpos
        mujoco.mj_kinematics(self.model, self.data)

    def positions(self, qpos) -> dict:
        """Objects, containers and both TCPs at `qpos`."""
        self._set(qpos)
        out = {name: self.data.body(name).xpos.copy() for name in (*scene.OBJECTS, *scene.CONTAINERS)}
        for side in ("left", "right"):
            out[f"{side}_tcp"] = self.data.site(f"{side}_tcp").xpos.copy()
        return out

    def tcp_paths(self, qpos, left, right) -> dict:
        """TCP path of each arm when its joints follow the chunk rows (arm joints only; gripper does not move the TCP)."""
        self.data.qpos[:] = qpos
        rows = {"left": np.asarray(left, float), "right": np.asarray(right, float)}
        paths = {"left": np.empty((len(rows["left"]), 3)), "right": np.empty((len(rows["right"]), 3))}
        for k in range(len(rows["left"])):
            for side in ("left", "right"):
                self.data.qpos[self.arm[side]] = rows[side][k][:6]
            mujoco.mj_kinematics(self.model, self.data)
            for side in ("left", "right"):
                paths[side][k] = self.data.site(f"{side}_tcp").xpos
        return paths


def gripper_event(opening_now: float, commands) -> tuple[str, int] | None:
    """('close', row) when an open gripper is commanded shut in the chunk, ('open', row) for the reverse, else None."""
    commands = np.asarray(commands, float)
    if opening_now >= GRIP_THRESHOLD:
        rows = np.nonzero(commands < GRIP_THRESHOLD)[0]
        return ("close", int(rows[0])) if len(rows) else None
    rows = np.nonzero(commands >= GRIP_THRESHOLD)[0]
    return ("open", int(rows[0])) if len(rows) else None


def pick_target(start, path, event, point, objects: dict, containers: dict) -> tuple[str | None, float | None, str]:
    """(name, distance in cm, how) of what the arm is heading for.

    close event: the object nearest to where the gripper closes (within 8 cm); open event: the container nearest to the
    release point; no event: the object the path gets closest to, if it gets at least 2 cm closer to it."""
    if event == "close":
        name, d = min(((n, float(np.linalg.norm(point - p))) for n, p in objects.items()), key=lambda x: x[1])
        return (name, round(d * 100, 1), "grasp") if d <= TARGET_RADIUS_M else (None, round(d * 100, 1), "grasp")
    if event == "open":
        name, d = min(((n, float(np.linalg.norm(point[:2] - p[:2]))) for n, p in containers.items()), key=lambda x: x[1])
        return name, round(d * 100, 1), "release"
    end = path[-1]
    gains = {n: float(np.linalg.norm(start - p) - np.linalg.norm(end - p)) for n, p in objects.items()}
    name = max(gains, key=gains.get)
    if gains[name] < APPROACH_M:
        return None, None, "approach"
    return name, round(float(np.linalg.norm(end - objects[name])) * 100, 1), "approach"


def intent(kin: Kinematics, snapshot: Snapshot, left, right) -> dict:
    """What a chunk means: gripper paths, which arm acts, where it closes or opens, and what it is heading for."""
    left, right = np.asarray(left, float), np.asarray(right, float)
    paths = kin.tcp_paths(snapshot.qpos, left, right)
    now = kin.positions(snapshot.qpos)
    now.update({name: np.asarray(point) for name, point in snapshot.scene_positions.items()})
    arms = {}
    for side, rows in (("left", left), ("right", right)):
        start = now[f"{side}_tcp"]
        path = paths[side]
        travel = float(np.linalg.norm(np.diff(np.vstack([start, path]), axis=0), axis=1).sum())
        event = gripper_event(snapshot.state[side][6], rows[:, 6])
        arms[side] = {"travel_cm": round(travel * 100, 1), "event": event[0] if event else None,
                      "event_step": event[1] if event else None,
                      "path": np.round(path, 4).tolist(), "start": np.round(start, 4).tolist()}
    # the acting arm: the one with a gripper event, else the one that moves most
    with_event = [s for s in arms if arms[s]["event"]]
    active = max(with_event or arms, key=lambda s: arms[s]["travel_cm"])
    a = arms[active]
    path = paths[active]
    point = path[a["event_step"]] if a["event"] else None
    objects = {n: now[n] for n in scene.OBJECTS}
    containers = {n: now[n] for n in scene.CONTAINERS}
    target, distance, how = pick_target(now[f"{active}_tcp"], path, a["event"], point, objects, containers)
    return {
        "arm": active, "arms": arms, "target": target, "distance_cm": distance, "how": how,
        "target_position": (now[target].tolist() if target in scene.OBJECTS or target in snapshot.scene_positions
                            else None),
        "event": a["event"], "event_step": a["event_step"],
        "event_s": None if a["event_step"] is None else round((a["event_step"] + 1) / 20, 2),
        "point": None if point is None else np.round(point, 4).tolist(),
        "text": describe_intent(active, a, target, distance, how),
    }


def describe_intent(arm, a, target, distance, how) -> str:
    name = target.replace("water_bottle", "bottle") if target else None
    side = f"{arm.capitalize()} arm"
    if how == "grasp" and a["event"]:
        when = f"after {(a['event_step'] + 1) / 20:.1f} s"
        return (f"{side} closes its gripper {when}, {distance} cm from the {name}." if name
                else f"{side} closes its gripper {when}, but not at any object (nearest {distance} cm away).")
    if how == "release":
        return f"{side} opens its gripper after {(a['event_step'] + 1) / 20:.1f} s over the {name}."
    if name:
        return f"{side} moves {a['travel_cm']} cm towards the {name} (ends {distance} cm from it), no grasp yet."
    return f"{side} moves {a['travel_cm']} cm without heading for any object."


def plan_change_cm(a: dict, b: dict) -> float:
    """How different two plans are: mean distance between the gripper paths of both arms, in cm."""
    d = []
    for side in ("left", "right"):
        pa, pb = np.asarray(a["arms"][side]["path"]), np.asarray(b["arms"][side]["path"])
        n = min(len(pa), len(pb))
        d.append(np.linalg.norm(pa[:n] - pb[:n], axis=1).mean())
    return float(np.mean(d)) * 100


def mean_intent(intents: list[dict]) -> dict:
    """The average path of several answers to the same question (reference for the change of other answers)."""
    out = {"arms": {}}
    for side in ("left", "right"):
        paths = [np.asarray(i["arms"][side]["path"]) for i in intents]
        n = min(len(p) for p in paths)
        out["arms"][side] = {"path": np.mean([p[:n] for p in paths], axis=0).tolist()}
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Talking to Dream-1 about a frozen moment
# ---------------------------------------------------------------------------------------------------------------------

class _FrozenEnv:
    """What dream_control.observation needs from an env: the joint state of the frozen moment."""

    def __init__(self, state: dict):
        self._state = {s: np.asarray(v, float) for s, v in state.items()}

    def state(self):
        return self._state


def open_dream(model: str):
    """A Dream-1 client with a policy open for `model` (one per worker thread)."""
    config = sim.settings()
    key = config.get("DREAM_API_KEY", "")
    if not key:
        raise RuntimeError("No API key: the X-Ray asks Dream-1 and needs one (see README).")
    gateway = config.get("DREAM_GATEWAY_URL", "https://api.dreamlabs.ai")
    poses = model in sim.POSE_MODELS
    return sim.open_policy(sim.policy_config(model, gateway, poses), key), poses


@dataclass
class Question:
    """One variant of the frozen moment: a prompt and the camera windows to send."""
    prompt: str
    windows: dict
    tag: object = None


class Prober:
    """Asks Dream-1 about one frozen moment, with a few parallel sessions. Every question starts a fresh episode
    (reset_episode), so no answer depends on an earlier question."""

    def __init__(self, snapshot: Snapshot, opener: Callable = open_dream, workers: int = 3,
                 stopped: Callable[[], bool] = lambda: False):
        self.snapshot = snapshot
        self.opener = opener
        self.workers = max(1, workers)
        self.stopped = stopped
        self.calls = 0
        self._lock = threading.Lock()

    def _ask_one(self, client, poses, question: Question) -> dict:
        for attempt in range(8):
            try:
                client.reset_episode()
            except Exception:
                pass
            sim.feed(client, _FrozenEnv(self.snapshot.state), question.windows, question.prompt, self.snapshot.model,
                     self.snapshot.steps, every=0, station=poses)
            try:
                reply = client.get_action()
                with self._lock:
                    self.calls += 1
                return reply
            except Exception as error:
                retry = getattr(error, "retryable", False) or type(error).__name__ == "DreamSessionExpired"
                if not retry or attempt == 7 or self.stopped():
                    raise
                time.sleep(getattr(error, "retry_after_s", None) or 1.0)
        raise RuntimeError("unreachable")

    def ask(self, questions: list[Question], on_answer: Callable[[int, Question, dict], None] | None = None) -> list:
        """Replies (dicts with q_l_chunk / q_r_chunk) in the order of `questions`; None for questions not asked
        because the job was stopped."""
        answers: list = [None] * len(questions)
        todo: queue.Queue = queue.Queue()
        for i, q in enumerate(questions):
            todo.put(i)
        errors: list = []

        def work():
            try:
                client, poses = self.opener(self.snapshot.model)
            except Exception as error:
                errors.append(error)
                return
            try:
                while not self.stopped() and not errors:
                    try:
                        i = todo.get_nowait()
                    except queue.Empty:
                        return
                    reply = self._ask_one(client, poses, questions[i])
                    answers[i] = reply
                    if on_answer:
                        on_answer(i, questions[i], reply)
            except Exception as error:
                errors.append(error)
            finally:
                try:
                    client.close()
                except Exception:
                    pass

        threads = [threading.Thread(target=work, daemon=True) for _ in range(min(self.workers, len(questions)))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        if errors:
            raise errors[0]
        return answers


def chunk(reply: dict) -> tuple[np.ndarray, np.ndarray]:
    return np.asarray(reply["q_l_chunk"], float), np.asarray(reply["q_r_chunk"], float)


# ---------------------------------------------------------------------------------------------------------------------
# 2. Where it looks: RISE masks
# ---------------------------------------------------------------------------------------------------------------------

def rise_mask(rng, grid=(5, 8), p=0.5, size=(FRAME_H, FRAME_W)) -> np.ndarray:
    """One smooth random mask in [0, 1] (1 = visible): a coarse random grid, bilinearly upsampled and randomly shifted
    by up to one cell, as in RISE."""
    gh, gw = grid
    h, w = size
    ch, cw = math.ceil(h / gh), math.ceil(w / gw)
    cells = (rng.random((gh + 1, gw + 1)) < p).astype(np.float32)
    up = np.asarray(Image.fromarray(cells, mode="F").resize(((gw + 1) * cw, (gh + 1) * ch), Image.BILINEAR))
    dy, dx = int(rng.integers(0, ch)), int(rng.integers(0, cw))
    return np.clip(up[dy:dy + h, dx:dx + w], 0, 1)


def masked_window(frames: list[str], mask: np.ndarray, fill: float = 127.0) -> list[str]:
    """The same mask on every frame of a camera's window: hidden parts become grey."""
    m = mask[..., None]
    return [_encode_array(decode_frame(f) * m + fill * (1 - m)) for f in frames]


def blank_window(frames: list[str], fill: float = 127.0) -> list[str]:
    return masked_window(frames, np.zeros((FRAME_H, FRAME_W), np.float32), fill)


def _small(mask: np.ndarray) -> np.ndarray:
    return np.asarray(Image.fromarray(mask.astype(np.float32), mode="F").resize((HEAT_W, HEAT_H), Image.BOX))


class RiseMap:
    """Accumulates importance = E[change | hidden] - E[change | visible] per heatmap cell, for one camera."""

    def __init__(self):
        self.d_vis = np.zeros((HEAT_H, HEAT_W))
        self.w_vis = np.zeros((HEAT_H, HEAT_W))
        self.d_hid = np.zeros((HEAT_H, HEAT_W))
        self.w_hid = np.zeros((HEAT_H, HEAT_W))

    def add(self, small_mask: np.ndarray, change_cm: float) -> None:
        self.d_vis += change_cm * small_mask
        self.w_vis += small_mask
        self.d_hid += change_cm * (1 - small_mask)
        self.w_hid += 1 - small_mask

    def importance(self) -> np.ndarray:
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.nan_to_num(self.d_hid / self.w_hid - self.d_vis / self.w_vis)


def chance_level(small_masks: list[np.ndarray], changes: list[float], shuffles: int = 200, seed: int = 1) -> float:
    """How high the strongest cell of a heatmap gets by chance with these masks: the 95th percentile of the peak
    importance when the plan changes are shuffled between the masks (a permutation test). Cells below it are noise."""
    if len(changes) < 4:
        return float("inf")
    rng = np.random.default_rng(seed)
    m = np.asarray(small_masks)  # (n, H, W)
    vis, hid = m.sum(0), (1 - m).sum(0)
    peaks = []
    for _ in range(shuffles):
        d = rng.permutation(np.asarray(changes))[:, None, None]
        with np.errstate(invalid="ignore", divide="ignore"):
            imp = np.nan_to_num((d * (1 - m)).sum(0) / hid - (d * m).sum(0) / vis)
        peaks.append(imp.max())
    return float(np.percentile(peaks, 95))


# ---------------------------------------------------------------------------------------------------------------------
# 3. Language: swap the object word
# ---------------------------------------------------------------------------------------------------------------------

def swap_object(prompt: str, word: str) -> str:
    """The prompt with its object word replaced by `word` ("put the banana on the plate" -> "put the apple on the
    plate"). Falls back to "put the <word> into the <container>" when no object word is found."""
    import re

    parsed = scene.parse_task(prompt)
    target = parsed[0] if parsed else None
    words = sorted((w for w, body in scene.OBJECT_WORDS.items() if body == target), key=len, reverse=True)
    for w in (["water bottle"] if target == "water_bottle" else []) + words:
        pattern = re.compile(rf"\b{re.escape(w)}\b", re.IGNORECASE)
        if pattern.search(prompt):
            return pattern.sub(word, prompt, count=1)
    container = parsed[1] if parsed else "bowl"
    return f"put the {word} into the {container}"


## The plan "goes towards" a named object when its closest approach to it is this much nearer than with the original
## prompt (or 3x the noise), and nearer than its change towards any other object. Measured on real Dream-1: the hard
## target (a grasp within 8 cm, a 2 cm approach) was missing in the re-asked plan of two of three moments, so the
## word could not be checked at all; the closest approach always exists.
PULL_MIN_CM = 1.0


def closest_approach_cm(kin_intent: dict, positions: dict) -> dict:
    """Per object, how close either gripper gets to it along the planned 2.4 s path (cm)."""
    pts = np.vstack([np.asarray(kin_intent["arms"][s]["path"]) for s in ("left", "right")])
    return {n: round(float(np.linalg.norm(pts - np.asarray(p), axis=1).min()) * 100, 2) for n, p in positions.items()}


def language_pull(rows: list[dict], base: dict, original: str | None, noise_cm: float = 0.0) -> dict:
    """Per swapped word: how much nearer the plan gets to the named object than with the original prompt (`pull_cm`),
    and whether that is more than towards any other object (`towards`).

    rows: {word, named, closest: [{object: cm} per answer]}; base: {object: cm} for the original prompt."""
    needed = max(3 * noise_cm, PULL_MIN_CM)
    for r in rows:
        if not r.get("closest"):
            continue
        mean = {n: float(np.mean([c[n] for c in r["closest"]])) for n in base}
        gains = {n: round(base[n] - mean[n], 2) for n in base}  # > 0: nearer than with the original prompt
        r["gain_cm"] = gains
        r["nearest"] = min(mean, key=mean.get)
        if r["named"] is None or r["named"] == original:
            r["pull_cm"], r["towards"] = None, None
            continue
        others = [g for n, g in gains.items() if n != r["named"]]
        r["pull_cm"] = gains[r["named"]]
        r["towards"] = bool(gains[r["named"]] > needed and gains[r["named"]] > max(others, default=-np.inf))
    checked = [r for r in rows if r.get("towards") is not None]
    return {"towards": sum(r["towards"] for r in checked), "checked": len(checked), "needed_cm": round(needed, 2)}


def language_summary(rows: list[dict]) -> dict:
    """rows: {word, named (body or None), targets: [body or None per repeat]}."""
    for r in rows:
        counts = {}
        for t in r["targets"]:
            counts[t] = counts.get(t, 0) + 1
        r["mode"] = max(counts, key=counts.get) if counts else None
        r["agreement"] = round(counts.get(r["mode"], 0) / max(1, len(r["targets"])), 2)
        r["followed"] = r["named"] is not None and r["mode"] == r["named"]
    real = [r for r in rows if r["named"] is not None]
    followed = sum(r["followed"] for r in real)
    all_targets = [t for r in rows for t in r["targets"] if t]
    favourite = max(set(all_targets), key=all_targets.count) if all_targets else None
    nonsense = next((r for r in rows if r["named"] is None), None)
    name = lambda t: (t or "nothing").replace("water_bottle", "bottle")  # noqa: E731
    if not real:
        text = "No answers yet."
    elif not all_targets:
        text = ("No plan heads for any object at this moment (no grasp, no clear approach within the 2.4 s chunk), so "
                "the word cannot be checked. Freeze a moment where the arm already reaches out.")
    elif followed == len(real):
        text = f"Follows the object word: it heads for the named object in all {len(real)} cases."
    elif followed == 0 and favourite and all_targets.count(favourite) >= len(rows):
        text = f"Ignores the object word: it goes for the {name(favourite)} whatever the prompt names."
    else:
        text = f"Follows the object word in {followed} of {len(real)} cases."
    if nonsense is not None and all_targets:
        text += f" With the made-up word “{nonsense['word']}” it goes for {name(nonsense['mode'])}."
    return {"rows": rows, "followed": followed, "of": len(real), "favourite": favourite, "text": text}


# ---------------------------------------------------------------------------------------------------------------------
# The three analyses (each: Prober in, JSON-ready result out)
# ---------------------------------------------------------------------------------------------------------------------

def _progress(cb, done, total, text=""):
    if cb:
        cb({"done": done, "total": total, "text": text})


def run_intent(prober: Prober, kin: Kinematics, repeats: int = 3, progress=None) -> dict:
    """Ask the unchanged moment `repeats` times: the plan, and how much Dream-1 varies on its own (noise floor)."""
    snap = prober.snapshot
    questions = [Question(snap.prompt, snap.windows, tag=i) for i in range(repeats)]
    done = [0]

    def answered(i, q, reply):
        done[0] += 1
        _progress(progress, done[0], repeats, "asking the unchanged moment")

    replies = [r for r in prober.ask(questions, answered) if r is not None]
    intents = [intent(kin, snap, *chunk(r)) for r in replies]
    if not intents:
        raise RuntimeError("stopped before Dream-1 answered")
    pairs = [plan_change_cm(a, b) for i, a in enumerate(intents) for b in intents[i + 1:]]
    targets = [i["target"] for i in intents]
    recorded = None
    if snap.reply:  # a run moment: how close is the re-asked plan to what Dream-1 answered during the run?
        recorded = intent(kin, snap, *chunk(snap.reply))
    return {
        "intent": intents[0], "repeats": intents, "noise_cm": round(float(np.mean(pairs)), 2) if pairs else None,
        "consistent_target": len(set(targets)) == 1, "targets": targets,
        "recorded": recorded,
        "recorded_change_cm": round(plan_change_cm(recorded, mean_intent(intents)), 2) if recorded else None,
        "calls": prober.calls,
    }


## RISE only runs where the plan depends on the images at all: when blanking a whole camera moves the plan by at most
## this (or 3x the noise), every masked window changes even less and the heatmap is noise. Measured on real Dream-1
## (22.11.2026): at 3 s into a run blanking any camera moved the plan 0.4-0.5 cm and 200 masks stayed at chance level.
MIN_RELIANCE_CM = 1.0
## Masks go on one camera only: the one whose blanking moves the plan most. Masking all three at once (as first built)
## hid half of every camera in every mask; on real Dream-1 the plan then changed a lot with every mask and no cell rose
## above chance even with 200 masks. With the other cameras untouched, each mask's effect is the effect of that camera.
RISE_P_ALL = 0.5  # visible share of a cell when all cameras are masked
RISE_P_ONE = 0.75  # one camera: hide a quarter, so a mask removes a few regions rather than half the picture


def run_rise(prober: Prober, kin: Kinematics, masks: int = 40, repeats: int = 3, seed: int = 0, progress=None,
             camera: str = "auto", p: float | None = None) -> dict:
    """RISE heatmap, plus camera reliance (each camera blanked) and the noise floor.

    The unchanged and blanked windows are asked first. When no camera matters at this moment (MIN_RELIANCE_CM) the
    masks are skipped and the result says so instead of drawing a heatmap of noise. `camera`: "auto" masks only the
    camera whose blanking moved the plan most, a camera name masks that one, "all" masks all three at once."""
    snap = prober.snapshot
    rng = np.random.default_rng(seed)
    questions = [Question(snap.prompt, snap.windows, tag=("base", i)) for i in range(repeats)]
    for cam in CAMERAS:
        questions.append(Question(snap.prompt, {**snap.windows, cam: blank_window(snap.windows[cam])}, tag=("blank", cam)))
    first = len(questions)
    total = first + masks
    done = [0]

    def answered(i, q, reply):
        done[0] += 1
        _progress(progress, done[0], total, "masked camera windows")

    replies = prober.ask(questions[:first], answered)
    intents = [None if r is None else intent(kin, snap, *chunk(r)) for r in replies]
    base = [it for q, it in zip(questions, intents) if q.tag[0] == "base" and it is not None]
    if not base:
        raise RuntimeError("stopped before the unchanged moment was answered")
    reference = mean_intent(base)
    noise = [plan_change_cm(b, reference) for b in base]
    blanked = [plan_change_cm(it, reference) for q, it in zip(questions, intents) if q.tag[0] == "blank" and it is not None]
    needed = max(3 * float(np.mean(noise)), MIN_RELIANCE_CM)
    blank_change = {q.tag[1]: plan_change_cm(it, reference) for q, it in zip(questions, intents)
                    if q.tag[0] == "blank" and it is not None}
    if camera == "auto":
        masked = [max(blank_change, key=blank_change.get)] if blank_change else list(CAMERAS)
    elif camera == "all":
        masked = list(CAMERAS)
    elif camera in CAMERAS:
        masked = [camera]
    else:
        raise ValueError(f"camera must be auto, all or one of {CAMERAS}")
    p = p if p is not None else RISE_P_ONE if len(masked) == 1 else RISE_P_ALL
    small_masks = []
    if blanked and max(blanked) <= needed:
        _progress(progress, first, first, "skipped the masks: no camera matters at this moment")
    else:
        for k in range(masks):
            windows, smalls = dict(snap.windows), {}
            for cam in masked:
                m = rise_mask(rng, p=p)
                windows[cam] = masked_window(snap.windows[cam], m)
                smalls[cam] = _small(m)
            small_masks.append(smalls)
            questions.append(Question(snap.prompt, windows, tag=("mask", k)))
        replies += prober.ask(questions[first:], lambda i, q, reply: answered(first + i, q, reply))
        intents += [None if r is None else intent(kin, snap, *chunk(r)) for r in replies[first:]]
    maps = {cam: RiseMap() for cam in CAMERAS}
    changes, reliance = [], {}
    for q, it in zip(questions, intents):
        if it is None:
            continue
        change = plan_change_cm(it, reference)
        if q.tag[0] == "blank":
            reliance[q.tag[1]] = {"change_cm": round(change, 2), "target": it["target"], "text": it["text"]}
        elif q.tag[0] == "mask":
            changes.append(change)
            for cam in masked:
                maps[cam].add(small_masks[q.tag[1]][cam], change)
    if not changes:  # masks skipped (or none answered)
        most = max(reliance.values(), key=lambda r: r["change_cm"])["change_cm"] if reliance else 0.0
        text = (f"At this moment the plan barely depends on the images: blanking a whole camera moves it by at most "
                f"{most} cm (needs more than {round(needed, 2)} cm), so masks would only map noise and were skipped. "
                f"Freeze a moment where the arm reaches for or carries an object.")
        zeros = np.zeros((HEAT_H, HEAT_W)).tolist()
        return {"heat": {cam: zeros for cam in CAMERAS}, "peak_cm": {cam: 0.0 for cam in CAMERAS},
                "chance_cm": {cam: None for cam in CAMERAS}, "looks_at": [], "reliance": reliance,
                "masked": [], "p_visible": p,
                "noise_cm": round(float(np.mean(noise)), 2), "mask_changes_cm": [], "masks": 0, "skipped": True,
                "grid": [HEAT_H, HEAT_W], "reference_target": base[0]["target"], "text": text, "calls": prober.calls}
    heat ={cam: np.round(maps[cam].importance(), 3).tolist() for cam in CAMERAS}
    peak = {cam: round(float(np.max(maps[cam].importance())), 2) if cam in masked else 0.0 for cam in CAMERAS}
    used = [small_masks[q.tag[1]] for q, it in zip(questions, intents) if it is not None and q.tag[0] == "mask"]
    chance = {cam: round(chance_level([u[cam] for u in used], changes), 2) if cam in masked else None for cam in CAMERAS}
    looks_at = [c for c in masked if peak[c] > chance[c]]
    noise_cm = round(float(np.mean(noise)), 2)
    strongest = max(reliance, key=lambda c: reliance[c]["change_cm"]) if reliance else None
    text = (f"Blanking the {CAMERA_LABELS[strongest].lower()} camera changes the plan most "
            f"({reliance[strongest]['change_cm']} cm; noise {noise_cm} cm)." if strongest else "")
    weak = [CAMERA_LABELS[c] for c, r in reliance.items() if r["change_cm"] <= 1.5 * noise_cm]
    if weak:
        text += f" {', '.join(weak)}: no clear effect, within the noise."
    where = f"the {CAMERA_LABELS[masked[0]].lower()} camera" if len(masked) == 1 else "all three cameras"
    if looks_at:
        text += f" Masks on {where}: heatmap above chance for {', '.join(CAMERA_LABELS[c].lower() for c in looks_at)}."
    else:
        text += f" Masks on {where}: no cell rises above chance with {len(changes)} masks."
    return {"heat": heat, "peak_cm": peak, "chance_cm": chance, "looks_at": looks_at, "reliance": reliance,
            "masked": masked, "p_visible": p, "noise_cm": noise_cm,
            "mask_changes_cm": [round(c, 2) for c in changes], "masks": len(changes), "grid": [HEAT_H, HEAT_W],
            "reference_target": base[0]["target"], "text": text.strip(), "calls": prober.calls}


def run_language(prober: Prober, kin: Kinematics, repeats: int = 2, words=None, progress=None) -> dict:
    """Swap the object word: does the plan go for the object the prompt names?"""
    snap = prober.snapshot
    words = words or PROBE_WORDS
    questions = [Question(snap.prompt, snap.windows, tag=(None, r)) for r in range(repeats)]  # the original prompt
    questions += [Question(swap_object(snap.prompt, w), snap.windows, tag=(w, r)) for w in words for r in range(repeats)]
    done = [0]

    def answered(i, q, reply):
        done[0] += 1
        _progress(progress, done[0], len(questions), f"prompt: {q.prompt}")

    replies = prober.ask(questions, answered)
    positions = {n: p for n, p in kin.positions(snap.qpos).items() if n in scene.OBJECTS}
    rows = {w: {"word": w, "named": words[w], "prompt": swap_object(snap.prompt, w), "targets": [], "texts": [],
                "closest": []} for w in words}
    base_intents = []
    for q, reply in zip(questions, replies):
        if reply is None:
            continue
        it = intent(kin, snap, *chunk(reply))
        if q.tag[0] is None:
            base_intents.append(it)
            continue
        rows[q.tag[0]]["targets"].append(it["target"])
        rows[q.tag[0]]["texts"].append(it["text"])
        rows[q.tag[0]]["closest"].append(closest_approach_cm(it, positions))
    answered_rows = [r for r in rows.values() if r["targets"]]
    result = language_summary(answered_rows)
    if base_intents:
        base_closest = [closest_approach_cm(it, positions) for it in base_intents]
        base = {n: float(np.mean([c[n] for c in base_closest])) for n in positions}
        noise = [plan_change_cm(a, b) for i, a in enumerate(base_intents) for b in base_intents[i + 1:]]
        parsed = scene.parse_task(snap.prompt)
        pull = language_pull(answered_rows, base, parsed[0] if parsed else None, float(np.mean(noise)) if noise else 0.0)
        result.update(pull=pull, base_closest_cm={n: round(v, 2) for n, v in base.items()})
        moved = ", ".join(f"{r['named'].replace('water_bottle', 'bottle')} {r['pull_cm']:+.1f} cm"
                          for r in answered_rows if r.get("pull_cm") is not None)
        verdict = (f"Towards the named object in {pull['towards']} of {pull['checked']} swapped words "
                   f"(closest approach vs. the original prompt: {moved}; needs more than {pull['needed_cm']} cm and "
                   f"more than towards any other object).")
        hard = result["text"] if result["text"] and "cannot be checked" not in result["text"] else ""
        result["text"] = (verdict + " " + hard).strip()
    held = [s for s in ("left", "right") if snap.state[s][6] < GRIP_THRESHOLD]
    result["warning"] = (f"The {held[0]} gripper is closed in this moment: the plan may be about placing what it holds, "
                         "not about which object to pick. Freeze a moment before the grasp." if held else None)
    result["calls"] = prober.calls
    return result
