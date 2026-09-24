"""core.bridge.goal_tracker — Nav2 목표 세대 관리. ROS 무의존.

`goal()` 이 진행 중 재목표를 막던 동안에는 액션 핸들이 항상 하나였고, 브리지는
`_goal_handle` 하나로 충분했다. SWM-001 의 moving goal 이 그 전제를 깼다:
2 Hz 로 목표를 갈아끼우면 선점된 목표의 결과가 뒤늦게 도착하고, 그것을 최신
목표의 결과로 읽으면 두 가지가 무너진다 —

1. 선점 결과(abort)가 nav_state 를 FAILED 로 떨어뜨려 SWM-004 HOLD 의 취소가
   `NavigationManager.cancel` 의 early-return 에 걸린다. 로봇은 계속 달린다.
2. 결과 콜백이 핸들을 지워버려, 정작 살아 있는 목표를 취소할 수단이 사라진다.

그래서 목표에 세대(generation)를 붙이고, **살아 있는 핸들 전부**를 들고 있는다.
여기에는 rclpy 가 없다 — 핸들은 그냥 불투명한 객체다.
"""

from __future__ import annotations

import threading
from typing import Any


class GoalTracker:
    """어떤 결과가 현재 목표의 것인지, 무엇을 취소해야 하는지."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._generation = 0
        self._live: dict[int, Any] = {}

    @property
    def live_count(self) -> int:
        with self._lock:
            return len(self._live)

    def opening(self) -> int:
        """목표를 보내기 직전. 이 세대 번호를 콜백까지 들고 간다."""
        with self._lock:
            self._generation += 1
            return self._generation

    def accepted(self, generation: int, handle: Any) -> bool:
        """액션 서버가 받아들였다.

        현재 세대면 등록하고 True. 지난 세대면 **등록하지 않고** False 다 —
        호출자는 그 핸들을 바로 취소해야 한다. 등록해 버리면 send 와 accept
        사이에 취소된 목표가 살아남는다: 취소 시점에는 아직 핸들이 없어
        아무것도 못 거두고, 뒤늦게 도착한 수락이 그것을 되살린다.
        """
        with self._lock:
            if generation != self._generation:
                return False
            self._live[generation] = handle
            return True

    def rejected(self, generation: int) -> bool:
        with self._lock:
            self._live.pop(generation, None)
            return generation == self._generation

    def finished(self, generation: int) -> bool:
        """결과 도착. 현재 세대면 True, 선점된 목표의 뒤늦은 결과면 False."""
        with self._lock:
            self._live.pop(generation, None)
            return generation == self._generation

    def cancel_all(self) -> list[Any]:
        """취소해야 할 핸들 전부. 세대를 올려 이후 도착하는 결과를 전부 stale 로 만든다.

        핸들 하나만 들고 있으면 send 와 accept 사이의 목표를 놓친다 — 그
        창에서 취소하면 아무것도 취소되지 않은 채 상태만 CANCELED 가 된다.
        """
        with self._lock:
            handles = list(self._live.values())
            self._live.clear()
            self._generation += 1
            return handles


def on_response(goals: GoalTracker, nav, future, generation: int, *,
                attach_result) -> None:
    """Send-goal future → 수락·거절, 그리고 지나간 세대의 수락 차단.

    rclpy 없이 전부 확인할 수 있도록 핸들은 불투명 객체다. `attach_result`
    (result future 를 이 세대에 묶는 일)만 브리지가 준다 — 그쪽이 ROS 다.
    """
    goal_handle = future.result()
    if goal_handle is None or not goal_handle.accepted:
        if goals.rejected(generation):
            nav.on_result(False, "REJECTED")
        return
    if not goals.accepted(generation, goal_handle):
        # 이미 지나간 목표의 수락이다(선점됐거나, 보내는 사이 취소됐다).
        # 살려두면 아무도 거두지 않는 Nav2 목표가 남는다.
        goal_handle.cancel_goal_async()
        return
    nav.on_goal_accepted()
    attach_result(goal_handle.get_result_async(), generation)


def on_result(goals: GoalTracker, nav, future, generation: int) -> None:
    """Result future → `nav.on_result`. 선점된 목표의 뒤늦은 결과는 무시한다.

    `result.status == 4` 는 `GoalStatus.STATUS_SUCCEEDED` 다 — rclpy 는
    성공 여부가 아니라 상태 코드를 주므로 그 비교가 전부다.
    """
    if not goals.finished(generation):
        # 선점된 목표의 뒤늦은 결과. moving goal 에서는 abort 로 끝나며,
        # 이것을 현재 목표의 실패로 읽으면 nav_state 가 FAILED 로 떨어져
        # 이어지는 HOLD 의 취소가 통째로 무시된다.
        return
    try:
        result = future.result()
        nav.on_result(result.status == 4)
    except Exception as exc:
        nav.on_result(False, str(exc))
