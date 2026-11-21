"""Separate SDK response timing from the main thread's rendering cadence."""
from concurrent.futures import Future
from types import SimpleNamespace

import pytest

from dreamtool import runner


@pytest.mark.parametrize(("sdk_seconds", "reason"), [(1.0, "api_timeout"), (6.0, "task_deadline")])
def test_request_timeout_between_render_polls(monkeypatch, sdk_seconds, reason):
    clock = [100.0]

    def get_action():
        clock[0] += sdk_seconds
        raise TimeoutError("request timed out")

    class DelayedPollPool:
        def __init__(self, **options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def submit(self, callback, *args):
            future = Future()
            future.set_result(callback(*args))
            # The sim thread observes the completed request after rendering.
            clock[0] += 2
            return future

    policy = SimpleNamespace(get_action=get_action, close=lambda: None)
    monkeypatch.setattr(runner, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(runner, "ThreadPoolExecutor", DelayedPollPool)
    monkeypatch.setattr(runner.sim, "FRAMES", 0)
    monkeypatch.setattr(runner.sim, "open_policy", lambda *_: policy)
    monkeypatch.setattr(runner.sim, "feed", lambda *args, **kwargs: None)

    result = runner.run_task("banana on plate", env=object(), api_key="test",
                             seconds=5, max_requests=1, verbose=False)

    assert result.stop_reason == reason
    assert result.requests == 1
    assert result.steps == 0
    assert result.rtts_s == [sdk_seconds]
    if reason == "task_deadline":
        assert result.seconds == 5
