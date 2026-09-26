"""Referee contract. Policy twists stay out of step()."""

from __future__ import annotations

from typing import Protocol

from games.field import Field
from games.game.state import MatchState, Observation


class Game(Protocol):
    field: Field

    def reset(self) -> MatchState: ...

    def step(self, obs: Observation) -> MatchState: ...
