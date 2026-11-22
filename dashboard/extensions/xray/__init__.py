"""Model X-Ray: why Dream-1 does what it does (the analysis itself is dreamtool/xray.py).

- Live: during every Dream-1 run, each reply is turned into gripper paths and drawn into the 3D view (where the
  gripper goes, where it closes, what it is heading for). The moments of the run are kept, so one can be frozen.
- Frozen moments ("snapshots"): the current scene, or a moment of the last run. Three analyses ask Dream-1 about it
  again: intent (and its noise), where it looks (RISE heatmaps + camera reliance), language (object word swapped).

Results live in out/extensions/xray/<snapshot>/. DREAM_XRAY_FAKE=1 swaps Dream-1 for a scripted stand-in (no credits).
"""

from __future__ import annotations

import json
import os
import re
import threading
import time

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dashboard.extension import Extension, overlay_line, overlay_sphere
from dreamtool import sim, xray, xray_fake
from dreamtool.runner import Hooks

SNAPSHOT_ID = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")
MAX_MOMENTS = 12
COLORS = {"active": (1.0, 0.55, 0.15, 0.95), "other": (0.55, 0.55, 0.6, 0.6), "close": (0.9, 0.2, 0.2, 0.9),
          "open": (0.2, 0.75, 0.35, 0.9), "target": (1.0, 0.85, 0.2, 0.35)}


class SnapshotBody(BaseModel):
    prompt: str = Field(min_length=2, max_length=300)
    model: str = sim.BETA_MODEL


class RunBody(BaseModel):
    snapshot: str
    kind: str = Field(pattern="^(intent|rise|language)$")
    masks: int = Field(40, ge=8, le=200)
    repeats: int = Field(0, ge=0, le=5)  # 0 = the analysis' default
    workers: int = Field(1, ge=1, le=6)  # Dream-1 refuses parallel sessions when at capacity (measured)


class OverlayBody(BaseModel):
    enabled: bool = True
    snapshot: str | None = None  # show this snapshot's plan when no run is live


def _jsonable_reply(reply) -> dict:
    return {k: np.asarray(reply[k], float).round(5).tolist() for k in ("q_l_chunk", "q_r_chunk")}


class XRayHook(Hooks):
    """Keeps the camera window of a Dream-1 run and turns every reply into a live intent."""

    def __init__(self, ext, run):
        self.ext, self.run = ext, run
        self.window = xray.FrameWindow()
        self.steps = 0
        self.kin = None

    def on_start(self, env, task, model):
        self.kin = xray.Kinematics(env.model)
        self.ext.moments = []
        self.ext.live = None

    def on_step(self, env, step, images):
        self.steps += 1
        if self.steps % sim.FRAME_EVERY_STEPS == 0:
            self.window.add(images)

    def on_reply(self, env, reply, rtt_s):
        state = env.state()
        snap = xray.Snapshot(prompt=self.run.get("prompt") or self.run["task"], model=self.run["model"],
                             state={s: np.asarray(state[s], float).tolist() for s in ("left", "right")},
                             qpos=env.data.qpos.tolist(), windows=self.window.copy() if self.window.full else {},
                             steps=self.steps, source="run", reply=_jsonable_reply(reply))
        try:
            live = xray.intent(self.kin, snap, *xray.chunk(reply))
        except Exception as error:  # a malformed chunk must not end the run
            self.ext.ctx.log(f"X-Ray live intent: {error}", "warn")
            return
        live["seconds"] = round(self.steps / 20, 1)
        self.ext.live = live
        if snap.windows:
            self.ext.moments = (self.ext.moments + [{"snapshot": snap, "intent": live}])[-MAX_MOMENTS:]
        self.ext.ctx.emit("live", {"text": live["text"], "seconds": live["seconds"], "target": live["target"],
                                   "moments": self.ext.moment_list()}, keep=False)


