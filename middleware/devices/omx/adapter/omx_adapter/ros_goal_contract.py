"""ROS goal identity and event snapshots without ROS runtime dependencies."""

from __future__ import annotations

import math
from array import array
from dataclasses import dataclass
from typing import Literal
from uuid import UUID


RosGoalEventKind = Literal[
    "GOAL_ACCEPTED", "GOAL_REJECTED", "GOAL_ACCEPTANCE_UNKNOWN", "RUNNING_FEEDBACK",
    "CANCEL_ACK", "TERMINAL_RESULT", "TERMINAL_UNKNOWN",
]
_KINDS = frozenset({
    "GOAL_ACCEPTED", "GOAL_REJECTED", "GOAL_ACCEPTANCE_UNKNOWN", "RUNNING_FEEDBACK",
    "CANCEL_ACK", "TERMINAL_RESULT", "TERMINAL_UNKNOWN",
})
_GOAL_BOUND_KINDS = frozenset({
    "GOAL_ACCEPTED", "RUNNING_FEEDBACK", "CANCEL_ACK", "TERMINAL_RESULT", "TERMINAL_UNKNOWN",
})


def canonical_ros_goal_id(value: object) -> str:
    """Convert a ROS 16-byte UUID or UUID string to canonical lowercase form."""
    try:
        if isinstance(value, str):
            parsed = UUID(value)
        elif isinstance(value, (bytes, bytearray, tuple, list, array)):
            raw = bytes(value)
        else:
            view = memoryview(value)
            if view.ndim != 1 or view.itemsize != 1 or view.format not in {"B", "b"}:
                raise ValueError("ROS goal UUID must be a one-dimensional byte array")
            raw = view.tobytes()
        if not isinstance(value, str):
            if len(raw) != 16:
                raise ValueError("ROS goal UUID must contain exactly 16 bytes")
            parsed = UUID(bytes=raw)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("ROS goal UUID is invalid") from exc
    if parsed.int == 0:
        raise ValueError("ROS goal UUID must not be nil")
    return str(parsed)


@dataclass(frozen=True)
class RosGoalEvent:
    """A bounded callback fact correlated to one command and semantic phase."""

    kind: RosGoalEventKind
    command_id: str
    phase_id: str | None
    goal_id: str | None
    observed_at_monotonic_s: float
    sequence: int
    status: int | None = None
    result_code: int | None = None
    feedback_sequence: int | None = None
    cancel_acknowledged: bool | None = None

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise ValueError("unsupported ROS goal event kind")
        for field_name in ("command_id",):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"{field_name} must be non-empty trimmed text")
        if self.phase_id is not None and (
            not isinstance(self.phase_id, str) or not self.phase_id or self.phase_id != self.phase_id.strip()
        ):
            raise ValueError("phase_id must be non-empty trimmed text when present")
        if self.kind in _GOAL_BOUND_KINDS:
            if self.goal_id is None or canonical_ros_goal_id(self.goal_id) != self.goal_id:
                raise ValueError("goal_id must be a canonical accepted ROS UUID")
        elif self.goal_id is not None:
            raise ValueError("goal_id must be absent when the server did not accept the goal")
        if isinstance(self.observed_at_monotonic_s, bool):
            raise ValueError("observed_at_monotonic_s must be finite and non-negative")
        try:
            observed_at = float(self.observed_at_monotonic_s)
        except (TypeError, ValueError) as exc:
            raise ValueError("observed_at_monotonic_s must be finite and non-negative") from exc
        if not math.isfinite(observed_at) or observed_at < 0:
            raise ValueError("observed_at_monotonic_s must be finite and non-negative")
        object.__setattr__(self, "observed_at_monotonic_s", observed_at)
        if type(self.sequence) is not int or self.sequence <= 0:
            raise ValueError("sequence must be a positive integer")
        if self.kind == "RUNNING_FEEDBACK":
            if type(self.feedback_sequence) is not int or self.feedback_sequence <= 0:
                raise ValueError("feedback_sequence must be positive for running feedback")
        elif self.feedback_sequence is not None:
            raise ValueError("feedback_sequence is only valid for running feedback")
        if self.kind == "CANCEL_ACK":
            if type(self.cancel_acknowledged) is not bool:
                raise ValueError("cancel_acknowledged must be boolean for cancel ACK")
        elif self.cancel_acknowledged is not None:
            raise ValueError("cancel_acknowledged is only valid for cancel ACK")
        if self.kind == "TERMINAL_RESULT":
            if type(self.status) is not int or self.status < 0:
                raise ValueError("status must be a non-negative integer for terminal result")
        elif self.status is not None:
            raise ValueError("status is only valid for terminal events")
        if self.kind not in {"TERMINAL_RESULT", "TERMINAL_UNKNOWN"} and self.result_code is not None:
            raise ValueError("result_code is only valid for terminal events")
        if self.result_code is not None and type(self.result_code) is not int:
            raise ValueError("result_code must be an integer")
