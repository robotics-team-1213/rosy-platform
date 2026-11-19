"""D-517 / D-525: pure geometry, handover resolution, and view assembly helpers for ``lane_traffic``."""

from __future__ import annotations

import math
from typing import Any, Optional

from fleet.routing.execute import arc_id
from fleet.traffic import blocks, handover

LOCALIZED = "LOCALIZED"


def units_under_pose(
    layout: blocks.Layout,
    graph,
    pose: tuple[float, float, float],
    length: float,
    u_max: float,
    extra: float = 0.0,
) -> dict[str, bool]:
    """``{unit: forward}`` a robot body at ``pose`` (± its length, u and ``extra`` along the lane) may touch."""
    x, y, yaw = pose
    reach = length + u_max + extra
    units: dict[str, bool] = {}
    for arc in graph.arcs.values():
        if not arc.forward:
            continue
        dist, s, tangent = arc.project(x, y)
        if dist > arc.width_m / 2 + u_max:
            continue
        forward = yaw is None or math.cos(yaw - tangent) >= 0.0
        for unit, s0, s1 in layout.edge_units[arc.edge_id]:
            if s1 > s - reach and s0 < s + reach:
                units[unit] = forward
    return units


def resolve_handover(service: Any, layout, trips: dict, robots, refused_unit: dict, now: float) -> None:
    """D-517 5 (M4): Fleet's resolver for a wait cycle or a 30 s UNKNOWN (``handover.decide``)."""
    localized = {robot.id for robot in robots if robot.d is not None}
    unknown = set(service._state.pinned) | (set(service._state.last_occupied) - localized)
    service._unknown_since = {r: service._unknown_since.get(r, now) for r in unknown}
    route = {robot.id: robot.route_id for robot in robots}
    service._tried = {r: tried for r, tried in service._tried.items() if route.get(r) == tried[0]}
    avoidable = {}
    for robot_id, unit in refused_unit.items():
        live = trips[robot_id]
        index = live.view["segment_index"]
        edges = [edge for edge, parts in layout.edge_units.items() if any(p[0] == unit for p in parts)]
        if index < len(live.segments) - 1 and live.segments[index]["edge_id"] not in edges:
            avoidable[robot_id] = edges
    cycle = service._view["wait_cycle"]
    service.avoidable = avoidable                            # D-610 7: the AI PC's deadlock case reads it
    seen = frozenset(cycle or ())
    service._cycle = (seen, service._cycle[1] + 1 if seen and seen == service._cycle[0] else int(bool(seen)))
    pending = {r for r, live in trips.items()
               if (live.view["hold"] or {}).get("reason") == "replan" and live.view["hold"].get("plan")}
    ai_pick = service.ai_replan(cycle if cycle and service._cycle[1] >= handover.CYCLE_PERIODS
                                else (), avoidable, now)
    periods = 0 if getattr(service.ai_replan, "waiting", False) else service._cycle[1]
    decisions = handover.decide(cycle, periods, avoidable, {r: t[1] for r, t in service._tried.items()},
                                pending, service._unknown_since, now, ai_pick=ai_pick)
    decisions = {r: row for r, row in decisions.items() if not r.startswith("signal:")}  # D-525 pseudo node
    for robot_id, row in decisions.items():
        if row["decision"] == "human" and robot_id in getattr(service, "autonomous_robots", ()):
            row["decision"], row["reason"] = "wait", "auto_hold:" + row["trigger"]
    for robot_id, row in decisions.items():
        if row["decision"] == "replan":
            service._tried[robot_id] = (route[robot_id], row["blocked_edges"])
        if robot_id in trips:
            trips[robot_id].traffic["resolver"] = row
    service._view["resolver"] = [{"robot_id": r, **row} for r, row in sorted(decisions.items())]


