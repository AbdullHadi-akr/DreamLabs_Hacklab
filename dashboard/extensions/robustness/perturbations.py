"""Perturbations for the robustness test. New perturbation = one function decorated with @perturbation.

Two kinds:

  env perturbation   fn(env, value, rng, target) -> Effect | restore | None
      env     YamEnv right after env.reset()
      value   strength in the perturbation's unit (cm, degrees, percent ...)
      rng     numpy Generator. Seeded per trial index, NOT per strength: trial 3 of a sweep pushes the object in the
              same direction at 2, 4 and 6 cm, so neighbouring strengths are compared on the same random draw.
      target  Target(obj, container) parsed from the task
      returns an Effect (restore, hooks, info) or just a restore function, or None.
              Object positions need no restoring (the next env.reset() does that); model changes (cameras, lights,
              masses, materials, body positions) do.

  text perturbation  fn(task, value, rng, target) -> str      (the prompt Dream-1 sees; success is still judged
                                                                against the original task)

Design choices (what is in here and what deliberately is not):
  * Only variation a real Dream-1 deployment meets: object/container placement, camera mounting, lighting, colors,
    sensor noise, object/grip physics, wording of the prompt, and the world changing during a grasp.
  * No latency perturbation: this sim pauses physics while it waits for Dream-1, so delays change nothing.
  * No joint-encoder noise: real encoders are precise, and the noisy state would also leak into hold commands.
  * No impossible scenes: every setup is checked (objects on the table, nothing exploding out of an overlap, target not
    already in the container) and re-drawn if invalid, so a failure is the model's, not the test's.
"""

from __future__ import annotations

import string
import zlib
from dataclasses import dataclass, field
from typing import Callable, NamedTuple

import mujoco
import numpy as np

from dreamtool import scene
from dreamtool.runner import Hooks

## Table top (m) and the part of it the arms can reach; objects must stay inside after a perturbation.
TABLE_Z = 0.76
WORKSPACE_X = (-0.42, 0.42)
WORKSPACE_Y = (-0.25, 0.22)

GROUPS = {
    "scene": "Scene layout",
    "visual": "Vision",
    "physics": "Physics",
    "language": "Language",
    "dynamic": "During the run",
}


class Target(NamedTuple):
    obj: str
    container: str


@dataclass
class Effect:
    restore: Callable | None = None  # env -> None, undo model changes
    hooks: list = field(default_factory=list)  # extra run hooks (e.g. a mid-run disturbance)
    info: dict = field(default_factory=dict)  # what was actually applied (direction, color ...), shown per trial

    def undo(self, env):
        if self.restore:
            self.restore(env)


@dataclass
class Perturbation:
    id: str
    label: str
    unit: str
    group: str
    defaults: list[float]  # sweep strengths
    max: float  # upper bound for the random mix
    neutral: float  # strength that means "unchanged" (the baseline)
    discrete: bool
    description: str
    kind: str  # "env" or "text"
    fn: Callable

    def seed_key(self) -> int:
        return zlib.crc32(self.id.encode())

    def sample(self, rng, top: float | None = None) -> float:
        """Random strength for the random mix: uniform between neutral and `top` (default: max)."""
        top = self.max if top is None else top
        if self.discrete:
            return float(rng.integers(int(self.neutral), int(max(top, self.neutral)) + 1))
        return round(float(rng.uniform(self.neutral, max(top, self.neutral))), 2)


REGISTRY: dict[str, Perturbation] = {}


def perturbation(id, label, unit, group, defaults, *, max=None, neutral=0.0, discrete=False, kind="env"):
    def register(fn):
        doc = " ".join((fn.__doc__ or "").split()).replace("`", "")
        REGISTRY[id] = Perturbation(id, label, unit, group, list(defaults), float(max if max is not None else defaults[-1]),
                                    float(neutral), discrete, doc, kind, fn)
        return fn

    return register


def as_effect(result) -> Effect:
    if result is None:
        return Effect()
    if isinstance(result, Effect):
        return result
    return Effect(restore=result)


# ---------- helpers ----------

