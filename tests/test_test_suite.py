"""Test planning, measured completion and execution accounting."""
from types import SimpleNamespace
import threading
from uuid import uuid4

import mujoco
import numpy as np
import pytest
from pydantic import ValidationError

from dashboard.extensions.test_suite import Config, TestSuite as SuiteExtension
from dashboard.extensions.test_suite.evaluation import Placement, placement
from dashboard.extensions.test_suite.metrics import Evidence, stats, stress_summary
from dashboard.extensions.test_suite.scenarios import apply, capture_start, generate
from dreamtool import runner, scene, sim


def test_repetition_count_is_independent_of_variation():
    config = Config(prompt="Banana on plate", position_variation=20, camera_variation=30,
                    difficulty="high", repeats=5, seed=42)
    cases = list(generate(config))
    assert len(cases) == 5 and cases == list(generate(config))
    assert all(case["object"] == "banana" and abs(case["offset"]) <= 20 for case in cases)
    assert len(list(generate(config.model_copy(update={"repeats": 1})))) == 1


def test_only_sweep_combines_conditions():
    settings = dict(prompt="Banana on plate", position_variation=20, camera_variation=30)
    assert len(list(generate(Config(mode="sweep", **settings)))) == 4
    with pytest.raises(ValidationError, match="120 runs"):
        Config(mode="sweep", repeats=30, **settings)
    with pytest.raises(ValidationError, match="Parameter Sweep"):
        Config(positions=[0, 5], **settings)


def test_quick_and_stress_have_distinct_plans():
    quick = list(generate(Config(mode="quick", prompt="banana on plate", repeats=8, position_variation=12)))
    assert len(quick) == 1 and quick[0]["current_scene"] and quick[0]["offset"] == 0
    stress = list(generate(Config(mode="safety", prompt="banana on plate",
                                  stress_scenarios=["visibility", "reach"])))
    assert [(c["offset"], c["tilt"], c["light"]) for c in stress] == [
        (0, -20, .45), (0, 20, .45), (15, 0, 1), (-15, 0, 1),
    ]
    assert [(c["stress_scenario"], c["stress_direction"]) for c in stress] == [
        ("visibility", "negative"), ("visibility", "positive"), ("reach", "positive"), ("reach", "negative"),
    ]


def test_stress_applies_signed_perturbations_and_restores_scene():
    config = Config(mode="safety", prompt="banana on plate", stress_scenarios=["combined"],
                    stress_baseline=True, seed=77)
    baseline, positive, negative = generate(config)
    assert (baseline["offset"], baseline["tilt"], baseline["light"]) == (0, 0, 1)
    assert baseline["stress_scenario"] == "baseline"
    env = sim.YamEnv()
    try:
        x = scene.position(env, "banana")[0]
        original_quat = env.model.camera("top").quat.copy()
        original_light = env.model.light_diffuse.copy()
        for case, sign in [(positive, 1), (negative, -1)]:
            assert case["seed"] == 77
            restore = apply(env, case)
            assert scene.position(env, "banana")[0] == pytest.approx(x + sign * .15)
            rotation = np.empty(4)
            expected = np.empty(4)
            mujoco.mju_axisAngle2Quat(rotation, np.array([1., 0., 0.]), -sign * np.deg2rad(20))
            mujoco.mju_mulQuat(expected, original_quat, rotation)
            np.testing.assert_allclose(env.model.camera("top").quat, expected)
            np.testing.assert_allclose(env.model.light_diffuse, original_light * .45)
            restore()
            np.testing.assert_allclose(env.model.camera("top").quat, original_quat)
            np.testing.assert_allclose(env.model.light_diffuse, original_light)
    finally:
        env.close()


@pytest.mark.parametrize("unsupported", [
    {"stress_scenarios": ["other"]}, {"stress_scenarios": ["reach", "reach"]},
    {"position_variation": 1}, {"camera_variation": 1}, {"difficulty": "low"}, {"positions": [0, 1]},
])
def test_stress_rejects_unsupported_configurations(unsupported):
    with pytest.raises(ValidationError):
        Config(mode="safety", prompt="banana on plate", **unsupported)


def test_stress_summary_keeps_task_safety_and_baseline_independent():
    success = dict(case={"stress_scenario": "baseline"}, task_success=True, execution_status="completed",
                   evaluation_method="deterministic_placement",
                   evaluation_evidence={"picked_up": True, "initial_planar_distance_m": .2, "best_planar_distance_m": .02},
                   safety_checks={"Joint limits": "fail", "Workspace envelope": "not_evaluated"},
                   last_verified_stage="Stable placement")
    failure = success | dict(case={"stress_scenario": "reach"}, task_success=False, execution_status="timed_out",
                             evaluation_evidence={"picked_up": False}, safety_checks={"Joint limits": "pass"})
    summary = stress_summary([success, failure])
    assert summary["baseline"]["successes"] == 1
    assert summary["baseline"]["violations"] == {"Joint limits": 1}
    assert summary["baseline"]["mean_progress_m"] == pytest.approx(.18)
    assert summary["scenarios"]["reach"]["timeouts"] == 1
    assert summary["scenarios"]["reach"]["pickup_observed"] == 1
    assert summary["total"]["checks"] == {"Joint limits": 2}
    assert stress_summary([failure])["baseline"] is None


