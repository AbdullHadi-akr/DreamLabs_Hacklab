"""Same scene, same strategy, paused latency, three times: where do the runs part?

python determinism.py <out.json> [repeats] [steps]
Per request: a hash of the frames and state sent, and the first rows of the reply. The first request whose frames match
but whose reply differs is server-side nondeterminism; a request whose frames already differ points at the simulator.
"""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(r"C:/Users/abdul/Documents/Hacklab/dream-tool")))
from dreamtool import runner, sim  # noqa: E402

out, repeats, steps = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 3, int(sys.argv[3]) if len(sys.argv) > 3 else 240
TASK = "put the apple into the bowl"


class Rec(runner.Hooks):
    def __init__(self):
        self.trips, self.replies, self.start = [], [], None

    def on_start(self, env, task, model):
        self.start = hashlib.sha1(np.ascontiguousarray(env.data.qpos).tobytes()).hexdigest()[:12]

    def on_round_trip(self, trip):
        frames = hashlib.sha1(json.dumps(trip.frames, sort_keys=True).encode()).hexdigest()[:12]
        obs = trip.observation or {}
        state = {k: np.round(np.asarray(v, float), 6).tolist() for k, v in obs.items() if k.startswith("state.")}
        self.trips.append({"frames": frames, "state": hashlib.sha1(json.dumps(state, sort_keys=True).encode()).hexdigest()[:12]})

    def on_reply(self, env, reply, rtt_s):
        self.replies.append(np.asarray(reply["q_r_chunk"], float)[:, :6].round(5).tolist())


runs = []
for k in range(repeats):
    env = sim.YamEnv()
    rec = Rec()
    res = runner.run_task(TASK, env=env, strategy="chunk", latency="paused", max_steps=steps, seconds=600, hooks=[rec],
                          verbose=False, stop_on_success=True)
    runs.append({"start": rec.start, "trips": rec.trips, "replies": rec.replies, "success": res.success, "steps": res.steps})
    env.close()
    print(k, rec.start, res.success, len(rec.trips), flush=True)

report = []
for i in range(min(len(r["trips"]) for r in runs)):
    f = [r["trips"][i]["frames"] for r in runs]
    s = [r["trips"][i]["state"] for r in runs]
    rep = [np.asarray(r["replies"][i]) for r in runs] if all(len(r["replies"]) > i for r in runs) else None
    diff = None if rep is None else float(max(np.abs(a - rep[0]).max() for a in rep))
    report.append({"request": i, "frames_equal": len(set(f)) == 1, "state_equal": len(set(s)) == 1, "reply_max_diff_rad": diff})
    print(report[-1])
Path(out).write_text(json.dumps({"starts": [r["start"] for r in runs], "report": report,
                                 "success": [r["success"] for r in runs]}, indent=1))