def _direction(rng, dims=2):
    v = rng.normal(size=dims)
    return v / (np.linalg.norm(v) or 1.0)


def _fmt_vec(v, unit="cm", scale=100):
    return ", ".join(f"{c * scale:+.1f}" for c in v) + f" {unit}"


def _body_geoms(env, body):
    bid = env.model.body(body).id
    return [g for g in range(env.model.ngeom) if env.model.geom_bodyid[g] == bid]


def _visual_geoms(env, body):
    m = env.model
    return [g for g in _body_geoms(env, body) if m.geom_rgba[g][3] > 0 or m.geom_matid[g] >= 0]


def _random_color(rng):
    """A saturated color with a random hue (RGB 0..1)."""
    hue = rng.uniform(0, 1)
    k = (np.array([5, 3, 1]) + hue * 6) % 6
    return 1 - np.clip(np.minimum(k, 4 - k), 0, 1) * 0.85


def _texture_mean(env, texid):
    m = env.model
    n = m.tex_width[texid] * m.tex_height[texid] * m.tex_nchannel[texid]
    data = m.tex_data[m.tex_adr[texid]:m.tex_adr[texid] + n].reshape(-1, m.tex_nchannel[texid])[:, :3]
    used = data[data.max(axis=1) > 40]  # scanned textures leave unused UV space black
    return np.median(used if len(used) else data, axis=0) / 255.0


def _tint(env, geoms, materials, color, amount):
    """Blend geom colors / material colors toward `color` by `amount` (0..1). Returns a restore function."""
    m = env.model
    saved_geoms = {g: m.geom_rgba[g].copy() for g in geoms}
    saved_mats = {i: m.mat_rgba[i].copy() for i in materials}
    for g, rgba in saved_geoms.items():
        m.geom_rgba[g][:3] = rgba[:3] * (1 - amount) + color * amount
    for i, rgba in saved_mats.items():
        m.mat_rgba[i][:3] = rgba[:3] * (1 - amount) + color * amount

    def restore(env):
        for g, rgba in saved_geoms.items():
            env.model.geom_rgba[g] = rgba
        for i, rgba in saved_mats.items():
            env.model.mat_rgba[i] = rgba

    return restore


def _recolor_body(env, body, color, amount):
    """Recolor a body's visible geoms. A texture would only be multiplied by the new color (a red apple turns dark,
    not blue), so textured geoms drop their material and start from the texture's mean color."""
    m = env.model
    saved = {g: (m.geom_rgba[g].copy(), int(m.geom_matid[g])) for g in _visual_geoms(env, body)}
    for g, (rgba, matid) in saved.items():
        start = rgba[:3]
        if matid >= 0:
            texids = [t for t in m.mat_texid[matid] if t >= 0]
            start = m.mat_rgba[matid][:3] * (_texture_mean(env, texids[0]) if texids else 1.0)
            m.geom_matid[g] = -1
        m.geom_rgba[g][:3] = start * (1 - amount) + color * amount
        m.geom_rgba[g][3] = 1.0

    def restore(env):
        for g, (rgba, matid) in saved.items():
            env.model.geom_rgba[g], env.model.geom_matid[g] = rgba, matid

    return restore


def _in_workspace(p, margin=0.0):
    return WORKSPACE_X[0] + margin < p[0] < WORKSPACE_X[1] - margin and WORKSPACE_Y[0] + margin < p[1] < WORKSPACE_Y[1] - margin


def _shift_free(env, obj, rng, distance_m, tries=12):
    """Move a free object by `distance_m` in a random planar direction that keeps it in the workspace."""
    start = scene.position(env, obj)
    for _ in range(tries):
        offset = _direction(rng) * distance_m
        if _in_workspace(start[:2] + offset, margin=0.03):
            scene.shift(env, obj, offset)
            return offset
    offset = _direction(rng) * distance_m  # let the scene check reject it
    scene.shift(env, obj, offset)
    return offset


# ---------- scene layout ----------

