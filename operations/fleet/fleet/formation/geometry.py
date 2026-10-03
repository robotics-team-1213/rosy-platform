"""fleet.formation.geometry — FOR-001 대형을 슬롯 오프셋으로 (순수 함수).

팔로워는 리더 heading 기준 `(distance, lateral)` 오프셋을 받는다
(`core_features.swarm.follow_goal`). 모든 정적 대형은 그 오프셋의 집합이므로
로봇 계약을 바꾸지 않고 여기서 끝난다. 이 모듈은 전송도 로봇도 모른다 — 입력은
숫자, 출력은 숫자다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Callable

#: 두 로봇이 가장 가까워지는 거리의 하한. LINE 과 GRID 앞줄은 팔로워를 리더와 나란히
#: 세우므로 이 값이 그대로 로봇 사이 거리다. Nav2 는 목표점이 아니라 **팔로워의
#: footprint** 로 충돌을 검사하므로 하한은
#:   inflation_radius + 리더 외접반경 + 팔로워 외접반경 + footprint_padding
#:   = 0.15 + 0.085 + 0.085 + 0.03 ≈ 0.35 m
#: 이다 (`src/navigation/params/nav2_params.yaml`: footprint 반폭 6 cm(한 변 12 cm) 정사각 → 외접반경
#: 0.085, inflation_radius 0.15, global costmap footprint_padding 0.03). 0.4 는 그 위로
#: 약 5 cm 여유다 — 넉넉하지 않다. Nav2 파라미터가 바뀌면 이 식으로 다시 계산한다.
MIN_SPACING = 0.4
DEFAULT_SPACING = 0.6

Point = tuple[float, float]


class Formation(str, Enum):
    FOLLOW = "FOLLOW"
    COLUMN = "COLUMN"
    LINE = "LINE"
    V = "V"
    GRID = "GRID"
    CIRCLE = "CIRCLE"


class FormationError(ValueError):
    """대형을 만들 수 없는 파라미터."""


@dataclass(frozen=True)
class SlotOffset:
    """리더 heading 기준 슬롯. `distance` 는 리더 뒤(+), `lateral` 은 리더 왼쪽(+), m."""

    distance: float
    lateral: float


def _side(k: int) -> float:
    """k 번째 팔로워의 좌우. 홀수는 왼쪽(+), 짝수는 오른쪽(−)."""
    return 1.0 if k % 2 == 1 else -1.0


def _rank(k: int) -> int:
    """좌우 교대에서 k 번째 팔로워가 리더에서 몇 칸 떨어지는지."""
    return math.ceil(k / 2)


def _column(n: int, s: float, _cols: int) -> list[SlotOffset]:
    return [SlotOffset(k * s, 0.0) for k in range(1, n + 1)]


def _line(n: int, s: float, _cols: int) -> list[SlotOffset]:
    return [SlotOffset(0.0, _side(k) * _rank(k) * s) for k in range(1, n + 1)]


def _v(n: int, s: float, _cols: int) -> list[SlotOffset]:
    return [SlotOffset(_rank(k) * s, _side(k) * _rank(k) * s) for k in range(1, n + 1)]


def _grid(n: int, s: float, cols: int) -> list[SlotOffset]:
    # 리더가 인덱스 0 (앞줄 왼쪽 끝). 팔로워 k 는 인덱스 k. 열은 오른쪽(−)으로 채운다.
    return [SlotOffset((k // cols) * s, -(k % cols) * s) for k in range(1, n + 1)]


def _circle(n: int, s: float, _cols: int) -> list[SlotOffset]:
    # 리더를 포함한 n+1 점을 원 위에 등간격으로. 인접 점 사이의 **현** 길이가 s 다 —
    # 두 로봇 사이의 직선 거리가 하한을 넘어야 하기 때문이다(호 길이가 아니다).
    total = n + 1
    r = s / (2.0 * math.sin(math.pi / total))
    # 리더는 각도 0 에 있고 원의 중심은 리더 뒤 r 에 있다. 점 θ 의 리더 기준 좌표:
    # 뒤로 r(1 − cos θ), 왼쪽으로 r sin θ.
    out = []
    for k in range(1, n + 1):
        theta = 2.0 * math.pi * k / total
        out.append(SlotOffset(r - r * math.cos(theta), r * math.sin(theta)))
    return out


_GENERATORS: dict[Formation, Callable[[int, float, int], list[SlotOffset]]] = {
    Formation.FOLLOW: _column,
    Formation.COLUMN: _column,
    Formation.LINE: _line,
    Formation.V: _v,
    Formation.GRID: _grid,
    Formation.CIRCLE: _circle,
}


def slots(formation: Formation, followers: int, spacing: float, *,
          grid_cols: int = 2) -> list[SlotOffset]:
    """`followers` 명의 팔로워 슬롯. 리더는 슬롯 0 이며 반환 목록에 들어가지 않는다."""
    try:
        formation = Formation(formation)
    except ValueError as exc:
        raise FormationError(f"unknown formation {formation!r}") from exc
    if not math.isfinite(spacing) or spacing < MIN_SPACING:
        raise FormationError(
            f"spacing {spacing} is below the floor {MIN_SPACING} m — the follower's goal "
            "would sit inside the leader's inflated footprint")
    if followers < 1:
        raise FormationError("a formation needs at least one follower")
    if formation is Formation.FOLLOW and followers != 1:
        raise FormationError("FOLLOW is a single follower; use COLUMN for more")
    if grid_cols < 1:
        raise FormationError("grid_cols must be at least 1")
    return _GENERATORS[formation](followers, spacing, grid_cols)


def slot_world_position(offset: SlotOffset, x: float, y: float, yaw: float) -> Point:
    """리더 pose `(x, y, yaw)` 에서 슬롯의 월드 좌표. `follow_goal` 과 같은 식이다."""
    heading = (math.cos(yaw), math.sin(yaw))
    left = (-math.sin(yaw), math.cos(yaw))
    return (
        x - offset.distance * heading[0] + offset.lateral * left[0],
        y - offset.distance * heading[1] + offset.lateral * left[1],
    )
