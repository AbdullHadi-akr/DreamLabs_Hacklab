"""Kinematics for teleop: forward/inverse kinematics of the simulated YAM arms and the main view's projection.

Everything here runs on the sim thread (MuJoCo is not thread-safe). The arm math works on its own scratch MjData,
never on the simulation's data, so solving a pose does not disturb the physics.
"""

from __future__ import annotations

import mujoco
import numpy as np

SIDES = ("left", "right")
## Axes of the TCP site (columns of its orientation): the fingers slide along y, the gripper points along z.
FINGER_AXIS, POINTING_AXIS = 1, 2
DOWN = np.array([0.0, 0.0, -1.0])


def _quat(mat: np.ndarray) -> np.ndarray:
    quat = np.empty(4)
    mujoco.mju_mat2Quat(quat, np.asarray(mat, float).ravel())
    return quat


def rotation(axis, angle: float) -> np.ndarray:
    """3x3 rotation by `angle` (rad) about the world axis `axis` (Rodrigues)."""
    axis = np.asarray(axis, float) / np.linalg.norm(axis)
    k = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    return np.eye(3) + np.sin(angle) * k + (1 - np.cos(angle)) * k @ k


def angle_between(mat_a, mat_b) -> float:
    """Angle (rad) of the rotation between two orientations."""
    cos = (np.trace(np.asarray(mat_a) @ np.asarray(mat_b).T) - 1) / 2
    return float(np.arccos(np.clip(cos, -1.0, 1.0)))


def point_down(mat) -> np.ndarray:
    """The orientation turned the shortest way so the gripper points straight down; its rotation is kept."""
    mat = np.asarray(mat, float)
    pointing = mat[:, POINTING_AXIS]
    axis = np.cross(pointing, DOWN)
    sin, cos = np.linalg.norm(axis), pointing @ DOWN
    if sin < 1e-9:
        return mat.copy() if cos > 0 else rotation(mat[:, 0], np.pi) @ mat
    return rotation(axis, np.arctan2(sin, cos)) @ mat


def describe(mat) -> dict:
    """For people: rotation = direction the fingers open in, seen from above (deg, 0 = along x, the gripper is
    symmetric so -90..90); tilt = how far the gripper points away from straight down (deg)."""
    mat = np.asarray(mat, float)
    fingers = mat[:, FINGER_AXIS]
    tilt = np.degrees(np.arccos(np.clip(mat[:, POINTING_AXIS] @ DOWN, -1, 1)))
    rotation_deg = None
    if np.hypot(fingers[0], fingers[1]) > 0.2:  # fingers not (almost) vertical
        rotation_deg = (np.degrees(np.arctan2(fingers[1], fingers[0])) + 90) % 180 - 90
    return {"rotation": None if rotation_deg is None else round(float(rotation_deg), 1), "tilt": round(float(tilt), 1)}


