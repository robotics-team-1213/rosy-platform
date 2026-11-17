"""Traffic policy domain models, evidence contracts, and configuration validation."""

from __future__ import annotations

from dataclasses import dataclass
import enum
import math
from typing import Optional

#: D-735: slowest APPROACH scale shared by moving axes; stationary turns keep angular speed.
#: D-422 still reads it for the conservative legacy tighter-arc family.
APPROACH_MIN_SCALE = 0.15


class TrafficPolicyMode(str, enum.Enum):
    DISABLED = "DISABLED"
    MONITOR_ONLY = "MONITOR_ONLY"
    ENFORCED = "ENFORCED"


def _finite(value) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


@dataclass(frozen=True)
class RoadEvidence:
    source: str
    stamp: float
    map_id: str
    scene_revision: str
    stop_line_visible: bool = False
    stop_line_distance_m: Optional[float] = None
    stop_line_confidence: float = 0.0
    crosswalk_visible: bool = False
    signal_colour: Optional[str] = None
    signal_confidence: float = 0.0
    signal_conflict: bool = False
    # Scene context (D-162) is observability only: it never changes a
    # verdict. All three fields arrive together or not at all.
    context_id: Optional[str] = None
    context_confidence: Optional[float] = None
    context_profile_revision: Optional[str] = None

    def __post_init__(self) -> None:
        if self.source != "CAMERA_ROAD":
            raise ValueError("unsupported road evidence source")
        if not _finite(self.stamp):
            raise ValueError("road evidence stamp must be finite")
        if not self.map_id or not self.scene_revision:
            raise ValueError("road evidence map and scene are required")
        for name, value in (
            ("stop_line_confidence", self.stop_line_confidence),
            ("signal_confidence", self.signal_confidence),
        ):
            if not _finite(value) or not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
        if self.stop_line_distance_m is not None:
            if (
                not _finite(self.stop_line_distance_m)
                or float(self.stop_line_distance_m) < 0.0
            ):
                raise ValueError("stop line distance must be non-negative")
            if not self.stop_line_visible:
                raise ValueError("invisible stop line cannot carry distance")
        if self.signal_colour not in (None, "RED", "YELLOW", "GREEN"):
            raise ValueError("unsupported traffic signal colour")
        provided = (
            self.context_id is not None,
            self.context_confidence is not None,
            self.context_profile_revision is not None,
        )
        if any(provided) and not all(provided):
            raise ValueError(
                "road evidence context requires id, confidence and revision"
            )
        if self.context_id is not None:
            if (
                not self.context_id.strip()
                or not self.context_profile_revision.strip()
            ):
                raise ValueError("road evidence context fields are required")
            if (
                not _finite(self.context_confidence)
                or not 0.0 <= float(self.context_confidence) <= 1.0
            ):
                raise ValueError(
                    "road evidence context confidence must be in [0, 1]"
                )


@dataclass(frozen=True)
class SignalHeadEvidence:
    """Measured-light signal evidence from the read-only observer service.

    D-337: the robot's second signal source is the observed light only —
    never the ESP32 contact claim (`/status`). `red`/`yellow`/`green` are
    the operator-mapped lamp booleans; exactly one lit lamp is a colour,
    zero or plural is indeterminate (a dark head never licenses entry).
    """

    stamp: float
    map_id: str
    scene_revision: str
    red: bool = False
    yellow: bool = False
    green: bool = False
    confidence: float = 0.0
    frozen: bool = False
    stable: bool = True

    def __post_init__(self) -> None:
        if not _finite(self.stamp):
            raise ValueError("signal head evidence stamp must be finite")
        if not self.map_id or not self.scene_revision:
            raise ValueError(
                "signal head evidence map and scene are required"
            )
        if not _finite(self.confidence) or not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("signal head confidence must be in [0, 1]")

    @property
    def colour(self) -> Optional[str]:
        """Single lit lamp colour; zero or plural lit lamps is no claim."""
        lit = [
            colour
            for colour, on in (
                ("RED", self.red),
                ("YELLOW", self.yellow),
                ("GREEN", self.green),
            )
            if on
        ]
        return lit[0] if len(lit) == 1 else None


@dataclass(frozen=True)
class TrafficPolicyConfig:
    mode: TrafficPolicyMode = TrafficPolicyMode.DISABLED
    map_id: str = ""
    scene_revision: str = ""
    policy_revision: str = "traffic-policy-v1"
    #: Operator declaration, not a camera absence verdict: `stop_and_go`
    #: means this scene's stop line is an unsignalized junction where a
    #: complete stop plus dwell licenses entry (reason unsignalized_proceed).
    junction_rule: str = "signal_controlled"
    approach_distance_m: float = 0.35
    stop_distance_m: float = 0.12
    stop_dwell_s: float = 0.5
    stale_after_s: float = 0.4
    min_confidence: float = 0.5
    proceed_speed_scale: float = 0.5

    def __post_init__(self) -> None:
        mode = (
            self.mode
            if isinstance(self.mode, TrafficPolicyMode)
            else TrafficPolicyMode(self.mode)
        )
        object.__setattr__(self, "mode", mode)
        values = (
            self.approach_distance_m,
            self.stop_distance_m,
            self.stop_dwell_s,
            self.stale_after_s,
            self.min_confidence,
            self.proceed_speed_scale,
        )
        if not all(_finite(value) for value in values):
            raise ValueError("traffic policy config must be finite")
        if not 0.0 < self.stop_distance_m < self.approach_distance_m:
            raise ValueError(
                "traffic stop distance must be below approach distance"
            )
        if self.stop_dwell_s <= 0.0 or self.stale_after_s <= 0.0:
            raise ValueError("traffic policy timeouts must be positive")
        if not 0.0 < self.min_confidence <= 1.0:
            raise ValueError("traffic policy min_confidence must be in (0, 1]")
        if not 0.0 < self.proceed_speed_scale <= 1.0:
            raise ValueError("proceed_speed_scale must be in (0, 1]")
        if not self.policy_revision:
            raise ValueError("traffic policy revision is required")
        if self.junction_rule not in ("signal_controlled", "stop_and_go"):
            raise ValueError("unsupported junction rule")
        if mode is not TrafficPolicyMode.DISABLED:
            if not self.map_id or not self.scene_revision:
                raise ValueError(
                    "active traffic policy requires map and scene"
                )


@dataclass(frozen=True)
class TrafficDecision:
    linear: float
    angular: float
    generation: int
    evidence_revision: int
    mode: TrafficPolicyMode
    policy_revision: str


__all__ = [
    "APPROACH_MIN_SCALE",
    "RoadEvidence",
    "SignalHeadEvidence",
    "TrafficDecision",
    "TrafficPolicyConfig",
    "TrafficPolicyMode",
    "_finite",
]
