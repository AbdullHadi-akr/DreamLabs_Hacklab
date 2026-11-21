"""Success rules, credits, multiplayer access, one-file report, second brain."""

import time
import warnings

import mujoco
import numpy as np
import pytest

warnings.filterwarnings("ignore", category=DeprecationWarning)
from fastapi.testclient import TestClient  # noqa: E402

from dashboard import brain, credits  # noqa: E402
from dashboard.lab_db import LabDB  # noqa: E402
from dashboard.multiplayer import PlayerError, Players  # noqa: E402
from dreamtool import scene, sim  # noqa: E402

REMOTE = {"cf-connecting-ip": "203.0.113.7"}  # what Cloudflare adds to every request through the tunnel


class Bus:
    def __init__(self):
        self.events = []

    def emit(self, type, data=None, keep=True):
        self.events.append((type, data))

    def log(self, *a, **k):
        pass


# ---------------- success rules ----------------

@pytest.fixture(scope="module")
def env():
    env = sim.YamEnv()
    yield env
    env.close()


def fresh(env):
    env.reset()
    mujoco.mj_forward(env.model, env.data)


def move(env, obj, xyz=None, quat=None):
    joint = env.data.joint(scene.FREE_JOINTS[obj])
    if xyz is not None:
        joint.qpos[:3] = xyz
    if quat is not None:
        joint.qpos[3:7] = quat
    mujoco.mj_forward(env.model, env.data)


def test_every_rule_example_is_understood():
    for rule in scene.describe_rules():
        assert scene.success_check(rule["example"]) is not None, rule["example"]
    assert scene.success_check("wave hello") is None
    assert scene.success_check("lift the table") is None  # not an object of the scene
    assert scene.parse_task("put the banana on the plate") == ("banana", "plate")


def test_lift_push_next_to_stack(env):
    fresh(env)
    lift = scene.success_check("lift the apple")
    assert not lift(env)
    move(env, "apple", scene.position(env, "apple") + [0, 0, 0.1])
    assert lift(env)

    fresh(env)
    left, right = scene.success_check("push the orange left"), scene.success_check("push the orange right")
    left(env), right(env)
    move(env, "orange", scene.position(env, "orange") + [0.1, 0, 0])  # the robot's left is +x
    assert left(env) and not right(env)

    fresh(env)
    near = scene.success_check("put the apple next to the bowl")
    bowl = scene.position(env, "bowl")
    move(env, "apple", [bowl[0] + 0.10, bowl[1], 0.79])
    assert near(env)

    fresh(env)
    stack = scene.success_check("stack the orange on the apple")
    apple = scene.position(env, "apple")
    assert not stack(env)
    move(env, "orange", apple + [0, 0, 0.06])
    assert stack(env)


def test_take_out_upright_all_fruit_and_order(env):
    fresh(env)
    scene.place(env, "apple", "bowl")
    mujoco.mj_forward(env.model, env.data)
    out = scene.success_check("take the apple out of the bowl")
    assert not out(env)
    move(env, "apple", [0.3, 0.2, 0.79])
    assert out(env)

    fresh(env)
    upright = scene.success_check("stand the bottle upright")
    assert upright(env)
    move(env, "water_bottle", quat=[np.cos(np.pi / 4), np.sin(np.pi / 4), 0, 0])  # lying on its side
    assert not upright(env)

    fresh(env)
    fruit = scene.success_check("put all fruit in the bowl")
    assert not fruit(env)
    for f in scene.FRUIT:
        scene.place(env, f, "bowl")
    mujoco.mj_forward(env.model, env.data)
    assert fruit(env)

    fresh(env)
    order = scene.success_check("put the apple in the bowl, then put the orange on the plate")
    assert not order(env)
    scene.place(env, "orange", "plate")
    mujoco.mj_forward(env.model, env.data)
    assert not order(env)  # the second step alone does not count
    scene.place(env, "apple", "bowl")
    mujoco.mj_forward(env.model, env.data)
    order(env)  # first step done now
    assert order(env)


