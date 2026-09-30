"""Road-behaviour data model: states, stamped inputs, params, output (D-384 §2, §4).

ROS-free. Split from machine.py so the transition function stays one readable file.
"""

from __future__ import annotations

import enum
import math
from dataclasses import dataclass, field
from typing import Any, Optional

DIRECTIONS = ("left", "straight", "right")
SIDES = ("left", "right", "opposite")

#: Same name and semantics as line_follow (manager._obstacle_hold): one warning when a
#: static corridor stop has lasted `obstacle_escalate_s`. Fleet re-routes (D-384 §4).
EVENT_OBSTACLE_HOLD = "nav.line_obstacle_hold"
EVENT_STOP_LINE_OVERSHOOT = "nav.road_stop_line_overshoot"
EVENT_TURN_TIMEOUT = "nav.road_turn_timeout"


class BehaviourState(str, enum.Enum):
    LANE_FOLLOW = "LANE_FOLLOW"
    FOLLOW = "FOLLOW"
    HOLD = "HOLD"
    APPROACH = "APPROACH"
    STOP_AT_LINE = "STOP_AT_LINE"
    YIELD_CHECK = "YIELD_CHECK"
    CREEP = "CREEP"
    CROSS = "CROSS"
    FAULT = "FAULT"


LANE_STATES = (BehaviourState.LANE_FOLLOW, BehaviourState.FOLLOW, BehaviourState.HOLD)
JUNCTION_STATES = (BehaviourState.APPROACH, BehaviourState.STOP_AT_LINE,
                   BehaviourState.YIELD_CHECK, BehaviourState.CREEP, BehaviourState.CROSS)


class RoadLevel(str, enum.Enum):
    """road_state degradation level (D-384 §3)."""

    TRACK = "TRACK"
    COAST = "COAST"
    SLOW = "SLOW"
    STOP = "STOP"


@dataclass(frozen=True)
class Stamped:
    """A value and the clock time it was measured. Fresh when 0 <= now - stamp <= t_stale."""

    value: Any
    stamp: float


@dataclass(frozen=True)
class RoadStateSample:
    level: RoadLevel | str
    d_m: Optional[float] = None
    phi_rad: Optional[float] = None


@dataclass(frozen=True)
class CorridorObstacle:
    """An object already inside the path corridor (line_follow clearance band)."""

    range_m: float
    bearing_rad: float
    closing_speed_mps: Optional[float]
    is_moving: bool


@dataclass(frozen=True)
class LeadRobot:
    gap_m: float
    speed_mps: float


@dataclass(frozen=True)
class JunctionAhead:
    distance_m: float
    junction_id: str
    branches: frozenset
    road_width_m: Optional[float] = None


@dataclass(frozen=True)
class JunctionRobot:
    robot_id: str
    arrival_time: float
    relative_side: str
    in_intersection: bool
    intended_direction: Optional[str] = None
    road_width_m: Optional[float] = None


@dataclass(frozen=True)
class TurnProgress:
    travelled_m: float
    arc_length_m: float
    target_lane_acquired: bool


@dataclass(frozen=True)
class BehaviourInputs:
    """Every field None = unknown. `junction`/`lead` Stamped(None) = known absent."""

    now: float
    road_state: Optional[Stamped] = None
    obstacles: Optional[Stamped] = None
    lead: Optional[Stamped] = None
    junction: Optional[Stamped] = None
    stop_line_distance: Optional[Stamped] = None
    route_direction: Optional[Stamped] = None
    pedestrian_at_crosswalk: Optional[Stamped] = None
    other_robots: Optional[Stamped] = None
    fleet_grant: Optional[Stamped] = None
    turn: Optional[Stamped] = None
    #: CORE's live linear cap (line_follow max_linear, safety limits). Same process, no stamp.
    core_speed_cap_mps: Optional[float] = None


@dataclass(frozen=True)
class BehaviourParams:
    """D-384 §4 numbers, scaled to the lane-auto operating point 0.03-0.08 m/s."""

    v_cruise: float = 0.08
    d0: float = 0.25
    tau: float = 1.5
    tau_min: float = 0.8
    #: Default equals LineFollowConfig.obstacle_escalate_s (checked by test).
    obstacle_escalate_s: float = 5.0
    hold_release_margin_m: float = 0.05
    moving_speed_eps: float = 0.01
    slow_factor: float = 0.5
    d_jn: float = 0.6
    v_app: float = 0.05
    d_stop_min: float = 0.15
    d_stop_max: float = 0.22
    t_stop: float = 1.0
    v_creep: float = 0.03
    t_clear: float = 1.0
    v_cross: float = 0.05
    t_tie: float = 0.5
    t_stale: float = 0.3
    arc_timeout_factor: float = 1.3
    #: Junction states need map pose and stop-line distance (D-378 §3.3-3.4). Off until then:
    #: a junction inside d_jn is HOLD `junction_unsupported`.
    junction_logic_enabled: bool = False

    def __post_init__(self) -> None:
        numbers = [value for value in vars(self).values() if not isinstance(value, bool)]
        if not all(math.isfinite(value) and value >= 0 for value in numbers):
            raise ValueError("road-behaviour params must be finite and non-negative")
        if self.tau < self.tau_min or self.tau_min < 0.8:
            raise ValueError("time gap tau must be >= 0.8 s (ISO 15622)")
        if not 0.0 < self.d_stop_min < self.d_stop_max <= self.d_jn:
            raise ValueError("stop window must satisfy 0 < d_stop_min < d_stop_max <= d_jn")
        if not 0.0 < self.v_creep <= self.v_app <= self.v_cruise:
            raise ValueError("speeds must satisfy 0 < v_creep <= v_app <= v_cruise")
        if not 0.0 < self.v_cross <= self.v_cruise:
            raise ValueError("v_cross must be in (0, v_cruise]")
        if not 0.0 < self.slow_factor <= 1.0 or self.t_stale <= 0 or self.arc_timeout_factor < 1:
            raise ValueError("slow_factor in (0, 1], t_stale > 0, arc_timeout_factor >= 1")

    @property
    def corridor_length_m(self) -> float:
        """Corridor length is speed-proportional: the follow gap at cruise, d0 + tau*v."""
        return self.d0 + self.tau * self.v_cruise


@dataclass(frozen=True)
class BehaviourMemory:
    """Everything step() carries between calls. Nothing else is remembered."""

    state: BehaviourState = BehaviourState.LANE_FOLLOW
    entered_at: Optional[float] = None
    arrived_at: Optional[float] = None
    path_choice: Optional[str] = None
    blocked_since: Optional[float] = None
    blocked_reported: bool = False


@dataclass(frozen=True)
class BehaviourOutput:
    """A speed cap CORE min()s into its own caps and a branch. Never a command."""

    state: BehaviourState
    speed_cap_mps: float
    path_choice: Optional[str]
    reason: str
    events: tuple = field(default_factory=tuple)


@dataclass(frozen=True)
class TransitionRow:
    source: BehaviourState
    condition: str
    target: BehaviourState
    speed_cap: str
