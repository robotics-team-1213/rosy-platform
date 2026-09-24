"""core.bridge.docking_executor — the bridge's DockingExecutor, ROS-free.

정책은 core_features.docking.manager 가 갖고 여기는 조정만 한다 — power/mode 와
PWR-005 LiDAR 의도와 같은 형태다. ROS 에 닿는 동작(Nav2 goal 전송·취소, 면제 Bool
발행, 마지막 odom 포즈 읽기)은 `ros_bridge` 가 callable 로 넘긴다 — 그래서 호스트
pytest 가 이 계약을 직접 부를 수 있다 (`test/test_bridge_docking_executor.py`).
"""

from __future__ import annotations

from typing import Callable, Optional

from core.bridge import odometry
from core_features.command.manager import Twist as CoreTwist
from core_features.navigation.manager import NavGoalSpec

Pose = Optional[tuple[float, float, float]]


class BridgeDockingExecutor:
    """`core_features.docking.model.DockingExecutor` 구현 (docking.manager 와 계약)."""

    def __init__(self, services, *,
                 send_goal: Callable[[NavGoalSpec], None],
                 cancel_goal: Callable[[], None],
                 publish_exemption: Callable[[bool], None],
                 odom_pose: Callable[[], Pose],
                 info: Callable[[str], None]) -> None:
        self._svc = services
        self._send_goal = send_goal
        self._cancel_goal = cancel_goal
        self._publish_exemption = publish_exemption
        self._odom_pose = odom_pose
        self._info = info
        self._dock_odom_mark = None
        self._applied_dock_exemption = False

    def _odom_xy(self):
        pose = self._odom_pose()
        return None if pose is None else (pose[0], pose[1])

    def navigate_to(self, pose) -> None:
        """스테이징 주행. 도킹 액션이 Nav2 구간까지 소유하므로 여기서 부른다.

        NavigationManager.goal 을 거치지 않으므로 nav_state 를 먼저 PLANNING
        으로 둔다 — 아니면 도킹이 첫 틱에 지난 주행의 ARRIVED/FAILED 를 읽는다."""
        self._svc.nav.external_goal_sent()
        self._send_goal(NavGoalSpec(x=pose.x, y=pose.y, yaw=pose.yaw))

    def cancel_navigation(self) -> None:
        self._cancel_goal()

    def drive(self, linear: float, angular: float) -> None:
        """접근·후진 속도. 기존 cmd_vel 멀렉서를 통과시킨다.

        도킹 슬롯을 쓴다 — DOCKING 에서만 바퀴에 닿는다. nav 슬롯을 쓰면 DOCKING
        을 떠난 뒤(IDLE → NAVIGATION) 도킹 틱의 값이 'navigation' 으로 나간다.
        """
        self._svc.command.set_docking_twist(CoreTwist(linear=linear, angular=angular))

    def stop(self) -> None:
        self._svc.command.set_docking_twist(CoreTwist(linear=0.0, angular=0.0))

    def set_collision_exemption(self, enabled: bool) -> None:
        """도크는 코스트맵에 장애물로 찍힌다 — 접근 구간에만 면제를 선언한다.

        Nav2 에 이를 끄는 표준 서비스가 없어서 의도를 토픽으로 내보낸다. 실제
        코스트맵 연동은 실기 항목으로 남는다(DOCK_GO). 토픽은 latch 라 바뀔 때만 낸다.
        """
        if enabled == self._applied_dock_exemption:
            return
        self._applied_dock_exemption = enabled
        self._publish_exemption(bool(enabled))
        self._info("docking collision exemption %s" % ("on" if enabled else "off"))

    def reset_odometry_mark(self) -> None:
        self._dock_odom_mark = self._odom_xy()

    def travelled_m(self) -> float:
        """마크 이후 이동 거리. 언도킹은 센서를 보지 않고 이 값만 쓴다."""
        return odometry.travelled_m(self._dock_odom_mark, self._odom_xy())

    def odometry_available(self) -> bool:
        """언도킹 전: 후진 거리를 잴 오도메트리가 들어오고 있는가."""
        return self._odom_xy() is not None

    def odometry_pose(self) -> Pose:
        """오도메트리 base 포즈 (x, y, yaw) — 주차형 도크의 프레임 사이 전파와 회전."""
        return self._odom_pose()
