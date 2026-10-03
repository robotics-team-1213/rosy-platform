"""Server-side freshness judgment (S3). Client must display these strings as-is."""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel


class EvidenceState(str, enum.Enum):
    FRESH = "fresh"
    DELAYED = "delayed"
    DISCONNECTED = "disconnected"
    UNAVAILABLE = "unavailable"


# Existing authorities: readiness default, D-23 speed sample, safety actuation budget.
STALE_POSE_S = 2.0
STALE_VELOCITY_S = 0.5
STALE_BATTERY_S = 5.0
STALE_NAVIGATION_S = 2.0
STALE_SAFETY_S = 0.2
STALE_DOCKING_S = 2.0

CHANNEL_STALE_AFTER_S = {
    "pose": STALE_POSE_S,
    "velocity": STALE_VELOCITY_S,
    "battery": STALE_BATTERY_S,
    "navigation": STALE_NAVIGATION_S,
    "safety": STALE_SAFETY_S,
    "docking": STALE_DOCKING_S,
}


class ValueEvidence(BaseModel):
    received_at: Optional[str] = None
    evidence: EvidenceState = EvidenceState.UNAVAILABLE
    stale_after_s: float = 0.0


def _iso(unix_s: float) -> str:
    return datetime.fromtimestamp(unix_s, tz=timezone.utc).isoformat(timespec="milliseconds")


def judge(
    *,
    has_source: bool,
    received_at: Optional[float],
    now: float,
    stale_after_s: float,
) -> ValueEvidence:
    if not has_source:
        return ValueEvidence(evidence=EvidenceState.UNAVAILABLE, stale_after_s=stale_after_s)
    if received_at is None:
        return ValueEvidence(evidence=EvidenceState.DISCONNECTED, stale_after_s=stale_after_s)
    stamp = _iso(received_at)
    if now - received_at <= stale_after_s:
        return ValueEvidence(
            received_at=stamp, evidence=EvidenceState.FRESH, stale_after_s=stale_after_s
        )
    return ValueEvidence(
        received_at=stamp, evidence=EvidenceState.DELAYED, stale_after_s=stale_after_s
    )
