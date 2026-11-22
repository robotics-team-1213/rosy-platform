"""Checks of a Leader's commissioned declarations (<leader calibration>.mount.json) for guarded_native.py.

All fail closed with ValueError before any torque: half-turn mount offsets, the trigger-to-jaw map, and follower_floor.
"""
from __future__ import annotations

from guarded_device import BODY, TICKS_PER_DEGREE, TURN

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
