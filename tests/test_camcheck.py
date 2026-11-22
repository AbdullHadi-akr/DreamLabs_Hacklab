"""Camera check: a clean window passes, every injected fault is named, and the runner hands the check what was sent."""
import time
from collections import deque
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from dreamtool import camcheck as cc
from dreamtool import runner, sim


@pytest.fixture(scope="module")
def moving():
    """60 steps of both arms moving, the truth of every step, and the window a correct loop would send."""
    env = sim.YamEnv()
    truth = cc.Truth()
    window = {c: deque(maxlen=sim.FRAMES) for c in cc.CAMERAS}
    state = env.state()
    for step in range(1, 61):
        left, right = np.array(state["left"]), np.array(state["right"])
        right[0] += 0.02 * step
        left[1] -= 0.01 * step
        env.step(left, right)
        images = env.images()
        truth.add(step, images)
        if step % sim.FRAME_EVERY_STEPS == 0:
            for c in cc.CAMERAS:
                window[c].append(cc.encode(np.asarray(Image.fromarray(images[c]).resize(cc.EXPECTED_SIZE))))
    frames = {f"video.{sim.VIDEO_ROLES[c]}": list(window[c]) for c in cc.CAMERAS}
    yield frames, truth.snapshot(), 60
    env.close()


def test_correct_window_passes(moving):
    frames, truth, step = moving
    result = cc.check_trip(frames, truth, step)
    for cam in cc.CAMERAS:
        info = result["cameras"][cam]
        assert info["status"] == "ok", (cam, info["issues"])
        assert info["shows"] == cam and info["transform"] == "upright" and info["score"] > 0.99
        assert info["lag_ms"] <= cc.LAG_LIMIT_MS
    assert result["cameras"]["top"]["fps"] == 5.0


class Sink:
    def set_observation(self, frames, observation, *, timestamp=None):
        self.frames = frames


@pytest.mark.parametrize("fault", list(cc.FAULTS))
def test_every_injected_fault_is_named(moving, fault):
    frames, truth, step = moving
    sink = Sink()
    faulty = cc.FaultyPolicy(sink, fault)
    sent = {k: [] for k in frames}
    for i in range(sim.FRAMES):  # tick by tick, as the client is fed
        faulty.set_observation({k: v[i] for k, v in frames.items()}, {})
        for k, v in sink.frames.items():
            sent[k].append(v)
    summary = cc.summarise([cc.check_trip(sent, truth, step)])
    assert cc.detected(fault, summary), summary
    expected_cam = cc.EXPECTED_ISSUE[fault][0]
    assert summary[expected_cam]["status"] == "fail"


def test_still_scene_is_not_called_late():
    env = sim.YamEnv()
    truth = cc.Truth()
    hold = env.state()
    images = None
    for step in range(1, 41):
        env.step(hold["left"], hold["right"])
        images = env.images()
        truth.add(step, images)
    old = cc.encode(np.asarray(Image.fromarray(images["top"]).resize(cc.EXPECTED_SIZE)))
    frames = {f"video.{sim.VIDEO_ROLES[c]}": [cc.encode(np.asarray(Image.fromarray(images[c]).resize(cc.EXPECTED_SIZE)))] * 9
              for c in cc.CAMERAS}
    frames["video.overhead"] = [old] * 9
    result = cc.check_trip(frames, truth.snapshot(), 40)
    assert result["cameras"]["top"]["status"] == "ok", result["cameras"]["top"]["issues"]
    env.close()


def test_runner_hands_round_trips_and_wraps_the_policy(monkeypatch):
    seen, wrapped = [], []

    class Client:
        def __init__(self):
            self.fns, self.frames = [], None

        def on_round_trip(self, fn):
            self.fns.append(fn)

        def set_observation(self, frames, observation, *, timestamp=None):
            self.frames = frames

        def get_action(self):
            rows = np.zeros((48, 7))
            rows[:, 6] = 1
            for fn in self.fns:
                fn(SimpleNamespace(frames={"video.overhead": [self.frames["video.overhead"]]}, error=None))
            return {"q_l_chunk": rows, "q_r_chunk": rows}

        def close(self):
            pass

    class Watch(runner.Hooks):
        def on_round_trip(self, trip):
            seen.append(trip.frames)

        def wrap_policy(self, policy):
            wrapped.append(policy)
            return cc.FaultyPolicy(policy, "bgr")

    class Env:
        def step(self, left, right):
            pass

        def state(self):
            return {"left": np.zeros(7), "right": np.zeros(7)}

    def feed(policy, env, windows, prompt, model, steps, every=1, station=False):
        policy.set_observation({"video.overhead": cc.encode(np.full((176, 320, 3), (200, 40, 10), np.uint8))}, {})

    monkeypatch.setattr(runner, "time", SimpleNamespace(monotonic=time.monotonic, sleep=lambda s: None))
    monkeypatch.setattr(runner.sim, "FRAMES", 0)
    monkeypatch.setattr(runner.sim, "open_policy", lambda *_: Client())
    monkeypatch.setattr(runner.sim, "feed", feed)
    monkeypatch.setattr(runner.sim, "capture", lambda *a, **k: {})
    monkeypatch.setattr(runner.sim, "validate_chunk", lambda env, reply, limit, **k: (reply["q_l_chunk"], reply["q_r_chunk"]))
    runner.run_task("wave", env=Env(), api_key="test", verbose=False, hooks=[Watch()], max_steps=48)
    assert len(wrapped) == 1 and seen, "the hook saw the request"
    red_blue = cc.decode(seen[0]["video.overhead"][0]).mean(axis=(0, 1))
    assert red_blue[2] > red_blue[0], "the round trip shows the frames after the proxy changed them (BGR)"


def test_dark_slow_scene_is_not_called_frozen():
    """Measured false alarm (75 % dimmed light): little change between frames on both sides is not a frozen camera."""
    from dashboard.extensions.robustness.perturbations import light_dim

    env = sim.YamEnv()
    light_dim(env, 75, None, None)
    truth = cc.Truth()
    window = {c: deque(maxlen=sim.FRAMES) for c in cc.CAMERAS}
    state = env.state()
    for step in range(1, 61):
        right = np.array(state["right"])
        right[0] += 0.002 * step  # slow
        env.step(state["left"], right)
        images = env.images()
        truth.add(step, images)
        if step % sim.FRAME_EVERY_STEPS == 0:
            for c in cc.CAMERAS:
                window[c].append(cc.encode(np.asarray(Image.fromarray(images[c]).resize(cc.EXPECTED_SIZE))))
    frames = {f"video.{sim.VIDEO_ROLES[c]}": list(window[c]) for c in cc.CAMERAS}
    result = cc.check_trip(frames, truth.snapshot(), 60)
    for cam in cc.CAMERAS:
        assert not any("frozen" in i for i in result["cameras"][cam]["issues"]), (cam, result["cameras"][cam])
    env.close()
