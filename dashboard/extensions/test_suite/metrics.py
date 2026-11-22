"""Trial evidence and campaign statistics."""
from collections import Counter, defaultdict
from hashlib import sha256
import time

import mujoco
import numpy as np

from dreamtool import Hooks, VideoRecorder, scene
from .evaluation import Placement, placement_failure
from .telemetry import RunTelemetry

JOINT_LIMITS = "Joint limits"
ARM_CONTACT = "Contact between opposite arms"


class Evidence(Hooks):
    def __init__(self, cancelled, video, goal, stage):
        self.cancelled = cancelled
        self.recorder = VideoRecorder(video) if video else None
        self.issues = {}
        self.safety_violations = {}
        self.actions = []
        self.contact_steps = 0
        self.samples = 0
        self.limits = []
        self.evaluator = Placement(goal)
        self.stage = stage
        self.timeline = [{"stage": "queued", "at": time.time()}]
        self.requests = []
        self.started = False
        self.telemetry = RunTelemetry()
        self.fingerprints = set()
        self.last_fingerprint = None
        self.consecutive_chunks = 0
        self.motion_anchor = None
        self.stationary_since = None
        self.stationary_seconds = 0.
        self.robot_moved = False
        self.initial_arm_contacts = set()

    def arm_contacts(self, env):
        contacts = set()
        for contact in env.data.contact[:env.data.ncon]:
            if contact.efc_address < 0:
                continue
            names = sorted(env.model.body(int(env.model.geom_bodyid[geom])).name for geom in contact.geom)
            if names[0].startswith("left_") and names[1].startswith("right_"):
                contacts.add(tuple(names))
        return contacts

    def scene_diagnostics(self, env, step, preexisting=False):
        table = env.model.geom("table")
        table_top = table.pos[2] + table.size[2]
        for name in scene.OBJECTS:
            if scene.position(env, name)[2] < table_top - 0.05:
                self.issues.setdefault(name, dict(
                    severity="Warning", reason=f"{name} below tabletop",
                    step=step, simulation_time=float(env.data.time), preexisting=preexisting,
                ))

    def prepare(self, env):
        self.evaluator.prepare(env)
        self.scene_diagnostics(env, 0, preexisting=True)
        self.initial_arm_contacts = self.arm_contacts(env)

    def mark(self, phase):
        now = time.time()
        self.timeline.append({"stage": phase, "at": now})
        self.stage(phase, at=now)

    def on_request(self, error, rtt_s):
        self.requests.append(dict(request=len(self.requests) + 1, at=time.time(), latency_seconds=rtt_s,
                                  error=str(error) if error else None,
                                  error_type=type(error).__name__ if error else None,
                                  code=getattr(error, "code", None)))

    def on_start(self, env, task, model):
        if self.cancelled.is_set():
            return
        self.started = True
        self.mark("running")
        joint_types = (mujoco.mjtJoint.mjJNT_HINGE, mujoco.mjtJoint.mjJNT_SLIDE)
        self.limits = [
            (env.model.joint(i).name, env.model.jnt_qposadr[i], *env.model.jnt_range[i])
            for i in range(env.model.njnt)
            if env.model.jnt_limited[i] and env.model.jnt_type[i] in joint_types
        ]

    def should_stop(self, env):
        if self.evaluator.complete:
            return "task_completed"
        if self.cancelled.is_set():
            return "stopped"
        if self.stationary_seconds >= 6 and len(self.actions) >= 3:
            return "repeated_ineffective_actions" if self.consecutive_chunks >= 3 else "agent_idle"
        return None

    def on_reply(self, env, reply, rtt_s):
        keys = ("q_l_chunk", "q_r_chunk")
        if all(key in reply for key in keys):
            chunks = np.asarray([reply[key] for key in keys], dtype=float)
            fingerprint = sha256(chunks.tobytes()).digest()
            self.fingerprints.add(fingerprint)
            self.consecutive_chunks = self.consecutive_chunks + 1 if fingerprint == self.last_fingerprint else 1
            self.last_fingerprint = fingerprint
        self.actions.append({
            "simulation_time": float(env.data.time), "rtt_s": rtt_s,
            "actions": {key: np.where(np.isfinite(reply[key]), reply[key], None).tolist()
                        for key in keys if key in reply},
        })

    def action_diagnostics(self):
        return dict(chunks_received=len(self.actions), distinct_chunks=len(self.fingerprints),
                    robot_moved=self.robot_moved if self.samples else None,
                    stationary_seconds=self.stationary_seconds if self.samples else None)

    def safety_checks(self):
        violations = {issue["category"] for issue in self.safety_violations.values()}
        return {
            JOINT_LIMITS: "fail" if JOINT_LIMITS in violations else "pass" if self.samples and self.limits else "not_evaluated",
            ARM_CONTACT: "fail" if ARM_CONTACT in violations else "pass" if self.samples else "not_evaluated",
            "Workspace envelope": "not_evaluated",
            "Contact force limits": "not_evaluated",
        }

    def on_step(self, env, step, images):
        state = env.state()
        self.evaluator.sample(env, state)
        placement = self.evaluator.latest or {}
        self.telemetry.observe(float(env.data.time), placement.get("planar_distance_m"),
                               placement.get("events", ()), images.get("top"))
        arms = np.concatenate((state["left"], state["right"]))
        positions = np.concatenate([scene.position(env, name) for name in scene.OBJECTS])
        now = float(env.data.time)
        if self.motion_anchor is None:
            self.motion_anchor = (arms, positions)
            self.stationary_since = now
        else:
            previous_arms, previous_positions = self.motion_anchor
            moved = np.max(np.abs(arms - previous_arms)) >= .03
            self.robot_moved |= bool(moved)
            if moved or np.max(np.abs(positions - previous_positions)) >= .01:
                self.motion_anchor = (arms, positions)
                self.stationary_since = now
        self.stationary_seconds = now - self.stationary_since
        self.samples += 1
        self.contact_steps += bool(env.data.ncon)
        self.scene_diagnostics(env, step)
        arm_contacts = self.arm_contacts(env)
        self.initial_arm_contacts.intersection_update(arm_contacts)
        for a, b in arm_contacts - self.initial_arm_contacts:
            self.safety_violations.setdefault(f"{a}/{b}", dict(
                category=ARM_CONTACT, severity="Warning", reason=f"Contact between opposite arms ({a}, {b})",
                step=step, simulation_time=now))
        for name, address, low, high in self.limits:
            if not low - 0.01 <= env.data.qpos[address] <= high + 0.01:
                self.safety_violations.setdefault(name, dict(
                    category=JOINT_LIMITS, severity="Warning", reason=f"{name} exceeded its modeled joint range",
                    step=step, simulation_time=float(env.data.time)))
        if self.recorder:
            self.recorder.add(images)

    def close(self):
        if self.recorder:
            self.recorder.close()


