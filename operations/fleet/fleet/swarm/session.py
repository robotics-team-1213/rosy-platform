"""Decision construction and compatibility exports for the safety-owned formation lifecycle."""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Optional, Sequence

from fleet.formation.assignment import GreedyDistanceAssigner
from fleet.swarm.arming import plan_assignment
from fleet.swarm.api.types import (ArmingFailed, FormationSpec, HoldPolicy, InvalidFormation, MapMismatch, SessionError, SessionState)
from fleet.swarm.api.ports import RobotClient, SlotAssigner
from fleet.swarm.relay import Relay
from fleet.swarm.session_lifecycle import FormationLifecycle, EVENT_TYPES, TRIGGERS

__all__ = [
    "ArmingFailed",
    "EVENT_TYPES",
    "FormationSession",
    "FormationSpec",
    "HoldPolicy",
    "InvalidFormation",
    "MapMismatch",
    "SessionError",
    "SessionState",
    "TRIGGERS",
]


class FormationSession(FormationLifecycle):
    def __init__(self, leader: RobotClient, followers: Sequence[RobotClient],
                 spec: FormationSpec, *,
                 assigner: Optional[SlotAssigner] = None,
                 policy: HoldPolicy = HoldPolicy.HOLD,
                 relay_factory: Callable[..., Relay] = Relay,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 member_order: Optional[Sequence[str]] = None) -> None:
        super().__init__(leader, followers, spec, assigner=assigner, policy=policy,
                         relay_factory=relay_factory, sleep=sleep, member_order=member_order,
                         plan_assignment=plan_assignment, assigner_factory=GreedyDistanceAssigner)
