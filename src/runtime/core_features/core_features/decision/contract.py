"""Decision contract. A result is an allowed action id, never a velocity."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping


class DecisionStatus(str, Enum):
    DECIDED = "DECIDED"
    ABSTAINED = "ABSTAINED"
    TIMEOUT = "TIMEOUT"
    INVALID = "INVALID"
    ERROR = "ERROR"
    STALE_INPUT = "STALE_INPUT"
    NO_PROVIDER = "NO_PROVIDER"
    POLICY_REJECTED = "POLICY_REJECTED"


@dataclass(frozen=True)
class ActionOption:
    id: str
    motion: bool = False


@dataclass(frozen=True)
class DecisionRequest:
    decision_id: str
    decision_type: str
    allowed_actions: tuple[ActionOption, ...]
    snapshot_age_ms: int
    max_age_ms: int
    deadline_ms: int
    elapsed_ms: int
    mode: str
    safety_state: str
    context: Mapping[str, object]
    fallback_action: str


@dataclass(frozen=True)
class DecisionResult:
    decision_id: str
    status: DecisionStatus
    selected_action: str | None
    fallback_action: str | None
    reason_code: str