@perturbation("target_shift", "Move target object", "cm", "scene", [0, 2, 4, 6, 8], max=8)
def target_shift(env, value, rng, target):
    """Moves the object to pick up by `value` cm in a random direction on the table. The core generalization test:
    does Dream-1 look where the object is, or replay a memorized motion?"""
    offset = _shift_free(env, target.obj, rng, value / 100) if value else np.zeros(2)
    return Effect(info={"offset": _fmt_vec(offset)})


@perturbation("target_rotate", "Rotate target object", "°", "scene", [0, 45, 90, 135, 180], max=180)
def target_rotate(env, value, rng, target):
    """Turns the object to pick up by `value` degrees around the vertical axis (random sign). Matters most for the
    banana; the apple and orange look nearly the same from every side."""
    angle = np.deg2rad(value) * rng.choice([-1, 1])
    joint = env.data.joint(scene.FREE_JOINTS[target.obj])
    turn = np.zeros(4)
    mujoco.mju_axisAngle2Quat(turn, np.array([0.0, 0.0, 1.0]), angle)
    result = np.zeros(4)
    mujoco.mju_mulQuat(result, turn, joint.qpos[3:7].copy())
    joint.qpos[3:7] = result
    joint.qvel[:] = 0
    return Effect(info={"yaw": f"{np.rad2deg(angle):+.0f}°"})


@perturbation("container_shift", "Move target container", "cm", "scene", [0, 3, 6, 9], max=9)
def container_shift(env, value, rng, target):
    """Moves the bowl/plate the object should go into by `value` cm. Tests whether the place location is read from
    the image or assumed."""
    body = env.model.body(target.container)
    original = body.pos.copy()
    offset = np.zeros(2)
    if value:
        for _ in range(12):
            offset = _direction(rng) * value / 100
            if _in_workspace(original[:2] + offset, margin=0.08):
                break
        body.pos[:2] = original[:2] + offset
        mujoco.mj_forward(env.model, env.data)

    def restore(env):
        env.model.body(target.container).pos[:] = original

    return Effect(restore=restore, info={"offset": _fmt_vec(offset)})


@perturbation("distractor_shift", "Move other objects", "cm", "scene", [0, 3, 6, 9], max=9)
def distractor_shift(env, value, rng, target):
    """Moves every object except the target by `value` cm, each in its own direction. A changed background layout
    should not change the grasp."""
    info = {}
    for obj in scene.OBJECTS:
        if obj != target.obj and value:
            info[obj] = _fmt_vec(_shift_free(env, obj, rng, value / 100))
    return Effect(info=info)


# ---------- vision ----------

@perturbation("camera_shift", "Shift overhead camera", "cm", "visual", [0, 1, 2, 4], max=4)
def camera_shift(env, value, rng, target):
    """Moves the overhead camera by `value` cm, like a camera mount that got bumped on a real station."""
    cam = env.model.camera("top")
    original = cam.pos.copy()
    offset = _direction(rng, 3) * value / 100
    cam.pos[:] = original + offset
    mujoco.mj_forward(env.model, env.data)  # camera poses in env.data are only updated by the kinematics

    def restore(env):
        env.model.camera("top").pos[:] = original
        mujoco.mj_forward(env.model, env.data)

    return Effect(restore=restore, info={"offset": _fmt_vec(offset)})


@perturbation("camera_tilt", "Tilt overhead camera", "°", "visual", [0, 2, 4, 8], max=8)
def camera_tilt(env, value, rng, target):
    """Tilts the overhead camera by `value` degrees around a random axis (mount drift, re-calibration error)."""
    cam = env.model.camera("top")
    original = cam.quat.copy()
    delta, result = np.zeros(4), np.zeros(4)
    mujoco.mju_axisAngle2Quat(delta, _direction(rng, 3), np.deg2rad(value))
    mujoco.mju_mulQuat(result, original, delta)
    cam.quat[:] = result
    mujoco.mj_forward(env.model, env.data)

    def restore(env):
        env.model.camera("top").quat[:] = original
        mujoco.mj_forward(env.model, env.data)

    return Effect(restore=restore)


