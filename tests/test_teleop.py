"""Teleop extension without the API: kinematics, projection, and keyboard/mouse/gripper commands in the real sim."""

import time
import warnings

import mujoco
import numpy as np
import pytest

warnings.filterwarnings("ignore", category=DeprecationWarning)
from fastapi.testclient import TestClient  # noqa: E402

from dashboard.app import create_app  # noqa: E402
from dashboard.extension import overlay_sphere  # noqa: E402
from dashboard.extensions.teleop.kinematics import (  # noqa: E402
    ArmKinematics, describe, drag_point, project, rotation, view_from_scene)
from dashboard.simulation import MAIN_SIZE, OrbitCamera  # noqa: E402
from dreamtool import scene, sim  # noqa: E402

API = "/api/ext/teleop"


def wait_for(condition, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        value = condition()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError("condition not reached in time")


@pytest.fixture(scope="module")
def env():
    env = sim.YamEnv()
    yield env
    env.close()


@pytest.fixture(scope="module")
def client():
    app = create_app()
    with TestClient(app) as c:
        c.app_ref = app
        wait_for(lambda: c.get(f"{API}/state").json().get("arms"))
        yield c


def tcp(client, side):
    return np.array(client.get(f"{API}/state").json()["arms"][side]["pos"])


def pose(client, side):
    arm = client.get(f"{API}/state").json()["arms"][side]
    return np.r_[arm["pos"], np.radians([arm["rotation"] or 0.0, arm["tilt"]]) * 0.05]  # 1 deg ~ 1 mm


def settled(client, side):
    """TCP once the arm has stopped moving and turning."""
    previous = pose(client, side)
    for _ in range(60):
        time.sleep(0.2)
        current = pose(client, side)
        if np.linalg.norm(current - previous) < 5e-4:
            return current[:3]
        previous = current
    raise AssertionError("arm did not settle")


def test_ik_reaches_table_objects_pointing_down(env):
    kin = ArmKinematics(env.model)
    home = env.state()
    for side, obj in (("left", "apple"), ("right", "banana")):
        target = scene.position(env, obj) + [0, 0, 0.05]
        q, error, rot_error = kin.solve(side, target, q0=home[side][:6], target_axis=(0, 0, -1))
        _, mat = kin.fk(side, q)
        assert error < 0.001 and rot_error < np.radians(1)
        assert mat[:, 2] @ [0, 0, -1] > np.cos(np.radians(1))


def test_ik_turns_the_gripper_and_stops_at_the_wrist_limit(env):
    kin = ArmKinematics(env.model)
    target = scene.position(env, "apple") + [0, 0, 0.06]
    q, _, _ = kin.solve("left", target, q0=env.state()["left"][:6], target_axis=(0, 0, -1))
    _, mat = kin.fk("left", q)
    start = describe(mat)["rotation"]
    goal = rotation(-mat[:, 2], np.radians(30)) @ mat  # 30 deg counterclockwise seen from above
    q, error, rot_error = kin.solve("left", target, goal, q)
    _, mat = kin.fk("left", q)
    assert error < 0.003 and rot_error < np.radians(1)
    assert abs((describe(mat)["rotation"] - start - 30 + 90) % 180 - 90) < 1
    for _ in range(8):  # keep turning: the wrist (joint 6, +-120 deg) stops it, position and tilt stay
        q, error, rot_error = kin.solve("left", target, rotation(-mat[:, 2], np.radians(30)) @ mat, q)
        _, mat = kin.fk("left", q)
    assert abs(abs(q[5]) - np.radians(120)) < 1e-3
    assert rot_error > np.radians(20) and error < 0.003 and describe(mat)["tilt"] < 1


def test_projection_matches_rendered_pixels(env):
    g = env.model.vis.global_
    g.offwidth, g.offheight = max(g.offwidth, MAIN_SIZE[0]), max(g.offheight, MAIN_SIZE[1])
    renderer = mujoco.Renderer(env.model, height=MAIN_SIZE[1], width=MAIN_SIZE[0])
    cam = mujoco.MjvCamera()
    OrbitCamera().apply(cam)
    for azimuth, elevation in ((90, -32), (30, -50)):
        cam.azimuth, cam.elevation = azimuth, elevation
        renderer.update_scene(env.data, camera=cam)
        view = view_from_scene(renderer.scene, *MAIN_SIZE)
        point = env.data.site("left_tcp").xpos.copy()
        overlay_sphere(renderer.scene, point, radius=0.012, rgba=(1, 0, 1, 1))
        u, v = project(view, point)
        r, g_, b = renderer.render()[int(v * MAIN_SIZE[1]), int(u * MAIN_SIZE[0])]
        assert r > 200 and b > 200 and g_ < 80  # the magenta marker is exactly there
        assert np.linalg.norm(drag_point(view, u, v, point) - point) < 1e-3
    renderer.close()


def test_keyboard_jog_moves_only_that_arm(client):
    left, right = settled(client, "left"), settled(client, "right")
    for _ in range(2):
        assert client.post(f"{API}/jog", json={"side": "left", "move": [0, 0, -1], "step": 0.05}).status_code == 200
    moved = settled(client, "left")
    assert abs(moved[2] - (left[2] - 0.10)) < 0.01
    assert np.linalg.norm(moved[:2] - left[:2]) < 0.01
    assert np.linalg.norm(settled(client, "right") - right) < 0.005


def test_mouse_drag_moves_in_the_horizontal_plane(client):
    start = settled(client, "right")
    u, v = client.get(f"{API}/state").json()["arms"]["right"]["screen"]
    client.post(f"{API}/drag", json={"side": "right", "u": u, "v": v, "start": True})
    client.post(f"{API}/drag", json={"side": "right", "u": u + 0.06, "v": v + 0.03})
    end = settled(client, "right")
    assert np.linalg.norm(end[:2] - start[:2]) > 0.03
    assert abs(end[2] - start[2]) < 0.01


def arm(client, side):
    return client.get(f"{API}/state").json()["arms"][side]


def test_rotate_and_tilt_the_gripper(client):
    settled(client, "left")
    client.post(f"{API}/jog", json={"side": "left", "move": [0, 0, -1], "step": 0.05})  # points it straight down
    settled(client, "left")
    start = arm(client, "left")
    assert start["tilt"] < 2
    client.post(f"{API}/jog", json={"side": "left", "rotate": 40})
    settled(client, "left")
    turned = arm(client, "left")
    assert abs((turned["rotation"] - start["rotation"] - 40 + 90) % 180 - 90) < 3
    assert np.linalg.norm(np.subtract(turned["pos"], start["pos"])) < 0.005  # turning does not move the TCP
    client.post(f"{API}/jog", json={"side": "left", "tilt": 20})
    settled(client, "left")
    assert abs(arm(client, "left")["tilt"] - 20) < 3
    pointing = client.app_ref.state.sim.env.data.site("left_tcp").xmat.reshape(3, 3)[:, 2]
    assert pointing[1] < -0.25  # fingertips tilted forward for the robot: away from its base (-y)
    assert client.get(f"{API}/state").json()["orientation"] == "free"  # tilting leaves "points straight down"
    client.post(f"{API}/orientation", json={"mode": "down"})
    client.post(f"{API}/jog", json={"side": "left", "rotate": 1})
    settled(client, "left")
    assert arm(client, "left")["tilt"] < 2


def test_keys_move_as_the_robot_sees_it_by_default(client):
    start = settled(client, "left")
    client.post(f"{API}/jog", json={"side": "left", "move": [1, 0, 0], "step": 0.03})  # W
    forward = settled(client, "left")
    assert forward[1] < start[1] - 0.025  # the robot's forward: away from its base (-y)
    client.post(f"{API}/jog", json={"side": "left", "move": [0, 1, 0], "step": 0.03})  # D
    right = settled(client, "left")
    assert right[0] < forward[0] - 0.025  # the robot's right (its overhead camera's right): -x
    # frame "view": as the 3D view sees it; its default camera looks at the robots from the front (+y)
    client.post(f"{API}/jog", json={"side": "left", "move": [1, 0, 0], "step": 0.03, "frame": "view"})
    assert settled(client, "left")[1] > right[1] + 0.025


def test_gripper_closes_and_opens(client):
    client.post(f"{API}/gripper", json={"side": "left", "action": "close"})
    wait_for(lambda: client.get(f"{API}/state").json()["arms"]["left"]["gripper"] < 0.05)
    client.post(f"{API}/gripper", json={"side": "left", "action": "toggle"})
    wait_for(lambda: client.get(f"{API}/state").json()["arms"]["left"]["gripper"] > 0.95)


def test_refused_during_a_run_and_reset_starts_fresh(client):
    assert client.post("/api/run", json={"task": "put apple into the bowl", "offline": True}).status_code == 200
    wait_for(lambda: client.app_ref.state.sim.current is not None)
    response = client.post(f"{API}/jog", json={"side": "left", "move": [1, 0, 0], "step": 0.01})
    assert response.status_code == 409
    client.post("/api/stop")
    wait_for(lambda: not client.app_ref.state.sim.busy)
    client.post("/api/reset")
    home = settled(client, "left")
    assert np.allclose(home, [0.305, -0.005, 0.936], atol=0.005)
    client.post(f"{API}/jog", json={"side": "left", "move": [0, 0, 1], "step": 0.02})
    assert abs(settled(client, "left")[2] - (home[2] + 0.02)) < 0.005


def test_invalid_hold_targets_are_rejected(client):
    worker = client.app_ref.state.sim
    future = worker.call(lambda env: {"left": [0.0] * 3}, hold=True)
    with pytest.raises(ValueError):
        future.result(timeout=5)
    future = worker.call(lambda env: {"left": [0.0] * 6 + [2.0]}, hold=True)
    with pytest.raises(ValueError):
        future.result(timeout=5)
    t0 = client.get("/api/state").json()["sim"]["time"]
    wait_for(lambda: client.get("/api/state").json()["sim"]["time"] > t0 + 0.5)  # the sim keeps running
