"""Admission, persistence and serial ownership for Fork Here comparisons."""
import json
import threading
import time
from uuid import UUID, uuid4

from fastapi import HTTPException

from dashboard import credits
from dashboard.simulation import SimulatorReserved
from dreamtool import sim
from .checkpoint import ForkExecution, STEP_LIMIT, budgets, chunks, read_checkpoint, set_physics
from .evaluation import Placement
from .scenarios import capture_start
from dreamtool.runner import Hooks

BRANCHES = ("baseline", "guarded")


def check_budget(db, model, requests):
    price = credits.price(model)
    if db is None or price is None:
        raise HTTPException(409, "A configured local price and credit ledger are required for a live fork.")
    maximum = round(price * requests, 6)
    balance = credits.summary(db)
    if min(balance["balance_usd"], balance["month_left_usd"]) < maximum:
        raise HTTPException(409, "The local credit balance or monthly limit cannot cover the comparison's maximum cost.")
    return maximum


class BranchHooks(Hooks):
    def __init__(self, evaluator, cancelled):
        self.evaluator, self.cancelled = evaluator, cancelled

    def on_step(self, env, step, images):
        self.evaluator.sample(env)

    def should_stop(self, env):
        if self.cancelled.is_set():
            return "stopped"
        if self.evaluator.complete:
            return "task_completed"
        return None


