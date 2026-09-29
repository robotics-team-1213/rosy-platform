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
import math
import re
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core_common.protocol.evidence import EvidenceState, ValueEvidence

PROTOCOL_VERSION = "1.0"


class HostStatusEvidence(BaseModel):
    """CORE judgment of one Host Agent network or release status sample."""

    evidence: EvidenceState = EvidenceState.UNAVAILABLE
    observed_at: str | None = None
    age_s: float | None = None
    stale_after_s: float = 15.0
    reason: str = ""


class DiscoveryScanPayload(BaseModel):
    """Site Fleet only: untrusted resolved mDNS observations, never credentials."""

    devices: list[dict[str, Any]] = Field(max_length=64)


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


class LocalStopState(str, enum.Enum):
    """Software latch facts only. No value means physical standstill is proven."""

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


class DeviceActionReceipt(BaseModel):
    """Local journal receipt; driver success and Mission goal are separate facts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mission_id: str = Field(min_length=1, max_length=192)
    step_id: str = Field(min_length=1, max_length=192)
    action_id: str = Field(min_length=1, max_length=192)
    attempt_id: str = Field(min_length=1, max_length=192)
    workcell_id: str = Field(min_length=1, max_length=96)
    instance_id: str = Field(min_length=1, max_length=96)
    state: DeviceActionState
    journal_event_id: int = Field(strict=True, ge=1)
    observed_at: datetime
    driver_goal_id: str | None = Field(default=None, max_length=192)
    reason: str | None = Field(default=None, max_length=256)

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


class DeviceActionLookup(BaseModel):
    """Read one local Action using its Fleet-issued identity pair."""

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


class PoseSample(BaseModel):
    """Leader Pose Stream payload (SWM-003, ≥10 Hz)."""

    robot_id: str
    pose: Pose
    seq: int
    #: v1.7 additive. 어느 맵의 좌표인지 — 없으면 확인하지 않는다(구 릴레이 호환).
    map_id: Optional[str] = None


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


class TrafficPolicyStatus(BaseModel):
    """Semantic road evidence and the latest command-gating verdict."""

    mode: str = "DISABLED"
    state: str = "DISABLED"
    reason: str = "policy_disabled"
    enforced: bool = False
    map_id: Optional[str] = None
    scene_revision: Optional[str] = None
    policy_revision: str = "traffic-policy-v1"
    evidence_revision: int = 0
    age_s: Optional[float] = None
    stop_line_visible: bool = False
    stop_line_distance_m: Optional[float] = None
    crosswalk_visible: bool = False
    signal_colour: Optional[str] = None
    signal_confidence: float = 0.0
    signal_conflict: bool = False
    linear_scale: float = 0.0


class VisionPreviewStatus(BaseModel):
    """Latest bounded front-camera preview available through CORE (v1.12)."""

    available: bool = False
    stale: bool = False
    source: Optional[str] = None
    frame_id: Optional[str] = None
    captured_at: Optional[float] = None
    age_ms: Optional[int] = None
    width: int = 0
    height: int = 0
    overlay: str = "none"
    sequence: int = 0


class VisionEvidenceRecord(BaseModel):
    """Saved operator camera evidence on the robot SD (API Ref v1.39)."""

    id: str
    kind: str
    file_name: str
    mime_type: str
    bytes: int
    sha256: str
    created_at: str


class VisionEvidenceList(BaseModel):
    records: list[VisionEvidenceRecord] = Field(default_factory=list)


class StateSnapshot(BaseModel):
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