def execution_status(reason, success=None):
    if reason in ("timeout", "wall_timeout", "task_deadline", "api_timeout", "agent_timeout"):
        return "timed_out"
    if reason.startswith("error"):
        return "error"
    if reason in ("stopped", "interrupted"):
        return "cancelled"
    if reason in ("request_budget", "agent_idle", "repeated_ineffective_actions") or success is False:
        return "failed"
    return "completed"


def stats(rows):
    evaluated = [row for row in rows if row["task_success"] is not None]
    successful = [row for row in evaluated if row["task_success"]]
    durations = [row["task_duration_seconds"] for row in rows if row["task_duration_seconds"] is not None]
    completed = [row["completion_duration_seconds"] for row in successful
                 if row["completion_duration_seconds"] is not None]
    latencies = [rtt for row in rows for rtt in row.get("rtts_s", [])]
    return dict(
        trials=len(rows), evaluated=len(evaluated), successes=len(successful),
        failures=len(evaluated) - len(successful), unevaluated=len(rows) - len(evaluated),
        success_rate=len(successful) / len(evaluated) if evaluated else None,
        coverage=len(evaluated) / len(rows) if rows else None,
        duration_samples=len(durations), average_duration=float(np.mean(durations)) if durations else None,
        duration_p50=float(np.percentile(durations, 50)) if durations else None,
        duration_p95=float(np.percentile(durations, 95)) if durations else None,
        completion_average=float(np.mean(completed)) if completed else None,
        completion_p50=float(np.percentile(completed, 50)) if completed else None,
        completion_p95=float(np.percentile(completed, 95)) if completed else None,
        durations_by_status={
            status: [row["task_duration_seconds"] for row in rows
                     if row["execution_status"] == status and row["task_duration_seconds"] is not None]
            for status in ("timed_out", "error", "cancelled")
        },
        requests=sum(row["api_request_count"] for row in rows),
        mean_rtt=float(np.mean(latencies)) if latencies else None,
        safety=dict(Counter(row["safety_status"] for row in rows)),
    )


