import gzip
import hashlib
import json
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient

from dashboard import app as dashboard_app, extension, lab_db
from dashboard.extensions.test_suite import checkpoint, forks
from dashboard.extensions.test_suite.evaluation import Placement
from dashboard.simulation import SimWorker
from dreamtool import sim


def eventually(fn, predicate):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        value = fn()
        if predicate(value):
            return value
        time.sleep(.025)
    pytest.fail("The simulator job did not finish")


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    folder = tmp_path_factory.mktemp("fork-here")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(extension, "DATA_DIR", folder)
        patch.setattr(dashboard_app, "LabDB", lambda: lab_db.LabDB(folder / "lab.db"))
        patch.setattr(sim, "open_policy", lambda *_: pytest.fail("Scripted demo attempted to open Dream-1"))
        patch.setattr(SimWorker, "publish", lambda *args, **kwargs: None)

        def capture(env, windows, keep=True):
            if keep:
                frame = str(env.data.time)
                for side, history in windows.items():
                    history.append(f"{side}-{frame}")
            return {}

        patch.setattr(sim, "capture", capture)
        app = dashboard_app.create_app()
        with TestClient(app) as client:
            response = client.post("/api/ext/test_suite/fork-demo")
            assert response.status_code == 200, response.text
            origin = response.json()["id"]
            report_url = f"/api/ext/test_suite/reports/{origin}"
            report = eventually(lambda: client.get(report_url).json(), lambda report: report["state"] != "running")
            assert report["trials"][0]["checkpoint"], report["trials"][0]
            assert report["trials"][0]["task_success"] is True
            directory = folder / "test_suite" / origin
            yield app, client, directory, report_url


def latest(client, url):
    return client.get(url).json()[0]


def test_demo_restores_twice_and_keeps_origin_immutable(demo):
    app, client, directory, report_url = demo
    original = (directory / "report.json").read_bytes()
    reference = json.loads(original)["trials"][0]["checkpoint"]
    saved = checkpoint.read_checkpoint(directory / "1.checkpoint.json.gz", reference)

    def verify(env):
        initial = checkpoint.capture_start(env)
        values = []
        try:
            for _ in range(2):
                restore = checkpoint.ForkExecution(Placement(("banana", "plate")), saved["task"], saved["model"],
                                                   checkpoint=saved)
                windows, steps = restore.restore_inputs(env)
                values.append((steps, checkpoint.capture_start(env),
                               checkpoint.digest(sim.observation(env, windows, saved["task"], saved["model"],
                                                                 saved["station"]))))
                for _ in range(5):
                    env.step(*saved["command"])
        finally:
            checkpoint.set_physics(env, initial)
        return values

    first, second = app.state.sim.call(verify).result(timeout=8)
    assert first == second
    assert first[2] == saved["observation"]
    url = f"{report_url}/forks/1"
    assert client.get(f"{url}/quote").json()["api_request_limit"] == 0
    assert client.post(url, json={}).status_code == 200
    pair = eventually(lambda: latest(client, url), lambda pair: pair["state"] != "running")
    assert pair["state"] == "done", pair
    baseline, guarded = (pair["branches"][key] for key in forks.BRANCHES)
    assert baseline["start_verified"] and guarded["start_verified"]
    assert baseline["outcome"] is False and baseline["target_entry"] is False
    assert guarded["outcome"] is True and guarded["stable_placement"] is True
    assert baseline["requests"] == guarded["requests"] == 0
    assert guarded["scripted_chunks"] >= 2
    assert app.state.sim.db.query("SELECT SUM(calls) AS calls, SUM(cost_usd) AS cost FROM runs")[0] == {
        "calls": 0, "cost": None,
    }
    assert guarded["guard_activations"] == guarded["replans"] == 1
    blocked, sent, returned, allowed = guarded["guard_events"]
    assert blocked["simulation_time"] == sent["simulation_time"] == returned["simulation_time"]
    assert blocked["in_target_region"] is False and allowed["in_target_region"] is True
    assert (directory / "report.json").read_bytes() == original


def test_guard_never_replans_twice_and_reports_lost_grasp():
    evaluator = SimpleNamespace(latest={"contacts": ["right_tip_left"], "in_target_region": False})
    env = SimpleNamespace(data=SimpleNamespace(time=1.0))
    execution = checkpoint.ForkExecution(evaluator, "banana on plate", sim.BETA_MODEL,
                                          checkpoint={"side": "right"}, guarded=True)
    execution.hold_opening = 0
    assert execution.request_limit(5) == 4
    opening = [0] * 6 + [1]
    assert execution.before_step(env, opening, opening) == "replan"
    assert execution.request_limit(5) == 5
    execution.boundary(env, {}, 0, None, None, False)
    execution.reply(env)
    assert execution.before_step(env, opening, opening) == "guard_repeated_early_release"
    assert execution.replans == 1
    evaluator.latest["contacts"] = []
    assert execution.before_step(env, opening, opening) == "guard_lost_grasp"


