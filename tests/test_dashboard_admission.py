from concurrent.futures import ThreadPoolExecutor
from threading import RLock
from types import SimpleNamespace

from fastapi.testclient import TestClient

from dashboard import app


def test_dashboard_admission_under_repeated_and_concurrent_requests(monkeypatch):
    def attach_campaign_lock(worker, bus):
        worker.campaign_recovery = SimpleNamespace(lock=RLock(), active=None)
        return []

    monkeypatch.setattr(app, "load_extensions", attach_campaign_lock)
    dashboard = app.create_app()
    worker = dashboard.state.sim
    client = TestClient(dashboard)
    body = {"task": "put apple on plate", "offline": True}
    assert client.post("/api/run", json=body).status_code == 503
    worker.ready.set()
    for invalid in ({"task": "  "}, {"task": "x" * 301}, {"seconds": 0}, {"seconds": 3601}, {"model": "  "}):
        assert client.post("/api/run", json=body | invalid).status_code == 422
    with ThreadPoolExecutor(8) as pool:
        responses = list(pool.map(lambda _: client.post("/api/run", json=body).status_code, range(16)))
    assert responses.count(200) == 1
    assert responses.count(409) == 15
    _, _, future = worker.jobs.get_nowait()
    assert client.post("/api/run", json=body).status_code == 409
    future.set_result(None)
    for _ in range(100):
        assert client.post("/api/run", json=body).status_code == 200
        _, _, future = worker.jobs.get_nowait()
        future.set_result(None)
    assert not worker.busy and worker.jobs.empty()
    client.post("/api/run", json=body)
    assert client.post("/api/stop").json()["dropped"] == 1
    assert client.post("/api/stop").json()["dropped"] == 0
    worker.campaign_recovery.active = "campaign"
    for endpoint, payload in (("run", body), ("stop", {}), ("home", {}), ("reset", {})):
        assert client.post(f"/api/{endpoint}", json=payload).status_code == 409
    worker.campaign_recovery.active = None
    assert client.post("/api/reset").status_code == 200
    assert client.post("/api/run", json=body).status_code == 409
    _, reset, future, _ = worker.jobs.get_nowait()
    class Scene:
        def reset(self):
            self.reset_occurred = True
    scene = Scene()
    reset(scene)
    future.set_result(None)
    assert scene.reset_occurred
    assert client.post("/api/run", json=body).status_code == 200
