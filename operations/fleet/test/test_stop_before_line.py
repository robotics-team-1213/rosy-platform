"""A place of kind "stop" is the stop line: the body front halts on it (user decision 2026-11-19)."""

from __future__ import annotations

import math

import pytest

from core_common.robot_body import NOMINAL_BODY

from fleet.routing.cost import RoutingConfig
from fleet.routing.graph import build_graph
from fleet.routing.snap import PlanError
from fleet.routing.stop_line import FALLBACK_FRONT_M
from fleet.routing.trip import PlanRequest, plan_trip
from fleet.site_map import SiteMap
from fleet.stop_front import body_front_m

CFG = RoutingConfig()
assert FALLBACK_FRONT_M == NOMINAL_BODY.front_x_m == body_front_m(None)  # routing is stdlib-only: constant pinned here
OFF = body_front_m("no-such-kind") + 0.01  # 0.05205 for the registered body
assert math.isclose(OFF, 0.05205)


def _graph(kind="stop", yaw=None, a=(-1.0, -0.47608), b=(0.1597, -0.47608)):
    place = {"id": "S", "name": "S", "x": b[0], "y": b[1], "kind": kind}
    if yaw is not None:
        place["yaw"] = yaw
    site = SiteMap(places=[{"id": "A", "name": "A", "x": a[0], "y": a[1], "kind": "junction"}, place],
                   edges=[{"id": "ab", "from": "A", "to": "S", "polyline": [list(a), list(b)], "direction": "one_way",
                           "width_m": 0.2, "speed_cap_mps": 1.0}])
    return build_graph(site, version=1)


def _plan(graph, start, goal="S", **kw):
    return plan_trip(graph, PlanRequest(map_version=1, start_pose=start, goal=goal, **kw), CFG)


def _end(graph, plan):
    """The point the runner's arrival judgement and the align step read: the last segment's s_to."""
    edge, forward, _s0, s1 = plan.segments[-1]
    arc = next(a for a in graph.arcs.values() if a.edge_id == edge and a.forward == forward)
    return arc.point_at(s1)[:2]


def test_s4_arriving_east_stops_the_centre_before_the_line():
    graph = _graph()
    x, y = _end(graph, _plan(graph, (-0.8, -0.47608, 0.0)))
    assert math.isclose(x, 0.1597 - 0.05205, abs_tol=1e-4) and math.isclose(y, -0.47608, abs_tol=1e-4)


def test_s3_with_yaw_pi_arriving_west_stops_east_of_the_line():
    graph = _graph(yaw=math.pi, a=(1.9, 0.2), b=(0.745, 0.2))
    x, _y = _end(graph, _plan(graph, (1.5, 0.2, math.pi)))
    assert math.isclose(x, 0.745 + 0.05205, abs_tol=1e-4)


def test_a_junction_is_unchanged():
    graph = _graph(kind="junction")
    assert math.isclose(_end(graph, _plan(graph, (-0.8, -0.47608, 0.0)))[0], 0.1597, abs_tol=1e-4)


def test_arrival_is_judged_at_the_offset_goal_not_the_line():
    graph = _graph()
    at_goal = _plan(graph, (0.1597 - OFF, -0.47608, 0.0))
    assert at_goal.segments == () and at_goal.places == ("S",)
    with pytest.raises(PlanError):  # the centre on the line is already past the goal: not arrived
        _plan(graph, (0.1597, -0.47608, 0.0))
    far = _plan(graph, (0.1597 - OFF - 0.2, -0.47608, 0.0))
    assert far.segments and math.isclose(_end(graph, far)[0], 0.1597 - OFF, abs_tol=1e-4)
