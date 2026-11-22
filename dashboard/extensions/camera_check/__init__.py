"""Camera check: do the camera images reach Dream-1 correctly? (the checks themselves: dreamtool/camcheck.py)

- Live: every Dream-1 run is watched. Every request's frames, exactly as they were sent (DreamClient.on_round_trip),
  are compared with the truth rendered by the simulation: right camera on the right key, upright, natural colours,
  current (lag), not frozen, in order, readable, not blank. A light per camera, and the 9 frames the model saw.
- Self-test: a short Dream-1 run without a fault and one per fault injected on purpose (swapped wrists, BGR, upside
  down, frozen, delayed, black, zoomed, duplicated). The check has to name each one.
- Does Dream-1 use them? Asks Dream-1 about a frozen moment with each camera blanked and the wrists swapped.

Reports live in out/extensions/camera_check/.
"""

from __future__ import annotations

import json
import os
import threading
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dashboard.extension import Extension
from dreamtool import camcheck, sim, xray, xray_fake
from dreamtool.runner import Hooks


class SelfTestBody(BaseModel):
    task: str = Field("put the banana on the plate", min_length=2, max_length=300)
    seconds: float = Field(12, ge=5, le=60)  # simulated seconds per run
    faults: list[str] = Field(default_factory=lambda: list(camcheck.FAULTS))
    model: str = sim.BETA_MODEL


class ModelUseBody(BaseModel):
    prompt: str = Field("put the banana on the plate", min_length=2, max_length=300)
    model: str = sim.BETA_MODEL
    repeats: int = Field(3, ge=2, le=5)


class CameraHook(Hooks):
    def __init__(self, ext, watch: camcheck.CameraWatch, run: dict):
        self.ext, self.watch, self.run = ext, watch, run

    def on_step(self, env, step, images):
        self.watch.add_truth(images)

    def on_round_trip(self, trip):
        self.watch.round_trip(trip)

    def wrap_policy(self, policy):
        return camcheck.FaultyPolicy(policy, self.watch.fault) if self.watch.fault else policy

    def on_end(self, env, result):
        threading.Thread(target=self.ext.finished, args=(self.watch, self.run), daemon=True).start()


def _compact(trip: dict) -> dict:
    return {"index": trip.get("index"), "error": trip.get("error"), "cameras": {
        cam: {k: info.get(k) for k in ("status", "issues", "shows", "score", "transform", "lag_ms", "fps", "count", "size")}
        for cam, info in trip["cameras"].items()}}


