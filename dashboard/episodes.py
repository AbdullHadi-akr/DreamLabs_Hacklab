"""Episodes for the teaching loop: Dream-1 tries a task, a person takes over if it fails, the whole try is recorded.

    run starts ──> recording (Dream-1 moves the arms)
        │ success ──────────────────────────────> saved
        │ fails, or a person presses Take over ─> takeover (a person moves the arms by remote control)
        │                                            └─ Save ─> saved (success check marks it) / Discard
        └ fails and nobody takes over ──────────> paused ─ Take over / Save / Discard

Each episode is written as its own LeRobot v2.1 dataset folder in out/episodes/ep-<id>/, in the layout Dream Labs
checks before a fine-tune (one session folder per episode; see dreamlabs/shared/datasets/validation.py). The cameras
are recorded at their own size, 640 x 360, as H.264 video; the arm values right arm first, as the YAM body is laid out.

The recorder lives on the sim thread: it sees every physics step (note_action, on_step). The HTTP side only sets flags
(take_over) or queues sim jobs (save, discard).
"""

from __future__ import annotations

import json
import re
import shutil
import threading
import time
from pathlib import Path

import av
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from dreamtool import scene

OUT_DIR = Path(__file__).resolve().parents[1] / "out"
EPISODES_DIR = OUT_DIR / "episodes"
EXPORTS_DIR = OUT_DIR / "exports"

FPS = 10  # frames per second in the dataset (Dream Labs takes 30, 15, 10 or 5)
STEP_HZ = 20  # physics steps per second (50 ms each)
STEPS_PER_FRAME = STEP_HZ // FPS
## Dream Labs' shortest episode: one training sample, 48 frames at 30 fps and the frame after them (1.6 s), which is
## 17 frames at 10 fps (dreamlabs/shared/datasets/validation.py min_episode_frames(); the fine-tuning tutorial's table).
MIN_FRAMES = 48 * FPS // 30 + 1
MAX_SECONDS = 600  # an episode left in takeover is saved after 10 simulated minutes
CAMERA_ROLES = {"top": "overhead", "left": "wrist_l", "right": "wrist_r"}  # simulator camera -> Dream Labs role
VIDEO_KEYS = {role: f"observation.images.{role}" for role in CAMERA_ROLES.values()}
JOINTS = [f"{side}_{part}" for side in ("right", "left") for part in (*(f"joint{i}" for i in range(1, 7)), "gripper")]

## The YAM body as Dream Labs describes it (dreamlabs/shared/datasets/embodiments.py): right arm first.
YAM_CONFIG = {
    "state": {"right_arm": [0, 6], "right_gripper": [6, 7], "left_arm": [7, 13], "left_gripper": [13, 14]},
    "action": {"right_arm": [0, 6], "right_gripper": [6, 7], "left_arm": [7, 13], "left_gripper": [13, 14]},
    "video": VIDEO_KEYS,
    "head_camera": "overhead",
}


def _vector(left, right) -> np.ndarray:
    """14 values, right arm first: right joints 1-6, right gripper, left joints 1-6, left gripper."""
    return np.r_[np.asarray(right, float)[:7], np.asarray(left, float)[:7]].astype(np.float32)


