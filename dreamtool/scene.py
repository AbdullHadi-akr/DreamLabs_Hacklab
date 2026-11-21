"""Szenen-Abfragen: wo liegen die Objekte, und ist eine Aufgabe geschafft?

Der Simulator selbst erkennt keinen Aufgaben-Erfolg ("Task success is not automatically detected"). Hier ist ein
erster, einfacher Erfolgs-Check auf Basis der Objekt-Positionen. Gute Stelle zum Ausbauen.
"""

from __future__ import annotations

import re

import numpy as np

## Bewegliche Objekte und Ablagen in der Szene (MuJoCo-Body-Namen).
OBJECTS = ("apple", "banana", "orange", "water_bottle")
CONTAINERS = ("bowl", "plate")

## Grobe Masse der Ablagen: Radius (m) in der Ebene und max. Hoehe ueber dem Boden der Ablage (m).
CONTAINER_SIZE = {"bowl": (0.075, 0.12), "plate": (0.065, 0.10)}

## Woerter im Task-Text -> Body-Namen.
ALIASES = {"bottle": "water_bottle", "water": "water_bottle", "dish": "plate"}


def position(env, name: str) -> np.ndarray:
    """Weltposition (x, y, z) eines Bodys in Metern."""
    return env.data.body(name).xpos.copy()


def positions(env) -> dict[str, np.ndarray]:
    """Positionen aller Objekte und Ablagen."""
    return {name: position(env, name) for name in (*OBJECTS, *CONTAINERS)}


def is_in(env, obj: str, container: str) -> bool:
    """Ob `obj` in/auf `container` liegt: nah genug in der Ebene und knapp darueber."""
    radius, height = CONTAINER_SIZE[container]
    o, c = position(env, obj), position(env, container)
    planar = np.linalg.norm(o[:2] - c[:2])
    above = o[2] - c[2]
    return bool(planar < radius and -0.01 < above < height)


def is_lifted(env, obj: str, start_z: float, threshold: float = 0.05) -> bool:
    """Ob `obj` mindestens `threshold` Meter ueber seiner Startposition ist."""
    return bool(position(env, obj)[2] - start_z > threshold)


def _name(word: str) -> str:
    word = word.lower()
    return ALIASES.get(word, word)


def parse_task(task: str) -> tuple[str, str] | None:
    """(objekt, ablage) aus Tasks der Form "put <objekt> into/in/on the <ablage>", sonst None."""
    match = re.search(r"put (?:the |an? )?(\w+) (?:into|in|onto|on) (?:the |a )?(\w+)", task.lower())
    if not match:
        return None
    obj, container = _name(match[1]), _name(match[2])
    if obj not in OBJECTS or container not in CONTAINERS:
        return None
    return obj, container


def success_check(task: str):
    """Ein Erfolgs-Check fuer Tasks, die parse_task versteht.

    @return Funktion env -> bool, oder None wenn der Task nicht verstanden wird.
    """
    parsed = parse_task(task)
    if parsed is None:
        return None
    obj, container = parsed
    return lambda env: is_in(env, obj, container)


def place(env, obj: str, container: str, height: float = 0.04) -> None:
    """Debug: `obj` direkt ueber `container` setzen (Freejoint), z. B. um Erfolgs-Checks zu testen."""
    joint = env.data.joint(f"{obj}_free")
    joint.qpos[:3] = position(env, container) + np.array([0.0, 0.0, height])
    joint.qpos[3:7] = [1.0, 0.0, 0.0, 0.0]
    joint.qvel[:] = 0.0


def shift(env, obj: str, offset) -> None:
    """`obj` um `offset` (dx, dy[, dz]) in Metern verschieben."""
    joint = env.data.joint(f"{obj}_free")
    offset = np.asarray(offset, dtype=float)
    joint.qpos[: len(offset)] += offset
    joint.qvel[:] = 0.0
