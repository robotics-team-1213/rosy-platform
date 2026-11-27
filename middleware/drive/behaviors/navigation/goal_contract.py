"""Nav2 goal data and the ROS-independent executor contract."""

from dataclasses import dataclass
import time
from typing import Protocol


@dataclass
class NavGoalSpec:
    x: float
    y: float
    yaw: float
    frame: str = "map"
    #: Route legs only: poses to pass through before `x, y` (Nav2 NavigateThroughPoses). Empty = NavigateToPose.
    via: tuple["NavGoalSpec", ...] = ()


class NavExecutor(Protocol):
    def send_goal(self, spec: NavGoalSpec, *, correlation_id: str | None = None) -> None: ...
    def cancel_goal(self) -> None: ...
    def send_initial_pose(self, x: float, y: float, yaw: float) -> None: ...
    def save_map(self, name: str) -> str: ...   # map_id 반환 (D-13, 브리지가 체크섬/대체 해시 산출)
    def reset_mapping(self) -> None: ...        # NAV-005 세션 초기화


class NavigationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def check_admit_deadline(admit_before):
    # D-1079: real monotonic time, including lock/gate waits, never the replaceable ROS clock.
    if admit_before is not None and time.monotonic() > admit_before:
        raise NavigationError("MOTION_ADMIT_DEADLINE_EXCEEDED", "motion admission deadline exceeded")
