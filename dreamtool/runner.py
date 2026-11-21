"""Die Kontrollschleife: Dream-1 im Simulator laufen lassen, mit Hooks fuer dein eigenes Tool.

Ablauf (synchron, wie im offiziellen Beispiel):
  1. 9 Kamera-Frames pro Kamera sammeln (0.2 s Abstand in Simulationszeit)
  2. get_action() -> Action-Chunk (bis 48 Zeilen x 7 Werte pro Arm), Physik pausiert waehrenddessen
  3. Zeilen mit 20 Hz ausfuehren, dabei neue Frames an den Client geben
  4. wiederholen bis Zeit um, Erfolg erkannt oder ein Hook stoppt

Eigene Logik haengst du ueber eine `Hooks`-Unterklasse ein (Monitoring, Sicherheits-Checks, Metriken, UI ...).
"""

from __future__ import annotations

import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import dataclass, field

import numpy as np

from . import scene, sim


class Hooks:
    """Ueberschreibe, was du brauchst. Alle Methoden sind optional."""

    def on_start(self, env, task: str, model: str) -> None:
        """Vor dem ersten Request."""

    def on_reply(self, env, reply: dict, rtt_s: float) -> None:
        """Nach jedem get_action(): `reply["q_l_chunk"]`, `reply["q_r_chunk"]` sind [H, 7]-Chunks."""

    def on_step(self, env, step: int, images: dict[str, np.ndarray]) -> None:
        """Nach jedem 50-ms-Physikschritt. `images`: top/left/right RGB 360x640."""

    def on_wait(self, env) -> None:
        """Alle ~20 ms, waehrend auf die Antwort von Dream-1 gewartet wird (Physik pausiert)."""

    def should_stop(self, env) -> str | None:
        """Gib einen Grund (str) zurueck, um den Lauf zu beenden, sonst None."""
        return None

    def on_end(self, env, result: "RunResult") -> None:
        """Nach dem Lauf."""


@dataclass
class RunResult:
    task: str
    model: str
    stop_reason: str = "timeout"
    success: bool | None = None  # None = kein Erfolgs-Check fuer diesen Task bekannt
    steps: int = 0
    requests: int = 0
    rtts_s: list[float] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def mean_rtt_s(self) -> float | None:
        return sum(self.rtts_s) / len(self.rtts_s) if self.rtts_s else None


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
) -> RunResult:
    """Fuehrt einen Task mit Dream-1 im Simulator aus. Braucht einen API-Key (siehe README)."""
    hooks = hooks if isinstance(hooks, list) else [hooks] if hooks else []
    config = sim.settings()
    key = api_key or config.get("DREAM_API_KEY", "")
    if not key:
        raise RuntimeError("No API key: set DREAM_API_KEY or write ~/.dreamlabs/credentials (see README).")
    gateway = config.get("DREAM_GATEWAY_URL", "https://api.dreamlabs.ai")

    own_env = env is None
    env = env if env is not None else sim.YamEnv()
    check = scene.success_check(task)
    result = RunResult(task=task, model=model, success=False if check else None)
    log = print if verbose else (lambda *a, **k: None)
    policy = None
    started_at = time.monotonic()

    try:
        windows = {name: deque(maxlen=sim.FRAMES) for name in sim.VIDEO_ROLES}
        steps = 0
        while any(len(w) < sim.FRAMES for w in windows.values()):
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
            for h in hooks:
                h.on_start(env, task, model)
            poses = model in sim.POSE_MODELS
            policy = sim.open_policy(sim.policy_config(model, gateway, poses), key)
            sim.feed(policy, env, windows, task, model, steps, every=0, station=poses)
            deadline = time.monotonic() + seconds
            restarts = 0

            def stop_reason():
                if time.monotonic() >= deadline:
                    return "timeout"
                if view is not None and not view.is_running():
                    return "viewer closed"
                if check and check(env):
                    result.success = True
                    if stop_on_success:
                        return "success"
                for h in hooks:
                    reason = h.should_stop(env)
                    if reason:
                        return reason
                return None

            while (reason := stop_reason()) is None:
                t0 = time.monotonic()
                future = pool.submit(policy.get_action)
                while not future.done():  # Physik pausiert, Viewer bleibt bedienbar
                    if view is not None:
                        view.sync()
                    for h in hooks:
                        h.on_wait(env)
                    time.sleep(0.02)
                try:
                    reply = future.result()
                except Exception as error:
                    if type(error).__name__ == "DreamSessionExpired" and restarts < 3:
                        restarts += 1
                        continue
                    if poses or not sim.needs_poses(error):
                        raise
                    policy.close()
                    poses = True
                    policy = sim.open_policy(sim.policy_config(model, gateway, poses), key)
                    sim.feed(policy, env, windows, task, model, steps, every=0, station=poses)
                    continue
                restarts = 0
                rtt = time.monotonic() - t0
                result.requests += 1
                result.rtts_s.append(rtt)
                log(f"  Dream · RTT {rtt:.2f}s · Request {result.requests} · Schritt {steps}")
                for h in hooks:
                    h.on_reply(env, reply, rtt)

                left, right = sim.validate_chunk(env, reply, actions_per_reply, verbose=False)
                for l_row, r_row in zip(left, right):
                    if stop_reason() is not None:
                        break
                    tick = time.monotonic()
                    env.step(l_row, r_row)
                    kept = steps % sim.FRAME_EVERY_STEPS == 0
                    images = sim.capture(env, windows, keep=kept)
                    if kept:
                        sim.feed(policy, env, windows, task, model, steps, station=poses)
                    steps += 1
                    result.steps += 1
                    for h in hooks:
                        h.on_step(env, steps, images)
                    if view is not None:
                        view.sync()
                    time.sleep(max(0.0, 0.05 - (time.monotonic() - tick)))
            result.stop_reason = reason
    except KeyboardInterrupt:
        result.stop_reason = "interrupted"
    finally:
        if policy is not None:
            try:
                policy.close()
            except Exception:
                pass
        result.seconds = time.monotonic() - started_at
        for h in hooks:
            h.on_end(env, result)
        if own_env:
            env.close()
    return result


def run_scripted(env, targets, hooks: Hooks | list[Hooks] | None = None, realtime: bool = False):
    """Fuehrt eine Liste von (left, right)-Zielen ohne API aus. Gut zum Testen deiner Hooks offline."""
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
