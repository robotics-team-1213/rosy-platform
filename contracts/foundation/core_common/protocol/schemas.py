"""core_common.protocol.schemas — Fleet 프로토콜 envelope/이벤트 스키마 (P1-19, ADR-D-10).

계약 원천: ROSY-API-REF-001 §6~§9.
- Envelope: 모든 Fleet↔Robot WS 메시지 공통 포장 (API Ref §7.1)
- HelloPayload / WelcomePayload: 핸드셰이크 (API Ref §7.2)
- HeartbeatPayload: 1 Hz 상태 전송 (API Ref §7.3)
- EventMessage: EVT-001 이벤트 모델 (API Ref §8)
- AckPayload: 명령 추적 (API Ref §7.5, PRT-004)

스키마 변경은 추가 전용(Additive)만 허용한다. envelope protocol_version 은 1.0 고정이고
additive 는 문서(API Ref)의 MINOR 로 기록한다(PRT-006, API Ref v1.8 노트).
"""

from __future__ import annotations

import enum
import json
import math
import re
from datetime import datetime, timezone
from typing import Any, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator

from core_common.protocol.evidence import EvidenceState, ValueEvidence
from core_common.protocol.network_peers import DiscoveryScanPayload  # noqa: F401
from core_common.protocol.route_context import RouteContext
from core_common.protocol.line_crosswalk import LineCrosswalkStatus  # noqa: F401 (D-573 6)

from core_common.protocol.access import LoginPairRequest, CameraPairApprovalRequest, SshPairRequest  # noqa: F401
from core_common.protocol.access import ConnectionInfo, SiteRoomsSnapshot  # noqa: F401
from core_common.protocol.localization import LocalizationStatus, OdomPose
from core_common.protocol.cell_goal_evidence import CellGoalEvidenceSubmission  # noqa: F401
from core_common.protocol.cell_app import (  # noqa: F401
    CellAppCompileRequest, CellAppDocumentSaveRequest, CellAppProposalRequest, CellOperatorCheckpoint)
from core_common.protocol.lane_perception import LanePerceptionRequest, LanePerceptionStatus  # noqa: F401
from core_common.protocol.line_arc import LineArcIrCorrection, LineArcStatus  # noqa: F401
from core_common.protocol.trip_lease import TripLeaseFields  # D-541 1: trip_lease, trip_lease_ended
from core_common.protocol.vision_preview_status import VisionPreviewStatus  # noqa: F401
from core_common.protocol.recording_start import RecordingStartRequest  # noqa: F401
from core_common.protocol.overhead_detections import OverheadDetectionsPayload  # noqa: F401
# PowerHealthResponse lives in protocol.power_health and references these shared types.
# Import that response from its module to avoid a schema import cycle.

PROTOCOL_VERSION = "1.0"


class HostStatusEvidence(BaseModel):
    """CORE judgment of one Host Agent network or release status sample."""

    evidence: EvidenceState = EvidenceState.UNAVAILABLE
    observed_at: str | None = None
    age_s: float | None = None
    stale_after_s: float = 15.0
    reason: str = ""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def new_msg_id() -> str:
    return str(uuid4())


# --- 공용 enum (API Ref §4) ----------------------------------------------

class RobotMode(str, enum.Enum):
    IDLE = "IDLE"
    MANUAL = "MANUAL"
    NAVIGATION = "NAVIGATION"
    DOCKING = "DOCKING"
    EMERGENCY = "EMERGENCY"


class NavigationState(str, enum.Enum):
    IDLE = "IDLE"
    PLANNING = "PLANNING"
    NAVIGATING = "NAVIGATING"
    ARRIVED = "ARRIVED"
    CANCELED = "CANCELED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class HealthState(str, enum.Enum):
    OK = "OK"
    WARNING = "WARNING"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


class Severity(str, enum.Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AckStatus(str, enum.Enum):
    ACCEPTED = "ACCEPTED"
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class FleetTaskStatus(str, enum.Enum):
    """Site Fleet task lifecycle; separate from a robot command ACK."""

    REQUESTED = "REQUESTED"
    QUEUED = "QUEUED"
    ACCEPTED = "ACCEPTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    HOLD = "HOLD"
    CANCELED = "CANCELED"
    EXPIRED = "EXPIRED"


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


_ACTION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}$")


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


