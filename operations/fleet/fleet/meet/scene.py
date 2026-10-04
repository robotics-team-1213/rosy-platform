"""한 줄 교착의 공통 장면.

알고리즘이 바꿔 끼워지려면 입력과 출력이 먼저 고정돼야 한다. 여기 있는 것은
차선 위의 위치, 방에서 기다리는 자리, 그리고 로봇에게 내리는 주문이다.
경로를 전송하지 않고, 누가 양보하는지도 정하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Action(Enum):
    """로봇 하나에게 내리는 다음 한 수."""

    PROCEED = "proceed"    # 지금 방향으로 선을 따라간다
    WAIT = "wait"          # 그 자리에 선다
    HOLD = "hold"          # 구간에 들어가지 않고 앞에서 기다린다
    SIDESTEP = "sidestep"  # 문에서 방으로 빠진다
    RETREAT = "retreat"    # 상대를 지나지 않고 구간 끝으로 빠진다
    ESCALATE = "escalate"  # 알고리즘이 정하지 않는다. 사람에게 넘긴다


@dataclass(frozen=True)
class Edge:
    """차선 하나. `s` 는 시작(0)에서 끝(`length_m`)까지의 거리다."""

    id: str
    length_m: float
    oneway: bool


@dataclass(frozen=True)
class Room:
    """선 밖에서 한 대가 설 자리. `clearance_m` 는 통과 선까지의 거리다."""

    id: str
    hold_xy: tuple[float, float]
    clearance_m: float


@dataclass(frozen=True)
class Door:
    """방에서 선으로 나오는 문. 같은 구간 위의 거리 `s_m` 이다."""

    edge_id: str
    s_m: float
    room_id: str


@dataclass(frozen=True)
class Robot:
    """구간에 올라간 로봇. `direction` 은 +1(끝으로) 또는 -1(시작으로).

    `edge_id` 가 없으면 선 밖에 있다. `room_id` 는 이미 들어간 방이다.
    `wants_edge` 는 들어가고 싶은 구간이다.
    """

    id: str
    edge_id: str | None
    s_m: float
    direction: int
    trusted: bool = True
    wants_edge: str | None = None
    room_id: str | None = None


@dataclass(frozen=True)
class Pin:
    """이 구간에서 이미 고른 비키는 로봇. 거리가 뒤집혀도 그 로봇을 유지한다."""

    edge_id: str
    yielder_id: str


@dataclass(frozen=True)
class Scene:
    """알고리즘이 보는 전부. 맵 파일은 여기 없고, 불러 주는 쪽이 채운다."""

    edges: tuple[Edge, ...]
    rooms: tuple[Room, ...]
    doors: tuple[Door, ...]
    robots: tuple[Robot, ...]
    body_m: float = 0.17
    pins: tuple[Pin, ...] = ()


@dataclass(frozen=True)
class Order:
    """로봇 하나의 주문. `room_id` 는 방으로 빠질 때, `s_m` 은 후퇴 끝이다."""

    robot_id: str
    action: Action
    room_id: str | None = None
    edge_id: str | None = None
    s_m: float | None = None
    reason: str = ""


@dataclass(frozen=True)
class Retreat:
    """상대를 통과하지 않고 빠질 수 있는 한 곳."""

    distance_m: float
    kind: str                 # "room" 또는 "end"
    room_id: str | None
    s_m: float


def edge(scene: Scene, edge_id: str) -> Edge:
    for item in scene.edges:
        if item.id == edge_id:
            return item
    raise KeyError(edge_id)


def on_edge(scene: Scene, edge_id: str) -> tuple[Robot, ...]:
    return tuple(robot for robot in scene.robots if robot.edge_id == edge_id)


def doors_on(scene: Scene, edge_id: str) -> tuple[Door, ...]:
    return tuple(door for door in scene.doors if door.edge_id == edge_id)


def open_doors(scene: Scene, edge_id: str) -> tuple[Door, ...]:
    """이미 로봇이 선 방의 문은 빼다. 한 방에는 한 대다."""
    taken = {robot.room_id for robot in scene.robots if robot.room_id}
    return tuple(door for door in doors_on(scene, edge_id) if door.room_id not in taken)


def closing(a: Robot, b: Robot) -> tuple[Robot, Robot] | None:
    """마주 보며 간격이 줄어들면 (끝으로 가는 쪽, 시작으로 가는 쪽)을 돌려준다."""
    plus, minus = (a, b) if a.direction > 0 else (b, a)
    if plus.direction <= 0 or minus.direction >= 0:
        return None
    if plus.s_m < minus.s_m:
        return plus, minus
    return None


def retreats(robot: Robot, line: Edge, doors: tuple[Door, ...]) -> tuple[Retreat, ...]:
    """이 로봇의 뒤쪽만 본다. 앞은 상대가 있는 쪽이라 피난처가 아니다."""
    found: list[Retreat] = []
    if robot.direction > 0:
        found.append(Retreat(robot.s_m, "end", None, 0.0))
        found.extend(
            Retreat(robot.s_m - door.s_m, "room", door.room_id, door.s_m)
            for door in doors if door.s_m <= robot.s_m
        )
    else:
        found.append(Retreat(line.length_m - robot.s_m, "end", None, line.length_m))
        found.extend(
            Retreat(door.s_m - robot.s_m, "room", door.room_id, door.s_m)
            for door in doors if door.s_m >= robot.s_m
        )
    return tuple(found)


def nearest_retreat(robot: Robot, line: Edge, doors: tuple[Door, ...]) -> Retreat:
    """가장 가까운 뒤쪽 피난처. 거리가 같으면 방을 끝보다 먼저 고른다."""
    return min(retreats(robot, line, doors), key=lambda item: (item.distance_m, item.kind != "room"))
