"""둘 다 선다.

마주 보면 둘 다 WAIT 다. 방으로 보내지 않는다. 지금 차선 막힘 규칙이
앞의 로봇에게 하는 일과 같다. 다른 알고리즘과 같은 장면을 비교할 기준점이다.
"""

from __future__ import annotations

from fleet.meet.scene import Action, Order, Scene, on_edge


class WaitBoth:
    name = "wait_both"

    def decide(self, scene: Scene) -> tuple[Order, ...]:
        orders: dict[str, Order] = {}
        for line in scene.edges:
            group = on_edge(scene, line.id)
            opposite = any(a.direction != b.direction for a in group for b in group)
            if len(group) >= 2 and opposite:
                for robot in group:
                    orders[robot.id] = Order(robot.id, Action.WAIT, reason="opposite")
        for robot in scene.robots:
            if robot.id in orders:
                continue
            if robot.edge_id is None and robot.wants_edge and on_edge(scene, robot.wants_edge):
                orders[robot.id] = Order(robot.id, Action.HOLD, edge_id=robot.wants_edge, reason="occupied")
                continue
            orders[robot.id] = Order(robot.id, Action.PROCEED, reason="clear")
        return tuple(orders[robot.id] for robot in scene.robots)
