"""Dashboard tests without the API: server, streams, offline run, extensions (scene, robustness dry run)."""

import threading
import time
import warnings

import pytest

warnings.filterwarnings("ignore", category=DeprecationWarning)
from fastapi.testclient import TestClient  # noqa: E402

from dashboard.app import create_app  # noqa: E402
from dreamtool import scene  # noqa: E402
from dreamtool.runner import RunResult  # noqa: E402


def wait_idle(app, timeout=60):
    end = time.time() + timeout
    while app.state.sim.busy and time.time() < end:
        time.sleep(0.1)
    assert not app.state.sim.busy


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    # results of test campaigns go to a temp folder, not into out/extensions/ next to the real runs
    import dashboard.extension

    original = dashboard.extension.DATA_DIR
    dashboard.extension.DATA_DIR = tmp_path_factory.mktemp("extensions")
    app = create_app()
    with TestClient(app) as c:
        c.app_ref = app
        yield c
    dashboard.extension.DATA_DIR = original


def test_state_and_extensions(client):
    state = client.get("/api/state").json()
    assert state["status"]["ready"] and not state["status"]["error"]
    ids = {e["id"] for e in state["extensions"]}
    assert {"scene_inspector", "robustness"} <= ids
    assert "_template" not in ids
    errors = [m for m in client.app_ref.state.bus.history if '"level": "error"' in m]
    assert not errors, errors


def test_static_files_have_js_mime(client):
    for url in ("/static/app.js", "/static/lib/api.js", "/ext/robustness/panel.js"):
        response = client.get(url)
        assert response.status_code == 200
        assert "javascript" in response.headers["content-type"]
    assert client.get("/ext/robustness/__init__.py").status_code == 404


def test_snapshot_and_camera(client):
    time.sleep(0.3)
    response = client.get("/snapshot/main.jpg")
    assert response.status_code == 200 and response.content[:2] == b"\xff\xd8"
    assert client.post("/api/camera", json={"azimuth": 10}).json()["azimuth"] == 10
    assert client.post("/api/camera", json={"reset": True}).json()["azimuth"] == 90


def test_offline_run_and_busy_lock(client):
    app = client.app_ref
    assert client.post("/api/run", json={"task": "put apple into the bowl", "offline": True}).status_code == 200
    assert client.post("/api/run", json={"task": "put apple into the bowl", "offline": True}).status_code == 409
    end = time.time() + 10
    while app.state.sim.current is None and time.time() < end:
        time.sleep(0.05)
    time.sleep(0.5)
    client.post("/api/stop")
    wait_idle(app)
    ended = [m for m in app.state.bus.history if '"run.ended"' in m]
    assert ended and '"stop_reason": "stopped"' in ended[-1]


def test_api_response_samples_do_not_carry_into_offline_run(client, monkeypatch):
    from dashboard import simulation

    release = threading.Event()
    observed = threading.Event()

    def mocked_runner(task, *, env, hooks, model, **_options):
        for latency in (.2, .4):
            for hook in hooks:
                hook.on_reply(env, {"q_l_chunk": []}, latency)
        observed.set()
        release.wait(5)
        return RunResult(task=task, model=model)

    monkeypatch.setattr(simulation.runner, "run_task", mocked_runner)
    worker = client.app_ref.state.sim
    live = worker.run_task("mocked timed task")
    try:
        assert observed.wait(5)
        assert client.get("/api/state").json()["status"]["run"]["rtts_s"] == [.2, .4]
    finally:
        release.set()
        live.result(timeout=5)

    client.post("/api/run", json={"task": "offline demo", "offline": True}).raise_for_status()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        run = client.get("/api/state").json()["status"]["run"]
        if run and run["model"] == "offline":
            assert run["requests"] == 0 and run["rtts_s"] == [] and run["last_rtt_s"] is None
            break
        time.sleep(.05)
    else:
        pytest.fail("Offline run did not enter the execution monitor")
    client.post("/api/stop")
    wait_idle(client.app_ref)


def test_stop_cancels_queued_run(client):
    app = client.app_ref
    client.post("/api/run", json={"task": "put apple into the bowl", "offline": True})
    client.post("/api/stop")
    wait_idle(app)
    assert any('"run.cancelled"' in m or '"run.ended"' in m for m in list(app.state.bus.history)[-3:])


def test_place_triggers_success_detection(client):
    app = client.app_ref
    client.post("/api/reset")
    wait_idle(app)
    assert client.post("/api/ext/scene_inspector/place", json={"object": "orange", "container": "bowl"}).json()["ok"]
    time.sleep(0.5)
    assert app.state.sim.call(lambda env: scene.is_in(env, "orange", "bowl")).result(timeout=5)


def test_robustness_dry_run_sweep(client):
    app = client.app_ref
    client.post("/api/reset")
    wait_idle(app)
    original = app.state.sim.call(lambda env: env.model.camera("top").quat.copy()).result(timeout=5)
    body = {"task": "put apple into the bowl", "perturbation": "camera_tilt", "values": [0, 5], "trials": 1,
            "seconds": 5, "dry_run": True, "record": False}
    assert client.post("/api/ext/robustness/start", json=body).status_code == 200
    end = time.time() + 60
    while client.get("/api/ext/robustness/status").json()["state"] == "running" and time.time() < end:
        time.sleep(0.2)
    status = client.get("/api/ext/robustness/status").json()
    assert status["state"] == "done" and status["done"] == 2
    after = app.state.sim.call(lambda env: env.model.camera("top").quat.copy()).result(timeout=5)
    assert (after == original).all(), "camera perturbation was not restored"


def test_robustness_adaptive_search(client):
    app = client.app_ref
    wait_idle(app)
    body = {"task": "put apple into the bowl", "mode": "adaptive", "perturbation": "target_shift", "trials": 4,
            "baseline_trials": 1, "seconds": 5, "dry_run": True, "record": False}
    assert client.post("/api/ext/robustness/start", json={**body, "perturbation": "prompt_paraphrase"}).status_code == 400
    assert client.post("/api/ext/robustness/start", json=body).status_code == 200
    end = time.time() + 120
    while client.get("/api/ext/robustness/status").json()["state"] == "running" and time.time() < end:
        time.sleep(0.2)
    status = client.get("/api/ext/robustness/status").json()
    assert status["state"] == "done" and status["done"] == 4
    assert status["rows"][0]["value"] == 0 and status["rows"][0]["search"]["why"] == "baseline"
    assert all(r["search"]["why"] == "most informative" for r in status["rows"][1:])
    assert status["analysis"]["stopped_because"] == "budget used up"
    assert client.get(f"/api/ext/robustness/download/{status['id']}/trials.csv").text.count("\n") == 5
