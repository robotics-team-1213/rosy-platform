"""Painted-track meet room-hold and yield manoeuvre helpers for StuckResolver (D-453, D-488)."""

from __future__ import annotations

import logging
import math
from typing import Optional

from fleet.stuck.peer_pose import _map_pose


def _hold_xy(plan, painted):
    room = next((item for item in painted.rooms if item.id == plan.room_id), None)
    return None if room is None else room.hold_xy


def _door_xy(plan, painted):
    if plan.s_m is None:
        return None
    x, y, _tangent = painted.line(plan.edge_id).point_at(plan.s_m)
    return (x, y)


def _gap_target(plan, painted, x: float, y: float):
    """Off the paint while still entering: the hold if the door is the nearest point, else the line."""
    from fleet.meet.place import ALONG_FIRST_M, MAX_OFF_M

    line = painted.line(plan.edge_id)
    _dist, s_m, _tangent = line.project(x, y)
    near_door = plan.s_m is not None and abs(s_m - plan.s_m) <= ALONG_FIRST_M + MAX_OFF_M
    if plan.action == "sidestep" and near_door:
        hold = _hold_xy(plan, painted)
        if hold is not None:
            return hold
    px, py, _tangent = line.point_at(s_m)
    return (px, py)


class _YieldPlan:
    """Policy direction of a yielder. The manoeuvre yaw is not a new meet heading."""

    def __init__(self, edge_id: str, direction: int, action: str,
                 room_id: Optional[str], s_m: Optional[float]) -> None:
        self.edge_id, self.direction, self.action = edge_id, direction, action
        self.room_id, self.s_m = room_id, s_m
        self.returning = False


def resolve_meet_yield(resolver, row, rows):
    """room_hold for poses on the painted track. None keeps R1/R2/R3."""
    from fleet.meet import decide
    from fleet.meet.place import project, yield_move
    from fleet.meet.scene import Action, Order, Pin, Robot

    me = _map_pose(row)
    if me is None:
        return None
    painted = resolver._painted()
    if painted is None:  # no active site map (D-488): R1/R2/R3 only
        if not resolver._warned_no_map:
            resolver._warned_no_map = True
            logging.getLogger("fleet.stuck.resolver").warning("stuck resolver: no active site map; meet rules off")
        return None
    resolver._warned_no_map = False
    rid = str(row["robot_id"])
    placed: dict[str, object] = {}
    robots: list[Robot] = []
    for other in rows:
        if not other.get("online", True):
            continue
        pose = _map_pose(other)
        if pose is None:
            continue
        place = project(painted, pose[0], pose[1], pose[2])
        if place is None:
            continue
        oid = str(other["robot_id"])
        placed[oid] = place
        plan = resolver._plans.get(oid)
        if place.room_id:
            if plan is not None and plan.room_id == place.room_id:
                plan.returning = True
            else:
                resolver._plans.pop(oid, None)
                plan = None
        if plan is not None and place.edge_id == plan.edge_id and not plan.returning:
            direction, trusted = plan.direction, True
        else:
            direction, trusted = place.direction, place.trusted
        robots.append(Robot(oid, place.edge_id, place.s_m, direction, trusted, room_id=place.room_id))
    mine = placed.get(rid)
    plan = resolver._plans.get(rid)
    if mine is None:
        if plan is None:
            return None
        return resolver._off_paint(me, plan, painted, rows, rid)
    if plan is not None and plan.returning:
        return resolver._rejoin(row, mine, plan, painted, rows, rid)
    if not any(other != rid for other in placed):
        return None
    pins = tuple(Pin(edge_id, yielder) for edge_id, yielder in resolver._pins.items())
    scene = painted.scene(tuple(robots), pins)
    orders = decide("room_hold", scene)
    resolver._keep_pins(scene, orders)
    order = next(item for item in orders if item.robot_id == rid)
    if order.action is Action.ESCALATE:
        resolver._plans.pop(rid, None)
        return ("meet", "ESCALATE")
    plan = resolver._plans.get(rid)
    if order.action in (Action.SIDESTEP, Action.RETREAT):
        robot = next(item for item in robots if item.id == rid)
        resolver._plans[rid] = _YieldPlan(
            order.edge_id or robot.edge_id or "", robot.direction, order.action.value,
            order.room_id, order.s_m)
        move = yield_move(mine, order, painted)
    elif plan is not None and mine.edge_id == plan.edge_id and not plan.returning:
        move = yield_move(mine, Order(
            rid, Action(plan.action), room_id=plan.room_id, edge_id=plan.edge_id, s_m=plan.s_m,
        ), painted)
    else:
        resolver._plans.pop(rid, None)
        move = None
    if move is None:
        return ("meet", "WAIT")
    return ("meet", "YIELD", move[0], move[1])


