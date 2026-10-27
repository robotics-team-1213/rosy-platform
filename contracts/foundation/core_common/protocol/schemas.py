"""Fleet schemas and canonical exports (ROSY-API-REF-001, D-10, D-664).

Envelope/hello/heartbeat/ACK: API Ref §7; events: §8.
Additive schema changes bump the API Ref MINOR; envelope protocol_version 은 1.0 (PRT-006).
"""

from __future__ import annotations

from .device_actions import (  # noqa: F401
    DeviceActionState, DeviceActionPhaseReceipt, MissionPhaseProgress, LocalStopState,
    StopRequestSource, ResolvedTargetEvidence, FleetActionGrant, DeviceActionReceipt,
    DeviceActionLookup, DeviceActionCancelRequest, LocalStopRequest, LocalStopQuery,
    LocalStopRearmRequest, LocalStopSnapshot)
from .arm_transfer import ArmTransferCapability, ArmTransferPayload, FleetArmTransferGrant  # noqa: F401
from .arm_transfer_jobs import (  # noqa: F401
    ArmTransferRequest, ArmTransferRequestKey, ArmTransferJobCreate, ArmTransferJobAdmit,
    ArmTransferJobSnapshot, ArmTransferJobResponse)
from .wire_status import RobotMode, NavigationState, HealthState, Severity, AckStatus
from .arm_transfer_observations import (  # noqa: F401
    ArmObservationPose, ArmObservationBounds, ArmLinkObservation, ArmOwnerObservation,
    ArmTransferObservation, ArmTransferObservationRequest, ArmTransferOwnerContext,
    ArmTransferObservationContext, ArmTransferObservationContextResponse, ArmTransferPhysicalReceipt,
    ArmTransferPhysicalReceiptResponse, ArmTransferObservationReply, ArmTransferCancelRequest)
from .arm_transfer_recovery import (  # noqa: F401
    ArmTransferRecoveryCreate, ArmTransferRecoveryApprove, ArmTransferRecoveryRequestSnapshot,
    ArmTransferRecoveryRequestResponse, ArmTransferRecoveryPreview, ArmTransferRecoveryPreviewResponse,
    ArmTransferRecoveryOwnerContext, ArmTransferRecoveryEvidenceContext, ArmTransferRecoveryContext,
    ArmTransferRecoveryContextResponse, ArmTransferRecoveryObservationRequest,
    ArmTransferRecoveryObservationReply, ArmTransferExecutionReview)

from .arm_transfer_preflight import (  # noqa: F401
    ArmTransferCheckRequest, ArmTransferCheckResult, ArmTransferCheckResponse, ArmTransferCheckRejection)
from .account_access import AccountAccess, AccountGrant  # noqa: F401
from .monitoring import FleetLinkObservation, FleetMonitoringRead  # noqa: F401
from .trip_jobs import (TripJobRequest, TripJobStep, TripJobSnapshot, TripJobStepSnapshot,
                        TripJobReadResponse, TripRequestKey)  # noqa: F401
from .policy_admission import (  # noqa: F401
    POLICY_ADMISSION_PRINCIPAL, PolicyAdmissionAuditEntry, PolicyAdmissionAuditResponse,
    PolicyAdmissionReadResponse, PolicyAdmissionScope, PolicyAdmissionStatus,
    PolicyAdmissionToggleRequest,
)
from .control_units import (  # noqa: F401
    ControlGoal, ControlNavigationCandidate, ControlWorkRequest, ControlIngressRequest,
    ControlApproveRequest, ControlDelegationState, ControlDelegationSnapshot, ControlUnitReply,
)
from .integrated_control import (  # noqa: F401
    ControlDispatchFence, ControlMapRef, ControlUnitSummary, ControlOverview,
    ControlRobotPose, ControlRobotInfo, ControlTaskInfo, ControlUnitDetail,
    ControlMapPoint, ControlMapPlace, ControlMapLane, ControlMapSnapshot,
    ControlStopRequest, ControlStopIngress, ControlStopUnitResult, ControlStopSnapshot,
    ControlStopReconcile, ControlStopReference, ControlStopHistory,
)
from .navigation_cancel import NAVIGATION_ADMISSION_FENCE_VERSION, ScopedNavigationCancelRequest  # noqa: F401
from .lamp import LampIdentifyRequest  # noqa: F401
from .media_grants import MediaGrantRequest, MediaGrantResponse, MediaSourceGrantRequest  # noqa: F401
from .channel_requests import (  # noqa: F401
    DiscordRequestEnvelope, ChannelRequestReceipt, ChannelRequestList, ChannelNavigationCandidate,
    ChannelReviewRequest, ChannelSubmitRequest, ChannelTaskLinkRequest, ChannelWorkflowView,
    ChannelWorkPrepareRequest, ChannelMissionPrepareRequest, ChannelCellPrepareRequest, ChannelWorkAdmitRequest,
    ChannelIncidentReference, ChannelIncidentClaimRequest,
)

import enum
import json
from datetime import datetime, timezone
from typing import Any, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator

