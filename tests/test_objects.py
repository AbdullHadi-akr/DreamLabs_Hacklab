"""Objects extension without the API: drag, lift, drop, turn and container moves in the real sim, through HTTP."""

import time
import warnings

import numpy as np
import pytest

warnings.filterwarnings("ignore", category=DeprecationWarning)
from fastapi.testclient import TestClient  # noqa: E402

from dashboard.app import create_app  # noqa: E402
from dashboard.extension import describe  # noqa: E402
from dashboard.extensions.teleop.kinematics import project  # noqa: E402
from dreamtool import scene  # noqa: E402

API = "/api/ext/objects"


def wait_for(condition, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        value = condition()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError("condition not reached in time")


@pytest.fixture(scope="module")
def client():
    app = create_app()
    with TestClient(app) as c:
        c.app_ref = app
        c.ext = next(e for e in app.state.extensions if e.id == "objects")
        wait_for(lambda: c.get(f"{API}/state").json()["items"])
        yield c


@pytest.fixture(autouse=True)
def fresh_layout(client):
    client.post("/api/reset")
    wait_for(lambda: not client.app_ref.state.sim.busy)
    time.sleep(0.6)  # objects settle
    yield
    client.post(f"{API}/release")


def pos(client, name):
    return np.array(client.get(f"{API}/state").json()["items"][name]["pos"])


def drag(client, name, path, mode="horizontal"):
    """Press on the object's image position, move along world points, keep holding."""
    view = client.ext.view
    u, v = project(view, pos(client, name))
    assert client.post(f"{API}/drag", json={"name": name, "u": u, "v": v, "mode": mode, "start": True}).status_code == 200
    for point in path:
        u, v = project(view, point)
        assert client.post(f"{API}/drag", json={"name": name, "u": u, "v": v, "mode": mode}).status_code == 200
        time.sleep(0.03)
    time.sleep(0.4)


def test_has_a_panel(client):
    """The mouse handling lives in panel.js: without it the tab only shows its description."""
    info = describe(client.ext)
    assert info["has_panel"] and info["has_css"]


def test_drag_slides_the_object_and_release_drops_it(client):
    start = pos(client, "apple")
    goal = start + [-0.08, -0.04, 0.0]
    drag(client, "apple", [start + (goal - start) * s for s in np.linspace(0.2, 1, 5)])
    assert client.get(f"{API}/state").json()["held"] == "apple"
    held = pos(client, "apple")
    assert np.linalg.norm(held[:2] - goal[:2]) < 0.01
    assert held[2] >= start[2] - 0.005  # never pushed into the table
    client.post(f"{API}/release")
    time.sleep(1.5)
    state = client.get(f"{API}/state").json()
    assert state["held"] is None
    dropped = pos(client, "apple")
    assert np.linalg.norm(dropped[:2] - goal[:2]) < 0.03 and abs(dropped[2] - start[2]) < 0.02


def test_shift_drag_lifts_without_sliding(client):
    start = pos(client, "orange")
    drag(client, "orange", [start + [0, 0, 0.05], start + [0, 0, 0.1]], mode="vertical")
    lifted = pos(client, "orange")
    assert lifted[2] - start[2] > 0.08 and np.linalg.norm(lifted[:2] - start[:2]) < 0.005
    client.post(f"{API}/release")
    time.sleep(1.5)
    assert abs(pos(client, "orange")[2] - start[2]) < 0.02  # fell back onto the table


def test_turn_about_the_vertical_axis(client):
    before = client.get(f"{API}/state").json()["items"]["banana"]["yaw"]
    assert client.post(f"{API}/turn", json={"name": "banana", "degrees": 30}).status_code == 200
    time.sleep(0.4)
    after = client.get(f"{API}/state").json()["items"]["banana"]["yaw"]
    assert abs((after - before + 180) % 360 - 180 - 30) < 2
    assert client.post(f"{API}/turn", json={"name": "bowl", "degrees": 30}).status_code == 400


def test_container_takes_its_contents_along_and_reset_layout_restores(client):
    app = client.app_ref
    app.state.sim.call(lambda env: scene.place(env, "apple", "plate")).result(timeout=5)
    time.sleep(1.5)
    plate, apple = pos(client, "plate"), pos(client, "apple")
    drag(client, "plate", [plate + [0, -0.05, 0], plate + [0, -0.1, 0]])
    client.post(f"{API}/release")
    time.sleep(0.8)
    moved = pos(client, "plate") - plate
    assert np.linalg.norm(moved[:2] - [0, -0.1]) < 0.01 and abs(moved[2]) < 1e-4
    assert np.linalg.norm((pos(client, "apple") - apple)[:2] - moved[:2]) < 0.02
    assert app.state.sim.call(lambda env: scene.is_in(env, "apple", "plate")).result(timeout=5)

    assert client.post(f"{API}/reset").status_code == 200
    wait_for(lambda: np.allclose(pos(client, "plate"), plate, atol=1e-4))  # positions arrive with the next frame


def test_refused_during_a_run(client):
    app = client.app_ref
    hold = app.state.sim.hold
    run = app.state.sim.run_task("hold still", offline=True, targets=[(hold["left"], hold["right"])] * 10)
    wait_for(lambda: app.state.sim.busy)
    u, v = client.get(f"{API}/state").json()["items"]["apple"]["screen"]
    assert client.post(f"{API}/drag", json={"name": "apple", "u": u, "v": v, "start": True}).status_code == 409
    assert client.post(f"{API}/reset").status_code == 409
    run.result(timeout=60)


def test_grabbing_does_not_make_anything_jump(client):
    """Bounds come from the meshes' vertices: a turned mesh's box would lift the apple ~2 cm when grabbed."""
    for name in ("apple", "banana", "bowl", "plate"):
        start = pos(client, name)
        drag(client, name, [start])
        assert 0 <= pos(client, name)[2] - start[2] < 0.004, name
        client.post(f"{API}/release")
        time.sleep(0.5)


def test_lift_the_bowl_with_its_contents_and_put_it_back_down(client):
    app = client.app_ref
    app.state.sim.call(lambda env: scene.place(env, "orange", "bowl")).result(timeout=5)
    time.sleep(1.5)
    bowl, orange = pos(client, "bowl"), pos(client, "orange")
    drag(client, "bowl", [bowl + [0, 0, 0.05], bowl + [0, 0, 0.12]], mode="vertical")
    lifted = pos(client, "bowl")
    assert abs(lifted[2] - bowl[2] - 0.12) < 0.01 and np.linalg.norm(lifted[:2] - bowl[:2]) < 0.002
    assert abs(pos(client, "orange")[2] - orange[2] - 0.12) < 0.02  # came up with it
    client.post(f"{API}/release")
    wait_for(lambda: abs(pos(client, "bowl")[2] - bowl[2]) < 1e-4)  # exactly where it stood
    time.sleep(1.0)
    assert app.state.sim.call(lambda env: scene.is_in(env, "orange", "bowl")).result(timeout=5)


def test_bowl_onto_the_plate_rides_along_with_it(client):
    bowl, plate = pos(client, "bowl"), pos(client, "plate")
    target = np.array([plate[0], plate[1], bowl[2]])
    drag(client, "bowl", [bowl + (target - bowl) * s for s in np.linspace(0.2, 1, 6)])
    client.post(f"{API}/release")
    time.sleep(0.6)
    on_plate = pos(client, "bowl")
    assert np.linalg.norm(on_plate[:2] - plate[:2]) < 0.01
    assert on_plate[2] > bowl[2] + 0.005  # stands on the plate, not in it
    start = pos(client, "plate")
    drag(client, "plate", [start + [0.03, -0.05, 0], start + [0.06, -0.1, 0]])
    client.post(f"{API}/release")
    time.sleep(0.6)
    moved = pos(client, "plate") - start
    assert np.linalg.norm(moved[:2] - [0.06, -0.1]) < 0.01
    assert np.allclose(pos(client, "bowl") - on_plate, moved, atol=0.002)
    # dragged off the plate back to its free spot, the bowl is put down onto the table
    bowl_now = pos(client, "bowl")
    home = np.array([bowl[0], bowl[1], bowl_now[2]])
    drag(client, "bowl", [bowl_now + (home - bowl_now) * s for s in np.linspace(0.2, 1, 6)])
    assert pos(client, "bowl")[2] > bowl[2] + 0.005  # held at the plate's height ...
    client.post(f"{API}/release")
    wait_for(lambda: np.allclose(pos(client, "bowl"), bowl, atol=2e-4))  # ... then put down where it started
