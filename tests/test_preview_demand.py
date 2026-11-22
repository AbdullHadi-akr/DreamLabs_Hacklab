"""Camera previews: only the stream variants someone watches are rendered and encoded, and a single preview
matches the images Dream-1 gets."""

import time
from types import SimpleNamespace

import mujoco
import numpy as np

from dashboard.simulation import CAMERAS, CAM_SIZE, SimWorker
from dreamtool import sim


def test_preview_renders_and_encodes_only_requested_variants(monkeypatch):
    worker = SimWorker(None)
    activity = []
    rgb = np.zeros((360, 640, 3), dtype=np.uint8)
    worker.env = SimpleNamespace(model=object(), data=object())
    worker.main_cam = mujoco.MjvCamera()
    worker.main_renderer = SimpleNamespace(scene=SimpleNamespace(ngeom=0), update_scene=lambda *a, **kw: None,
                                           render=lambda: activity.append("main render") or rgb)
    monkeypatch.setattr(worker, "_store", lambda name, image, *a, **kw: activity.append((name, image.shape)))
    monkeypatch.setattr(worker, "_render_preview", lambda name: activity.append(f"render {name}") or rgb)

    def publish():
        worker._last.update(main=0, state=time.monotonic())
        worker.publish()

    publish()
    assert activity == []
    with worker.watch_frames("main-teleop"), worker.watch_frames("left"):
        publish()
    assert activity == ["main render", ("main-teleop", rgb.shape), "render left", ("left", (*CAM_SIZE[::-1], 3))]
    activity.clear()
    with worker.watch_frames("left-large"):
        worker._camera_preview_times["left"] = 0
        worker._last.update(main=0, state=time.monotonic())
        worker.publish({"left": rgb})
    assert activity == [("left-large", rgb.shape)]
    activity.clear()
    publish()
    assert activity == []

    worker._camera_preview_times = dict.fromkeys(CAMERAS, 0.0)
    with worker.watch_frames("left"), worker.watch_frames("top"), worker.watch_frames("right"):
        for i in range(3):
            publish()
            assert len(activity) == (i + 1) * 2
    assert [event for event in activity if isinstance(event, str)] == [f"render {name}" for name in CAMERAS]


def test_single_preview_matches_native_station_images():
    worker = SimWorker(None)
    worker.env = sim.YamEnv()
    try:
        reference = worker.env.images()
        for name in CAMERAS:
            preview = worker._render_preview(name)
            assert preview.shape == reference[name].shape
            # Repeated native renders can vary by one channel value on rasterized edges.
            np.testing.assert_allclose(preview, reference[name], atol=1, rtol=0)
    finally:
        worker.env.close()