from core_common.protocol.docking import DockState, DockingStatus  # noqa: F401
from core_common.protocol.station_charging import (  # noqa: F401 (D-772)
    StationPoseRecord, StationPoseAck, StationObservation, MapPoseEvidence, StationTargetBinding, SeatingEvidence,
    ChargeCompletionEvidence, BatteryEnergyEvidence, StationTargetStatus, ChargePolicyProfile, ChargeDecision,
    ChargeSessionStatus, StationMotionCommand, StationReturnPermit, StationDeparturePermit, StationDepartureReceipt,
)
from core_common.protocol.power import (  # noqa: F401 (PWR-001~005, D-440)
    DevicePowerState, PowerMode, PowerStatus, PresenceState)
from core_common.protocol.swarm import SwarmRole, SwarmStatus, SwarmReferenceSource, SwarmFollowParams  # noqa: F401
from core_common.protocol.evidence import EvidenceState, HostStatusEvidence, ValueEvidence
from core_common.protocol.line_stuck import LineStuckPrecondition  # noqa: F401
from core_common.protocol.work import FleetTaskStatus, FleetWorkDecisionRequest, FleetWorkOverview, FleetWorkSummary, FleetWorkWait  # noqa: F401
from core_common.protocol.fleet_judgment import FleetJudgmentReceipt, FleetObservedClosure  # noqa: F401
from core_common.protocol.network_peers import DiscoveryScanPayload  # noqa: F401
from core_common.protocol.route_context import RouteContext
from core_common.protocol.line_crosswalk import LineCrosswalkStatus  # noqa: F401 (D-573 6)
from core_common.protocol.access import LoginPairRequest, CameraPairApprovalRequest, SshPairRequest  # noqa: F401
from core_common.protocol.access import ConnectionInfo, SiteRoomsSnapshot  # noqa: F401
from core_common.protocol.localization import LocalizationStatus, OdomPose
from core_common.protocol.cell_goal_evidence import CellGoalEvidenceSubmission  # noqa: F401
from core_common.protocol.cell_transfer import (  # noqa: F401 (D-403; D-779 7, D-780 pair/barrier fields)
    _ACTION_ID, CellTransferBarrier, CellTransferPayload, CellTransferPose, FleetCellTransferGrant)
from core_common.protocol.cell_app import (  # noqa: F401
    CellAppCompileRequest, CellAppDocumentSaveRequest, CellAppProposalRequest, CellOperatorCheckpoint)
from core_common.protocol.lane_perception import LanePerceptionRequest, LanePerceptionStatus  # noqa: F401
from core_common.protocol.line_arc import LineArcIrCorrection, LineArcStatus  # noqa: F401
from core_common.protocol.trip_lease import TripLeaseFields  # D-541 1: trip_lease, trip_lease_ended
from core_common.protocol.vision_preview_status import VisionPreviewStatus  # noqa: F401
from core_common.protocol.recording_start import RecordingStartRequest  # noqa: F401
from core_common.protocol.overhead_detections import OverheadDetectionsPayload  # noqa: F401
from core_common.protocol.site_survey import SurveyReference, RoadEvidence, FacilityApproach, SiteFacility  # noqa: F401
# PowerHealthResponse lives in protocol.power_health and references these shared types.
# Import that response from its module to avoid a schema import cycle.

PROTOCOL_VERSION = "1.0"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def new_msg_id() -> str:
    return str(uuid4())


# --- 공용 enum (API Ref §4) ----------------------------------------------

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
        if _bounded_finite_json_size(value) > MISSION_EVENT_DETAIL_MAX_BYTES:
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

from .state_components import (  # noqa: F401
    Pose, Velocity, Battery, BatteryLevel, BatteryStatus, SafetySummary, PoseSample,
    LineStuckStatus, LineJunctionStatus, LineFollowStatus, TrafficPolicyStatus,
    VisionEvidenceRecord, VisionEvidenceList, ActivityOwner, RobotActivity,
    ShadowRecordRef, ShadowEvalStats, SafetyShadowStatus, SafetyPolicyHold, SafetyPolicyStatus,
)


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


class JunctionSignalAnswer(BaseModel):
    """D-620: a paired Fleet answer, correlated to the stopped junction episode."""

    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    lamp: Literal["green", "red", "unknown"]
    may_enter: bool = Field(strict=True)
    reason: str = Field(max_length=96)


class HeartbeatPayload(BaseModel):
    state_snapshot: StateSnapshot
    junction_signal_request: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{32}$")


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


from .ui_surface import (  # noqa: F401
    UiSurfaceLink, UiPanelDescriptor, UiActionGroup, UiSurfaceManifest)

# --- D-418 로봇 SSH 접속 (API Ref §5.8, v1.89 additive) ----------------------
#
# administrator 전용 /api/v1/host/ssh/... 의 본문과 응답. CORE 는 이 모양을 검사한
# 뒤 root rosy-ssh-access 에 넘기고, 그 도우미가 같은 규칙을 따로 다시 검사한다.

from .ssh import (  # noqa: F401
    SSH_LABEL_PATTERN, SSH_KEY_TYPES, SSH_TIME_PATTERN, SSH_MAX_KEYS,
    SshKeyAddRequest, SshKeyAdded, SshKeyInfo, SshKeyList, SshHostKeys,
    SshPasswordRequest, SshPasswordIssued, SshPasswordStatus,
)
