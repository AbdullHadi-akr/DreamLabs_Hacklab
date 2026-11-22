"""Independent testing workspace backed by the dashboard's shared simulator."""
from concurrent.futures import CancelledError
import csv
import io
import json
import threading
import time
from typing import Annotated, Literal
from uuid import UUID, uuid4

from PIL import Image
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from dashboard.extension import Extension
from dashboard.simulation import result_dict
from dreamtool import sim

from .evaluation import placement, snapshot

from .metrics import Evidence, execution_status, summarize
from .scenarios import STRESS, apply, capture_start, generate, sweep_values
from .checkpoint import DEMO_PREFIX, TASK, ForkExecution, chunks
from .forks import Forks
from ..robustness.replay import plan as scripted_plan

Prompt = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=300)]
Offset = Annotated[float, Field(ge=-30, le=30)]
Angle = Annotated[float, Field(ge=-35, le=35)]
Lighting = Annotated[float, Field(ge=0, le=2)]


class Config(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")

    mode: Literal["quick", "repeated", "sweep", "safety", "ab", "reproduction"] = "repeated"
    prompt: Prompt
    prompt_b: Prompt | None = None
    stress_scenarios: list[Literal["reach", "visibility", "combined"]] = Field(default_factory=lambda: ["combined"], min_length=1, max_length=3)
    stress_baseline: bool = False
    model: str = sim.BETA_MODEL
    seconds: float = Field(60, gt=0, le=300)
    max_requests: int = Field(30, ge=1, le=200)
    record: bool = False
    dry_run: bool = False
    goal: str = Field("", max_length=300)
    object: Literal["apple", "banana", "orange", "water_bottle"] | None = None
    position_variation: float = Field(0, ge=0, le=20)
    camera_variation: float = Field(0, ge=0, le=30)
    difficulty: Literal["none", "low", "medium", "high"] = "none"
    positions: list[Offset] | None = Field(None, min_length=1, max_length=10)
    tilts: list[Angle] | None = Field(None, min_length=1, max_length=10)
    lights: list[Lighting] | None = Field(None, min_length=1, max_length=10)
    repeats: int = Field(1, ge=1, le=100)
    seed: int = Field(0, ge=0, le=2**32-1)

    @property
    def placement_goal(self):
        return placement(self.goal or self.prompt)

    @model_validator(mode="after")
    def validate_campaign(self):
        self.model = sim.resolve_model(self.model)
        if self.mode == "ab" and not self.prompt_b:
            raise ValueError("A/B Comparison requires Prompt B.")
        if self.mode == "safety":
            if len(set(self.stress_scenarios)) != len(self.stress_scenarios):
                raise ValueError("Select each supported stress scenario once.")
            if self.position_variation or self.camera_variation or self.difficulty != "none":
                raise ValueError("Safety Stress Test uses only the perturbations defined by the selected scenarios.")
        if self.goal.strip() and not placement(self.goal):
            raise ValueError("Use an object placement goal, for example: put the banana on the plate.")
        if self.mode not in ("sweep", "reproduction") and any(values is not None for values in (self.positions, self.tilts, self.lights)):
            raise ValueError("Explicit lists are available in Parameter Sweep only.")
        positions, angles, lights = sweep_values(self)
        count = self.repeats * len(positions) * len(angles) * len(lights) if self.mode == "sweep" else self.repeats
        if self.mode == "ab":
            count *= 2
        if count > 100:
            raise ValueError(f"The selected sweep produces {count} runs. Reduce it to 100 runs or fewer.")
        moves_object = (any(positions) if self.mode == "sweep"
                        else any(dx for name in self.stress_scenarios for dx, _, _ in STRESS[name]) if self.mode == "safety"
                        else self.position_variation > 0 and self.mode in ("repeated", "ab"))
        if moves_object and not (self.object or self.placement_goal):
            raise ValueError("Name an object in the placement task or select the object to move in Advanced settings.")
        return self


class Review(BaseModel):
    passed: bool


class CampaignControl(BaseModel):
    id: UUID


class ForkConfirmation(BaseModel):
    confirmed: bool = False


class TestSuite(Extension):
    """The Test Suite workspace: campaigns of many runs (quick, repeated, sweep, safety, A/B, reproduction),
    their evaluation and reports, and Fork Here comparisons."""

    id = "test_suite"
    title = "Test Suite"
    slot = "workspace"

    def setup(self):
        self.lock = threading.Lock()
        self.active = None
        self.cancelled = threading.Event()
        self.cancel_pending = threading.Event()
        self.live = None
        self.history_cache = {}
        self.forks = Forks(self) if hasattr(self.ctx, "sim") else None

    def directory(self, campaign: UUID):
        return self.ctx.data_dir / campaign.hex

    def save(self, report):
        path = self.directory(UUID(report["id"])) / "report.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, allow_nan=False), encoding="utf-8")
        temporary.replace(path)

    def read(self, campaign):
        path = self.directory(campaign) / "report.json"
        with self.lock:
            if not path.is_file():
                raise HTTPException(404, "Campaign not found.")
            report = json.loads(path.read_text(encoding="utf-8"))
            if report["state"] == "running" and self.active != campaign.hex:
                report["state"] = "interrupted"
        return summarize(report)

    def read_actions(self, campaign, row):
        # Older reports kept the timeline inline.
        if "actions" in row:
            return row["actions"]
        path = self.directory(campaign) / f'{row["number"]}.actions.json'
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []

    def start(self, config, replay=None, fork_demo=False):
        worker = self.ctx.sim
        with self.lock:
            if self.active or worker.busy:
                raise HTTPException(409, "The simulator is busy.")
            if not worker.ready.is_set() or worker.error:
                raise HTTPException(503, "The simulator is unavailable.")
            if not config.dry_run and not sim.settings().get("DREAM_API_KEY"):
                raise HTTPException(400, "Configure a Dream-1 API key or choose dry run.")
            campaign = uuid4().hex
            cases = [replay["case"]] if replay else list(generate(config))
            report = dict(id=campaign, created=time.time(), state="running", total=len(cases),
                          config=config.model_dump(), trials=[], logs=[])
            if fork_demo:
                report["fork_demo"] = True
                cases[0]["current_scene"] = False
            if replay:
                report["reproduction"] = replay["reference"]
            self.save(report)
            self.cancelled.clear()
            self.cancel_pending.clear()
            self.live = None
            self.active = campaign
            threading.Thread(target=self.run_campaign, args=(config, cases, report), daemon=True).start()
        return {"id": campaign}

    def run_campaign(self, config, cases, report):
        worker = self.ctx.sim
        try:
            for index, case in enumerate(cases, 1):
                if self.cancelled.is_set() or self.cancel_pending.is_set():
                    break
                def stage(status, **extra):
                    event = dict(id=report["id"], trial=index, total=len(cases), task=case["prompt"],
                                 status=status, at=time.time())
                    event.update(extra)
                    with self.lock:
                        self.live = event
                    self.ctx.emit("progress", event)

                stage("queued")
                directory = self.directory(UUID(report["id"]))
                video = directory / f"{index}.mp4" if config.record else None
                goal = placement(config.goal or case["prompt"])
                evidence = Evidence(self.cancelled, video, goal, stage)
                demo = report.get("fork_demo", False)
                experiment = None
                if config.mode == "quick" and goal == ("banana", "plate") and (demo or not config.dry_run):
                    experiment = ForkExecution(evidence.evaluator, case["prompt"], case["model"],
                                               path=directory / f"{index}.checkpoint.json.gz",
                                               script=[] if demo else None, max_requests=config.max_requests)
                restore = None
                initial = final = None
                starting_physics = None
                setup_seconds = None

                def setup(env):
                    nonlocal restore, initial, starting_physics, setup_seconds
                    evidence.mark("preparing")
                    started = time.monotonic()
                    try:
                        if self.cancelled.is_set():
                            return
                        restore = apply(env, case)
                        if demo:
                            rows = scripted_plan(env, "banana", "plate", release_height=.085)
                            experiment.script = chunks(rows[:DEMO_PREFIX]) + chunks(rows[DEMO_PREFIX:])
                            experiment.continuation = rows[DEMO_PREFIX:]
                        initial = snapshot(env)
                        starting_physics = capture_start(env)
                        evidence.prepare(env)
                    finally:
                        setup_seconds = time.monotonic() - started

                def teardown(env):
                    nonlocal final
                    try:
                        evidence.mark("evaluating")
                        if initial is not None:
                            final = snapshot(env)
                        evidence.close()
                    finally:
                        if restore:
                            restore()

                future = worker.run_task(case["prompt"], model=case["model"], seconds=config.seconds,
                                         hooks=[evidence], setup=setup, teardown=teardown,
                                         offline=config.dry_run, stop_on_success=False, max_requests=config.max_requests,
                                         capture_each_step=config.record,
                                         targets=lambda env: [(env.state()["left"], env.state()["right"])] * 10,
                                         source=self.id, label=f"Run {index}/{len(cases)}",
                                         **({"experiment": experiment} if experiment else {}))
                result = result_dict(future.result())
                termination = result["stop_reason"]
                unevaluated_dry_run = config.dry_run and not demo
                verdict, explanation = evidence.evaluator.result(termination, unevaluated_dry_run)
                category, verified_stage = evidence.evaluator.classify(
                    termination, verdict, bool(evidence.requests and evidence.requests[-1].get("error"))
                    or termination.startswith("error: Dream"))
                if unevaluated_dry_run and execution_status(termination) == "completed":
                    category, verified_stage = "EVALUATION_UNAVAILABLE", None
                execution = execution_status(termination, verdict)
                duration = result["seconds"] if evidence.started else None
                safety_checks = evidence.safety_checks()
                captured_frames = []
                for kind, (observed_time, frame) in evidence.telemetry.frames.items():
                    try:
                        Image.fromarray(frame).save(directory / f"{index}.{kind}.jpg", quality=84)
                        captured = dict(kind=kind, simulation_time=observed_time)
                        if kind in evidence.telemetry.milestones:
                            captured["event"] = evidence.telemetry.milestones[kind]
                        captured_frames.append(captured)
                    except (OSError, ValueError) as exc:
                        report["logs"].append(f"Run {index}: could not save {kind} snapshot ({exc}).")
                progress = evidence.telemetry.progress(
                    (evidence.evaluator.latest or {}).get("events", ()), termination,
                    final.get("simulation_time") if final else None)
                if progress:
                    (directory / f"{index}.progress.json").write_text(json.dumps(progress), encoding="utf-8")
                final_frame = next((frame for frame in captured_frames if frame["kind"] == "final"), None)
                row = dict(
                    result, number=index, case=case, task_success=verdict, execution_status=execution,
                    termination_reason=termination, evaluation_status="evaluated" if verdict is not None else "not_evaluated",
                    safety_status="fail" if "fail" in safety_checks.values() else "pass" if "pass" in safety_checks.values() else "not_evaluated",
                    task_duration_seconds=duration, completion_duration_seconds=duration if verdict is True else None,
                    setup_duration_seconds=setup_seconds, api_request_count=result["requests"],
                    mean_request_latency_seconds=result["mean_rtt_s"],
                    evaluation_method="deterministic_placement" if goal and not unevaluated_dry_run else None,
                    evaluation_evidence=evidence.evaluator.latest, failure_reason=explanation, confidence=None,
                    initial_state=initial, final_state=final, timeline=evidence.timeline,
                    api_events=evidence.requests, video=bool(video and video.is_file()), action_chunks=len(evidence.actions),
                    snapshot_available=final_frame is not None,
                    snapshot_simulation_time=final_frame["simulation_time"] if final_frame else None,
                    snapshots=captured_frames, progress_available=progress is not None,
                    issues=list(evidence.issues.values()), contact_steps=evidence.contact_steps, samples=evidence.samples,
                    safety_violations=list(evidence.safety_violations.values()),
                    action_diagnostics=evidence.action_diagnostics(),
                    starting_physics=starting_physics,
                    failure_category=category, last_verified_stage=verified_stage,
                    safety_checks=safety_checks,
                )
                row["success"] = verdict
                if experiment:
                    row["checkpoint"] = experiment.reference
                    if not experiment.reference:
                        row["checkpoint_unavailable"] = experiment.reason
                evidence.timeline.append({"stage": execution, "at": time.time()})
                if evidence.actions:
                    (directory / f"{index}.actions.json").write_text(
                        json.dumps(evidence.actions, allow_nan=False), encoding="utf-8")
                report["trials"].append(row)
                level = "error" if execution == "error" else "warn" if execution in ("failed", "timed_out") else "info"
                report["logs"].extend(dict(at=entry["at"], level="info", source=f"Run {index}", message=entry["stage"])
                                      for entry in evidence.timeline[:-1])
                report["logs"].extend(dict(at=entry["at"], level="error", source=f"Run {index} · API",
                                           message=entry["error"]) for entry in evidence.requests if entry["error"])
                report["logs"].append(dict(at=time.time(), level=level, source=f"Run {index}",
                                           message=f"{execution}. {explanation or termination}"))
                self.save(summarize(report))
                stage(execution)
                self.ctx.emit("trial", {"id": report["id"], "trial": index})
            if self.cancelled.is_set():
                report["state"] = "stopped"
            elif self.cancel_pending.is_set() and len(report["trials"]) < report["total"]:
                report["state"] = "cancelled"
            else:
                report["state"] = "done"
        except CancelledError:
            report["state"] = "stopped"
        except Exception as exc:
            report["state"] = "error"
            report["logs"].append(dict(at=time.time(), level="error", source="Campaign", message=str(exc)))
            self.ctx.log(str(exc), "error")
        finally:
            with self.lock:
                try:
                    self.save(summarize(report))
                finally:
                    self.active = None
                    self.live = None
            self.ctx.emit("ended", {"id": report["id"], "state": report["state"], "total": report["total"],
                                    "stats": summarize(report)["stats"], "name": config.prompt})

    def shutdown(self):
        self.cancelled.set()
        if self.forks is not None:
            self.forks.cancelled.set()

    def router(self):
        router = APIRouter()

        @router.get("/history")
        def history():
            items = []
            with self.lock:
                for path in self.ctx.data_dir.glob("*/report.json"):
                    stamp = path.stat().st_mtime_ns
                    cached = self.history_cache.get(path)
                    if cached is None or cached[0] != stamp:
                        report = json.loads(path.read_text(encoding="utf-8"))
                        summary = {key: report[key] for key in ("id", "created", "state", "total", "config")}
                        summary["completed"] = len(report["trials"])
                        self.history_cache[path] = stamp, summary
                    item = self.history_cache[path][1].copy()
                    if item["state"] == "running":
                        if self.active == item["id"]:
                            item["live"] = self.live
                        else:
                            item["state"] = "interrupted"
                    items.append(item)
            return sorted(items, key=lambda item: item["created"], reverse=True)

        @router.post("/start")
        def start(config: Config):
            if config.mode == "reproduction":
                raise HTTPException(422, "Select a saved failed run to reproduce.")
            return self.start(config)

        @router.post("/fork-demo")
        def fork_demo():
            return self.start(Config(mode="quick", prompt=TASK, dry_run=True, seconds=180), fork_demo=True)

        @router.get("/reports/{campaign}/forks/{trial}")
        def fork_history(campaign: UUID, trial: int):
            return self.forks.history(campaign, trial)

        @router.get("/reports/{campaign}/forks/{trial}/quote")
        def fork_quote(campaign: UUID, trial: int):
            return self.forks.quote(self.forks.checkpoint(campaign, trial))

        @router.post("/reports/{campaign}/forks/{trial}")
        def fork(campaign: UUID, trial: int, body: ForkConfirmation):
            return self.forks.launch(campaign, trial, body.confirmed)

        @router.post("/forks/{comparison}/stop")
        def stop_fork(comparison: UUID):
            return self.forks.stop(comparison)

        @router.post("/stop")
        def stop(body: CampaignControl | None = None):
            with self.lock:
                if body and self.active != body.id.hex:
                    raise HTTPException(409, "This campaign is no longer active.")
                if self.active:
                    self.cancelled.set()
            return {"ok": True}

        @router.post("/cancel")
        def cancel(body: CampaignControl | None = None):
            with self.lock:
                if body and self.active != body.id.hex:
                    raise HTTPException(409, "This campaign is no longer active.")
                if self.active:
                    self.cancel_pending.set()
            return {"ok": True}

        @router.get("/reports/{campaign}")
        def report(campaign: UUID):
            return self.read(campaign)

        @router.get("/failed-runs")
        def failed_runs():
            items = []
            for path in self.ctx.data_dir.glob("*/report.json"):
                data = self.read(UUID(path.parent.name))
                if data["state"] == "running" or data["config"].get("dry_run") or not data["config"].get("reset", True):
                    continue
                for row in data["trials"]:
                    if row["task_success"] is False or row["execution_status"] in ("failed", "error", "timed_out"):
                        items.append(dict(id=data["id"], created=data["created"], number=row["number"],
                                          prompt=row["case"]["prompt"], reason=row["failure_category"] if row.get("failure_category")
                                          else row["termination_reason"]))
            return sorted(items, key=lambda item: (item["created"], item["number"]), reverse=True)

        @router.get("/reports/{campaign}/export/{format}")
        def export(campaign: UUID, format: Literal["json", "csv"]):
            data = report(campaign)
            if format == "json":
                for row in data["trials"]:
                    row["actions"] = self.read_actions(campaign, row)
                content, media = json.dumps(data, indent=2), "application/json"
            else:
                stream = io.StringIO()
                fields = ["number", "seed", "object", "offset", "tilt", "light", "execution_status",
                          "termination_reason", "evaluation_status", "task_success", "safety_status", "failure_reason",
                          "task_duration_seconds", "completion_duration_seconds", "setup_duration_seconds",
                          "api_request_count", "mean_request_latency_seconds", "evaluation_method", "manual_success",
                          "failure_category", "last_verified_stage", "variant", "pair", "stress_scenario", "stress_direction"]
                writer = csv.DictWriter(stream, fields, extrasaction="ignore")
                writer.writeheader()
                for row in data["trials"]:
                    writer.writerow(row | row["case"])
                content, media = stream.getvalue(), "text/csv"
            return Response(content, media_type=media,
                            headers={"Content-Disposition": f'attachment; filename="{campaign}.{format}"'})

        @router.get("/reports/{campaign}/video/{trial}")
        def video(campaign: UUID, trial: int):
            path = self.directory(campaign) / f"{trial}.mp4"
            if not path.is_file():
                raise HTTPException(404)
            return FileResponse(path, media_type="video/mp4")

        @router.get("/reports/{campaign}/snapshot/{trial}")
        def last_frame(campaign: UUID, trial: int):
            path = self.directory(campaign) / f"{trial}.jpg"
            if not path.is_file():
                path = self.directory(campaign) / f"{trial}.final.jpg"
            if not path.is_file():
                raise HTTPException(404, "No overhead frame was captured for this run.")
            return FileResponse(path, media_type="image/jpeg")

        @router.get("/reports/{campaign}/snapshot/{trial}/{kind}")
        def frame(campaign: UUID, trial: int, kind: Literal["first", "contact", "pickup", "closest", "final"]):
            path = self.directory(campaign) / f"{trial}.{kind}.jpg"
            if not path.is_file():
                raise HTTPException(404, "No frame was captured for this milestone.")
            return FileResponse(path, media_type="image/jpeg")

        @router.get("/reports/{campaign}/progress/{trial}")
        def progress(campaign: UUID, trial: int):
            path = self.directory(campaign) / f"{trial}.progress.json"
            if not path.is_file():
                raise HTTPException(404, "No target-distance measurements were recorded.")
            return FileResponse(path, media_type="application/json")

        @router.get("/reports/{campaign}/actions/{trial}")
        def actions(campaign: UUID, trial: int):
            data = self.read(campaign)
            if not 1 <= trial <= len(data["trials"]):
                raise HTTPException(404)
            return self.read_actions(campaign, data["trials"][trial - 1])

        @router.post("/reports/{campaign}/review/{trial}")
        def review(campaign: UUID, trial: int, body: Review):
            data = self.read(campaign)
            with self.lock:
                if data["state"] == "running" or data["config"]["dry_run"]:
                    raise HTTPException(409, "Review is available for completed live campaigns.")
                if not 1 <= trial <= len(data["trials"]):
                    raise HTTPException(404)
                # Read the latest version while holding the write lock.
                path = self.directory(campaign) / "report.json"
                data = json.loads(path.read_text(encoding="utf-8"))
                data["trials"][trial - 1]["manual_success"] = body.passed
                self.save(data)
            self.ctx.emit("trial", {"id": campaign.hex, "trial": trial})
            return {"ok": True}

        @router.post("/reports/{campaign}/repeat/{trial}")
        def repeat(campaign: UUID, trial: int):
            data = self.read(campaign)
            if not 1 <= trial <= len(data["trials"]):
                raise HTTPException(404)
            config = data["config"]
            if not config.get("reset", True):
                raise HTTPException(409, "This historical run did not start from a reset scene.")
            if data["state"] == "running":
                raise HTTPException(409, "Wait until the original campaign finishes.")
            original = data["trials"][trial - 1]
            case = dict(original["case"], run=1)
            if original.get("starting_physics") is not None:
                case["starting_physics"] = original["starting_physics"]
            replay = Config(
                mode="reproduction", prompt=case["prompt"], model=case["model"], seconds=config["seconds"],
                max_requests=config.get("max_requests", 30), record=config["record"], dry_run=config["dry_run"],
                seed=case.get("seed", config["seed"]), object=case.get("object", config.get("object")),
                positions=[case["offset"]], tilts=[case["tilt"]], lights=[case["light"]],
                goal=config.get("goal", ""),
            )
            reference = {key: original.get(key) for key in (
                "number", "task_success", "termination_reason", "task_duration_seconds",
                "failure_category", "last_verified_stage", "final_state", "evaluation_evidence")}
            reference.update(campaign=data["id"], restored_physics="starting_physics" in case)
            return self.start(replay, replay={"case": case, "reference": reference})

        return router