class Forks:
    def __init__(self, suite):
        self.suite = suite
        self.worker = suite.ctx.sim
        self.lock = threading.RLock()
        self.active = None
        self.cancelled = threading.Event()

    def checkpoint(self, campaign, trial):
        report = self.suite.read(campaign)
        if report["state"] == "running" or not 1 <= trial <= len(report["trials"]):
            raise HTTPException(409, "Select a recorded trial in a finished campaign.")
        reference = report["trials"][trial - 1].get("checkpoint")
        if not reference:
            raise HTTPException(409, "This trial has no restorable checkpoint. Run an eligible banana-to-plate trial.")
        try:
            return read_checkpoint(self.suite.directory(campaign) / f"{trial}.checkpoint.json.gz", reference)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    def quote(self, saved):
        base, guarded = budgets(saved)
        scripted = saved["script"] is not None
        calls = 0 if scripted else base + guarded
        maximum = 0 if scripted else check_budget(self.worker.db, saved["model"], calls)
        return dict(api_request_limit=calls, max_cost_usd=maximum, baseline_request_limit=0 if scripted else base,
                    guarded_request_limit=0 if scripted else guarded, additional_replans=1)

    def path(self, campaign, comparison):
        return self.suite.directory(campaign) / "comparisons" / f"{comparison.hex}.json"

    def save(self, campaign, data):
        target = self.path(campaign, UUID(data["id"]))
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, allow_nan=False), encoding="utf-8")
        temporary.replace(target)

    def history(self, campaign, trial):
        folder = self.suite.directory(campaign) / "comparisons"
        with self.lock:
            items = [json.loads(path.read_text(encoding="utf-8")) for path in folder.glob("*.json")]
            for item in items:
                if item["state"] == "running" and item["id"] != self.active:
                    item["state"] = "interrupted"
                    for branch in item["branches"].values():
                        if branch["status"] in ("pending", "running"):
                            branch.update(status="interrupted", reason="The dashboard restarted.")
            return sorted((item for item in items if item["trial"] == trial),
                          key=lambda item: item["created"], reverse=True)

    def launch(self, campaign, trial, confirmed):
        saved = self.checkpoint(campaign, trial)
        scripted = saved["script"] is not None
        worker = self.worker
        with self.suite.lock, worker.controls_lock, self.lock:
            ext_busy = any(getattr(ext, "campaign", None) and ext.campaign.state == "running"
                           or (getattr(ext, "job", None) or {}).get("state") == "running"
                           for ext in worker.extensions)
            if self.active or self.suite.active or worker.busy or ext_busy:
                raise HTTPException(409, "The simulator is busy. Wait for the active run or comparison.")
            if not worker.ready.is_set() or worker.error:
                raise HTTPException(503, "The simulator is unavailable.")
            if worker.recorder is not None and worker.recorder.episode:
                raise HTTPException(409, "Save or discard the open episode before starting a fork.")
            quote = self.quote(saved)
            if not scripted and (not confirmed or not sim.settings().get("DREAM_API_KEY")):
                raise HTTPException(409, "A live fork requires a configured key and confirmation of its request limit.")
            comparison = dict(id=uuid4().hex, campaign=campaign.hex, trial=trial, checkpoint=saved["id"],
                              created=time.time(), state="running", scripted=scripted, quote=quote,
                              branches={name: {"status": "pending"} for name in BRANCHES})
            self.save(campaign, comparison)
            self.active = comparison["id"]
            self.cancelled.clear()
            try:
                worker.call(lambda env: self.run(env, campaign, saved, comparison), exclusive=True)
            except SimulatorReserved as error:
                self.active = None
                comparison["state"] = "error"
                for branch in comparison["branches"].values():
                    branch.update(status="not_run", reason=str(error))
                self.save(campaign, comparison)
                raise HTTPException(409, str(error)) from error
        with self.lock:
            return json.loads(self.path(campaign, UUID(comparison["id"])).read_text(encoding="utf-8"))

    def stop(self, comparison):
        with self.lock:
            if self.active != comparison.hex:
                raise HTTPException(409, "This comparison is no longer running.")
            self.cancelled.set()
        return {"ok": True}

    def branch(self, saved, name, limit, comparison):
        scripted = saved["script"] is not None
        guarded = name == "guarded"
        script = None
        if scripted:
            open_row = [list(row) for row in saved["command"]]
            open_row[0 if saved["side"] == "left" else 1][6] = 1.
            wrong = [open_row] * 48
            script = [wrong, *chunks(saved["script"])] if guarded else [wrong] * limit
            limit = min(limit, len(script))
        evaluator = Placement(("banana", "plate"))
        execution = ForkExecution(evaluator, saved["task"], saved["model"], script=script,
                                  checkpoint=saved, guarded=guarded)
        result = self.worker.run_reserved(saved["task"], model=saved["model"], offline=scripted,
                                          seconds=saved["remaining_seconds"], max_requests=limit,
                                          strategy="chunk", latency="paused", max_steps=STEP_LIMIT,
                                          capture_each_step=False, experiment=execution,
                                          hooks=[BranchHooks(evaluator, self.cancelled)], source="fork_here",
                                          label=f"{comparison} · {name}")
        reason = result.stop_reason
        status = ("restore_failed" if not execution.verified else "cancelled" if reason == "stopped"
                  else "error" if reason.startswith("error:") or reason == "api_timeout" else "complete")
        evidence = evaluator.latest if execution.verified else None
        verdict, _ = evaluator.result(reason, False)
        if reason.startswith("guard_"):
            verdict = False
        price = credits.price(saved["model"])
        return dict(status=status, reason=reason, start_verified=execution.verified, outcome=verdict,
                    sim_seconds=result.sim_seconds if execution.verified else None,
                    target_entry=evidence and evidence["entered_target_region"],
                    stable_placement=evidence and evidence["stable_placement_observed"],
                    requests=result.requests, scripted_chunks=result.scripted_requests,
                    cost_usd=0 if scripted else round(result.requests * price, 6), guard_activations=execution.activations,
                    replans=execution.replans, guard_events=execution.events,
                    evaluation_events=evaluator.events[execution.event_start:] if evidence else [])

    def run(self, env, campaign, saved, comparison):
        branches = comparison["branches"]
        original = None
        try:
            original = capture_start(env)
            for name, limit in zip(BRANCHES, budgets(saved)):
                if self.cancelled.is_set() or self.worker.shutdown_event.is_set():
                    branches[name] = dict(status="cancelled", reason="Stopped before starting.")
                    continue
                if any(branch["status"] == "restore_failed" for branch in branches.values()):
                    branches[name] = dict(status="not_run", reason="The comparison could not verify restored conditions.")
                    continue
                with self.lock:
                    branches[name]["status"] = "running"
                    self.save(campaign, comparison)
                branch = self.branch(saved, name, limit, comparison["id"])
                with self.lock:
                    branches[name] = branch
                    self.save(campaign, comparison)
            statuses = {branch["status"] for branch in branches.values()}
            comparison["state"] = ("cancelled" if "cancelled" in statuses else "done" if statuses == {"complete"}
                                   else "error")
        except Exception as error:
            comparison["state"] = "error"
            for branch in branches.values():
                if branch["status"] in ("running", "pending"):
                    branch.update(status="error", reason=f"{type(error).__name__}: {error}")
        finally:
            with self.lock:
                try:
                    if original is not None:
                        set_physics(env, original)
                except ValueError as error:
                    comparison.update(state="error", restore_error=str(error))
                try:
                    self.save(campaign, comparison)
                finally:
                    self.active = None
