"""Single-camera RISE and the language pull on saved X-Ray snapshots, on real Dream-1.

python xray_v2.py <port> <log.jsonl> <masks> <snapshot> [<snapshot> ...]
Per snapshot: language (2 asks per word + the original prompt), then RISE with masks on the most relied-on camera.
"""
import json
import sys
import time
import urllib.request

port, log_path, masks, snaps = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4:]
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
    print(json.dumps(entry, default=str)[:600], flush=True)


for snap in snaps:
    for kind, extra in (("language", {"repeats": 2}), ("rise", {"masks": masks, "camera": "auto"})):
        call("POST", "/api/ext/xray/run", {"snapshot": snap, "kind": kind, **extra})
        while True:
            time.sleep(5)
            job = call("GET", "/api/ext/xray/status")["job"]
            if job["state"] != "running":
                break
        res = call("GET", f"/api/ext/xray/snapshots/{snap}")["results"].get(kind, {})
        log({"snapshot": snap, "step": kind, "job": job,
             "result": {k: v for k, v in res.items() if k not in ("heat", "mask_changes_cm")}})
log({"finished": True})
