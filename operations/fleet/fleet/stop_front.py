"""The body front of the robot kind the trip is for, from the robot body registry (nominal body as the fallback)."""

from __future__ import annotations

from core_common.robot_body import NOMINAL_BODY, nominal_body_for


def body_front_m(robot_kind: str | None) -> float:
    return (nominal_body_for(robot_kind) or NOMINAL_BODY).front_x_m