class CellTransferPose(BaseModel):
    """Finite robot-base pose carried by the fixed-cell transfer grant (D-403)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    x: float = Field(strict=True, allow_inf_nan=False)
    y: float = Field(strict=True, allow_inf_nan=False)
    z: float = Field(strict=True, allow_inf_nan=False)
    yaw: float = Field(strict=True, allow_inf_nan=False)


class CellTransferPayload(BaseModel):
    """One inseparable pick/place pair compiled from an approved Cell Job."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: str = Field(min_length=1, max_length=192)
    recipe_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cell_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    step_index: int = Field(strict=True, ge=0)
    item: Literal["box", "slip_sheet"]
    pallet: str = Field(min_length=1, max_length=96)
    layer: int = Field(strict=True, ge=0)
    frame: Literal["robot_base"]
    home: CellTransferPose
    pick: CellTransferPose
    place: CellTransferPose
    pick_approach_z: float = Field(strict=True, allow_inf_nan=False)
    place_approach_z: float = Field(strict=True, allow_inf_nan=False)
    carry_z: float = Field(strict=True, allow_inf_nan=False)

    @field_validator("job_id", "pallet")
    @classmethod
    def _cell_transfer_identifier(cls, value: str) -> str:
        if not _ACTION_ID.fullmatch(value):
            raise ValueError("Cell Transfer identity must be a trimmed identifier")
        return value

    @model_validator(mode="after")
    def _approaches_are_carried(self):
        if (self.pick_approach_z < self.pick.z or self.place_approach_z < self.place.z
                or self.carry_z < max(self.pick_approach_z, self.place_approach_z)):
            raise ValueError("carry_z must cover both target approach heights")
        return self


class FleetCellTransferGrant(BaseModel):
    """Fleet authority for exactly one ordered Cell Job transfer step."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mission_id: str = Field(min_length=1, max_length=192)
    step_id: str = Field(min_length=1, max_length=192)
    action_id: str = Field(min_length=1, max_length=192)
    attempt_id: str = Field(min_length=1, max_length=192)
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    workcell_id: str = Field(min_length=1, max_length=96)
    instance_id: str = Field(min_length=1, max_length=96)
    action_kind: Literal["CELL_TRANSFER"]
    cell_transfer: CellTransferPayload
    capability_revision: str = Field(min_length=1, max_length=128)
    config_revision: str = Field(min_length=1, max_length=128)
    authority_epoch: int = Field(strict=True, ge=0)
    dispatch_generation: int = Field(strict=True, ge=0)
    issued_at: datetime
    expires_at: datetime

    @field_validator("mission_id", "step_id", "action_id", "attempt_id", "workcell_id",
                     "instance_id", "capability_revision", "config_revision")
    @classmethod
    def _cell_grant_identifier(cls, value: str) -> str:
        if not _ACTION_ID.fullmatch(value):
            raise ValueError("identity must be a trimmed identifier")
        return value

    @model_validator(mode="after")
    def _cell_grant_consistency(self):
        identities = (self.mission_id, self.step_id, self.action_id, self.attempt_id)
        if len(set(identities)) != len(identities):
            raise ValueError("mission, step, action and attempt identities must be distinct")
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


# --- Envelope (API Ref §7.1, PRT-001) ------------------------------------

MISSION_EVENT_DETAIL_MAX_BYTES = 16 * 1024
ER2_FEEDBACK_CONTEXT_MAX_BYTES = 8 * 1024
ER2_TOOL_ARGUMENT_MAX_BYTES = 4 * 1024
ER2_TOOL_RESULT_MAX_BYTES = 4 * 1024
ER2_MAX_FUNCTION_CALLS_PER_TURN = 4
ER2_PROVIDER_DEADLINE_SECONDS = 45
ER2_REPLAY_MAX_STEPS = 8
ER2_REPLAY_MAX_BYTES = 64 * 1024
ER2_RESPONSE_MAX_BYTES = 64 * 1024
ER2_IMAGE_MAX_BYTES = 14 * 1024 * 1024
ER2_MAX_ESTIMATED_TURN_COST_USD = 0.10
ER2_POST_ACTION_OBSERVATION_MAX_AGE_SECONDS = 30


def _bounded_finite_json_size(value: Any) -> int:
    try:
        return len(json.dumps(
            value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise ValueError("value must be finite JSON") from exc


class MissionProgressAxis(BaseModel):
    """One Fleet Mission progress source; this is not physical-state proof."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: str = Field(min_length=1, max_length=64)
    source: str = Field(min_length=1, max_length=96)
    last_event_id: int | None = Field(default=None, strict=True, ge=0)
    observed_at: datetime | None = None
    revision: str | None = Field(default=None, max_length=192)
    freshness: Literal["CURRENT", "FRESH", "STALE", "UNKNOWN"]
    reason: str | None = Field(default=None, max_length=256)
    physical_state: str | None = Field(default=None, max_length=32)


