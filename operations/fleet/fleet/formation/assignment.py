"""fleet.formation.assignment — FOR-002 슬롯 배정 (순수 함수).

거리 기반 그리디가 v1 이다. FOR-002 는 알고리즘을 인터페이스 뒤에 두어 Hungarian
으로 바꿀 수 있어야 한다고 했으므로, 인터페이스가 먼저고 구현은 그중 하나다.
"""

from __future__ import annotations

import math
from typing import Mapping, Protocol, Sequence, runtime_checkable

from fleet.formation.geometry import Point


class AssignmentError(ValueError):
    """배정할 수 없는 입력."""


@runtime_checkable
class SlotAssigner(Protocol):
    def assign(self, robots: Mapping[str, Point], slots: Sequence[Point]) -> dict[str, int]:
        """`robot_id → slot index`. 전단사여야 한다."""
        ...


class GreedyDistanceAssigner:
    """모든 (로봇, 슬롯) 쌍을 거리 오름차순으로 훑어, 둘 다 비어 있으면 짝짓는다.

    최적은 아니지만 결정적이다: 거리가 같으면 robot_id, 그다음 슬롯 번호로 가른다.
    그래서 입력 dict 의 순서가 결과를 바꾸지 않는다.
    """

    def assign(self, robots: Mapping[str, Point], slots: Sequence[Point]) -> dict[str, int]:
        if len(robots) != len(slots):
            raise AssignmentError(
                f"{len(robots)} robots for {len(slots)} slots — the formation must have one "
                "slot per follower")
        for robot_id, pos in robots.items():
            if not all(math.isfinite(v) for v in pos):
                raise AssignmentError(f"robot {robot_id!r} has a non-finite position {pos}")
        for j, slot in enumerate(slots):
            if not all(math.isfinite(v) for v in slot):
                raise AssignmentError(f"slot {j} has a non-finite position {slot}")
        pairs = sorted(
            (math.dist(pos, slots[j]), robot_id, j)
            for robot_id, pos in robots.items()
            for j in range(len(slots))
        )
        taken_robots: set[str] = set()
        taken_slots: set[int] = set()
        out: dict[str, int] = {}
        for _, robot_id, j in pairs:
            if robot_id in taken_robots or j in taken_slots:
                continue
            out[robot_id] = j
            taken_robots.add(robot_id)
            taken_slots.add(j)
        return out
