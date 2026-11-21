"""Adaptive breaking-point search: finds a known break, stops early when nothing breaks, honest verdicts."""

import numpy as np

from dashboard.extensions.robustness import adaptive
from dashboard.extensions.robustness.adaptive import BreakpointSearch


def simulate(theta, base=0.9, budget=15, seed=0, top=8.0):
    rng = np.random.default_rng(seed)
    search = BreakpointSearch(0, top)
    obs = [(0.0, bool(rng.random() < base)) for _ in range(3)]
    while len(obs) < budget:
        search.fit(obs)
        if search.stop_reason(len(obs) - 3):
            break
        s, gain = search.next_strength()
        assert 0 <= s <= top and gain >= 0
        p = base / (1 + np.exp(-(theta - s) / 0.5))
        obs.append((s, bool(rng.random() < p)))
    search.fit(obs)
    return search, obs


def test_finds_a_known_breaking_point():
    covered = 0
    for seed in range(10):
        search, _ = simulate(theta=4.0, seed=seed)
        lo, hi = search.estimate()["ci"]
        covered += lo <= 4.0 <= hi
    assert covered >= 8  # 80 % interval: should hold in most runs


def test_concentrates_trials_near_the_break():
    _, obs = simulate(theta=2.0, seed=1)
    searched = [s for s, _ in obs[3:]]
    assert np.median(np.abs(np.array(searched) - 2.0)) < 2.0


def test_stops_early_when_nothing_breaks():
    search, obs = simulate(theta=50.0, seed=2)
    assert len(obs) < 10
    assert search.stop_reason(len(obs) - 3) == "robust in the whole range"


def rows(values_events, level=1.0):
    return [{"value": v, "outcome": "success" if y else "no_grasp", "progress": 1.0 if y else 0.25, "index": i}
            for i, (v, y) in enumerate(values_events, 1)]


def test_verdicts():
    weak = adaptive.summarize(rows([(0, False)] * 3), 0, 8, "cm", "success", 12)
    assert "never happens" in weak["verdict"]["text"] and weak["verdict"]["breaking_point"] is None
    # the same trials still count for a weaker stage: progress 0.25 = reached
    reached = adaptive.summarize(rows([(0, False)] * 3), 0, 8, "cm", "reached", 12)
    assert "never happens" not in reached["verdict"]["text"]
    broke = adaptive.summarize(rows([(0, True)] * 3 + [(2, True), (6, False), (4, False), (3, True), (3.5, False)]),
                               0, 8, "cm", "success", 12)
    assert broke["verdict"]["breaking_point"] is not None and 2 < broke["verdict"]["breaking_point"] < 5
    assert len(broke["curve"]["s"]) == len(broke["curve"]["mean"]) == len(broke["curve"]["lo"])


def test_invalid_trials_do_not_count():
    r = rows([(0, True)] * 3)
    r.append({"value": 5, "outcome": "invalid", "progress": None, "index": 4})
    assert len(adaptive.summarize(r, 0, 8, "cm", "success", 12)["observations"]) == 3
