"""Camera check: do the camera images reach Dream-1 correctly?

Dream Labs' own tools show the frames to a person who types "yes" (python -m dream.check, DebugView); the only automatic
check is the frame rate. Here every frame Dream-1 was actually sent (DreamClient.on_round_trip: the request as it left)
is compared with the truth: in the simulation each camera can be rendered on its own at every step. Per frame that says

  which camera it really is   (a swapped or duplicated key shows up as the wrong camera)
  which way it is turned      (upside down, mirrored, red and blue swapped)
  which moment it shows       (lag behind the robot, a frozen camera, frames out of order, frame rate)
  whether it shows anything   (black / blown-out frames, a picture that matches no camera: cropped, zoomed, other source)

The truth is kept small (80 x 44 pixels per camera per step); a sent frame is matched by normalised correlation against
every camera, every recent step and every orientation. FaultyPolicy injects each of these faults on purpose, so the
check can show that it catches them (self-test).
"""

from __future__ import annotations

import base64
import threading
from collections import deque
from dataclasses import dataclass, field

import cv2
import numpy as np

from . import sim

CAMERAS = ("top", "left", "right")
LABELS = {"top": "Overhead", "left": "Left wrist", "right": "Right wrist"}
MATCH_W, MATCH_H = 80, 44
TRUTH_STEPS = 120  # 6 s of truth per camera
EXPECTED_SIZE = (320, 176)
TRANSFORMS = {
    "upright": lambda a: a,
    "upside down": lambda a: a[::-1, ::-1],
    "mirrored": lambda a: a[:, ::-1],
    "flipped vertically": lambda a: a[::-1, :],
    "red and blue swapped": lambda a: a[..., ::-1],
}
GOOD_MATCH = 0.95  # correlation of a correct frame with its truth is ~0.99
LAG_LIMIT_MS = 250  # frames are taken every 200 ms: the newest may be up to 150 ms old, more is late
TIE = 0.0015  # matches within this of the best are indistinguishable (a still scene)
FROZEN_TRUTH_CHANGE = 1.0  # grey levels (0..255, 80x44) between two 200 ms truth frames: the camera's view moved
FROZEN_SENT_CHANGE = 0.3  # ... and between two sent frames: nothing changed (JPEG noise only)


def camera_of_key(key: str) -> str | None:
    """'video.wrist_l' / 'image_window.left' -> 'left'."""
    for cam, role in sim.VIDEO_ROLES.items():
        if key in (f"video.{role}", f"image_window.{cam}"):
            return cam
    return None


def _vector(rgb: np.ndarray) -> np.ndarray:
    small = cv2.resize(rgb, (MATCH_W, MATCH_H), interpolation=cv2.INTER_AREA).astype(np.float32)
    return small


def _normalise(v: np.ndarray) -> np.ndarray:
    v = v.reshape(-1).astype(np.float32)
    v = v - v.mean()
    n = np.linalg.norm(v)
    return v / n if n > 1e-6 else v


def decode(b64: str) -> np.ndarray | None:
    try:
        data = np.frombuffer(base64.b64decode(b64), np.uint8)
        bgr = cv2.imdecode(data, cv2.IMREAD_COLOR)
        return None if bgr is None else bgr[..., ::-1]
    except Exception:
        return None


def encode(rgb: np.ndarray, quality: int = 85) -> str:
    ok, buf = cv2.imencode(".jpg", np.ascontiguousarray(rgb[..., ::-1]), [cv2.IMWRITE_JPEG_QUALITY, quality])
    return base64.b64encode(buf.tobytes()).decode("ascii")


class Truth:
    """Small renders of every camera at every control step (kept by a hook on the sim thread)."""

    def __init__(self, steps: int = TRUTH_STEPS):
        self.frames: deque = deque(maxlen=steps)  # (step, {cam: (MATCH_H, MATCH_W, 3) float32})
        self.lock = threading.Lock()

    def add(self, step: int, images: dict) -> None:
        if not images or any(c not in images for c in CAMERAS):
            return
        entry = (step, {c: _vector(images[c]) for c in CAMERAS})
        with self.lock:
            self.frames.append(entry)

    def snapshot(self) -> list:
        with self.lock:
            return list(self.frames)


