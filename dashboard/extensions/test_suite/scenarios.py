"""Plan exact repetitions or explicit parameter combinations in MuJoCo."""
from itertools import product
import random

import mujoco
import numpy as np

from dreamtool import scene

LIGHT = {"none": 1., "low": .85, "medium": .65, "high": .45}
STRESS = {"reach": [(15, 0, 1), (-15, 0, 1)], "visibility": [(0, -20, .45), (0, 20, .45)],
          "combined": [(15, -20, .45), (-15, 20, .45)]}
STATE_SPEC = mujoco.mjtState.mjSTATE_INTEGRATION


def capture_start(env):
    state = np.empty(mujoco.mj_stateSize(env.model, STATE_SPEC))
    mujoco.mj_getState(env.model, env.data, state, STATE_SPEC)
    return state.tolist()


def sweep_values(config):
    return (
        config.positions or list(dict.fromkeys([0., config.position_variation])),
        config.tilts or list(dict.fromkeys([0., config.camera_variation])),
        config.lights or [LIGHT[config.difficulty]],
    )


def generate(config):
    rng = random.Random(config.seed)
    goal = config.placement_goal
    obj = config.object or (goal[0] if goal else None)
    if config.mode == "quick":
        yield dict(prompt=config.prompt, model=config.model, object=obj, offset=0., tilt=0., light=1.,
                   seed=config.seed, run=1, current_scene=True)
        return
    if config.mode == "safety":
        plan = [("baseline", None, (0, 0, 1))] if config.stress_baseline else []
        for name in config.stress_scenarios:
            for values in STRESS[name]:
                signed = values[1] if name == "visibility" else values[0]
                plan.append((name, "positive" if signed > 0 else "negative", values))
        conditions = (values for _, _, values in plan)
    elif config.mode == "sweep":
        combinations = list(product(*sweep_values(config)))
        conditions = (values for _ in range(config.repeats) for values in combinations)
    else:
        conditions = (
            (rng.uniform(-config.position_variation, config.position_variation),
             rng.uniform(-config.camera_variation, config.camera_variation), LIGHT[config.difficulty])
            for _ in range(config.repeats)
        )
    for number, (offset, tilt, light) in enumerate(conditions, 1):
        case = dict(prompt=config.prompt, model=config.model, object=obj, offset=offset,
                    tilt=tilt, light=light, seed=config.seed, run=number)
        if config.mode == "ab":
            yield dict(case, run=2 * number - 1, pair=number, variant="A")
            yield dict(case, run=2 * number, pair=number, variant="B", prompt=config.prompt_b)
        else:
            if config.mode == "safety":
                case["stress_scenario"], case["stress_direction"], _ = plan[number - 1]
            yield case


def apply(env, case):
    if not case.get("current_scene"):
        env.reset()
    if "starting_physics" in case:
        mujoco.mj_setState(env.model, env.data, np.asarray(case["starting_physics"]), STATE_SPEC)
    elif case["offset"]:
        scene.shift(env, case["object"], [case["offset"] / 100, 0])
    camera = env.model.camera("top")
    original = camera.quat.copy()
    diffuse = env.model.light_diffuse.copy()
    ambient = env.model.light_ambient.copy()

    def restore():
        camera.quat[:] = original
        env.model.light_diffuse[:] = diffuse
        env.model.light_ambient[:] = ambient
        mujoco.mj_forward(env.model, env.data)

    try:
        rotation = np.empty(4)
        mujoco.mju_axisAngle2Quat(rotation, np.array([1., 0., 0.]), np.deg2rad(case["tilt"]))
        mujoco.mju_mulQuat(camera.quat, original, rotation)
        env.model.light_diffuse[:] = diffuse * case["light"]
        env.model.light_ambient[:] = ambient * case["light"]
        mujoco.mj_forward(env.model, env.data)
    except Exception:
        restore()
        raise
    return restore
