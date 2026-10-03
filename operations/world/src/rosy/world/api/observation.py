"""Immutable observation references; validity does not assert physical truth."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class SnapshotValidity(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"


def _identifier(value: str, field: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be a non-empty trimmed string")


@dataclass(frozen=True)
class ObservationSnapshot:
    """A pointer to sourced evidence with its frame and calibration revision."""

    snapshot_id: str
    source: str
    captured_at_ns: int
    received_at: datetime
    frame_id: str
    calibration_revision: str
    evidence_refs: tuple[str, ...]
    validity: SnapshotValidity
    transform_revision: str | None = None

    def __post_init__(self) -> None:
        for name in ("snapshot_id", "source", "frame_id", "calibration_revision"):
            _identifier(getattr(self, name), name)
        if isinstance(self.captured_at_ns, bool) or not isinstance(self.captured_at_ns, int):
            raise ValueError("captured_at_ns must be an integer nanosecond timestamp")
        if self.captured_at_ns <= 0:
            raise ValueError("captured_at_ns must be positive")
        if (not isinstance(self.received_at, datetime) or self.received_at.tzinfo is None
                or self.received_at.utcoffset() is None):
            raise ValueError("received_at must include a timezone")
        if not isinstance(self.evidence_refs, tuple) or not self.evidence_refs:
            raise ValueError("evidence_refs must be a non-empty tuple")
        for reference in self.evidence_refs:
            _identifier(reference, "evidence reference")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("evidence_refs must be unique")
        if not isinstance(self.validity, SnapshotValidity):
            raise ValueError("validity must be a SnapshotValidity value")
        if self.transform_revision is not None:
            _identifier(self.transform_revision, "transform_revision")
