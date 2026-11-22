"""Checks and tracking-time clamping of commissioned Leader/Follower limits for guarded_native.py."""
from __future__ import annotations

from guarded_device import BODY, NAMES, TICKS_PER_DEGREE, TURN, normalized
from guarded_native_probe import safe_print

GRIP_ENDS = ("leader_open", "leader_closed", "follower_open", "follower_closed")


def check_mount(mount):
    """A Leader mount declaration: body joints only, each exactly half a turn (leader_home --match-follower asks the same before moving)."""
    if (type(mount) is not dict or set(mount) - set(BODY)
            or any(type(value) is not int or value not in (-TURN // 2, TURN // 2) for value in mount.values())):
        raise ValueError("leader mount offsets are half a turn (+-2048 ticks) on body joints only")


def check_grip_map(grip_map, leader, follower):
    """The checked copy of a trigger map (None: none declared): four integer ends inside both calibrated ranges."""
    grip_map = dict(grip_map) if type(grip_map) is dict else grip_map  # a copy: later edits cannot reach it
    if grip_map is not None and (
            type(grip_map) is not dict or set(grip_map) != set(GRIP_ENDS)
            or any(type(value) is not int for value in grip_map.values())
            or grip_map["leader_open"] == grip_map["leader_closed"]
            or abs(grip_map["follower_open"] - grip_map["follower_closed"]) >= 100 * TICKS_PER_DEGREE
            or any(not bus.calibration["gripper"].range_min <= grip_map[f"{side}_{end}"] <= bus.calibration["gripper"].range_max
                   for side, bus in (("leader", leader), ("follower", follower)) for end in ("open", "closed"))):
        raise ValueError("leader gripper map needs four integer ends inside the calibrated ranges and a Follower "
                         "travel under 100 degrees")
    return grip_map


def check_floor(floor, follower):
    """The checked copy of follower_floor (None: none): body joint -> integer tick inside the Follower's calibrated range."""
    floor = {} if floor is None else floor
    if (type(floor) is not dict or set(floor) - set(BODY) or any(
            type(value) is not int or not follower.calibration[name].range_min <= value <= follower.calibration[name].range_max
            for name, value in floor.items())):
        raise ValueError("leader follower_floor needs integer ticks inside the Follower's calibrated range, body joints only")
    return dict(floor)


def _clamp_notice(motion, name: str, text: str) -> None:
    clamped = getattr(motion, "clamped", None)
    if clamped is None or name not in clamped:
        if clamped is not None:
            clamped.add(name)
        safe_print(text)


def validate_targets(motion, leader: dict, mapped: dict, target: dict, current: dict) -> None:
    """Validate follower actual pose strictly and map/validate Leader targets (smoothly clamping only while tracking)."""
    for name in NAMES:
        cal = motion.follower.calibration[name]
        if not cal.range_min <= current[name] <= cal.range_max:
            raise ValueError(f"{name}: outside calibrated range")
    can_clamp = bool(motion.full_arm and motion.command is not None and motion.tracking)
    prev_m = getattr(motion, "prev_mapped", None)
    clamped = getattr(motion, "clamped", None)
    if motion.teacher:
        target["gripper"] = leader["gripper"]
        for name, value in target.items():
            cal = motion.follower.calibration[name]
            if not cal.range_min <= value <= cal.range_max:
                raise ValueError(f"{name}: target outside follower calibrated range")
    else:
        for name in BODY:
            lcal, fcal = motion.leader.calibration[name], motion.follower.calibration[name]
            in_l = lcal.range_min <= mapped[name] <= lcal.range_max
            in_f = fcal.range_min <= target[name] <= fcal.range_max
            if not can_clamp:
                if not in_l:
                    raise ValueError(f"{name}: outside calibrated range")
                if not in_f:
                    raise ValueError(f"{name}: target outside follower calibrated range")
            elif not (in_l and in_f):
                low = max(fcal.range_min, motion.floor.get(name, fcal.range_min))
                if (prev_m is not None and name in prev_m and abs(mapped[name] - prev_m[name]) >= 100 * TICKS_PER_DEGREE - 1e-9) or low > fcal.range_max:
                    raise ValueError(f"{name}: outside calibrated range" if not in_l else f"{name}: target outside follower calibrated range")
                clamped_v = max(low, min(fcal.range_max, target[name]))
                target[name] = clamped_v
                _clamp_notice(motion, name, f"{motion.label}: {name} clamped at follower calibrated end ({clamped_v}); torque stays ON")
            elif clamped is not None:
                clamped.discard(name)
        lg, lcal = leader["gripper"], motion.leader.calibration["gripper"]
        lg_use, g_clamped = lg, False
        if not lcal.range_min <= lg <= lcal.range_max:
            if not can_clamp or (prev_m is not None and "gripper" in prev_m and abs(lg - prev_m["gripper"]) >= 100 * TICKS_PER_DEGREE - 1e-9):
                raise ValueError("gripper: outside calibrated range")
            lg_use, g_clamped = max(lcal.range_min, min(lcal.range_max, lg)), True
            _clamp_notice(motion, "gripper", f"{motion.label}: gripper leader trigger clamped at calibrated end ({lg_use}); torque stays ON")
        if not motion.body_only:
            if motion.grip_map:
                ends = motion.grip_map
                part = (lg_use - ends["leader_closed"]) / (ends["leader_open"] - ends["leader_closed"])
                target["gripper"] = round(ends["follower_closed"] + max(0.0, min(1.0, part)) * (ends["follower_open"] - ends["follower_closed"]))
            else:
                grip = normalized(motion.leader, {"gripper": lg_use})["gripper.pos"]
                grip_id = motion.follower.motors["gripper"].id
                target["gripper"] = motion.follower._unnormalize({grip_id: grip})[grip_id]
            fcal = motion.follower.calibration["gripper"]
            if not fcal.range_min <= target["gripper"] <= fcal.range_max:
                if not can_clamp or (prev_m is not None and "gripper" in prev_m and abs(lg - prev_m["gripper"]) >= 100 * TICKS_PER_DEGREE - 1e-9):
                    raise ValueError("gripper: target outside follower calibrated range")
                target["gripper"], g_clamped = max(fcal.range_min, min(fcal.range_max, target["gripper"])), True
                _clamp_notice(motion, "gripper", f"{motion.label}: gripper clamped at follower calibrated end ({target['gripper']}); torque stays ON")
        if not g_clamped and clamped is not None:
            clamped.discard("gripper")
    if not motion.body_only and abs(target["gripper"] - current["gripper"]) >= 100 * TICKS_PER_DEGREE - 1e-9:
        raise ValueError("gripper motor travel >=100 degrees; align manually with torque OFF")