class MissionProgressSnapshot(BaseModel):
    """Snapshot-first Site Fleet status for one Mission and its evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_event_id: int = Field(strict=True, ge=0)
    snapshot_at: datetime
    mission: MissionProgressAxis
    step: MissionProgressAxis
    action: MissionProgressAxis
    goal_evidence: MissionProgressAxis
    stop: MissionProgressAxis
    active_phase: Literal["approach", "grasp", "transfer", "release"] | None = None
    phases: tuple[MissionPhaseProgress, ...] = Field(default=(), max_length=4)


class MissionProgressEvent(BaseModel):
    """One Mission journal entry ordered by Fleet event ID."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: int = Field(strict=True, ge=1)
    event_source: str = Field(min_length=1, max_length=48)
    source_event_id: str = Field(min_length=1, max_length=192)
    mission_id: str = Field(min_length=1, max_length=192)
    step_id: str = Field(min_length=1, max_length=192)
    action_id: str | None = Field(default=None, max_length=192)
    attempt_id: str | None = Field(default=None, max_length=192)
    state: str = Field(min_length=1, max_length=64)
    event_type: str = Field(min_length=1, max_length=64)
    actor_id: str = Field(min_length=1, max_length=96)
    detail: dict[str, Any] = Field(
        description="Finite JSON object up to 16 KiB when serialized as UTF-8",
    )
    created_at: datetime

    @field_validator("detail")
    @classmethod
    def detail_is_bounded_json(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            encoded = json.dumps(
                value, sort_keys=True, separators=(",", ":"),
                ensure_ascii=False, allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("Mission event detail must be finite JSON") from exc
        if len(encoded) > MISSION_EVENT_DETAIL_MAX_BYTES:
            raise ValueError("Mission event detail exceeds the 16 KiB limit")
        return value


class MissionProgressEventPage(BaseModel):
    """A bounded cursor page and the snapshot watermark observed by its query."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_event_id: int = Field(strict=True, ge=0)
    cursor_floor: int = Field(strict=True, ge=0)
    next_after_event_id: int = Field(strict=True, ge=0)
    has_more: bool
    events: list[MissionProgressEvent] = Field(max_length=200)


class MissionProgressReadResponse(BaseModel):
    """Owner-scoped Mission record, bounded recent history, and snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal: dict[str, Any]
    mission: dict[str, Any]
    history: list[MissionProgressEvent] = Field(max_length=50)
    history_truncated: bool
    progress: MissionProgressSnapshot


class MissionCursorResetDetail(BaseModel):
    """Cursor recovery detail when the client cursor is ahead of Fleet."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: Literal["MISSION_CURSOR_RESET_REQUIRED"]
    snapshot_restart_required: Literal[True]
    cursor_floor: int = Field(strict=True, ge=0)
    snapshot: MissionProgressReadResponse


class MissionCursorExpiredDetail(BaseModel):
    """Cursor recovery detail when requested history was pruned."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: Literal["MISSION_CURSOR_EXPIRED"]
    snapshot_restart_required: Literal[True]
    cursor_floor: int = Field(strict=True, ge=0)
    snapshot: MissionProgressReadResponse


class MissionCursorResetError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    detail: MissionCursorResetDetail


class MissionCursorExpiredError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    detail: MissionCursorExpiredDetail


class MissionModelContext(BaseModel):
    """Allowlisted status input scoped to one principal and workcell."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mission_id: str = Field(min_length=1, max_length=192)
    workcell_id: str = Field(min_length=1, max_length=96)
    snapshot_event_id: int = Field(strict=True, ge=0)
    mission_state: str = Field(min_length=1, max_length=64)
    step_state: str = Field(min_length=1, max_length=64)
    action_state: str = Field(min_length=1, max_length=64)
    action_reason: str | None = Field(default=None, max_length=256)
    goal_evidence_state: str = Field(min_length=1, max_length=64)
    goal_evidence_reason: str | None = Field(default=None, max_length=256)
    stop_state: str = Field(min_length=1, max_length=64)
    stop_reason: str | None = Field(default=None, max_length=256)
    active_phase: Literal["approach", "grasp", "transfer", "release"] | None = None
    phases: tuple[MissionPhaseProgress, ...] = Field(default=(), max_length=4)


class MissionFeedbackTurnScope(BaseModel):
    """Trusted server-side identity captured when an ER 2 turn is enqueued."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    principal_id: str = Field(min_length=1, max_length=96)
    workcell_id: str = Field(min_length=1, max_length=96)
    mission_id: str = Field(min_length=1, max_length=192)
    action_id: str = Field(min_length=1, max_length=192)
    attempt_id: str = Field(min_length=1, max_length=192)
    dispatch_generation: int = Field(strict=True, ge=0)
    event_watermark: int = Field(strict=True, ge=0)
    model_policy_revision: str = Field(min_length=1, max_length=96)
    outcome_policy: Literal["STATUS_ONLY", "STATUS_AND_REPLAN"]

    @field_validator("principal_id", "workcell_id", "mission_id", "action_id",
                     "attempt_id", "model_policy_revision")
    @classmethod
    def _trusted_identity_is_trimmed(cls, value: str) -> str:
        if value != value.strip() or any(ord(char) < 32 for char in value):
            raise ValueError("trusted identity must be trimmed and contain no controls")
        return value


class MissionFeedbackContext(BaseModel):
    """Bounded model-facing progress. It describes evidence, never device authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mission_id: str = Field(min_length=1, max_length=192)
    workcell_id: str = Field(min_length=1, max_length=96)
    action_id: str = Field(min_length=1, max_length=192)
    attempt_id: str = Field(min_length=1, max_length=192)
    dispatch_generation: int = Field(strict=True, ge=0)
    stop_generation: int = Field(strict=True, ge=0)
    authority_epoch: int = Field(strict=True, ge=0)
    snapshot_event_id: int = Field(strict=True, ge=0)
    snapshot_at: datetime
    policy_revision: str = Field(min_length=1, max_length=96)
    outcome_policy: Literal["STATUS_ONLY", "STATUS_AND_REPLAN"]
    task_summary: str = Field(min_length=1, max_length=10_000)
    mission_source: str = Field(min_length=1, max_length=96)
    step_source: str = Field(min_length=1, max_length=96)
    action_source: str = Field(min_length=1, max_length=96)
    action_freshness: Literal["CURRENT", "FRESH", "STALE", "UNKNOWN"]
    action_observed_at: datetime | None = None
    goal_evidence_source: str = Field(min_length=1, max_length=96)
    goal_evidence_freshness: Literal["CURRENT", "FRESH", "STALE", "UNKNOWN"]
    goal_evidence_observed_at: datetime | None = None
    stop_source: str = Field(min_length=1, max_length=96)
    stop_freshness: Literal["CURRENT", "FRESH", "STALE", "UNKNOWN"]
    stop_observed_at: datetime | None = None
    mission_state: str = Field(min_length=1, max_length=64)
    step_state: str = Field(min_length=1, max_length=64)
    action_state: str = Field(min_length=1, max_length=64)
    action_reason: str | None = Field(default=None, max_length=256)
    goal_evidence_state: str = Field(min_length=1, max_length=64)
    goal_evidence_reason: str | None = Field(default=None, max_length=256)
    stop_state: str = Field(min_length=1, max_length=64)
    stop_reason: str | None = Field(default=None, max_length=256)
    active_phase: Literal["approach", "grasp", "transfer", "release"] | None = None
    phases: tuple[MissionPhaseProgress, ...] = Field(default=(), max_length=4)

    @model_validator(mode="after")
    def _bounded_and_replan_is_not_stopped(self) -> "MissionFeedbackContext":
        if _bounded_finite_json_size(self.model_dump(mode="json")) > ER2_FEEDBACK_CONTEXT_MAX_BYTES:
            raise ValueError("ER 2 feedback context exceeds the 8 KiB limit")
        if self.outcome_policy == "STATUS_AND_REPLAN" and (
                self.stop_state != "DISPATCH_ENABLED"
                or self.stop_generation != self.dispatch_generation):
            raise ValueError("replan feedback requires a matching enabled stop generation")
        for observed in (self.snapshot_at, self.action_observed_at,
                         self.goal_evidence_observed_at, self.stop_observed_at):
            if observed is not None and (observed.tzinfo is None or observed.utcoffset() is None):
                raise ValueError("feedback observation times must be timezone-aware")
        return self


class ER2ToolResult(BaseModel):
    """Small allowlisted result returned to the provider; never a command receipt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_name: Literal["get_mission_status", "propose_replan", "unsupported"]
    status: Literal["accepted", "rejected", "unavailable"]
    reason_code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z0-9_]+$")
    event_id: int | None = Field(default=None, strict=True, ge=0)
    proposal_id: str | None = Field(default=None, min_length=1, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _bounded_tool_result(self) -> "ER2ToolResult":
        if _bounded_finite_json_size(self.model_dump(mode="json")) > ER2_TOOL_RESULT_MAX_BYTES:
            raise ValueError("ER 2 tool result exceeds the 4 KiB limit")
        return self


class EnvelopeType(str, enum.Enum):
    HELLO = "hello"
    WELCOME = "welcome"
    HEARTBEAT = "heartbeat"
    EVENT = "event"
    COMMAND = "command"
    ACK = "ack"
    ERROR = "error"
    POSE = "pose"  # v1.1: Leader Pose Stream (SWM-003, API Ref §7.8)


class Envelope(BaseModel):
    protocol_version: str = PROTOCOL_VERSION
    msg_id: str = Field(default_factory=new_msg_id)
    # PRT-004 계약 필드(D-170/D-297): top-level Envelope에서 설정·소비하는
    # 런타임 경로는 아직 없다. Site Fleet의 Pinky REST correlation_id는 D-316 범위다.
    correlation_id: Optional[str] = None
    type: EnvelopeType
    ts: str = Field(default_factory=utc_now_iso)
    payload: dict[str, Any] = Field(default_factory=dict)


# --- 핸드셰이크 (API Ref §7.2, PRT-002) -----------------------------------

class HelloPayload(BaseModel):
    robot_id: str
    pairing_token: str
    api_versions: list[str] = ["v1"]
    protocol_version: str = PROTOCOL_VERSION
    device_uid: str = ""
    device_name: str = ""
    model: str = ""
    hardware_serial: str = ""


class WelcomePayload(BaseModel):
    robot_id: str
    fleet_name: str
    long_term_token: Optional[str] = None
    protocol_version: str = PROTOCOL_VERSION
    last_event_seq: int = 0


# --- Heartbeat (API Ref §7.3, PRT-003) ------------------------------------

class Pose(BaseModel):
    x: float = 0.0
    y: float = 0.0
    yaw: float = 0.0


class Velocity(BaseModel):
    linear: float = 0.0
    angular: float = 0.0


class Battery(BaseModel):
    """Raw battery reading. `None` means no reading has arrived yet.

    A missing reading is not 0% (D-82 Law 0): 0% reads as a flat battery, a
    false critical alarm on a robot whose battery source simply is not running.
    """

    percent: Optional[float] = None
    voltage: Optional[float] = None


class BatteryLevel(str, enum.Enum):
    """SAF-005 경보 단계. DEEP만 신설이고 나머지는 기존 임계 그대로다."""

    OK = "ok"
    WARNING = "warning"        # SAF-005 경고 — 기본 20%
    CRITICAL = "critical"      # SAF-005 크리티컬 — 기본 10%
    DEEP = "deep"              # 모터 정지 후 호스트 셧다운 (D-27)


class BatteryStatus(BaseModel):
    """필터를 통과한 배터리 판정. `battery`(생 percent/voltage)와 별개로 붙는다.

    `filtered_voltage`는 저역통과를 거친 값이라 `battery.voltage`와 다를 수 있다.
    전류 센싱이 없으므로 percent는 어디까지나 추정치다.
    """

    level: BatteryLevel = BatteryLevel.OK
    shutdown_armed: bool = False
    filtered_voltage: Optional[float] = None
    charging: bool = False      # 확인된 충전 — DEEP 셧다운을 억제한다 (D-27)


class DockState(str, enum.Enum):
    """도킹 상태 (DNC-003).

    계약이 명시한 DOCK/UNDOCK/CHARGING/DOCKED/DOCK_FAILED 을 다듬은 것이다.
    계약에는 "도크에 있지 않다"는 상태가 없는데 로봇은 대부분의 시간을 거기서
    보내고, 도킹이라는 *행위* 와 그 *결과* 가 한 이름에 섞여 있었다.
    enum 값 추가는 additive 이므로 문서의 MINOR 로 기록된다(PRT-006).
    """

    UNDOCKED = "UNDOCKED"        # 기본 — 도크에 있지 않고 가는 중도 아니다
    DOCKING = "DOCKING"          # 시퀀스 진행 중 (스테이징 주행 포함)
    DOCKED = "DOCKED"            # 접점은 물렸으나 충전은 미확인
    CHARGING = "CHARGING"        # 도크가 전류를 보고하고 전압이 떨어지지 않는다
    UNDOCKING = "UNDOCKING"      # 오도메트리만으로 후진 중
    DOCK_FAILED = "DOCK_FAILED"  # 재시도를 소진했다. 명령 전까지 종착이다


class DockingStatus(BaseModel):
    """상태 스냅샷 additive 필드 (DNC-002)."""

    state: DockState = DockState.UNDOCKED
    dock_id: Optional[str] = None
    phase: Optional[str] = None      # DOCKING 중의 내부 단계
    retries: int = 0
    error: Optional[str] = None


class SafetySummary(BaseModel):
    estop: bool = False


# --- 절전/근접 웨이크 (PWR-001~004, D-24) -----------------------------------

class PowerMode(str, enum.Enum):
    """센서·디스플레이 듀티 사이클 모드. 모터 안전 경로와 무관하다."""

    ACTIVE = "ACTIVE"      # 상시 — 활동 중이거나 깨어 있음
    IDLE = "IDLE"          # 저속 샘플링, LCD 디밍
    STANDBY = "STANDBY"    # 최저 샘플링, LCD 소등


class PresenceState(str, enum.Enum):
    """초음파 근접 판정 결과 (표시 전용 — 장애물 회피는 Nav2 담당)."""

    NONE = "none"
    NEAR = "near"          # near_m 이내 접근
    CONTACT = "contact"    # contact_m 이내 — 접촉으로 간주


class PowerStatus(BaseModel):
    mode: PowerMode = PowerMode.ACTIVE
    presence: PresenceState = PresenceState.NONE
    info_visible: bool = False
    sample_rate_hz: float = 20.0
    last_wake_reason: Optional[str] = None
    idle_seconds: float = 0.0
    lidar_spinning: bool = True     # PWR-005 LiDAR 모터 회전 의도
    lidar_ready: bool = True        # 스핀업 완료 — 스캔을 신뢰할 수 있는가


# --- Swarm (D-20, SWM-001~006, API Ref §7.8) --------------------------------

class SwarmRole(str, enum.Enum):
    NONE = "none"
    LEADER = "leader"
    FOLLOWER = "follower"


class SwarmStatus(BaseModel):
    """상태 스냅샷 additive 필드 (SWM-006)."""

    role: SwarmRole = SwarmRole.NONE
    formation: Optional[str] = None
    active: bool = False


class SwarmReferenceSource(str, enum.Enum):
    """D-21 분산 진화 훅: 참조 pose 스트림 소스 (SWM-007)."""

    FLEET = "fleet"  # 기본 — Fleet 릴레이 (API Ref §7.8)
    PEER = "peer"    # 예약 — 로봇 간 P2P (재검토 트리거 발생 시 구현)


class SwarmFollowParams(BaseModel):
    """POST /api/v1/swarm/follow payload (SWM-002)."""

    target_robot_id: str
    distance: float = 0.5          # 종방향 유지 거리 (m)
    lateral: float = 0.0           # 측방 오프셋 (m)
    max_speed: float = 0.15        # m/s (SAF-004 상한과 별개 추가 제약)
    stream_timeout_ms: int = 1000  # pose 스트림 단절 판정 (SWM-004)
    source: SwarmReferenceSource = SwarmReferenceSource.FLEET  # v1.2 additive
    #: v1 additive. 대형 멤버를 robots.yaml 순서로. 비어 있으면 승계를 하지 않는다.
    members: list[str] = Field(default_factory=list)
    #: D-559 additive. trail = replay the leader's driven path `distance` behind (lateral 0).
    mode: Literal["offset", "trail"] = "offset"


class PoseSample(BaseModel):
    """Leader Pose Stream payload (SWM-003, ≥10 Hz)."""

    robot_id: str
    pose: Pose
    seq: int
    #: v1.7 additive. 어느 맵의 좌표인지 — 없으면 확인하지 않는다(구 릴레이 호환).
    map_id: Optional[str] = None
    frame: Optional[Literal["map", "odom"]] = None  # D-559 additive; trail drops "odom" samples
    #: D-581 additive. "fleet": Fleet re-expressed the leader in `for_robot_id`'s own odom frame
    #: from ceiling-camera anchors (frame "odom"); only that follower's trail accepts it.
    anchor: Optional[Literal["fleet"]] = None
    for_robot_id: Optional[str] = None
    anchor_age_s: Optional[float] = None  # oldest of the two camera anchors behind this sample
    anchor_hold: Optional[str] = None  # set: Fleet has no usable anchor (why); hold, keep the stream


class LineStuckStatus(BaseModel):
    """D-407 open lane stuck: the console answers it by ``stuck_id``."""

    stuck_id: str
    cause: str                            # obstacle_ahead | lane_lost | crosswalk_blocked (D-573 4)
    phase: str                            # ASKING | WAITING_CONSOLE | BACKING | SETTLING
    held_s: float = 0.0
    attempts: int = 0
    max_attempts: int = 0
    local_enabled: bool = False
    ask_remaining_s: Optional[float] = None   # None = console answer only, no local fallback
    last_answer: Optional[str] = None
    decisions: list[str] = Field(default_factory=list)
    # D-573 4 crosswalk_blocked: person_present | look_unknown | sensor_stale | zone_lost
    detail: Optional[str] = None


class LineJunctionStatus(BaseModel):
    """D-494 decision 4 / D-495: the one pending next-junction instruction and its progress."""

    pending_action: Optional[str] = None  # straight | left | right | stop
    place_id: Optional[str] = None
    state: str = "idle"  # API ref line_follow.junction.state list (D-507: approaching, unexpected)
    seq: int = 0
    turn_deg: Optional[float] = None      # D-495: signed bounded turn (left +)
    reason: Optional[str] = None          # D-495: why a maneuver aborted
    pivot_basis: Optional[str] = None     # D-507 4: map | stop_point; D-520: segment_end


class LineFollowStatus(BaseModel):
    """Selected line source and the last fail-closed control decision (D-143)."""

    mode: str = "OFF"
    state: str = "OFF"
    source: Optional[str] = None
    error: Optional[float] = None
    confidence: float = 0.0
    age_s: Optional[float] = None
    linear: float = 0.0
    angular: float = 0.0
    reason: str = "mode_off"
    clearance_m: Optional[float] = None   # D-344 §11: 정면 LiDAR 최소 거리(없으면 None)
    # D-422 몸 기준 정지(path + URDF 몸 기하): 의도 경로를 따라 몸이 닿기까지의 거리,
    # 그 속도의 정지 간격, 가장 가까운 것을 본 센서("lidar" | "ultrasonic"). 아니면 None.
    body_gap_m: Optional[float] = None
    stop_gap_m: Optional[float] = None
    clearance_source: Optional[str] = None
    stuck: Optional[LineStuckStatus] = None  # D-407: open stuck (None = not stuck)
    # D-507 7: D-468 while following -- "contained" (proven) | "unknown" (D-468 idle,
    # following as recovery off). None when D-468 is not tracking or not configured.
    lane_return_containment: Optional[Literal['contained', 'unknown']] = None
    junction: LineJunctionStatus = Field(default_factory=LineJunctionStatus)  # D-494 decision 4
    arc: Optional[LineArcStatus] = None  # D-520 2: the latest arc of this process, if any
    route_context: Optional[RouteContext] = None
    route_context_published_at_s: Optional[float] = None
    # D-573 6: key only while the gate is on (null outside a zone); absent = not watched (D-577 R3).
    crosswalk: Optional[LineCrosswalkStatus] = None
    crosswalk_reported: bool = Field(default=False, exclude=True)

    @model_serializer(mode="wrap")
    def _omit_unreported_crosswalk(self, handler):
        data = handler(self)
        if not self.crosswalk_reported:
            data.pop("crosswalk", None)
        return data


class TrafficPolicyStatus(BaseModel):
    """Semantic road evidence and the latest command-gating verdict."""

    mode: str = "DISABLED"
    state: str = "DISABLED"
    reason: str = "policy_disabled"
    enforced: bool = False
    map_id: Optional[str] = None
    scene_revision: Optional[str] = None
    policy_revision: str = "traffic-policy-v1"
    junction_rule: str = "signal_controlled"
    evidence_revision: int = 0
    age_s: Optional[float] = None
    stop_line_visible: bool = False
    stop_line_distance_m: Optional[float] = None
    crosswalk_visible: bool = False
    signal_colour: Optional[str] = None
    signal_confidence: float = 0.0
    signal_conflict: bool = False
    signal_source_kind: str = "camera"
    signal_head_age_s: Optional[float] = None
    signal_head_frozen: bool = False
    linear_scale: float = 0.0


class VisionEvidenceRecord(BaseModel):
    """Saved operator camera evidence on the robot SD (API Ref v1.39)."""

    id: str
    kind: str
    file_name: str
    mime_type: str
    bytes: int
    sha256: str
    created_at: str
    preview_mode: Optional[Literal['raw', 'annotated']] = None
    pair_group_id: Optional[str] = Field(default=None, pattern=r'^[0-9a-f]{32}$')
    annotation_origin: Optional[Literal['none', 'model_unreviewed']] = None


class VisionEvidenceList(BaseModel):
    records: list[VisionEvidenceRecord] = Field(default_factory=list)


class ActivityOwner(BaseModel):
    """The token that holds an activity lease. `id` is the opaque token id (whoami)."""

    id: str
    role: str = ""
    label: str = ""


class RobotActivity(BaseModel):
    """An attended activity every screen must show (D-321 addendum, v1.68 additive).

    Present only while a calibration session lease is alive; `null` otherwise.
    """

    kind: str = "CALIBRATING"
    session_id: str
    calibration_kind: str
    label: str
    owner: ActivityOwner
    started_at: str
    remaining_s: float


class ShadowRecordRef(BaseModel):
    """Last stop/unavailable shadow verdict. `t` is CORE monotonic seconds."""

    t: float
    reason: str
    source: str


class ShadowEvalStats(BaseModel):
    p50: Optional[float] = None
    p99: Optional[float] = None
    n: int = 0


class SafetyShadowStatus(BaseModel):
    """D-400 shadow counters (v1.71 additive).

    No extra="forbid" on these: an older hub must keep accepting a heartbeat
    from a newer robot that adds a key.
    """

    counts: dict[str, int]
    last_stop: Optional[ShadowRecordRef] = None
    last_unavailable: Optional[ShadowRecordRef] = None
    eval_ms: ShadowEvalStats
    dropped_events: int = 0
    suppressed_events: int = 0
    record_errors: int = 0


class SafetyPolicyStatus(BaseModel):
    """D-400: the safety policy mode CORE runs, and why (v1.71 additive)."""

    mode: str
    mode_effective: str
    mode_error: str = ""
    revision: str = ""
    sources: dict[str, str] = Field(default_factory=dict)
    shadow: Optional[SafetyShadowStatus] = None


class StateSnapshot(TripLeaseFields):
    """로봇 상태 스냅샷 — /ws/state payload와 동일 (API Ref §6.1)."""

    robot_id: str
    online: bool = True
    mode: RobotMode = RobotMode.IDLE
    navigation: NavigationState = NavigationState.IDLE
    map_id: Optional[str] = None
    pose: Pose = Field(default_factory=Pose)
    velocity: Velocity = Field(default_factory=Velocity)
    battery: Battery = Field(default_factory=Battery)
    battery_status: BatteryStatus = Field(default_factory=BatteryStatus)
    docking: DockingStatus = Field(default_factory=DockingStatus)
    safety: SafetySummary = Field(default_factory=SafetySummary)
    swarm: SwarmStatus = Field(default_factory=SwarmStatus)  # v1.1 additive (SWM-006)
    power: PowerStatus = Field(default_factory=PowerStatus)  # v1.4 additive (PWR-001)
    line_follow: LineFollowStatus = Field(default_factory=LineFollowStatus)  # v1.10 additive
    traffic_policy: TrafficPolicyStatus = Field(
        default_factory=TrafficPolicyStatus)  # v1.11 additive
    diagnostics_summary: dict[str, HealthState] = Field(default_factory=dict)
    seq: int = 0
    timestamp: str = Field(default_factory=utc_now_iso)
    #: v1.8 additive. Server-judged freshness per channel. Consumers must ignore
    #: unknown keys (API-002). Client must not recompute thresholds.
    evidence: dict[str, ValueEvidence] = Field(default_factory=dict)
    hitl_requested: bool = False  # ADR-1000: HITL intervention request flag
    capabilities_degraded: list[str] = Field(default_factory=list)  # ADR-1000: Modules in degraded fallback
    #: v1.68 additive (D-321 addendum): attended calibration lease, else null.
    activity: Optional[RobotActivity] = None
    #: v1.69 additive (D-395): state and pose frame; null from robots before D-395.
    localization: Optional[LocalizationStatus] = None
    safety_policy: Optional[SafetyPolicyStatus] = None  # D-400, v1.71 additive
    odom_pose: Optional[OdomPose] = None  # D-494 2, v1.112 additive; null until odometry


class HeartbeatPayload(BaseModel):
    state_snapshot: StateSnapshot


# --- 이벤트 (EVT-001, API Ref §8 이벤트 카탈로그) ---------------------------

class EventMessage(BaseModel):
    seq: int
    event_id: str = Field(default_factory=new_msg_id)
    ts: str = Field(default_factory=utc_now_iso)
    robot_id: str
    type: str                      # 예: "nav.completed" — 카탈로그는 API Ref §8
    severity: Severity = Severity.INFO
    source: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


# --- 명령 추적 (API Ref §7.5, PRT-004) --------------------------------------

class AckPayload(BaseModel):
    status: AckStatus
    error: Optional[str] = None


class UiSurfaceLink(BaseModel):
    id: str
    title: str


class UiPanelDescriptor(BaseModel):
    id: str
    title: str
    slot: str
    order: int
    module: str
    css: list[str]
    action_group: str | None = None
    state: str
    reason: str | None = None


class UiActionGroup(BaseModel):
    id: str
    title: str
    order: int


class UiSurfaceManifest(BaseModel):
    surface: str
    grammar: str
    role: str
    surfaces: list[UiSurfaceLink]
    action_groups: list[UiActionGroup]
    panels: list[UiPanelDescriptor]
    revision: str


# --- D-418 로봇 SSH 접속 (API Ref §5.8, v1.89 additive) ----------------------
#
# administrator 전용 /api/v1/host/ssh/... 의 본문과 응답. CORE 는 이 모양을 검사한
# 뒤 root rosy-ssh-access 에 넘기고, 그 도우미가 같은 규칙을 따로 다시 검사한다.

SSH_LABEL_PATTERN = r"^[a-z0-9][a-z0-9._:-]{0,47}$"
SSH_KEY_TYPES = ("ssh-ed25519", "sk-ssh-ed25519@openssh.com",
                 "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521")
SSH_TIME_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
SSH_MAX_KEYS = 32
_SSH_PUBLIC_KEY = re.compile(r"^(?P<type>[a-z0-9@.-]+) [A-Za-z0-9+/]+={0,2}(?: [!-~ ]{1,100})?$")


class SshKeyAddRequest(BaseModel):
    """POST /host/ssh/keys. 선택 항목·authorized_keys 옵션은 받지 않는다."""

    model_config = ConfigDict(extra="forbid", strict=True)

    public_key: str = Field(min_length=1, max_length=1200)
    label: str = Field(pattern=SSH_LABEL_PATTERN)
    expires_days: int = Field(ge=1, le=365)

    @field_validator("public_key")
    @classmethod
    def _one_allowed_line(cls, value: str) -> str:
        match = _SSH_PUBLIC_KEY.fullmatch(value.strip())
        if match is None or match["type"] not in SSH_KEY_TYPES:
            raise ValueError(f"one OpenSSH public key line of {', '.join(SSH_KEY_TYPES)}")
        return value.strip()


class SshKeyAdded(BaseModel):
    label: str = Field(pattern=SSH_LABEL_PATTERN)
    fingerprint: str = Field(pattern=r"^SHA256:[A-Za-z0-9+/]{43}$")
    expires_at: str = Field(pattern=SSH_TIME_PATTERN)


class SshKeyInfo(BaseModel):
    label: str = Field(pattern=SSH_LABEL_PATTERN)
    type: Literal["ssh-ed25519", "sk-ssh-ed25519@openssh.com",
                  "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521"]
    fingerprint: str = Field(pattern=r"^SHA256:[A-Za-z0-9+/]{43}$")
    added_at: str = Field(pattern=SSH_TIME_PATTERN)
    expires_at: str = Field(pattern=SSH_TIME_PATTERN)
    added_by: str = Field(max_length=128)


class SshKeyList(BaseModel):
    keys: list[SshKeyInfo] = Field(max_length=SSH_MAX_KEYS)


class SshHostKeys(BaseModel):
    hostname: str
    host_keys: list[str]


class LampIdentifyRequest(BaseModel):
    """A short, display-only LED challenge (color None: the robot's own); the face owner may refuse it."""
    model_config = ConfigDict(extra="forbid")
    color: Optional[Literal["blue", "amber"]] = None


class SshPasswordRequest(BaseModel):
    """POST /host/ssh/password. 분 단위, 1..60."""

    model_config = ConfigDict(extra="forbid", strict=True)

    minutes: int = Field(ge=1, le=60)


class SshPasswordIssued(BaseModel):
    user: Literal["rosy"]
    password: str = Field(pattern=r"^rosy-[a-hjkmnp-z2-9]{4}-[a-hjkmnp-z2-9]{4}-[a-hjkmnp-z2-9]{4}$")
    expires_at: str = Field(pattern=SSH_TIME_PATTERN)


class SshPasswordStatus(BaseModel):
    enabled: bool
    expires_at: Optional[str] = Field(default=None, pattern=SSH_TIME_PATTERN)
    #: usermod could not lock the password; sshd refuses it by a drop-in until the retry locks it.
    lock_pending: bool = False
