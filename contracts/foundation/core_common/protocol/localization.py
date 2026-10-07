"""Fleet-assisted localization wire models (D-395 §4, API Ref §6.1 and §7.9).

Robot -> Fleet: `LocalizationStatus` on every state snapshot (the frame flag the
pose never had) and a `CandidateReport` when the state changes. Fleet -> robot:
`LocalizationDecision`, a candidate index or a direct pose with its source,
the cues that carried it, and a lifetime counted from receipt (D-395 rev. 3:
Fleet and robot clocks are not synchronised, so there is no absolute expiry).
All fields are additive (API-002, PRT-006): an old consumer ignores them, and a
snapshot without `localization` is a robot that predates D-395.
"""

from __future__ import annotations

import enum
import re
from typing import Annotated, Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Finite = Annotated[float, Field(allow_inf_nan=False)]
Unit = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
_REQUEST_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
#: `LocalizationStatus.reason` while the robot's 3 s injection check runs (state stays
#: CANDIDATES). Fleet's ladder and CORE's missions wait on it (D-395 S1 re-run R6).
CHECKING = "checking"


class LocState(str, enum.Enum):
    UNKNOWN = "UNKNOWN"
    CANDIDATES = "CANDIDATES"
    LOCALIZED = "LOCALIZED"
    SUSPECT = "SUSPECT"


class PoseFrame(str, enum.Enum):
    MAP = "map"
    ODOM = "odom"


class Cue(str, enum.Enum):
    """What carried a decision. square/paint/peers/slot differ between a pose and
    its 180-degree mirror; last_good and overhead may support but never carry one."""

    SQUARE = "square"
    PAINT = "paint"
    PEERS = "peers"
    SLOT = "slot"
    LAST_GOOD = "last_good"
    OVERHEAD = "overhead"


class DecisionSource(str, enum.Enum):
    CANDIDATE = "candidate"
    OVERHEAD = "overhead"
    HOMING_REF = "homing_ref"
    HUMAN = "human"


def _request_id(value: str) -> str:
    if not _REQUEST_ID.fullmatch(value):
        raise ValueError("request_id must be 1-64 of [A-Za-z0-9_.:-]")
    return value


class LocalizationStatus(BaseModel):
    """Robot-owned state; `pose_frame` says which frame the snapshot `pose` is in."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: LocState
    pose_frame: PoseFrame
    confidence: Unit = 0.0
    reason: Optional[str] = Field(default=None, max_length=64)
    needs_human: bool = False
    request_id: Optional[str] = None
    #: D-395 rev. 4 §5 follow-up (S1 R1): what a LOCALIZED robot's lidar sees that the map
    #: does not explain, base_link, from one full scan; empty outside LOCALIZED. Fleet's
    #: monitor places them from an anchor's map pose to check the other robots.
    unmapped_objects: list[RobotPoint] = Field(default_factory=list, max_length=16)
    #: Robot-clock stamp of that scan. Fleet uses it only to tell one scan from the next
    #: (clocks are not synchronised, rev. 3); it times freshness from first sight.
    objects_stamp: Optional[Finite] = None

    @field_validator("request_id")
    @classmethod
    def _id(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else _request_id(value)


class MapPose(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    x: Finite
    y: Finite
    yaw: Finite


class LocCandidate(MapPose):
    """One base_link pose hypothesis in the map frame (D-395 §4.2)."""

    scan_fit: Unit
    paint_score: Optional[Unit] = None


class RobotPoint(BaseModel):
    """An unmapped lidar object in base_link: forward x, left y, metres."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    x: Finite
    y: Finite


class SquareSighting(BaseModel):
    """Reference-square detector output (D-395 rev. 1 §6), base_link."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bearing_rad: Finite
    range_m: Optional[Annotated[float, Field(gt=0.0, allow_inf_nan=False)]] = None
    confidence: Unit


class CandidateReport(BaseModel):
    """Robot -> Fleet when the localization state changes (D-395 §4.2)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    robot_id: str = Field(min_length=1, max_length=64)
    request_id: str
    candidates: list[LocCandidate] = Field(min_length=1, max_length=8)
    unmapped_objects: list[RobotPoint] = Field(default_factory=list, max_length=16)
    square_sightings: list[SquareSighting] = Field(default_factory=list, max_length=4)
    pickup: bool = False
    stamp: Finite

    @field_validator("request_id")
    @classmethod
    def _id(cls, value: str) -> str:
        return _request_id(value)


class LocalizationDecision(BaseModel):
    """Fleet -> robot: a candidate index or a direct pose, never both (D-395 §4.3)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    candidate_index: Optional[int] = Field(default=None, ge=0, le=7, strict=True)
    pose: Optional[MapPose] = None
    source: DecisionSource
    cues: list[Cue] = Field(default_factory=list, max_length=6)
    evidence: dict[str, Any] = Field(default_factory=dict, max_length=16)
    #: Seconds the robot may act on this after receiving it (D-395 rev. 3).
    ttl_s: Annotated[float, Field(gt=0.0, le=30.0, allow_inf_nan=False)] = 5.0

    @field_validator("request_id")
    @classmethod
    def _id(cls, value: str) -> str:
        return _request_id(value)

    @model_validator(mode="after")
    def _one_target(self) -> "LocalizationDecision":
        if (self.candidate_index is None) == (self.pose is None):
            raise ValueError("exactly one of candidate_index and pose")
        if (self.source is DecisionSource.CANDIDATE) != (self.candidate_index is not None):
            raise ValueError("source 'candidate' goes with candidate_index; other sources carry a pose")
        return self


class OdomPose(BaseModel):
    """D-491 2: pose in the robot's odom frame and when CORE received it.

    ``stamp`` is UTC epoch seconds (wall time, not robot monotonic), the same
    form as a sighting's ``captured_at``, so Fleet can pair the two.
    """

    x: float
    y: float
    yaw: float
    stamp: float
