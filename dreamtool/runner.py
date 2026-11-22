"""The control loop: run Dream-1 in the simulator, with hooks for your own tool.

Flow (synchronous, like the official example):
  1. collect 9 camera frames per camera (0.2 s apart in simulated time)
  2. get_action() -> action chunk (up to 48 rows x 7 values per arm); physics pauses meanwhile
  3. execute the rows at 20 Hz while feeding new frames to the client (how many rows, and whether consecutive chunks
     are blended, is the inference strategy: see inference.py)
  4. repeat until time is up, success is detected or a hook stops the run

Plug in your own logic with a `Hooks` subclass (monitoring, safety checks, metrics, UI ...).
"""

from __future__ import annotations

import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import dataclass, field

import numpy as np

from . import inference, scene, sim

MAX_RETRY_WAIT_S = 180.0  # per run: longer than that at capacity and the run ends with the error

## How the Dream client should account for the time a request is in flight (`latency=`):
##   "paused"  the loop runs no rows meanwhile, which is the truth here: physics pauses during every request. The
##             client's seam smoothing then hands over from the old plan at row 0 of the new one.
##   "client"  the client's own default: it assumes the loop kept running at 20 rows/s and replaces the first
##             round-trip-many rows (about 11 at 0.55 s) of every new chunk with the rest of the old plan. In a paused
##             simulation that is an artificial reaction delay, and a random one, since the round trip varies.
LATENCY_MODES = ("paused", "client")
PAUSED_ACTION_HZ = 1e-3  # rows per second the client may assume during a request: round(rtt * 1e-3) = 0 rows


class Hooks:
    """Override what you need. All methods are optional."""

    def on_start(self, env, task: str, model: str) -> None:
        """Before the first request."""

    def on_reply(self, env, reply: dict, rtt_s: float) -> None:
        """After every get_action(): `reply["q_l_chunk"]`, `reply["q_r_chunk"]` are [H, 7] chunks."""

    def on_request(self, error: Exception | None, rtt_s: float) -> None:
        """When a managed inference attempt returns a reply or raises."""

    def on_step(self, env, step: int, images: dict[str, np.ndarray]) -> None:
        """After every 50 ms physics step. `images`: top/left/right RGB 360x640."""

    def on_wait(self, env) -> None:
        """Every ~20 ms while waiting for Dream-1's reply (physics paused)."""

    def should_stop(self, env) -> str | None:
        """Return a reason (str) to end the run, otherwise None."""
        return None

    def on_end(self, env, result: "RunResult") -> None:
        """After the run."""

    def wrap_policy(self, policy):
        """The client the run talks to, or a proxy around it (e.g. one that changes frames before they are sent)."""
        return policy

    def on_round_trip(self, trip) -> None:
        """After every get_action(), on the request thread (keep it short, never touch env): exactly what Dream-1 was
        sent and what came back (dream.debug_view.RoundTrip: `frames` key -> base64 JPEGs oldest first, `observation`,
        `action`, `error`)."""


@dataclass
class RunResult:
    task: str
    model: str
    stop_reason: str = "timeout"
    success: bool | None = None  # None = no success check known for this task
    steps: int = 0
    requests: int = 0
    strategy: str = "chunk"
    latency: str = "paused"
    retries: int = 0  # retryable refusals (Dream-1 at capacity) that were waited out
    commands: dict = field(default_factory=dict)  # smoothness of the executed commands (inference.CommandStats)
    rtts_s: list[float] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def mean_rtt_s(self) -> float | None:
        return sum(self.rtts_s) / len(self.rtts_s) if self.rtts_s else None


def _get_action(policy):
    """Time the SDK call on its worker thread, independently of rendering and polling."""
    started = time.monotonic()
    try:
        reply = policy.get_action()
    except Exception as exc:
        finished = time.monotonic()
        return None, exc, finished - started, finished
    finished = time.monotonic()
    return reply, None, finished - started, finished