def step_off_paint(resolver, pose, plan, painted, rows, rid):
    """A usable pose that project() rejected. The timer already ended; this xy is the rest."""
    from fleet.meet.place import steer_toward

    x, y, yaw = pose
    if plan.returning:
        clear = resolver._door_clear(plan, painted, rows, rid)
        target = _door_xy(plan, painted) if clear else _hold_xy(plan, painted)
    else:
        target = _gap_target(plan, painted, x, y)
    if target is None:
        return ("meet", "WAIT")
    move = steer_toward(x, y, yaw, target)
    if move is None:
        return ("meet", "WAIT")
    return ("meet", "YIELD", move[0], move[1])


def step_rejoin(resolver, row, mine, plan, painted, rows, rid):
    """Back to the door, then face the stored travel direction. RESUME only on the paint."""
    from fleet.meet.place import ALONG_FIRST_M, along_to, steer_toward

    if not resolver._door_clear(plan, painted, rows, rid):
        if mine.room_id:
            return ("meet", "WAIT")
        hold = _hold_xy(plan, painted)
        if hold is None:
            return ("meet", "WAIT")
        move = steer_toward(mine.x, mine.y, mine.yaw, hold)
        if move is None:
            return ("meet", "WAIT")
        return ("meet", "YIELD", move[0], move[1])
    if mine.room_id or mine.edge_id != plan.edge_id:
        target = _door_xy(plan, painted)
        if target is None:
            return ("meet", "WAIT")
        move = steer_toward(mine.x, mine.y, mine.yaw, target)
        if move is None:
            return ("meet", "WAIT")
        return ("meet", "YIELD", move[0], move[1])
    if plan.s_m is None or abs(mine.s_m - plan.s_m) > ALONG_FIRST_M:
        if plan.s_m is None:
            return ("meet", "WAIT")
        move = along_to(mine, painted, plan.s_m)
        if move is None:
            return ("meet", "WAIT")
        return ("meet", "YIELD", move[0], move[1])
    if mine.trusted and mine.direction == plan.direction:
        if resolver._peer_ahead(row, rows) is not False:
            return ("meet", "WAIT")
        return ("meet", "RESUME")
    line = painted.line(plan.edge_id)
    hop = 0.15 if plan.direction > 0 else -0.15
    target_s = min(max(mine.s_m + hop, 0.0), line.length_m)
    move = along_to(mine, painted, target_s)
    if move is None:
        return ("meet", "WAIT")
    return ("meet", "YIELD", move[0], move[1])


def is_door_clear(resolver, plan, painted, rows, rid) -> bool:
    """The passer has gone past the door. An unusable pose blocks the return."""
    from fleet.meet.place import project

    if plan.s_m is None:
        return False
    door_x, door_y, _tangent = painted.line(plan.edge_id).point_at(plan.s_m)
    clearance = resolver.config.peer_reach_m + resolver.config.peer_radius_m
    for other in rows:
        if str(other.get("robot_id")) == rid:
            continue
        pose = _map_pose(other)
        if pose is None:
            return False
        place = project(painted, pose[0], pose[1], pose[2])
        if place is not None and place.edge_id == plan.edge_id:
            passed = (plan.s_m - place.s_m) * plan.direction
            if passed <= clearance:
                return False
        elif place is not None and place.room_id == plan.room_id:
            return False
        elif math.hypot(pose[0] - door_x, pose[1] - door_y) <= clearance:
            return False
    return True


def retain_active_pins(resolver, scene, orders) -> None:
    from fleet.meet.scene import Action, closing

    kept: dict[str, str] = {}
    for line in scene.edges:
        group = [robot for robot in scene.robots if robot.edge_id == line.id]
        if len(group) != 2:
            continue
        pair = closing(group[0], group[1])
        if pair is None:
            continue
        ids = {pair[0].id, pair[1].id}
        chosen = next((order.robot_id for order in orders
                       if order.robot_id in ids and order.action in (Action.SIDESTEP, Action.RETREAT)), None)
        if chosen is None and resolver._pins.get(line.id) in ids:
            chosen = resolver._pins[line.id]
        if chosen is not None:
            kept[line.id] = chosen
    resolver._pins = kept