@perturbation("light_dim", "Dim lights", "%", "visual", [0, 25, 50, 75], max=75)
def light_dim(env, value, rng, target):
    """Reduces all light (lamps, ambient and headlight) by `value` percent: a darker room than in training."""
    m = env.model
    saved = (m.light_diffuse.copy(), m.light_ambient.copy(), m.light_specular.copy(),
             m.vis.headlight.diffuse.copy(), m.vis.headlight.ambient.copy())
    k = 1 - value / 100
    m.light_diffuse[:] *= k
    m.light_ambient[:] *= k
    m.light_specular[:] *= k
    m.vis.headlight.diffuse[:] = saved[3] * k
    m.vis.headlight.ambient[:] = saved[4] * k

    def restore(env):
        m = env.model
        m.light_diffuse[:], m.light_ambient[:], m.light_specular[:] = saved[:3]
        m.vis.headlight.diffuse[:], m.vis.headlight.ambient[:] = saved[3], saved[4]

    return Effect(restore=restore)


@perturbation("table_color", "Change table color", "%", "visual", [0, 25, 50, 100], max=100)
def table_color(env, value, rng, target):
    """Tints the table toward a random color by `value` percent: a different workbench than in training."""
    color = _random_color(rng)
    mat = env.model.geom_matid[env.model.geom("table").id]
    restore = _tint(env, [], [mat], color, value / 100)
    return Effect(restore=restore, info={"color": "#" + "".join(f"{int(c * 255):02x}" for c in color)})


@perturbation("target_color", "Recolor target object", "%", "visual", [0, 25, 50, 100], max=100)
def target_color(env, value, rng, target):
    """Recolors the object to pick up toward a random color by `value` percent. Shows whether Dream-1 finds "the
    apple" by its color or by its shape. (Scanned fruit lose their texture detail as soon as value > 0.)"""
    color = _random_color(rng)
    restore = _recolor_body(env, target.obj, color, value / 100) if value else None
    return Effect(restore=restore, info={"color": "#" + "".join(f"{int(c * 255):02x}" for c in color)})


class _NoisyImages:
    """Wraps env.images(): adds pixel noise. A few pre-drawn noise frames, randomly picked and shifted per call, keep
    this cheap enough for the 20 Hz loop."""

    def __init__(self, env, sigma, rng):
        self.original, self.rng = env.images, rng
        self.sigma, self.bank = sigma, {}

    def __call__(self):
        images = self.original()
        out = {}
        for name, img in images.items():
            bank = self.bank.get(img.shape)
            if bank is None:
                bank = self.bank[img.shape] = [
                    np.clip(self.rng.normal(0, self.sigma, img.shape), -127, 127).astype(np.int16) for _ in range(4)]
            noise = np.roll(bank[self.rng.integers(len(bank))], self.rng.integers(img.shape[1]), axis=1)
            out[name] = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        return out


@perturbation("image_noise", "Camera noise", "σ", "visual", [0, 5, 10, 20], max=20)
def image_noise(env, value, rng, target):
    """Adds Gaussian pixel noise (standard deviation `value` of 255) to all three cameras: cheap or badly lit sensors.
    The robot-camera tiles in the dashboard show the noisy images, i.e. exactly what Dream-1 gets."""
    if not value:
        return None
    env.images = _NoisyImages(env, value, np.random.default_rng(rng.integers(1 << 32)))

    def restore(env):
        env.__dict__.pop("images", None)

    return Effect(restore=restore)


# ---------- physics ----------

@perturbation("target_mass", "Heavier target", "×", "physics", [1, 2, 4, 8], max=8, neutral=1)
def target_mass(env, value, rng, target):
    """Multiplies the mass of the object to pick up by `value` (e.g. a full instead of an empty bottle)."""
    body = env.model.body(target.obj)
    mass, inertia = body.mass.copy(), body.inertia.copy()
    body.mass[:] = mass * value
    body.inertia[:] = inertia * value
    # recompute derived constants (inverse weights) from the new mass; on scratch data, mj_setConst resets what it gets
    mujoco.mj_setConst(env.model, mujoco.MjData(env.model))

    def restore(env):
        b = env.model.body(target.obj)
        b.mass[:], b.inertia[:] = mass, inertia
        mujoco.mj_setConst(env.model, mujoco.MjData(env.model))

    return Effect(restore=restore)


