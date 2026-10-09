"""Line-follow data model: modes, observations, config, decisions (D-143, D-344).

Split out of manager.py so the manager keeps only the one lock owner
(tick, observe, set_mode, obstacle/IR/ladder gates); ROS-free.
"""

from __future__ import annotations

import enum
import math
import re
from dataclasses import dataclass
from typing import Optional

from core_common.robot_body import stop_gap_m
from core_common.protocol.lane_containment import LaneContainmentEvidence

#: Pre-D-422 LiDAR-origin defaults: sector mode and path mode without the URDF outline.
SECTOR_STOP_M = 0.20
SECTOR_RESUME_M = 0.28
#: Source stamps up to this far ahead of CORE's source clock count as now (clock skew,
#: D-495 SIM finding 2); further ahead the sample is refused. Line observations and odom poses.
SOURCE_FUTURE_TOLERANCE_S = 0.1
#: D-507 9: the site floor declaration names a Fleet SiteMap map_id.
SITE_MAP_ID = re.compile(r"[A-Za-z0-9_.-]{1,64}")


class LineFollowMode(str, enum.Enum):
    OFF = "OFF"
    IR_LINE = "IR_LINE"
    CAMERA_LINE = "CAMERA_LINE"


@dataclass(frozen=True)
class LineObservation:
    source: LineFollowMode
    stamp: float
    visible: bool
    error: Optional[float]
    confidence: float
    ir_calibrated: bool = False
    calibration_revision: Optional[str] = None
    # D-364 §3: camera evidence computed on an estimated (NOMINAL) floor model.
    ground: Optional[str] = None
    quality_reason: Optional[str] = None
    containment: Optional[LaneContainmentEvidence] = None

    def __post_init__(self) -> None:
        if self.containment is not None and (
                self.source is not LineFollowMode.CAMERA_LINE or
                not isinstance(self.containment, LaneContainmentEvidence) or
                abs(self.containment.stamp-self.stamp) > .000001):
            raise ValueError("containment must match original camera image stamp")
        if self.containment is not None and (
                (self.containment.ground_source == "NOMINAL") != (self.ground == "NOMINAL")):
            raise ValueError("containment and observation ground provenance must agree")
        if self.quality_reason is not None and (self.source is not LineFollowMode.CAMERA_LINE
                or self.quality_reason not in ('low_light', 'overexposed') or self.visible or self.confidence != 0):
            raise ValueError('invalid camera quality requires invisible evidence with zero confidence')
        if self.ground is not None and (self.source is not LineFollowMode.CAMERA_LINE
                                        or self.ground != "NOMINAL"):
            raise ValueError("only camera evidence may carry the NOMINAL ground label")
        if self.source is LineFollowMode.OFF:
            raise ValueError("OFF cannot be an observation source")
        if not _finite(self.stamp):
            raise ValueError("observation stamp must be finite")
        if not _finite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        if self.visible:
            if not _finite(self.error) or not -1.0 <= float(self.error) <= 1.0:
                raise ValueError("visible observation error must be in [-1, 1]")
        elif self.error is not None:
            raise ValueError("invisible observation cannot carry an error")
        if type(self.ir_calibrated) is not bool:
            raise ValueError("IR calibration marker must be a boolean")
        if self.ir_calibrated and (not isinstance(self.calibration_revision, str)
                                   or not self.calibration_revision.strip()):
            raise ValueError("calibrated IR evidence requires a revision")


