"""Local device Action and stop DTOs; schemas.py retains canonical exports."""
from __future__ import annotations

import enum
import math
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .cell_transfer import _ACTION_ID


class DeviceActionState(str, enum.Enum):
    """Durable local Action journal state; independent of Mission goal evidence."""

    PREPARED = "PREPARED"
    SUBMITTING = "SUBMITTING"
    ACCEPTED = "ACCEPTED"
    RUNNING = "RUNNING"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    UNKNOWN = "UNKNOWN"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    HOLD = "HOLD"


class DeviceActionPhaseReceipt(BaseModel):
    """Allowlisted ROS phase snapshot; excludes goal IDs and motion data."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    phase_id: Literal["approach", "grasp", "transfer", "release"]
    ordinal: int = Field(strict=True, ge=0, le=3)
    state: Literal[
        "SUBMITTING", "ACCEPTED", "RUNNING", "CANCEL_REQUESTED",
        "UNKNOWN", "SUCCEEDED", "FAILED", "CANCELED",
    ]
    journal_event_id: int = Field(strict=True, ge=1)
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def _phase_time_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("phase observed_at must include a timezone")
        return value

    @model_validator(mode="after")
    def _phase_identity_matches_ordinal(self):
        expected = ("approach", "grasp", "transfer", "release")[self.ordinal]
        if self.phase_id != expected:
            raise ValueError("phase ID does not match its fixed ordinal")
        return self


class MissionPhaseProgress(BaseModel):
    """Read-only Mission projection of one device phase."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    phase_id: Literal["approach", "grasp", "transfer", "release"]
    ordinal: int = Field(strict=True, ge=0, le=3)
    state: Literal[
        "SUBMITTING", "ACCEPTED", "RUNNING", "CANCEL_REQUESTED",
        "UNKNOWN", "SUCCEEDED", "FAILED", "CANCELED",
    ]
    last_event_id: int = Field(strict=True, ge=1)
    observed_at: datetime


class LocalStopState(str, enum.Enum):
    """Software latch facts only. No value means physical standstill is proven."""

    OPEN = "OPEN"
    REQUESTED = "REQUESTED"
    LOCAL_LATCHED = "LOCAL_LATCHED"
    UNKNOWN = "UNKNOWN"


class StopRequestSource(str, enum.Enum):
    FLEET = "fleet"
    OPERATOR_LOCAL = "operator_local"
    COORDINATOR = "coordinator"  # D-780 2: workcell coordinator peer; reason codes in workcell_barrier