@dataclass
class FrameMatch:
    """How one sent frame matched the rendered truth: which camera, orientation, step and lag."""

    index: int  # position in the window, 0 = oldest
    ok_image: bool
    camera: str | None = None  # what it really shows
    transform: str | None = None
    score: float = 0.0
    step: int | None = None  # truth step it matches best
    step_range: tuple | None = None  # all steps it matches equally well (a still scene)
    lag_ms: float | None = None
    brightness: float | None = None
    contrast: float | None = None
    size: tuple | None = None


def match_frame(rgb: np.ndarray, truth: list, latest_step: int) -> dict:
    """Best (camera, orientation, step) for one sent frame, by normalised correlation against all of the truth."""
    small = _vector(rgb)
    steps = np.array([s for s, _ in truth])
    bank = np.stack([_normalise(t[c]) for _, t in truth for c in CAMERAS])  # (steps*3, D)
    best = None
    by_transform = {}
    for name, tf in TRANSFORMS.items():
        scores = bank @ _normalise(np.ascontiguousarray(tf(small)))
        k = int(np.argmax(scores))
        by_transform[name] = float(scores[k])
        if best is None or scores[k] > best[0] + 1e-9:
            best = (float(scores[k]), name, k, scores)
    score, transform, k, scores = best
    cam = CAMERAS[k % 3]
    cam_scores = scores[CAMERAS.index(cam)::3]
    tied = np.nonzero(cam_scores >= score - TIE)[0]
    newest = int(steps[tied.max()])
    return {"camera": cam, "transform": transform, "score": round(score, 4), "step": newest,
            "step_range": (int(steps[tied.min()]), newest), "lag_ms": (latest_step - newest) * 50,
            "upright_score": round(by_transform["upright"], 4),
            "camera_scores": {c: round(float(scores[CAMERAS.index(c)::3].max()), 4) for c in CAMERAS}}


def check_trip(frames: dict, truth: list, latest_step: int, expected_count: int = sim.FRAMES) -> dict:
    """One request: per camera key, what arrived and what is wrong with it."""
    out = {"cameras": {}, "keys": sorted(frames), "latest_step": latest_step}
    keys_by_cam = {}
    for key in frames:
        cam = camera_of_key(key)
        if cam:
            keys_by_cam[cam] = key
    out["unknown_keys"] = [k for k in frames if camera_of_key(k) is None]
    newest_hashes = {}
    for cam in CAMERAS:
        key = keys_by_cam.get(cam)
        if key is None:
            out["cameras"][cam] = {"issues": [f"no frames under the {LABELS[cam].lower()} key"], "status": "fail"}
            continue
        window = frames[key]
        info = {"key": key, "count": len(window), "frames": [], "issues": []}
        images = [decode(f) for f in window]
        if len(window) != expected_count:
            info["issues"].append(f"{len(window)} frames in the window instead of {expected_count}")
        if any(im is None for im in images):
            info["issues"].append("a frame is not a readable JPEG")
        good = [im for im in images if im is not None]
        if good:
            h, w = good[-1].shape[:2]
            info["size"] = [w, h]
            if (w, h) != EXPECTED_SIZE:
                info["issues"].append(f"frames are {w}x{h}, the model reads {EXPECTED_SIZE[0]}x{EXPECTED_SIZE[1]}")
            newest_hashes[cam] = good[-1]
        # frozen? frame-to-frame change of the sent window against the truth's change over the same 200 ms steps,
        # both in grey levels at the matching size (a dark or still scene changes little on both sides)
        small = [_vector(im) for im in good]
        info["sent_changes"] = [round(float(np.abs(a - b).mean()), 2) for a, b in zip(small[:-1], small[1:])]
        if truth and len(truth) >= 2:
            span = min(len(truth), sim.FRAME_EVERY_STEPS * (len(window) - 1) + 1)
            t = [entry[1][cam] for entry in truth[-span:]][::sim.FRAME_EVERY_STEPS]
            info["truth_changes"] = [round(float(np.abs(a - b).mean()), 2) for a, b in zip(t[:-1], t[1:])]
        for i, im in enumerate(images):
            if im is None:
                info["frames"].append({"index": i, "readable": False})
                continue
            row = {"index": i, "readable": True, "brightness": round(float(im.mean()), 1),
                   "contrast": round(float(im.std()), 1)}
            if truth:
                row.update(match_frame(im, truth, latest_step))
            info["frames"].append(row)
        _judge_camera(cam, info, truth)
        out["cameras"][cam] = info
    # the same picture under two keys
    cams = list(newest_hashes)
    for i, a in enumerate(cams):
        for b in cams[i + 1:]:
            if newest_hashes[a].shape == newest_hashes[b].shape and \
                    float(np.abs(newest_hashes[a].astype(np.float32) - newest_hashes[b]).mean()) < 2.0:
                for c in (a, b):
                    out["cameras"][c]["issues"].append(f"same picture as the {LABELS[b if c == a else a].lower()} key")
                    out["cameras"][c]["status"] = "fail"
    return out


