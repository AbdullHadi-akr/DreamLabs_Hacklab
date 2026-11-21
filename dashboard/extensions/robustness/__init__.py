"""Robustness Lab: Dream-1 unter gezielten Stoerungen testen und die Erfolgsquote pro Staerke messen.

Ein Sweep = fuer jeden Wert (z. B. 0, 2, 4, 6 cm) N Trials. Jeder Trial: Szene zuruecksetzen, Stoerung anwenden,
Task laufen lassen, Erfolg messen. Ergebnisse gehen live ans Panel und landen als JSON in out/extensions/robustness/.

"Trockenlauf" ersetzt Dream-1 durch kurzes Stillhalten: testet die ganze Pipeline ohne API und ohne Credits.
"""

from __future__ import annotations

import json
import threading
import time

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dashboard.extension import Extension
from dreamtool import scene, sim

from .perturbations import REGISTRY


class SweepBody(BaseModel):
    task: str = Field(min_length=2)
    perturbation: str
    values: list[float] = Field(min_length=1, max_length=20)
    trials: int = Field(3, ge=1, le=50)
    seconds: float = Field(45, gt=1, le=600)
    model: str = sim.BETA_MODEL
    dry_run: bool = True
    seed: int = 0


def hold_still(env, seconds=1.5):
    state = env.state()
    return [(state["left"], state["right"])] * int(seconds * 20)


class Sweep:
    def __init__(self, ext: "RobustnessLab", body: SweepBody):
        self.ext, self.body = ext, body
        self.stopped = False
        self.rows: list[dict] = []
        self.state = "running"
        self.started = time.time()
        self.thread = threading.Thread(target=self._run, name="robustness-sweep", daemon=True)

    @property
    def total(self):
        return len(self.body.values) * self.body.trials

    def summary(self):
        per_value = []
        for value in self.body.values:
            rows = [r for r in self.rows if r["value"] == value]
            known = [r for r in rows if r["success"] is not None]
            hits = sum(1 for r in known if r["success"])
            per_value.append({"value": value, "done": len(rows), "successes": hits,
                              "rate": hits / len(known) if known else None})
        p = REGISTRY[self.body.perturbation]
        return {"state": self.state, "config": self.body.model_dump(), "unit": p.unit, "label": p.label,
                "done": len(self.rows), "total": self.total, "per_value": per_value, "rows": self.rows}

    def _run(self):
        ctx, body = self.ext.ctx, self.body
        p = REGISTRY[body.perturbation]
        target = (scene.parse_task(body.task) or (None, None))[0]
        ctx.log(f"Sweep gestartet: {p.label}, Werte {body.values}, {body.trials} Trials"
                + (" (Trockenlauf)" if body.dry_run else ""))
        try:
            for vi, value in enumerate(body.values):
                for trial in range(body.trials):
                    if self.stopped:
                        raise InterruptedError
                    rng = np.random.default_rng([body.seed, vi, trial])
                    restore = []

                    def setup(env, value=value, rng=rng, restore=restore):
                        env.reset()
                        undo = p.apply(env, value, rng, target)
                        if undo:
                            restore.append(undo)

                    def teardown(env, restore=restore):
                        for undo in restore:
                            undo(env)

                    future = ctx.sim.run_task(
                        body.task, model=body.model, seconds=body.seconds, offline=body.dry_run,
                        targets=hold_still if body.dry_run else None, setup=setup, teardown=teardown,
                        source=ctx.id, label=f"{p.label} {value:g}{p.unit} · Trial {trial + 1}/{body.trials}",
                    )
                    result = future.result()
                    self.rows.append({"value": value, "trial": trial + 1, "success": result.success,
                                      "stop_reason": result.stop_reason, "steps": result.steps,
                                      "seconds": round(result.seconds, 1), "mean_rtt_s": result.mean_rtt_s})
                    ctx.emit("progress", self.summary())
                    if result.stop_reason == "stopped" or result.stop_reason.startswith("error"):
                        if result.stop_reason.startswith("error"):
                            ctx.log(f"Trial fehlgeschlagen ({result.stop_reason}), Sweep bricht ab.", "error")
                        raise InterruptedError
            self.state = "done"
        except InterruptedError:
            self.state = "stopped"
        except Exception as error:
            self.state = "error"
            ctx.log(f"Sweep-Fehler: {error}", "error")
        finally:
            path = ctx.data_dir / f"sweep-{time.strftime('%Y%m%d-%H%M%S')}.json"
            path.write_text(json.dumps(self.summary(), indent=2, default=float))
            ctx.log(f"Sweep {self.state}: {len(self.rows)}/{self.total} Trials, gespeichert in {path.name}")
            ctx.emit("progress", self.summary())


class RobustnessLab(Extension):
    title = "Robustness"
    icon = "🧪"
    description = "Dream-1 unter Stoerungen testen: Erfolgsquote pro Stoerstaerke"
    order = 20

    def setup(self):
        self.sweep: Sweep | None = None

    def router(self):
        r = APIRouter()

        @r.get("/perturbations")
        def perturbations():
            return [{"id": p.id, "label": p.label, "unit": p.unit, "defaults": p.defaults,
                     "description": p.description} for p in REGISTRY.values()]

        @r.get("/status")
        def status():
            return self.sweep.summary() if self.sweep else None

        @r.post("/start")
        def start(body: SweepBody):
            if body.perturbation not in REGISTRY:
                raise HTTPException(400, f"Unbekannte Stoerung: {body.perturbation}")
            if self.sweep and self.sweep.state == "running":
                raise HTTPException(409, "Es laeuft schon ein Sweep.")
            if self.ctx.sim.busy:
                raise HTTPException(409, "Die Simulation ist beschaeftigt. Erst den laufenden Lauf stoppen.")
            if not body.dry_run and not sim.settings().get("DREAM_API_KEY"):
                raise HTTPException(400, "Kein API-Key: nur Trockenlauf moeglich.")
            self.sweep = Sweep(self, body)
            self.sweep.thread.start()
            return self.sweep.summary()

        @r.post("/stop")
        def stop():
            if self.sweep and self.sweep.state == "running":
                self.sweep.stopped = True
                self.ctx.sim.cancel_queued(self.ctx.id)
                self.ctx.sim.stop()
            return {"ok": True}

        return r

    def shutdown(self):
        if self.sweep:
            self.sweep.stopped = True
