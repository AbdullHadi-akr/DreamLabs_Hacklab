"""Teaching loop: Dream-1 part, take over, person part, save, the database rows, export with Dream Labs' check."""

import json

import av
import numpy as np
import pyarrow.parquet as pq
import pytest

from dashboard import episodes
from dashboard.lab_db import LabDB
from dreamtool import scene, sim

TASK = "put banana on the plate"


class Bus:
    def __init__(self):
        self.events, self.logs = [], []

    def emit(self, type, data=None, keep=True):
        self.events.append((type, data))

    def log(self, message, level="info", source="core"):
        self.logs.append(message)


def steps(env, rec, count, step=0):
    for i in range(count):
        row = np.r_[0.0, 0.3 * np.sin((step + i) / 10), 0.4, 0.0, 0.0, 0.0, 1.0]
        rec.note_action(row, row)
        due = rec.frame_due()
        env.step(row, row)
        rec.on_step(env, env.images() if due else None)


@pytest.fixture(scope="module")
def env():
    env = sim.YamEnv()
    yield env
    env.close()


def test_take_over_episode_is_recorded_marked_and_exported(env, tmp_path, monkeypatch):
    monkeypatch.setattr(episodes, "EPISODES_DIR", tmp_path / "episodes")
    monkeypatch.setattr(episodes, "EXPORTS_DIR", tmp_path / "exports")
    db, bus = LabDB(tmp_path / "lab.db"), Bus()
    rec = episodes.Recorder(db, bus, root=tmp_path / "episodes")

    run_id = db.run_started(task=TASK, prompt=TASK, model="dreamlabs/dream-1-beta", source="core", label="")
    rec.run_started({"task": TASK, "model": "dreamlabs/dream-1-beta", "offline": False, "source": "core"}, run_id, env)
    assert rec.mode == "dream"
    steps(env, rec, 40)  # Dream-1's part: 20 frames
    db.run_ended(run_id, {"model": "dreamlabs/dream-1-beta", "success": False, "requests": 3, "stop_reason": "timeout",
                          "steps": 40, "seconds": 2.0, "mean_rtt_s": 0.8})
    rec.run_ended({"success": False}, env)
    assert rec.mode == "paused"

    assert rec.take_over(sim=None) == "takeover"
    assert rec.recording_idle
    scene.place(env, "banana", "plate")  # the person finishes the task
    steps(env, rec, 40, step=40)  # the person's part: 20 frames
    saved = rec.save(env)
    assert saved["success"] == 1 and saved["frames"] == 40
    assert rec.mode is None

    row = db.query("SELECT * FROM episodes")[0]
    assert (row["status"], row["took_over"], row["dream_frames"], row["person_frames"]) == ("saved", 1, 20, 20)
    assert (row["dream_success"], row["success"], row["seconds"]) == (0, 1, 4.0)
    run = db.query("SELECT * FROM runs")[0]
    assert run["cost_usd"] == pytest.approx(3 * 0.0014) and run["success"] == 0

    summary = db.summary()
    assert summary["trainable"] == [{"task": TASK, "episodes": 1, "seconds": 4.0}]
    assert summary["takeovers"][0]["took_over"] == 1

    pytest.importorskip("dream.datasets")  # Dream Labs' own dataset check
    result = episodes.export(db, TASK, "banana-test")
    # only the person's part goes in: the 20 frames after the take-over, not Dream-1's 20 before it
    assert (result["episodes"], result["frames"], result["cut"], result["skipped"]) == (1, 20, 1, 0)
    folder = tmp_path / "exports" / "banana-test" / row["folder"]
    table = pq.read_table(folder / "data" / "chunk-000" / "episode_000000.parquet")
    assert table.num_rows == 20 and table.column("frame_index").to_pylist() == list(range(20))
    original = pq.read_table(tmp_path / "episodes" / row["folder"] / "data" / "chunk-000" / "episode_000000.parquet")
    assert table.column("action").to_pylist() == original.column("action").to_pylist()[20:]
    for key in episodes.VIDEO_KEYS.values():
        with av.open(str(folder / "videos" / "chunk-000" / key / "episode_000000.mp4")) as video:
            assert sum(1 for _ in video.decode(video=0)) == 20
    assert json.loads((folder / "meta" / "info.json").read_text())["total_frames"] == 20
    assert db.query("SELECT finetune_id FROM episodes")[0]["finetune_id"] == result["id"]
    assert db.summary()["trainable"] == []  # an exported episode is not offered twice
    with pytest.raises(ValueError):
        episodes.export(db, TASK, "banana-test-2")


def test_a_take_over_too_short_to_train_on_stays_out_of_the_export(env, tmp_path, monkeypatch):
    monkeypatch.setattr(episodes, "EPISODES_DIR", tmp_path / "episodes")
    monkeypatch.setattr(episodes, "EXPORTS_DIR", tmp_path / "exports")
    db, bus = LabDB(tmp_path / "lab.db"), Bus()
    rec = episodes.Recorder(db, bus, root=tmp_path / "episodes")
    rec.run_started({"task": TASK, "model": "m", "offline": False, "source": "core"}, None, env)
    steps(env, rec, 40)  # Dream-1: 20 frames
    rec.run_ended({"success": False}, env)
    rec.take_over(sim=None)
    scene.place(env, "banana", "plate")
    steps(env, rec, 20, step=40)  # the person: 10 frames, 1 s, shorter than Dream Labs' 1.7 s
    rec.save(env)
    assert episodes.MIN_FRAMES == 17
    with pytest.raises(ValueError, match="shorter than 1.7 s"):
        episodes.export(db, TASK, "too-short", validate=False)
    assert not (tmp_path / "exports" / "too-short").exists()


def test_discard_removes_the_folder(env, tmp_path):
    db, bus = LabDB(tmp_path / "lab.db"), Bus()
    rec = episodes.Recorder(db, bus, root=tmp_path / "episodes")
    rec.run_started({"task": TASK, "model": "m", "offline": False, "source": "core"}, None, env)
    steps(env, rec, 6)
    rec.run_ended({"success": False}, env)
    rec.discard()
    assert not any((tmp_path / "episodes").iterdir())
    assert db.query("SELECT status FROM episodes")[0]["status"] == "discarded"


def test_offline_and_extension_runs_are_not_recorded(env, tmp_path):
    db, bus = LabDB(tmp_path / "lab.db"), Bus()
    rec = episodes.Recorder(db, bus, root=tmp_path / "episodes")
    rec.run_started({"task": TASK, "model": "offline", "offline": True, "source": "core"}, None, env)
    rec.run_started({"task": TASK, "model": "m", "offline": False, "source": "robustness"}, None, env)
    assert rec.mode is None and db.query("SELECT * FROM episodes") == []