class EpisodeWriter:
    """Writes one episode as a LeRobot v2.1 dataset folder. Videos are encoded while recording (memory stays small);
    the table of arm values is written at the end."""

    def __init__(self, folder: Path, task: str, fps: int = FPS):
        self.folder, self.task, self.fps = Path(folder), task, fps
        self.states: list[np.ndarray] = []
        self.actions: list[np.ndarray | None] = []
        self._video: dict[str, tuple] = {}  # role -> (container, stream)
        self.size: tuple[int, int] | None = None

    @property
    def frames(self) -> int:
        return len(self.states)

    def add(self, state: np.ndarray, images: dict) -> None:
        """One frame: the arm values and the three camera pictures at this moment. Its action arrives later."""
        for camera, role in CAMERA_ROLES.items():
            self._encode(role, images[camera])
        self.states.append(state)
        self.actions.append(None)

    def set_action(self, action: np.ndarray) -> None:
        """The target the arms were sent right after the last frame: that frame's action."""
        if self.actions and self.actions[-1] is None:
            self.actions[-1] = action

    def _encode(self, role: str, rgb: np.ndarray) -> None:
        if role not in self._video:
            height, width = rgb.shape[:2]
            self.size = (height, width)
            path = self.folder / "videos" / "chunk-000" / VIDEO_KEYS[role] / "episode_000000.mp4"
            path.parent.mkdir(parents=True, exist_ok=True)
            container = av.open(str(path), mode="w")
            stream = container.add_stream("libx264" if "libx264" in av.codecs_available else "h264", rate=self.fps)
            stream.width, stream.height, stream.pix_fmt = width, height, "yuv420p"
            stream.options = {"g": "2", "crf": "23"}  # a key frame every 2 frames: training reads frames at random
            self._video[role] = (container, stream)
        container, stream = self._video[role]
        frame = av.VideoFrame.from_ndarray(np.ascontiguousarray(rgb), format="rgb24")
        for packet in stream.encode(frame):
            container.mux(packet)

    def _close_videos(self) -> None:
        for container, stream in self._video.values():
            for packet in stream.encode():
                container.mux(packet)
            container.close()
        self._video = {}

    def finish(self) -> int:
        """Closes the videos and writes the table and the meta files. Returns the number of frames."""
        self._close_videos()
        n = self.frames
        if n == 0:
            return 0
        actions = [a if a is not None else s for a, s in zip(self.actions, self.states)]  # last frame: hold
        table = pa.table({
            "observation.state": pa.array([s.tolist() for s in self.states], type=pa.list_(pa.float32(), 14)),
            "action": pa.array([a.tolist() for a in actions], type=pa.list_(pa.float32(), 14)),
            "timestamp": pa.array(np.arange(n, dtype=np.float32) / self.fps, type=pa.float32()),
            "frame_index": pa.array(np.arange(n), type=pa.int64()),
            "episode_index": pa.array(np.zeros(n, dtype=np.int64)),
            "index": pa.array(np.arange(n), type=pa.int64()),
            "task_index": pa.array(np.zeros(n, dtype=np.int64)),
        })
        data = self.folder / "data" / "chunk-000" / "episode_000000.parquet"
        data.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, data)

        height, width = self.size
        vector = {"dtype": "float32", "shape": [14], "names": JOINTS}
        scalar = lambda dtype: {"dtype": dtype, "shape": [1], "names": None}  # noqa: E731
        video = {"dtype": "video", "shape": [height, width, 3], "names": ["height", "width", "channels"],
                 "info": {"video.height": height, "video.width": width, "video.codec": "h264",
                          "video.pix_fmt": "yuv420p", "video.is_depth_map": False, "video.fps": self.fps,
                          "video.channels": 3, "has_audio": False}}
        info = {
            "codebase_version": "v2.1", "robot_type": "yam", "total_episodes": 1, "total_frames": n,
            "total_tasks": 1, "total_videos": len(VIDEO_KEYS), "total_chunks": 1, "chunks_size": 1000,
            "fps": self.fps, "splits": {"train": "0:1"},
            "data_path": "data/chunk-{episode_chunk:03d}/episode_{episode_index:06d}.parquet",
            "video_path": "videos/chunk-{episode_chunk:03d}/{video_key}/episode_{episode_index:06d}.mp4",
            "features": {"observation.state": vector, "action": vector,
                         **{key: video for key in VIDEO_KEYS.values()},
                         "timestamp": scalar("float32"), "frame_index": scalar("int64"),
                         "episode_index": scalar("int64"), "index": scalar("int64"), "task_index": scalar("int64")},
        }
        meta = self.folder / "meta"
        meta.mkdir(parents=True, exist_ok=True)
        (meta / "info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
        (meta / "episodes.jsonl").write_text(
            json.dumps({"episode_index": 0, "tasks": [self.task], "length": n}) + "\n", encoding="utf-8")
        (meta / "tasks.jsonl").write_text(json.dumps({"task_index": 0, "task": self.task}) + "\n", encoding="utf-8")
        return n

    def discard(self) -> None:
        self._close_videos()
        shutil.rmtree(self.folder, ignore_errors=True)


class Recorder:
    """The teaching loop's recorder. Sim thread: note_action, on_step, run_started, run_ended, save, discard.
    Any thread: take_over (sets a flag), status."""

    def __init__(self, db, bus, root: Path = EPISODES_DIR):
        self.db, self.bus, self.root = db, bus, Path(root)
        self.enabled = True  # record every Dream-1 run started from the task bar
        self.episode: dict | None = None
        self._steps = 0
        self._lock = threading.Lock()

    # ---------- state ----------

    @property
    def mode(self) -> str | None:
        return self.episode["mode"] if self.episode else None

    @property
    def recording_idle(self) -> bool:
        """Whether the sim's idle loop (between runs) must feed steps: a person is moving the arms."""
        return self.mode == "takeover"

    def frame_due(self) -> bool:
        """Whether the next on_step records a frame (the caller then renders the cameras)."""
        return self._steps % STEPS_PER_FRAME == 0

    def status(self) -> dict:
        ep = self.episode
        if ep is None:
            return {"enabled": self.enabled, "mode": None}
        w = ep["writer"]
        return {"enabled": self.enabled, "mode": ep["mode"], "id": ep["id"], "task": ep["task"],
                "frames": w.frames, "seconds": round(w.frames / FPS, 1), "dream_frames": ep["dream_frames"],
                "person_frames": ep["person_frames"], "dream_success": ep["dream_success"],
                "take_over_requested": ep["take_over_requested"]}

    def _emit(self) -> None:
        self.bus.emit("episode.state", self.status())

    # ---------- sim thread ----------

    def run_started(self, info: dict, run_id: int | None, env) -> None:
        if not self.enabled or info.get("offline") or info.get("source") != "core":
            return
        if self.episode is not None:
            self.save(env)
        episode_id = self.db.execute(
            "INSERT INTO episodes (run_id, started_at, task, model, status, fps) VALUES (?, ?, ?, ?, 'recording', ?)",
            (run_id, time.time(), info["task"], info.get("model"), FPS))
        folder = f"ep-{episode_id:06d}"
        self.episode = {"id": episode_id, "task": info["task"], "folder": folder, "mode": "dream",
                        "writer": EpisodeWriter(self.root / folder, info["task"]), "dream_frames": 0,
                        "person_frames": 0, "dream_success": None, "take_over_requested": False,
                        "check": scene.success_check(info["task"])}
        if self.episode["check"] is not None:
            self.episode["check"](env)  # stores the start state (lift, push, take out of compare with it)
        self.db.update("episodes", episode_id, folder=folder)
        self._steps = 0
        self.bus.log(f"Recording episode {episode_id}.")
        self._emit()

    def note_action(self, left, right) -> None:
        """Before every physics step: the targets the arms are sent. They are the action of the last frame."""
        if self.mode in ("dream", "takeover"):
            self.episode["writer"].set_action(_vector(left, right))

    def on_step(self, env, images: dict | None) -> None:
        """After every physics step while recording. Every second step becomes a frame (10 per second)."""
        if self.mode not in ("dream", "takeover"):
            return
        due = self.frame_due()
        self._steps += 1
        if not due or not images:
            return
        state = env.state()
        ep = self.episode
        ep["writer"].add(_vector(state["left"], state["right"]), images)
        ep["dream_frames" if ep["mode"] == "dream" else "person_frames"] += 1
        if ep["writer"].frames % FPS == 0:
            self._emit()  # once per recorded second
        if ep["writer"].frames >= MAX_SECONDS * FPS:
            self.bus.log(f"Episode {ep['id']} reached {MAX_SECONDS} s and was saved.", "warn")
            self.save(env)

    def run_ended(self, result: dict, env) -> None:
        ep = self.episode
        if ep is None or ep["mode"] != "dream":
            return
        success = result.get("success")
        ep["dream_success"] = None if success is None else int(bool(success))
        if ep["take_over_requested"]:
            ep["mode"] = "takeover"
            self.bus.log("Take over: move the arms with Control, then press Save.")
        elif success:
            self.save(env)
            return
        else:
            ep["mode"] = "paused"
        self.db.update("episodes", ep["id"], status=ep["mode"])
        self._emit()

    def save(self, env) -> dict | None:
        ep, self.episode = self.episode, None
        if ep is None:
            return None
        check = ep.get("check")
        success = None if check is None else int(bool(check(env)))
        frames = ep["writer"].finish()
        if frames == 0:
            ep["writer"].discard()
            self.db.update("episodes", ep["id"], status="discarded", ended_at=time.time(), note="no frames")
            self._emit()
            return None
        note = f"shorter than {MIN_FRAMES / FPS} s: Dream Labs will refuse it" if frames < MIN_FRAMES else None
        self.db.update("episodes", ep["id"], status="saved", ended_at=time.time(), success=success,
                       took_over=int(ep["person_frames"] > 0), dream_frames=ep["dream_frames"],
                       person_frames=ep["person_frames"], seconds=frames / FPS, dream_success=ep["dream_success"],
                       note=note)
        verdict = {1: "success", 0: "not finished", None: "no success check for this task"}[success]
        self.bus.log(f"Episode {ep['id']} saved: {frames / FPS:.1f} s, {verdict}.")
        self._emit()
        return {"id": ep["id"], "success": success, "frames": frames}

    def discard(self, env=None) -> None:
        ep, self.episode = self.episode, None
        if ep is None:
            return
        ep["writer"].discard()
        self.db.update("episodes", ep["id"], status="discarded", ended_at=time.time())
        self.bus.log(f"Episode {ep['id']} discarded.")
        self._emit()

    # ---------- any thread ----------

    def take_over(self, sim) -> str:
        """During a Dream-1 run: stop Dream-1 (the scene stays as it is) and let a person continue.
        After a failed run: continue the paused episode by remote control."""
        ep = self.episode
        if ep is None:
            raise ValueError("No episode is being recorded. Start a run with Dream-1 first.")
        if ep["mode"] == "dream":
            ep["take_over_requested"] = True
            sim.stop()  # with Dream-1: after the pending reply; run_ended then switches to takeover
            self._emit()
            return "stopping Dream-1"
        if ep["mode"] == "paused":
            ep["mode"] = "takeover"
            self._steps = 0
            self.db.update("episodes", ep["id"], status="takeover")
            self._emit()
            return "takeover"
        return ep["mode"]


# ---------- export for a fine-tune ----------

NAME_RE = re.compile(r"^[a-z0-9-]{1,64}$")


def cut_episode(source: Path, target: Path, start: int, fps: int = FPS) -> int:
    """Writes the episode folder `source` again into `target`, without its first `start` frames: the table rows, the
    three videos (decoded and encoded again, frame by frame) and the meta files. Returns the frames kept.

    Used for episodes where a person took over: training learns every frame it gets the same way, so the frames where
    Dream-1 went wrong would teach the mistake. Only the person's part, from the take-over to the end, is kept."""
    table = pq.read_table(source / "data" / "chunk-000" / "episode_000000.parquet")
    n = table.num_rows - start
    if n <= 0:
        raise ValueError(f"{source.name}: nothing after frame {start}")
    kept = table.slice(start)
    data = target / "data" / "chunk-000" / "episode_000000.parquet"
    data.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({
        "observation.state": kept.column("observation.state"),
        "action": kept.column("action"),
        "timestamp": pa.array(np.arange(n, dtype=np.float32) / fps, type=pa.float32()),
        "frame_index": pa.array(np.arange(n), type=pa.int64()),
        "episode_index": pa.array(np.zeros(n, dtype=np.int64)),
        "index": pa.array(np.arange(n), type=pa.int64()),
        "task_index": kept.column("task_index"),
    }), data)

    for key in VIDEO_KEYS.values():
        relative = Path("videos") / "chunk-000" / key / "episode_000000.mp4"
        (target / relative).parent.mkdir(parents=True, exist_ok=True)
        with av.open(str(source / relative)) as reader, av.open(str(target / relative), mode="w") as writer:
            stream = None
            for index, frame in enumerate(reader.decode(video=0)):
                if index < start:
                    continue
                if stream is None:
                    stream = writer.add_stream("libx264" if "libx264" in av.codecs_available else "h264", rate=fps)
                    stream.width, stream.height, stream.pix_fmt = frame.width, frame.height, "yuv420p"
                    stream.options = {"g": "2", "crf": "23"}  # as EpisodeWriter: a key frame every 2 frames
                picture = av.VideoFrame.from_ndarray(frame.to_ndarray(format="rgb24"), format="rgb24")
                for packet in stream.encode(picture):
                    writer.mux(packet)
            if stream is None:  # the video is shorter than the table: nothing after the take-over to keep
                raise ValueError(f"{source.name}: {key} has no frames after frame {start}")
            for packet in stream.encode():
                writer.mux(packet)

    meta = target / "meta"
    meta.mkdir(parents=True, exist_ok=True)
    info = json.loads((source / "meta" / "info.json").read_text(encoding="utf-8"))
    info["total_frames"] = n
    (meta / "info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    episode = json.loads((source / "meta" / "episodes.jsonl").read_text(encoding="utf-8").splitlines()[0])
    episode["length"] = n
    (meta / "episodes.jsonl").write_text(json.dumps(episode) + "\n", encoding="utf-8")
    shutil.copy2(source / "meta" / "tasks.jsonl", meta / "tasks.jsonl")
    return n


def export(db, task: str, name: str, *, validate: bool = True) -> dict:
    """Copies every saved, successful, long-enough episode of `task` that no earlier export used into
    out/exports/<name>/ (one session folder per episode), checks it with Dream Labs' own dataset checks, and records
    the export in the database. Nothing is uploaded and no credits are spent.

    An episode where a person took over goes in cut: only the part from the take-over to the end (cut_episode()).
    When that part is shorter than Dream Labs' shortest episode (MIN_FRAMES), the episode stays out of the export."""
    if not NAME_RE.fullmatch(name):
        raise ValueError("The name may hold lowercase letters, digits and '-', at most 64 characters.")
    target = EXPORTS_DIR / name
    if target.exists() or db.query("SELECT 1 FROM finetunes WHERE name = ?", (name,)):
        raise ValueError(f"An export named {name!r} exists already.")
    rows = db.query("SELECT id, folder, seconds, took_over, dream_frames, person_frames FROM episodes "
                    "WHERE status = 'saved' AND success = 1 AND finetune_id IS NULL AND task = ? AND seconds >= ? "
                    "ORDER BY id", (task, MIN_FRAMES / FPS))
    skipped = [r for r in rows if r["took_over"] and (r["person_frames"] or 0) < MIN_FRAMES]
    rows = [r for r in rows if r not in skipped]
    if not rows:
        short = f" ({len(skipped)} with a take-over whose part after it is shorter than {MIN_FRAMES / FPS} s)" \
            if skipped else ""
        raise ValueError(f"No unused successful episodes for {task!r}{short}.")
    target.mkdir(parents=True)
    frames, cut = 0, 0
    try:
        for row in rows:
            source = EPISODES_DIR / row["folder"]
            if row["took_over"] and row["dream_frames"]:
                frames += cut_episode(source, target / row["folder"], int(row["dream_frames"]))
                cut += 1
            else:
                shutil.copytree(source, target / row["folder"])
                frames += int(round(row["seconds"] * FPS))
        report = None
        if validate:
            from dream import datasets  # Dream Labs' own checks, the ones upload_dataset() runs; nothing is sent

            report = datasets.validate_dataset(target, YAM_CONFIG)
            if not report.ok:
                raise ValueError(f"Dream Labs' dataset check refused the export: {report.error}")
    except Exception as error:
        # a half-written folder would block this name for good ("exists already"): remove it
        shutil.rmtree(target, ignore_errors=True)
        if isinstance(error, ValueError):
            raise
        raise ValueError(f"The export failed: {type(error).__name__}: {error}") from error
    finetune_id = db.execute(
        "INSERT INTO finetunes (created_at, name, task, folder, episodes, frames, status) "
        "VALUES (?, ?, ?, ?, ?, ?, 'exported')", (time.time(), name, task, name, len(rows), frames))
    for row in rows:
        db.update("episodes", row["id"], finetune_id=finetune_id)
    notes = list(getattr(report, "notes", []) or [])
    if cut:
        notes.append(f"{cut} episode(s) with a take-over: only the part after the take-over is in the export.")
    if skipped:
        notes.append(f"{len(skipped)} episode(s) left out: the part after the take-over is shorter than "
                     f"{MIN_FRAMES / FPS} s, the shortest episode Dream Labs trains on.")
    return {"id": finetune_id, "name": name, "folder": str(target), "episodes": len(rows), "frames": frames,
            "cut": cut, "skipped": len(skipped), "notes": notes}