@perturbation("grip_friction", "Slippery gripper pads", "%", "physics", [0, 50, 90, 98], max=98)
def grip_friction(env, value, rng, target):
    """Reduces the friction of all finger pads by `value` percent (worn pads, wet or oily object). The pads have
    contact priority, so their friction decides every grasp."""
    m = env.model
    tips = [g for g in range(m.ngeom) if (m.geom(g).name or "").split("_contact")[0].endswith(("tip_left", "tip_right"))]
    saved = {g: m.geom_friction[g].copy() for g in tips}
    for g, f in saved.items():
        m.geom_friction[g][0] = f[0] * (1 - value / 100)

    def restore(env):
        for g, f in saved.items():
            env.model.geom_friction[g] = f

    return Effect(restore=restore, info={"pads": len(tips)})


# ---------- language ----------

_KEYBOARD_NEIGHBOURS = {
    "a": "qwsz", "b": "vghn", "c": "xdfv", "d": "serfcx", "e": "wsdr", "f": "drtgvc", "g": "ftyhbv", "h": "gyujnb",
    "i": "ujko", "j": "huikmn", "k": "jiolm", "l": "kop", "m": "njk", "n": "bhjm", "o": "iklp", "p": "ol",
    "q": "wa", "r": "edft", "s": "awedxz", "t": "rfgy", "u": "yhji", "v": "cfgb", "w": "qase", "x": "zsdc",
    "y": "tghu", "z": "asx",
}


@perturbation("prompt_typos", "Typos in prompt", "%", "language", [0, 5, 10, 20], max=20, kind="text")
def prompt_typos(task, value, rng, target):
    """Introduces typos (neighbouring key, dropped, doubled or swapped letter) in `value` percent of the letters.
    Real users type fast."""
    chars = list(task)
    letters = [i for i, c in enumerate(chars) if c in string.ascii_letters]
    count = int(round(len(letters) * value / 100))
    for i in sorted(rng.choice(letters, size=min(count, len(letters)), replace=False), reverse=True):
        c = chars[i].lower()
        kind = rng.integers(4)
        if kind == 0:
            chars[i] = rng.choice(list(_KEYBOARD_NEIGHBOURS.get(c, c)))
        elif kind == 1:
            del chars[i]
        elif kind == 2:
            chars.insert(i, chars[i])
        elif i + 1 < len(chars):
            chars[i], chars[i + 1] = chars[i + 1], chars[i]
    return "".join(chars)


_DESCRIPTIONS = {"apple": "red fruit", "banana": "yellow fruit", "orange": "orange fruit", "water_bottle": "bottle"}
PARAPHRASES = [
    "{task}",
    "place the {obj} in the {container}",
    "could you please pick up the {obj} and put it into the {container}?",
    "{obj} -> {container}",
    "put the {description} into the {container}",
]


@perturbation("prompt_paraphrase", "Reword prompt", "#", "language", [0, 1, 2, 3, 4], max=4, discrete=True, kind="text")
def prompt_paraphrase(task, value, rng, target):
    """Says the same thing differently: 1 = synonyms, 2 = long and polite, 3 = terse "apple -> bowl", 4 = describes
    the object instead of naming it ("the red fruit")."""
    template = PARAPHRASES[int(np.clip(value, 0, len(PARAPHRASES) - 1))]
    obj = target.obj.replace("water_", "")
    return template.format(task=task, obj=obj, container=target.container,
                           description=_DESCRIPTIONS.get(target.obj, target.obj))


# ---------- during the run ----------

