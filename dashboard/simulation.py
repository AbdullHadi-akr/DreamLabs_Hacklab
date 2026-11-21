"""Der Sim-Worker: EIN Thread besitzt die MuJoCo-Welt, die Renderer und die Dream-1-Laeufe.

MuJoCo-Daten und OpenGL-Kontexte sind nicht thread-sicher. Deshalb fasst nur dieser Thread `env` an. Alle
anderen (HTTP-Handler, Extensions) schicken Auftraege:

    sim.call(lambda env: ...)        -> Future   beliebiger Code auf dem Sim-Thread (zwischen Laeufen)
    sim.run_task("put apple ...")    -> Future[RunResult]   ein Lauf (live mit Dream-1 oder offline)
    sim.stop()                       bricht den aktuellen Lauf ab

Zwischen den Laeufen haelt die Sim die Arme in ihrer letzten Pose und rendert weiter, damit das Dashboard lebt.
"""

from __future__ import annotations

import dataclasses
import queue
import threading
import time
import traceback
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Callable

import cv2
import mujoco
import numpy as np

from dreamtool import runner, scene, sim
from dreamtool.runner import Hooks, RunResult

## Hauptansicht (frei drehbare Kamera) und die drei Roboter-Kameras.
MAIN_SIZE = (960, 540)
MAIN_FPS = 25
CAM_SIZE = (320, 180)
CAM_FPS = 10
STATE_HZ = 10
JPEG_QUALITY = 80
CAMERAS = ("top", "left", "right")


class OrbitCamera:
    """Freie Kamera der Hauptansicht; der Browser dreht/zoomt sie, der Sim-Thread rendert damit."""

    DEFAULT = {"lookat": [0.0, 0.0, 0.85], "distance": 1.45, "azimuth": 90.0, "elevation": -32.0}

    def __init__(self):
        self._lock = threading.Lock()
        self._values = {k: (list(v) if isinstance(v, list) else v) for k, v in self.DEFAULT.items()}

    def update(self, **values) -> dict:
        with self._lock:
            for key in ("distance", "azimuth", "elevation"):
                if values.get(key) is not None:
                    self._values[key] = float(values[key])
            if values.get("lookat") is not None and len(values["lookat"]) == 3:
                self._values["lookat"] = [float(v) for v in values["lookat"]]
            self._values["distance"] = float(np.clip(self._values["distance"], 0.2, 6.0))
            self._values["elevation"] = float(np.clip(self._values["elevation"], -89.0, 89.0))
            return dict(self._values)

    def reset(self) -> dict:
        return self.update(**self.DEFAULT)

    def get(self) -> dict:
        with self._lock:
            return dict(self._values)

    def apply(self, cam: mujoco.MjvCamera) -> None:
        values = self.get()
        cam.type = mujoco.mjtCamera.mjCAMERA_FREE
        cam.lookat[:] = values["lookat"]
        cam.distance, cam.azimuth, cam.elevation = values["distance"], values["azimuth"], values["elevation"]


@dataclass
class RunRequest:
    task: str
    model: str = sim.BETA_MODEL
    seconds: float = 60.0
    offline: bool = False
    targets: Callable | list | None = None  # offline: Liste von (left, right) oder Funktion env -> Liste
    setup: Callable | None = None  # env -> None, vor dem Lauf auf dem Sim-Thread
    teardown: Callable | None = None  # env -> None, nach dem Lauf (auch bei Fehlern)
    hooks: list = field(default_factory=list)
    stop_on_success: bool = True
    source: str = "core"  # wer den Lauf gestartet hat (core oder Extension-ID)
    label: str = ""
    id: int = 0


def result_dict(result: RunResult) -> dict:
    data = dataclasses.asdict(result)
    data["mean_rtt_s"] = result.mean_rtt_s
    return data


def demo_motion(env) -> list:
    """Offline-Testbewegung (ohne API): beide Arme winken kurz, dann zurueck nach Hause."""
    rows = [np.r_[0.0, 0.6 * np.sin(t / 15), 0.5, 0.0, 0.0, 0.0, 0.5 + 0.5 * np.cos(t / 10)] for t in range(120)]
    start = [(row, row) for row in rows]
    last = {"left": rows[-1], "right": rows[-1]}
    return start + sim.home_path(last, seconds=2.0)


class _CoreHook(Hooks):
    """Verbindet einen Lauf mit dem Dashboard: Frames, Events, Stop-Knopf."""

    def __init__(self, worker: "SimWorker", request: RunRequest):
        self.worker, self.request = worker, request

    def on_reply(self, env, reply, rtt_s):
        self.worker.run_stats["requests"] += 1
        self.worker.run_stats["last_rtt_s"] = rtt_s
        rows = len(reply.get("q_l_chunk", []))
        self.worker.bus.emit("run.reply", {"id": self.request.id, "rtt_s": rtt_s, "rows": rows})

    def on_step(self, env, step, images):
        self.worker.run_stats["steps"] = step
        self.worker.publish(images or None)

    def on_wait(self, env):
        self.worker.publish()

    def should_stop(self, env):
        if self.worker.stop_event.is_set() or self.worker.shutdown_event.is_set():
            return "stopped"
        return None


