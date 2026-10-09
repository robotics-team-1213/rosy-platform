"""D-546 6: how Fleet answers a robot's "where am I" request (pure).

Order: (a) the overhead-camera map pose, only when it is LOCALIZED and anchored by a fresh
sighting; (b) the D-395 arbiter, when the robot has candidates; (c) a model, which is not
built (`resolve_pose_with_model`); then (d) the operator. The answer is a
`LocalizationDecision` for the existing `POST /localization/decision`; the robot's own
3 s scan check still decides whether it takes it.
"""

from __future__ import annotations

import math
from typing import Mapping, Optional

from pydantic import ValidationError

from core_common.protocol.localization import (Cue, DecisionSource, LocalizationDecision,
                                               MapPose)

#: The sighting that anchors the overhead pose must be this fresh (Rosy Cam runs at ~10 Hz).
OVERHEAD_ANCHOR_FRESH_S = 2.0
#: Seconds the robot may act on a decision after receiving it (D-395 rev. 3).
DECISION_TTL_S = 5.0
#: An open request is answered again after this (the decision ttl plus the 3 s scan check).
RETRY_S = DECISION_TTL_S + 3.0


def is_live(request: Mapping) -> bool:
    """False for a request older than its own `ttl_s` (CORE reports `age_s` on its clock)."""
    try:
        age, ttl = float(request["age_s"]), float(request["ttl_s"])
    except (KeyError, TypeError, ValueError):
        return False
    return math.isfinite(age) and math.isfinite(ttl) and 0.0 <= age <= ttl


def overhead_decision(request: Mapping, pose) -> Optional[LocalizationDecision]:
    """The overhead map pose as a decision, or None when it is not trustworthy.

    `pose` is `fleet.localization.map_pose.MapPose`. Only a LOCALIZED pose whose anchor is a
    fresh sighting counts: DEGRADED and UNKNOWN are not, and neither is any pose that is
    odom alone (a robot's own odom is what a stale-pose request says it cannot trust)."""
    if (pose is None or pose.state != "LOCALIZED" or pose.anchor_age_s is None
            or not 0.0 <= pose.anchor_age_s <= OVERHEAD_ANCHOR_FRESH_S):
        return None
    try:
        return LocalizationDecision(
            request_id=request["request_id"], pose=MapPose(x=pose.x, y=pose.y, yaw=pose.yaw),
            source=DecisionSource.OVERHEAD, cues=[Cue.OVERHEAD], ttl_s=DECISION_TTL_S,
            evidence={"request_reason": request.get("reason"), "anchor_age_s": round(pose.anchor_age_s, 2)})
    except (KeyError, TypeError, ValidationError):
        return None


def resolve_pose_with_model(request: Mapping, state: Optional[Mapping]) -> Optional[LocalizationDecision]:
    """D-546 8 hook: a VLM `pose_hint` on the AI PC. Not implemented; the AI PC owner's
    consent is pending, so this answers nothing and the request goes to the operator."""
    return None