def build_traffic_view(
    service: Any, version, layout, graph, trips: dict, result, refused_unit: dict, robots, gaps
) -> dict:
    state = service._state
    holders: dict[str, set] = {}
    unknown: dict[str, set] = {}
    occupied: dict[str, set] = {}
    for robot_id, held in state.held.items():
        for unit, _forward in held.values():
            holders.setdefault(unit, set()).add(robot_id)
    localized = {r for r, live in trips.items() if (live.view.get("pose") or {}).get("state") == LOCALIZED}
    for table in (state.last_occupied, state.pinned):
        for robot_id, units in table.items():
            for unit in units:
                (occupied if robot_id in localized and table is state.last_occupied else unknown) \
                    .setdefault(unit, set()).add(robot_id)
    units = []
    for unit_id, unit in sorted(layout.units.items()):
        who = holders.get(unit_id, set()) | occupied.get(unit_id, set()) | unknown.get(unit_id, set())
        status = ("UNKNOWN" if unit_id in unknown else "OCCUPIED" if unit_id in occupied
                  else "GRANTED" if unit_id in holders else "FREE")
        units.append({"id": unit_id, "capacity": unit.capacity, "zone": unit.zone, "two_way": unit.two_way,
                      "state": status, "holders": sorted(who),
                      "waiting": sorted(r for r, u in refused_unit.items() if u == unit_id)})
    loops = {}
    for robot_id, live in trips.items():
        if live.repeat and live.lap_arcs:
            edges, capacity = service._loop(layout, graph, live.lap_arcs)
            loops.setdefault(edges, {"edges": sorted(edges), "capacity": capacity, "robots": []})["robots"] \
                .append(robot_id)
    cycle = blocks.wait_cycle(result.waiting_for)
    at = {robot.id: robot for robot in robots}
    return {
        "map_version": version,
        "block_length_m": {edge: round(parts[0][2] - parts[0][1], 3)
                           for edge, parts in sorted(layout.edge_units.items())},
        "units": units,
        "robots": [{"robot_id": robot_id, "authority_end_m": _round(result.authority_end.get(robot_id)),
                    "front_d_m": _round(at[robot_id].d), "convoy": at[robot_id].convoy and {
                        "leader": at[robot_id].convoy, "follows": at[robot_id].follows,
                        "gap_m": gaps.get(robot_id)},
                    "waiting_for": list(result.waiting_for.get(robot_id, ())), "lap": live.view.get("lap"),
                    "trip_state": live.view["state"]} for robot_id, live in sorted(trips.items())],
        "loop_capacity": list(loops.values()),
        "wait_cycle": list(cycle) if cycle else None,
        "unplaced": list(result.unplaced),
    }


def _shift(state: blocks.TableState, robot_id: str, old_spans, shift: float) -> None:
    """A repeat trip dropped ``shift`` route metres of finished laps: its grants, shared grants and
    authority move with the route (span ``i`` becomes ``i - n``), so the same route id stays valid.
    Every other table is keyed by unit, not span index."""
    n = sum(1 for span in old_spans if span.d1 <= shift + 1e-6)
    held = state.held.get(robot_id)
    if held is not None:
        state.held[robot_id] = {i - n: grant for i, grant in held.items() if i >= n}
    shared = state.shared.get(robot_id)
    if shared is not None:  # span-indexed too: a stale index would let a shared unit pass (Safety-Review)
        state.shared[robot_id] = {i - n: member for i, member in shared.items() if i >= n}
    if robot_id in state.authority:
        if state.held.get(robot_id):
            state.authority[robot_id] -= shift
        else:  # every grant was in the dropped laps: no authority without a grant behind it
            del state.authority[robot_id]


def _front_on(graph, live, other, d: float, after: float, body: float) -> Optional[float]:
    """``other``'s front ``d`` (its route metres) in ``live``'s route metres: the first place past
    ``after`` where the arcs under its body come in the same order, or None (not on shared arcs)."""
    mine, theirs = _arcs(graph, live), _arcs(graph, other)
    i = max((k for k, (_arc, base) in enumerate(theirs) if base <= d), default=0)
    j = i
    while j > 0 and theirs[j][1] > d - body:
        j -= 1
    need = [arc for arc, _base in theirs[j:i + 1]]
    for k in range(i - j, len(mine)):
        front = mine[k][1] + d - theirs[i][1]
        if front > after and [arc for arc, _base in mine[k - (i - j):k + 1]] == need:
            return front
    return None


def _arcs(graph, live) -> list:
    """``(arc id, route metres where it starts)`` along a trip's plan."""
    out, base = [], 0.0
    for seg in live.segments:
        out.append((arc_id(seg), base))
        base += graph.arcs[arc_id(seg)].length_m
    return out


def _edges(arc_ids) -> frozenset:
    return frozenset(arc.rsplit(":", 1)[0] for arc in arc_ids)


def _round(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, 3)


def _empty(version) -> dict:
    return {"map_version": version, "block_length_m": {}, "units": [], "robots": [], "loop_capacity": [],
            "wait_cycle": None, "unplaced": [], "resolver": [], "signals": []}
