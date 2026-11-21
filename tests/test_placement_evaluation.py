import mujoco
import pytest

from dashboard.extensions.test_suite.evaluation import Placement, placement
from dreamtool import scene, sim


@pytest.mark.parametrize(("prompt", "goal"), [
    ("Please, place the water bottle inside the bowl.", ("water_bottle", "bowl")),
    ("Set a banana on top of the dish, please!", ("banana", "plate")),
    ("Move an orange to the plate", ("orange", "plate")),
    ("Banana on plate", ("banana", "plate")),
    ("Do not place the apple in the bowl.", None),
    ("Put the banana on the plate and then remove it", None),
    ("Put the apple beside the bowl", None),
    ("Put water into the bowl", None),
    ("Move a cube to the plate", None),
])
def test_supported_single_final_goal(prompt, goal):
    assert placement(prompt) == goal


def test_diagnostics_distinguish_missing_and_lost_target():
    env = sim.YamEnv()
    try:
        trial = Placement(("banana", "plate"))
        trial.sample(env)
        assert "made no verified contact" in trial.result("request_budget", False)[1]
        scene.place(env, "banana", "plate", height=.02)
        mujoco.mj_forward(env.model, env.data)
        trial.sample(env)
        assert trial.latest["best_planar_distance_m"] == pytest.approx(0)
        assert trial.latest["height_above_target_m"] == pytest.approx(.02)
        scene.shift(env, "banana", [0.2, 0])
        mujoco.mj_forward(env.model, env.data)
        trial.sample(env)
        assert trial.latest["entered_target_region"]
        assert trial.latest["planar_distance_m"] == pytest.approx(.2)
        assert trial.latest["best_planar_distance_m"] == pytest.approx(0)
        assert "subsequently left" in trial.result("task_deadline", False)[1]
    finally:
        env.close()


def test_pickup_failure_uses_verified_contact_at_22_point_8_seconds():
    trial = Placement(("banana", "plate"))
    trial.latest = {
        "in_target_region": False, "entered_target_region": False, "supported_by_target": False,
        "released": True, "gripper_contact_observed": True, "picked_up": False,
        "closest_gripper_distance_m": .12,
        "events": [{"event": "Gripper contacted object", "simulation_time": 22.8}],
    }
    verdict, reason = trial.result("task_deadline", False)
    assert verdict is False
    assert trial.classify("task_deadline", verdict) == ("PICKUP_FAILED", "Gripper contact")
    assert "Gripper contact was observed at 22.8 s" in reason
    assert "no successful lift" in reason
