"""The trial monitor tells a released target (gripper opened) from one that slipped out of a closed gripper."""
from types import SimpleNamespace

import numpy as np

from dashboard.extensions.robustness.monitor import TrialMonitor


class StubEnv:
    def __init__(self):
        self.pos = {"banana": np.array([0.0, 0.0, 0.78]), "plate": np.array([0.3, 0.0, 0.76]),
                    "apple": np.array([0.5, 0.5, 0.78]), "orange": np.array([0.6, 0.5, 0.78]),
                    "water_bottle": np.array([0.7, 0.5, 0.8]), "bowl": np.array([-0.3, 0.3, 0.76])}
        self.tcp = {"left": np.array([1.0, 1.0, 1.0]), "right": np.array([0.0, 0.0, 0.80])}
        self.opening = 0.3
        self.data = SimpleNamespace(body=lambda n: SimpleNamespace(xpos=self.pos[n]),
                                    site=lambda n: SimpleNamespace(xpos=self.tcp[n.split("_")[0]]), time=0.0,
                                    warning=[SimpleNamespace(number=0)] * 20)

    def state(self):
        return {"left": np.r_[np.zeros(6), 1.0], "right": np.r_[np.zeros(6), self.opening]}


def run(release: bool):
    env = StubEnv()
    m = TrialMonitor("banana", "plate")
    m.on_start(env, "put the banana on the plate", "x")
    for k in range(10):  # lift it with a closed gripper
        env.pos["banana"] = np.array([0.05 * k / 10, 0, 0.78 + 0.01 * k])
        env.tcp["right"] = env.pos["banana"] + [0, 0, 0.02]
        m.on_step(env, k, {})
    if release:
        env.opening = 0.9
    env.pos["banana"] = np.array([0.08, 0, 0.78])  # back on the table, far from the plate
    m.on_step(env, 11, {})
    m.on_end(env, SimpleNamespace(success=False, stop_reason="timeout"))
    return m.metrics


def test_released_and_slipped_are_told_apart():
    released, slipped = run(True), run(False)
    assert released["drops"] == 1 and released["drop"]["cause"] == "released"
    assert slipped["drops"] == 1 and slipped["drop"]["cause"] == "slipped"
    assert released["outcome"] == "carry_failed"