def run_task(
    task: str,
    *,
    model: str = sim.BETA_MODEL,
    seconds: float = 60.0,
    actions_per_reply: int = 48,
    viewer: bool = False,
    hooks: Hooks | list[Hooks] | None = None,
    env=None,
    api_key: str | None = None,
    stop_on_success: bool = True,
    verbose: bool = True,
    prompt: str | None = None,
    max_requests: int | None = None,
    capture_each_step: bool = True,
    strategy: "str | inference.Strategy" = "chunk",
    max_steps: int | None = None,
    latency: str = "paused",
) -> RunResult:
    """Runs a task with Dream-1 in the simulator. Needs an API key (see README).

    `prompt` is the text Dream-1 receives (default: `task`). `task` still decides the success check, so a reworded
    or misspelled prompt is judged against the original goal.
    `strategy` decides how each action chunk is executed (inference.py). `latency` tells the client whether rows run
    while a request is in flight (LATENCY_MODES). `max_steps` ends the run after that many
    control steps (a budget in simulated time, independent of how long the requests take); `seconds` stays the
    wall-clock limit.
    """
    hooks = hooks if isinstance(hooks, list) else [hooks] if hooks else []
    config = sim.settings()
    key = api_key or config.get("DREAM_API_KEY", "")
    if not key:
        raise RuntimeError("No API key: set DREAM_API_KEY or write ~/.dreamlabs/credentials (see README).")
    gateway = config.get("DREAM_GATEWAY_URL", "https://api.dreamlabs.ai")

    own_env = env is None
    env = env if env is not None else sim.YamEnv()
    managed = max_requests is not None
    check = None if managed else scene.success_check(task)
    prompt = prompt or task
    strategy = inference.parse(strategy)
    executor = inference.ChunkExecutor(strategy, actions_per_reply)
    stats = inference.CommandStats()
    if latency not in LATENCY_MODES:
        raise ValueError(f"latency must be one of {LATENCY_MODES}")
    result = RunResult(task=task, model=model, success=False if check else None, strategy=strategy.id, latency=latency)
    log = print if verbose else (lambda *a, **k: None)
    policy = None
    started_at = time.monotonic()
    ended_at = None
    deadline = started_at + seconds

    def open_policy(poses):
        options = sim.policy_config(model, gateway, poses)
        if latency == "paused":
            options["action_hz"] = PAUSED_ACTION_HZ
        if managed:
            options["timeout_ms"] = min(15000, max(1, int(1000 * (deadline - time.monotonic()))))
        client = sim.open_policy(options, key)
        if hasattr(client, "on_round_trip"):
            for h in hooks:
                client.on_round_trip(h.on_round_trip)
        for h in hooks:
            client = h.wrap_policy(client)
        return client

    try:
        if managed:
            for h in hooks:
                h.on_start(env, task, model)
        windows = {name: deque(maxlen=sim.FRAMES) for name in sim.VIDEO_ROLES}
        steps = 0
        while any(len(w) < sim.FRAMES for w in windows.values()):
            if managed:
                reason = next((reason for h in hooks if (reason := h.should_stop(env))), None)
                if reason or time.monotonic() >= deadline:
                    result.stop_reason = reason or "task_deadline"
                    return result
            state = env.state()
            env.step(state["left"], state["right"])
            sim.capture(env, windows, keep=steps % sim.FRAME_EVERY_STEPS == 0)
            steps += 1

        viewer_ctx = nullcontext(None)
        if viewer:
            import mujoco.viewer

            viewer_ctx = mujoco.viewer.launch_passive(env.model, env.data, show_left_ui=False, show_right_ui=False)

        with viewer_ctx as view, ThreadPoolExecutor(max_workers=1) as pool:
            if view is not None:
                sim.aim_viewer(view)
            if not managed:
                for h in hooks:
                    h.on_start(env, task, model)
            poses = model in sim.POSE_MODELS
            policy = open_policy(poses)
            sim.feed(policy, env, windows, prompt, model, steps, every=0, station=poses)
            if not managed:
                deadline = time.monotonic() + seconds
            restarts = 0
            waited = 0.0  # seconds spent waiting on retryable refusals

            def stop_reason():
                if managed:
                    reason = next((reason for h in hooks if (reason := h.should_stop(env))), None)
                    if reason:
                        return reason
                if time.monotonic() >= deadline:
                    # with a simulated budget, running out of wall time first means the run was cut short (a hung
                    # request, a sleeping machine): not the same as using up the budget (measured 22.11.2026)
                    return "task_deadline" if managed else "wall_timeout" if max_steps is not None else "timeout"
                if max_steps is not None and result.steps >= max_steps:
                    return "timeout"
                if view is not None and not view.is_running():
                    return "viewer closed"
                if check and check(env):
                    result.success = True
                    if stop_on_success:
                        return "success"
                if not managed:
                    for h in hooks:
                        reason = h.should_stop(env)
                        if reason:
                            return reason
                return None

            while (reason := stop_reason()) is None:
                if managed and result.requests >= max_requests:
                    reason = "request_budget"
                    break
                future = pool.submit(_get_action, policy)
                pending_stop = None
                while not future.done():  # physics paused, viewer stays responsive
                    if managed and pending_stop is None and (pending_stop := stop_reason()):
                        ended_at = deadline if pending_stop == "task_deadline" else time.monotonic()
                    if view is not None:
                        view.sync()
                    for h in hooks:
                        h.on_wait(env)
                    time.sleep(0.02)
                reply, error, rtt, finished = future.result()
                if managed:
                    result.requests += 1
                    result.rtts_s.append(rtt)
                    for h in hooks:
                        h.on_request(error, rtt)
                    # A reply can finish after the deadline between two render polls.
                    if pending_stop is None and finished >= deadline:
                        pending_stop, ended_at = "task_deadline", deadline
                    if pending_stop:
                        reason = pending_stop
                        if error is None:
                            for h in hooks:
                                h.on_reply(env, reply, rtt)
                        break
                if error is not None:
                    if type(error).__name__ == "DreamSessionExpired" and restarts < 3:
                        restarts += 1
                        continue
                    # Dream Labs marks capacity refusals (pool_full, pool_warming, rate_limited) as retryable: wait and
                    # ask again with the same observation. Physics is paused meanwhile, so the run is not changed by it.
                    if getattr(error, "retryable", False) and waited < MAX_RETRY_WAIT_S:
                        pause = min(float(getattr(error, "retry_after_s", None) or 2.0), 15.0)
                        result.retries += 1
                        log(f"  Dream refused ({getattr(error, 'reason', type(error).__name__)}), retrying in {pause:.0f} s")
                        time.sleep(pause)
                        waited += pause
                        continue
                    if poses or not sim.needs_poses(error):
                        raise error
                    policy.close()
                    poses = True
                    policy = open_policy(poses)
                    sim.feed(policy, env, windows, prompt, model, steps, every=0, station=poses)
                    continue
                restarts = 0
                if not managed:
                    result.requests += 1
                    result.rtts_s.append(rtt)
                log(f"  Dream · RTT {rtt:.2f}s · request {result.requests} · step {steps}")
                for h in hooks:
                    h.on_reply(env, reply, rtt)

                left, right = sim.validate_chunk(env, reply, inference.CHUNK, verbose=False)
                left, right = executor.plan(result.steps, left, right)
                for row, (l_row, r_row) in enumerate(zip(left, right)):
                    if stop_reason() is not None:
                        break
                    tick = time.monotonic()
                    env.step(l_row, r_row)
                    stats.add(l_row, r_row, seam=row == 0)
                    kept = steps % sim.FRAME_EVERY_STEPS == 0
                    images = sim.capture(env, windows, keep=kept) if kept or capture_each_step else {}
                    if kept:
                        sim.feed(policy, env, windows, prompt, model, steps, station=poses)
                    steps += 1
                    result.steps += 1
                    for h in hooks:
                        h.on_step(env, steps, images)
                    if managed and stop_reason() is not None:
                        break
                    if view is not None:
                        view.sync()
                    time.sleep(max(0.0, 0.05 - (time.monotonic() - tick)))
            result.stop_reason = reason
            if managed and reason in ("success", "task_completed"):
                result.success = True
    except KeyboardInterrupt:
        result.stop_reason = "interrupted"
    except Exception as error:
        if not managed:
            raise
        if isinstance(error, TimeoutError) or getattr(error, "reason", None) == "queue_timeout":
            result.stop_reason = "api_timeout"
        else:
            result.stop_reason = f"error: {type(error).__name__}: {error}"
    finally:
        result.commands = stats.summary()
        if managed:
            if result.stop_reason == "task_deadline":
                ended_at = deadline
            result.seconds = (ended_at if ended_at is not None else time.monotonic()) - started_at
        if policy is not None:
            try:
                policy.close()
            except Exception:
                pass
        if not managed:
            result.seconds = time.monotonic() - started_at
        for h in hooks:
            h.on_end(env, result)
        if own_env:
            env.close()
    return result


def run_scripted(env, targets, hooks: Hooks | list[Hooks] | None = None, realtime: bool = False):
    """Executes a list of (left, right) targets without the API. Good for testing your hooks offline."""
    hooks = hooks if isinstance(hooks, list) else [hooks] if hooks else []
    for step, (left, right) in enumerate(targets, 1):
        if any(h.should_stop(env) for h in hooks):
            return "stopped"
        tick = time.monotonic()
        env.step(left, right)
        images = env.images() if any(type(h).on_step is not Hooks.on_step for h in hooks) else {}
        for h in hooks:
            h.on_step(env, step, images)
        if realtime:
            time.sleep(max(0.0, 0.05 - (time.monotonic() - tick)))
    return "done"
