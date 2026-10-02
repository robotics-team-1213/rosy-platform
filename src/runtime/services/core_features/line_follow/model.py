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

    def __post_init__(self) -> None:
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
    obstacle_stop_m: float = 0.20
    obstacle_resume_m: float = 0.28
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
    # D-407 막힘 복구. 관제에 묻고 recovery_ask_s 안에 답이 없으면(또는 관제 연결이 없으면)
    # 로컬 후진·재판단. 로컬 복구는 로봇별로 켠다(self-mask 측정 뒤).
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

    def __post_init__(self) -> None:
        self._check_recovery()
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
        obstacle = (self.obstacle_stop_m, self.obstacle_resume_m, self.obstacle_half_angle_deg,
                    self.lidar_forward_deg, self.clearance_stale_s)
        if not all(_finite(value) for value in obstacle):
            raise ValueError("line-follow obstacle config must be finite")
        if not 0.0 < self.obstacle_stop_m < self.obstacle_resume_m <= 2.0:
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
        if not self.obstacle_resume_m <= self.obstacle_path_horizon_m <= 2.0:
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
        if type(self.ir_guard_enabled) is not bool:
            raise ValueError("ir_guard_enabled must be a boolean")
        guard = (self.ir_guard_edge_error, self.ir_guard_turn, self.ir_guard_speed_scale)
        if not all(_finite(value) for value in guard):
            raise ValueError("line-follow IR guard config must be finite")
        if not 0.0 < self.ir_guard_edge_error < 1.0 or self.ir_guard_turn <= 0:
            raise ValueError("IR guard edge error must be in (0, 1) and turn positive")
        if not 0.0 <= self.ir_guard_speed_scale <= 1.0:
            raise ValueError("ir_guard_speed_scale must be in [0, 1]")
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
