"""Scene queries: where are the objects, and is a task done?

The simulator itself does not detect task success ("Task success is not automatically detected"). The success check
here reads object positions. It understands the task types in RULES; a new task type is one more entry there
(a pattern for the task text and a function that builds the check). Two tasks joined by "then" must happen in order.

A check is a callable env -> bool. Some rules compare with the start of the task (lift, push, take out of), so the
FIRST call of a check stores the start state: call it once when the task starts (the run loop does this before the
first step; the recorder when an episode starts).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

import numpy as np

## Movable objects and containers in the scene (MuJoCo body names).
OBJECTS = ("apple", "banana", "orange", "water_bottle")
CONTAINERS = ("bowl", "plate")
FRUIT = ("apple", "banana", "orange")

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
ALIASES = {**OBJECT_WORDS, **CONTAINER_WORDS, "fruits": "fruit"}

## A container counts as the goal only right after one of these (with at most a few words in between) ...
_PLACE = {"into", "in", "onto", "on", "inside", "to", "->", "→", "auf", "rein", "hinein"}
## ... and not when the words in between say "next to / in front of / out of" etc.
_NOT_PLACE = {"front", "next", "behind", "beside", "near", "left", "right", "side", "away", "from", "out", "off",
              "under", "below", "beneath", "around", "between", "neben", "vor", "hinter", "unter", "aus", "von",
              "of"}

## Directions as the robot sees them (its overhead camera looks along -y; its left arm is on the +x side).
DIRECTIONS = {
    "forward": (0.0, -1.0), "away": (0.0, -1.0),
    "back": (0.0, 1.0), "backward": (0.0, 1.0), "backwards": (0.0, 1.0), "toward": (0.0, 1.0),
    "left": (1.0, 0.0), "right": (-1.0, 0.0),
}

TABLE_TOP_Z = 0.76
LIFT_M = 0.05  # lifted: at least 5 cm above its start height
PUSH_M = 0.08  # pushed: at least 8 cm in the asked direction (default when the task names no distance)
NEXT_TO_M = (0.03, 0.15)  # next to: centres 3 to 15 cm apart in the plane, and not in or on the other
STACK_PLANAR_M = 0.06  # stacked: centres closer than 6 cm in the plane, and the top one higher
UPRIGHT_DEG = 20  # upright: its own up axis within 20 degrees of straight up


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


def is_lifted(env, obj: str, start_z: float, threshold: float = LIFT_M) -> bool:
    """Whether `obj` is at least `threshold` meters above its start position."""
    return bool(position(env, obj)[2] - start_z > threshold)


def _tokens(task: str) -> list[str]:
    text = task.lower()
    text = re.sub(r"\b(on )?top of\b", "on", text)  # "on top of the plate" = on the plate
    text = re.sub(r"\binside of\b", "inside", text)
    return re.findall(r"->|→|[a-zäöüß]+", text)


## Words that negate the task ("do not put ...", "don't", "never", German "nicht"/"kein").
_NEGATION = {"not", "never", "dont", "nicht", "kein", "keine", "niemals"}
## Actions after the goal change the final state ("... and then remove it"): no single goal to measure.
_LATER_ACTION = {"then", "remove", "take", "lift", "pick", "move", "put", "place", "drop", "back", "again",
                 "dann", "danach", "wieder", "nimm", "nehme"}


def _goal(tokens: list[str]) -> tuple[str, int, int] | None:
    """(container, index of its placement word, index of the container word): the last container that follows a
    placement word."""
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
                return CONTAINER_WORDS[tokens[i]], j, i
    return None
def is_upright(env, obj: str, max_deg: float = UPRIGHT_DEG) -> bool:
    """Whether the object's own z axis (up in the start scene) points within `max_deg` of straight up."""
    up = env.data.body(obj).xmat.reshape(3, 3)[:, 2]
    return bool(up[2] >= np.cos(np.radians(max_deg)))


def _name(word: str) -> str:
    word = word.lower()
    return ALIASES.get(word, word)


