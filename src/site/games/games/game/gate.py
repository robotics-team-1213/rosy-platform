"""Last clamp on policy twists. Geometry only; no HTTP."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping

from games.field import ZERO, Field, Twist
from games.game.state import MatchState, Observation, Phase


@dataclass(frozen=True)
class CommandSet:
    twists: dict[str, Twist]
    estop: bool


def gate(
    twists: Mapping[str, Twist],
    obs: Observation,
    state: MatchState,
    field: Field,
    *,
    max_linear: float | None = None,
    max_angular: float | None = None,
) -> CommandSet:
    roster = (field.home_id, field.away_id)
    ids = tuple(dict.fromkeys((*twists, *roster)))
    if state.phase is not Phase.PLAY:
        return CommandSet(twists={robot_id: ZERO for robot_id in ids}, estop=False)

    close = _too_close(obs, field.min_spacing_m)
    out: dict[str, Twist] = {}
    for robot_id in ids:
        twist = twists.get(robot_id, ZERO)
        if not math.isfinite(twist.linear) or not math.isfinite(twist.angular):
            out[robot_id] = ZERO
            continue
        linear = min(twist.linear, 0.0) if robot_id in close else twist.linear
        angular = twist.angular
        if max_linear is not None:
            linear = max(-max_linear, min(max_linear, linear))
        if max_angular is not None:
            angular = max(-max_angular, min(max_angular, angular))
        out[robot_id] = Twist(linear, angular)
    return CommandSet(twists=out, estop=False)


def _too_close(obs: Observation, spacing_m: float) -> set[str]:
    close: set[str] = set()
    robots = list(obs.robots.items())
    for i, (left_id, left) in enumerate(robots):
        for right_id, right in robots[i + 1 :]:
            if math.hypot(right.x - left.x, right.y - left.y) < spacing_m:
                close.add(left_id)
                close.add(right_id)
    return close
