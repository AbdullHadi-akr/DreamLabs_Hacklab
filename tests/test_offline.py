"""Offline tests: no API key, no network calls."""

import numpy as np
import pytest

from dreamtool import Hooks, VideoRecorder, run_scripted, scene, sim


@pytest.fixture
def env():
    e = sim.YamEnv()
    yield e
    e.close()


def test_env_steps_and_renders(env):
    state = env.step(sim.HOME, sim.HOME)
    assert set(state) == {"left", "right"} and state["left"].shape == (7,)
    images = env.images()
    assert set(images) == {"top", "left", "right"}
    assert images["top"].shape == (360, 640, 3)


def test_success_check_parses_tasks():
    assert scene.success_check("put apple into the bowl") is not None
    assert scene.success_check("Put the banana on the plate") is not None
    assert scene.success_check("put bottle in the bowl") is not None
    assert scene.success_check("wave hello") is None


def test_success_check_detects_object_in_bowl(env):
    check = scene.success_check("put apple into the bowl")
    assert not check(env)
    # "teleport" the apple: freejoint qpos = (x, y, z, qw, qx, qy, qz)
    bowl = scene.position(env, "bowl")
    env.data.joint("apple_free").qpos[:3] = bowl + np.array([0, 0, 0.04])
    env.data.joint("apple_free").qvel[:] = 0
    for _ in range(20):
        env.step(sim.HOME, sim.HOME)
    assert check(env)


def test_observation_builds_without_api(env):
    from collections import deque

    windows = {name: deque(maxlen=sim.FRAMES) for name in sim.VIDEO_ROLES}
    steps = 0
    while any(len(w) < sim.FRAMES for w in windows.values()):
        env.step(sim.HOME, sim.HOME)
        sim.capture(env, windows, keep=steps % sim.FRAME_EVERY_STEPS == 0)
        steps += 1
    obs = sim.observation(env, windows, "put apple into the bowl", sim.BETA_MODEL)
    assert obs["prompt"] == "put apple into the bowl"
    assert len(obs["video.overhead"]) == sim.FRAMES


def test_hooks_and_recorder(env, tmp_path):
    seen = []

    class Count(Hooks):
        def on_step(self, env, step, images):
            seen.append(step)

    path = tmp_path / "clip.mp4"
    with VideoRecorder(path) as rec:

        class Rec(Hooks):
            def on_step(self, env, step, images):
                rec.add(images)

        run_scripted(env, sim.home_path(env.state(), seconds=0.5), hooks=[Count(), Rec()])
    assert seen == list(range(1, 11))
    assert path.stat().st_size > 0
