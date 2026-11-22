"""Inference strategies: chunk execution, temporal ensembling, smoothness stats, and the runner wiring."""
import math
import time
from types import SimpleNamespace

import numpy as np
import pytest

from dashboard.extensions.robustness import compare
from dreamtool import inference, runner


def test_parse_strategies():
    assert inference.parse("chunk") == inference.Strategy()
    assert inference.parse(None).id == "chunk"
    assert inference.parse("receding-48").id == "chunk"  # executing all 48 rows is the default
    s = inference.parse(" Ensemble-16 ")
    assert (s.id, s.execute, s.ensemble) == ("ensemble-16", 16, True)
    assert inference.parse("receding-8").execute == 8
    for bad in ("ensemble-0", "receding-49", "blend-4", "ensemble", "16"):
        with pytest.raises(ValueError):
            inference.parse(bad)
    assert all(inference.is_valid(p) for p in inference.PRESETS)


def test_chunk_and_receding_execute_a_prefix():
    chunk = np.arange(48 * 7, dtype=float).reshape(48, 7)
    left, right = inference.ChunkExecutor("chunk").plan(0, chunk, -chunk)
    assert len(left) == 48 and (right == -chunk).all()
    left, _ = inference.ChunkExecutor("receding-16").plan(0, chunk, chunk)
    assert (left == chunk[:16]).all()
    # a shorter chunk than the execution length is executed in full
    left, _ = inference.ChunkExecutor("receding-16").plan(0, chunk[:5], chunk[:5])
    assert len(left) == 5
    # the runner's actions_per_reply still caps the default strategy
    left, _ = inference.ChunkExecutor("chunk", limit=10).plan(0, chunk, chunk)
    assert len(left) == 10


def test_ensemble_blends_overlapping_plans():
    ex = inference.ChunkExecutor("ensemble-16")
    zeros, ones = np.zeros((48, 7)), np.ones((48, 7))
    first, _ = ex.plan(0, zeros, zeros)
    assert (first == 0).all() and len(first) == 16
    second, _ = ex.plan(16, ones, ones)
    # step 16: the new plan looks 0 steps ahead (weight 1), the old one 16 (weight e^-0.8)
    w_old = math.exp(-inference.DEFAULT_DECAY * 16)
    # both look one step further ahead per row, so the mix stays the same along the window (ACT-style averaging)
    assert np.allclose(second[:, 0], 1 / (1 + w_old))
    # the gripper is never averaged: a half-closed gripper drops the object
    assert (second[:, 6] == 1).all()
    # once the old plan has run out it is dropped
    ex.plan(48, ones, ones)
    assert [p[0] for p in ex.predictions] == [16, 48]


def test_crossfade_hands_over_without_a_seam():
    ex = inference.ChunkExecutor("crossfade-16")
    zeros, ones = np.zeros((48, 7)), np.ones((48, 7))
    first, _ = ex.plan(0, zeros, zeros)
    assert (first == 0).all(), "nothing to fade from in the first execution"
    second, _ = ex.plan(16, ones, ones)
    assert second[0, 0] == pytest.approx(1 / 16) and second[-1, 0] == 1
    assert np.allclose(np.diff(second[:, 0]), 1 / 16)
    assert (second[:, 6] == 1).all(), "the gripper follows the new plan at once"
    s = inference.parse("crossfade-16")
    assert (s.blend, s.ensemble, s.label) == ("crossfade", False, "Crossfade (16)")


def test_ensemble_of_agreeing_plans_is_the_plan():
    trajectory = np.linspace(0, 1, 200)[:, None] * np.ones((1, 7))
    for name in ("ensemble-8", "crossfade-8"):
        ex = inference.ChunkExecutor(name)
        executed = []
        for step in range(0, 96, 8):
            rows, _ = ex.plan(step, trajectory[step:step + 48], trajectory[step:step + 48])
            executed.extend(rows)
        assert np.allclose(executed, trajectory[:96]), name


