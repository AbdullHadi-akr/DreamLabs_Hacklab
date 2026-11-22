"""Model X-Ray: kinematics, intent, RISE statistics and the language probe, against a scripted stand-in for Dream-1."""
import numpy as np
import pytest

from dreamtool import scene, sim, xray, xray_fake


@pytest.fixture(scope="module")
def frozen():
    env = sim.YamEnv()
    snap = xray.capture_scene(env, "Pick up the banana and put it on the green plate", sim.BETA_MODEL)
    yield env, snap, xray.Kinematics(env.model)
    env.close()


def test_capture_scene_freezes_a_full_window(frozen):
    env, snap, _ = frozen
    assert all(len(snap.windows[c]) == sim.FRAMES for c in xray.CAMERAS)
    assert xray.decode_frame(snap.windows["top"][-1]).shape == (xray.FRAME_H, xray.FRAME_W, 3)
    assert len(snap.qpos) == env.model.nq
    again = xray.Snapshot.from_dict(snap.to_dict())
    assert again.id == snap.id and again.windows == snap.windows


def test_kinematics_does_not_touch_the_live_state(frozen):
    env, snap, kin = frozen
    before = env.data.qpos.copy()
    rows = np.tile(np.r_[np.asarray(snap.state["right"][:6]), 1.0], (48, 1))
    rows[:, 0] += np.linspace(0, 0.6, 48)
    paths = kin.tcp_paths(snap.qpos, np.tile(np.r_[np.asarray(snap.state["left"][:6]), 1.0], (48, 1)), rows)
    assert (env.data.qpos == before).all()
    assert np.linalg.norm(paths["right"][-1] - paths["right"][0]) > 0.05
    assert np.allclose(paths["left"][0], paths["left"][-1])


def test_gripper_event_and_target():
    assert xray.gripper_event(1.0, [1, 1, 0.3, 0]) == ("close", 2)
    assert xray.gripper_event(0.0, [0, 0.8, 1]) == ("open", 1)
    assert xray.gripper_event(1.0, [1, 1]) is None
    objects = {"apple": np.array([0.3, 0, 0.8]), "banana": np.array([-0.3, 0, 0.8])}
    containers = {"bowl": np.array([0, 0.2, 0.76]), "plate": np.array([0, -0.2, 0.76])}
    start, path = np.array([0, 0, 1.0]), np.array([[0.1, 0, 0.9], [0.28, 0, 0.82]])
    assert xray.pick_target(start, path, "close", path[-1], objects, containers)[:1] == ("apple",)
    assert xray.pick_target(start, path, None, None, objects, containers)[0] == "apple"  # approach without a grasp
    assert xray.pick_target(start, path, "open", np.array([0.01, -0.19, 0.9]), objects, containers)[0] == "plate"
    far = np.array([0.0, 0.0, 1.3])
    assert xray.pick_target(start, np.array([far]), "close", far, objects, containers)[0] is None


def test_intent_reads_a_grasp(frozen):
    _, snap, kin = frozen
    banana = kin.positions(snap.qpos)["banana"]
    left = np.tile(np.r_[np.asarray(snap.state["left"][:6]), 1.0], (48, 1))
    right = np.tile(np.r_[np.asarray(snap.state["right"][:6]), 1.0], (48, 1))
    right[20:, 6] = 0.0  # closes the gripper where it is: far from every object
    it = xray.intent(kin, snap, left, right)
    assert it["arm"] == "right" and it["event"] == "close" and it["event_step"] == 20 and it["target"] is None
    assert "not at any object" in it["text"]
    assert np.linalg.norm(banana) > 0


def test_swap_object_keeps_the_wording():
    assert xray.swap_object("Pick up the banana and put it on the green plate", "apple") == \
        "Pick up the apple and put it on the green plate"
    assert xray.swap_object("place the water bottle in the bowl", "blicket") == "place the blicket in the bowl"
    assert xray.swap_object("Leg die Banane auf den Teller", "apple") == "Leg die apple auf den Teller"
    assert xray.swap_object("wave", "apple") == "put the apple into the bowl"


def test_rise_importance_finds_the_region_that_matters():
    rng = np.random.default_rng(0)
    m = xray.RiseMap()
    masks, changes = [], []
    for _ in range(200):
        small = xray._small(xray.rise_mask(rng))
        change = 5.0 * (1 - small[5:15, 10:30].mean()) + rng.normal(0, 0.2)  # hiding the centre moves the plan
        m.add(small, change)
        masks.append(small)
        changes.append(change)
    imp = m.importance()
    assert imp[8:12, 15:25].mean() > 5 * abs(imp[:3, :6].mean())
    assert imp.max() > xray.chance_level(masks, changes)


def test_chance_level_rejects_pure_noise():
    rng = np.random.default_rng(3)
    masks = [xray._small(xray.rise_mask(rng)) for _ in range(40)]
    changes = list(rng.normal(1, 0.3, 40))
    m = xray.RiseMap()
    for s, c in zip(masks, changes):
        m.add(s, c)
    assert m.importance().max() < xray.chance_level(masks, changes, seed=5) * 1.5