# ---------------- credits ----------------

def test_credits_estimate_confirm_limit_and_balance(tmp_path):
    db = LabDB(tmp_path / "lab.db")
    s = credits.settings(db)
    assert (s["start_balance_usd"], s["monthly_limit_usd"]) == (150.0, 100.0)
    model = sim.BETA_MODEL
    short = credits.check_run(db, model, 60)
    assert short["calls"] == 26 and not short["needs_confirm"] and short["refusal"] is None
    assert credits.check_run(db, model, 240)["needs_confirm"]
    credits.save_settings(db, monthly_limit_usd=0.01)
    assert "limit" in credits.check_run(db, model, 60)["refusal"]
    with pytest.raises(ValueError):
        credits.save_settings(db, start_balance_usd=-1)
    run = db.run_started(task="t", prompt="t", model=model, source="core", label="")
    db.run_ended(run, {"model": model, "requests": 100, "success": True, "sim_seconds": 30.0})
    summary = credits.summary(db)
    assert summary["spent_total_usd"] == pytest.approx(0.14) and summary["balance_usd"] == pytest.approx(149.86)
    assert summary["spent_today_usd"] == pytest.approx(0.14)
    assert db.query("SELECT seconds FROM runs")[0]["seconds"] == 30.0  # simulated seconds


# ---------------- multiplayer: rules ----------------

def test_access_code_and_arm_owners():
    players = Players(Bus(), code="ABCD-EFGH")
    with pytest.raises(PlayerError):
        players.join("1.1.1.1", "WRONG", "x")
    token, guest = players.join("1.1.1.1", "abcd efgh", "Sam")
    assert players.guest_client(token) == guest
    assert "Take the left arm" in players.may_move(guest, "left", "guest")
    players.claim(guest, "right", "guest")
    assert players.may_move(guest, "right", "guest") is None
    assert "belongs to Sam" in players.may_move("h-host", "right", "host")
    assert players.may_move("h-host", "left", "host") is None
    players.claim(guest, "left", "guest")  # a guest holds one arm: taking the other gives the first back
    assert players.owners == {"left": guest, "right": None}
    for _ in range(10):
        with pytest.raises(PlayerError):
            players.join("2.2.2.2", "nope", "")
    with pytest.raises(PlayerError) as locked:
        players.join("2.2.2.2", "ABCD-EFGH", "")  # even the right code waits after 10 wrong ones
    assert locked.value.status == 429


# ---------------- multiplayer and credits through the web server ----------------

@pytest.fixture(scope="module")
def client(tmp_path_factory):
    import dashboard.extension

    original = dashboard.extension.DATA_DIR
    dashboard.extension.DATA_DIR = tmp_path_factory.mktemp("extensions")
    from dashboard.app import create_app

    app = create_app()
    with TestClient(app, follow_redirects=False) as c:
        c.app_ref = app
        yield c
    dashboard.extension.DATA_DIR = original


def test_guest_needs_code_and_moves_only_own_arm(client):
    app = client.app_ref
    assert client.get("/", headers={**REMOTE, "accept": "text/html"}).status_code == 303
    assert client.post("/api/run", json={"task": "put banana on the plate"}, headers=REMOTE).status_code == 401
    assert client.post("/api/join", json={"code": "WRONG"}, headers=REMOTE).status_code == 403
    joined = client.post("/api/join", json={"code": app.state.players.code, "name": "Judge"}, headers=REMOTE)
    assert joined.status_code == 200
    # The cookie is "secure" (HTTPS only, as through Cloudflare); the test client speaks HTTP, so pass it on by hand.
    assert "secure" in joined.headers["set-cookie"].lower()
    client.cookies.set("dream_guest", joined.cookies["dream_guest"])
    assert client.post("/api/run", json={"task": "put banana on the plate", "offline": True},
                       headers=REMOTE).status_code == 403
    jog = {"side": "left", "move": [1, 0, 0], "step": 0.01}
    assert client.post("/api/ext/teleop/jog", json=jog, headers=REMOTE).status_code == 409  # no arm taken yet
    assert client.post("/api/players/claim", json={"side": "left"}, headers=REMOTE).status_code == 200
    assert client.post("/api/ext/teleop/jog", json=jog, headers=REMOTE).status_code != 409
    assert client.post("/api/ext/teleop/jog", json=jog).status_code == 409  # the host cannot move the guest's arm
    guest_view = client.get("/api/players", headers=REMOTE).json()
    assert "code" not in guest_view and guest_view["me"]["arm"] == "left"
    assert client.get("/api/players").json()["code"] == app.state.players.code
    assert client.get("/api/state", headers=REMOTE).json()["me"]["role"] == "guest"
    assert client.get("/api/state").json()["me"]["role"] == "host"
    client.post("/api/players/release", json={"side": "left"})  # the host frees it again


