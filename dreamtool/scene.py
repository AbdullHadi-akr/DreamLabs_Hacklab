"""Scene queries: where are the objects, and is a task done?

The simulator itself does not detect task success ("Task success is not automatically detected"). This is a first,
simple success check based on object positions. A good place to extend.
"""

from __future__ import annotations

import re

import numpy as np

## Movable objects and containers in the scene (MuJoCo body names).
OBJECTS = ("apple", "banana", "orange", "water_bottle")
CONTAINERS = ("bowl", "plate")

## Rough container size: planar radius (m) and max. height above the container base (m).
CONTAINER_SIZE = {"bowl": (0.075, 0.12), "plate": (0.065, 0.10)}

## Free joint of each movable object (the bottle's joint is not named after its body).
FREE_JOINTS = {"apple": "apple_free", "banana": "banana_free", "orange": "orange_free", "water_bottle": "bottle_free"}

## Words in the task text -> body names.
ALIASES = {"bottle": "water_bottle", "water": "water_bottle", "dish": "plate"}


def position(env, name: str) -> np.ndarray:
    """World position (x, y, z) of a body in meters."""
    return env.data.body(name).xpos.copy()


def positions(env) -> dict[str, np.ndarray]:
    """Positions of all objects and containers."""
    return {name: position(env, name) for name in (*OBJECTS, *CONTAINERS)}


def is_in(env, obj: str, container: str) -> bool:
    """Whether `obj` lies in/on `container`: close enough in the plane and just above it."""
    radius, height = CONTAINER_SIZE[container]
    o, c = position(env, obj), position(env, container)
    planar = np.linalg.norm(o[:2] - c[:2])
    above = o[2] - c[2]
    return bool(planar < radius and -0.01 < above < height)


def is_lifted(env, obj: str, start_z: float, threshold: float = 0.05) -> bool:
    """Whether `obj` is at least `threshold` meters above its start position."""
    return bool(position(env, obj)[2] - start_z > threshold)


def _name(word: str) -> str:
    word = word.lower()
    return ALIASES.get(word, word)


def parse_task(task: str) -> tuple[str, str] | None:
    """(object, container) from tasks of the form "put <object> into/in/on the <container>", else None."""
    match = re.search(r"put (?:the |an? )?(\w+) (?:into|in|onto|on) (?:the |a )?(\w+)", task.lower())
    if not match:
        return None
    obj, container = _name(match[1]), _name(match[2])
    if obj not in OBJECTS or container not in CONTAINERS:
        return None
    return obj, container


def success_check(task: str):
    """A success check for tasks that parse_task understands.

    @return Function env -> bool, or None if the task is not understood.
    """
    parsed = parse_task(task)
    if parsed is None:
        return None
    obj, container = parsed
    return lambda env: is_in(env, obj, container)


def place(env, obj: str, container: str, height: float = 0.04) -> None:
    """Debug: put `obj` right above `container` (free joint), e.g. to test success checks."""
    joint = env.data.joint(FREE_JOINTS[obj])
    joint.qpos[:3] = position(env, container) + np.array([0.0, 0.0, height])
    joint.qpos[3:7] = [1.0, 0.0, 0.0, 0.0]
    joint.qvel[:] = 0.0


def shift(env, obj: str, offset) -> None:
    """Move `obj` by `offset` (dx, dy[, dz]) in meters."""
    joint = env.data.joint(FREE_JOINTS[obj])
    offset = np.asarray(offset, dtype=float)
    joint.qpos[: len(offset)] += offset
    joint.qvel[:] = 0.0
