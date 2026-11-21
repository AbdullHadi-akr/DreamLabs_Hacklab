"""Einen Task mit Dream-1 im Simulator ausfuehren.

    python run.py "put apple into the bowl"                 # mit 3D-Viewer
    python run.py "put banana on the plate" --headless --record out/banana.mp4
    python run.py --offline --record out/offline.mp4        # ohne API: Arme fahren ein Skript ab
"""

import argparse

import numpy as np

from dreamtool import Hooks, VideoRecorder, run_scripted, run_task, scene, sim


class PrintProgress(Hooks):
    """Beispiel-Hook: zeigt alle 2 s die Position des Ziel-Objekts. Ersetze/erweitere das mit deinem Tool."""

    def __init__(self, watch="apple"):
        self.watch = watch

    def on_step(self, env, step, images):
        if step % 40 == 0:
            x, y, z = scene.position(env, self.watch)
            print(f"  [{step:5d}] {self.watch}: x={x:+.3f} y={y:+.3f} z={z:.3f}")

    def on_end(self, env, result):
        rtt = f"{result.mean_rtt_s:.2f}s" if result.mean_rtt_s else "-"
        print(
            f"Fertig: {result.stop_reason} · Erfolg={result.success} · {result.steps} Schritte · "
            f"{result.requests} Requests · RTT {rtt} · {result.seconds:.1f}s"
        )


class RecordHook(Hooks):
    def __init__(self, path):
        self.recorder = VideoRecorder(path)

    def on_step(self, env, step, images):
        self.recorder.add(images)

    def on_end(self, env, result):
        self.recorder.close()
        print(f"Video gespeichert: {self.recorder.path} ({self.recorder.frames} Frames)")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("task", nargs="?", default="put apple into the bowl")
    parser.add_argument("--model", type=sim.resolve_model, default=sim.BETA_MODEL)
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--actions", type=int, default=48, help="Zeilen pro Antwort ausfuehren (1-48)")
    parser.add_argument("--headless", action="store_true", help="ohne 3D-Viewer")
    parser.add_argument("--record", help="MP4-Datei fuer die drei Kamerabilder")
    parser.add_argument("--offline", action="store_true", help="kein API-Call: Arme fahren eine Testbewegung")
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
        print("Offline-Lauf OK:", {k: np.round(v, 3).tolist() for k, v in scene.positions(env).items()})
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
