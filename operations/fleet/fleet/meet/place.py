"""260919 차선 위에 자세를 올리고, 주문 하나를 회전·직진 한 구간으로 바꾼다.

폴리라인은 활성 현장 지도(D-484 `rosy.site_map/1`)에서 읽는다. 방과 문은 D-451 의 자리다.
선에서 0.08 m 보다 멀면 그 선 위가 아니다. (0, 0) 은 고리에서 약 0.084 m 라
여기에 올라가지 않는다. 헤딩이 접선과 60° 안이면 그 방향이고, 아니면
신뢰하지 않는다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from fleet.meet.scene import Action, Door, Edge, Order, Pin, Robot, Room, Scene

MAX_OFF_M = 0.08
ROOM_AT_M = 0.12
HEADING_CONE = math.pi / 3
ALONG_FIRST_M = 0.20
DONE_M = 0.05
YIELD_MAX_M = 2.0

# (hold xy, clearance, edge, door xy). 문 s 는 그 점을 선에 올린 거리다.
_ROOMS = (
    ("west_spot", (-1.0, 0.0), 0.27, "west", (-1.2696, 0.0)),
    ("east_room", (0.65, 0.30), 0.32, "east", (0.327, 0.301)),
)


def _wrap(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


@dataclass(frozen=True)
class Place:
    """한 자세를 올린 결과. `direction` 은 선의 진행이고, `yaw` 는 로봇이 보는 쪽이다."""

    edge_id: str | None
    s_m: float
    direction: int
    trusted: bool
    room_id: str | None
    x: float
    y: float
    yaw: float


@dataclass(frozen=True)
class _Line:
    id: str
    oneway: bool
    points: tuple[tuple[float, float], ...]
    knots: tuple[float, ...]
    start: str = ""
    end: str = ""

    @property
    def length_m(self) -> float:
        return self.knots[-1]

    def project(self, x: float, y: float) -> tuple[float, float, float]:
        """가장 가까운 점의 (거리, s, 접선 각)."""
        best: tuple[float, float, float] | None = None
        for index in range(len(self.points) - 1):
            ax, ay = self.points[index]
            bx, by = self.points[index + 1]
            dx, dy = bx - ax, by - ay
            length = math.hypot(dx, dy)
            if length == 0.0:
                continue
            t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (length * length)))
            px, py = ax + t * dx, ay + t * dy
            dist = math.hypot(x - px, y - py)
            if best is None or dist < best[0]:
                best = (dist, self.knots[index] + t * length, math.atan2(dy, dx))
        if best is None:
            raise ValueError(f"edge {self.id} has no segment")
        return best

    def point_at(self, s_m: float) -> tuple[float, float, float]:
        s_m = min(max(s_m, 0.0), self.length_m)
        for index in range(len(self.points) - 1):
            end = self.knots[index + 1]
            if s_m > end and index + 1 < len(self.points) - 1:
                continue
            span = end - self.knots[index]
            t = 0.0 if span == 0.0 else (s_m - self.knots[index]) / span
            ax, ay = self.points[index]
            bx, by = self.points[index + 1]
            return ax + t * (bx - ax), ay + t * (by - ay), math.atan2(by - ay, bx - ax)
        ax, ay = self.points[-1]
        return ax, ay, 0.0


@dataclass(frozen=True)
class Painted:
    lines: tuple[_Line, ...]
    rooms: tuple[Room, ...]
    doors: tuple[Door, ...]

    def line(self, edge_id: str) -> _Line:
        for item in self.lines:
            if item.id == edge_id:
                return item
        raise KeyError(edge_id)

    def scene(self, robots: tuple[Robot, ...] = (), pins: tuple[Pin, ...] = ()) -> Scene:
        return Scene(
            edges=tuple(Edge(item.id, item.length_m, item.oneway) for item in self.lines),
            rooms=self.rooms,
            doors=self.doors,
            robots=robots,
            pins=pins,
        )


def painted_from(site_map) -> Painted:
    """Lines from a ``fleet.site_map.SiteMap``. A D-451 room is kept only when its edge exists."""
    lines = []
    for edge in site_map.edges:
        points = tuple((float(x), float(y)) for x, y in edge.polyline)
        knots = [0.0]
        for start, end in zip(points, points[1:]):
            knots.append(knots[-1] + math.hypot(end[0] - start[0], end[1] - start[1]))
        lines.append(_Line(edge.id, edge.direction == "one_way", points, tuple(knots), edge.from_, edge.to))
    doors: list[Door] = []
    rooms: list[Room] = []
    for room_id, hold, clearance, edge_id, door_xy in _ROOMS:
        line = next((item for item in lines if item.id == edge_id), None)
        if line is None:
            continue
        _dist, s_m, _tangent = line.project(door_xy[0], door_xy[1])
        rooms.append(Room(room_id, hold, clearance))
        doors.append(Door(edge_id, s_m, room_id))
    return Painted(tuple(lines), tuple(rooms), tuple(doors))


_ACTIVE: Painted | None = None


def use_painted(painted: Painted | None) -> None:
    """The site map store sets this on start-up and on every activation."""
    global _ACTIVE
    _ACTIVE = painted


def painted_track() -> Painted | None:
    """The active site map's lines, or None while no site map is active."""
    return _ACTIVE


