"""방으로 한 대만 비킨다.

양방향에서 같은 방향은 간격이 몸보다 좁을 때만 뒷차가 선다. 일방통행에서는
서지 않고 둘 다 가게 둔다. 간격은 로봇이 앞에서 직접 선다. 마주 보면 앞은
상대라서 구간 끝은 상대 뒤에 있다. 빠지는 길은 각자 뒤쪽뿐이고, 그 거리가
짧은 한 대만 움직인다. 거리가 0.15 m 안이면 id 가 큰 쪽이 비킨다. 한 번 고른
로봇이 `pins` 에 있으면 거리가 뒤집혀도 그 로봇이 비킨다. 찬 방의 문은 쓰지
않는다. 방향이 신뢰되지 않거나 같은 양방향 선에 셋 이상이거나 일방통행에서
반대 방향이면 사람에게 넘긴다.
"""

from __future__ import annotations

from fleet.meet.scene import (
    Action, Order, Retreat, Robot, Scene, closing, edge, nearest_retreat, on_edge, open_doors,
)

#: 이 안이면 같은 거리로 보고 id 로 정한다. 몇 cm 차이에 도는 쪽이 바뀌지 않게 한다.
TIE_M = 0.15


class RoomHold:
    name = "room_hold"

    def decide(self, scene: Scene) -> tuple[Order, ...]:
        orders: dict[str, Order] = {}
        for line in scene.edges:
            group = list(on_edge(scene, line.id))
            if group:
                orders.update(self._edge(scene, line.id, group))
        for robot in scene.robots:
            if robot.id in orders:
                continue
            if robot.edge_id is None and robot.room_id:
                orders[robot.id] = Order(robot.id, Action.WAIT, room_id=robot.room_id, reason="in_room")
            elif robot.edge_id is None and robot.wants_edge:
                orders[robot.id] = self._entry(scene, robot)
            else:
                orders[robot.id] = Order(robot.id, Action.PROCEED, reason="clear")
        return tuple(orders[robot.id] for robot in scene.robots)

    def _edge(self, scene: Scene, edge_id: str, group: list[Robot]) -> dict[str, Order]:
        line = edge(scene, edge_id)
        opposite = any(robot.direction < 0 for robot in group) and any(robot.direction > 0 for robot in group)
        if (not line.oneway and len(group) >= 3) or (line.oneway and opposite):
            return {robot.id: Order(robot.id, Action.ESCALATE, reason="unresolved") for robot in group}
        if len(group) == 2 and opposite:
            pair = closing(group[0], group[1])
            if pair is None:
                return {robot.id: Order(robot.id, Action.PROCEED, reason="apart") for robot in group}
            if not all(robot.trusted for robot in group):
                return {robot.id: Order(robot.id, Action.ESCALATE, reason="untrusted") for robot in group}
            return self._yield(scene, line.id, pair[0], pair[1])
        if line.oneway:
            return {robot.id: Order(robot.id, Action.PROCEED, reason="oneway") for robot in group}
        return self._convoy(scene, group)

    def _convoy(self, scene: Scene, group: list[Robot]) -> dict[str, Order]:
        direction = group[0].direction
        ordered = sorted(group, key=lambda robot: robot.s_m if direction > 0 else -robot.s_m)
        orders = {ordered[-1].id: Order(ordered[-1].id, Action.PROCEED, reason="lead")}
        for rear, ahead in zip(ordered, ordered[1:]):
            gap = abs(ahead.s_m - rear.s_m)
            close = gap < scene.body_m
            orders[rear.id] = Order(
                rear.id, Action.WAIT if close else Action.PROCEED, reason="gap" if close else "follow",
            )
        return orders

    def _yield(self, scene: Scene, edge_id: str, plus: Robot, minus: Robot) -> dict[str, Order]:
        line = edge(scene, edge_id)
        doors = open_doors(scene, edge_id)
        pinned = _pinned(scene, edge_id, plus, minus)
        if pinned == plus.id:
            retreat, yielder, holder = nearest_retreat(plus, line, doors), plus, minus
        elif pinned == minus.id:
            retreat, yielder, holder = nearest_retreat(minus, line, doors), minus, plus
        else:
            left = (nearest_retreat(plus, line, doors), plus)
            right = (nearest_retreat(minus, line, doors), minus)
            retreat, yielder = _shorter(left, right)
            holder = minus if yielder is plus else plus
        return {
            yielder.id: _yield_order(yielder.id, retreat, edge_id),
            holder.id: Order(holder.id, Action.WAIT, reason="hold"),
        }

    def _entry(self, scene: Scene, robot: Robot) -> Order:
        line = edge(scene, robot.wants_edge or "")
        if line.oneway and robot.direction < 0:
            return Order(robot.id, Action.HOLD, edge_id=line.id, reason="oneway")
        occupants = on_edge(scene, line.id)
        if any(other.direction != robot.direction for other in occupants):
            return Order(robot.id, Action.HOLD, edge_id=line.id, reason="opposite")
        entry_s = 0.0 if robot.direction > 0 else line.length_m
        if any(abs(other.s_m - entry_s) < scene.body_m for other in occupants):
            return Order(robot.id, Action.HOLD, edge_id=line.id, reason="gap")
        return Order(robot.id, Action.PROCEED, edge_id=line.id, reason="enter")


def _pinned(scene: Scene, edge_id: str, plus: Robot, minus: Robot) -> str | None:
    for pin in scene.pins:
        if pin.edge_id == edge_id and pin.yielder_id in (plus.id, minus.id):
            return pin.yielder_id
    return None


def _shorter(first: tuple[Retreat, Robot], second: tuple[Retreat, Robot]) -> tuple[Retreat, Robot]:
    (left, left_robot), (right, right_robot) = first, second
    if abs(left.distance_m - right.distance_m) <= TIE_M:
        return (left, left_robot) if left_robot.id > right_robot.id else (right, right_robot)
    return (left, left_robot) if left.distance_m < right.distance_m else (right, right_robot)


def _yield_order(robot_id: str, retreat: Retreat, edge_id: str) -> Order:
    if retreat.kind == "room":
        return Order(robot_id, Action.SIDESTEP, room_id=retreat.room_id, edge_id=edge_id,
                     s_m=retreat.s_m, reason="room")
    return Order(robot_id, Action.RETREAT, edge_id=edge_id, s_m=retreat.s_m, reason="rear")
