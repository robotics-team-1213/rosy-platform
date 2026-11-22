"""MuJoCo camera-local pose changes for fitting and training view variation."""
import math

import numpy as np


_AXES = tuple(zip(np.eye(3), ("rx", "ry", "rz")))


def apply_delta(cell, camera, base, delta):
    """Move the camera relative to its parent body and rotate about camera-local axes."""
    import mujoco

    model, i = cell.model, cell.model.camera(camera).id
    pos, quat, fovy = base
    model.cam_pos[i] = pos + [delta.get("x", 0.), delta.get("y", 0.), delta.get("z", 0.)]
    turn, q = np.zeros(4), quat.copy()
    for axis, key in _AXES:
        mujoco.mju_axisAngle2Quat(turn, axis, math.radians(delta.get(key, 0.)))
        mujoco.mju_mulQuat(q, q.copy(), turn)
    model.cam_quat[i], model.cam_fovy[i] = q, fovy + delta.get("fovy", 0.)


def camera_angle_sampler(world, arm_view, max_deg, namespace):
    """Return a scenario setter using nominal mount poses. None restores the nominal angles."""
    model = world.model
    names = {"top": "top", "side": "side", "wrist": arm_view}
    i_by_name = {role: model.camera(name).id for role, name in names.items()}
    bases = {role: (model.cam_pos[i].copy(), model.cam_quat[i].copy(), float(model.cam_fovy[i])) for role, i in i_by_name.items()}

    def set_angles(seed):
        rng = np.random.default_rng([seed, namespace, 6172]) if seed is not None else None
        result = {}
        for role, name in names.items():
            angles = {key: float(rng.uniform(-max_deg, max_deg)) if rng is not None else 0.0 for _, key in _AXES}
            apply_delta(world, name, bases[role], angles)
            result[role] = angles
        return result

    return set_angles
