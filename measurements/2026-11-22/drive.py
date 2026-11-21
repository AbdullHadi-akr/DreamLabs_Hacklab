"""Runs robustness campaigns one after another on a dashboard instance and logs each summary.

python drive.py <port> <plan.json> <log.jsonl>
plan.json: a list of StartBody dicts (see dashboard/extensions/robustness/__init__.py).
"""
import json
import sys
import time
import urllib.error
import urllib.request

port, plan_path, log_path = sys.argv[1], sys.argv[2], sys.argv[3]
base = f"http://127.0.0.1:{port}/api/ext/robustness"


def call(method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or "null")


def log(entry):
    entry["at"] = time.strftime("%H:%M:%S")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    print(json.dumps(entry)[:300], flush=True)


for i, body in enumerate(json.load(open(plan_path, encoding="utf-8"))):
    while True:  # the simulation must be idle
        try:
            s = call("GET", "/status")
            if not s or s["state"] != "running":
                break
        except Exception:
            pass
        time.sleep(5)
    try:
        started = call("POST", "/start", body)
    except urllib.error.HTTPError as e:
        log({"plan": i, "error": e.read().decode()[:500], "body": body})
        time.sleep(10)
        continue
    cid = started["id"]
    log({"plan": i, "started": cid, "body": body})
    last = -1
    while True:
        time.sleep(15)
        try:
            s = call("GET", "/status")
        except Exception as e:
            log({"plan": i, "poll_error": str(e)})
            continue
        if s["done"] != last:
            last = s["done"]
            print(f"  {cid}: {s['done']}/{s['total']}", flush=True)
        if s["state"] != "running":
            break
    a = s["analysis"]
    log({"plan": i, "id": cid, "state": s["state"], "done": s["done"], "verdict": a["verdict"]["text"],
         "per": [{k: p.get(k) for k in ("id", "successes", "n", "progress", "requests", "joint_speed", "seam_ratio",
                                         "joint_jitter", "sim_seconds", "wall_seconds", "outcomes")}
                 for p in a.get("per_strategy", [])],
         "pairs": a.get("pairs")})
log({"finished": True})