def test_paired_scenes_and_reproduction_restore_mujoco_start():
    config = Config(mode="ab", prompt="banana on plate", prompt_b="Move the banana onto the plate",
                    position_variation=8, camera_variation=9, seed=22, repeats=3)
    cases = list(generate(config))
    assert len(cases) == 6
    for a, b in zip(cases[::2], cases[1::2]):
        assert (a["variant"], b["variant"]) == ("A", "B")
        assert a["prompt"] != b["prompt"]
        assert all(a[key] == b[key] for key in ("offset", "tilt", "light", "pair", "seed"))
    env = sim.YamEnv()
    try:
        restore = apply(env, cases[0])
        original = capture_start(env)
        restore()
        restore = apply(env, cases[1])
        assert capture_start(env) == original
        env.step(sim.HOME, sim.HOME)
        restore()
        restore = apply(env, dict(cases[0], starting_physics=original))
        assert capture_start(env) == original
        restore()
    finally:
        env.close()


def test_plate_success_requires_supported_stable_pose():
    env = sim.YamEnv()
    try:
        evaluator = Placement(placement("Put the banana on the plate"))
        assert evaluator.result("task_deadline", False)[0] is None
        evaluator.sample(env)
        assert evaluator.result("task_deadline", False)[0] is False
        scene.place(env, "banana", "plate", height=.02)
        mujoco.mj_forward(env.model, env.data)
        evaluator.sample(env)
        assert not evaluator.complete
        for _ in range(30):
            env.step(sim.HOME, sim.HOME)
            evaluator.sample(env)
        assert evaluator.latest["supported_by_target"]
        assert evaluator.latest["released"]
        assert evaluator.result("success", False) == (True, None)
        assert evaluator.result("success", True)[0] is None
    finally:
        env.close()


def test_managed_runner_stops_after_confirmed_completion(monkeypatch):
    env = sim.YamEnv()
    requests = []

    def get_action():
        requests.append(1)
        return {"q_l_chunk": [sim.HOME.tolist()] * 48, "q_r_chunk": [sim.HOME.tolist()] * 48}

    def capture(env, windows, keep):
        if keep:
            for frames in windows.values():
                frames.append(None)
        return {}

    def prepare_reply(env, reply, rtt_s):
        scene.place(env, "banana", "plate", height=.02)
        mujoco.mj_forward(env.model, env.data)

    evidence = Evidence(threading.Event(), None, placement("banana on plate"), lambda *_a, **_kw: None)
    evidence.on_reply = prepare_reply
    monkeypatch.setattr(sim, "open_policy", lambda *_: SimpleNamespace(get_action=get_action, close=lambda: None))
    monkeypatch.setattr(sim, "capture", capture)
    monkeypatch.setattr(sim, "feed", lambda *args, **kwargs: None)
    try:
        result = runner.run_task("banana on plate", env=env, api_key="test-key", hooks=[evidence],
                                 seconds=10, max_requests=4, stop_on_success=False, verbose=False)
        assert result.stop_reason == "task_completed"
        assert result.requests == len(requests) == 1
        assert evidence.evaluator.result(result.stop_reason, False) == (True, None)
        assert result.steps < 48
    finally:
        env.close()


def test_metrics_separate_full_task_durations_and_request_latency():
    first = dict(task_success=True, task_duration_seconds=12, completion_duration_seconds=12,
                 execution_status="completed", safety_status="pass", rtts_s=[.1, .2], api_request_count=2)
    timeout = first | dict(task_success=None, task_duration_seconds=30, completion_duration_seconds=None,
                          execution_status="timed_out", rtts_s=[.3], api_request_count=1)
    result = stats([first, timeout])
    assert result["average_duration"] == 21
    assert result["duration_samples"] == 2
    assert result["completion_average"] == 12
    assert result["durations_by_status"]["timed_out"] == [30]
    assert result["requests"] == 3 and result["mean_rtt"] == pytest.approx(.2)
    assert result["coverage"] == .5
    assert stats([timeout])["success_rate"] is None


def test_scene_anomaly_and_repeated_idle_actions_are_independent():
    env = sim.YamEnv()
    evidence = Evidence(threading.Event(), None, placement("banana on plate"), lambda *_a, **_kw: None)
    try:
        env.data.joint(scene.FREE_JOINTS["orange"]).qpos[2] -= .2
        mujoco.mj_forward(env.model, env.data)
        evidence.prepare(env)
        assert evidence.issues["orange"]["preexisting"]
        assert not evidence.safety_violations
        reply = {"q_l_chunk": [sim.HOME.tolist()], "q_r_chunk": [sim.HOME.tolist()]}
        for _ in range(3):
            evidence.on_reply(env, reply, .1)
        evidence.on_step(env, 1, {})
        env.data.time += 6.1
        evidence.on_step(env, 2, {})
        assert evidence.should_stop(env) == "repeated_ineffective_actions"
        assert evidence.action_diagnostics()["distinct_chunks"] == 1
    finally:
        env.close()


def test_replay_reads_action_files_and_older_inline_timelines(tmp_path):
    extension = SuiteExtension(SimpleNamespace(data_dir=tmp_path))
    campaign = uuid4()
    directory = extension.directory(campaign)
    directory.mkdir()
    (directory / "1.actions.json").write_text('[{"simulation_time": 1.5}]', encoding="utf-8")
    assert extension.read_actions(campaign, {"number": 1}) == [{"simulation_time": 1.5}]
    assert extension.read_actions(campaign, {"number": 2}) == []
    assert extension.read_actions(campaign, {"number": 2, "actions": [{"rtt_s": 0.2}]}) == [{"rtt_s": 0.2}]
