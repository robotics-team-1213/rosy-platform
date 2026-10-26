"""Fleet-owned swarm data declarations; no planning, admission or I/O."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

MIN_SPACING = 0.4

DEFAULT_SPACING = 0.6

Point = tuple[float, float]

class Formation(str, Enum):
    FOLLOW = "FOLLOW"
    COLUMN = "COLUMN"
    LINE = "LINE"
    V = "V"
    GRID = "GRID"
    CIRCLE = "CIRCLE"
    #: D-559: COLUMN slots, but each follower replays the leader's driven path
    #: (`mode="trail"`, `distance` = path distance behind the leader).
    TRAIL = "TRAIL"

class FormationError(ValueError):
    """대형을 만들 수 없는 파라미터."""

@dataclass(frozen=True)
class SlotOffset:
    """리더 heading 기준 슬롯. `distance` 는 리더 뒤(+), `lateral` 은 리더 왼쪽(+), m."""

    distance: float
    lateral: float

@dataclass
class FormationSpec:
    formation: Formation
    spacing: float = DEFAULT_SPACING
    grid_cols: int = 2
    max_speed: float = 0.15
    stream_timeout_ms: int = 1000

class SessionError(Exception):
    pass

class ArmingFailed(SessionError):
    def __init__(self, robot_id: str, code: str, message: str = "") -> None:
        super().__init__(f"{robot_id} refused follow: {code} {message}".strip())
        self.robot_id = robot_id
        self.code = code

class MapMismatch(SessionError):
    def __init__(self, map_ids: dict[str, Optional[str]]) -> None:
        super().__init__(f"robots are not on one map: {map_ids}")
        self.map_ids = map_ids

class InvalidFormation(SessionError):
    """대형을 만들 수 없는 spec. `FormationError`/`AssignmentError` 의 세션 쪽 얼굴."""

class SessionState(str, Enum):
    IDLE = "IDLE"
    ARMING = "ARMING"
    RUNNING = "RUNNING"
    HOLDING = "HOLDING"
    STOPPED = "STOPPED"

class HoldPolicy(str, Enum):
    HOLD = "HOLD"      # 릴레이 pause + 리더 navigation/cancel. 팔로워 follow 세션은 산다.
    ABORT = "ABORT"    # 전 팔로워 swarm/cancel + 리더 navigation/cancel. 세션 종료.
