"""D-785: an Action SUCCEEDED counts as completed only when the measured joints reached the goal.

On the native OMX graph the vendor JointTrajectoryController has no goal constraints, so it reports
SUCCEEDED after ``time_from_start`` whether or not a motor followed (2026-10-17 micro-step: wire
goal 2023 -> 2025, torque OFF, joint flat, SUCCEEDED). ``max_final_state_errors`` lets an owner
policy require the latest accepted joint state to be within a per-joint error of the commanded
final position. ``None`` for a joint leaves it unchecked (a gripper that stalls on an object);
an unset policy keeps today's behaviour.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from types import MappingProxyType


def normalize_final_state_errors(joint_names, configured) -> Mapping[str, float | None] | None:
    if configured is None:
        return None
    try:
        errors = dict(configured)
    except (TypeError, ValueError):
        raise ValueError("max_final_state_errors must be a mapping of joint names") from None
    if set(errors) != set(joint_names):
        raise ValueError("max_final_state_errors must exactly match joint_names")
    checked: dict[str, float | None] = {}
    for name in joint_names:
        value = errors[name]
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) \
                    or value <= 0:
                raise ValueError(f"max_final_state_errors[{name}] must be positive and finite, or None")
            value = float(value)
        checked[name] = value
    if all(value is None for value in checked.values()):
        raise ValueError("max_final_state_errors must check at least one joint")
    return MappingProxyType(checked)


def final_state_reason(errors, command, snapshot) -> str | None:
    """None when completed; otherwise the HOLD reason. Never trusts the Action result alone."""
    if errors is None:
        return None
    if snapshot is None:
        return "final_state_unavailable"
    for name, target in command.positions.items():
        limit = errors.get(name)
        if limit is None:
            continue
        measured = snapshot.positions.get(name)
        if measured is None:
            return "final_state_unavailable"
        if abs(measured - target) > limit:
            return "goal_not_reached"
    return None


__all__ = ["final_state_reason", "normalize_final_state_errors"]