class ResolvedTargetEvidence(BaseModel):
    """Pixel-level object identity evidence tied to one camera observation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    object_id: str = Field(min_length=1, max_length=128)
    observation_id: str = Field(min_length=1, max_length=160)
    frame_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    camera_identity: str = Field(min_length=1, max_length=160)
    optical_frame_id: str = Field(min_length=1, max_length=160)
    calibration_revision: str = Field(min_length=1, max_length=128)
    transform_revision: str = Field(min_length=1, max_length=128)
    capture_time_ns: int = Field(strict=True, gt=0)
    selector_kind: str = Field(pattern=r"^(object_id|inventory_id|label|relation|point|bbox)$")
    image_bbox_xyxy: tuple[float, float, float, float]

    @field_validator("object_id", "observation_id", "camera_identity", "optical_frame_id",
                     "calibration_revision", "transform_revision")
    @classmethod
    def _trimmed_evidence_id(cls, value: str) -> str:
        if value != value.strip() or not value:
            raise ValueError("evidence identities and revisions must be non-empty and trimmed")
        return value

    @field_validator("image_bbox_xyxy", mode="before")
    @classmethod
    def _bbox_numbers(cls, value):
        if (not isinstance(value, (list, tuple)) or len(value) != 4
                or any(isinstance(item, bool) for item in value)):
            raise ValueError("image_bbox_xyxy must contain four finite pixel coordinates")
        try:
            result = tuple(float(item) for item in value)
        except (TypeError, ValueError) as exc:
            raise ValueError("image_bbox_xyxy must contain four finite pixel coordinates") from exc
        if not all(math.isfinite(item) for item in result):
            raise ValueError("image_bbox_xyxy must contain four finite pixel coordinates")
        return result

    @field_validator("image_bbox_xyxy")
    @classmethod
    def _bbox_increasing(cls, value: tuple[float, float, float, float]):
        if value[0] < 0 or value[1] < 0 or value[0] >= value[2] or value[1] >= value[3]:
            raise ValueError("image_bbox_xyxy must be non-negative and increasing")
        return value


class FleetActionGrant(BaseModel):
    """Short-lived Fleet authority to prepare one local, fixed-workcell Action."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mission_id: str = Field(min_length=1, max_length=192)
    step_id: str = Field(min_length=1, max_length=192)
    action_id: str = Field(min_length=1, max_length=192)
    attempt_id: str = Field(min_length=1, max_length=192)
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    workcell_id: str = Field(min_length=1, max_length=96)
    instance_id: str = Field(min_length=1, max_length=96)
    action_kind: str = Field(pattern=r"^PICK_PLACE$")
    source_evidence: ResolvedTargetEvidence
    destination_evidence: ResolvedTargetEvidence
    capability_revision: str = Field(min_length=1, max_length=128)
    config_revision: str = Field(min_length=1, max_length=128)
    observation_revision: str = Field(min_length=1, max_length=128)
    authority_epoch: int = Field(strict=True, ge=0)
    dispatch_generation: int = Field(strict=True, ge=0)
    issued_at: datetime
    expires_at: datetime

    @field_validator("mission_id", "step_id", "action_id", "attempt_id", "workcell_id",
                     "instance_id", "capability_revision", "config_revision", "observation_revision")
    @classmethod
    def _identifier(cls, value: str) -> str:
        if not _ACTION_ID.fullmatch(value):
            raise ValueError("identity must be a trimmed identifier")
        return value

    @model_validator(mode="after")
    def _grant_consistency(self):
        identities = (self.mission_id, self.step_id, self.action_id, self.attempt_id)
        if len(set(identities)) != len(identities):
            raise ValueError("mission, step, action and attempt identifiers must be distinct")
        source, destination = self.source_evidence, self.destination_evidence
        same_observation = (
            source.observation_id == destination.observation_id
            and source.frame_sha256 == destination.frame_sha256
            and source.camera_identity == destination.camera_identity
            and source.optical_frame_id == destination.optical_frame_id
            and source.calibration_revision == destination.calibration_revision
            and source.transform_revision == destination.transform_revision
            and source.capture_time_ns == destination.capture_time_ns
        )
        if not same_observation:
            raise ValueError("source and destination must cite the same observation")
        if source.object_id == destination.object_id:
            raise ValueError("source and destination must identify distinct objects")
        if (self.issued_at.tzinfo is None or self.expires_at.tzinfo is None
                or self.expires_at <= self.issued_at):
            raise ValueError("grant expiry must follow an aware issuance timestamp")
        return self


class DeviceActionReceipt(BaseModel):
    """Local journal receipt; driver success and Mission goal are separate facts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mission_id: str = Field(min_length=1, max_length=192)
    step_id: str = Field(min_length=1, max_length=192)
    action_id: str = Field(min_length=1, max_length=192)
    attempt_id: str = Field(min_length=1, max_length=192)
    workcell_id: str = Field(min_length=1, max_length=96)
    instance_id: str = Field(min_length=1, max_length=96)
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    authority_epoch: int = Field(strict=True, ge=0)
    dispatch_generation: int = Field(strict=True, ge=0)
    state: DeviceActionState
    journal_event_id: int = Field(strict=True, ge=1)
    observed_at: datetime
    driver_goal_id: str | None = Field(default=None, max_length=192)
    reason: str | None = Field(default=None, max_length=256)
    created: bool = False
    phase_summaries: tuple[DeviceActionPhaseReceipt, ...] | None = Field(default=None, max_length=4)
    journal_id: str | None = Field(default=None, max_length=64)  # owner journal identity (C4b 1d)

    @field_validator("mission_id", "step_id", "action_id", "attempt_id", "workcell_id", "instance_id")
    @classmethod
    def _receipt_identifier(cls, value: str) -> str:
        if not _ACTION_ID.fullmatch(value):
            raise ValueError("receipt identity must be a trimmed identifier")
        return value

    @field_validator("observed_at")
    @classmethod
    def _receipt_time_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        return value

    @model_validator(mode="after")
    def _phase_summaries_are_ordered(self):
        if self.phase_summaries is not None:
            ordinals = [phase.ordinal for phase in self.phase_summaries]
            if ordinals != list(range(len(ordinals))):
                raise ValueError("phase summaries must be contiguous and ordered")
            if any(phase.journal_event_id > self.journal_event_id
                   for phase in self.phase_summaries):
                raise ValueError("phase event cannot follow the receipt journal watermark")
        return self


class DeviceActionLookup(BaseModel):
    """Identity pair for attempt-scoped operations, including cancellation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action_id: str = Field(min_length=1, max_length=192)
    attempt_id: str = Field(min_length=1, max_length=192)

    @field_validator("action_id", "attempt_id")
    @classmethod
    def _lookup_identifier(cls, value: str) -> str:
        if not _ACTION_ID.fullmatch(value):
            raise ValueError("lookup identity must be a trimmed identifier")
        return value


