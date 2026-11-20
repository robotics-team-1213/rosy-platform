"""Immutable plan shape and structural views over the existing D-18 records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

# PlanBundle/PlanStep live in rosy.contracts.skill; re-exported here so existing imports keep the same objects.
from rosy.contracts.skill import AttemptIdentity, PlanBundle, PlanStep, ReceiptBinding
from rosy.contracts.skill.invocation import _identifier


class _GrantLike(Protocol):
    mission_id: str
    step_id: str
    action_id: str
    attempt_id: str
    workcell_id: str
    instance_id: str
    request_digest: str
    authority_epoch: int
    dispatch_generation: int
    action_kind: str
    capability_revision: str
    config_revision: str
    observation_revision: str


def _revision(value: str, field: str) -> None:
    _identifier(value, field)


@dataclass(frozen=True)
class GrantBinding:
    identity: AttemptIdentity
    action_kind: str
    capability_revision: str
    config_revision: str
    observation_revision: str

    def __post_init__(self) -> None:
        if not isinstance(self.identity, AttemptIdentity):
            raise ValueError("identity must be an AttemptIdentity")
        if self.action_kind != "PICK_PLACE":
            raise ValueError("this mapping supports only the existing PICK_PLACE wire kind")
        for name in ("capability_revision", "config_revision", "observation_revision"):
            _revision(getattr(self, name), name)

    @classmethod
    def from_wire(cls, grant: _GrantLike) -> GrantBinding:
        """Copy identity and revisions only; does not authenticate or authorize a grant."""
        identity = AttemptIdentity(
            mission_id=grant.mission_id,
            step_id=grant.step_id,
            action_id=grant.action_id,
            attempt_id=grant.attempt_id,
            workcell_id=grant.workcell_id,
            instance_id=grant.instance_id,
            request_digest=grant.request_digest,
            authority_epoch=grant.authority_epoch,
            dispatch_generation=grant.dispatch_generation,
        )
        return cls(
            identity=identity,
            action_kind=grant.action_kind,
            capability_revision=grant.capability_revision,
            config_revision=grant.config_revision,
            observation_revision=grant.observation_revision,
        )