# ---------------------------------------------------------------------------------------------------------------------
# Rules: one entry per task type. Each has a pattern and a builder: match -> check, or None if the words in the match
# are not objects of the scene. The FIRST matching rule wins, so specific rules come before general ones.
# ---------------------------------------------------------------------------------------------------------------------

class Check:
    """A success check. The first call stores the start state (`start`), every call answers done or not."""

    def __init__(self, text: str, done: Callable, remember: Callable | None = None):
        self.text, self._done, self._remember, self.start = text, done, remember, None

    def __call__(self, env) -> bool:
        if self.start is None:
            self.start = self._remember(env) if self._remember else {}
        return bool(self._done(env, self.start))

    def __repr__(self):
        return f"Check({self.text!r})"


@dataclass
class Rule:
    id: str
    example: str
    description: str
    pattern: str
    build: Callable  # (match) -> Check | None


OBJ = r"(?:the |an? )?(\w+)"


def _obj(word):
    name = _name(word)
    return name if name in OBJECTS else None


def _container(word):
    name = _name(word)
    return name if name in CONTAINERS else None


def _thing(word):
    """An object or a container (for 'next to' and 'stack on')."""
    name = _name(word)
    return name if name in OBJECTS or name in CONTAINERS else None


def _all_fruit_in(m):
    container = _container(m[1])
    if not container:
        return None
    return Check(m[0], lambda env, s: all(is_in(env, f, container) for f in FRUIT))


def _take_out(m):
    obj, container = _obj(m[1]), _container(m[2])
    if not (obj and container):
        return None
    return Check(m[0], lambda env, s: not is_in(env, obj, container) and position(env, obj)[2] < TABLE_TOP_Z + 0.08)


def _put_in(m):
    obj, container = _obj(m[1]), _container(m[2])
    if not (obj and container):
        return None
    return Check(m[0], lambda env, s: is_in(env, obj, container))


def _stack(m):
    top, bottom = _obj(m[1]), _obj(m[2])  # "place X on the plate" is put_in, not stack
    if not (top and bottom) or top == bottom:
        return None

    def done(env, s):
        a, b = position(env, top), position(env, bottom)
        return np.linalg.norm(a[:2] - b[:2]) < STACK_PLANAR_M and a[2] > b[2] + 0.02 and a[2] > TABLE_TOP_Z + 0.04
    return Check(m[0], done)


def _next_to(m):
    obj, other = _obj(m[1]), _thing(m[2])
    if not (obj and other) or obj == other:
        return None

    def done(env, s):
        a, b = position(env, obj), position(env, other)
        planar = np.linalg.norm(a[:2] - b[:2])
        inside = other in CONTAINERS and is_in(env, obj, other)
        return NEXT_TO_M[0] < planar < NEXT_TO_M[1] and not inside and a[2] < TABLE_TOP_Z + 0.08
    return Check(m[0], done)


def _push(m):
    obj, direction = _obj(m[1]), DIRECTIONS.get(m[2].lower())
    if not (obj and direction):
        return None
    distance = float(m[3]) / 100 if m[3] else PUSH_M
    unit = np.array(direction)

    def done(env, s):
        moved = position(env, obj)[:2] - s["pos"][:2]
        return float(moved @ unit) >= distance and position(env, obj)[2] < TABLE_TOP_Z + 0.08
    return Check(m[0], done, lambda env: {"pos": position(env, obj)})


def _lift(m):
    obj = _obj(m[1])
    if not obj:
        return None
    return Check(m[0], lambda env, s: is_lifted(env, obj, s["z"]), lambda env: {"z": position(env, obj)[2]})


def _upright(m):
    obj = _obj(m[1])
    if not obj:
        return None
    return Check(m[0], lambda env, s: is_upright(env, obj) and position(env, obj)[2] < TABLE_TOP_Z + 0.15)