@dataclass(frozen=True)
class LineFollowConfig:
    cruise_speed: float = 0.08
    max_linear: float = 0.10
    steering_gain: float = 0.8
    max_angular: float = 0.7
    min_confidence: float = 0.35
    stale_after_s: float = 0.3
    lost_after_s: float = 3.0
    ir_calibration_revision: Optional[str] = None
    # D-344 §11: 앞 물체 정지. LiDAR 정면 부채꼴 최소 거리가 stop 보다 가까우면 멈추고
    # resume 보다 멀어지면 다시 간다(떨림 방지). lidar_forward_deg 는 장착 방향.
    # D-422: 둘 다 LiDAR 원점 기준의 운영자 덮어쓰기다. 비어 있으면 sector 와 몸 기하 없는
    # path 는 SECTOR_STOP_M/SECTOR_RESUME_M, 몸 기하가 있는 path 는 속도로 정지 간격을 유도한다.
    obstacle_stop_m: Optional[float] = None
    obstacle_resume_m: Optional[float] = None
    obstacle_half_angle_deg: float = 20.0
    lidar_forward_deg: float = 0.0
    clearance_stale_s: float = 0.5
    # D-344 §11 보강: path 는 지금 조향으로 곧 지나갈 짧은 호 둘레 띠(±half_width)만 센다 —
    # L 모서리에서 돌아 나가는 쪽이 아닌 앞 벽에는 서지 않는다. sector 는 정면 부채꼴(옛 판정).
    # 기본은 sector 다 — path 는 가제보 한 바퀴와 실물 LiDAR 좌·우 확인 뒤에 기본이 된다.
    obstacle_mode: str = "sector"
    obstacle_corridor_half_width_m: float = 0.09
    obstacle_path_horizon_m: float = 0.40
    # LiDAR returns of the robot's own body (clearance.self_mask_from_config), per robot.
    lidar_self_mask: tuple = ()
    # path: 막힘이 풀리려면 이만큼 계속 비어 있어야 한다(의도 호가 바뀌며 서다 가다 떨지 않게).
    obstacle_release_s: float = 0.2
    # 앞 물체 정지가 이만큼 이어지면 nav.line_obstacle_hold 사건을 한 번 낸다(운전자가 풀어야 함).
    obstacle_escalate_s: float = 5.0
    # D-344 §13: 각속도 상한이 D-342 수동 한도 계단(safety.manual_angular)을 따른다.
    # false 면 max_angular 만 쓴다(명시적 덮어쓰기).
    max_angular_follows_manual: bool = True
    # D-344 §13(사용자 결정 2026-09-30): 차선 자동은 수동 한도 L1(0.30 rad/s) 이상에서만.
    # 살아 있는 manual_angular 가 이보다 작으면 limit_level_too_low 로 멈춘다. 0 이면 끈다.
    lane_auto_min_manual_angular: float = 0.30
    # D-344 §12: 카메라 차선 추종 중 IR 이탈 감시. 바닥을 보는 좌·중·우 IR 이 경계선을
    # 한쪽에서 보면 반대로 비키고(ir_guard_turn, 속도 ir_guard_speed_scale 배), 가운데에서
    # 보면 선을 밟고 넘는 중이라 멈춘다. 켜져 있는데 IR 이 끊기거나 미교정이면 멈춘다.
    ir_guard_enabled: bool = False
    ir_guard_edge_error: float = 0.3
    ir_guard_turn: float = 0.5
    ir_guard_speed_scale: float = 0.5
    # D-491: 감시가 쉬어도 되는 알려진 횡단보도 구간. ir_row_x_m 은 IR 센서 줄의 x(URDF ir_*_link,
    # base_footprint 앞)이고 없으면 쉬지 않는다. 구간 길이 상한과, 영상 시각부터 움직인 odom 거리에
    # 대한 오차 비율(여유 = 투영 불확실도 + 비율 × 이동 거리). 둘 다 실측 뒤 다시 정한다.
    ir_row_x_m: Optional[float] = None
    crosswalk_zone_max_m: float = 0.20
    crosswalk_odom_error_fraction: float = 0.05
    # 카메라가 잰 횡단보도 끝 거리의 앞뒤 오차 비율(9dfk 실측 2026-10-07: 0.3 m에서 약 1.5 cm).
    crosswalk_range_error_fraction: float = 0.05
    # D-407 막힘 복구. 관제에 묻고 recovery_ask_s 안에 답이 없으면(또는 관제 연결이 없으면)
    # 로컬 후진·재판단. 모델 기본값은 꺼짐이고, 로봇 기본값(rosy_default.yaml)은 D-495부터 켜짐이다.
    recovery_local_enabled: bool = False
    recovery_ask_s: float = 15.0
    recovery_back_m: float = 0.08
    recovery_back_speed: float = 0.03      # 실제 속도 = min(D-342 수동 선속도 한도, 이 값)
    recovery_rear_clear_m: float = 0.06    # 몸 뒤끝 기준, 후진 전·중
    recovery_max_attempts: int = 2
    recovery_settle_s: float = 1.0
    # 사용자 결정 2026-10-02: LiDAR 가 못 보는 뒤 띠(range_min, self-mask)는 마지막 전진 명령까지
    # recovery_trail_s 동안 앞으로 recovery_back_m 이상 왔고 누적 |yaw| 가 이 값 이하일 때만 들어간다.
    recovery_trail_s: float = 5.0
    recovery_trail_yaw_deg: float = 10.0
    # 결정 2026-10-02: 지나온 길은 마지막 전진 명령이 이만큼 이내일 때만 믿는다(관제 대기도 센다).
    recovery_trail_max_age_s: float = 30.0
    # 확인 2026-10-02: recovered 로 닫힌 뒤 이 시간 안이거나 이 거리를 아직 못 갔을 때 다시 막히면
    # 같은 막힘으로 시도 수를 이어 센다(복구-재막힘 무한 반복 방지).
    recovery_restuck_s: float = 20.0
    # 확인 2026-10-02: FleetAgent 가 잠깐 다시 붙는 동안(이 시간 이내)은 관제 연결로 본다.
    recovery_console_grace_s: float = 3.0
    recovery_restuck_m: float = 0.30
    # 뒤 띠 폭 = URDF 몸 반폭(body_half_width_m) + 이 여유. 반폭이 없으면 obstacle_corridor_half_width_m.
    recovery_rear_lateral_margin_m: float = 0.02
    # D-397 URDF 몸 기하(base_footprint, x 앞): 없으면 뒤 여유를 잴 수 없어 후진하지 않는다.
    body_lidar_x_m: Optional[float] = None
    body_rear_x_m: Optional[float] = None
    body_rotation_radius_m: Optional[float] = None
    body_half_width_m: Optional[float] = None
    # D-422 몸 기준 앞 물체 정지(path): 몸 앞끝(URDF footprint.front_x_m)과 초음파 위치(ultrasonic.x_m).
    # 정지 간격 = body_margin + v·latency + v²/(2·decel), 재출발은 + hysteresis.
    body_front_x_m: Optional[float] = None
    body_ultrasonic_x_m: Optional[float] = None
    obstacle_body_margin_m: float = 0.02
    obstacle_latency_s: float = 0.15
    obstacle_decel_mps2: float = 0.5
    obstacle_resume_hysteresis_m: float = 0.03
    obstacle_ultrasonic_half_angle_deg: float = 15.0
    obstacle_ultrasonic_stale_s: float = 0.3
    # D-476 expected-road bridge: on a short lane loss right after confident following, drive
    # the followed lane's straight extension slowly. Distance ladder from D-384 (measured odom
    # travel x bridge_distance_scale: full speed below coast, x slow_scale below slow, then
    # stop) and done by lost_after_s - bridge_time_margin_s. Off by default, model and robot
    # (D-476 rev 1: an enabled bridge needs ir_guard_enabled and a floor basis).
    bridge_enabled: bool = False
    # Arming (D-476 rev 2026-10-07): the last bridge_arm_frames camera frames all visible with
    # confidence >= bridge_arm_confidence and the tick TRACKING. 0.5 sits above the 0.35 follow
    # floor, so frames that steer at under a quarter of the confidence scale never arm; 3 frames
    # is the D-468 reacquisition count and spans about one stale_after_s (0.3 s) at 7.7-10 Hz.
    # Straight only: |error| <= bridge_arm_max_error (0.1: the follower's own curve_scale
    # 1 - 0.65|e| slows < 7 %, i.e. it treats this as straight) and |angular| <=
    # bridge_arm_max_angular (0.08 = steering_gain 0.8 x 0.1). All four are plausibility gates
    # until D-476 step 1 replay justifies them; none is device evidence.
    bridge_arm_confidence: float = 0.5
    bridge_arm_frames: int = 3
    bridge_arm_max_error: float = 0.1
    bridge_arm_max_angular: float = 0.08
    # D-476 rev 2: a streak outside that straight band arms on a steady arc instead. Over the
    # last bridge_arm_frames frames the commanded curvature (angular/linear) spreads by at most
    # bridge_arm_curvature_tolerance (0.5 1/m: worst lateral error 0.5 x (0.25/1.08)^2 / 2 =
    # 13.4 mm, about half the 23.5 mm play), its mean is within bridge_arm_max_curvature (4.0 1/m:
    # lane_graph map_v2_fleet roundabout radius 0.2514 m, the tightest lane arc), and the error
    # spreads by at most bridge_arm_error_spread (derived below).
    bridge_arm_max_curvature: float = 4.0
    bridge_arm_curvature_tolerance: float = 0.5
    bridge_lookahead_m: float = 0.10
    bridge_coast_m: float = 0.10
    bridge_slow_m: float = 0.25
    bridge_slow_scale: float = 0.5
    bridge_distance_scale: float = 1.08
    bridge_time_margin_s: float = 0.5
    # D-495 bounded junction turn (review M5/M6): consecutive fresh confident lane frames that
    # count as reacquired, and the actuation/odom latency the turn stops early for.
    junction_reacquire_frames: int = 3
    junction_turn_lead_s: float = 0.15
    # Review L3: odom speeds below which the robot counts as standing still (turn start/settle).
    junction_still_linear: float = 0.01
    junction_still_angular: float = 0.05
    # D-507 9: the site floor declaration, one per map. The site lead walked every lane and
    # junction of SiteMap map_id plus 0.30 m outside it (turn, advance, approach, bridge, return
    # and the D-468 retrace's rear path) and found no drop-off, hole or step. It is the floor
    # basis of motion_admitted's site basis (D-507 6 b/c); None = no declaration.
    site_floor_map_id: Optional[str] = None
    # D-520 map-guided arc (on by default, user 2026-10-09): it drives only with the site floor
    # declaration above (capability lane_arc). curvature gain g in omega = g*v*kappa (D-500 measured
    # motion response, [0.8, 1.25]); arc_blind_max_m: travel without a camera fit before
    # lane_arc_blind (step 1 SIM default: the whole segment, 1.0 m).
    arc_enabled: bool = True
    route_context_enabled: bool = False
    arc_curvature_gain: float = 1.0
    arc_blind_max_m: float = 1.0
    authority_required: bool = False  # D-517 4: no motion without a live Fleet authority, even before one
    # D-468 containment (implementation note 2026-10-06): the corridor is eroded by the producer's
    # uncertainty_m. 0 means every URDF footprint corner is inside only if uncertainty_m bounds
    # every lateral error; jitter and footprint tolerance not in it go in this body margin. The
    # default 0 is to be revisited from measured 2-sigma boundary jitter once real producers send
    # uncertainty_m. Entry also subtracts drift at the live linear limit over 0.3 s; a tracking
    # robot leaves only when margin + u < 0. A normal checkpoint uses at most (1 - fraction) of the play.
    lane_return_body_margin_m: float = 0.0
    lane_return_checkpoint_fraction: float = 0.5

    def __post_init__(self) -> None:
        self._check_recovery()
        self._check_body_stop()
        self._check_bridge()
        self._check_junction()
        values = (self.cruise_speed, self.max_linear, self.steering_gain,
                  self.max_angular, self.min_confidence,
                  self.stale_after_s, self.lost_after_s)
        if not all(_finite(value) for value in values):
            raise ValueError("line-follow config must be finite")
        if not 0.0 < self.cruise_speed <= self.max_linear <= 0.10:
            raise ValueError("line-follow speed must be positive and capped at 0.10 m/s")
        if self.steering_gain <= 0 or self.max_angular <= 0:
            raise ValueError("line-follow steering limits must be positive")
        if not 0.0 < self.min_confidence <= 1.0:
            raise ValueError("min_confidence must be in (0, 1]")
        if self.stale_after_s <= 0 or self.lost_after_s <= 0:
            raise ValueError("line-follow timeouts must be positive")
        obstacle = (self.sector_stop_m, self.sector_resume_m, self.obstacle_half_angle_deg,
                    self.lidar_forward_deg, self.clearance_stale_s)
        if not all(_finite(value) for value in obstacle):
            raise ValueError("line-follow obstacle config must be finite")
        if not 0.0 < self.sector_stop_m < self.sector_resume_m <= 2.0:
            raise ValueError("obstacle_stop_m must be positive and below obstacle_resume_m")
        if not 0.0 < self.obstacle_half_angle_deg <= 90.0 or self.clearance_stale_s <= 0:
            raise ValueError("obstacle sector and clearance staleness must be positive")
        if self.obstacle_mode not in ("path", "sector"):
            raise ValueError("obstacle_mode must be 'path' or 'sector'")
        corridor = (self.obstacle_corridor_half_width_m, self.obstacle_path_horizon_m)
        if not all(_finite(value) for value in corridor):
            raise ValueError("line-follow obstacle corridor must be finite")
        if not 0.0 < self.obstacle_corridor_half_width_m <= 0.5:
            raise ValueError("obstacle_corridor_half_width_m must be in (0, 0.5]")
        if not self.sector_resume_m <= self.obstacle_path_horizon_m <= 2.0:
            raise ValueError("obstacle_path_horizon_m must cover obstacle_resume_m and stay <= 2 m")
        timing = (self.obstacle_release_s, self.obstacle_escalate_s,
                  self.lane_auto_min_manual_angular)
        if not all(_finite(value) for value in timing):
            raise ValueError("line-follow obstacle timing and ladder floor must be finite")
        if not 0.0 <= self.obstacle_release_s <= 2.0 or self.obstacle_escalate_s <= 0:
            raise ValueError("obstacle_release_s must be in [0, 2] and obstacle_escalate_s positive")
        if self.lane_auto_min_manual_angular < 0:
            raise ValueError("lane_auto_min_manual_angular must be nonnegative")
        if type(self.max_angular_follows_manual) is not bool:
            raise ValueError("max_angular_follows_manual must be a boolean")
        for name in ('ir_guard_enabled', 'authority_required'):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a boolean")
        guard = (self.ir_guard_edge_error, self.ir_guard_turn, self.ir_guard_speed_scale)
        if not all(_finite(value) for value in guard):
            raise ValueError("line-follow IR guard config must be finite")
        if not 0.0 < self.ir_guard_edge_error < 1.0 or self.ir_guard_turn <= 0:
            raise ValueError("IR guard edge error must be in (0, 1) and turn positive")
        if not 0.0 <= self.ir_guard_speed_scale <= 1.0:
            raise ValueError("ir_guard_speed_scale must be in [0, 1]")
        if self.ir_row_x_m is not None and not (_finite(self.ir_row_x_m) and abs(self.ir_row_x_m) <= 0.2):
            raise ValueError("ir_row_x_m must be a finite base_footprint x within 0.2 m")
        if not (_finite(self.crosswalk_zone_max_m) and 0.0 < self.crosswalk_zone_max_m <= 0.5):
            raise ValueError("crosswalk_zone_max_m must be in (0, 0.5]")
        if not (_finite(self.crosswalk_odom_error_fraction) and 0.0 <= self.crosswalk_odom_error_fraction <= 0.5):
            raise ValueError("crosswalk_odom_error_fraction must be in [0, 0.5]")
        if not (_finite(self.crosswalk_range_error_fraction) and 0.0 <= self.crosswalk_range_error_fraction <= 0.5):
            raise ValueError("crosswalk_range_error_fraction must be in [0, 0.5]")
        if (self.ir_calibration_revision is not None
                and (not isinstance(self.ir_calibration_revision, str)
                     or not re.fullmatch(r"[0-9a-f]{64}", self.ir_calibration_revision))):
            raise ValueError("IR calibration revision must be a lowercase SHA-256 digest")

    def _check_recovery(self) -> None:
        if type(self.recovery_local_enabled) is not bool:
            raise ValueError("recovery_local_enabled must be a boolean")
        timing = (self.recovery_ask_s, self.recovery_back_m, self.recovery_back_speed,
                  self.recovery_rear_clear_m, self.recovery_settle_s, self.recovery_trail_s,
                  self.recovery_trail_yaw_deg, self.recovery_restuck_s, self.recovery_restuck_m,
                  self.recovery_trail_max_age_s)
        if not all(_finite(value) and value > 0 for value in timing):
            raise ValueError("line-follow recovery times and distances must be positive and finite")
        if not _finite(self.recovery_console_grace_s) or not 0.0 <= self.recovery_console_grace_s <= 10.0:
            raise ValueError("recovery_console_grace_s must be in [0, 10]")
        if self.recovery_trail_max_age_s > 300.0:
            raise ValueError("recovery_trail_max_age_s is capped at 300 s")
        if self.recovery_trail_s > 30.0 or self.recovery_trail_yaw_deg > 45.0:
            raise ValueError("recovery_trail_s is capped at 30 s and recovery_trail_yaw_deg at 45")
        if self.recovery_back_m > 0.20 or self.recovery_back_speed > 0.05:
            raise ValueError("recovery_back_m is capped at 0.20 m and recovery_back_speed at 0.05 m/s")
        if (type(self.recovery_max_attempts) is not int
                or not 0 <= self.recovery_max_attempts <= 5):
            raise ValueError("recovery_max_attempts must be an integer in [0, 5]")
        if (not _finite(self.recovery_rear_lateral_margin_m)
                or not 0.0 <= self.recovery_rear_lateral_margin_m <= 0.10):
            raise ValueError("recovery_rear_lateral_margin_m must be in [0, 0.10]")
        if (not _finite(self.lane_return_body_margin_m)
                or not 0.0 <= self.lane_return_body_margin_m <= 0.05):
            raise ValueError("lane_return_body_margin_m must be in [0, 0.05]")
        if (not _finite(self.lane_return_checkpoint_fraction)
                or not 0.0 <= self.lane_return_checkpoint_fraction <= 1.0):
            raise ValueError("lane_return_checkpoint_fraction must be in [0, 1]")
        if self.body_half_width_m is not None and (
                not _finite(self.body_half_width_m) or not 0.0 < self.body_half_width_m <= 0.5):
            raise ValueError("body_half_width_m must be in (0, 0.5]")
        body = (self.body_lidar_x_m, self.body_rear_x_m, self.body_rotation_radius_m)
        if any(value is not None and not _finite(value) for value in body):
            raise ValueError("line-follow body geometry must be finite or unset")
        if self.body_rear_x_m is not None and not -0.5 < self.body_rear_x_m < 0.0:
            raise ValueError("body_rear_x_m must be behind base_footprint (-0.5, 0)")
        if self.body_rotation_radius_m is not None and not 0.0 < self.body_rotation_radius_m <= 0.5:
            raise ValueError("body_rotation_radius_m must be in (0, 0.5]")

    def _check_junction(self) -> None:
        if type(self.junction_reacquire_frames) is not int or not 1 <= self.junction_reacquire_frames <= 20:
            raise ValueError("junction_reacquire_frames must be a whole number in [1, 20]")
        if not _finite(self.junction_turn_lead_s) or not 0.0 <= self.junction_turn_lead_s <= 1.0:
            raise ValueError("junction_turn_lead_s must be in [0, 1]")
        if not _finite(self.junction_still_linear) or not 0.0 < self.junction_still_linear <= 0.05:
            raise ValueError("junction_still_linear must be in (0, 0.05] m/s")
        if not _finite(self.junction_still_angular) or not 0.0 < self.junction_still_angular <= 0.2:
            raise ValueError("junction_still_angular must be in (0, 0.2] rad/s")
        if type(self.arc_enabled) is not bool:
            raise ValueError("arc_enabled must be a boolean")
        if type(self.route_context_enabled) is not bool:
            raise ValueError("route_context_enabled must be a boolean")
        if not (_finite(self.arc_curvature_gain) and 0.8 <= self.arc_curvature_gain <= 1.25
                and _finite(self.arc_blind_max_m) and 0.0 < self.arc_blind_max_m <= 1.0):
            raise ValueError("arc_curvature_gain must be in [0.8, 1.25] and arc_blind_max_m in (0, 1]")
        site = self.site_floor_map_id
        if site is None:
            return
        if not isinstance(site, str) or not SITE_MAP_ID.fullmatch(site) or site == "site":
            raise ValueError("site_floor_map_id must be a SiteMap map_id ([A-Za-z0-9_.-]{1,64}), "
                             "not the default 'site'")
        if not (self.ir_guard_enabled and self.obstacle_mode == "path" and self.body_stop_known):
            raise ValueError("site_floor_map_id needs ir_guard_enabled, obstacle_mode path and "
                             "the URDF body geometry (D-507 9)")

    @property
    def bridge_arm_error_spread(self) -> float:
        """D-476 rev 2: the error spread that commands bridge_arm_curvature_tolerance at cruise
        (angular = steering_gain x error), so a steady arc is steady in error and curvature."""
        return self.bridge_arm_curvature_tolerance*self.cruise_speed/self.steering_gain

    @property
    def bridge_arm_min_travel_m(self) -> float:
        """D-476 rev 2: the odom travel an arc's arming window must span. The follower's error
        scale in length is cruise_speed/steering_gain (one error unit commands curvature
        steering_gain/cruise_speed), so over this travel a curvature mismatch of
        bridge_arm_curvature_tolerance turns the body by bridge_arm_error_spread rad, the error
        step the gate resolves. Shorter windows (a crawl, a few frames) cannot tell an arc from
        a correction, and their odom turn cannot check the curvature."""
        return self.bridge_arm_error_spread/self.bridge_arm_curvature_tolerance

    def _check_bridge(self) -> None:
        if type(self.bridge_enabled) is not bool:
            raise ValueError("bridge_enabled must be a boolean")
        values = (self.bridge_lookahead_m, self.bridge_coast_m, self.bridge_slow_m,
                  self.bridge_slow_scale, self.bridge_distance_scale, self.bridge_time_margin_s,
                  self.bridge_arm_confidence, self.bridge_arm_max_error, self.bridge_arm_max_angular,
                  self.bridge_arm_max_curvature, self.bridge_arm_curvature_tolerance)
        if not all(_finite(value) for value in values):
            raise ValueError("line-follow bridge config must be finite")
        if not 0.0 < self.bridge_lookahead_m <= 0.5:
            raise ValueError("bridge_lookahead_m must be in (0, 0.5]")
        if not 0.0 < self.bridge_coast_m <= self.bridge_slow_m <= 0.5:
            raise ValueError("bridge distances must satisfy 0 < bridge_coast_m <= bridge_slow_m <= 0.5")
        if not 0.0 < self.bridge_slow_scale <= 1.0:
            raise ValueError("bridge_slow_scale must be in (0, 1]")
        if not 1.0 <= self.bridge_distance_scale <= 2.0:
            raise ValueError("bridge_distance_scale must be in [1, 2]")
        if not 0.0 < self.bridge_time_margin_s <= 2.0:
            raise ValueError("bridge_time_margin_s must be in (0, 2]")
        if not 0.0 < self.bridge_arm_confidence <= 1.0:
            raise ValueError("bridge_arm_confidence must be in (0, 1]")
        if type(self.bridge_arm_frames) is not int or not 1 <= self.bridge_arm_frames <= 30:
            raise ValueError("bridge_arm_frames must be an integer in [1, 30]")
        if not (0.0 < self.bridge_arm_max_error <= 1.0
                and 0.0 < self.bridge_arm_max_angular <= self.max_angular):
            raise ValueError("bridge_arm_max_error must be in (0, 1] and bridge_arm_max_angular "
                             "in (0, max_angular]")
        if not 0.0 < self.bridge_arm_curvature_tolerance <= self.bridge_arm_max_curvature <= 10.0:
            raise ValueError("bridge arc config must satisfy 0 < bridge_arm_curvature_tolerance "
                             "<= bridge_arm_max_curvature <= 10")
        if self.bridge_enabled and self.bridge_arm_confidence < self.min_confidence:
            raise ValueError("bridge_enabled needs bridge_arm_confidence >= min_confidence")
        if self.bridge_enabled and not self.ir_guard_enabled:
            # D-476 rev 1: the IR guard is the bridge's only lateral fence.
            raise ValueError("bridge_enabled needs ir_guard_enabled")
        if self.bridge_enabled and not self.bridge_time_margin_s < self.lost_after_s:
            # Only an enabled bridge needs time inside the LOST clock; an off one changes nothing.
            raise ValueError("bridge_enabled needs bridge_time_margin_s below lost_after_s")

    def _check_body_stop(self) -> None:
        for name in ("obstacle_stop_m", "obstacle_resume_m"):
            value = getattr(self, name)
            if value is not None and not _finite(value):
                raise ValueError(f"{name} must be a finite number or unset")
        terms = (self.obstacle_body_margin_m, self.obstacle_latency_s, self.obstacle_decel_mps2,
                 self.obstacle_resume_hysteresis_m, self.obstacle_ultrasonic_half_angle_deg,
                 self.obstacle_ultrasonic_stale_s)
        if not all(_finite(value) for value in terms):
            raise ValueError("line-follow body stop terms must be finite")
        if not 0.0 <= self.obstacle_body_margin_m <= 0.20 or not 0.0 <= self.obstacle_latency_s <= 1.0:
            raise ValueError("obstacle_body_margin_m must be in [0, 0.2] and obstacle_latency_s in [0, 1]")
        if not 0.0 < self.obstacle_decel_mps2 <= 10.0:
            raise ValueError("obstacle_decel_mps2 must be in (0, 10]")
        if not 0.0 < self.obstacle_resume_hysteresis_m <= 0.20:
            raise ValueError("obstacle_resume_hysteresis_m must be in (0, 0.2]")
        if (not 0.0 < self.obstacle_ultrasonic_half_angle_deg <= 45.0
                or not 0.0 < self.obstacle_ultrasonic_stale_s <= 2.0):
            raise ValueError("ultrasonic cone must be in (0, 45] deg and its staleness in (0, 2] s")
        for name in ("body_front_x_m", "body_ultrasonic_x_m"):
            value = getattr(self, name)
            if value is not None and (not _finite(value) or not -0.5 < value < 0.5):
                raise ValueError(f"{name} must be in (-0.5, 0.5) or unset")
        if self.body_front_x_m is not None and not self.body_front_x_m > 0.0:
            raise ValueError("body_front_x_m must be ahead of base_footprint")
        if (self.body_front_x_m is not None and self.body_ultrasonic_x_m is not None
                and self.body_ultrasonic_x_m > self.body_front_x_m):
            raise ValueError("body_ultrasonic_x_m cannot be ahead of body_front_x_m")

    @property
    def obstacle_override(self) -> bool:
        """D-422: an operator set obstacle_stop_m or obstacle_resume_m (LiDAR origin): it wins."""
        return self.obstacle_stop_m is not None or self.obstacle_resume_m is not None

    @property
    def sector_stop_m(self) -> float:
        """LiDAR-origin stop distance: the override, else the pre-D-422 default (one unset half
        of the pair keeps its old default, so an old overlay reads exactly as before)."""
        return SECTOR_STOP_M if self.obstacle_stop_m is None else float(self.obstacle_stop_m)

    @property
    def sector_resume_m(self) -> float:
        return SECTOR_RESUME_M if self.obstacle_resume_m is None else float(self.obstacle_resume_m)

    @property
    def body_stop_known(self) -> bool:
        """D-422 body-referenced stop needs the whole URDF outline and the LiDAR position."""
        return None not in (self.body_front_x_m, self.body_lidar_x_m, self.body_rear_x_m,
                            self.body_half_width_m, self.body_rotation_radius_m)

    def derived_stop_gap_m(self, speed: float) -> float:
        """D-422 body gap that stops in time from `speed`: margin + reaction + braking."""
        # D-424: the one gap rule shared with the sensing gate and the calibration tools.
        return stop_gap_m(max(0.0, float(speed)), margin_m=self.obstacle_body_margin_m,
                          latency_s=self.obstacle_latency_s, decel_mps2=self.obstacle_decel_mps2)

    @property
    def body_geometry_known(self) -> bool:
        return self.body_lidar_x_m is not None and self.body_rear_x_m is not None


@dataclass(frozen=True)
class LineFollowDecision:
    linear: float = 0.0
    angular: float = 0.0
    generation: int = 0
    evidence_revision: int = 0
    mode: LineFollowMode = LineFollowMode.OFF


def _finite(value) -> bool:
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(float(value)))