def clone_report(directory, report_url, transform=None):
    """Seed an independent historical report without rewriting the origin trial."""
    original = json.loads((directory / "report.json").read_bytes())
    copy_id = uuid4().hex
    target = directory.parent / copy_id
    target.mkdir()
    original["id"] = copy_id
    run = original["trials"][0]
    if transform is None:
        run.pop("checkpoint")
    else:
        saved = checkpoint.read_checkpoint(directory / "1.checkpoint.json.gz", run["checkpoint"])
        raw = checkpoint.encode(transform(saved))
        (target / "1.checkpoint.json.gz").write_bytes(gzip.compress(raw))
        run["checkpoint"]["sha256"] = hashlib.sha256(raw).hexdigest()
    (target / "report.json").write_text(json.dumps(original))
    return report_url.rsplit("/", 1)[0] + "/" + copy_id


def test_old_reports_and_incompatible_artifacts(demo):
    _, client, directory, url = demo
    old = clone_report(directory, url)
    assert client.get(old).status_code == 200
    assert client.post(f"{old}/forks/1", json={}).status_code == 409
    incompatible = clone_report(directory, url, lambda saved: {**saved, "schema": 0})
    assert client.post(f"{incompatible}/forks/1", json={}).status_code == 409
    missing = clone_report(directory, url, lambda saved: saved)
    artifact = directory.parent / missing.rsplit("/", 1)[-1] / "1.checkpoint.json.gz"
    artifact.write_bytes(b"partial")
    assert client.post(f"{missing}/forks/1", json={}).status_code == 409
    changed_scene = clone_report(directory, url, lambda saved: {**saved, "scene": "incompatible"})
    comparison_url = f"{changed_scene}/forks/1"
    assert client.post(comparison_url, json={}).status_code == 200
    result = eventually(lambda: latest(client, comparison_url), lambda pair: pair["state"] != "running")
    assert result["branches"]["baseline"]["status"] == "restore_failed"
    assert result["branches"]["guarded"]["status"] == "not_run"
    assert result["branches"]["baseline"]["start_verified"] is False


def test_cancel_and_reject_competing_actions(demo, monkeypatch):
    app, client, _, report = demo
    entered, release = threading.Event(), threading.Event()
    step = forks.BranchHooks.on_step

    def hold(self, env, index, images):
        entered.set()
        release.wait(8)
        step(self, env, index, images)

    monkeypatch.setattr(forks.BranchHooks, "on_step", hold)
    url = f"{report}/forks/1"
    started = client.post(url, json={}).json()
    try:
        assert entered.wait(8)
        assert client.post(url, json={}).status_code == 409
        assert client.post("/api/run", json={"task": "offline demo", "offline": True}).status_code == 409
        assert client.post("/api/ext/test_suite/fork-demo").status_code == 409
        assert client.post("/api/reset").status_code == 409
        assert client.post("/api/ext/objects/reset").status_code == 409
        assert client.post("/api/ext/teleop/gripper", json={"side": "right", "action": "open"}).status_code == 409
        assert client.post(f"/api/ext/test_suite/forks/{started['id']}/stop").status_code == 200
    finally:
        release.set()
    pair = eventually(lambda: latest(client, url), lambda pair: pair["state"] != "running")
    assert pair["state"] == "cancelled"
    assert all(branch["status"] == "cancelled" for branch in pair["branches"].values())
    eventually(lambda: app.state.sim.busy, lambda busy: not busy)
    assert client.post("/api/ext/teleop/gripper", json={"side": "right", "action": "open"}).status_code == 200


def test_live_fork_requires_confirmation_and_accounts_failed_replan(demo, monkeypatch):
    app, client, directory, report_url = demo
    run = json.loads((directory / "report.json").read_bytes())["trials"][0]
    saved = checkpoint.read_checkpoint(directory / "1.checkpoint.json.gz", run["checkpoint"])
    live = clone_report(directory, report_url, lambda saved: {**saved, "script": None, "remaining_requests": 1})
    url = f"{live}/forks/1"
    typed_open = np.array(saved["command"])
    typed_open[checkpoint.SIDES.index(saved["side"]), 6] = 1

    class FakePolicy(checkpoint.ScriptedPolicy):
        def get_action(self):
            try:
                return super().get_action()
            except StopIteration:
                raise TimeoutError("fixture replan timeout") from None

    monkeypatch.setattr(sim, "settings", lambda: {"DREAM_API_KEY": "fixture"})
    monkeypatch.setattr(sim, "open_policy", lambda *_: FakePolicy([[typed_open]]))
    quote = client.get(f"{url}/quote").json()
    assert (quote["baseline_request_limit"], quote["guarded_request_limit"]) == (1, 2)
    assert client.post(url, json={}).status_code == 409
    assert client.post(url, json={"confirmed": True}).status_code == 200
    result = eventually(lambda: latest(client, url), lambda pair: pair["state"] != "running")
    assert result["branches"]["baseline"]["requests"] == 1
    guarded = result["branches"]["guarded"]
    assert guarded["status"] == "error" and guarded["reason"] == "api_timeout"
    assert guarded["requests"] == 2 and guarded["replans"] == 1
    assert guarded["guard_events"][-1]["decision"] == "Replan failed"
    rows = app.state.sim.db.query("SELECT calls, cost_usd FROM runs WHERE label LIKE ? ORDER BY id",
                                  (f"{result['id']}%",))
    assert [row["calls"] for row in rows] == [1, 2]
    assert sum(row["cost_usd"] for row in rows) == pytest.approx(quote["max_cost_usd"])
    eventually(lambda: app.state.sim.busy, lambda busy: not busy)