class CameraCheck(Extension):
    title = "Cameras"
    icon = ""
    description = "Do the camera images reach Dream-1 correctly? Checked against the simulation's own renders"
    order = 25

    def setup(self):
        self.watch: camcheck.CameraWatch | None = None
        self.last_report: dict | None = None
        self.selftest: dict | None = None
        self.model_use: dict | None = None
        self.stopping = False
        self.fake = os.environ.get("DREAM_XRAY_FAKE") == "1"
        latest = sorted((self.ctx.data_dir / "runs").glob("*.json"), reverse=True)[:1] if (self.ctx.data_dir / "runs").is_dir() else []
        if latest:
            try:
                self.last_report = json.loads(latest[0].read_text(encoding="utf-8"))
            except Exception:
                pass

    # ---------- live ----------

    def run_hooks(self, run):
        if run.get("offline") or run.get("source") == self.ctx.id:
            return None  # the self-test brings its own hook
        self.watch = camcheck.CameraWatch(on_trip=lambda trip: self.ctx.emit("trip", _compact(trip), keep=False))
        return CameraHook(self, self.watch, run)

    def finished(self, watch: camcheck.CameraWatch, run: dict) -> dict:
        report = watch.finish()
        report.update(run={k: run.get(k) for k in ("id", "task", "model", "source", "label", "strategy")},
                      finished=time.time(), trips_detail=[_compact(t) for t in watch.trips])
        folder = self.ctx.data_dir / "runs"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{time.strftime('%Y%m%d-%H%M%S')}-{run.get('id', 0)}.json").write_text(
            json.dumps(report, default=float), encoding="utf-8")
        if run.get("source") != self.ctx.id:
            self.last_report = report
            self.ctx.emit("report", {k: report[k] for k in ("summary", "trips", "run")})
        return report

    # ---------- self-test ----------

    def _selftest(self, body: SelfTestBody):
        st = self.selftest
        try:
            for fault in [None, *body.faults]:
                if self.stopping:
                    break
                st["current"] = fault or "none"
                self.ctx.emit("selftest", st, keep=False)
                watch = camcheck.CameraWatch(fault=fault,
                                             on_trip=lambda trip: self.ctx.emit("trip", _compact(trip), keep=False))
                self.watch = watch  # the live cards show the self-test too
                run = {"id": 0, "task": body.task, "model": body.model, "source": self.ctx.id,
                       "label": f"Camera self-test: {camcheck.FAULTS.get(fault, 'no fault')}"}
                result = self.ctx.sim.run_task(
                    body.task, model=body.model, seconds=body.seconds * 6 + 60, max_steps=int(body.seconds * 20),
                    hooks=[CameraHook(self, watch, run)], source=self.ctx.id, label=run["label"]).result()
                report = self.finished(watch, run)
                summary = report["summary"]
                if fault is None:
                    row = {"fault": "none", "label": "No fault (baseline)",
                           "clean": all(s["status"] in ("ok", "unchecked") for s in summary.values()),
                           "issues": {c: s["issues"] for c, s in summary.items() if s["issues"]}}
                else:
                    others = {c: s["issues"] for c, s in summary.items() if s["issues"]}
                    row = {"fault": fault, "label": camcheck.FAULTS[fault], "detected": camcheck.detected(fault, summary),
                           "issues": others}
                row.update(trips=report["trips"], stop_reason=result.stop_reason,
                           lag_ms={c: s["lag_ms_median"] for c, s in summary.items()})
                st["rows"].append(row)
                self.ctx.emit("selftest", st, keep=False)
                if result.stop_reason.startswith("error"):
                    raise RuntimeError(result.stop_reason)
            faults = [r for r in st["rows"] if r["fault"] != "none"]
            st["caught"] = sum(r["detected"] for r in faults)
            st["of"] = len(faults)
            base = next((r for r in st["rows"] if r["fault"] == "none"), None)
            st["text"] = (f"Caught {st['caught']} of {st['of']} injected faults"
                          + ("; the clean run passed." if base and base["clean"] else
                             "; the clean run had findings too (see below)." if base else "."))
            st["state"] = "stopped" if self.stopping else "done"
        except Exception as error:
            st.update(state="error", text=f"{type(error).__name__}: {error}")
        st["current"] = None
        (self.ctx.data_dir / "selftests").mkdir(parents=True, exist_ok=True)
        (self.ctx.data_dir / "selftests" / f"{time.strftime('%Y%m%d-%H%M%S')}.json").write_text(
            json.dumps(st, default=float), encoding="utf-8")
        self.ctx.log(f"Camera self-test {st['state']}: {st.get('text', '')}")
        self.ctx.emit("selftest", st)

    # ---------- does the model use them ----------

    def _model_use(self, body: ModelUseBody):
        mu = self.model_use
        try:
            snap = self.ctx.sim.call(lambda env: xray.capture_scene(env, body.prompt, body.model)).result(timeout=60)
            kin = self.ctx.sim.call(lambda env: xray.Kinematics(env.model)).result(timeout=30)
            opener = xray_fake.open_fake if self.fake else xray.open_dream
            prober = xray.Prober(snap, opener, workers=1, stopped=lambda: self.stopping)

            def progress(p):
                mu.update(done=p["done"], total=p["total"])
                self.ctx.emit("model_use", mu, keep=False)

            mu.update(camcheck.model_uses_cameras(prober, kin, repeats=body.repeats, progress=progress),
                      state="done", snapshot=snap.id, frames={c: snap.windows[c][-1] for c in camcheck.CAMERAS})
        except Exception as error:
            if self.stopping:  # stopped on purpose: not an error
                mu.update(state="stopped", text="Stopped before Dream-1 answered every question.")
            else:
                mu.update(state="error", text=f"{type(error).__name__}: {error}")
        self.ctx.emit("model_use", mu)

    # ---------- HTTP ----------

    def router(self):
        r = APIRouter()

        @r.get("/status")
        def status():
            live = None
            if self.watch is not None:
                live = {"trips": len(self.watch.trips), "summary": camcheck.summarise(self.watch.trips),
                        "last": _compact(self.watch.trips[-1]) if self.watch.trips else None}
            return {"live": live, "report": None if self.last_report is None else
                    {k: self.last_report.get(k) for k in ("summary", "trips", "run", "finished")},
                    "selftest": self.selftest, "model_use": self.model_use, "faults": camcheck.FAULTS,
                    "fake": self.fake, "labels": camcheck.LABELS}

        @r.get("/last-trip")
        def last_trip():
            if self.watch is None or not self.watch.trips:
                return None  # no request seen yet (not an error: keeps the browser console clean)
            trip = self.watch.trips[-1]
            frames = self.watch.last_frames or {}
            out = {}
            for cam, info in trip["cameras"].items():
                key = info.get("key")
                out[cam] = {**{k: v for k, v in info.items() if k != "frames"},
                            "frames": [{**row, "jpeg": (frames.get(key) or [None] * 99)[row["index"]]}
                                       for row in info.get("frames", [])]}
            return {"index": trip["index"], "cameras": out}

        @r.post("/selftest")
        def selftest(body: SelfTestBody):
            unknown = [f for f in body.faults if f not in camcheck.FAULTS]
            if unknown:
                raise HTTPException(400, f"Unknown faults: {unknown}")
            if self.ctx.sim.busy or (self.selftest and self.selftest["state"] == "running"):
                raise HTTPException(409, "The simulation is busy.")
            if not sim.settings().get("DREAM_API_KEY"):
                raise HTTPException(400, "No API key: the self-test watches real Dream-1 requests.")
            self.stopping = False
            self.selftest = {"state": "running", "rows": [], "current": None, "task": body.task,
                             "total": len(body.faults) + 1, "started": time.time()}
            threading.Thread(target=self._selftest, args=(body,), daemon=True).start()
            return self.selftest

        @r.post("/model-use")
        def model_use(body: ModelUseBody):
            if self.ctx.sim.busy:
                raise HTTPException(409, "The simulation is busy. Run this between runs.")
            if self.model_use and self.model_use.get("state") == "running":
                raise HTTPException(409, "Already running.")
            if not self.fake and not sim.settings().get("DREAM_API_KEY"):
                raise HTTPException(400, "No API key.")
            self.stopping = False
            self.model_use = {"state": "running", "done": 0, "total": body.repeats + 4, "prompt": body.prompt}
            threading.Thread(target=self._model_use, args=(body,), daemon=True).start()
            return self.model_use

        @r.post("/stop")
        def stop():
            self.stopping = True
            self.ctx.sim.cancel_queued(self.ctx.id)
            self.ctx.sim.stop()
            return {"ok": True}

        return r

    def shutdown(self):
        self.stopping = True
