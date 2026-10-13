"""The route fact bundle names each planner and carries no command."""

from __future__ import annotations

import pytest

from fleet.routing.brief import route_context
from fleet.routing.cost import RoutingConfig
from fleet.routing.execute import plan_again
from fleet.routing.graph import build_graph
from fleet.site_map import SiteMap


def test_route_context_names_each_planner_and_refuses_a_command():
    bundle = route_context(planner="lane_graph", supplied={"to": "NW", "blocked_edges": []},
                           holds={"segments": ["ring_s"]})
    assert bundle["role"] == "fact" and bundle["planner"] == "lane_graph"
    assert [row["id"] for row in bundle["planners"]] == ["lane_graph", "lane_step", "nav2", "grid"]
    assert [row["live"] for row in bundle["planners"]] == [True, True, False, False]
    assert [row["motion"] for row in bundle["planners"]] == [
        "line_follow", "short_point", "open_floor", "occupancy"]
    assert bundle["planners"][0]["give"] == [
        "to", "via", "arrive_yaw", "speed_cap", "blocked_edges", "extra_cost"]
    assert bundle["planners"][1]["note"] == "one_point_goal"
    assert bundle["planners"][2]["note"] == "not_this_runtime"
    text = str(bundle)
    for verb in ("WAIT", "YIELD", "RESUME", "ABORT", "MANUAL"):
        assert verb not in text
    assert "command" not in bundle and "decision" not in bundle
    with pytest.raises(ValueError):
        route_context(planner="smac", supplied={}, holds={})
    with pytest.raises(ValueError):
        route_context(planner="lane_step", supplied={"decision": "WAIT"}, holds={})


def test_plan_again_keeps_the_callers_block_and_cost():
    places = {"Z": (-1, 0), "A": (0, 0), "U": (1, 1), "D": (1, -1), "B": (2, 0)}
    edges = [("z_a", "Z", "A"), ("a_u", "A", "U"), ("a_d", "A", "D"), ("u_b", "U", "B"), ("d_b", "D", "B")]
    site = SiteMap(
        places=[{"id": pid, "name": pid, "x": xy[0], "y": xy[1]} for pid, xy in places.items()],
        edges=[{"id": edge, "from": start, "to": end, "polyline": [places[start], places[end]],
                "direction": "one_way", "width_m": 0.2, "speed_cap_mps": 1.0}
               for edge, start, end in edges])
    graph = build_graph(site, version=1)
    active = (1, None, graph)
    caps = {"kind": "pinky_pro", "modes": ["lane", "free"], "max_speed": 1.0, "junction_turn": True}
    blocked, _hold = plan_again(active, (-0.5, 0.0, 0.0), {"to": "B", "blocked_edges": ["a_d"]},
                                caps, frozenset(), set(), RoutingConfig())
    costed, cost_hold = plan_again(active, (-0.5, 0.0, 0.0), {"to": "B", "extra_cost": {"a_d": 1.0}},
                                   caps, frozenset(), set(), RoutingConfig())
    assert _hold is None and cost_hold is None
    assert [seg["edge_id"] for seg in blocked["segments"]] == ["z_a", "a_u", "u_b"]
    assert [seg["edge_id"] for seg in costed["segments"]] == ["z_a", "a_u", "u_b"]
