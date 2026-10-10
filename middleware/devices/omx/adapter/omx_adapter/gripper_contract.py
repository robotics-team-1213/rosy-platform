"""Typed, ROS-free gripper readback requirements for a future device adapter.

No sensor implementation or force threshold is provided here. A device adapter
must prove the meaning and revision of its own readback before using this
contract for physical operation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


class GripperReadbackError(ValueError):
    """The gripper readback cannot prove the requested object state."""


@dataclass(frozen=True)
class GripperObservation:
    workcell_id: str
    instance_id: str
    sensor_revision: str
    sequence: int
    received_at: float
    state: str
    object_present: bool | None
    object_id: str | None
    owner_generation: int

    def __post_init__(self) -> None:
        for name in ("workcell_id", "instance_id", "sensor_revision"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ValueError(f"{name} must be a non-empty trimmed string")
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("sequence must be a non-negative integer")
        if type(self.owner_generation) is not int or self.owner_generation < 0:
            raise ValueError("owner_generation must be a non-negative integer")
        if isinstance(self.received_at, bool):
            raise ValueError("received_at must be finite monotonic time")
        try:
            received_at = float(self.received_at)
        except (TypeError, ValueError) as exc:
            raise ValueError("received_at must be finite monotonic time") from exc
        if not math.isfinite(received_at):
            raise ValueError("received_at must be finite monotonic time")
        object.__setattr__(self, "received_at", received_at)
        if self.state not in {"OPEN", "CLOSED", "UNKNOWN"}:
            raise ValueError("state must be OPEN, CLOSED, or UNKNOWN")
        if self.object_present not in {True, False, None}:
            raise ValueError("object_present must be boolean or unknown")
        if self.object_id is not None and (
                not isinstance(self.object_id, str) or not self.object_id.strip()
                or self.object_id != self.object_id.strip()):
            raise ValueError("object_id must be empty or a trimmed string")


@dataclass(frozen=True)
class HoldReceipt:
    workcell_id: str
    instance_id: str
    sensor_revision: str
    sequence: int
    received_at: float
    object_id: str
    owner_generation: int


@dataclass(frozen=True)
class ReleaseReceipt:
    workcell_id: str
    instance_id: str
    sensor_revision: str
    sequence: int
    received_at: float
    object_id: str
    owner_generation: int


def _require_fresh(observation: GripperObservation, *, now: float, max_age_s: float) -> None:
    if isinstance(now, bool) or isinstance(max_age_s, bool):
        raise GripperReadbackError("gripper readback freshness is invalid")
    try:
        current, limit = float(now), float(max_age_s)
    except (TypeError, ValueError) as exc:
        raise GripperReadbackError("gripper readback freshness is invalid") from exc
    age = current - observation.received_at
    if (not math.isfinite(current) or not math.isfinite(limit) or limit <= 0
            or age < 0 or age > limit):
        raise GripperReadbackError("gripper readback is stale or from the future")


def verify_held_object(observation: GripperObservation, *, object_id: str,
                       now: float, max_age_s: float) -> HoldReceipt:
    _require_fresh(observation, now=now, max_age_s=max_age_s)
    if (observation.state != "CLOSED" or observation.object_present is not True
            or observation.object_id != object_id):
        raise GripperReadbackError("gripper readback does not prove the requested object is held")
    return HoldReceipt(
        observation.workcell_id, observation.instance_id, observation.sensor_revision,
        observation.sequence, observation.received_at, object_id, observation.owner_generation,
    )


def verify_released_object(observation: GripperObservation, *, object_id: str,
                           now: float, max_age_s: float) -> ReleaseReceipt:
    _require_fresh(observation, now=now, max_age_s=max_age_s)
    if (observation.state != "OPEN" or observation.object_present is not False
            or observation.object_id is not None):
        raise GripperReadbackError("gripper readback does not prove the object was released")
    return ReleaseReceipt(
        observation.workcell_id, observation.instance_id, observation.sensor_revision,
        observation.sequence, observation.received_at, object_id, observation.owner_generation,
    )