RULES: list[Rule] = [
    Rule("all_fruit_in", "put all fruit in the bowl", "apple, banana and orange are all in or on the container",
         r"put all (?:the )?fruits? (?:into|in|onto|on) " + OBJ, _all_fruit_in),
    Rule("take_out", "take the apple out of the bowl", "the object is no longer in the container and lies low",
         r"(?:take|get|remove) " + OBJ + r" (?:out of|from) " + OBJ, _take_out),
    Rule("stack", "stack the orange on the apple", "the object rests on top of the other one",
         r"(?:stack|place) " + OBJ + r" (?:on top of|onto|on) " + OBJ, _stack),
    Rule("put_in", "put the banana on the plate", "the object is in or on the container (natural sentences and "
         "German work too, for example 'Leg den Apfel in die Schüssel')",
         r"(?:put|place) " + OBJ + r" (?:into|in|onto|on) " + OBJ, _put_in),
    Rule("next_to", "put the apple next to the bowl", "3 to 15 cm apart, not in it, on the table",
         r"(?:put|place|move) " + OBJ + r" (?:next to|beside|near) " + OBJ, _next_to),
    Rule("push", "push the orange left", "moved at least 8 cm (or the given cm) in the direction, as the robot sees it",
         r"push " + OBJ + r" (?:to the )?(forward|away|backwards?|back|toward|left|right)(?: by (\d+) ?cm)?", _push),
    Rule("lift", "lift the apple", "at least 5 cm above where it started",
         r"(?:lift|pick up|raise) " + OBJ, _lift),
    Rule("upright", "stand the bottle upright", "its own up axis within 20 degrees of straight up",
         r"(?:stand|set|put) " + OBJ + r" (?:up ?right|upright|up)", _upright),
]


def _single(task: str) -> Check | None:
    # Placement first, with the natural-language parser: otherwise "pick up the banana and put it on the plate"
    # would match the lift rule ("pick up the banana") and count as done once the banana is in the air.
    placement = parse_task(task)
    if placement is not None:
        obj, container = placement
        return Check(task, lambda env, s: is_in(env, obj, container))
    text = task.lower().strip()
    for rule in RULES:
        match = re.search(rule.pattern, text)
        if match:
            check = rule.build(match)
            if check is not None:
                return check
    return None


def _in_order(task: str):
    """'<task one>, then <task two>': both must succeed, the second after the first."""
    parts = re.split(r",? (?:and )?then ", task.lower())
    if len(parts) != 2:
        return None
    first, second = _single(parts[0]), _single(parts[1])
    if first is None or second is None:
        return None

    def remember(env):
        first(env), second(env)  # both store their own start state now
        return {"first_done": False}

    def done(env, s):
        if not s["first_done"]:
            s["first_done"] = first(env)
            return False
        return second(env)
    return Check(task, done, remember)


def success_check(task: str):
    """The success check for a task, or None when no rule understands the task (then success stays unknown)."""
    return _in_order(task) or _single(task)


def describe_rules() -> list[dict]:
    """The task types the success check understands, for the dashboard."""
    rows = [{"id": r.id, "example": r.example, "description": r.description} for r in RULES]
    rows.append({"id": "in_order", "example": "put the apple in the bowl, then put the orange on the plate",
                 "description": "two tasks joined by 'then': the second must succeed after the first"})
    return rows


def parse_task(task: str) -> tuple[str, str] | None:
    """(object, container) from a natural task, else None.

    Understands e.g. "put apple into the bowl", "Pick up the banana and put it on the green plate",
    "place the water bottle in the bowl", "move the apple from the plate to the bowl", "apple -> bowl",
    "Leg den Apfel in die Schüssel". The goal is the container after the last placement word (into, in, on, to,
    auf ...); the object is the first object named before it. Color/size words are ignored, and an object word used
    as an adjective ("the orange bowl") is not taken as the object.

    Returns None when the goal cannot be measured: negated tasks ("Do not place the apple in the bowl") and tasks
    that act again after placing ("Put the banana on the plate and then remove it").
    The success check uses it first for "put / place X in or on Y" tasks; the other task types go to RULES.
    """
    tokens = _tokens(task.replace("n't", " not").replace("n’t", " not"))
    if _NEGATION & set(tokens):
        return None
    goal = _goal(tokens)
    if goal is None:
        return None
    container, place_at, container_at = goal
    if _LATER_ACTION & set(tokens[container_at + 1:]):
        return None
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
