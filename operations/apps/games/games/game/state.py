"""Match phase, observation, and referee result. No policy twists."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Mapping, Optional

from games.field import Pose2D


class Phase(str, enum.Enum):
    KICKOFF = "kickoff"
    PLAY = "play"
    HOLD = "hold"
    GOAL = "goal"


@dataclass(frozen=True)
class Observation:
    t: float
    ball: Optional[Pose2D]
    robots: Mapping[str, Pose2D]
    lost_ball: bool
    lost_robots: frozenset[str]
    home_goal: Optional[tuple[tuple[float, float], ...]] = None
    away_goal: Optional[tuple[tuple[float, float], ...]] = None


@dataclass(frozen=True)
class MatchState:
    phase: Phase
    score: Mapping[str, int]
    reason: str
    scorer: Optional[str] = None