def _heading(yaw: float, tangent: float) -> tuple[int, bool]:
    delta = _wrap(yaw - tangent)
    if abs(delta) <= HEADING_CONE:
        return 1, True
    if abs(_wrap(delta - math.pi)) <= HEADING_CONE:
        return -1, True
    return 1, False


def project(painted: Painted, x: float, y: float, yaw: float) -> Place | None:
    """선 위이거나 방 정차 안이면 자리를 돌려준다. 둘 다 아니면 None."""
    nearest: tuple[float, _Line, float, float] | None = None
    for line in painted.lines:
        dist, s_m, tangent = line.project(x, y)
        if nearest is None or dist < nearest[0]:
            nearest = (dist, line, s_m, tangent)
    for room in painted.rooms:
        if math.hypot(x - room.hold_xy[0], y - room.hold_xy[1]) <= ROOM_AT_M:
            return Place(None, 0.0, 1, True, room.id, x, y, yaw)
    if nearest is None or nearest[0] > MAX_OFF_M:
        return None
    _dist, line, s_m, tangent = nearest
    direction, trusted = _heading(yaw, tangent)
    return Place(line.id, s_m, direction, trusted, None, x, y, yaw)


def pose_on(painted: Painted, edge_id: str, s_m: float, *, direction: int = 1) -> tuple[float, float, float]:
    """시험과 구간 계산용. `direction` +1 은 접선, -1 은 그 반대."""
    x, y, tangent = painted.line(edge_id).point_at(s_m)
    yaw = tangent if direction > 0 else _wrap(tangent + math.pi)
    return x, y, yaw


def yield_move(place: Place, order: Order, painted: Painted) -> tuple[float, float] | None:
    """주문 하나의 다음 구간. `(회전 rad, 직진 m)`. 이미 왔으면 None.

    문까지 0.20 m 보다 멀면 먼저 선을 따라 문까지 간다. 그 다음 호출이
    방으로 빠진다. 한 구간은 2 m 를 넘지 않는다.
    """
    if place.edge_id is None or order.action not in (Action.SIDESTEP, Action.RETREAT):
        return None
    line = painted.line(place.edge_id)
    if order.action is Action.SIDESTEP and order.s_m is not None and abs(place.s_m - order.s_m) > ALONG_FIRST_M:
        return _along(line, place, order.s_m)
    if order.action is Action.SIDESTEP:
        room = next((item for item in painted.rooms if item.id == order.room_id), None)
        if room is None:
            return None
        return _toward(place, room.hold_xy)
    target = order.s_m
    if target is None:
        target = 0.0 if place.direction > 0 else line.length_m
    return _along(line, place, target)


def _along(line: _Line, place: Place, target_s: float) -> tuple[float, float] | None:
    delta = target_s - place.s_m
    distance = min(abs(delta), YIELD_MAX_M)
    if distance < DONE_M:
        return None
    _x, _y, tangent = line.point_at(place.s_m)
    face = tangent if delta > 0.0 else _wrap(tangent + math.pi)
    return _wrap(face - place.yaw), distance


def _toward(place: Place, hold: tuple[float, float]) -> tuple[float, float] | None:
    dx, dy = hold[0] - place.x, hold[1] - place.y
    distance = min(math.hypot(dx, dy), YIELD_MAX_M)
    if distance < DONE_M:
        return None
    return _wrap(math.atan2(dy, dx) - place.yaw), distance


def steer_toward(x: float, y: float, yaw: float, target: tuple[float, float]) -> tuple[float, float] | None:
    """지도 위 한 점에서 목표까지의 다음 구간. 0.05 m 안이면 None.

    도착은 다음 자세가 말한다. 보낸 지령의 시간을 적분하지 않는다.
    """
    return _toward(Place(None, 0.0, 1, True, None, x, y, yaw), target)


def along_to(place: Place, painted: Painted, target_s: float) -> tuple[float, float] | None:
    """이미 선 위에 있을 때, 그 선의 s 까지 한 구간."""
    if place.edge_id is None:
        return None
    return _along(painted.line(place.edge_id), place, target_s)