def _judge_camera(cam: str, info: dict, truth: list) -> None:
    rows = [r for r in info["frames"] if r.get("readable")]
    issues = info["issues"]
    if rows:
        last = rows[-1]
        if last["contrast"] < 4:
            issues.append("blank picture (black or a single colour)")
        elif last["brightness"] > 245:
            issues.append("blown-out picture (almost white)")
    matched = [r for r in rows if "camera" in r]
    if matched and not any("blank" in i for i in issues):
        newest = matched[-1]
        info["shows"] = newest["camera"]
        info["score"] = newest["score"]
        info["transform"] = newest["transform"]
        info["lag_ms"] = newest["lag_ms"] if newest["score"] >= GOOD_MATCH else None  # no lag without a sure match
        if newest["score"] < GOOD_MATCH:
            issues.append(f"picture matches no camera well (best {newest['score']:.2f}): cropped, zoomed, distorted "
                          "or another source")
        else:
            if newest["camera"] != cam:
                issues.append(f"shows the {LABELS[newest['camera']].lower()} camera")
            if newest["transform"] != "upright":
                issues.append(newest["transform"])
            if newest["lag_ms"] > LAG_LIMIT_MS:  # the newest equally good step: a still scene is never "late"
                issues.append(f"{newest['lag_ms']:.0f} ms behind the robot")
            # order and rate over the window (only where the scene moved enough to tell moments apart)
            sure = lambda r: r["score"] >= GOOD_MATCH and r["step_range"][0] == r["step_range"][1]  # noqa: E731
            steps = [r["step"] for r in matched if sure(r)]
            if len(steps) >= 3 and any(b < a for a, b in zip(steps[:-1], steps[1:])):
                issues.append("frames out of order")
            # frame rate from directly neighbouring frames whose moment is certain (still phases are ambiguous)
            gaps = [b["step"] - a["step"] for a, b in zip(matched[:-1], matched[1:])
                    if b["index"] - a["index"] == 1 and sure(a) and sure(b)]
            if len(gaps) >= 2 and np.median(gaps) > 0:
                info["fps"] = round(20 / float(np.median(gaps)), 1)
            sent, true = info.get("sent_changes", []), info.get("truth_changes", [])
            moving = sum(c > FROZEN_TRUTH_CHANGE for c in true)
            still = sum(c < FROZEN_SENT_CHANGE for c in sent)
            if moving >= 3 and len(sent) >= 4 and still >= len(sent) - 1:
                issues.append("frozen: the frames repeat while the robot moves")
    info["status"] = "fail" if issues else ("ok" if matched else "unchecked")


