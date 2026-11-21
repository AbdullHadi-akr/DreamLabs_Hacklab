"""Perturbations for the robustness test. New perturbation = one function decorated with @perturbation.

Signature:  fn(env, value, rng, target) -> restore | None
  env     YamEnv (right after env.reset())
  value   strength in the given unit (e.g. cm or degrees)
  rng     numpy Generator (reproducible per trial)
  target  target object from the task (e.g. "apple") or None
  restore optional: function env -> None that undoes changes to the model (cameras, lights ...).
          Object positions need no restoring; the next env.reset() takes care of that.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import mujoco
import numpy as np

from dreamtool import scene


@dataclass
class Perturbation:
    id: str
    label: str
    unit: str
    defaults: list[float]
    description: str
    apply: Callable


REGISTRY: dict[str, Perturbation] = {}


def perturbation(id: str, label: str, unit: str, defaults: list[float], description: str = ""):
    def register(fn):
        REGISTRY[id] = Perturbation(id, label, unit, defaults, description or (fn.__doc__ or "").strip().replace("`", ""), fn)
        return fn

    return register


def _random_direction(rng, dims=2):
    v = rng.normal(size=dims)
    return v / (np.linalg.norm(v) or 1.0)


@perturbation("object_shift", "Shift target object", "cm", [0, 2, 4, 6, 8])
def object_shift(env, value, rng, target):
    """Moves the target object by `value` cm in a random direction on the table."""
    scene.shift(env, target or "apple", _random_direction(rng) * value / 100)


@perturbation("all_objects_shift", "Shift all objects", "cm", [0, 2, 4, 6])
def all_objects_shift(env, value, rng, target):
    """Moves every movable object independently by `value` cm."""
    for obj in scene.OBJECTS:
        scene.shift(env, obj, _random_direction(rng) * value / 100)


@perturbation("camera_shift", "Shift overhead camera", "cm", [0, 1, 2, 4])
def camera_shift(env, value, rng, target):
    """Moves the overhead camera, like a badly mounted camera on a real robot."""
    cam = env.model.camera("top")
    original = cam.pos.copy()
    cam.pos[:] = original + _random_direction(rng, 3) * value / 100

    def restore(env):
        env.model.camera("top").pos[:] = original

    return restore


@perturbation("camera_tilt", "Tilt overhead camera", "°", [0, 2, 4, 8])
def camera_tilt(env, value, rng, target):
    """Tilts the overhead camera by `value` degrees around a random axis."""
    cam = env.model.camera("top")
    original = cam.quat.copy()
    axis = _random_direction(rng, 3)
    delta = np.zeros(4)
    mujoco.mju_axisAngle2Quat(delta, axis, np.deg2rad(value))
    result = np.zeros(4)
    mujoco.mju_mulQuat(result, original, delta)
    cam.quat[:] = result

    def restore(env):
        env.model.camera("top").quat[:] = original

    return restore


@perturbation("light_dim", "Dim lights", "%", [0, 25, 50, 75])
def light_dim(env, value, rng, target):
    """Reduces the brightness of all lights by `value` percent."""
    original = env.model.light_diffuse.copy()
    env.model.light_diffuse[:] = original * (1 - value / 100)

    def restore(env):
        env.model.light_diffuse[:] = original

    return restore