def test_jitter_is_not_fooled_by_slowing_down():
    def motion(path):
        m = inference.Smoothness()
        for q in path:
            m.add(q)
        return m.summary()

    rng = np.random.default_rng(0)
    n = 760
    reach = lambda k: np.sin(np.arange(k * n) / (40 * k))  # noqa: E731  the same reach, k times slower
    seams = lambda k: np.repeat(rng.normal(0, 0.01, k * n // 16 + 1), 16)[:k * n]  # noqa: E731
    as_arms = lambda x: x[:, None] * np.ones((1, 12))  # noqa: E731
    smooth, smooth_slow = motion(as_arms(reach(1))), motion(as_arms(reach(2)))
    shaky, shaky_slow = motion(as_arms(reach(1) + seams(1))), motion(as_arms(reach(2) + seams(2)))
    assert smooth["jitter"] < 0.01 and smooth_slow["jitter"] < 0.01
    assert shaky["jitter"] > 10 * smooth["jitter"]
    # slower with the same seams: absolute jerk barely changes, jitter does not improve
    assert shaky_slow["speed"] < 0.6 * shaky["speed"]
    assert shaky_slow["jitter"] >= shaky["jitter"]
    # absolute jerk mostly measures speed
    assert smooth["jerk"] > 6 * smooth_slow["jerk"]
    # standing still: no jitter share
    assert motion(np.zeros((50, 12)))["jitter"] is None


def test_command_stats_seams():
    stats = inference.CommandStats()
    for i in range(10):
        stats.add(np.full(7, i * 0.01), np.zeros(7), seam=i == 0)
    for i in range(10):  # the second execution starts 0.1 rad off
        stats.add(np.full(7, 0.2 + i * 0.01), np.zeros(7), seam=i == 0)
    s = stats.summary()
    assert s["executions"] == 2 and s["seams"] == 1 and s["rows"] == 20
    assert s["seam_jump_rad"] == pytest.approx(0.11)
    assert s["typical_step_rad"] == pytest.approx(0.01)
    assert s["seam_ratio"] == pytest.approx(11)
    assert s["command_jerk"] > 0


def test_simulated_chunks_ensemble_is_smoother():
    plan = [(np.r_[np.full(6, t / 300), 0.5], np.r_[np.full(6, -t / 300), 0.5]) for t in range(300)]
    chunk_rows, chunk = inference.simulated_chunks(plan, "chunk", [0, 1])
    rec_rows, receding = inference.simulated_chunks(plan, "receding-16", [0, 1])
    ens_rows, ensemble = inference.simulated_chunks(plan, "ensemble-16", [0, 1])
    _, crossfade = inference.simulated_chunks(plan, "crossfade-16", [0, 1])
    assert crossfade["seam_jump_rad"] < receding["seam_jump_rad"] / 4
    assert len(chunk_rows) == len(rec_rows) == len(ens_rows) == 300
    assert chunk["executions"] == math.ceil(300 / 48) and receding["executions"] == math.ceil(300 / 16)
    assert ensemble["seam_jump_rad"] < receding["seam_jump_rad"]
    assert ensemble["command_jerk"] < receding["command_jerk"]
    # paired: the same seed gives the same plan noise
    again, _ = inference.simulated_chunks(plan, "chunk", [0, 1])
    assert all((a[0] == b[0]).all() for a, b in zip(chunk_rows, again))
    # the gripper command is never noisy
    assert np.allclose([row[0][6] for row in ens_rows], 0.5)


class FakeEnv:
    def __init__(self):
        self.commands = []

    def step(self, left, right):
        self.commands.append(np.array(left))

    def state(self):
        return {"left": np.zeros(7), "right": np.zeros(7)}


def run_fake(monkeypatch, strategy, max_steps=48, seconds=60):
    """run_task against a policy whose n-th reply is a chunk filled with n."""
    replies = []

    def get_action():
        replies.append(len(replies))
        value = np.full((48, 7), float(len(replies) - 1))
        value[:, 6] = 0.5
        return {"q_l_chunk": value, "q_r_chunk": value}

    monkeypatch.setattr(runner, "time", SimpleNamespace(monotonic=time.monotonic, sleep=lambda s: None))
    monkeypatch.setattr(runner.sim, "FRAMES", 0)
    monkeypatch.setattr(runner.sim, "open_policy", lambda *_: SimpleNamespace(get_action=get_action, close=lambda: None))
    monkeypatch.setattr(runner.sim, "feed", lambda *a, **k: None)
    monkeypatch.setattr(runner.sim, "capture", lambda *a, **k: {})
    monkeypatch.setattr(runner.sim, "validate_chunk", lambda env, reply, limit, **k: (reply["q_l_chunk"][:limit], reply["q_r_chunk"][:limit]))
    env = FakeEnv()
    result = runner.run_task("wave the arms", env=env, api_key="test", seconds=seconds, verbose=False,
                             strategy=strategy, max_steps=max_steps)
    return result, env


def test_runner_replans_with_strategy(monkeypatch):
    result, env = run_fake(monkeypatch, "chunk")
    assert (result.requests, result.steps, result.stop_reason, result.strategy) == (1, 48, "timeout", "chunk")
    assert result.commands["executions"] == 1 and result.commands["seams"] == 0

    result, env = run_fake(monkeypatch, "receding-16")
    assert (result.requests, result.steps, result.strategy) == (3, 48, "receding-16")
    assert result.commands["seams"] == 2
    assert [c[0] for c in env.commands[::16]] == [0, 1, 2]

    result, env = run_fake(monkeypatch, "ensemble-16")
    w_old = math.exp(-inference.DEFAULT_DECAY * 16)
    assert env.commands[16][0] == pytest.approx(1 / (1 + w_old))
    assert result.commands["seam_jump_rad"] < 1


def test_mcnemar_exact():
    assert compare.mcnemar_exact(0, 0) is None
    assert compare.mcnemar_exact(0, 3) == pytest.approx(0.25)
    assert compare.mcnemar_exact(0, 6) == pytest.approx(2 / 64)
    assert compare.mcnemar_exact(3, 3) == 1.0


def _row(trial, strategy, success, progress, seam, jitter=3.0):
    return {"trial": trial, "strategy": strategy, "success": success, "progress": progress, "outcome":
            "success" if success else "no_grasp", "requests": 3 if strategy != "chunk" else 1, "steps": 600,
            "seconds": 40.0, "commands": {"seam_jump_rad": seam, "seam_ratio": seam * 100, "command_jerk": 1.0},
            "metrics": {"joint_jerk": 2.0 if strategy == "chunk" else 1.0, "joint_speed": 0.1 if strategy == "chunk" else 0.06,
                        "joint_jitter": 3.0 if strategy == "chunk" else jitter}}


def test_compare_summary_pairs_and_verdict():
    strategies = [inference.parse(s).describe() for s in ("chunk", "ensemble-16")]
    rows = []
    for t in range(1, 9):
        rows.append(_row(t, "chunk", t <= 2, 1.0 if t <= 2 else 0.25, 0.08))
        rows.append(_row(t, "ensemble-16", True, 1.0, 0.02))
    summary = compare.compare_summary(strategies, rows)
    pair = summary["pairs"][0]
    assert (pair["n"], pair["only_baseline"], pair["only_this"], pair["both"]) == (8, 0, 6, 2)
    assert pair["p_value"] == pytest.approx(0.031, abs=1e-3)
    assert pair["seam_change"] == pytest.approx(-0.75)
    assert pair["requests_factor"] == 3
    assert summary["verdict"]["best"] == "ensemble-16" and summary["verdict"]["significant"]
    assert "Temporal ensemble (16) wins: 8/8" in summary["verdict"]["text"]
    assert "arms 40% slower" in summary["verdict"]["text"]
    # half the absolute jerk only because it is slower: not called smoother
    assert pair["speed_change"] == pytest.approx(-0.4) and pair["jitter_change"] == 0
    assert summary["verdict"]["smoothest"] is None
    smoother = compare.compare_summary(strategies, [_row(1, "chunk", True, 1, 0.1),
                                                    _row(1, "ensemble-16", True, 1, 0.05, jitter=2.0)])
    assert smoother["verdict"]["smoothest"] == "ensemble-16"
    assert "jitter −33%" in smoother["verdict"]["text"]
    # nothing differs yet
    same = compare.compare_summary(strategies, [_row(1, "chunk", True, 1, 0.1), _row(1, "ensemble-16", True, 1, 0.1)])
    assert same["verdict"]["best"] is None and "No difference" in same["verdict"]["text"]
    assert compare.compare_summary(strategies, [])["verdict"]["text"] == "No trials yet."


def test_runner_waits_out_a_full_pool(monkeypatch):
    """Measured: DA-2000 pool_full ended a campaign. A retryable refusal is now waited out (physics is paused)."""
    class PoolFull(Exception):
        retryable, retry_after_s, reason = True, 0.0, "pool_full"

    calls = []

    def get_action():
        calls.append(1)
        if len(calls) == 2:
            raise PoolFull("DA-2000 NO_CAPACITY")
        value = np.zeros((48, 7))
        value[:, 6] = 0.5
        return {"q_l_chunk": value, "q_r_chunk": value}

    monkeypatch.setattr(runner, "time", SimpleNamespace(monotonic=time.monotonic, sleep=lambda s: None))
    monkeypatch.setattr(runner.sim, "FRAMES", 0)
    monkeypatch.setattr(runner.sim, "open_policy", lambda *_: SimpleNamespace(get_action=get_action, close=lambda: None))
    monkeypatch.setattr(runner.sim, "feed", lambda *a, **k: None)
    monkeypatch.setattr(runner.sim, "capture", lambda *a, **k: {})
    monkeypatch.setattr(runner.sim, "validate_chunk", lambda env, reply, limit, **k: (reply["q_l_chunk"], reply["q_r_chunk"]))
    result = runner.run_task("wave the arms", env=FakeEnv(), api_key="test", seconds=60, verbose=False, max_steps=96)
    assert result.stop_reason == "timeout" and result.steps == 96 and result.retries == 1


def test_paused_physics_keeps_the_new_plan_from_row_0(monkeypatch):
    """Measured: the client replaces round(rtt x 20) rows of each new chunk with the old plan, assuming the robot kept
    moving during the request. Physics is paused here, so the runner tells it so (action_hz ~ 0 -> clock row 0)."""
    from dream import smoothing

    previous = np.tile(np.linspace(0, 1, 48)[:, None], (1, 7))
    assert smoothing.old_motion(previous, 20, 0.55 * 20)[0] == 11, "the client's default: 11 rows of the old plan"
    assert smoothing.old_motion(previous, 20, 0.55 * runner.PAUSED_ACTION_HZ)[0] == 0

    seen = {}

    def open_policy(options, key):
        seen.update(options)
        raise RuntimeError("stop here")

    monkeypatch.setattr(runner.sim, "FRAMES", 0)
    monkeypatch.setattr(runner.sim, "open_policy", open_policy)
    with pytest.raises(RuntimeError):
        runner.run_task("wave the arms", env=FakeEnv(), api_key="test", verbose=False)
    assert seen["action_hz"] == runner.PAUSED_ACTION_HZ
    seen.clear()
    with pytest.raises(RuntimeError):
        runner.run_task("wave the arms", env=FakeEnv(), api_key="test", verbose=False, latency="client")
    assert "action_hz" not in seen or seen["action_hz"] == 20


def test_wall_clock_cut_is_not_a_used_up_budget(monkeypatch):
    """Measured 22.11.2026: requests hung while the machine slept, the wall clock ended a trial after 240 of 800 steps
    and it was scored as a model failure. Under a simulated budget that is `wall_timeout`, which is never scored."""
    result, _ = run_fake(monkeypatch, "chunk", max_steps=48, seconds=1e-9)
    assert result.stop_reason == "wall_timeout" and result.steps < 48
    result, _ = run_fake(monkeypatch, "chunk", max_steps=None, seconds=1e-9)
    assert result.stop_reason == "timeout", "without a simulated budget the wall clock is the budget"
