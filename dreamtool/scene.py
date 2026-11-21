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

## Words in the task text -> body names (English and German, singular and plural).
OBJECT_WORDS = {
    "apple": "apple", "apples": "apple", "apfel": "apple", "äpfel": "apple",
    "banana": "banana", "bananas": "banana", "banane": "banana", "bananen": "banana",
    "orange": "orange", "oranges": "orange", "orangen": "orange", "mandarine": "orange",
    "bottle": "water_bottle", "bottles": "water_bottle", "water": "water_bottle", "flasche": "water_bottle",
    "wasserflasche": "water_bottle",
}
CONTAINER_WORDS = {
    "bowl": "bowl", "bowls": "bowl", "schüssel": "bowl", "schuessel": "bowl", "schale": "bowl",
    "plate": "plate", "plates": "plate", "dish": "plate", "teller": "plate",
}
ALIASES = {**OBJECT_WORDS, **CONTAINER_WORDS}  # kept for older callers

## A container counts as the goal only right after one of these (with at most a few words in between) ...
_PLACE = {"into", "in", "onto", "on", "inside", "to", "->", "→", "auf", "rein", "hinein"}
## ... and not when the words in between say "next to / in front of / out of" etc.
_NOT_PLACE = {"front", "next", "behind", "beside", "near", "left", "right", "side", "away", "from", "out", "off",
              "under", "below", "beneath", "around", "between", "neben", "vor", "hinter", "unter", "aus", "von",
              "of"}


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


def _tokens(task: str) -> list[str]:
    text = task.lower()
    text = re.sub(r"\b(on )?top of\b", "on", text)  # "on top of the plate" = on the plate
    text = re.sub(r"\binside of\b", "inside", text)
    return re.findall(r"->|→|[a-zäöüß]+", text)


def _goal(tokens: list[str]) -> tuple[str, int] | None:
    """The goal container and the index of its placement word: the last container that follows a placement word."""
    for i in range(len(tokens) - 1, -1, -1):
        if tokens[i] not in CONTAINER_WORDS:
            continue
        for j in range(i - 1, max(-1, i - 5), -1):  # up to 3 words in between ("the big blue plate")
            word = tokens[j]
            if word in _NOT_PLACE:
                break
            if word in _PLACE:
                if j > 0 and tokens[j - 1] in _NOT_PLACE:  # "next to the bowl", "close to"
                    break
                return CONTAINER_WORDS[tokens[i]], j
    return None


def parse_task(task: str) -> tuple[str, str] | None:
    """(object, container) from a natural task, else None.

    Understands e.g. "put apple into the bowl", "Pick up the banana and put it on the green plate",
    "place the water bottle in the bowl", "move the apple from the plate to the bowl", "apple -> bowl",
    "Leg den Apfel in die Schüssel". The goal is the container after the last placement word (into, in, on, to,
    auf ...); the object is the first object named before it. Color/size words are ignored, and an object word used
    as an adjective ("the orange bowl") is not taken as the object.
    """
    tokens = _tokens(task)
    goal = _goal(tokens)
    if goal is None:
        return None
    container, place_at = goal
    for k, word in enumerate(tokens[:place_at]):
        if word not in OBJECT_WORDS:
            continue
        following = tokens[k + 1] if k + 1 < len(tokens) else ""
        if following in CONTAINER_WORDS:  # "the orange bowl": a color, not the orange
            continue
        if word == "water" and following not in ("bottle", "bottles", ""):
            continue  # "water" alone only counts in "water bottle"
        return OBJECT_WORDS[word], container
    return None


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
