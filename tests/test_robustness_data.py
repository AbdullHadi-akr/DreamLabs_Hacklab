"""Stored robustness runs: CSV export, ZIP bundle, robustness map binning."""

import csv
import io
import json
import zipfile

from dashboard.extensions.robustness import data
from dashboard.extensions.robustness.perturbations import REGISTRY


def fake_result(cid, values, outcomes, dry_run=True, mode="sweep", pid="target_shift"):
    p = REGISTRY[pid]
    rows = []
    for i, (v, outcome) in enumerate(zip(values, outcomes), 1):
        rows.append({"index": i, "trial": 1, "value": v, "params": {pid: v}, "prompt": "put apple into the bowl",
                     "outcome": outcome, "success": outcome == "success",
                     "progress": 1.0 if outcome == "success" else 0.25, "metrics": {"max_lift_cm": 1.5},
                     "stop_reason": "done", "seconds": 2.5, "steps": 50, "mean_rtt_s": None, "redraws": 0,
                     "info": {pid: {"offset": "+1.0, +0.0 cm"}}, "video": None})
    return {"id": cid, "mode": mode, "state": "done", "started": 1.8e9, "done": len(rows), "total": len(rows),
            "config": {"task": "put apple into the bowl", "dry_run": dry_run, "model": "dreamlabs/dream-1-beta"},
            "perturbation": {"id": pid, "label": p.label}, "rows": rows,
            "analysis": {"verdict": {"text": "ok"}}}


def test_csv_has_one_row_per_trial_and_excel_variant():
    result = fake_result("20260101-000000-target_shift", [0, 4, 8], ["success", "success", "no_reach"])
    text = data.to_csv(data.trial_records(result))
    rows = list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))
    assert len(rows) == 3
    assert rows[2]["outcome"] == "no_reach" and rows[2]["p_target_shift"] == "8" and rows[0]["success"] == "1"
    assert rows[1]["progress"] == "1" and rows[1]["max_lift_cm"] == "1.5"
    excel = data.to_csv(data.trial_records(result), excel=True)
    assert excel.splitlines()[0].count(";") > 10 and "1,5" in excel


def test_bundle_contains_json_csv_and_videos(tmp_path):
    result = fake_result("20260101-000000-target_shift", [0], ["success"])
    (tmp_path / "trial-001.mp4").write_bytes(b"\x00" * 10)
    target = tmp_path / "out.zip"
    data.write_bundle(result, tmp_path, target)
    names = zipfile.ZipFile(target).namelist()
    assert {f"{result['id']}/{n}" for n in ("result.json", "trials.csv", "trial-001.mp4")} == set(names)
    assert json.loads(zipfile.ZipFile(target).read(f"{result['id']}/result.json"))["id"] == result["id"]


def test_strength_bins():
    shift = REGISTRY["target_shift"]  # max 8 cm
    assert [data.strength_bin(v, shift) for v in (0, 1, 2, 3, 4, 6, 8, 12)] == [0, 1, 1, 2, 2, 3, 4, 5]
    mass = REGISTRY["target_mass"]  # neutral 1, max 8
    assert data.strength_bin(1, mass) == 0 and data.strength_bin(8, mass) == 4


def test_map_pools_sweeps_and_skips_random_and_invalid():
    a = fake_result("20260101-000000-target_shift", [0, 4, 8], ["success", "success", "no_reach"])
    b = fake_result("20260102-000000-target_shift", [0, 4, 8], ["success", "no_grasp", "invalid"])
    r = fake_result("20260103-000000-random", [3], ["no_reach"], mode="random")
    m = data.robustness_map([a, b, r])
    row = next(x for x in m["rows"] if x["id"] == "target_shift")
    base, half, full = row["cells"][0], row["cells"][2], row["cells"][4]
    assert (base["n"], base["successes"]) == (2, 2)
    assert (half["n"], half["successes"]) == (2, 1)
    assert full["n"] == 1  # the invalid trial is not counted
    assert m["excluded_random"] == 1
    assert len(row["campaigns"]) == 2
    assert all(c is None for c in next(x for x in m["rows"] if x["id"] == "light_dim")["cells"])


def test_policy_filter():
    dry = fake_result("20260101-000000-target_shift", [0], ["success"])
    live = fake_result("20260102-000000-target_shift", [0], ["no_reach"], dry_run=False)
    assert [data.matches(x, None, "dry run") for x in (dry, live)] == [True, False]
    assert data.policy_key(live) == "dreamlabs/dream-1-beta · client latency"  # recorded before the latency fix
    live["config"]["latency"] = "paused"
    assert data.policy_key(live) == "dreamlabs/dream-1-beta"
