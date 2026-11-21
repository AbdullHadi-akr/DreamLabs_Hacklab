"""Robustness Lab: perturb the scene, run the task, and see how and when Dream-1 fails.

Two modes:
  sweep   one perturbation at increasing strengths (0, 2, 4, 6 cm ...) -> success curve + breaking point.
          The baseline strength is always included, and trials are interleaved (trial 1 at every strength, then
          trial 2 ...), so a sweep stopped halfway is still balanced. Trial i uses the same random draw at every
          strength (paired comparison: same direction, only the distance grows).
  random  every trial draws a random strength for each selected perturbation -> which factor hurts most.
  adaptive  Bayesian search for the breaking point of one perturbation: every next strength is the one that tells
          the most about where the model breaks (see adaptive.py). Fewer trials than a sweep for the same answer.

Every trial is watched by a TrialMonitor (reach / lift / carry / place, outcome, optional MP4). Results stream to the
panel and are saved in out/extensions/robustness/<campaign>/result.json; the report page shows them in full.

"Dry run" replaces Dream-1 with a scripted pick-and-place that is planned once on the unperturbed scene and replayed
blindly. No API, no credits, and a useful reference for what a non-adaptive policy does.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Literal

import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from dashboard import brain, credits
from dashboard.extension import Extension
from dreamtool import scene, sim

from . import adaptive, analysis, data, onefile, replay
from .monitor import OUTCOMES, TrialMonitor
from .perturbations import GROUPS, REGISTRY, InvalidSetup, Target, prepare, rewrite

CAMPAIGN_ID = re.compile(r"^[0-9]{8}-[0-9]{6}-[a-z_]+$")


class StartBody(BaseModel):
    task: str = Field(min_length=2, max_length=300)
    mode: Literal["sweep", "random", "adaptive"] = "sweep"
    perturbation: str = "target_shift"  # sweep, adaptive
    values: list[float] = Field(default_factory=list, max_length=20)  # sweep; empty = defaults
    factors: dict[str, float] = Field(default_factory=dict)  # random: id -> max strength
    trials: int = Field(3, ge=1, le=100)  # sweep: per strength; random, adaptive: total budget
    max_strength: float | None = None  # adaptive: upper end of the searched range (default: the perturbation's max)
    measure: Literal["success", "carried", "lifted", "reached"] = "success"  # adaptive: which stage must hold
    baseline_trials: int = Field(3, ge=1, le=10)  # adaptive: unperturbed trials first
    seconds: float = Field(45, gt=1, le=600)
    model: str = sim.BETA_MODEL
    dry_run: bool = True
    record: bool = False  # trial videos cost disk space and time: off unless asked for
    seed: int = 0


class Campaign:
    def __init__(self, ext: "RobustnessLab", body: StartBody):
        self.ext, self.body = ext, body
        self.target = Target(*scene.parse_task(body.task))
        self.stopped = False
        self.rows: list[dict] = []
        self.state = "running"
        self.current: dict | None = None
        self.started = time.time()
        name = body.perturbation if body.mode != "random" else "random"
        self.id = f"{time.strftime('%Y%m%d-%H%M%S')}-{name}"
        self.dir = ext.ctx.data_dir / self.id
        self.plan = None
        self.stopped_because = None
        if body.mode == "adaptive":
            p = REGISTRY[body.perturbation]
            self.top = body.max_strength if body.max_strength is not None else p.max
            self.values = []
            self.schedule = None  # decided trial by trial
        elif body.mode == "sweep":
            p = REGISTRY[body.perturbation]
            values = list(dict.fromkeys(body.values or p.defaults))
            if p.neutral not in values:
                values.insert(0, p.neutral)  # without a baseline nothing can be called a drop
            self.values = values
            # trial-major order: a stopped sweep still covers every strength equally
            self.schedule = [{"value": v, "trial": t} for t in range(body.trials) for v in values]
        else:
            self.values = []
            self.schedule = [{"trial": t} for t in range(body.trials)]
        self.thread = threading.Thread(target=self._run, name="robustness-campaign", daemon=True)

    # ---------- summary ----------

    def summary(self) -> dict:
        b = self.body
        data = {
            "id": self.id, "state": self.state, "mode": b.mode, "config": b.model_dump(),
            "target": {"object": self.target.obj, "container": self.target.container},
            "done": len(self.rows), "total": self.total, "current": self.current,
            "started": self.started, "elapsed_s": round(time.time() - self.started, 1),
            "rows": self.rows, "outcome_labels": OUTCOMES,
            "policy": "scripted blind replay (dry run)" if b.dry_run else b.model,
            "cost": self.cost(),
        }
        if b.mode == "adaptive":
            p = REGISTRY[b.perturbation]
            data.update(perturbation=_describe(p) | {"max": self.top},
                        values=sorted({r["value"] for r in self.rows}),
                        analysis=adaptive.summarize(self.rows, p.neutral, self.top, p.unit, b.measure, b.trials,
                                                    self.stopped_because))
        elif b.mode == "sweep":
            p = REGISTRY[b.perturbation]
            data.update(perturbation=_describe(p), values=self.values,
                        analysis=analysis.sweep_summary(self.values, self.rows, p.neutral, p.unit, p.discrete))
        else:
            data.update(factors=[_describe(REGISTRY[f]) | {"max": m} for f, m in b.factors.items()],
                        analysis=analysis.random_summary(b.factors, {f: REGISTRY[f].neutral for f in b.factors},
                                                         self.rows, {f: REGISTRY[f].label for f in b.factors}))
        return data

    def cost(self) -> dict:
        """Dream-1 calls and their cost over all trials (calls x price; a dry run makes no calls)."""
        calls = sum(r.get("calls") or 0 for r in self.rows)
        price = None if self.body.dry_run else credits.price(self.body.model)
        if self.body.dry_run:
            return {"calls": 0, "usd": 0.0, "price_usd": None, "note": "dry run: no Dream-1 calls"}
        return {"calls": calls, "usd": None if price is None else round(calls * price, 6), "price_usd": price,
                "note": "" if price is not None else "price of this model unknown"}

    @property
    def total(self) -> int:
        if self.schedule is not None:
            return len(self.schedule)
        # adaptive: the budget while running; afterwards what was actually needed (it may stop early)
        return self.body.trials if self.state == "running" else len(self.rows)

    def entries(self):
        """The trials to run. Fixed for sweep/random; for adaptive each one is chosen after the previous result."""
        if self.schedule is not None:
            yield from self.schedule
            return
        b = self.body
        p = REGISTRY[b.perturbation]
        level = adaptive.MEASURES[b.measure][0]
        for t in range(min(b.baseline_trials, b.trials)):
            yield {"value": p.neutral, "trial": t, "why": "baseline"}
        base = [y for r in self.rows if (y := adaptive.event(r, level)) is not None]
        if len(base) >= 3 and not any(base):
            self.stopped_because = "measure never reached at baseline"
            return
        search = adaptive.BreakpointSearch(p.neutral, self.top)
        for t in range(len(self.rows), b.trials):
            observations = [(r["value"], y) for r in self.rows if (y := adaptive.event(r, level)) is not None]
            search.fit(observations)
            reason = search.stop_reason(len(self.rows) - b.baseline_trials)
            if reason:
                self.stopped_because = reason
                return
            strength, gain = search.next_strength()
            est = search.estimate()
            yield {"value": round(strength, 3), "trial": t, "why": "most informative",
                   "gain": round(gain, 3), "ci_before": [round(v, 3) for v in est["ci"]]}
        self.stopped_because = "budget used up"

    def save(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "result.json").write_text(json.dumps(self.summary(), indent=2, default=float), encoding="utf-8")

    # ---------- execution ----------

    def _items(self, entry, rng):
        """(perturbation, strength) pairs for one trial."""
        if self.body.mode != "random":
            return [(REGISTRY[self.body.perturbation], entry["value"])]
        return [(REGISTRY[fid], REGISTRY[fid].sample(rng, top)) for fid, top in self.body.factors.items()]

    def _run(self):
        ctx, body = self.ext.ctx, self.body
        if body.mode == "sweep":
            mode_text = f"{REGISTRY[body.perturbation].label}, strengths {self.values}, {body.trials} trials each"
        elif body.mode == "adaptive":
            mode_text = (f"breaking point of {REGISTRY[body.perturbation].label} up to {self.top:g}, "
                         f"measure {body.measure}, budget {body.trials} trials")
        else:
            mode_text = f"random mix of {', '.join(body.factors)}, {body.trials} trials"
        ctx.log(f"Robustness {body.mode} started: {mode_text}" + (" (dry run)" if body.dry_run else ""))
        try:
            if body.dry_run:
                try:
                    self.plan = ctx.sim.call(lambda env: replay.plan(env, *self.target)).result(timeout=60)
                except Exception as error:
                    ctx.log(f"Scripted replay could not be planned ({error}); dry runs just hold still.", "warn")
                    self.plan = None
            for index, entry in enumerate(self.entries()):
                if self.stopped:
                    raise InterruptedError
                self._trial(index, entry)
                self.save()
                ctx.emit("progress", self.summary())
                last = self.rows[-1]
                if last["stop_reason"] == "stopped":
                    raise InterruptedError
                if last["stop_reason"].startswith("error"):
                    ctx.log(f"Trial failed ({last['stop_reason']}), aborting.", "error")
                    raise InterruptedError
            self.state = "done"
        except InterruptedError:
            self.state = "stopped"
        except Exception as error:
            self.state = "error"
            ctx.log(f"Robustness campaign error: {type(error).__name__}: {error}", "error")
        finally:
            self.current = None
            self.save()
            try:
                brain.campaign_ended(self.summary())  # the second brain's raw files (dashboard/brain.py)
            except Exception as error:
                ctx.log(f"Second brain: {error}", "warn")
            verdict = self.summary()["analysis"]["verdict"]["text"]
            ctx.log(f"Robustness {self.state}: {len(self.rows)}/{self.total} trials. {verdict}")
            ctx.emit("progress", self.summary())

    def _trial(self, index, entry):
        ctx, body = self.ext.ctx, self.body
        seed = [body.seed, entry["trial"]]
        items = self._items(entry, np.random.default_rng([*seed, 7919]))
        env_items = [(p, v) for p, v in items if p.kind == "env"]
        text_items = [(p, v) for p, v in items if p.kind == "text"]
        prompt = rewrite(body.task, text_items, self.target, seed)
        params = {p.id: v for p, v in items}
        number = index + 1
        label = (f"{items[0][0].label} {entry['value']:g}{items[0][0].unit}" if body.mode != "random"
                 else "Random mix") + f" · trial {number}/{self.total}"
        self.current = {"index": number, "label": label, "params": params, "prompt": prompt}
        ctx.emit("trial", self.current)
        row = {"index": number, "trial": entry["trial"] + 1, "params": params, "prompt": prompt, "info": {},
               "stop_reason": "", "steps": 0, "seconds": 0.0, "mean_rtt_s": None, "redraws": 0, "video": None}
        if "value" in entry:
            row["value"] = entry["value"]
        if "why" in entry:  # adaptive: why this strength was chosen
            row["search"] = {k: entry[k] for k in ("why", "gain", "ci_before") if k in entry}

        # Set the scene up first (on the sim thread) and only start the run if it is a fair trial:
        # an invalid setup must neither cost credits nor count as a model failure.
        try:
            effects, row["redraws"] = ctx.sim.call(
                lambda env: prepare(env, env_items, self.target, seed)).result(timeout=30)
        except InvalidSetup as error:
            row.update(outcome="invalid", progress=None, success=False, metrics={}, note=str(error),
                       stop_reason="invalid setup")
            ctx.log(f"Trial {number}: no valid setup found ({error}), skipped.", "warn")
            self.rows.append(row)
            return

        def teardown(env):
            for effect in reversed(effects):
                effect.undo(env)

        video = self.dir / f"trial-{number:03d}.mp4" if body.record else None
        monitor = TrialMonitor(self.target.obj, self.target.container, video)
        self.dir.mkdir(parents=True, exist_ok=True)
        if body.dry_run:
            targets = (lambda env: self.plan) if self.plan else replay.hold_still
        else:
            targets = None
        result = ctx.sim.run_task(
            body.task, prompt=prompt if prompt != body.task else None, model=body.model, seconds=body.seconds,
            offline=body.dry_run, realtime=not body.dry_run, targets=targets, teardown=teardown,
            hooks=[monitor, *(h for e in effects for h in e.hooks)], source=ctx.id, label=label,
        ).result()

        price = None if body.dry_run else credits.price(body.model)
        row.update(
            calls=result.requests, cost_usd=0.0 if body.dry_run else (
                None if price is None else round(result.requests * price, 6)),
            stop_reason=result.stop_reason, steps=result.steps, seconds=round(result.sim_seconds, 1),
            mean_rtt_s=None if result.mean_rtt_s is None else round(result.mean_rtt_s, 2),
            info={p.id: e.info for (p, _), e in zip(env_items, effects) if e.info},
            video=video.name if video is not None and video.is_file() and monitor.frames else None,
        )
        m = dict(monitor.metrics) or {"outcome": "aborted", "progress": None, "success": False}
        row.update(outcome=m.pop("outcome"), progress=m.pop("progress"), success=m.pop("success"), metrics=m)
        if "note" in m:
            row["note"] = m.pop("note")
            ctx.log(f"Trial {number}: {row['note']}.", "warn")
        self.rows.append(row)


def _describe(p):
    return {"id": p.id, "label": p.label, "unit": p.unit, "group": p.group, "group_label": GROUPS[p.group],
            "defaults": p.defaults, "max": p.max, "neutral": p.neutral, "discrete": p.discrete,
            "description": p.description, "kind": p.kind}


class RobustnessLab(Extension):
    title = "Robustness"
    icon = ""
    description = "Perturb the scene and see how and when Dream-1 fails"
    order = 20
    slot = "suite"  # three tiles in the Test Suite builder (a normal tab when there is no Test Suite)
    suite_modes = [
        {"id": "sweep", "title": "Robustness Sweep", "subtitle": "Failure curve", "icon": "⫶"},
        {"id": "adaptive", "title": "Breaking Point", "subtitle": "Adaptive search", "icon": "◎"},
        {"id": "random", "title": "Perturbation Mix", "subtitle": "Which factor hurts", "icon": "⁂"},
    ]

    def setup(self):
        self.campaign: Campaign | None = None

    def _campaign_dir(self, campaign_id: str) -> Path:
        if not CAMPAIGN_ID.match(campaign_id):
            raise HTTPException(404)
        path = self.ctx.data_dir / campaign_id
        if not (path / "result.json").is_file():
            raise HTTPException(404, "No such campaign")
        return path

    def router(self):
        r = APIRouter()

        @r.get("/perturbations")
        def perturbations():
            return {"groups": GROUPS, "items": [_describe(p) for p in REGISTRY.values()]}

        @r.get("/status")
        def status():
            return self.campaign.summary() if self.campaign else None

        @r.post("/start")
        def start(body: StartBody):
            if scene.parse_task(body.task) is None:
                raise HTTPException(400, "Can't tell which object should go into which container, so success can't "
                                         "be measured. Name one object (apple, banana, orange, bottle) and the goal "
                                         "after into/in/on/to (bowl, plate), e.g. \"pick up the banana and put it "
                                         "on the plate\".")
            if body.mode != "random" and body.perturbation not in REGISTRY:
                raise HTTPException(400, f"Unknown perturbation: {body.perturbation}")
            if body.mode == "adaptive":
                p = REGISTRY.get(body.perturbation)
                if p is None or p.discrete:
                    raise HTTPException(400, "The breaking-point search needs a perturbation with an ordered strength "
                                             "(not a set of prompt variants).")
                top = body.max_strength if body.max_strength is not None else p.max
                if top <= p.neutral:
                    raise HTTPException(400, f"Maximum strength must be above {p.neutral:g} {p.unit}.")
                if body.trials < body.baseline_trials + adaptive.MIN_ADAPTIVE:
                    raise HTTPException(400, f"Budget too small: at least {body.baseline_trials + adaptive.MIN_ADAPTIVE} "
                                             "trials (baseline + 3 searched).")
            if body.mode == "random":
                unknown = [f for f in body.factors if f not in REGISTRY]
                if unknown or not body.factors:
                    raise HTTPException(400, f"Pick at least one known perturbation (unknown: {unknown})")
            if self.campaign and self.campaign.state == "running":
                raise HTTPException(409, "A robustness campaign is already running.")
            if self.ctx.sim.busy:
                raise HTTPException(409, "The simulation is busy. Stop the current run first.")
            if not body.dry_run and not sim.settings().get("DREAM_API_KEY"):
                raise HTTPException(400, "No API key: only dry runs are possible.")
            self.campaign = Campaign(self, body)
            self.campaign.save()
            self.campaign.thread.start()
            return self.campaign.summary()

        @r.post("/stop")
        def stop():
            if self.campaign and self.campaign.state == "running":
                self.campaign.stopped = True
                self.ctx.sim.cancel_queued(self.ctx.id)
                self.ctx.sim.stop()
            return {"ok": True}

        @r.get("/history")
        def history():
            items = []
            for path in sorted(self.ctx.data_dir.glob("*/result.json"), reverse=True)[:50]:
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                items.append({
                    "id": data["id"], "mode": data["mode"], "state": data["state"], "task": data["config"]["task"],
                    "label": data.get("perturbation", {}).get("label") or "Random mix",
                    "dry_run": data["config"]["dry_run"], "done": data["done"], "total": data["total"],
                    "verdict": data["analysis"]["verdict"]["text"],
                })
            return items

        @r.get("/results/{campaign_id}")
        def results(campaign_id: str):
            if self.campaign and self.campaign.id == campaign_id:
                return self.campaign.summary()
            return json.loads((self._campaign_dir(campaign_id) / "result.json").read_text(encoding="utf-8"))

        # ---------- stored runs & downloads ----------

        def stored(task=None, policy=None):
            results = data.load_all(self.ctx.data_dir)
            if self.campaign:  # the running campaign: live state instead of the last save
                results = [self.campaign.summary() if r["id"] == self.campaign.id else r for r in results]
            return [r for r in results if data.matches(r, task, policy)]

        @r.get("/runs")
        def runs(task: str | None = None, policy: str | None = None):
            everything = stored()
            return {
                "runs": [data.run_info(r, self.ctx.data_dir / r["id"]) for r in everything
                         if data.matches(r, task, policy)],
                "tasks": sorted({r["config"]["task"] for r in everything}),
                "policies": sorted({data.policy_key(r) for r in everything}),
            }

        @r.get("/map")
        def robustness_map(task: str | None = None, policy: str | None = None):
            return data.robustness_map(stored(task, policy))

        def attachment(text: str, filename: str, media_type: str):
            return Response(text.encode("utf-8"), media_type=f"{media_type}; charset=utf-8",
                            headers={"Content-Disposition": f'attachment; filename="{filename}"'})

        @r.get("/download/all-trials.csv")
        def download_all(task: str | None = None, policy: str | None = None, excel: bool = False):
            records = [rec for result in stored(task, policy) for rec in data.trial_records(result)]
            return attachment(data.to_csv(records, excel), f"robustness-trials-{time.strftime('%Y%m%d-%H%M')}.csv",
                              "text/csv")

        @r.get("/download/{campaign_id}/result.json")
        def download_json(campaign_id: str):
            result = results(campaign_id)
            return attachment(json.dumps(result, indent=2, default=float), f"{campaign_id}.json", "application/json")

        @r.get("/download/{campaign_id}/trials.csv")
        def download_csv(campaign_id: str, excel: bool = False):
            return attachment(data.to_csv(data.trial_records(results(campaign_id)), excel), f"{campaign_id}.csv",
                              "text/csv")

        @r.get("/download/{campaign_id}/report.html")
        def download_report(campaign_id: str, videos: bool = False):
            """The whole report as ONE html file: opens without the dashboard. Videos only when asked for."""
            folder = self.ctx.data_dir / campaign_id
            text = onefile.render(results(campaign_id), folder, videos=videos)
            return attachment(text, f"{campaign_id}{'-with-videos' if videos else ''}.html", "text/html")

        @r.get("/download/{campaign_id}/bundle.zip")
        def download_zip(campaign_id: str):
            folder = self._campaign_dir(campaign_id)
            handle, name = tempfile.mkstemp(suffix=".zip")
            os.close(handle)
            data.write_bundle(results(campaign_id), folder, Path(name))
            return FileResponse(name, media_type="application/zip", filename=f"{campaign_id}.zip",
                                background=BackgroundTask(os.unlink, name))

        @r.get("/video/{campaign_id}/{name}")
        def video(campaign_id: str, name: str):
            if not re.match(r"^trial-[0-9]{3}\.mp4$", name):
                raise HTTPException(404)
            path = self.ctx.data_dir / campaign_id / name
            if not CAMPAIGN_ID.match(campaign_id) or not path.is_file():
                raise HTTPException(404)
            return FileResponse(path, media_type="video/mp4")

        return r

    def shutdown(self):
        if self.campaign:
            self.campaign.stopped = True