def test_offline_run_counts_simulated_seconds_and_credit_routes(client):
    app = client.app_ref
    assert client.get("/api/credits").json()["start_balance_usd"] == 150.0
    est = client.get("/api/credits/estimate", params={"model": sim.BETA_MODEL, "seconds": 60}).json()
    assert est["calls"] >= 1 and est["usd"] is not None
    assert client.post("/api/run", json={"task": "put apple into the bowl", "offline": True}).status_code == 200
    end = time.time() + 120
    while time.time() < end and (app.state.sim.busy or not app.state.db.query("SELECT 1 FROM runs WHERE ended_at")):
        time.sleep(0.2)
    row = app.state.db.query("SELECT * FROM runs ORDER BY id DESC LIMIT 1")[0]
    assert row["seconds"] == pytest.approx(len([None] * 120 + [None] * 40) * 0.05, abs=1.0)  # 160 steps of 50 ms
    assert row["cost_usd"] is None  # a test motion makes no Dream-1 calls


# ---------------- one-file report and second brain ----------------

def test_one_file_report_and_brain(tmp_path, monkeypatch):
    from dashboard.extensions.robustness import onefile

    result = {"id": "20261121-120000-target_shift", "mode": "sweep", "state": "done", "done": 2, "total": 2,
              "policy": "dreamlabs/dream-1-beta", "started": time.time(),
              "config": {"task": "put apple into the bowl"}, "perturbation": {"label": "Move target", "unit": "cm"},
              "cost": {"calls": 12, "usd": 0.0168},
              "analysis": {"verdict": {"text": "Breaks at 4 cm"},
                           "per_value": [{"value": 0, "n": 1, "successes": 1, "rate": 1.0, "outcomes": {"success": 1}},
                                         {"value": 4, "n": 1, "successes": 0, "rate": 0.0, "outcomes": {}}]},
              "rows": [{"index": 1, "params": {"target_shift": 0}, "outcome": "success", "success": True,
                        "seconds": 12.0, "calls": 6, "cost_usd": 0.0084, "prompt": "put apple into the bowl"}]}
    page = onefile.render(result, tmp_path)
    assert page.startswith("<!doctype html>") and "<svg" in page and "$0.0168" in page and "<video" not in page

    monkeypatch.setattr(brain, "BRAIN_DIR", tmp_path / "brain")
    path = brain.run_ended({"task": "put apple into the bowl", "model": "m", "source": "core", "prompt": "p"},
                           {"success": True, "stop_reason": "success", "requests": 3, "cost_usd": 0.0042,
                            "sim_seconds": 7.2}, 5)
    brain.run_ended({"task": "x", "offline": True}, {}, 6)  # test motions are not written
    text = path.read_text(encoding="utf-8")
    assert text.count("| put apple into the bowl |") == 1 and "0.0042" in text
    assert brain.campaign_ended(result).read_text(encoding="utf-8").count("Breaks at 4 cm") == 1
    db = LabDB(tmp_path / "lab.db")
    summary = brain.daily_summary(db, credits.summary(db)).read_text(encoding="utf-8")
    assert "Success and cost per model and task" in summary
