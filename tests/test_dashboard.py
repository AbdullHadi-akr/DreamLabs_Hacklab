"""Dashboard tests without the API: server, streams, offline run, extensions (scene, robustness dry run)."""

import time
import warnings

import pytest

warnings.filterwarnings("ignore", category=DeprecationWarning)
from fastapi.testclient import TestClient  # noqa: E402

from dashboard.app import create_app  # noqa: E402
from dreamtool import scene  # noqa: E402


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


def test_robustness_strategy_comparison(client):
    app = client.app_ref
    wait_idle(app)
    presets = client.get("/api/ext/robustness/strategies").json()["presets"]
    assert [p["id"] for p in presets][:3] == ["crossfade-30", "chunk", "receding-24"]
    body = {"task": "put apple into the bowl", "mode": "compare", "strategies": ["chunk", "ensemble-16"],
            "perturbation": "none", "trials": 1, "seconds": 5, "dry_run": True, "record": False}
    assert client.post("/api/ext/robustness/start", json={**body, "strategies": ["chunk"]}).status_code == 400
    assert client.post("/api/ext/robustness/start", json={**body, "strategies": ["chunk", "blend-3"]}).status_code == 400
    assert client.post("/api/ext/robustness/start", json=body).status_code == 200
    end = time.time() + 60
    while client.get("/api/ext/robustness/status").json()["state"] == "running" and time.time() < end:
        time.sleep(0.2)
    status = client.get("/api/ext/robustness/status").json()
    assert status["state"] == "done" and status["done"] == 2, [(r["stop_reason"], r.get("note")) for r in status["rows"]]
    assert [r["strategy"] for r in status["rows"]] == ["chunk", "ensemble-16"]
    assert all(r["trial"] == 1 for r in status["rows"]), "both strategies run the same pair"
    assert status["rows"][1]["requests"] > status["rows"][0]["requests"]
    assert status["rows"][1]["commands"]["seams"] > 0
    assert [p["id"] for p in status["analysis"]["per_strategy"]] == ["chunk", "ensemble-16"]
    assert status["analysis"]["pairs"][0]["n"] in (0, 1)
    csv_text = client.get(f"/api/ext/robustness/download/{status['id']}/trials.csv").text
    assert "strategy" in csv_text.splitlines()[0] and "ensemble-16" in csv_text
    state = client.get("/api/state").json()
    assert state["strategies"][0]["id"] == state["default_strategy"] == "crossfade-30"
    assert client.post("/api/run", json={"task": "x y", "strategy": "nope"}).status_code in (400, 409)


def test_xray_freeze_and_ask(client):
    app = client.app_ref
    wait_idle(app)
    xr = next(e for e in app.state.extensions if e.id == "xray")
    xr.fake = True  # scripted stand-in instead of Dream-1
    assert client.post("/api/ext/xray/run", json={"snapshot": "nope", "kind": "intent"}).status_code == 404
    r = client.post("/api/ext/xray/snapshot", json={"prompt": "put the banana on the plate"})
    assert r.status_code == 200
    snap_id = r.json()["id"]
    assert client.post("/api/ext/xray/run", json={"snapshot": snap_id, "kind": "intent"}).status_code == 200
    end = time.time() + 30
    while client.get("/api/ext/xray/status").json()["job"]["state"] == "running" and time.time() < end:
        time.sleep(0.1)
    status = client.get("/api/ext/xray/status").json()
    assert status["job"]["state"] == "done" and status["job"]["calls"] == 3
    detail = client.get(f"/api/ext/xray/snapshots/{snap_id}").json()
    assert detail["results"]["intent"]["intent"]["event"] == "close" and set(detail["frames"]) == {"top", "left", "right"}
    assert client.post("/api/ext/xray/overlay", json={"enabled": True, "snapshot": snap_id}).status_code == 200
    assert client.delete(f"/api/ext/xray/snapshots/{snap_id}").status_code == 200
    assert client.get(f"/api/ext/xray/snapshots/{snap_id}").status_code == 404


def test_camera_check_routes(client):
    app = client.app_ref
    wait_idle(app)
    status = client.get("/api/ext/camera_check/status").json()
    assert set(status["faults"]) >= {"swap_wrists", "bgr", "delay", "black"}
    assert client.post("/api/ext/camera_check/selftest", json={"faults": ["nope"]}).status_code == 400
    cam = next(e for e in app.state.extensions if e.id == "camera_check")
    cam.fake = True
    assert client.post("/api/ext/camera_check/model-use", json={"prompt": "put the banana on the plate"}).status_code == 200
    end = time.time() + 30
    while client.get("/api/ext/camera_check/status").json()["model_use"]["state"] == "running" and time.time() < end:
        time.sleep(0.1)
    mu = client.get("/api/ext/camera_check/status").json()["model_use"]
    assert mu["state"] == "done" and mu["rows"]["blank:top"]["reacts"] and not mu["rows"]["blank:left"]["reacts"]
