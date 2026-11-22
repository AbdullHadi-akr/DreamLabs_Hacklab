"""Test Suite run assets: telemetry from observed frames only, and asset routes that keep trials apart."""

import json
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.extensions.test_suite import TestSuite as SuiteExtension
from dashboard.extensions.test_suite.telemetry import RunTelemetry


def test_telemetry_uses_observed_frames_and_distance_samples_only():
    trace = RunTelemetry()
    contact = {"event": "Gripper contacted object", "simulation_time": 1.05}
    frame = np.zeros((2, 2, 3), dtype=np.uint8)
    trace.observe(1., .4, [], frame)
    trace.observe(1.05, .3, [contact], None)
    assert "contact" not in trace.frames
    trace.observe(1.1, .31, [contact], frame)
    trace.observe(1.3, .5, [contact], None)
    assert trace.frames["contact"][0] == 1.1
    assert trace.frames["closest"][0] == 1.1
    assert trace.frames["final"][0] == 1.1
    assert "pickup" not in trace.frames
    progress = trace.progress([contact], "task_deadline", 1.3)
    assert progress["samples"] == [(1., .4), (1.05, .3), (1.3, .5)]
    assert [(marker["event"], marker["simulation_time"]) for marker in progress["markers"]] == [
        ("Closest measured approach", 1.05), ("Run ended", 1.3),
    ]
    assert RunTelemetry().progress([], "task_deadline", 9.) is None


def test_asset_routes_isolate_trials_and_preserve_historical_snapshot(tmp_path):
    suite = SuiteExtension(SimpleNamespace(data_dir=tmp_path))
    suite.setup()
    campaign = uuid4()
    directory = suite.directory(campaign)
    directory.mkdir()
    (directory / "1.jpg").write_bytes(b"legacy-frame")
    (directory / "2.contact.jpg").write_bytes(b"second-run-frame")
    (directory / "2.progress.json").write_text(json.dumps({"samples": [[2, .3]]}), encoding="utf-8")
    historical = {
        "id": campaign.hex, "config": {"mode": "repeated", "dry_run": False},
        "state": "done", "trials": [{
            "number": 1, "stop_reason": "timeout", "requests": 2, "mean_rtt_s": .3,
            "seconds": 60, "case": {"prompt": "banana on plate", "offset": 0, "tilt": 0, "light": 1},
            "snapshot_available": True,
        }],
    }
    (directory / "report.json").write_text(json.dumps(historical), encoding="utf-8")
    app = FastAPI()
    app.include_router(suite.router())
    client = TestClient(app)
    prefix = f"/reports/{campaign.hex}"
    row = client.get(prefix).raise_for_status().json()["trials"][0]
    assert row["snapshot_available"] and row["task_success"] is None
    assert client.get(prefix + "/snapshot/1").content == b"legacy-frame"
    assert client.get(prefix + "/snapshot/2/contact").content == b"second-run-frame"
    assert client.get(prefix + "/snapshot/1/contact").status_code == 404
    assert client.get(prefix + "/progress/2").json()["samples"] == [[2, .3]]
    assert client.get(prefix + "/progress/1").status_code == 404