class SimWorker(threading.Thread):
    def __init__(self, bus, extensions: list | None = None):
        super().__init__(name="sim-worker", daemon=True)
        self.bus = bus
        self.extensions = extensions or []
        self.camera = OrbitCamera()
        self.jobs: queue.Queue = queue.Queue()
        self.ready = threading.Event()
        self.stop_event = threading.Event()
        self.shutdown_event = threading.Event()
        self.frames: dict[str, tuple[int, bytes]] = {}
        self.state_snapshot: dict = {}
        self.current: RunRequest | None = None
        self.run_stats: dict = {}
        self.error: str | None = None
        self._run_ids = 0
        self._last = {"main": 0.0, "cams": 0.0, "state": 0.0}
        self._seq = 0
        self.env = None

    # ---------- oeffentliche, thread-sichere API ----------

    def call(self, fn: Callable) -> Future:
        """fn(env) auf dem Sim-Thread ausfuehren (zwischen Laeufen). Ergebnis/Exception kommt ueber das Future."""
        future: Future = Future()
        self.jobs.put(("call", fn, future))
        return future

    def run_task(self, task: str, **options) -> Future:
        """Einen Lauf einreihen. Optionen siehe RunRequest. Liefert Future[RunResult]."""
        self._run_ids += 1
        request = RunRequest(task=task, id=self._run_ids, **options)
        future: Future = Future()
        self.jobs.put(("run", request, future))
        self.bus.emit("run.queued", {"id": request.id, "task": task, "source": request.source, "label": request.label})
        return future

    def stop(self) -> None:
        """Aktuellen Lauf abbrechen (bei Dream-1: nach der laufenden Antwort)."""
        if self.current is not None:
            self.stop_event.set()

    def cancel_queued(self, source: str | None = None) -> int:
        """Wartende Laeufe (optional nur einer Quelle) verwerfen."""
        kept, dropped = [], 0
        while True:
            try:
                job = self.jobs.get_nowait()
            except queue.Empty:
                break
            if job[0] == "run" and (source is None or job[1].source == source):
                job[2].cancel()
                dropped += 1
                self.bus.emit("run.cancelled", {"id": job[1].id, "task": job[1].task, "source": job[1].source,
                                                "label": job[1].label})
            else:
                kept.append(job)
        for job in kept:
            self.jobs.put(job)
        return dropped

    @property
    def busy(self) -> bool:
        return self.current is not None or any(job[0] == "run" for job in list(self.jobs.queue))

    def status(self) -> dict:
        run = None
        if self.current is not None:
            r = self.current
            run = {"id": r.id, "task": r.task, "model": "offline" if r.offline else r.model, "source": r.source,
                   "label": r.label, **self.run_stats}
        queued = sum(1 for job in list(self.jobs.queue) if job[0] == "run")
        return {"ready": self.ready.is_set(), "error": self.error, "running": run is not None, "run": run,
                "queued": queued}

    def shutdown(self) -> None:
        self.shutdown_event.set()
        self.stop_event.set()

    # ---------- Sim-Thread ----------

    def run(self):
        try:
            self.env = sim.YamEnv()
            g = self.env.model.vis.global_
            g.offwidth, g.offheight = max(g.offwidth, MAIN_SIZE[0]), max(g.offheight, MAIN_SIZE[1])
            self.main_renderer = mujoco.Renderer(self.env.model, height=MAIN_SIZE[1], width=MAIN_SIZE[0])
            self.main_cam = mujoco.MjvCamera()
            self.hold = self.env.state()
            self.ready.set()
            self.bus.log("Simulation bereit.")
        except Exception as error:
            self.error = f"{type(error).__name__}: {error}"
            self.ready.set()
            self.bus.log(f"Simulation konnte nicht starten: {self.error}", "error")
            return

        while not self.shutdown_event.is_set():
            try:
                job = self.jobs.get(timeout=0.0)
            except queue.Empty:
                job = None
            if job is not None:
                if job[0] == "call":
                    self._execute_call(job[1], job[2])
                elif job[2].set_running_or_notify_cancel():
                    self._execute_run(job[1], job[2])
                continue
            tick = time.monotonic()
            self.env.step(self.hold["left"], self.hold["right"])
            self.publish()
            time.sleep(max(0.0, 0.05 - (time.monotonic() - tick)))

        self.env.close()
        self.main_renderer.close()

    def _execute_call(self, fn, future: Future):
        if not future.set_running_or_notify_cancel():
            return
        try:
            future.set_result(fn(self.env))
        except Exception as error:
            future.set_exception(error)
        self.hold = self.env.state()
        self.publish(force=True)

    def _execute_run(self, request: RunRequest, future: Future):
        env = self.env
        self.stop_event.clear()
        self.current = request
        self.run_stats = {"steps": 0, "requests": 0, "last_rtt_s": None, "started": time.time()}
        info = {"id": request.id, "task": request.task, "model": "offline" if request.offline else request.model,
                "offline": request.offline, "source": request.source, "label": request.label}
        self.bus.emit("run.started", info)
        hooks = [_CoreHook(self, request)]
        for ext in self.extensions:
            try:
                hook = ext.run_hooks(info)
                if hook is not None:
                    hooks.append(hook)
            except Exception:
                self.bus.log(f"run_hooks von {ext.id} fehlgeschlagen:\n{traceback.format_exc()}", "error", ext.id)
        hooks.extend(request.hooks)
        hooks = [_SafeHook(h, self.bus) if not isinstance(h, _CoreHook) else h for h in hooks]

        result = RunResult(task=request.task, model=info["model"])
        try:
            if request.setup:
                request.setup(env)
            if request.offline:
                targets = request.targets(env) if callable(request.targets) else request.targets
                targets = targets if targets is not None else demo_motion(env)
                check = scene.success_check(request.task)
                started = time.monotonic()
                for h in hooks:
                    h.on_start(env, request.task, "offline")
                result.stop_reason = runner.run_scripted(env, targets, hooks=hooks, realtime=True)
                result.steps = self.run_stats["steps"]
                result.seconds = time.monotonic() - started
                result.success = bool(check(env)) if check else None
                for h in hooks:
                    h.on_end(env, result)
            else:
                result = runner.run_task(
                    request.task, model=request.model, seconds=request.seconds, env=env, hooks=hooks,
                    viewer=False, verbose=False, stop_on_success=request.stop_on_success,
                )
        except Exception as error:
            result.stop_reason = f"error: {type(error).__name__}: {error}"
            self.bus.log(f"Lauf fehlgeschlagen: {error}", "error", request.source)
        finally:
            if request.teardown:
                try:
                    request.teardown(env)
                except Exception as error:
                    self.bus.log(f"teardown fehlgeschlagen: {error}", "error", request.source)
            self.hold = env.state()
            self.current = None
            self.stop_event.clear()
        self.bus.emit("run.ended", {**info, "result": result_dict(result)})
        future.set_result(result)
        self.publish(force=True)

    # ---------- Rendering & Status ----------

    def publish(self, images: dict | None = None, force: bool = False) -> None:
        """Rendert (gedrosselt) Hauptansicht + Kameras und sendet den Sim-Zustand. Nur auf dem Sim-Thread."""
        now = time.monotonic()
        if force or now - self._last["main"] >= 1 / MAIN_FPS:
            self._last["main"] = now
            self.camera.apply(self.main_cam)
            self.main_renderer.update_scene(self.env.data, camera=self.main_cam)
            for ext in self.extensions:
                try:
                    ext.decorate(self.env, self.main_renderer.scene)
                except Exception as error:
                    self.bus.log(f"decorate von {ext.id}: {error}", "error", ext.id)
            self._store("main", self.main_renderer.render())
        if force or now - self._last["cams"] >= 1 / CAM_FPS:
            self._last["cams"] = now
            images = images or self.env.images()
            for name in CAMERAS:
                self._store(name, cv2.resize(images[name], CAM_SIZE, interpolation=cv2.INTER_AREA))
        if force or now - self._last["state"] >= 1 / STATE_HZ:
            self._last["state"] = now
            state = self.env.state()
            self.state_snapshot = {
                "time": float(self.env.data.time),
                "arms": {side: values.round(4).tolist() for side, values in state.items()},
                "objects": {name: pos.round(4).tolist() for name, pos in scene.positions(self.env).items()},
                "status": self.status(),
            }
            self.bus.emit("sim.state", self.state_snapshot, keep=False)

    def _store(self, name: str, rgb: np.ndarray) -> None:
        ok, jpeg = cv2.imencode(".jpg", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if ok:
            self._seq += 1
            self.frames[name] = (self._seq, jpeg.tobytes())


class _SafeHook(Hooks):
    """Faengt Fehler in Extension-Hooks ab, damit ein Bug in einer Extension keinen Lauf abbricht."""

    def __init__(self, inner: Hooks, bus):
        self.inner, self.bus, self.failed = inner, bus, set()

    def _call(self, name, *args):
        if name in self.failed:
            return None
        try:
            return getattr(self.inner, name)(*args)
        except Exception:
            self.failed.add(name)
            self.bus.log(f"Hook {type(self.inner).__name__}.{name} deaktiviert:\n{traceback.format_exc()}", "error")
            return None

    def on_start(self, *a): self._call("on_start", *a)  # noqa: E704
    def on_reply(self, *a): self._call("on_reply", *a)  # noqa: E704
    def on_step(self, *a): self._call("on_step", *a)  # noqa: E704
    def on_wait(self, *a): self._call("on_wait", *a)  # noqa: E704
    def should_stop(self, *a): return self._call("should_stop", *a)  # noqa: E704
    def on_end(self, *a): self._call("on_end", *a)  # noqa: E704