class _MidRunPush(Hooks):
    """Moves the target once, the moment a gripper comes close and before the object is lifted."""

    TRIGGER_M = 0.08

    def __init__(self, target, distance_m, rng, info):
        self.target, self.distance, self.rng, self.info = target, distance_m, rng, info
        self.fired, self.z0 = False, None

    def on_start(self, env, task, model):
        self.z0 = scene.position(env, self.target.obj)[2]

    def on_step(self, env, step, images):
        if self.fired or not self.distance or self.z0 is None:
            return
        p = scene.position(env, self.target.obj)
        if p[2] - self.z0 > 0.02:  # already lifted: too late, a push now would be a different test
            self.fired = True
            self.info["push"] = "not applied (object already lifted)"
            return
        reach = min(np.linalg.norm(env.data.site(f"{s}_tcp").xpos - p) for s in ("left", "right"))
        if reach < self.TRIGGER_M:
            self.fired = True
            offset = _shift_free(env, self.target.obj, self.rng, self.distance)
            mujoco.mj_forward(env.model, env.data)
            self.info["push"] = f"{_fmt_vec(offset)} at t={env.data.time:.1f}s"


@perturbation("mid_run_push", "Move target mid-grasp", "cm", "dynamic", [0, 3, 6, 9], max=9)
def mid_run_push(env, value, rng, target):
    """Moves the target by `value` cm at the moment a gripper gets within 8 cm of it. Tests closed-loop behaviour:
    does Dream-1 notice and re-grasp, or close on empty air?"""
    info = {}
    return Effect(hooks=[_MidRunPush(target, value / 100, rng, info)], info=info)


# ---------- setting up a trial ----------

class InvalidSetup(Exception):
    pass


def check_scene(env, target: Target) -> str | None:
    """Lets the scene settle for 0.5 s and returns a problem description, or None if the setup is a fair trial."""
    mujoco.mj_forward(env.model, env.data)
    before = {obj: scene.position(env, obj) for obj in scene.OBJECTS}
    hold = env.state()
    for _ in range(10):
        env.step(hold["left"], hold["right"])
    for obj in scene.OBJECTS:
        p = scene.position(env, obj)
        if p[2] < TABLE_Z or not (-0.6 < p[0] < 0.6 and -0.6 < p[1] < 0.4):
            return f"{obj} is off the table"
        if np.linalg.norm(p[:2] - before[obj][:2]) > 0.025:
            return f"{obj} was pushed by an overlap"
    c = scene.position(env, target.container)
    if not _in_workspace(c[:2]):
        return f"{target.container} is out of reach"
    if not _in_workspace(scene.position(env, target.obj)[:2]):
        return f"{target.obj} is out of reach"
    if scene.is_in(env, target.obj, target.container):
        return f"{target.obj} already in the {target.container}"
    for container in scene.CONTAINERS:
        r, _ = scene.CONTAINER_SIZE[container]
        for obj in scene.OBJECTS:
            if np.linalg.norm(scene.position(env, obj)[:2] - scene.position(env, container)[:2]) < r + 0.02:
                return f"{obj} lies in the {container}"
    return None


def prepare(env, items: list[tuple[Perturbation, float]], target: Target, seed: list[int], attempts: int = 8):
    """Resets the scene and applies all env perturbations; re-draws until the scene is a fair trial.

    @return (effects, attempt) — the effects to undo after the run and how many re-draws were needed.
    @raise InvalidSetup if no valid setup was found.
    """
    problem = None
    for attempt in range(attempts):
        env.reset()
        effects = []
        try:
            for p, value in items:
                rng = np.random.default_rng([*seed, attempt, p.seed_key()])
                effects.append(as_effect(p.fn(env, value, rng, target)))
            problem = check_scene(env, target)
        except Exception:
            for effect in reversed(effects):
                effect.undo(env)
            raise
        if problem is None:
            return effects, attempt
        for effect in reversed(effects):
            effect.undo(env)
    env.reset()
    raise InvalidSetup(problem)


def rewrite(task: str, items: list[tuple[Perturbation, float]], target: Target, seed: list[int]) -> str:
    """Applies all text perturbations (paraphrase first, then typos) and returns the prompt for Dream-1."""
    prompt = task
    for p, value in sorted(items, key=lambda item: item[0].id != "prompt_paraphrase"):
        prompt = p.fn(prompt, value, np.random.default_rng([*seed, p.seed_key()]), target)
    return prompt
