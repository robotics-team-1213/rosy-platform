"""D-485 2·4·6: one A* over layered lane states with a time cost (``heapq``, deterministic ties).

A state ``(k, arc)`` is "at the end of this arc, via places 0..k-1 already visited". Reaching
via ``k``'s place moves the same arc end to layer ``k+1`` at no extra cost, so the arc that
arrived keeps its heading into the next leg (still no U-turn at a via) and the whole trip is
optimal, not leg by leg. The robot's own arc from ``s0`` is the state name ``^``; the goal
is ``$``: the end of an arc into the goal place, or a point ``s`` on an arc for a coordinate
target. Heap order is ``(f, -g, arc id, layer)``: on equal f the larger g, then the smaller
id — the same input always gives the same route.

The bound is the straight distance to the next via, plus the straight distances between the
remaining vias and the goal, at the fastest allowed speed. Straight lines never exceed a lane
(ends are pinned to places) and turn/place costs are ≥ 0, so it never overestimates.
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
           extra_cost: Mapping[str, float] | None = None, via: tuple[str, ...] = (),
           use_heuristic: bool = True, stats: dict | None = None) -> tuple[float, list[Segment]] | None:
    """Cheapest ``(cost_s, segments)`` or None. ``use_heuristic=False`` is plain Dijkstra.

    ``stats["layer"]`` is the highest via layer reached: on None it names the failing leg.
    """
    extra = extra_cost or {}
    arcs = graph.arcs
    final = len(via)
    rate = {arc_id: 1.0 / speed(arc) for arc_id, arc in arcs.items()}
    vmax = 1.0 / min(rate.values())
    successors = graph.successors(config, lambda arc, nxt, kind: transition_cost(
        turn_deg(arc.end_tangent, nxt.start_tangent), kind, config))
    full = {arc_id: arc.length_m * rate[arc_id] + extra.get(arc.edge_id, 0.0)
            for arc_id, arc in arcs.items() if allowed(arc)}
    targets = [graph.place_xy(place) for place in via] + [goal.xy]
    rest = [0.0] * (final + 1)  # straight distance from target k through the later targets
    for k in range(final - 1, -1, -1):
        rest[k] = rest[k + 1] + math.dist(targets[k], targets[k + 1])
    bound: dict[tuple[str, int], float] = {}

    def h(place: str, k: int) -> float:
        if not use_heuristic:
            return 0.0
        key = (place, k)
        if key not in bound:
            bound[key] = heuristic(graph.place_xy(place), targets[k], vmax) + rest[k] / vmax
        return bound[key]

    def leg(arc: Arc, s_from: float, s_to: float) -> float:
        return (s_to - s_from) * rate[arc.id] + extra.get(arc.edge_id, 0.0)

    first = arcs[start[0]]
    end_of: dict[str, Arc] = {START: first}
    best: dict[tuple[str, int], float] = {}
    came: dict[tuple[str, int], tuple[tuple[str, int] | None, Segment | None]] = {}
    heap: list[tuple[float, float, str, int]] = []
    top = 0

    def relax(state: tuple[str, int], g: float, parent, segment: Segment | None) -> None:
        if g < best.get(state, math.inf):
            best[state] = g
            came[state] = (parent, segment)
            name, k = state
            f = g if name == GOAL else g + h(end_of[name].end_place, k)
            heapq.heappush(heap, (f, -g, name, k))

    if final == 0 and start[0] in goal.on_arcs and goal.on_arcs[start[0]] >= start[1]:
        s_goal = goal.on_arcs[start[0]]
        relax((GOAL, final), leg(first, start[1], s_goal), None, (first.id, start[1], s_goal))
    relax((START, 0), leg(first, start[1], first.length_m), None, (first.id, start[1], first.length_m))
    done: set[tuple[str, int]] = set()
    while heap:
        _f, neg_g, name, k = heapq.heappop(heap)
        state = (name, k)
        if state in done:
            continue
        done.add(state)
        top = max(top, k)
        g = -neg_g
        if name == GOAL:
            if stats is not None:
                stats["layer"] = final
            return g, _segments(came, state)
        arc = end_of[name]
        place = arc.end_place
        if k < final and via[k] == place:
            relax((name, k + 1), g, state, None)
            continue
        if k == final and goal.place == place and (goal.arrive_ok is None or goal.arrive_ok(arc)):
            relax((GOAL, final), g, state, None)
        for nxt_id, step in successors[arc.id]:
            cost = full.get(nxt_id)
            if cost is None:
                continue
            nxt = arcs[nxt_id]
            if k == final and nxt_id in goal.on_arcs:  # a point part-way: before the done check
                s_goal = goal.on_arcs[nxt_id]
                relax((GOAL, final), g + step + leg(nxt, 0.0, s_goal), state, (nxt_id, 0.0, s_goal))
            if (nxt_id, k) in done:
                continue
            end_of[nxt_id] = nxt
            relax((nxt_id, k), g + step + cost, state, (nxt_id, 0.0, nxt.length_m))
    if stats is not None:
        stats["layer"] = top
    return None


def _segments(came, state) -> list[Segment]:
    out: list[Segment] = []
    while state is not None:
        parent, segment = came[state]
        if segment is not None:
            out.append(segment)
        state = parent
    out.reverse()
    return out
