"""Dry-run stand-in for Dream-1: a scripted pick-and-place that is planned ONCE on the unperturbed scene and then
replayed blindly in every trial.

It costs no credits and is deterministic, so it validates the whole test pipeline (setup, perturbation, monitoring,
analysis, video). It is also a useful reference: an open-loop policy fails as soon as the object or container moves
a couple of centimetres and ignores every visual change. Dream-1 should do better on the first and match it on the
second.
"""

from __future__ import annotations

import mujoco
import numpy as np

from dreamtool import scene, sim

## Weight of the "gripper points down" term in the IK; small over the container, where any tilt is fine.
GRASP_WEIGHT, PLACE_WEIGHT = 0.3, 0.02


def solve_ik(env, side, target, seed, weight=GRASP_WEIGHT):
    """Damped least squares IK for the TCP site: position `target`, gripper z-axis pointing down."""
    m = env.model
    d = mujoco.MjData(m)
    d.qpos[:] = env.data.qpos
    ids = [m.joint(f"{side}_joint{i}").id for i in range(1, 7)]
    qa, va, limits = m.jnt_qposadr[ids], m.jnt_dofadr[ids], m.jnt_range[ids]
    site = m.site(f"{side}_tcp").id
    down = np.array([0.0, 0.0, -1.0])
    rng = np.random.default_rng(0)
    best = (np.inf, None)
    for initial in [seed] + [rng.uniform(limits[:, 0] * 0.6, limits[:, 1] * 0.6) for _ in range(8)]:
        q = np.clip(np.asarray(initial, float), limits[:, 0], limits[:, 1])
        for _ in range(150):
            d.qpos[qa] = q
            mujoco.mj_kinematics(m, d)
            mujoco.mj_comPos(m, d)
            e_rot = np.cross(d.site_xmat[site].reshape(3, 3)[:, 2], down)
            e_pos = target - d.site_xpos[site]
            score = np.linalg.norm(e_pos) + 0.05 * np.linalg.norm(e_rot)
            if score < best[0]:
                best = (score, q.copy())
            if np.linalg.norm(e_pos) < 0.003 and (weight < GRASP_WEIGHT or np.linalg.norm(e_rot) < 0.05):
                return q
            jp, jr = np.zeros((3, m.nv)), np.zeros((3, m.nv))
            mujoco.mj_jacSite(m, d, jp, jr, site)
            J = np.vstack([jp[:, va], weight * jr[:, va]])
            dq = J.T @ np.linalg.solve(J @ J.T + 1e-4 * np.eye(6), np.r_[e_pos, weight * e_rot])
            q = np.clip(q + np.clip(dq, -0.15, 0.15), limits[:, 0], limits[:, 1])
    if best[0] < 0.01:
        return best[1]
    raise ValueError(f"IK found no pose for {side} arm at {np.round(target, 3)}")


def plan(env, obj: str, container: str) -> list:
    """Plans pick-and-place of `obj` into `container` on a freshly reset scene. Returns (left, right) targets."""
    env.reset()
    home = sim.HOME
    for _ in range(10):
        env.step(home, home)
    p, c = scene.position(env, obj), scene.position(env, container)
    side = "left" if p[0] > 0 else "right"
    q, rows = np.zeros(6), []

    def move(target, opening, steps, weight=GRASP_WEIGHT):
        nonlocal q
        end = solve_ik(env, side, np.asarray(target, float), q, weight)
        for a in np.linspace(0, 1, steps):
            rows.append(np.r_[q + (end - q) * (a * a * (3 - 2 * a)), opening])
        q = end

    def grip(start, end, steps):
        rows.extend(np.r_[q, o] for o in np.linspace(start, end, steps))

    grasp_z = -0.009 if obj == "orange" else 0.003
    move(p + [0, 0, 0.14], 1, 40)
    move(p + [0, 0, grasp_z], 1, 30)
    grip(1, 0, 15)
    move(p + [0, 0, 0.15], 0, 30)
    move(c + [0, 0, 0.17], 0, 40, PLACE_WEIGHT)
    move(c + [0, 0, 0.11], 0, 15, PLACE_WEIGHT)
    grip(0, 1, 10)
    move(c + [0, 0, 0.18], 1, 15, PLACE_WEIGHT)
    rows.extend([rows[-1]] * 20)  # let the object settle before the success check
    env.reset()
    return [(r, home) if side == "left" else (home, r) for r in rows]


def hold_still(env, seconds=1.5):
    state = env.state()
    return [(state["left"], state["right"])] * int(seconds * 20)