def test_analyses_with_the_stand_in(frozen):
    _, snap, kin = frozen
    prober = xray.Prober(snap, xray_fake.open_fake, workers=3)
    intent = xray.run_intent(prober, kin)
    assert intent["noise_cm"] == 0 and intent["consistent_target"] and intent["intent"]["event"] == "close"
    rise = xray.run_rise(prober, kin, masks=40)
    assert rise["looks_at"] == ["top"], "the stand-in only looks at the overhead image"
    assert rise["reliance"]["top"]["change_cm"] > 0.5 and rise["reliance"]["left"]["change_cm"] == 0
    assert np.asarray(rise["heat"]["top"]).shape == (xray.HEAT_H, xray.HEAT_W)
    lang = xray.run_language(prober, kin, repeats=1)
    assert [r["word"] for r in lang["rows"]] == list(xray.PROBE_WORDS)
    assert lang["warning"] is None
    assert prober.calls == 3 + 3 + 3 + 40 + 1 + 5, "language: the original prompt once, then each word"
    assert rise["masked"] == ["top"] and rise["chance_cm"]["left"] is None, "masks only on the camera that matters"
    assert set(lang["pull"]) == {"towards", "checked", "needed_cm"} and lang["pull"]["checked"] == 3


def test_prober_retries_a_warming_model(frozen):
    _, snap, _ = frozen

    class Warming(Exception):
        retryable, retry_after_s = True, 0.01

    class Flaky(xray_fake.FakeDream):
        tries = 0

        def get_action(self):
            Flaky.tries += 1
            if Flaky.tries < 3:
                raise Warming("pool_warming")
            return super().get_action()

    prober = xray.Prober(snap, lambda model: (Flaky(), True), workers=1)
    assert prober.ask([xray.Question(snap.prompt, snap.windows)])[0] is not None
    assert Flaky.tries == 3 and prober.calls == 1


def test_language_summary_texts():
    rows = [{"word": w, "named": b, "targets": [b]} for w, b in [("apple", "apple"), ("banana", "banana")]]
    assert "all 2 cases" in xray.language_summary(rows)["text"]
    rows = [{"word": w, "named": b, "targets": ["banana"]} for w, b in [("apple", "apple"), ("orange", "orange")]]
    rows.append({"word": "blicket", "named": None, "targets": ["banana"]})
    summary = xray.language_summary(rows)
    assert "Ignores the object word" in summary["text"] and "blicket" in summary["text"]
    none = [{"word": "apple", "named": "apple", "targets": [None]}]
    assert "No plan heads for any object" in xray.language_summary(none)["text"]
    assert scene.parse_task("put the banana on the plate") == ("banana", "plate")


def test_rise_skips_the_masks_when_no_camera_matters(frozen, monkeypatch):
    """Measured on real Dream-1: early in a run blanking a camera moved the plan 0.5 cm and 200 masks stayed at chance."""
    _, snap, kin = frozen
    monkeypatch.setattr(xray, "MIN_RELIANCE_CM", 1e6)  # no camera change is large enough
    prober = xray.Prober(snap, xray_fake.open_fake, workers=2)
    rise = xray.run_rise(prober, kin, masks=40)
    assert rise["skipped"] and rise["masks"] == 0 and rise["looks_at"] == []
    assert prober.calls == 3 + 3, "only the unchanged and the blanked windows were asked"
    assert set(rise["reliance"]) == set(xray.CAMERAS) and "barely depends on the images" in rise["text"]


def test_rise_can_still_mask_all_cameras(frozen):
    _, snap, kin = frozen
    prober = xray.Prober(snap, xray_fake.open_fake, workers=2)
    rise = xray.run_rise(prober, kin, masks=16, camera="all")
    assert rise["masked"] == list(xray.CAMERAS) and rise["p_visible"] == xray.RISE_P_ALL
    assert all(rise["chance_cm"][c] is not None for c in xray.CAMERAS)


def test_language_pull_needs_the_named_object_to_come_nearer_than_the_others():
    base = {"apple": 20.0, "banana": 30.0, "orange": 30.0, "water_bottle": 40.0}
    rows = [
        {"word": "banana", "named": "banana", "closest": [{**base, "banana": 24.0}, {**base, "banana": 26.0}]},
        {"word": "orange", "named": "orange", "closest": [{n: v - 5 for n, v in base.items()}]},  # everything nearer
        {"word": "bottle", "named": "water_bottle", "closest": [{**base, "water_bottle": 39.5}]},  # within 1 cm
        {"word": "apple", "named": "apple", "closest": [base]},  # the original word: the reference
        {"word": "blicket", "named": None, "closest": [{**base, "orange": 10.0}]},
    ]
    pull = xray.language_pull(rows, base, original="apple")
    by = {r["word"]: r for r in rows}
    assert by["banana"]["pull_cm"] == 5.0 and by["banana"]["towards"]
    assert by["orange"]["pull_cm"] == 5.0 and not by["orange"]["towards"], "not specific: every object came nearer"
    assert not by["bottle"]["towards"], "0.5 cm is below the 1 cm floor"
    assert by["apple"]["towards"] is None and by["blicket"]["towards"] is None and by["blicket"]["nearest"] == "orange"
    assert pull == {"towards": 1, "checked": 3, "needed_cm": 1.0}