class ModelXRay(Extension):
    title = "X-Ray"
    icon = ""
    description = "Why Dream-1 does what it does: planned path, where it looks, whether it follows the words"
    order = 30

    def setup(self):
        self.moments: list[dict] = []
        self.live: dict | None = None
        self.overlay = True
        self.overlay_snapshot: str | None = None
        self.job: dict | None = None
        self.stopping = False
        self.lock = threading.Lock()
        self.fake = os.environ.get("DREAM_XRAY_FAKE") == "1"

    # ---------- storage ----------

    def _dir(self, snap_id: str):
        if not SNAPSHOT_ID.match(snap_id or ""):
            raise HTTPException(404, "No such snapshot")
        return self.ctx.data_dir / snap_id

    def _load(self, snap_id: str) -> tuple[xray.Snapshot, dict]:
        folder = self._dir(snap_id)
        if not (folder / "snapshot.json").is_file():
            raise HTTPException(404, "No such snapshot")
        snap = xray.Snapshot.from_dict(json.loads((folder / "snapshot.json").read_text(encoding="utf-8")))
        results_file = folder / "results.json"
        results = json.loads(results_file.read_text(encoding="utf-8")) if results_file.is_file() else {}
        return snap, results

    def _save(self, snap: xray.Snapshot, results: dict | None = None) -> None:
        folder = self._dir(snap.id)
        folder.mkdir(parents=True, exist_ok=True)
        if not (folder / "snapshot.json").is_file():
            (folder / "snapshot.json").write_text(json.dumps(snap.to_dict()), encoding="utf-8")
        if results is not None:
            (folder / "results.json").write_text(json.dumps(results, default=float), encoding="utf-8")

    def _list(self) -> list[dict]:
        items = []
        for path in sorted(self.ctx.data_dir.glob("*/snapshot.json"), reverse=True)[:30]:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                results = path.parent / "results.json"
                done = list(json.loads(results.read_text(encoding="utf-8"))) if results.is_file() else []
            except Exception:
                continue
            items.append({"id": data["id"], "prompt": data["prompt"], "source": data.get("source", "scene"),
                          "seconds": round(data.get("steps", 0) / 20, 1), "created": data.get("created"), "done": done})
        return items

    def moment_list(self) -> list[dict]:
        return [{"index": i, "seconds": round(m["snapshot"].steps / 20, 1), "text": m["intent"]["text"],
                 "target": m["intent"]["target"]} for i, m in enumerate(self.moments)]

    def status(self) -> dict:
        return {"job": self.job, "snapshots": self._list(), "moments": self.moment_list(),
                "live": None if self.live is None else {k: self.live[k] for k in ("text", "seconds", "target")},
                "overlay": self.overlay, "overlay_snapshot": self.overlay_snapshot, "fake": self.fake,
                "has_api_key": bool(sim.settings().get("DREAM_API_KEY"))}

    # ---------- jobs ----------

    def _start(self, body: RunBody) -> None:
        snap, results = self._load(body.snapshot)
        if not snap.windows or any(len(snap.windows.get(c, [])) != sim.FRAMES for c in xray.CAMERAS):
            raise HTTPException(400, "This moment has no complete camera window.")
        if not self.fake and not sim.settings().get("DREAM_API_KEY"):
            raise HTTPException(400, "No API key: the X-Ray asks Dream-1 (or start the dashboard with DREAM_XRAY_FAKE=1).")
        with self.lock:
            if self.job and self.job["state"] == "running":
                raise HTTPException(409, "An X-Ray analysis is already running.")
            self.stopping = False
            self.job = {"snapshot": snap.id, "kind": body.kind, "state": "running", "done": 0, "total": 0,
                        "text": "opening Dream-1 sessions", "calls": 0, "started": time.time()}
        threading.Thread(target=self._run, args=(body, snap, results), daemon=True, name="xray").start()

    def _run(self, body: RunBody, snap: xray.Snapshot, results: dict) -> None:
        def progress(p):
            self.job.update(done=p["done"], total=p["total"], text=p["text"], calls=prober.calls)
            self.ctx.emit("job", self.job, keep=False)

        opener = xray_fake.open_fake if self.fake else xray.open_dream
        prober = xray.Prober(snap, opener, workers=body.workers, stopped=lambda: self.stopping)
        try:
            kin = self.ctx.sim.call(lambda env: xray.Kinematics(env.model)).result(timeout=30)
            if body.kind == "intent":
                result = xray.run_intent(prober, kin, repeats=body.repeats or 3, progress=progress)
            elif body.kind == "rise":
                result = xray.run_rise(prober, kin, masks=body.masks, repeats=body.repeats or 3, progress=progress)
            else:
                result = xray.run_language(prober, kin, repeats=body.repeats or 2, progress=progress)
            result.update(finished=time.time(), simulated=self.fake, options=body.model_dump())
            results[body.kind] = result
            self._save(snap, results)
            self.job.update(state="stopped" if self.stopping else "done", calls=prober.calls,
                            text=result.get("text") or result.get("intent", {}).get("text", ""))
            self.ctx.log(f"X-Ray {body.kind} on {snap.id}: {self.job['text']} ({prober.calls} Dream-1 calls)")
        except Exception as error:
            self.job.update(state="stopped" if self.stopping else "error", text=f"{type(error).__name__}: {error}",
                            calls=prober.calls)
            self.ctx.log(f"X-Ray {body.kind} failed: {error}", "error")
        self.ctx.emit("job", self.job)

    # ---------- HTTP ----------

    def router(self):
        r = APIRouter()

        @r.get("/status")
        def status():
            return self.status()

        @r.post("/snapshot")
        def snapshot(body: SnapshotBody):
            if self.ctx.sim.busy:
                raise HTTPException(409, "The simulation is busy. Freeze the scene between runs.")
            snap = self.ctx.sim.call(lambda env: xray.capture_scene(env, body.prompt, body.model)).result(timeout=60)
            self._save(snap)
            return {"id": snap.id, "status": self.status()}

        @r.post("/moments/{index}/keep")
        def keep(index: int):
            if not 0 <= index < len(self.moments):
                raise HTTPException(404, "No such moment")
            snap = self.moments[index]["snapshot"]
            self._save(snap)
            return {"id": snap.id, "status": self.status()}

        @r.get("/snapshots/{snap_id}")
        def get_snapshot(snap_id: str):
            snap, results = self._load(snap_id)
            return {**snap.summary(), "results": results}

        @r.delete("/snapshots/{snap_id}")
        def delete_snapshot(snap_id: str):
            folder = self._dir(snap_id)
            for name in ("snapshot.json", "results.json"):
                if (folder / name).is_file():
                    (folder / name).unlink()
            if folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()
            if self.overlay_snapshot == snap_id:
                self.overlay_snapshot = None
            return self.status()

        @r.post("/run")
        def run(body: RunBody):
            self._start(body)
            return self.job

        @r.post("/stop")
        def stop():
            self.stopping = True
            return {"ok": True}

        @r.post("/overlay")
        def overlay(body: OverlayBody):
            self.overlay = body.enabled
            self.overlay_snapshot = body.snapshot
            return self.status()

        return r

    # ---------- live + 3D ----------

    def run_hooks(self, run):
        if run.get("offline"):
            return None
        return XRayHook(self, run)

    def _shown_intent(self, env) -> dict | None:
        if not self.overlay:
            return None
        if self.ctx.sim.busy and self.live is not None:
            return self.live
        if self.overlay_snapshot:
            try:
                _, results = self._cached(self.overlay_snapshot)
                return (results.get("intent") or {}).get("intent")
            except Exception:
                return None
        return self.live

    _cache: dict = {}

    def _cached(self, snap_id):
        folder = self._dir(snap_id)
        path = folder / "results.json"
        mtime = path.stat().st_mtime if path.is_file() else 0
        hit = self._cache.get(snap_id)
        if hit is None or hit[0] != mtime:
            hit = (mtime, self._load(snap_id))
            self._cache[snap_id] = hit
        return hit[1]

    def decorate(self, env, scene):
        shown = self._shown_intent(env)
        if not shown:
            return
        for side, arm in shown["arms"].items():
            color = COLORS["active"] if side == shown["arm"] else COLORS["other"]
            points = [arm["start"], *arm["path"]]
            for a, b in zip(points[:-1], points[1:]):
                overlay_line(scene, a, b, width=4.0 if side == shown["arm"] else 2.0, rgba=color)
            overlay_sphere(scene, arm["path"][-1], radius=0.008, rgba=color)
        if shown.get("point"):
            overlay_sphere(scene, shown["point"], radius=0.014, rgba=COLORS["close" if shown["event"] == "close" else "open"])
        if shown.get("target"):
            overlay_sphere(scene, env.data.body(shown["target"]).xpos, radius=0.05, rgba=COLORS["target"])

    def shutdown(self):
        self.stopping = True
