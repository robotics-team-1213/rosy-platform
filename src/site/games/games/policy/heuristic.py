"""Stage-1 chase. No camera, no neural net."""

from __future__ import annotations

import math

from games.field import ZERO, Field, Twist
from games.game import MatchState, Observation, Phase


class HeuristicPolicy:
    def __init__(
        self,
        field: Field | None = None,
        *,
        speed: float = 0.08,
        angular: float = 0.40,
    ) -> None:
        self.field = field or Field()
        self.speed = speed
        self.angular = angular
        self.avoid_m = self.field.min_spacing_m

    def act(self, obs: Observation, state: MatchState) -> dict[str, Twist]:
        if state.phase is not Phase.PLAY:
            return {}
        return {robot_id: self._twist(robot_id, obs) for robot_id in obs.robots}

    def _twist(self, robot_id: str, observation: Observation) -> Twist:
        pose = observation.robots.get(robot_id)
        if pose is None or observation.ball is None:
            return ZERO
        if not all(math.isfinite(v) for v in (pose.x, pose.y, pose.yaw, observation.ball.x, observation.ball.y)):
            return ZERO
        heading = math.atan2(observation.ball.y - pose.y, observation.ball.x - pose.x)
        err = _wrap(heading - pose.yaw)
        turn = max(-self.angular, min(self.angular, err * 2.0))
        drive = self.speed if abs(err) < 0.4 else 0.0
        goal_x = self.field.opponent_goal_x(robot_id)
        drive += 0.02 if (goal_x - pose.x) * math.cos(pose.yaw) > 0 else 0.0
        other = next((rid for rid in observation.robots if rid != robot_id), None)
        if other is not None:
            opp = observation.robots[other]
            if math.hypot(opp.x - pose.x, opp.y - pose.y) < self.avoid_m:
                drive = min(drive, 0.0)
        return Twist(linear=max(-self.speed, min(self.speed, drive)), angular=turn)


def _wrap(angle: float) -> float:
    if not math.isfinite(angle):
        return 0.0
    return math.remainder(angle, 2 * math.pi)
