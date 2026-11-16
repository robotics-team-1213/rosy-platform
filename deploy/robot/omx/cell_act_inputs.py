#!/usr/bin/env python3
"""Real-cell inputs of the two-arm ACT shadow, in the order and size the policy was trained on (read only).

The two-arm policy (`tools/sim/omx_two_arm_policy_helpers.py`) takes `observation.state` = arm_a's six joints then arm_b's
(`sites.ARMS` order; `JOINTS` = joint1..joint5, gripper_joint_1; radians), four RGB cameras `observation.images.<view>` for the views of
`omx_two_arm_teacher_stages.RECORDED`, each rendered 240x320 (`SHAPE`) and fed as uint8/255 CHW, and, when the checkpoint has the input,
`observation.environment_state` (`goal_of`: this carry's arm block in its arm's half, zeros for the other arm). Nothing is filled in:
a camera, an arm state or a goal this cell cannot read makes `Unavailable`, and the shadow row says why. This module only calls
`.frame(camera)` and `.act("state")` on the cells; it has no way to command an arm."""
from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import time

import numpy as np

from arm_status_bridge import to_radians  # the cell's one follower-units -> radians conversion (gripper 0..100)

VIEWS = ("top", "side", "a_wrist", "b_wrist")  # RECORDED in tools/sim/omx_two_arm_teacher_stages.py
ARMS = ("arm_a", "arm_b")  # sites.ARMS: the order of both arms' joints and goal halves
JOINTS = ("joint1", "joint2", "joint3", "joint4", "joint5", "gripper_joint_1")  # omx_two_arm_world.JOINTS
SHAPE = (240, 320)  # (height, width) of omx_two_arm_policy_helpers.SHAPE
JOINT_NAMES = tuple(f"{arm}.{joint}" for arm in ARMS for joint in JOINTS)
SHARED = {"top": "top", "side": "side"}  # A and B cells share these two cameras; each wrist is its own arm's `wrist`
MAX_SPAN_S = 2.0  # the capture of all frames and both states must fit this window, else the row refuses


class Unavailable(Exception):
    """An input the policy needs could not be read; `missing` names the views/arms/goal."""

    def __init__(self, reason: str, missing=()):
        super().__init__(reason)
        self.missing = list(missing)


def _rgb(image):
    import cv2

    if not isinstance(image, np.ndarray) or image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
        raise ValueError("uint8 HxWx3 frame required")
    # the cell decodes BGR (cv2.imdecode); the sim renders RGB. Bicubic like omx_two_arm_shadow.compare's PIL resize.
    return np.ascontiguousarray(cv2.resize(cv2.cvtColor(image, cv2.COLOR_BGR2RGB), SHAPE[::-1], interpolation=cv2.INTER_CUBIC))


def grip_rule(config: dict, arm: str) -> dict:
    """The arm's own gripper rule from its arm-cal profile (`cell_arm_cal`): 30 mm held at `held_30mm` units, `gap_mm_per_unit`.
    The peer's profile is read by its arm id from the work dir: `arm_calibration_path` names this cell's arm only."""
    import cell_arm_cal

    profile = cell_arm_cal.load(config if arm == config.get("arm_id") else Path(config.get("work_dir", ".")).expanduser(), arm)
    return {"held_30mm": float(profile["held_30mm"]), "gap_mm_per_unit": float(profile["gap_mm_per_unit"])}


def sim_gripper(units: float, rule: dict) -> float:
    """Follower gripper units -> the sim's gripper_joint_1: the real jaw gap by the arm's rule, posed by the palletizing jaw
    geometry (the sim's fingers). The servo angle is not it: 2026-11-17 the servo's 50.5 closed read 0.03 rad, the sim's
    trained gripper range is 0.34-0.99."""
    isaac = str(Path(__file__).resolve().parents[3] / "learning" / "envs" / "isaac")
    if isaac not in sys.path:
        sys.path.insert(0, isaac)
    import palletizing_gripper as jaw

    return jaw.angle_for_gap_clipped((30 + (units - rule["held_30mm"]) * rule["gap_mm_per_unit"]) / 1000)


def _read_state(cell, arm, rule):
    reply = cell.act("state")
    state = reply.get("state") if isinstance(reply, dict) and reply.get("ok") else None
    if state is None or len(state) != len(JOINTS):
        raise Unavailable(f"{arm}: no six-joint state ({reply.get('error') if isinstance(reply, dict) else reply})", [f"state:{arm}"])
    body = to_radians(state)  # the follower calibration is the full 0..4095 range on arm_a and arm_b (checked 2026-11-17)
    return [body[name] for name in ("joint1", "joint2", "joint3", "joint4", "joint5")] + [sim_gripper(float(state[5]), rule)], float(state[5])


