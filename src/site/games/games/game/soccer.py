"""1v1 push-ball referee. Observation in, MatchState out."""

from __future__ import annotations

from typing import Optional

from games.field import Field
from games.game.state import MatchState, Observation, Phase


class SoccerGame:
    def __init__(self, field: Field | None = None) -> None:
        self.field = field or Field()
        self.phase = Phase.KICKOFF
        self.score = {self.field.home_id: 0, self.field.away_id: 0}

    def reset(self) -> MatchState:
        self.phase = Phase.KICKOFF
        return MatchState(phase=self.phase, score=dict(self.score), reason="")

    def step(self, obs: Observation) -> MatchState:
        if self.phase is Phase.PLAY and self._is_lost(obs):
            self.phase = Phase.HOLD
            return MatchState(
                phase=self.phase,
                score=dict(self.score),
                reason=self._lost_reason(obs),
            )
        if self.phase is Phase.HOLD:
            if self._is_lost(obs):
                return MatchState(
                    phase=self.phase,
                    score=dict(self.score),
                    reason=self._lost_reason(obs),
                )
            self.phase = Phase.KICKOFF
        if self.phase is Phase.KICKOFF:
            if self._kickoff_ready(obs):
                self.phase = Phase.PLAY
            return MatchState(phase=self.phase, score=dict(self.score), reason="")
        scorer = self._goal_scorer(obs)
        if scorer is not None:
            self.score[scorer] += 1
            scored = MatchState(
                phase=Phase.GOAL,
                score=dict(self.score),
                reason="goal",
                scorer=scorer,
            )
            self.phase = Phase.KICKOFF
            return scored
        return MatchState(phase=self.phase, score=dict(self.score), reason="")

    def _is_lost(self, obs: Observation) -> bool:
        if obs.lost_ball or obs.ball is None:
            return True
        if obs.lost_robots:
            return True
        return self.field.home_id not in obs.robots or self.field.away_id not in obs.robots

    def _lost_reason(self, obs: Observation) -> str:
        if obs.lost_ball or obs.ball is None:
            return "lost_ball"
        if obs.lost_robots:
            return "lost_robots"
        return "lost_robots"

    def _kickoff_ready(self, obs: Observation) -> bool:
        if obs.lost_ball or obs.ball is None:
            return False
        if obs.lost_robots:
            return False
        if self.field.home_id not in obs.robots or self.field.away_id not in obs.robots:
            return False
        return (obs.ball.x ** 2 + obs.ball.y ** 2) ** 0.5 <= self.field.kickoff_radius_m

    def _goal_scorer(self, obs: Observation) -> Optional[str]:
        if obs.ball is None:
            return None
        field = self.field.with_goals(home=obs.home_goal, away=obs.away_goal)
        if field.in_away_goal(obs.ball.x, obs.ball.y):
            return self.field.home_id
        if field.in_home_goal(obs.ball.x, obs.ball.y):
            return self.field.away_id
        return None