class ArmKinematics:
    """FK/IK for the six arm joints up to the simulator's TCP site (`<side>_tcp`, between the fingertips)."""

    def __init__(self, model: mujoco.MjModel):
        self.model = model
        self.data = mujoco.MjData(model)
        self.site = {side: model.site(f"{side}_tcp").id for side in SIDES}
        joints = {side: [model.joint(f"{side}_joint{i}") for i in range(1, 7)] for side in SIDES}
        self.qpos_adr = {side: np.array([int(j.qposadr[0]) for j in joints[side]]) for side in SIDES}
        self.dof_adr = {side: np.array([int(j.dofadr[0]) for j in joints[side]]) for side in SIDES}
        self.limits = {side: np.array([j.range.copy() for j in joints[side]]) for side in SIDES}
        self._jacp = np.zeros((3, model.nv))
        self._jacr = np.zeros((3, model.nv))

    def fk(self, side: str, q) -> tuple[np.ndarray, np.ndarray]:
        """TCP position (world, m) and orientation (3x3) for the six joint angles q."""
        self.data.qpos[self.qpos_adr[side]] = q
        mujoco.mj_kinematics(self.model, self.data)
        mujoco.mj_comPos(self.model, self.data)  # the Jacobian needs the com-based dof frames
        site = self.site[side]
        return self.data.site_xpos[site].copy(), self.data.site_xmat[site].reshape(3, 3).copy()

    def solve(self, side: str, target_pos, target_mat=None, q0=None, *, target_axis=None, iterations: int = 100,
              rot_weight: float = 0.3, damping: float = 0.02, max_step: float = 0.25,
              ) -> tuple[np.ndarray, float, float]:
        """Joint angles that bring the TCP to target_pos, starting from q0.

        Orientation, optional: target_mat = the full TCP orientation (3x3), or target_axis = only the direction the
        gripper points in (the TCP's z axis, e.g. straight down); the rotation around it stays free.
        Damped least squares, clamped to the joint limits. Unreachable targets give the closest pose found.
        @return (six joint angles, remaining position error in m, remaining orientation error in rad)
        """
        lo, hi = self.limits[side].T
        q = np.clip(np.asarray(q0 if q0 is not None else np.zeros(6), float), lo, hi)
        target_pos = np.asarray(target_pos, float)
        target_quat = _quat(target_mat) if target_mat is not None else None
        axis = None if target_axis is None else np.asarray(target_axis, float) / np.linalg.norm(target_axis)
        oriented = target_quat is not None or axis is not None
        site, dofs = self.site[side], self.dof_adr[side]
        err_rot = np.zeros(3)
        for _ in range(iterations):
            pos, mat = self.fk(side, q)
            err_pos = target_pos - pos
            if target_quat is not None:
                current = _quat(mat)
                mujoco.mju_negQuat(current, current)
                diff = np.empty(4)
                mujoco.mju_mulQuat(diff, target_quat, current)
                mujoco.mju_quat2Vel(err_rot, diff, 1.0)  # rotation still to go, world frame
            elif axis is not None:
                pointing = mat[:, POINTING_AXIS]
                err_rot = np.cross(pointing, axis)
                if pointing @ axis < -0.99:  # pointing the opposite way: the cross product vanishes, nudge it
                    err_rot = np.cross(pointing, mat[:, 0])
            if np.linalg.norm(err_pos) < 1e-4 and (not oriented or np.linalg.norm(err_rot) < 2e-3):
                break
            mujoco.mj_jacSite(self.model, self.data, self._jacp, self._jacr, site)
            if not oriented:
                jac, err = self._jacp[:, dofs], err_pos
            else:
                jac_rot = self._jacr[:, dofs]
                if axis is not None:  # only turning the pointing direction counts, not rolling around it
                    pointing = mat[:, POINTING_AXIS]
                    jac_rot = (np.eye(3) - np.outer(pointing, pointing)) @ jac_rot
                jac = np.vstack([self._jacp[:, dofs], rot_weight * jac_rot])
                err = np.r_[err_pos, rot_weight * err_rot]
            dq = jac.T @ np.linalg.solve(jac @ jac.T + damping**2 * np.eye(len(err)), err)
            norm = np.linalg.norm(dq)
            if norm > max_step:
                dq *= max_step / norm
            q = np.clip(q + dq, lo, hi)
        pos, mat = self.fk(side, q)
        if target_mat is not None:
            rot_error = angle_between(mat, target_mat)
        elif axis is not None:
            rot_error = float(np.arccos(np.clip(mat[:, POINTING_AXIS] @ axis, -1, 1)))
        else:
            rot_error = 0.0
        return q, float(np.linalg.norm(target_pos - pos)), rot_error


# ---------- main view: world point <-> image position ----------


def view_from_scene(scene: mujoco.MjvScene, width: int, height: int) -> dict:
    """The camera of the frame just built in `scene` (after update_scene), for project() and drag_point()."""
    cam = mujoco.mjv_averageCamera(scene.camera[0], scene.camera[1])  # what a mono render uses
    forward, up = np.array(cam.forward, float), np.array(cam.up, float)
    tan_y = cam.frustum_top / cam.frustum_near
    return {"pos": np.array(cam.pos, float), "forward": forward, "up": up, "right": np.cross(forward, up),
            "tan_y": tan_y, "tan_x": tan_y * width / height}


def project(view: dict, point) -> list[float] | None:
    """Image position (u, v) of a world point, 0..1 from the top left, or None if it is behind the camera."""
    rel = np.asarray(point, float) - view["pos"]
    depth = rel @ view["forward"]
    if depth <= 1e-6:
        return None
    u = 0.5 + 0.5 * (rel @ view["right"]) / depth / view["tan_x"]
    v = 0.5 - 0.5 * (rel @ view["up"]) / depth / view["tan_y"]
    return [round(float(u), 4), round(float(v), 4)]


def ray(view: dict, u: float, v: float) -> np.ndarray:
    """Direction of the view ray through image position (u, v)."""
    direction = view["forward"] + (2 * u - 1) * view["tan_x"] * view["right"] + (1 - 2 * v) * view["tan_y"] * view["up"]
    return direction / np.linalg.norm(direction)


def drag_point(view: dict, u: float, v: float, anchor, mode: str = "horizontal", max_move: float = 1.0):
    """Where a point dragged from `anchor` to image position (u, v) ends up.

    horizontal: on the horizontal plane through the anchor (height stays). vertical: only the height changes,
    on the vertical plane through the anchor that faces the camera. None if the ray misses the plane.
    """
    anchor = np.asarray(anchor, float)
    origin, direction = view["pos"], ray(view, u, v)
    if mode == "vertical":
        normal = np.array([view["forward"][0], view["forward"][1], 0.0])
        if np.linalg.norm(normal) < 1e-6:  # looking straight down: no sensible vertical plane
            return None
        normal /= np.linalg.norm(normal)
    else:
        normal = np.array([0.0, 0.0, 1.0])
    denom = direction @ normal
    if abs(denom) < 1e-4:
        return None
    t = ((anchor - origin) @ normal) / denom
    if t <= 0:
        return None
    point = origin + t * direction
    if mode == "vertical":
        point = np.array([anchor[0], anchor[1], point[2]])
    move = point - anchor
    if np.linalg.norm(move) > max_move:  # grazing view angles: no jumps across the room
        point = anchor + move / np.linalg.norm(move) * max_move
    return point
