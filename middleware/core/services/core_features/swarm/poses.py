"""core_features.swarm.poses — 리더 참조 pose 와 추종 목표 (SWM-001). ROS 무의존.

Navigation 이 실행할 NavGoalSpec 을 만든다. 상태머신은 여기 없다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from core_features.navigation.manager import NavGoalSpec


@dataclass
class ReferencePose:
    """리더가 보고한 pose 한 표본 (API Ref 7.8)."""

    robot_id: str
    x: float
    y: float
    yaw: float
    seq: int = 0
    #: 이 좌표가 어느 맵의 것인지. `None` 이면 확인할 수 없다.
    map_id: Optional[str] = None


def follow_goal(reference: ReferencePose, distance: float, lateral: float) -> NavGoalSpec:
    """리더 뒤 `distance`, 왼쪽으로 `lateral` 떨어진 지점.

    리더의 heading 을 기준으로 잡는다 — 맵 좌표축이 아니다. 그래야 리더가
    회전해도 대형이 유지된다.
    """
    heading = (math.cos(reference.yaw), math.sin(reference.yaw))
    left = (-math.sin(reference.yaw), math.cos(reference.yaw))
    return NavGoalSpec(
        x=reference.x - distance * heading[0] + lateral * left[0],
        y=reference.y - distance * heading[1] + lateral * left[1],
        yaw=reference.yaw,
    )
