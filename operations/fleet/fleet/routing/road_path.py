"""Two-layer road-path & shared-corridor departure pipeline.

Layer 1 — General Rules (일반 규칙):
- ``plan_road_path``: snaps any start pose and goal onto the directed road graph ``Graph``
  and samples continuous road-following waypoints (``waypoints_site``, ``places``, ``edges``)
  so Nav2 and the Fleet console always follow painted roads rather than Euclidean chords.
- ``CorridorRule`` & ``arbitrate_corridor_departure``: generic traffic arbiter for any
  single-capacity shared departure corridor. Ranks ready-to-leave stations by shortest
  directed road-graph distance to ``exit_place`` (``exit_nearest``) or waiting time (``fair``),
  checks live corridor occupancy on ``corridor_edges``, releases at most ``capacity`` robots,
  and holds the rest with ``queued_for_exit`` or ``corridor_busy``.

Layer 2 — Regional Rules (지역 규칙):
- ``regional_corridor_for_map``: binds the site's charge-bay zone (e.g. ``world_261026``
  bays ``C1..C3`` -> shared spine ``P3 -> P2 -> P1`` -> exit ``S1``) into a ``CorridorRule``,
  honouring optional ``SiteRules`` overrides.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from fleet.routing.corridor_arbiter import (
    AT_STATION_M,
    CorridorRule,
    _active_corridor_movers,
    _can_reach,
    arbitrate_corridor_departure,
    regional_corridor_for_map,
    station_exit_routes,
)
from fleet.routing.cost import RoutingConfig, wrap
from fleet.routing.graph import Graph
from fleet.routing.snap import PlanError
from fleet.routing.trip import Plan, PlanRequest, plan_trip


@dataclass(frozen=True)
class RoadPathPlan:
    waypoints_site: tuple[dict[str, Any], ...]
    places: tuple[str, ...]
    edges: tuple[str, ...]
    segments: tuple[tuple[str, bool, float, float], ...]
    length_m: float
    eta_s: float
    map_version: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "waypoints_site": [dict(w) for w in self.waypoints_site],
            "places": list(self.places),
            "edges": list(self.edges),
            "length_m": self.length_m,
            "eta_s": self.eta_s,
            "map_version": self.map_version,
        }


def _candidate_start_poses(
    graph: Graph, x: float, y: float, yaw: float | None, config: RoutingConfig
) -> list[tuple[float, float, float, float]]:
    """Return ``(dist_m, sx, sy, syaw)`` candidates sorted by distance to ``(x, y)`` first."""
    candidates: list[tuple[float, float, float, float]] = []
    if yaw is not None and math.isfinite(yaw):
        candidates.append((0.0, x, y, float(yaw)))
    near: list[tuple[float, int, float, float, float, float, str]] = []
    max_factor = max(1.5, config.snap_width_factor)
    for arc in graph.arcs.values():
        dist, s_m, _tangent = arc.project(x, y)
        if dist <= max_factor * arc.width_m:
            px, py, pt = arc.point_at(s_m)
            sx, sy = (x, y) if dist <= arc.width_m * 0.49 else (px, py)
            at_dead_end = 1 if s_m >= arc.length_m - 1e-3 else 0
            yaw_err = abs(wrap((yaw or pt) - pt)) if yaw is not None else 0.0
            near.append((dist, at_dead_end, yaw_err, sx, sy, pt, arc.id))
    near.sort(key=lambda item: (round(item[0], 3), item[1], round(item[2], 3), item[6]))
    for dist, _dead, _yerr, sx, sy, pt, _aid in near:
        if not any(
            math.dist((sx, sy), (c[1], c[2])) < 1e-3
            and abs(wrap(pt - c[3])) < 0.05
            for c in candidates
        ):
            candidates.append((dist, sx, sy, pt))
    return candidates


def _sample_plan_waypoints(
    graph: Graph,
    plan: Plan,
    start_xy: tuple[float, float],
    goal: str | tuple[float, float, float | None],
    step_m: float,
) -> tuple[dict[str, Any], ...]:
    if not plan.segments:
        if isinstance(goal, str) and goal in graph.places:
            gx, gy = graph.place_xy(goal)
            gyaw = getattr(graph.places[goal], "yaw", None) or 0.0
        elif isinstance(goal, tuple):
            gx, gy = float(goal[0]), float(goal[1])
            gyaw = float(goal[2]) if goal[2] is not None else 0.0
        else:
            gx, gy, gyaw = start_xy[0], start_xy[1], 0.0
        return (
            {
                "x": round(gx, 4),
                "y": round(gy, 4),
                "yaw": round(gyaw, 4),
                "s_m": 0.0,
                "edge_id": "",
                "kind": "stop",
            },
        )

    pts: list[dict[str, Any]] = []
    cum_s = 0.0
    for seg_idx, (edge_id, forward, s_from, s_to) in enumerate(plan.segments):
        arc_id = f"{edge_id}:{'fwd' if forward else 'rev'}"
        arc = graph.arcs[arc_id]
        span = max(0.0, s_to - s_from)
        steps = max(1, int(math.ceil(span / max(0.04, step_m))))
        for i in range(steps + 1):
            if i == 0 and seg_idx > 0:
                continue
            s_val = s_from + span * (i / steps)
            px, py, pyaw = arc.point_at(s_val)
            along = cum_s + (s_val - s_from)
            if pts and math.dist((pts[-1]["x"], pts[-1]["y"]), (px, py)) < 0.015 and i < steps:
                continue
            pts.append(
                {
                    "x": round(px, 4),
                    "y": round(py, 4),
                    "yaw": round(pyaw, 4),
                    "s_m": round(along, 4),
                    "edge_id": edge_id,
                    "kind": "pass",
                }
            )
        cum_s += span
    if pts:
        pts[-1]["kind"] = "stop"
        if isinstance(goal, str) and goal in graph.places:
            place_yaw = getattr(graph.places[goal], "yaw", None)
            if place_yaw is not None:
                pts[-1]["yaw"] = round(float(place_yaw), 4)
        elif isinstance(goal, tuple) and len(goal) > 2 and goal[2] is not None:
            pts[-1]["yaw"] = round(float(goal[2]), 4)
    return tuple(pts)


def _goal_targets(
    graph: Graph, goal: str | tuple[float, float] | tuple[float, float, float | None]
) -> list[str | tuple[float, float, float | None]]:
    if isinstance(goal, str):
        if goal in graph.places:
            gx, gy = graph.place_xy(goal)
            return [goal, (gx, gy, None)]
        return [goal]
    gx, gy = float(goal[0]), float(goal[1])
    gyaw = float(goal[2]) if len(goal) > 2 and goal[2] is not None else None
    if gyaw is not None:
        return [(gx, gy, gyaw), (gx, gy, None)]
    return [(gx, gy, None)]


def plan_road_path(
    graph: Graph,
    start_pose: tuple[float, float] | tuple[float, float, float | None],
    goal: str | tuple[float, float] | tuple[float, float, float | None],
    config: RoutingConfig = RoutingConfig(),
    *,
    step_m: float = 0.12,
    via: tuple[str, ...] = (),
    arrive_yaw: float | None = None,
    blocked_edges: frozenset[str] = frozenset(),
) -> RoadPathPlan:
    """General Rule 1: snap ``start_pose`` and ``goal`` to ``graph`` and emit road-following waypoints."""
    sx, sy = float(start_pose[0]), float(start_pose[1])
    syaw = float(start_pose[2]) if len(start_pose) > 2 and start_pose[2] is not None else None
    candidates = _candidate_start_poses(graph, sx, sy, syaw, config)
    if not candidates:
        raise PlanError("TRIP_START_OFF_MAP", {"off_lane_m": None})

    best_plan: Plan | None = None
    best_dist: float = math.inf
    last_err: PlanError | None = None
    targets = _goal_targets(graph, goal)
    for dist_m, cx, cy, cyaw in candidates:
        if best_plan is not None and dist_m > best_dist + 0.03:
            break
        cand_pose = (cx, cy, cyaw)
        for target in targets:
            req = PlanRequest(
                map_version=graph.version,
                start_pose=cand_pose,
                goal=target,
                via=via,
                arrive_yaw=arrive_yaw,
                blocked_edges=blocked_edges,
            )
            try:
                plan = plan_trip(graph, req, config)
                if best_plan is None or plan.eta_s + 0.25 < best_plan.eta_s:
                    best_plan = plan
                    best_dist = dist_m
                break
            except PlanError as exc:
                last_err = exc

    if best_plan is None:
        raise last_err or PlanError("TRIP_NO_ROUTE", {"segment": 0, "unblock_would_help": False})

    waypoints = _sample_plan_waypoints(graph, best_plan, (sx, sy), goal, step_m)
    edges: list[str] = []
    for edge_id, _fwd, _s0, _s1 in best_plan.segments:
        if not edges or edges[-1] != edge_id:
            edges.append(edge_id)
    places = list(best_plan.places)
    if isinstance(goal, str) and (not places or places[-1] != goal):
        places.append(goal)
    return RoadPathPlan(
        waypoints_site=waypoints,
        places=tuple(places),
        edges=tuple(edges),
        segments=best_plan.segments,
        length_m=best_plan.length_m,
        eta_s=best_plan.eta_s,
        map_version=best_plan.map_version,
    )
