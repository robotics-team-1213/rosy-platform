"""Observer that never sees a ball. Used to prove the host holds at zero."""

from __future__ import annotations

from games.field import Pose2D
from games.game import Observation


class HoldObserver:
    def __init__(self, home_id: str, away_id: str) -> None:
        self.home_id = home_id
        self.away_id = away_id

    def observe(self) -> Observation:
        return Observation(
            t=0.0,
            ball=None,
            robots={
                self.home_id: Pose2D(-0.4, 0.0, 0.0),
                self.away_id: Pose2D(0.4, 0.0, 3.14),
            },
            lost_ball=True,
            lost_robots=frozenset(),
        )
