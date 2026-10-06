"""D-485 2·4: A* over lane states with a time cost (``heapq``, deterministic ties).

A state is "at the end of this arc". The start is the robot's arc from ``s0`` (state
``^``), the goal a virtual state ``$``: the end of an arc into the goal place, or a point
``s`` on an arc for a coordinate target. Heap order is ``(f, -g, state id)``: on equal f the
larger g, then the smaller id — the same input always gives the same route.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from typing import Callable, Mapping

from fleet.routing.cost import RoutingConfig, heuristic, transition_cost, turn_deg
from fleet.routing.graph import Arc, Graph

START, GOAL = "^", "$"


@dataclass(frozen=True)
class Goal:
    xy: tuple[float, float]
    place: str | None = None
    #: Place goal: may this arc end the trip (arrive yaw)? None accepts any.
    arrive_ok: Callable[[Arc], bool] | None = None
    #: Coordinate goal: arc id -> s on that arc.
    on_arcs: Mapping[str, float] = field(default_factory=dict)


Segment = tuple[str, float, float]  # (arc id, s_from, s_to)


def search(graph: Graph, start: tuple[str, float], goal: Goal, config: RoutingConfig, *,
           allowed: Callable[[Arc], bool], speed: Callable[[Arc], float],
           extra_cost: Mapping[str, float] | None = None,
           use_heuristic: bool = True) -> tuple[float, list[Segment]] | None:
    """Cheapest ``(cost_s, segments)`` or None. ``use_heuristic=False`` is plain Dijkstra."""
    extra = extra_cost or {}
    vmax = max(speed(arc) for arc in graph.arcs.values())

    def leg(arc: Arc, s_from: float, s_to: float) -> float:
        return (s_to - s_from) / speed(arc) + extra.get(arc.edge_id, 0.0)

    def h(state: str) -> float:
        if not use_heuristic or state == GOAL:
            return 0.0
        return heuristic(graph.place_xy(arc_of[state].end_place), goal.xy, vmax)

    first = graph.arcs[start[0]]
    arc_of: dict[str, Arc] = {START: first}
    best: dict[str, float] = {}
    came: dict[str, tuple[str | None, Segment | None]] = {}
    heap: list[tuple[float, float, str]] = []

    def relax(state: str, g: float, parent: str | None, segment: Segment | None) -> None:
        if g < best.get(state, math.inf):
            best[state] = g
            came[state] = (parent, segment)
            heapq.heappush(heap, (g + h(state), -g, state))

    if start[0] in goal.on_arcs and goal.on_arcs[start[0]] >= start[1]:
        s_goal = goal.on_arcs[start[0]]
        relax(GOAL, leg(first, start[1], s_goal), None, (first.id, start[1], s_goal))
    relax(START, leg(first, start[1], first.length_m), None, (first.id, start[1], first.length_m))
    done: set[str] = set()
    while heap:
        _f, neg_g, state = heapq.heappop(heap)
        if state in done:
            continue
        done.add(state)
        g = -neg_g
        if state == GOAL:
            return g, _segments(came)
        arc = arc_of[state]
        place = arc.end_place
        if goal.place == place and (goal.arrive_ok is None or goal.arrive_ok(arc)):
            relax(GOAL, g, state, None)
        kind = getattr(graph.places[place], "kind", "junction")
        for nxt_id in graph.out_of.get(place, ()):
            nxt = graph.arcs[nxt_id]
            if not allowed(nxt) or (place, arc.edge_id, nxt.edge_id) in graph.bans:
                continue
            step = transition_cost(turn_deg(arc.end_tangent, nxt.start_tangent), kind, config)
            if step is None:
                continue
            if nxt_id in goal.on_arcs:
                s_goal = goal.on_arcs[nxt_id]
                relax(GOAL, g + step + leg(nxt, 0.0, s_goal), state, (nxt_id, 0.0, s_goal))
            arc_of[nxt_id] = nxt
            relax(nxt_id, g + step + leg(nxt, 0.0, nxt.length_m), state, (nxt_id, 0.0, nxt.length_m))
    return None


def _segments(came) -> list[Segment]:
    out: list[Segment] = []
    state: str | None = GOAL
    while state is not None:
        parent, segment = came[state]
        if segment is not None:
            out.append(segment)
        state = parent
    out.reverse()
    return out
