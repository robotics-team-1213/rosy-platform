"""Existing state snapshot components; canonical exports remain in schemas."""

from __future__ import annotations

import enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_serializer, model_validator

from .route_context import RouteContext
from .line_crosswalk import LineCrosswalkStatus
from .line_arc import LineArcStatus


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
    shown_percent: Optional[float] = None  # D-688 display estimate; percent stays the live policy value


class SafetySummary(BaseModel):
    estop: bool = False


# --- 절전/근접 웨이크 (PWR-001~004, D-24) -----------------------------------

# --- Swarm (D-20, SWM-001~006, API Ref §7.8) --------------------------------

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
    cause: str  # obstacle_ahead | lane_lost | crosswalk_blocked (D-573 4) | no_motion | no_progress | dithering (D-607)
    phase: str                            # ASKING | WAITING_CONSOLE | BACKING | SETTLING
    held_s: float = 0.0
    attempts: int = 0
    max_attempts: int = 0
    local_enabled: bool = False
    conditional_back: bool = False  # D-718: absent on old CORE; no conditional POST admission
    ask_remaining_s: Optional[float] = None   # None = console answer only, no local fallback
    last_answer: Optional[str] = None
    decisions: list[str] = Field(default_factory=list)
    # D-573 4 crosswalk_blocked: person_present | look_unknown | sensor_stale | zone_lost; else the (last) HOLD reason
    detail: Optional[str] = None
    inquiry: Optional[dict] = None  # D-623 current typed situation context; not execution permission


class LineJunctionStatus(BaseModel):
    """D-494 decision 4 / D-495: the one pending next-junction instruction and its progress."""

    pending_action: Optional[str] = None  # straight | left | right | stop
    place_id: Optional[str] = None
    state: str = "idle"  # API ref line_follow.junction.state list (D-507: approaching, unexpected)
    seq: int = 0
    turn_deg: Optional[float] = None      # D-495: signed bounded turn (left +)
    reason: Optional[str] = None          # D-495: why a maneuver aborted
    pivot_basis: Optional[str] = None     # D-507 4: map | stop_point; D-520: segment_end
    signal_request_id: Optional[str] = None  # D-620: one stopped junction episode
    signal_state: Optional[str] = None       # waiting | red | unknown | green | fallback | entered
    #: D-759 5: the bend pass took its entry heading from Fleet's map_entry, not the body's own yaw.
    map_entry_used: bool = False
    #: D-759 5: why not (none_sent, disabled, stale, future, no_sample, epoch, carry, heading); None when used,
    #: before the take-over of a placed one, and for every instruction that is not a bend.
    map_entry_reason: Optional[str] = None
    #: D-767 A: what a window's or bend's distance counts from: stamp (the odom sample at pose_stamp) |
    #: receipt (as before); None for an instruction without either.
    distance_basis: Optional[str] = None
    #: D-767 A: none_sent when receipt (an unusable pose_stamp is refused, 409 INSTRUCTION_STAMP_UNUSABLE).
    distance_basis_reason: Optional[str] = None


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
    lane_cue: Optional[dict] = None  # D-511 rev 1: the unexpired Fleet lane cue (LaneCueRequest)
    # D-573 6 (개정 2026-10-10): CORE always reports it; absent = an older CORE (D-577 R3 fails closed).
    crosswalk: Optional[LineCrosswalkStatus] = None
    crosswalk_reported: bool = Field(default=False, exclude=True)
    # D-760 rev 3 item 9 (v1.227): the regulation standing the robot, by precedence authority > signal >
    # crosswalk_held > crosswalk_wait > crosswalk_look; None = line-follow off or none holds it.
    regulation_wait: Optional[Literal['authority', 'signal', 'crosswalk_held', 'crosswalk_wait',
                                      'crosswalk_look']] = None

    @model_validator(mode="before")
    @classmethod
    def _crosswalk_key_means_reported(cls, data):
        # Only the key says "reported" (hub copy, D-555); a bare flag is not null=outside (D-577 R3).
        if isinstance(data, dict):
            data = {**data, "crosswalk_reported": "crosswalk" in data}
        return data

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


class SafetyPolicyHold(BaseModel):
    """D-400 4: enforce sensor gaps answered with HOLD since CORE start (v1.223 additive)."""

    count: int = 0
    reason: str = ""


class SafetyPolicyStatus(BaseModel):
    """D-400: the safety policy mode CORE runs, and why (v1.71 additive)."""

    mode: str
    mode_effective: str
    mode_error: str = ""
    revision: str = ""
    sources: dict[str, str] = Field(default_factory=dict)
    shadow: Optional[SafetyShadowStatus] = None
    hold: Optional[SafetyPolicyHold] = None  # enforce only
