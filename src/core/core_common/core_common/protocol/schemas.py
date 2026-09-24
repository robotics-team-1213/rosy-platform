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
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from core_common.protocol.evidence import ValueEvidence

PROTOCOL_VERSION = "1.0"


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
    # 계약 전용 필드(D-170): 중앙 Fleet 서버 착수 전까지 이 필드를 설정·소비하는
    # 런타임 경로는 없다. 명령 추적 확장은 PRT-004와 함께 같은 변경에 담는다.
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
