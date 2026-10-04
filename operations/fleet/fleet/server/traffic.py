"""경로 충돌 판정 — 두 로봇이 같은 좁은 곳에서 만날지 미리 본다.

왜 Fleet 이 하는가: 로봇의 코스트맵은 자기 주변만 본다. 상대가 아직 멀리 있으면 둘 다
같은 통로로 들어가는 계획을 세우고, 서로를 본 순간에는 이미 마주 보고 갇혀 있다. 폭
1.4 m 통로에서 pinky 두 대가 0.10 m 간격으로 멈춘 채 둘 다 실패한 것이 그 장면이다.
비켜설 자리가 있는지는 두 경로를 동시에 쥔 쪽만 알 수 있고, 그쪽이 Fleet 이다(D-12).

여기는 숫자만 다룬다 - 전송도 asyncio 도 없다. 판정이 순수해야 로봇을 건드리기 **전에**
부를 수 있고, 거절된 미션이 이미 달리던 미션을 흔들지 않는다.
"""

from __future__ import annotations

import math
from typing import Iterable, Optional, Sequence

#: 두 경로가 이보다 가까이 스치면 같은 자리를 두고 다툰다고 본다. pinky 풋프린트가
#: 0.12 m 이고 서로 비켜서려면 대략 두 대 폭 + 여유가 필요하다. 1.4 m 통로에서 이 값이면
#: 마주 오는 경로만 걸리고, 넓은 방에서 스쳐 지나가는 경로는 걸리지 않는다.
DEFAULT_CLEARANCE_M = 0.7

#: 경로는 5 cm 간격의 조밀한 폴리라인이다. 전부 비교하면 O(n*m) 이 수천 x 수천이 된다.
#: 20 cm 간격이면 충돌 판정에 충분하고 비교량은 1/16 로 줄어든다.
SAMPLE_STEP_M = 0.2

#: mover 와 같은 점으로 보고되면 길을 막았다고 말할 수 없다 (D-116).
#: 풋프린트(~0.12 m)보다 작고 factory spawn 간격(0.6 m)보다 훨씬 작다.
COINCIDENT_M = 0.05

Point = tuple[float, float]


def coincident(a: Point, b: Point, eps: float = COINCIDENT_M) -> bool:
    """두 보고가 같은 점인지. 측위 실패로 겹친 원점을 길로 보지 않기 위해 쓴다."""
    return math.dist(a, b) < eps


def route_points(payload: object) -> list[Point]:
    """로봇이 준 `/navigation/path` 응답에서 (x, y) 목록만 뽑는다.

    비어 있거나 모양이 다르면 빈 목록이다 - 경로를 모르면 충돌도 주장하지 않는다.
    """
    poses = payload.get("poses") if isinstance(payload, dict) else None
    if not isinstance(poses, list):
        return []
    out: list[Point] = []
    for pose in poses:
        if not isinstance(pose, dict):
            continue
        try:
            out.append((float(pose["x"]), float(pose["y"])))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def thin(points: Sequence[Point], step: float = SAMPLE_STEP_M) -> list[Point]:
    """`step` 보다 촘촘한 점은 버린다. 시작점과 끝점은 반드시 남긴다."""
    if not points:
        return []
    kept = [points[0]]
    for point in points[1:]:
        if math.dist(point, kept[-1]) >= step:
            kept.append(point)
    if kept[-1] != points[-1]:
        kept.append(points[-1])
    return kept


def closest_approach(a: Sequence[Point], b: Sequence[Point]) -> Optional[float]:
    """두 경로가 가장 가까워지는 거리. 한쪽이라도 비면 `None`."""
    if not a or not b:
        return None
    thin_a, thin_b = thin(a), thin(b)
    best = math.inf
    for point in thin_a:
        for other in thin_b:
            best = min(best, math.dist(point, other))
    return best


def routes_conflict(a: Sequence[Point], b: Sequence[Point],
                    clearance: float = DEFAULT_CLEARANCE_M) -> bool:
    """두 경로가 `clearance` 안으로 들어오면 충돌로 본다.

    경로를 모르면(빈 목록) 충돌이 아니다. 모른다는 이유로 미션을 막으면, 아직 계획을
    내지 못한 로봇 때문에 현장이 통째로 서 버린다.
    """
    approach = closest_approach(a, b)
    return approach is not None and approach < clearance


def blocking_robot(route: Sequence[Point], claims: dict[str, Sequence[Point]],
                   clearance: float = DEFAULT_CLEARANCE_M,
                   skip: Iterable[str] = ()) -> Optional[str]:
    """이 경로와 부딪히는 첫 로봇. 없으면 `None`.

    순서를 robot_id 로 고정한다 - 같은 상황에서 늘 같은 대가 양보해야 운영자가 화면을
    읽을 수 있고, 두 대가 서로 양보하다 둘 다 서는 일도 없다.
    """
    skipped = set(skip)
    for robot_id in sorted(claims):
        if robot_id in skipped:
            continue
        if routes_conflict(route, claims[robot_id], clearance):
            return robot_id
    return None


def closest_points(a: Sequence[Point], b: Sequence[Point]) -> Optional[tuple[Point, Point]]:
    """두 경로가 가장 가까워지는 지점 쌍. 한쪽이 비면 `None`.

    도로의 교차로다. 선착 판정(누가 그 자리에 먼저 도달하나)은 이 지점을 기준으로
    한다 - `remaining_distance` 와 함께 쓴다.
    """
    if not a or not b:
        return None
    best: Optional[tuple[Point, Point]] = None
    best_d = math.inf
    for pa in thin(a):
        for pb in thin(b):
            d = math.dist(pa, pb)
            if d < best_d:
                best_d = d
                best = (pa, pb)
    return best


def remaining_distance(route: Sequence[Point], pose: Optional[Point],
                       target: Optional[Point]) -> Optional[float]:
    """경로 위 `pose` 에서 경로 위 `target` 까지 남은 경로 거리. m.

    판정할 수 없으면 `None` 이고, 부른 쪽은 무한대로 읽는다 — 모른다는 이유로
    순서를 뒤집지 않는다(빈 경로를 "아무도 안 막는다"로 읽던 원칙과 같다). `target`
    이 아직 안 온 시작점 뒤면(지나쳤거나 다른 경로 위 점이면) 역시 `None`이다.
    """
    if not route or pose is None or target is None:
        return None
    thin_route = thin(route)
    start = min(range(len(thin_route)), key=lambda i: math.dist(thin_route[i], pose))
    goal = min(range(len(thin_route)), key=lambda i: math.dist(thin_route[i], target))
    if goal <= start:
        return None
    return sum(math.dist(thin_route[i], thin_route[i + 1])
               for i in range(start, goal))
