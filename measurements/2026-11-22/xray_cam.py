"""Real Dream-1 X-Ray + camera-use test on a dashboard instance, then logs the results.

python xray_cam.py <port> <task> <log.jsonl>
1. a Dream-1 run of the task (30 s) so the X-Ray collects moments
2. freezes the moment where the plan heads for an object (or the middle one)
3. X-Ray intent (3 calls), language (5 words x 2), RISE (60 masks + 6)
4. camera "does Dream-1 use them?" (7 calls, frozen current scene)
"""
import json
import sys
import time
import urllib.request

port, task, log_path = sys.argv[1], sys.argv[2], sys.argv[3]
base = f"http://127.0.0.1:{port}"


def call(method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read() or "null")


def log(entry):
    entry["at"] = time.strftime("%H:%M:%S")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")
    print(json.dumps(entry, default=str)[:400], flush=True)


def idle():
    while call("GET", "/api/state")["status"]["running"] or call("GET", "/api/state")["status"]["queued"]:
        time.sleep(3)


old = sys.argv[5] if len(sys.argv) > 5 else None
if old:
    call("POST", "/api/ext/xray/run", {"snapshot": old, "kind": "rise", "masks": 200})
    while True:
        time.sleep(5)
        job = call("GET", "/api/ext/xray/status")["job"]
        if job["state"] != "running":
            break
    res = call("GET", f"/api/ext/xray/snapshots/{old}")["results"].get("rise", {})
    log({"step": "rise_old_snapshot", "job": job, "result": {k: v for k, v in res.items() if k not in ("heat", "mask_changes_cm")}})
idle()
call("POST", "/api/reset")
idle()
call("POST", "/api/run", {"task": task, "seconds": 120, "strategy": "crossfade-30"})
time.sleep(5)
idle()
moments = call("GET", "/api/ext/xray/status")["moments"]
log({"step": "moments", "moments": moments})
import re


def close_to_target(m):
    """The plan closes the gripper at the object or ends within 5 cm of it: a moment where the arm really reaches."""
    if not m["target"]:
        return False
    end = re.search(r"ends ([0-9.]+) cm", m["text"])
    return "closes its gripper" in m["text"] and "not at any" not in m["text"] or (end is not None and float(end.group(1)) <= 5)


pick = next((m for m in moments if close_to_target(m)), next((m for m in moments if m["target"]), None))
if pick is None:
    log({"error": "no moments"})
    sys.exit(1)
snap = call("POST", f"/api/ext/xray/moments/{pick['index']}/keep")["id"]
log({"step": "frozen", "snapshot": snap, "moment": pick})
for kind, extra in (("intent", {}), ("language", {"repeats": 2}), ("rise", {"masks": int(sys.argv[4]) if len(sys.argv) > 4 else 60})):
    call("POST", "/api/ext/xray/run", {"snapshot": snap, "kind": kind, **extra})
    while True:
        time.sleep(5)
        job = call("GET", "/api/ext/xray/status")["job"]
        if job["state"] != "running":
            break
    res = call("GET", f"/api/ext/xray/snapshots/{snap}")["results"].get(kind, {})
    slim = {k: v for k, v in res.items() if k not in ("heat", "repeats", "mask_changes_cm")}
    if kind == "intent":
        slim["intent"] = {k: res["intent"][k] for k in ("text", "target", "arm", "event", "event_s")}
        slim.pop("recorded", None)
    log({"step": kind, "job": job, "result": slim})
idle()
call("POST", "/api/ext/camera_check/model-use", {"prompt": task})
while True:
    time.sleep(5)
    mu = call("GET", "/api/ext/camera_check/status")["model_use"]
    if mu["state"] != "running":
        break
log({"step": "camera_model_use", "result": {k: v for k, v in mu.items() if k != "frames"}})
log({"finished": True})
