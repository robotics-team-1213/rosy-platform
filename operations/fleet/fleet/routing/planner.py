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
    arcs = graph.arcs
    rate = {arc_id: 1.0 / speed(arc) for arc_id, arc in arcs.items()}
    vmax = 1.0 / min(rate.values())
    # Per search: the full cost of each usable arc and the bound of each place.
    full = {arc_id: arc.length_m * rate[arc_id] + extra.get(arc.edge_id, 0.0)
            for arc_id, arc in arcs.items() if allowed(arc)}
    bound = {place: (heuristic(graph.place_xy(place), goal.xy, vmax) if use_heuristic else 0.0)
             for place in graph.places}

    def leg(arc: Arc, s_from: float, s_to: float) -> float:
        return (s_to - s_from) * rate[arc.id] + extra.get(arc.edge_id, 0.0)

    successors = graph.successors(config, lambda arc, nxt, kind: transition_cost(
        turn_deg(arc.end_tangent, nxt.start_tangent), kind, config))
    first = arcs[start[0]]
    end_of: dict[str, Arc] = {START: first}
    best: dict[str, float] = {}
    came: dict[str, tuple[str | None, Segment | None]] = {}
    heap: list[tuple[float, float, str]] = []

    def relax(state: str, g: float, parent: str | None, segment: Segment | None) -> None:
        if g < best.get(state, math.inf):
            best[state] = g
            came[state] = (parent, segment)
            h = 0.0 if state == GOAL else bound[end_of[state].end_place]
            heapq.heappush(heap, (g + h, -g, state))

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
        arc = end_of[state]
        place = arc.end_place
        if goal.place == place and (goal.arrive_ok is None or goal.arrive_ok(arc)):
            relax(GOAL, g, state, None)
        for nxt_id, step in successors[arc.id]:
            cost = full.get(nxt_id)
            if cost is None or nxt_id in done:
                continue
            nxt = arcs[nxt_id]
            if nxt_id in goal.on_arcs:
                s_goal = goal.on_arcs[nxt_id]
                relax(GOAL, g + step + leg(nxt, 0.0, s_goal), state, (nxt_id, 0.0, s_goal))
            end_of[nxt_id] = nxt
            relax(nxt_id, g + step + cost, state, (nxt_id, 0.0, nxt.length_m))
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
