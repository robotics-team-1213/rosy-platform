"""비켜설 자리 — 맵을 읽어 실제로 공간을 만든다.

`traffic` 은 순서를 만든다. 늦게 온 미션을 세워 두면 앞의 로봇이 통로를 비우고, 그때
대기 미션이 나간다. 그것으로 풀리지 않는 장면이 하나 있다 — **서 있는 로봇이 상대의
목표 자리를 깔고 앉은 경우**다. 2x1 m 방에서 두 대가 자리를 맞바꾸는 미션이 그것이다.
A 는 B 가 선 곳으로 가야 하고 B 는 A 가 선 곳으로 가야 하는데, 대기열은 "앞이 끝나면
간다"고만 말한다. 앞은 끝나지 않는다 — 끝나려면 뒤가 비켜야 하기 때문이다.

그래서 여기서는 순서가 아니라 **자리**를 찾는다. 점유 격자에서 (1) 로봇이 설 만큼 넓고
(2) 상대 경로에서 충분히 떨어져 있고 (3) 지금 자리에서 걸어갈 수 있는 칸을 고른다.
가장 가까운 것 하나면 된다 — 비켜서는 거리는 짧을수록 좋다.

**폭은 면제 사유가 아니다 (D-93).** 한때 "이 통로는 충분히 넓으니 Fleet 이 빠져도
된다"는 기준이 여기 있었다. 실측이 그것을 부정했다 - 6 x 6 m 빈 방에서 마주 오는 두
대가 3 번 다 방 한가운데에서 0.13~0.17 m 간격으로 맞물려 섰다. 로봇 폭(0.111 m)의
54 배 공간이다. RPP 는 옆으로 피하지 않고 앞이 막히면 서며, 두 대가 대칭이라 같은 쪽으로
돌고 거기서 다시 만난다. 그래서 면제가 성립하는 폭은 없다.

과잉 개입을 막는 것은 폭이 아니라 **경로**다. 계획 경로는 이미 아는 장애물을 피해
나오므로, 그런데도 경로가 선 로봇 가까이를 지난다면 돌아갈 자리가 없다는 뜻이다.

**없으면 없다고 말한다.** 폭 1 m 방에는 그런 칸이 없고, 이 모듈은 그때 `None` 을
돌려준다. 관제는 그것을 "길이 막혔는데 비켜설 자리가 없다"로 운영자에게 보여야 한다 —
있는 척하고 로봇을 벽으로 보내는 것보다 낫다.

전송도 asyncio 도 없다. 숫자만 다루므로 로봇을 건드리기 **전에** 부를 수 있다.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

Point = tuple[float, float]
Cell = tuple[int, int]

#: 점유 확률이 이 이상이면 벽이다. nav2 가 맵 서버에 쓰는 `occupied_thresh` 0.65 와
#: 같은 자리를 노린다 - 계획기가 벽으로 보는 칸을 여기서 빈 칸으로 보면 안 된다.
OCCUPIED_COST = 65

#: pinky 의 외접 반지름. 풋프린트 반폭 0.06 에 바퀴와 범퍼 여유를 더해 잡는다. 이보다
#: 좁은 칸은 "설 수 있는 자리"가 아니다.
ROBOT_RADIUS_M = 0.12


#: 비켜선 로봇이 상대 경로에서 떨어져 있어야 하는 거리. 지나가는 쪽 반폭 0.12 에
#: 비켜선 쪽 반폭 0.12, 그리고 측위 오차와 벽 쏠림 몫 0.2 를 더한 값이다.
#:
#: `traffic.DEFAULT_CLEARANCE_M` (0.7) 을 그대로 쓰지 않는 이유가 있다. 그쪽은 **경로 대
#: 경로** 판정이고, 마주 오는 두 계획을 미리 갈라 놓는 값이라 후해도 된다. 여기는 **선
#: 로봇 대 경로**다 - 0.7 을 요구하면 폭 1 m 통로 옆 벽감은 전부 탈락하고, 비켜설 자리가
#: 실제로 있는 맵에서도 늘 "자리 없음"이 된다.
YIELD_KEEP_OUT_M = 0.45

#: 비켜서느라 이보다 멀리 가야 한다면 그것은 양보가 아니라 또 하나의 미션이다.
MAX_DETOUR_M = 3.0

#: 가장 가까운 자리를 찾은 뒤 이만큼 더 보고 더 깊은 자리를 고른다. 벽감 입구에 선 로봇은
#: 통로를 아직 좁힌다 - 0.5 m 더 들어가는 값으로 지나가는 쪽이 훨씬 편해진다.
BAY_SLACK_M = 0.5

#: 대피 지점은 해제 기준(`keep_out_m`)보다 **이만큼 더** 멀어야 한다.
#:
#: 이것이 없으면 교착이 생긴다. 실측 - 2x1 m 방에서 경로로부터 0.48 m 떨어진 자리를
#: 골랐는데(기준 0.45 통과), 로봇은 목표에 0.13 m 못 미쳐 섰고 AMCL 은 0.18 m 틀렸다.
#: 보고 위치는 경로에서 0.18 m 였고, 기다리던 미션의 해제 조건은 "0.45 m 밖"이었다.
#: 둘 다 영원히 서서 화면은 "물러나면 자동 출발합니다"라고 거짓말을 했다.
#:
#: 값은 그 실측과 반대쪽 실측 사이에서 고른다. 문제가 된 자리는 0.48 m 였고, 폭 1 m
#: 통로 옆 0.3 m 벽감의 자리는 0.65 m 다 - 뒤쪽은 살려야 한다. 0.15 는 앞을 버리고 뒤를
#: 남긴다. 이 값으로도 못 막는 경우는 콘솔의 `_check_yield_worked` 가 받는다 - 여백을
#: 더 키우면 쓸 만한 벽감이 통째로 탈락하고, 자리가 있는 맵에서도 "자리 없음"이 된다.
BAY_MARGIN_M = 0.15

#: 자유 폭은 이 위로는 재지 않는다. 넓은 방 한가운데의 정확한 값은 쓸 데가 없고,
#: 상한이 있어야 거리장을 계산할 창을 유한하게 잡을 수 있다.
CAP_M = 2.2

_SQRT2 = math.sqrt(2.0)


@dataclass(frozen=True)
class Grid:
    """MAP-003 점유 격자 위의 좌표 변환. 페이로드를 복사하지 않고 그대로 읽는다."""

    width: int
    height: int
    resolution: float
    origin_x: float
    origin_y: float
    origin_yaw: float
    data: Sequence[int]

    @classmethod
    def from_payload(cls, payload: object) -> Optional["Grid"]:
        """격자 스냅샷 → `Grid`. 모양이 아니면 `None` 이다 - 맵이 없으면 판단도 없다."""
        if not isinstance(payload, dict):
            return None
        try:
            width = int(payload["width"])
            height = int(payload["height"])
            resolution = float(payload["resolution"])
            data = payload["data"]
        except (KeyError, TypeError, ValueError):
            return None
        if width <= 0 or height <= 0 or resolution <= 0:
            return None
        if not isinstance(data, (list, tuple)) or len(data) < width * height:
            return None
        origin = payload.get("origin") or {}
        try:
            ox = float(origin.get("x", 0.0))
            oy = float(origin.get("y", 0.0))
            oyaw = float(origin.get("yaw", 0.0))
        except (TypeError, ValueError):
            return None
        return cls(width, height, resolution, ox, oy, oyaw, data)

    def cell_of(self, point: Point) -> Cell:
        dx = point[0] - self.origin_x
        dy = point[1] - self.origin_y
        cos_y, sin_y = math.cos(-self.origin_yaw), math.sin(-self.origin_yaw)
        gx = dx * cos_y - dy * sin_y
        gy = dx * sin_y + dy * cos_y
        return int(math.floor(gx / self.resolution)), int(math.floor(gy / self.resolution))

    def point_of(self, cell: Cell) -> Point:
        """칸의 **중심**. 모서리를 돌려주면 로봇이 칸 경계로 가서 반 칸만큼 벽에 붙는다."""
        gx = (cell[0] + 0.5) * self.resolution
        gy = (cell[1] + 0.5) * self.resolution
        cos_y, sin_y = math.cos(self.origin_yaw), math.sin(self.origin_yaw)
        return (self.origin_x + gx * cos_y - gy * sin_y,
                self.origin_y + gx * sin_y + gy * cos_y)

    def blocked(self, cx: int, cy: int) -> bool:
        """벽이거나, 모르는 곳이거나, 격자 밖.

        **모르는 칸도 막힌 것으로 센다.** 아직 못 본 곳으로 로봇을 비켜세우면, 비켜선
        자리가 벽 속일 수 있다. 맵이 자란 뒤에 다시 고르면 된다.
        """
        if cx < 0 or cy < 0 or cx >= self.width or cy >= self.height:
            return True
        value = self.data[cy * self.width + cx]
        return value < 0 or value >= OCCUPIED_COST


@dataclass(frozen=True)
class _Window:
    """거리장을 계산할 격자 구간(칸 단위, 양 끝 포함)."""

    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def w(self) -> int:
        return self.x1 - self.x0 + 1

    @property
    def h(self) -> int:
        return self.y1 - self.y0 + 1

    def holds(self, cx: int, cy: int) -> bool:
        return self.x0 <= cx <= self.x1 and self.y0 <= cy <= self.y1


def _window_for(grid: Grid, points: Iterable[Point], reach_m: float,
                cap_m: float = CAP_M) -> _Window:
    """관심 영역 + 여유. 창 밖의 벽은 거리장에 안 잡히므로 상한만큼 더 넓게 잡는다."""
    cells = [grid.cell_of(p) for p in points]
    pad = int(math.ceil((reach_m + cap_m) / grid.resolution)) + 2
    xs = [c[0] for c in cells] or [0]
    ys = [c[1] for c in cells] or [0]
    return _Window(min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)


def _clearance_field(grid: Grid, window: _Window) -> list[float]:
    """창 안 각 칸에서 가장 가까운 막힌 칸까지의 거리(m).

    8SSED - 벡터를 두 번 훑으며 전파한다. 유클리드 거리 변환을 창 크기에 비례하는 비용으로
    얻는다. 창은 경로 길이가 정한다 - 실측으로 공장 맵(4x3 m) 전체가 47 ms, 40x40 m 맵의
    20 m 경로가 0.38 s 다. 그래서 호출하는 쪽은 이것을 스레드로 넘긴다.
    """
    w, h = window.w, window.h
    far = 1 << 14
    vx = [0] * (w * h)
    vy = [0] * (w * h)
    for j in range(h):
        row = j * w
        cy = window.y0 + j
        for i in range(w):
            if not grid.blocked(window.x0 + i, cy):
                vx[row + i] = far
                vy[row + i] = far

    def relax(idx: int, src: int, dx: int, dy: int) -> None:
        ax, ay = vx[src] + dx, vy[src] + dy
        if ax * ax + ay * ay < vx[idx] * vx[idx] + vy[idx] * vy[idx]:
            vx[idx], vy[idx] = ax, ay

    for j in range(h):
        row = j * w
        prev = row - w
        for i in range(w):
            idx = row + i
            if vx[idx] == 0 and vy[idx] == 0:
                continue
            if j > 0:
                relax(idx, prev + i, 0, 1)
                if i > 0:
                    relax(idx, prev + i - 1, 1, 1)
                if i + 1 < w:
                    relax(idx, prev + i + 1, 1, 1)
            if i > 0:
                relax(idx, idx - 1, 1, 0)
    for j in range(h - 1, -1, -1):
        row = j * w
        nxt = row + w
        for i in range(w - 1, -1, -1):
            idx = row + i
            if vx[idx] == 0 and vy[idx] == 0:
                continue
            if j + 1 < h:
                relax(idx, nxt + i, 0, 1)
                if i > 0:
                    relax(idx, nxt + i - 1, 1, 1)
                if i + 1 < w:
                    relax(idx, nxt + i + 1, 1, 1)
            if i + 1 < w:
                relax(idx, idx + 1, 1, 0)

    res = grid.resolution
    return [math.hypot(vx[k], vy[k]) * res for k in range(w * h)]


def free_width_at(grid: Grid, point: Point, cap_m: float = CAP_M) -> float:
    """이 지점의 자유 폭(m) - 가장 가까운 벽까지 거리의 두 배. `cap_m` 에서 자른다.

    점이 벽 안이면 0 이다. 상한을 두는 이유는 넓은 방 한가운데의 정확한 값이 판단을
    바꾸지 않기 때문이다 - "두 대가 지나갈 수 있는가"만 알면 된다.
    """
    cx, cy = grid.cell_of(point)
    if grid.blocked(cx, cy):
        return 0.0
    reach = int(math.ceil(cap_m / grid.resolution)) + 1
    best = float(reach)
    for dy in range(-reach, reach + 1):
        for dx in range(-reach, reach + 1):
            if grid.blocked(cx + dx, cy + dy):
                d = math.hypot(dx, dy)
                if d < best:
                    best = d
    # 칸 중심끼리 잰 값이라 반 칸만큼 후하다. 좁은 쪽으로 깎는다.
    metres = max(0.0, best * grid.resolution - grid.resolution * 0.5)
    return min(cap_m, metres * 2.0)


def nearest_on_route(route: Sequence[Point], point: Point) -> Optional[Point]:
    """경로에서 이 점과 가장 가까운 지점. 경로가 비면 `None`."""
    if not route:
        return None
    return min(route, key=lambda p: math.dist(p, point))


def best_bay(grid: Optional[Grid], route: Sequence[Point], robot_xy: Point, *,
             keep_out_m: float, robot_radius_m: float = ROBOT_RADIUS_M,
             max_detour_m: float = MAX_DETOUR_M,
             slack_m: float = BAY_SLACK_M,
             margin_m: float = BAY_MARGIN_M) -> Optional[Point]:
    """`robot_xy` 에 선 로봇이 `route` 를 비켜 줄 가장 가까운 자리. 없으면 `None`.

    고르는 조건 셋. 로봇이 설 만큼 넓고(`robot_radius_m`), 경로에서
    `keep_out_m + margin_m` 이상 떨어져 있고, 지금 자리에서 좁은 목을 지나지 않고 갈 수
    있어야 한다. 마지막 조건이 없으면 벽 건너편의 넓은 자리를 골라 놓고 로봇은 영영
    도착하지 못한다. 가운데 조건에 `margin_m` 이 붙은 이유는 `BAY_MARGIN_M` 에 적었다 -
    해제 기준과 같은 값으로 자리를 고르면 교착이 생긴다.

    다익스트라를 쓰는 이유는 하나다 - 비용이 낮은 칸부터 나오므로 창 전체를 훑지 않고도
    가까운 후보부터 손에 넣는다. 다만 **첫 후보를 그대로 쓰지는 않는다.** 가장 가까운
    자리는 보통 벽감 **입구**이고, 거기 선 로봇은 통로를 아직 좁힌다. 첫 후보가 나온 뒤
    `slack_m` 만큼 더 보고, 그 안에서 경로에서 가장 먼 자리를 고른다 - 몇십 cm 더 들어가는
    값으로 지나가는 쪽이 벽과 로봇 사이를 비집지 않아도 된다.
    """
    if grid is None or not route:
        return None
    window = _window_for(grid, list(route) + [robot_xy], max_detour_m)
    field = _clearance_field(grid, window)

    def clearance(cx: int, cy: int) -> float:
        if not window.holds(cx, cy):
            return 0.0
        return field[(cy - window.y0) * window.w + (cx - window.x0)]

    start = grid.cell_of(robot_xy)
    if grid.blocked(*start):
        # 보고된 pose 가 벽 안이면(측위가 튀었거나 맵이 낡았으면) 비켜설 자리를 고를
        # 근거가 없다. 조용히 아무 데나 보내는 것보다 모른다고 하는 편이 낫다.
        return None

    needed = keep_out_m + margin_m
    res = grid.resolution
    seen: set[Cell] = set()
    # 출발 칸은 여유 조건을 묻지 않고 넣는다 - 로봇은 이미 거기 서 있다. 맵 잡음 때문에
    # 제자리가 "못 서는 칸"으로 나오면 탐색이 시작도 못 한다.
    queue: list[tuple[float, int, int]] = [(0.0, start[0], start[1])]
    budget = max_detour_m
    #: (경로에서 떨어진 거리, 비용, 자리). 비용은 같은 거리일 때 가까운 쪽을 고르는 데 쓴다.
    best: Optional[tuple[float, float, Point]] = None
    while queue:
        cost, cx, cy = heapq.heappop(queue)
        if (cx, cy) in seen:
            continue
        seen.add((cx, cy))
        if cost > budget:
            break
        point = grid.point_of((cx, cy))
        if cost > 0.0 and clearance(cx, cy) >= robot_radius_m:
            nearest = nearest_on_route(route, point)
            off_route = math.inf if nearest is None else math.dist(nearest, point)
            if off_route >= needed:
                if best is None:
                    # 첫 후보가 나왔다. 이제부터는 조금 더 들어간 자리를 찾을 여지만 본다.
                    budget = min(budget, cost + slack_m)
                if best is None or (off_route, -cost) > (best[0], -best[1]):
                    best = (off_route, cost, point)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = cx + dx, cy + dy
                if (nx, ny) in seen or not window.holds(nx, ny):
                    continue
                # 지나가는 칸에도 같은 여유를 건다 - 로봇이 통과할 수 없는 틈으로
                # 이어진 자리는 갈 수 없는 자리다.
                if clearance(nx, ny) < robot_radius_m:
                    continue
                step = res * (_SQRT2 if dx and dy else 1.0)
                heapq.heappush(queue, (cost + step, nx, ny))
    return None if best is None else best[2]