def summarize(report):
    rows = report["trials"]
    groups = defaultdict(list)
    reasons = Counter()
    for row in rows:
        if "task_success" not in row:
            # Older evaluations did not verify release or stability.
            reason = row["stop_reason"]
            dry = report["config"]["dry_run"]
            row.update(task_success=None, execution_status=execution_status(reason),
                       termination_reason=reason, evaluation_status="not_evaluated",
                       safety_status="not_evaluated", task_duration_seconds=None,
                       legacy_loop_duration_seconds=row.get("seconds"), completion_duration_seconds=None,
                       api_request_count=row["requests"], mean_request_latency_seconds=row["mean_rtt_s"],
                       evaluation_method=None, evaluation_evidence=None,
                       failure_reason="Historical dry run." if dry else "Historical run lacks release and stability evidence.",
                       confidence=None)
        if "safety_violations" not in row and row.get("samples") and row.get("issues"):
            issues = row["issues"]
            row["safety_violations"] = [issue for issue in issues if "modeled joint range" in issue["reason"]]
            row["issues"] = [issue for issue in issues if issue not in row["safety_violations"]]
            row["safety_status"] = "fail" if row["safety_violations"] else "pass"
        evidence = row.get("evaluation_evidence")
        if (report["config"].get("mode") == "safety" and evidence and row["task_success"] is not True
                and row["termination_reason"] in ("task_deadline", "request_budget", "task_finished")
                and row.get("evaluation_method")):
            row["failure_category"], row["failure_reason"] = placement_failure(evidence, row["termination_reason"])
        case = row["case"]
        groups[f'{case["offset"]:.1f} cm / {case["tilt"]:.1f}° / {case["light"]:.2f}×'].append(row)
        if row["failure_reason"]:
            reasons[row["failure_reason"]] += 1
    termination = Counter(row["termination_reason"] for row in rows)
    outside = sum(row.get("evaluation_evidence", {}).get("in_target_region") is False
                  for row in rows if row.get("evaluation_evidence"))
    variants = {variant: [row for row in rows if row["case"].get("variant") == variant and "pair" in row["case"]]
                for variant in ("A", "B")}
    by_pair = {row["case"]["pair"]: row for row in variants["B"]}
    pairs = [dict(number=a["case"]["pair"], a=a["number"], b=b["number"], outcome_a=a["task_success"],
                  outcome_b=b["task_success"],
                  duration_delta=(b["task_duration_seconds"] - a["task_duration_seconds"]
                                  if a["task_duration_seconds"] is not None and b["task_duration_seconds"] is not None else None))
             for a in variants["A"] if (b := by_pair.get(a["case"]["pair"]))]
    evaluated_pairs = [pair for pair in pairs if pair["outcome_a"] is not None and pair["outcome_b"] is not None]
    comparison = dict(variants={key: stats(value) | {"failures_by_stage": dict(Counter(
        row["failure_category"] for row in value if row.get("failure_category")))} for key, value in variants.items()},
        pairs=pairs, discordant=sum(pair["outcome_a"] != pair["outcome_b"] for pair in evaluated_pairs),
        evaluated_pairs=len(evaluated_pairs))
    return dict(report, stats=stats(rows), conditions={key: stats(group) for key, group in groups.items()},
                reasons=dict(reasons), execution=dict(Counter(row["execution_status"] for row in rows)),
                diagnostics=dict(termination=dict(termination), outside_target=outside,
                                 categories=dict(Counter(row["failure_category"] for row in rows if row.get("failure_category")))),
                comparison=comparison if report["config"].get("mode") == "ab" else None,
                stress=stress_summary(rows) if report["config"].get("mode") == "safety" else None)


def stress_summary(rows):
    scenarios = defaultdict(list)
    for row in rows:
        case = row["case"]
        name = case.get("stress_scenario") or "unlabeled"
        scenarios[name].append(row)

    def summarize_group(group):
        measured = [row["evaluation_evidence"] for row in group
                    if row.get("evaluation_method") and row.get("evaluation_evidence")]
        pickups = [evidence["picked_up"] for evidence in measured if isinstance(evidence.get("picked_up"), bool)]
        progress = [max(0., evidence["initial_planar_distance_m"] - evidence["best_planar_distance_m"])
                    for evidence in measured if evidence.get("initial_planar_distance_m") is not None
                    and evidence.get("best_planar_distance_m") is not None]
        checks = Counter()
        violations = Counter()
        check_names = set()
        for row in group:
            for name, status in row.get("safety_checks", {}).items():
                check_names.add(name)
                if status in ("pass", "fail"):
                    checks[name] += 1
                if status == "fail":
                    violations[name] += 1
        evaluated = [row for row in group if row["task_success"] is not None]
        return dict(runs=len(group), evaluated=len(evaluated), successes=sum(row["task_success"] for row in evaluated),
                    pickups=sum(pickups), pickup_observed=len(pickups),
                    placements=sum(row["task_success"] is True for row in group if row.get("evaluation_method")),
                    placement_observed=len(measured),
                    timeouts=sum(row["execution_status"] == "timed_out" for row in group),
                    checks=dict(checks), violations=dict(violations), check_names=sorted(check_names),
                    stages=dict(Counter(row["last_verified_stage"] for row in group if row.get("last_verified_stage"))),
                    mean_progress_m=float(np.mean(progress)) if progress else None)

    baseline = scenarios.pop("baseline", [])
    return dict(scenarios={name: summarize_group(group) for name, group in scenarios.items()},
                baseline=summarize_group(baseline) if baseline else None, total=summarize_group(rows))
