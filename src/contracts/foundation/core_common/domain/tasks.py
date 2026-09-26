"""Atomic REST actions mapped to CAP-001 flags. Not a workflow engine."""

from __future__ import annotations

import enum

from core_common.capability import Capability, CapabilityError


class TaskKind(str, enum.Enum):
    MOVE = "MOVE"
    NAVIGATE = "NAVIGATE"
    RETURN_HOME = "RETURN_HOME"
    FOLLOW = "FOLLOW"
    DOCK = "DOCK"

    @property
    def capability(self) -> str:
        return {
            TaskKind.MOVE: "teleop",
            TaskKind.NAVIGATE: "navigation.goal_navigation",
            TaskKind.RETURN_HOME: "navigation.return_home",
            TaskKind.FOLLOW: "swarm.follow",
            TaskKind.DOCK: "docking.supported",
        }[self]

    @property
    def concept_id(self) -> str:
        return {
            TaskKind.MOVE: "mobility.move",
            TaskKind.NAVIGATE: "mobility.navigate",
            TaskKind.RETURN_HOME: "mobility.navigate",
            TaskKind.FOLLOW: "mobility.follow",
            TaskKind.DOCK: "mobility.dock",
        }[self]

    def require(self, capability: Capability) -> None:
        try:
            capability.require(self.capability)
        except CapabilityError as exc:
            raise CapabilityError(self.capability, concept_id=self.concept_id) from exc
