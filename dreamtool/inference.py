"""Inference strategies: how the action chunks Dream-1 returns become motor commands.

Dream-1 plans up to 48 steps (2.4 s at 20 Hz) per request. How much of that plan is executed before asking again, and
how consecutive plans are combined, is a choice on our side: it changes behaviour without touching the model.

  chunk         execute the whole chunk, then ask again (the official example; open loop for 2.4 s)
  receding-N    execute the first N rows, throw the rest away, ask again with fresh frames (receding horizon, MPC
                style): reacts faster to what the cameras see, but every new plan may start somewhere else -> seams
  ensemble-N    ask every N steps and average every chunk that still covers a step (temporal ensembling as in ACT).
                A prediction made k steps ahead gets the weight exp(-decay * k), so the fresh plan weighs most. The
                ratio between two plans stays the same along the window: this averages out plan-to-plan noise and
                shrinks seams, at the price of following a new plan only partly (lag).
  crossfade-N   ask every N steps and fade linearly from the previous plan to the new one over the N executed rows:
                the first row is almost the old command (no seam), the last one is the new plan alone (no lag
                beyond the window).

Blending only touches the arm joints. The gripper always follows the newest plan: an average of "open" and "closed"
is a half-closed gripper that lets the object slip (seen with Dream-1: ensemble-16 lifted the apple and lost it on
the way in 3 of 4 trials before this rule).

Physics pauses while a request is in flight, so asking more often costs wall time and API calls, not simulated time.

CommandStats measures what the strategy does to the commands: the jump at each seam between two executions (compared
with a normal step inside a chunk), the speed, the absolute jerk and the jitter share (Smoothness). Absolute jerk
alone mostly measures speed: a strategy that slows the arm down looks "smooth" without being any less shaky.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

import numpy as np

CHUNK = 48
HZ = 20
DEFAULT_DECAY = 0.05
## What the dashboard runs unless told otherwise, and the menu (default first). Measured on 22.11.2026 with real Dream-1
## (measurements/2026-11-22, NIGHTLY_REPORT.md): against the full chunk on the same scenes, crossfade-30 succeeded in 9
## pairs where the chunk failed and never the other way round (32 pairs, McNemar p = 0.004, progress +0.36
## [+0.24, +0.48]); the full chunk mostly never grasps. Horizons of 8 and 16 rows were no better or worse than the
## chunk, so they are left out of the menu (parse() still takes any "<kind>-<rows>").
DEFAULT = "crossfade-30"
PRESETS = [DEFAULT, "chunk", "receding-24", "receding-30", "crossfade-24", "receding-16", "ensemble-16", "crossfade-16"]
BLENDS = {"receding": "none", "ensemble": "ensemble", "crossfade": "crossfade"}
_PATTERN = re.compile(r"^(receding|ensemble|crossfade)-(\d{1,2})$")


@dataclass(frozen=True)
class Strategy:
    id: str = "chunk"
    execute: int = CHUNK  # rows executed per request
    blend: str = "none"  # none | ensemble | crossfade
    decay: float = DEFAULT_DECAY  # ensemble: weight = exp(-decay * steps ahead)

    @property
    def ensemble(self) -> bool:
        return self.blend == "ensemble"

    @property
    def label(self) -> str:
        if self.id == "chunk":
            return "Full chunk (48)"
        name = {"none": "Receding horizon", "ensemble": "Temporal ensemble", "crossfade": "Crossfade"}[self.blend]
        return f"{name} ({self.execute})"

    @property
    def description(self) -> str:
        seconds = self.execute / HZ
        if self.id == "chunk":
            return "Executes all 48 planned steps (2.4 s) before asking Dream-1 again. Default behaviour."
        factor = "~{:.0f}× the requests".format(CHUNK / self.execute)
        if self.blend == "ensemble":
            return (f"Asks every {self.execute} steps ({seconds:g} s) and averages the arm joints of all plans that "
                    "cover a step (fresh predictions weigh more; the gripper follows the newest plan). Averages out "
                    f"plan noise, follows new plans with lag and can slow the arm down. {factor}.")
        if self.blend == "crossfade":
            return (f"Asks every {self.execute} steps ({seconds:g} s) and fades the arm joints from the previous plan "
                    f"to the new one over those steps (the gripper follows the new plan). No seam jumps, fully on the "
                    f"new plan after {seconds:g} s. {factor}.")
        return (f"Asks every {self.execute} steps ({seconds:g} s) and executes only the start of each new plan. "
                f"Reacts faster, but every new plan may start somewhere else. {factor}.")

    def describe(self) -> dict:
        return {"id": self.id, "label": self.label, "description": self.description, "execute": self.execute,
                "blend": self.blend, "requests_factor": round(CHUNK / self.execute, 1),
                "gripper": "newest plan"}  # results without this key averaged the gripper too


def parse(value: "str | Strategy | None") -> Strategy:
    """'chunk', 'receding-N', 'ensemble-N' or 'crossfade-N' (1 <= N <= 48) -> Strategy. Raises ValueError otherwise."""
    if isinstance(value, Strategy):
        return value
    text = (value or "chunk").strip().lower()
    if text in ("chunk", "receding-48"):
        return Strategy()
    m = _PATTERN.match(text)
    if not m or not 1 <= int(m.group(2)) <= CHUNK:
        raise ValueError(f"Unknown inference strategy {value!r}: use chunk, receding-N, ensemble-N or crossfade-N "
                         "(N = 1..48).")
    n = int(m.group(2))
    if m.group(1) == "receding" and n == CHUNK:
        return Strategy()
    return Strategy(id=f"{m.group(1)}-{n}", execute=n, blend=BLENDS[m.group(1)])


def is_valid(value: str) -> bool:
    try:
        parse(value)
        return True
    except ValueError:
        return False


class ChunkExecutor:
    """Turns each new chunk into the rows to execute next. Steps are absolute control steps since the run started."""

    def __init__(self, strategy: "str | Strategy" = "chunk", limit: int = CHUNK):
        self.strategy = parse(strategy)
        self.execute = max(1, min(self.strategy.execute, limit))
        self.predictions: list[tuple[int, np.ndarray, np.ndarray]] = []  # (step the chunk starts at, left, right)

    def plan(self, step: int, left: np.ndarray, right: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        left, right = np.asarray(left, dtype=float), np.asarray(right, dtype=float)
        n = min(self.execute, len(left))
        blend = self.strategy.blend
        if blend == "none":
            return left[:n], right[:n]
        # keep only plans that still reach into the future, then add the new one
        self.predictions = [p for p in self.predictions if p[0] + len(p[1]) > step]
        previous = self.predictions[-1] if self.predictions else None
        self.predictions.append((step, left, right))
        if blend == "crossfade":
            out_l, out_r = left[:n].copy(), right[:n].copy()
            if previous is not None:
                start, pl, pr = previous
                for k in range(n):
                    i = step + k - start
                    if i >= len(pl):
                        break  # the old plan ends here: the new one alone
                    a = (k + 1) / n
                    out_l[k] = (1 - a) * pl[i] + a * left[k]
                    out_r[k] = (1 - a) * pr[i] + a * right[k]
            return _newest_gripper(out_l, left), _newest_gripper(out_r, right)
        out_l, out_r = np.empty((n, left.shape[1])), np.empty((n, right.shape[1]))
        for k, t in enumerate(range(step, step + n)):
            weights, ls, rs = [], [], []
            for start, pl, pr in self.predictions:
                i = t - start
                if 0 <= i < len(pl):
                    weights.append(math.exp(-self.strategy.decay * i))
                    ls.append(pl[i])
                    rs.append(pr[i])
            w = np.asarray(weights) / sum(weights)
            out_l[k], out_r[k] = w @ np.asarray(ls), w @ np.asarray(rs)
        return _newest_gripper(out_l, left), _newest_gripper(out_r, right)


def _newest_gripper(rows: np.ndarray, newest: np.ndarray) -> np.ndarray:
    """Blends are for the arm joints only: the gripper command comes from the newest plan unchanged."""
    rows[:, 6] = newest[:len(rows), 6]
    return rows


class Smoothness:
    """Speed, jerk and jitter of a joint trajectory sampled at 20 Hz.

    jitter = RMS velocity of what is left after a 0.45 s moving average / RMS velocity of the whole motion: the share of
    the motion that is shaking (seams between plans, plan-to-plan noise) rather than going somewhere. 0 = perfectly
    smooth, 1 = nothing but shaking. A path driven slower with the same shaking scores worse, never better.
    Absolute jerk is reported too, but it mostly measures speed: an arm that moves slower looks "smooth".
    """

    WINDOW = 9  # steps of the moving average (0.45 s): slower than any seam, faster than a reach

    def __init__(self):
        self.rows: list[np.ndarray] = []

    def add(self, q) -> None:
        self.rows.append(np.asarray(q, dtype=float))

    def summary(self) -> dict:
        out = {"speed": None, "jerk": None, "jitter": None}
        if len(self.rows) < 4:
            return out
        q = np.asarray(self.rows)
        rms = lambda x: float(np.sqrt(np.mean(x ** 2)))  # noqa: E731
        speed = rms(np.diff(q, axis=0)) * HZ
        out["speed"] = round(speed, 4)
        out["jerk"] = round(rms(np.diff(q, n=3, axis=0)) * HZ ** 3, 2)
        w = self.WINDOW
        if len(q) > w + 2 and speed > 1e-3:
            kernel = np.ones(w) / w
            smooth = np.column_stack([np.convolve(q[:, j], kernel, mode="valid") for j in range(q.shape[1])])
            inner = q[w // 2: len(q) - w // 2]
            out["jitter"] = round(rms(np.diff(inner - smooth, axis=0)) / rms(np.diff(inner, axis=0)), 3)
        return out


class CommandStats:
    """Smoothness of the executed command stream. Call add() for every executed row, seam=True for the first row of
    each new execution (the first one of a run is not a seam: there is nothing before it)."""

    def __init__(self):
        self.previous: np.ndarray | None = None  # last row (arm joints of both arms)
        self.seam_jumps: list[float] = []
        self.inner_steps: list[float] = []
        self.motion = Smoothness()
        self.rows = 0
        self.executions = 0

    @staticmethod
    def _arms(left, right) -> np.ndarray:
        return np.r_[np.asarray(left, dtype=float)[:6], np.asarray(right, dtype=float)[:6]]

    def add(self, left, right, seam: bool = False):
        row = self._arms(left, right)
        if seam or not self.rows:
            self.executions += 1
        if self.previous is not None:
            delta = float(np.max(np.abs(row - self.previous)))
            (self.seam_jumps if seam else self.inner_steps).append(delta)
        self.previous = row
        self.motion.add(row)
        self.rows += 1

    def summary(self) -> dict:
        typical = float(np.median(self.inner_steps)) if self.inner_steps else None
        mean_seam = float(np.mean(self.seam_jumps)) if self.seam_jumps else None
        motion = self.motion.summary()
        return {
            "rows": self.rows,
            "executions": self.executions,
            "seams": len(self.seam_jumps),
            "seam_jump_rad": None if mean_seam is None else round(mean_seam, 4),
            "max_seam_jump_rad": round(max(self.seam_jumps), 4) if self.seam_jumps else None,
            "typical_step_rad": None if typical is None else round(typical, 4),
            # how much bigger a seam is than a normal step inside a chunk (1 = invisible seam)
            "seam_ratio": round(mean_seam / typical, 2) if mean_seam is not None and typical else None,
            # commanded arm joints: RMS speed (rad/s), RMS jerk (rad/s^3) and the share that is jitter (Smoothness)
            "command_speed": motion["speed"],
            "command_jerk": motion["jerk"],
            "command_jitter": motion["jitter"],
        }


def simulated_chunks(plan: list, strategy: "str | Strategy", seed, noise_rad: float = 0.03,
                     drift_rad: float = 0.004) -> tuple[list, dict]:
    """Dry run: what a strategy makes of a policy whose consecutive plans disagree.

    The "policy" is the scripted plan; each simulated request returns the next 48 rows of it plus noise that is fixed
    per request (an offset of `noise_rad`) and grows along the chunk (a random walk of `drift_rad` per step), like two
    plans of a real model that agree in spirit but not in detail. Seeded per start step, so two strategies that ask
    at the same step get the same plan.
    @return (rows to execute as (left, right) pairs, CommandStats summary)
    """
    executor = ChunkExecutor(strategy)
    stats = CommandStats()
    rows: list = []
    step = 0
    total = len(plan)
    while step < total:
        rng = np.random.default_rng([*np.atleast_1d(seed).tolist(), step])
        chunk = []
        for side in (0, 1):
            base = np.array([plan[min(step + i, total - 1)][side] for i in range(CHUNK)], dtype=float)
            offset = rng.normal(0, noise_rad, 7)
            walk = np.cumsum(rng.normal(0, drift_rad, (CHUNK, 7)), axis=0)
            noisy = base + offset + walk
            noisy[:, 6] = base[:, 6]  # keep the gripper command exact: the noise is about where the arm goes
            chunk.append(noisy)
        left, right = executor.plan(step, chunk[0], chunk[1])
        for i, (l_row, r_row) in enumerate(zip(left, right)):
            if step >= total:
                break
            stats.add(l_row, r_row, seam=i == 0 and step > 0)
            rows.append((l_row, r_row))
            step += 1
    return rows, stats.summary()
