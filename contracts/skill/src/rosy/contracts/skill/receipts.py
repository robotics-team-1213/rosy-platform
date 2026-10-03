"""Portable receipt correlation without device or ROS imports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Protocol

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class _ReceiptLike(Protocol):
    mission_id: str
    step_id: str
    action_id: str
    attempt_id: str
    workcell_id: str
    instance_id: str
    request_digest: str
    authority_epoch: int
    dispatch_generation: int
    state: object
    journal_event_id: int
    observed_at: datetime


def _identifier(value: str, field: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be a non-empty trimmed string")


@dataclass(frozen=True)
class AttemptIdentity:
    """Identity shared by an authorized Action and its local receipt."""

    mission_id: str
    step_id: str
    action_id: str
    attempt_id: str
    workcell_id: str
    instance_id: str
    request_digest: str
    authority_epoch: int
    dispatch_generation: int

    def __post_init__(self) -> None:
        names = ("mission_id", "step_id", "action_id", "attempt_id",
                 "workcell_id", "instance_id")
        for name in names:
            _identifier(getattr(self, name), name)
        if len({getattr(self, name) for name in names[:4]}) != 4:
            raise ValueError(
                "mission, step, action and attempt IDs must be distinct",
            )
        if (not isinstance(self.request_digest, str)
                or not _SHA256.fullmatch(self.request_digest)):
            raise ValueError(
                "request_digest must be a lowercase SHA-256 digest",
            )
        for name in ("authority_epoch", "dispatch_generation"):
            value = getattr(self, name)
            if (isinstance(value, bool) or not isinstance(value, int)
                    or value < 0):
                raise ValueError(f"{name} must be a non-negative integer")


@dataclass(frozen=True)
class ReceiptBinding:
    """Correlated local journal view, not physical goal or task evidence."""

    identity: AttemptIdentity
    state: str
    journal_event_id: int
    observed_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.identity, AttemptIdentity):
            raise ValueError("identity must be an AttemptIdentity")
        _identifier(self.state, "state")
        if (isinstance(self.journal_event_id, bool)
                or not isinstance(self.journal_event_id, int)
                or self.journal_event_id < 1):
            raise ValueError("journal_event_id must be a positive integer")
        if (not isinstance(self.observed_at, datetime)
                or self.observed_at.tzinfo is None
                or self.observed_at.utcoffset() is None):
            raise ValueError("observed_at must include a timezone")

    @classmethod
    def from_wire(cls, receipt: _ReceiptLike) -> ReceiptBinding:
        """Copy identity and state, not physical completion evidence."""
        identity = AttemptIdentity(
            mission_id=receipt.mission_id,
            step_id=receipt.step_id,
            action_id=receipt.action_id,
            attempt_id=receipt.attempt_id,
            workcell_id=receipt.workcell_id,
            instance_id=receipt.instance_id,
            request_digest=receipt.request_digest,
            authority_epoch=receipt.authority_epoch,
            dispatch_generation=receipt.dispatch_generation,
        )
        state = (receipt.state.value if hasattr(receipt.state, "value")
                 else receipt.state)
        return cls(
            identity=identity,
            state=state,
            journal_event_id=receipt.journal_event_id,
            observed_at=receipt.observed_at,
        )