def summarise(trips: list[dict]) -> dict:
    """A run: per camera, how often each issue appeared, typical lag and match."""
    out = {}
    for cam in CAMERAS:
        rows = [t["cameras"][cam] for t in trips if cam in t["cameras"]]
        checked = [r for r in rows if r.get("status") in ("ok", "fail")]
        counts = {}
        for r in checked:
            for issue in r.get("issues", []):
                key = issue.split(" (")[0]
                key = "behind the robot" if "behind the robot" in key else key
                counts[key] = counts.get(key, 0) + 1
        lags = [r["lag_ms"] for r in checked if r.get("lag_ms") is not None]
        scores = [r["score"] for r in checked if r.get("score") is not None]
        fps = [r["fps"] for r in checked if r.get("fps")]
        failing = {k: v for k, v in counts.items() if v >= max(1, len(checked) // 2)}
        out[cam] = {"requests": len(rows), "checked": len(checked), "issues": counts,
                    "status": "unchecked" if not checked else ("fail" if failing else ("warn" if counts else "ok")),
                    "lag_ms_median": None if not lags else float(np.median(lags)),
                    "lag_ms_max": None if not lags else float(max(lags)),
                    "score_median": None if not scores else round(float(np.median(scores)), 4),
                    "fps_median": None if not fps else float(np.median(fps))}
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Fault injection (self-test): a proxy around the Dream-1 client that breaks the frames on purpose
# ---------------------------------------------------------------------------------------------------------------------

FAULTS = {
    "swap_wrists": "Left and right wrist cameras swapped",
    "duplicate": "Overhead picture sent under the left wrist key too",
    "upside_down": "Left wrist camera upside down",
    "bgr": "Overhead camera in BGR (red and blue swapped)",
    "frozen": "Overhead camera frozen on its first frame",
    "delay": "Overhead camera 0.6 s behind",
    "black": "Right wrist camera black",
    "zoom": "Overhead camera cropped to the centre (zoomed)",
}
EXPECTED_ISSUE = {  # what the check must report for each fault: (camera, words in an issue)
    "swap_wrists": ("left", "shows the right wrist"),
    "duplicate": ("left", "same picture as"),
    "upside_down": ("left", "upside down"),
    "bgr": ("top", "red and blue swapped"),
    "frozen": ("top", "frozen"),
    "delay": ("top", "behind the robot"),
    "black": ("right", "blank"),
    "zoom": ("top", "matches no camera"),
}


class FaultyPolicy:
    """Forwards everything to the real client; set_observation() breaks the frames first."""

    def __init__(self, inner, fault: str):
        self.inner, self.fault = inner, fault
        self.first: dict = {}
        self.history: deque = deque(maxlen=4)

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def _key(self, frames, cam):
        return next((k for k in frames if camera_of_key(k) == cam), None)

    def _map(self, frames, cam, fn):
        key = self._key(frames, cam)
        if key:
            frames[key] = fn(frames[key])

    def set_observation(self, frames, observation, *, timestamp=None):
        frames = dict(frames)
        f = self.fault
        if f == "swap_wrists":
            a, b = self._key(frames, "left"), self._key(frames, "right")
            frames[a], frames[b] = frames[b], frames[a]
        elif f == "duplicate":
            frames[self._key(frames, "left")] = frames[self._key(frames, "top")]
        elif f == "upside_down":
            self._map(frames, "left", lambda b64: encode(decode(b64)[::-1, ::-1]))
        elif f == "bgr":
            self._map(frames, "top", lambda b64: encode(decode(b64)[..., ::-1]))
        elif f == "frozen":
            key = self._key(frames, "top")
            self.first.setdefault(key, frames[key])
            frames[key] = self.first[key]
        elif f == "delay":
            key = self._key(frames, "top")
            self.history.append(frames[key])
            frames[key] = self.history[0]  # 3 ticks (0.6 s) old once the history is full
        elif f == "black":
            self._map(frames, "right", lambda b64: encode(np.zeros_like(decode(b64))))
        elif f == "zoom":
            def zoom(b64):
                im = decode(b64)
                h, w = im.shape[:2]
                crop = im[int(h * .2):int(h * .8), int(w * .2):int(w * .8)]
                return encode(cv2.resize(crop, (w, h), interpolation=cv2.INTER_LINEAR))
            self._map(frames, "top", zoom)
        return self.inner.set_observation(frames, observation, timestamp=timestamp)


def detected(fault: str, summary: dict) -> bool:
    cam, words = EXPECTED_ISSUE[fault]
    return any(words in issue for issue in summary[cam]["issues"])


# ---------------------------------------------------------------------------------------------------------------------
# The run hook: truth on the sim thread, checks on a worker thread
# ---------------------------------------------------------------------------------------------------------------------

@dataclass
class CameraWatch:
    """Watches one run. `fault`: inject it (self-test). `keep_frames`: keep the last trip's frames for the panel."""
    fault: str | None = None
    on_trip: object = None  # callback(check dict) after each request was checked
    truth: Truth = field(default_factory=Truth)
    trips: list = field(default_factory=list)
    step: int = 0
    last_frames: dict | None = None

    def __post_init__(self):
        self._queue: deque = deque()
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None

    def add_truth(self, images) -> None:
        self.step += 1
        self.truth.add(self.step, images)

    def round_trip(self, trip) -> None:
        """On the request thread: queue the frames and the truth as it is now (physics is paused meanwhile)."""
        frames = {k: list(v) for k, v in (trip.frames or {}).items()}
        self._queue.append((frames, self.truth.snapshot(), self.step,
                            None if trip.error is None else f"{type(trip.error).__name__}: {trip.error}"))
        with self._lock:
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._work, daemon=True, name="camera-check")
                self._worker.start()

    def _work(self):
        while self._queue:
            frames, truth, step, error = self._queue.popleft()
            result = check_trip(frames, truth, step)
            result["index"] = len(self.trips) + 1
            result["error"] = error
            self.trips.append(result)
            self.last_frames = frames
            if self.on_trip:
                try:
                    self.on_trip(result)
                except Exception:
                    pass

    def finish(self, timeout: float = 20.0) -> dict:
        if self._worker is not None:
            self._worker.join(timeout)
        return {"fault": self.fault, "trips": len(self.trips), "summary": summarise(self.trips)}


# ---------------------------------------------------------------------------------------------------------------------
# Does the model use them? (asks Dream-1 about a frozen moment, see xray.py)
# ---------------------------------------------------------------------------------------------------------------------

def model_uses_cameras(prober, kin, repeats: int = 3, progress=None) -> dict:
    """Each camera blanked once, and the wrist cameras swapped once, against the unchanged moment asked `repeats` times.
    A camera counts as used when blanking it moves the planned path clearly more than Dream-1 varies by itself."""
    from . import xray

    snap = prober.snapshot
    qs = [xray.Question(snap.prompt, snap.windows, tag=("base", i)) for i in range(repeats)]
    for cam in CAMERAS:
        qs.append(xray.Question(snap.prompt, {**snap.windows, cam: xray.blank_window(snap.windows[cam])},
                                tag=("blank", cam)))
    qs.append(xray.Question(snap.prompt, {**snap.windows, "left": snap.windows["right"], "right": snap.windows["left"]},
                            tag=("swap", "wrists")))
    done = [0]

    def answered(i, q, reply):
        done[0] += 1
        if progress:
            progress({"done": done[0], "total": len(qs), "text": f"{q.tag[0]} {q.tag[1]}"})

    replies = prober.ask(qs, answered)
    intents = [None if r is None else xray.intent(kin, snap, *xray.chunk(r)) for r in replies]
    base = [it for q, it in zip(qs, intents) if q.tag[0] == "base" and it is not None]
    if not base:
        raise RuntimeError("stopped before the unchanged moment was answered")
    reference = xray.mean_intent(base)
    noise = float(np.mean([xray.plan_change_cm(b, reference) for b in base]))
    threshold = max(3 * noise, 1.0)  # at least 1 cm: below that a path change is not worth calling a reaction
    rows = {}
    for q, it in zip(qs, intents):
        if it is None or q.tag[0] == "base":
            continue
        change = xray.plan_change_cm(it, reference)
        rows[f"{q.tag[0]}:{q.tag[1]}"] = {"kind": q.tag[0], "camera": q.tag[1], "change_cm": round(change, 2),
                                          "reacts": change > threshold, "target": it["target"], "text": it["text"]}
    used = [LABELS[r["camera"]] for r in rows.values() if r["kind"] == "blank" and r["reacts"]]
    ignored = [LABELS[r["camera"]] for r in rows.values() if r["kind"] == "blank" and not r["reacts"]]
    text = (f"Dream-1 reacts to: {', '.join(used)}." if used else "Dream-1's plan does not react to any single camera.")
    if ignored:
        text += f" No clear reaction when blanking: {', '.join(ignored)}."
    swap = rows.get("swap:wrists")
    if swap:
        text += (" Swapping the wrist cameras changes the plan." if swap["reacts"]
                 else " Swapping the wrist cameras does not change the plan.")
    return {"rows": rows, "noise_cm": round(noise, 2), "threshold_cm": round(threshold, 2), "text": text,
            "base_target": base[0]["target"], "base_text": base[0]["text"], "calls": prober.calls}
