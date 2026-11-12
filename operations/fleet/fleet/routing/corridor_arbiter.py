"""Shared-corridor departure arbitration and regional corridor rules."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Iterable, Literal, Mapping, Sequence

from fleet.routing.cost import RoutingConfig
from fleet.routing.graph import Graph
from fleet.routing.snap import PlanError

if TYPE_CHECKING:
    from fleet.routing.road_path import RoadPathPlan

AT_STATION_M = 0.08


@dataclass(frozen=True)
class CorridorRule:
    zone_id: str
    station_places: tuple[str, ...]
    corridor_edges: tuple[str, ...]
    exit_place: str
    order: Literal["exit_nearest", "fair"] = "exit_nearest"
    capacity: int = 1
    exit_clear_m: float = 0.12


def station_exit_routes(
    graph: Graph,
    rule: CorridorRule,
    config: RoutingConfig = RoutingConfig(),
    *,
    plan_fn: Callable[..., RoadPathPlan] | None = None,
) -> dict[str, RoadPathPlan]:
    """Compute shortest road-graph path from each station in ``rule.station_places`` to ``rule.exit_place``."""
    if plan_fn is None:
        from fleet.routing.road_path import plan_road_path
        plan_fn = plan_road_path
    routes: dict[str, RoadPathPlan] = {}
    for station in rule.station_places:
        if station not in graph.places or rule.exit_place not in graph.places:
            continue
        sx, sy = graph.place_xy(station)
        try:
            routes[station] = plan_fn(graph, (sx, sy, None), rule.exit_place, config)
        except PlanError:
            continue
    return routes


def _active_corridor_movers(
    graph: Graph,
    rule: CorridorRule,
    robots: Iterable[Any],
    in_station_robots: set[str],
) -> list[str]:
    """Robots actively moving through ``rule.corridor_edges`` toward ``rule.exit_place``."""
    corridor_set = set(rule.corridor_edges)
    exit_xy = graph.place_xy(rule.exit_place) if rule.exit_place in graph.places else None
    movers: list[str] = []
    for r in robots:
        if not getattr(r, "online", False) or getattr(r, "pose", None) is None:
            continue
        rid = r.robot_id
        if rid in in_station_robots:
            continue
        rx, ry = float(r.pose[0]), float(r.pose[1])
        if exit_xy is not None and math.dist((rx, ry), exit_xy) <= rule.exit_clear_m:
            # Check if already on an outgoing edge outside the corridor
            on_outside = False
            for arc in graph.arcs.values():
                if arc.edge_id in corridor_set:
                    continue
                d, s_m, _t = arc.project(rx, ry)
                if d <= arc.width_m * 0.55 and s_m > rule.exit_clear_m:
                    on_outside = True
                    break
            if on_outside:
                continue
        for arc in graph.arcs.values():
            if arc.edge_id not in corridor_set:
                continue
            d, _s, _t = arc.project(rx, ry)
            if d <= arc.width_m * 0.65:
                movers.append(rid)
                break
    return sorted(set(movers))


def arbitrate_corridor_departure(
    rule: CorridorRule,
    graph: Graph,
    actions: list[dict[str, Any]],
    robots: Iterable[Any],
    visits: Mapping[str, Any] | None = None,
    config: RoutingConfig = RoutingConfig(),
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """General Rule 2: gate ready-to-leave stations sequentially by proximity to ``rule.exit_place``."""
    visits = visits or {}
    robots_list = list(robots)
    routes = station_exit_routes(graph, rule, config)
    station_xy = {
        s: graph.place_xy(s) for s in rule.station_places if s in graph.places
    }
    in_station_robots: set[str] = set()
    for r in robots_list:
        if getattr(r, "online", False) and getattr(r, "pose", None) is not None:
            if any(math.dist(r.pose, xy) <= AT_STATION_M for xy in station_xy.values()):
                in_station_robots.add(r.robot_id)

    active_movers = _active_corridor_movers(graph, rule, robots_list, in_station_robots)
    station_ranks = sorted(
        (
            (routes[s].length_m, s)
            for s in rule.station_places
            if s in routes
        ),
        key=lambda item: (round(item[0], 4), item[1]),
    )
    station_rank_map = {s: idx + 1 for idx, (_d, s) in enumerate(station_ranks)}

    leave_Indices: list[tuple[tuple[Any, ...], int]] = []
    for idx, row in enumerate(actions):
        bay = row.get("bay")
        if bay in routes and row.get("action") in ("leave", "stay"):
            row["exit_place"] = rule.exit_place
            row["exit_distance_m"] = round(routes[bay].length_m, 4)
            row["exit_rank"] = station_rank_map.get(bay, 999)
            row["departure_route"] = routes[bay].to_dict()
        if row.get("action") == "leave" and bay in routes:
            dist_m = routes[bay].length_m
            conn_s = float(row.get("connected_s") or 0.0)
            key = (
                (round(dist_m, 4), -conn_s, row["robot_id"])
                if rule.order == "exit_nearest"
                else (-conn_s, round(dist_m, 4), row["robot_id"])
            )
            leave_Indices.append((key, idx))

    leave_Indices.sort(key=lambda item: item[0])
    slots_free = max(0, rule.capacity - len(active_movers))
    granted_ids: list[str] = []
    queued_ids: list[str] = []

    for order_pos, (_key, act_idx) in enumerate(leave_Indices):
        row = dict(actions[act_idx])
        rid = row["robot_id"]
        if order_pos < slots_free:
            row["ahead"] = list(active_movers)
            granted_ids.append(rid)
        else:
            ahead = list(active_movers) + [
                actions[leave_Indices[j][1]]["robot_id"] for j in range(order_pos)
            ]
            row["action"] = "stay"
            row["reason"] = "corridor_busy" if active_movers else "queued_for_exit"
            row["ahead"] = ahead
            queued_ids.append(rid)
        actions[act_idx] = row

    summary = {
        "zone_id": rule.zone_id,
        "order": rule.order,
        "exit_place": rule.exit_place,
        "capacity": rule.capacity,
        "corridor_edges": list(rule.corridor_edges),
        "station_order": [
            {
                "bay": s,
                "rank": idx + 1,
                "exit_distance_m": round(dist_m, 4),
                "places": list(routes[s].places),
                "edges": list(routes[s].edges),
            }
            for idx, (dist_m, s) in enumerate(station_ranks)
        ],
        "active_departing": active_movers,
        "granted_robot_ids": granted_ids,
        "queued_robot_ids": queued_ids,
    }
    return actions, summary


def regional_corridor_for_map(
    graph: Graph | None,
    bays: Sequence[Any],
    site_rules: Any = None,
) -> CorridorRule | None:
    """Regional Rule: derive the ``CorridorRule`` for the site map's charging bay zone."""
    from fleet.routing.road_path import plan_road_path

    if graph is None or not bays:
        return None
    station_ids = tuple(b.id for b in bays if b.id in graph.places)
    if not station_ids:
        return None

    order: Literal["exit_nearest", "fair"] = "exit_nearest"
    exit_place: str | None = None
    if site_rules is not None:
        ret = getattr(site_rules, "return_", None)
        dep = getattr(site_rules, "departure", None)
        if ret is not None and getattr(ret, "exit_place", None):
            exit_place = ret.exit_place
        if dep is not None and getattr(dep, "order", None) in ("exit_nearest", "fair"):
            order = dep.order

    if exit_place is None or exit_place not in graph.places:
        # Regional topology discovery: S1 is the charge-zone exit on world_261026;
        # otherwise pick the first shared non-bay place reachable from every bay.
        if "S1" in graph.places:
            exit_place = "S1"
        else:
            for cand in graph.places:
                if cand in station_ids:
                    continue
                if all(
                    _can_reach(graph, s, cand) for s in station_ids
                ):
                    exit_place = cand
                    break
    if exit_place is None:
        return None

    corridor_edges: list[str] = []
    for s in station_ids:
        sx, sy = graph.place_xy(s)
        try:
            rp = plan_road_path(graph, (sx, sy, None), exit_place)
            for eid in rp.edges:
                if eid not in corridor_edges:
                    corridor_edges.append(eid)
        except PlanError:
            continue
    if not corridor_edges:
        return None

    return CorridorRule(
        zone_id="charge_bay_corridor",
        station_places=station_ids,
        corridor_edges=tuple(corridor_edges),
        exit_place=exit_place,
        order=order,
        capacity=1,
    )


def _can_reach(graph: Graph, start_place: str, goal_place: str) -> bool:
    from fleet.routing.road_path import plan_road_path

    try:
        sx, sy = graph.place_xy(start_place)
        plan_road_path(graph, (sx, sy, None), goal_place)
        return True
    except PlanError:
        return False
