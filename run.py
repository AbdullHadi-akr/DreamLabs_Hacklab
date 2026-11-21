"""Run a task with Dream-1 in the simulator.

    python run.py "put apple into the bowl"                 # with 3D viewer
    python run.py "put banana on the plate" --headless --record out/banana.mp4
    python run.py --offline --record out/offline.mp4        # no API: the arms follow a script
"""

import argparse

import numpy as np

from dreamtool import Hooks, VideoRecorder, run_scripted, run_task, scene, sim


class PrintProgress(Hooks):
    """Example hook: prints the target object's position every 2 s. Replace/extend it with your tool."""

    def __init__(self, watch="apple"):
        self.watch = watch

    def on_step(self, env, step, images):
        if step % 40 == 0:
            x, y, z = scene.position(env, self.watch)
            print(f"  [{step:5d}] {self.watch}: x={x:+.3f} y={y:+.3f} z={z:.3f}")

    def on_end(self, env, result):
        rtt = f"{result.mean_rtt_s:.2f}s" if result.mean_rtt_s else "-"
        print(
            f"Done: {result.stop_reason} · success={result.success} · {result.steps} steps · "
            f"{result.requests} requests · RTT {rtt} · {result.seconds:.1f}s"
        )


class RecordHook(Hooks):
    def __init__(self, path):
        self.recorder = VideoRecorder(path)

    def on_step(self, env, step, images):
        self.recorder.add(images)

    def on_end(self, env, result):
        self.recorder.close()
        print(f"Video saved: {self.recorder.path} ({self.recorder.frames} frames)")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("task", nargs="?", default="put apple into the bowl")
    parser.add_argument("--model", type=sim.resolve_model, default=sim.BETA_MODEL)
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--actions", type=int, default=48, help="rows to execute per reply (1-48)")
    parser.add_argument("--headless", action="store_true", help="without the 3D viewer")
    parser.add_argument("--record", help="MP4 file for the three camera images")
    parser.add_argument("--offline", action="store_true", help="no API call: the arms perform a test motion")
    args = parser.parse_args()

    watch = next((o for o in scene.OBJECTS if o.split("_")[0] in args.task.lower()), "apple")
    hooks = [PrintProgress(watch)]
    if args.record:
        hooks.append(RecordHook(args.record))

    if args.offline:
        env = sim.YamEnv()
        wave = [np.r_[0.0, 0.6 * np.sin(t / 15), 0.5, 0.0, 0.0, 0.0, 0.5 + 0.5 * np.cos(t / 10)] for t in range(120)]
        targets = [(row, row) for row in wave] + sim.home_path(env.state())
        run_scripted(env, targets, hooks=hooks)
        for h in hooks:
            if isinstance(h, RecordHook):
                h.on_end(env, None)
        print("Offline run OK:", {k: np.round(v, 3).tolist() for k, v in scene.positions(env).items()})
        env.close()
        return

    run_task(
        args.task,
        model=args.model,
        seconds=args.seconds,
        actions_per_reply=args.actions,
        viewer=not args.headless,
        hooks=hooks,
    )


if __name__ == "__main__":
    main()