def goal(spec: dict, binding, arm: str, source, dest):
    """`omx_two_arm_policy_helpers.goal_of` of this carry's block; None when the checkpoint has no goal input."""
    if not binding.goal_size:
        return None
    if binding.goal_mode == "site":  # goal_block(mode="site"): 1, one-hot source, one-hot target over the sorted site names
        names, site_map = list(binding.goal_sites), spec.get("site_map", {})
        pair = (site_map.get(source), site_map.get(dest))
        if pair[0] not in names or pair[1] not in names:
            raise Unavailable(f"goal sites {source!r}->{dest!r} do not map to the policy's sites (config act_shadow.site_map)", ["goal"])
        block = np.zeros(1 + 2 * len(names), np.float32)
        block[0], block[1 + names.index(pair[0])], block[1 + len(names) + names.index(pair[1])] = 1.0, 1.0, 1.0
    else:  # joints mode needs the sim layout's IK (goal_block); the lab supplies it per carry in config act_shadow.joint_goals
        block = spec.get("joint_goals", {}).get(f"{source}>{dest}")
        if block is None or len(block) != binding.goal_size // 2:
            raise Unavailable(f"no {binding.goal_size // 2}-value joints goal for {source!r}>{dest!r} (config act_shadow.joint_goals)", ["goal"])
        block = np.asarray(block, np.float32)
    out, half = np.zeros(binding.goal_size, np.float32), binding.goal_size // 2
    out[ARMS.index(arm) * half:(ARMS.index(arm) + 1) * half] = block
    return out


def check_binding(binding) -> None:
    """The checkpoint's own input features must be exactly the trained layout this module assembles."""
    if (tuple(sorted(binding.image_views)) != tuple(sorted(VIEWS)) or tuple(binding.image_shape) != (3, *SHAPE)
            or binding.state_size != len(JOINT_NAMES) or tuple(binding.joint_names) != JOINT_NAMES):
        raise Unavailable(f"checkpoint inputs {sorted(binding.image_views)} {binding.image_shape} state {binding.state_size} "
                          f"differ from the trained layout {VIEWS} {(3, *SHAPE)} {len(JOINT_NAMES)}")


def assemble(cell, config: dict, peer, spec: dict, binding, source, dest) -> dict:
    """{state, images, goal, meta} for one inference, or `Unavailable`. `cell` is this arm's cell, `peer` the other arm's."""
    check_binding(binding)
    arm = config.get("arm_id")
    if arm not in ARMS:
        raise Unavailable(f"arm_id {arm!r} is not one of the two-arm policy's arms {ARMS}", ["arm_id"])
    other = ARMS[1 - ARMS.index(arm)]
    cells = {arm: cell, other: peer}
    if peer is None:
        raise Unavailable(f"{other} is not connected (config act_shadow.peer); one arm's state is not the policy's input", [f"state:{other}", f"{VIEWS[2 + ARMS.index(other)]}"])
    route = {"top": (arm, "top"), "side": (arm, "side"), "a_wrist": ("arm_a", "wrist"), "b_wrist": ("arm_b", "wrist")}
    images, raw, times, missing = {}, {}, [], {}
    for view in VIEWS:
        owner, camera = route[view]
        try:
            times.append(time.time())
            frame = cells[owner].frame(camera)
            raw[view], images[view] = frame.shape[:2], _rgb(frame)
        except Exception as error:  # a camera the cell lacks or cannot read: named, never replaced by a blank image
            missing[view] = f"{owner}.{camera}: {type(error).__name__}: {error}"
    states, grip_units, rules = {}, {}, {name: grip_rule(config, name) for name in ARMS}
    for name in ARMS:
        try:
            times.append(time.time())
            states[name], grip_units[name] = _read_state(cells[name], name, rules[name])
        except Unavailable as error:
            missing[f"state:{name}"] = str(error)
    if missing:
        raise Unavailable("; ".join(f"{k} ({v})" for k, v in missing.items()), missing)
    times.append(time.time())
    if times[-1] - times[0] > MAX_SPAN_S:
        raise Unavailable(f"capture took {times[-1] - times[0]:.2f} s (> {MAX_SPAN_S}): inputs are not one moment", ["span"])
    state = np.asarray([v for name in ARMS for v in states[name]], np.float32)
    if not np.isfinite(state).all():
        raise Unavailable("nonfinite joint state", ["state"])
    vector = goal(spec, binding, arm, source, dest)
    meta = {"views": list(VIEWS), "camera_sources": {v: ".".join(route[v]) for v in VIEWS}, "model_shape": [3, *SHAPE],
            "source_shapes": {v: list(s) for v, s in raw.items()}, "capture_span_s": round(times[-1] - times[0], 3),
            "frames_sha256": {v: hashlib.sha256(images[v].tobytes()).hexdigest() for v in VIEWS},
            "positions": [float(v) for v in state], "gripper_units": grip_units, "gripper_rules": rules, "goal": None if vector is None else {"mode": binding.goal_mode, "size": int(vector.size)}}
    return {"state": state, "images": images, "goal": vector, "meta": meta}