class DeviceActionCancelRequest(DeviceActionLookup):
    """Request cancellation of the matching driver goal; ACK is not stop proof."""

    reason: str = Field(min_length=1, max_length=256)
    requested_at: datetime

    @field_validator("requested_at")
    @classmethod
    def _cancel_time_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("requested_at must include a timezone")
        return value


class LocalStopRequest(BaseModel):
    """A software stop request fenced to one workcell and dispatch generation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workcell_id: str = Field(min_length=1, max_length=96)
    instance_id: str = Field(min_length=1, max_length=96)
    authority_epoch: int = Field(strict=True, ge=0)
    dispatch_generation: int = Field(strict=True, ge=0)
    requested_at: datetime
    reason: str = Field(min_length=1, max_length=256)

    @field_validator("workcell_id", "instance_id")
    @classmethod
    def _request_stop_identity(cls, value: str) -> str:
        if not _ACTION_ID.fullmatch(value):
            raise ValueError("stop identity must be a trimmed identifier")
        return value

    @field_validator("requested_at")
    @classmethod
    def _stop_time_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("requested_at must include a timezone")
        return value


class LocalStopQuery(BaseModel):
    """Read the latched software stop state for exactly one workcell instance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workcell_id: str = Field(min_length=1, max_length=96)
    instance_id: str = Field(min_length=1, max_length=96)

    @field_validator("workcell_id", "instance_id")
    @classmethod
    def _query_stop_identity(cls, value: str) -> str:
        if not _ACTION_ID.fullmatch(value):
            raise ValueError("stop query identity must be a trimmed identifier")
        return value


class LocalStopRearmRequest(BaseModel):
    """Fleet-only signal to reopen local dispatch after operator reconciliation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workcell_id: str = Field(min_length=1, max_length=96)
    instance_id: str = Field(min_length=1, max_length=96)
    authority_epoch: int = Field(strict=True, ge=0)
    dispatch_generation: int = Field(strict=True, ge=0)

    @field_validator("workcell_id", "instance_id")
    @classmethod
    def _rearm_stop_identity(cls, value: str) -> str:
        if not _ACTION_ID.fullmatch(value):
            raise ValueError("stop rearm identity must be a trimmed identifier")
        return value


class LocalStopSnapshot(BaseModel):
    """Stop request/latch projection without driver or physical completion claims."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workcell_id: str = Field(min_length=1, max_length=96)
    instance_id: str = Field(min_length=1, max_length=96)
    authority_epoch: int = Field(strict=True, ge=0)
    dispatch_generation: int = Field(strict=True, ge=0)
    state: LocalStopState
    source: StopRequestSource
    observed_at: datetime
    reason: str = Field(min_length=1, max_length=256)

    @field_validator("workcell_id", "instance_id")
    @classmethod
    def _stop_identity(cls, value: str) -> str:
        if not _ACTION_ID.fullmatch(value):
            raise ValueError("stop identity must be a trimmed identifier")
        return value
