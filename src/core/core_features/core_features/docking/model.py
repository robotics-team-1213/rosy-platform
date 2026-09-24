"""core_features.docking.model — 도킹 상태머신의 단계·모션 계약·설정.

`manager` 와 `parking_phases` 가 함께 쓰는 정의다. `manager` 가 그대로 다시 내보낸다
(`from core_features.docking.manager import DockPhase, DockingConfig`).

ROS 무의존.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Protocol

from core_features.docking.database import Pose2D


class DockPhase(str, enum.Enum):
    """`DOCKING` 안의 내부 단계.

    재시도가 *어디서* 실패했는지 알아야 하기 때문에 존재한다. 도착하지 못한
    것과 도착했는데 전류가 없는 것은 복구 방법이 다르다.
    """

    STAGING = "staging"          # Nav2 로 도크 앞까지
    ACQUIRING = "acquiring"      # 검출기가 도크를 찾는다
    APPROACHING = "approaching"  # 관측 상대 포즈에 서보
    SETTLING = "settling"        # 전류가 흐르기를 기다린다
    BACKOFF = "backoff"          # 실패 후 뒤로 빠져 재시도 준비
    TURNING = "turning"          # 주차형: 제자리 회전 (진입, 언도킹 뒤)
    ALIGNING = "aligning"        # 주차형: 주차점에서 방위만 맞춘다


class DockingExecutor(Protocol):
    """모션. ros_bridge 가 구현하고 이 계층은 의도만 말한다."""

    def navigate_to(self, pose: Pose2D) -> None: ...
    def cancel_navigation(self) -> None: ...
    def drive(self, linear: float, angular: float) -> None: ...
    def stop(self) -> None: ...
    def set_collision_exemption(self, enabled: bool) -> None: ...
    def travelled_m(self) -> float: ...
    def reset_odometry_mark(self) -> None: ...
    # 주차형만 쓴다 (선택, getattr 로 찾는다): 오도메트리 base 포즈
    # `odometry_pose() -> Optional[tuple[x, y, yaw]]`.
    # 선택: `odometry_available() -> bool` — 언도킹 전 오도메트리 기준점이 있는가.
    # 없으면 travelled_m 이 0.0 에 머물러 후진이 끝나지 않는다.


@dataclass
class DockingConfig:
    staging_timeout_s: float = 120.0
    acquire_timeout_s: float = 15.0
    approach_timeout_s: float = 60.0
    settle_timeout_s: float = 20.0
    backoff_s: float = 2.0
    backoff_distance_m: float = 0.25
    reseat_distance_m: float = 0.06     # 접점 재착좌 — 스테이징까지 가지 않는다

    approach_speed: float = 0.06        # m/s — 접근은 느려야 한다
    approach_gain_yaw: float = 1.2
    max_angular: float = 0.5
    undock_speed: float = 0.08
    undock_timeout_margin_s: float = 2.0  # 후진 마감 = 2 × 거리/속도 + 이 값

    detector_lost_grace_s: float = 2.0  # 이 시간 안에 다시 보이면 실패가 아니다
    charge_confirm_s: float = 10.0      # 충전 확정 창

    # 주차형 (approach="pose")
    turn_timeout_s: float = 30.0
    align_timeout_s: float = 15.0
    settle_still_s: float = 0.6         # 멈춘 뒤 이만큼 지나 찍힌 관측으로 판정
    creep_exhausted_s: float = 1.0      # 크리프를 다 쓰고도 이만큼 안 보이면 재시도
    acquire_look_s: float = 0.5         # 기어가기 전에 먼저 본다 (5 Hz 두 프레임 + 지연)
    backoff_timeout_s: float = 10.0
    aim_min_m: float = 0.05             # 이보다 가까우면 주차점이 아니라 도크 yaw 를 겨눈다
