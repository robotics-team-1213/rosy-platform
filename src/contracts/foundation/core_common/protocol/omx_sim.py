"""Versioned browser contract for an isolated OMX-AI Gazebo practice host.

These schemas describe simulated commands only. They do not enable a physical
OMX profile or grant authority in the Fleet Action UDS protocol.
"""

from __future__ import annotations

import math
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Wire(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OmxSimTarget(_Wire):
    kind: Literal["omx_sim"] = "omx_sim"
    simulation: Literal[True] = True
    instance_id: str = Field(min_length=1, max_length=64)
    joints: tuple[str, ...] = Field(min_length=1, max_length=8)
    gripper: str = Field(min_length=1, max_length=64)
    camera: bool = False


class OmxSimJog(_Wire):
    instance_id: str = Field(min_length=1, max_length=64)
    seat_id: str = Field(min_length=1, max_length=64)
    request_id: str = Field(min_length=1, max_length=64)
    joint: str = Field(min_length=1, max_length=64)
    delta_rad: float
    duration_s: float = Field(ge=0.1, le=1.0)
    state_sequence: int = Field(ge=0)
    expires_at_ms: int = Field(gt=0)

    @model_validator(mode="after")
    def bounded_delta(self) -> "OmxSimJog":
        if not math.isfinite(self.delta_rad) or not 0 < abs(self.delta_rad) <= 0.05:
            raise ValueError("delta_rad must be finite, nonzero and within 0.05 rad")
        return self


GoalState = Literal[
    "LOCAL_ACCEPTED", "ROS_ACCEPTED", "RUNNING", "SUCCEEDED", "REJECTED",
    "CANCEL_REQUESTED", "CANCELED", "UNKNOWN_HOLD",
]


class OmxSimGoal(_Wire):
    command_id: str = Field(min_length=1, max_length=64)
    state: GoalState
    ros_goal_id: str | None = None
    reason: str = ""

    @model_validator(mode="after")
    def goal_id_matches_stage(self) -> "OmxSimGoal":
        requires_id = self.state in {"ROS_ACCEPTED", "RUNNING", "SUCCEEDED", "CANCELED"}
        forbids_id = self.state in {"LOCAL_ACCEPTED", "REJECTED"}
        if (requires_id and self.ros_goal_id is None) or (forbids_id and self.ros_goal_id is not None):
            raise ValueError("ROS goal identity must match the acceptance stage")
        if self.ros_goal_id is not None:
            try:
                parsed = UUID(self.ros_goal_id)
            except ValueError as exc:
                raise ValueError("ros_goal_id must be UUID") from exc
            if parsed.int == 0 or str(parsed) != self.ros_goal_id:
                raise ValueError("ros_goal_id must be a canonical non-nil UUID")
        return self
