"""Line-follow modes and the one observation record (D-143, D-344, D-364); ROS-free.

Split out of model.py (D-766 size limit); model.py re-exports every name, so
``core_features.line_follow.model`` imports keep working.
"""

from __future__ import annotations

import enum
import math
from dataclasses import dataclass
from typing import Optional

from core_common.protocol.lane_containment import LaneContainmentEvidence


class LineFollowMode(str, enum.Enum):
    OFF = "OFF"
    IR_LINE = "IR_LINE"
    CAMERA_LINE = "CAMERA_LINE"


@dataclass(frozen=True)
class LineObservation:
    source: LineFollowMode
    stamp: float
    visible: bool
    error: Optional[float]
    confidence: float
    ir_calibrated: bool = False
    calibration_revision: Optional[str] = None
    # D-364 §3: camera evidence computed on an estimated (NOMINAL) floor model.
    ground: Optional[str] = None
    quality_reason: Optional[str] = None
    containment: Optional[LaneContainmentEvidence] = None

    def __post_init__(self) -> None:
        if self.containment is not None and (
                self.source is not LineFollowMode.CAMERA_LINE or
                not isinstance(self.containment, LaneContainmentEvidence) or
                abs(self.containment.stamp-self.stamp) > .000001):
            raise ValueError("containment must match original camera image stamp")
        if self.containment is not None and (
                (self.containment.ground_source == "NOMINAL") != (self.ground == "NOMINAL")):
            raise ValueError("containment and observation ground provenance must agree")
        if self.quality_reason is not None and (self.source is not LineFollowMode.CAMERA_LINE
                or self.quality_reason not in ('low_light', 'overexposed', 'odom_side_conflict')
                or self.visible or self.confidence != 0):
            raise ValueError('invalid camera quality requires invisible evidence with zero confidence')
        if self.ground is not None and (self.source is not LineFollowMode.CAMERA_LINE
                                        or self.ground != "NOMINAL"):
            raise ValueError("only camera evidence may carry the NOMINAL ground label")
        if self.source is LineFollowMode.OFF:
            raise ValueError("OFF cannot be an observation source")
        if not _finite(self.stamp):
            raise ValueError("observation stamp must be finite")
        if not _finite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        if self.visible:
            if not _finite(self.error) or not -1.0 <= float(self.error) <= 1.0:
                raise ValueError("visible observation error must be in [-1, 1]")
        elif self.error is not None:
            raise ValueError("invisible observation cannot carry an error")
        if type(self.ir_calibrated) is not bool:
            raise ValueError("IR calibration marker must be a boolean")
        if self.ir_calibrated and (not isinstance(self.calibration_revision, str)
                                   or not self.calibration_revision.strip()):
            raise ValueError("calibrated IR evidence requires a revision")


def _finite(value) -> bool:
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(float(value)))
