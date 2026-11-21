"""Shared localization identifier and odometry rules."""

import math
from typing import Optional

#: D-758 0: one odom step beyond this many metres plus ODOM_JUMP_MPS * dt is a discontinuity (the
#: line-follow PoseTrail's 0.02 + 0.2 dt, recovery/lane_return.py), so the odom epoch moves.
ODOM_JUMP_M, ODOM_JUMP_MPS = 0.02, 0.2


def normalize_map_id(value) -> Optional[str]:
    """MAP-001 map id, normalised to a string or nothing.

    `navigation.map_id: 42` in YAML parses as an int, and every consumer here
    treats the id as a string: the swarm map guard compares it (so a non-string
    never matches and the formation silently stops issuing goals), and the
    leader pose stream declares it `Optional[str]` (so pydantic raises and the
    socket closes on connect, with the handler's bare except hiding why). A
    scalar the operator typed becomes its text; anything else is not an id.
    """
    if isinstance(value, str):
        return value or None
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return str(value)
    return None


def odom_position_jump(dx: float, dy: float, dt: float) -> bool:
    return math.hypot(dx, dy) > ODOM_JUMP_M + ODOM_JUMP_MPS * dt
