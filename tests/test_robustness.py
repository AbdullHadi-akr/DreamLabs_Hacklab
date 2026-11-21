"""Robustness extension without the API: perturbations restore the model, setups are fair, analysis is sane."""

import numpy as np
import pytest

from dashboard.extensions.robustness import analysis, replay
from dashboard.extensions.robustness.monitor import TrialMonitor
from dashboard.extensions.robustness.perturbations import (
    REGISTRY, InvalidSetup, Target, as_effect, check_scene, prepare, rewrite,
)
from dreamtool import runner, scene, sim

TARGET = Target("apple", "bowl")


@pytest.fixture(scope="module")
def env():
    e = sim.YamEnv()
    yield e
    e.close()


def model_snapshot(env):
    m = env.model
    return {name: getattr(m, name).copy() for name in (
        "cam_pos", "cam_quat", "light_diffuse", "light_ambient", "light_specular", "body_pos", "body_mass",
        "body_inertia", "geom_friction", "geom_rgba", "mat_rgba", "geom_matid", "body_invweight0", "dof_invweight0")} | {
        "headlight": np.r_[m.vis.headlight.diffuse, m.vis.headlight.ambient]}


@pytest.mark.parametrize("pid", [p.id for p in REGISTRY.values() if p.kind == "env"])
def test_env_perturbation_restores_model(env, pid):
    p = REGISTRY[pid]
    before = model_snapshot(env)
    env.reset()
    effect = as_effect(p.fn(env, p.defaults[-1], np.random.default_rng(1), TARGET))
    env.images()  # rendering must still work
    effect.undo(env)
    after = model_snapshot(env)
    for key in before:
        assert np.array_equal(before[key], after[key]), f"{pid} left {key} changed"
    assert "images" not in env.__dict__


def test_visual_perturbations_change_the_image(env):
    env.reset()
    base = env.images()["top"].astype(float)
    for pid in ("light_dim", "table_color", "target_color", "image_noise", "camera_tilt"):
        p = REGISTRY[pid]
        env.reset()
        effect = as_effect(p.fn(env, p.defaults[-1], np.random.default_rng(2), TARGET))
        changed = (np.abs(env.images()["top"].astype(float) - base).sum(axis=2) > 40).sum()
        effect.undo(env)
        assert changed > 300, f"{pid} has no visible effect ({changed} pixels changed)"


def test_paired_draws_same_direction_at_every_strength(env):
    p = REGISTRY["target_shift"]
    offsets = []
    for value in (2, 6):
        effects, _ = prepare(env, [(p, value)], TARGET, seed=[0, 3])
        offsets.append(scene.position(env, "apple")[:2] - env.model.body("apple").pos[:2])
    a, b = (o / np.linalg.norm(o) for o in offsets)
    assert a @ b > 0.95


def test_overlapping_setup_is_rejected(env):
    env.reset()
    # the apple right on top of the orange: settling pushes them apart
    scene.shift(env, "apple", scene.position(env, "orange")[:2] - scene.position(env, "apple")[:2])
    assert check_scene(env, TARGET) is not None
    env.reset()
    assert check_scene(env, TARGET) is None


def test_impossible_strength_raises_invalid(env):
    p = REGISTRY["target_shift"]
    with pytest.raises(InvalidSetup):
        prepare(env, [(p, 200)], TARGET, seed=[0, 0], attempts=3)


def test_prompt_rewrites():
    typos = REGISTRY["prompt_typos"]
    paraphrase = REGISTRY["prompt_paraphrase"]
    task = "put apple into the bowl"
    assert rewrite(task, [(typos, 0)], TARGET, [0, 0]) == task
    noisy = rewrite(task, [(typos, 20)], TARGET, [0, 0])
    assert noisy != task and noisy == rewrite(task, [(typos, 20)], TARGET, [0, 0])  # reproducible
    assert rewrite(task, [(paraphrase, 4)], TARGET, [0, 0]) == "put the red fruit into the bowl"
    assert scene.parse_task(task) == tuple(TARGET)  # success is still judged on the original task


def test_scripted_replay_and_monitor(env):
    plan = replay.plan(env, "apple", "bowl")
    env.reset()
    ok = TrialMonitor("apple", "bowl")
    ok.on_start(env, "", "")
    runner.run_scripted(env, plan, hooks=[ok])
    ok.on_end(env, runner.RunResult("", "", stop_reason="done", success=scene.is_in(env, "apple", "bowl")))
    assert ok.metrics["outcome"] == "success" and ok.metrics["progress"] == 1.0

    env.reset()
    still = TrialMonitor("apple", "bowl")
    still.on_start(env, "", "")
    runner.run_scripted(env, replay.hold_still(env), hooks=[still])
    still.on_end(env, runner.RunResult("", "", stop_reason="done", success=False))
    assert still.metrics["outcome"] == "no_reach" and still.metrics["progress"] == 0.0


def test_wilson_and_verdict():
    lo, hi = analysis.wilson(3, 3)
    assert 0.4 < lo < 0.5 and hi == 1.0
    rows = [{"value": v, "success": s, "outcome": "success" if s else "no_grasp", "progress": 1.0 if s else 0.25}
            for v, s in [(0, True), (0, True), (0, True), (2, True), (2, True), (2, False), (4, False), (4, False),
                         (4, False)]]
    summary = analysis.sweep_summary([0, 2, 4], rows, 0, "cm")
    assert summary["verdict"]["breaking_point"] == 4
    assert "robust up to 2 cm" in summary["verdict"]["text"].lower()
    weak_base = [dict(r, success=False, outcome="no_grasp", progress=0.5 if r["value"] == 0 else 0.0) for r in rows]
    summary = analysis.sweep_summary([0, 2, 4], weak_base, 0, "cm")
    assert summary["verdict"]["metric"] == "progress" and summary["verdict"]["breaking_point"] == 2


def test_random_summary_finds_harmful_factor():
    rng = np.random.default_rng(0)
    rows = []
    for i in range(20):
        shift, light = rng.uniform(0, 8), rng.uniform(0, 75)
        success = shift < 3
        rows.append({"index": i, "params": {"target_shift": shift, "light_dim": light}, "success": success,
                     "outcome": "success" if success else "no_grasp", "progress": 1.0 if success else 0.25})
    summary = analysis.random_summary({"target_shift": 8, "light_dim": 75}, {"target_shift": 0, "light_dim": 0}, rows)
    assert summary["verdict"]["most_harmful"] == "target_shift"


def test_heavy_target_keeps_physics_stable(env):
    """Regression: scaling a mass without recomputing the model constants made MuJoCo blow up mid-grasp."""
    plan = replay.plan(env, "apple", "bowl")
    effects, _ = prepare(env, [(REGISTRY["target_mass"], 8)], TARGET, seed=[0, 0])
    monitor = TrialMonitor("apple", "bowl")
    monitor.on_start(env, "", "")
    runner.run_scripted(env, plan, hooks=[monitor])
    monitor.on_end(env, runner.RunResult("", "", stop_reason="done", success=scene.is_in(env, "apple", "bowl")))
    for effect in effects:
        effect.undo(env)
    assert monitor.metrics["outcome"] != "invalid", monitor.metrics
    assert monitor.metrics["max_lift_cm"] > 5
