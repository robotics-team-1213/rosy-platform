"""D-525 rev 5: site map ``map_v2_fleet`` v5, traced from the painted track (ceiling_north, paint-7b220d432c2a).

The map is a file to activate on the site (``deploy/site/site-maps``); these checks are what activation and
the D-525 signal check would refuse, plus the D-517 loop limit the demo needs.
"""

import json
import math
from pathlib import Path
from types import SimpleNamespace

from fleet.routing.cost import RoutingConfig
from fleet.routing.graph import build_graph
from fleet.routing.trip import prepare
from fleet.site_map import SiteMap
from fleet.traffic import signal_phase
from fleet.traffic.blocks import build_layout, loop_capacity
from fleet.traffic.config import _traffic_signals, _traffic_zones
from test_blocks import DEMO

ROOT = Path(__file__).resolve().parents[3]
V5 = ROOT / "deploy" / "site" / "site-maps" / "map_v2_fleet-v5.json"
EXAMPLE = ROOT / "deploy" / "site" / "fleet-site.yaml.example"
FIGURE_EIGHT = ["west:fwd", "ring_in_sw:fwd", "ring_s:fwd", "ring_out_se:fwd", "east_out:fwd", "east:fwd",
                "ring_in_ne:fwd", "ring_n:fwd", "ring_out_nw:fwd", "west_out:fwd"]


def _v5():
    return SiteMap.model_validate(json.loads(V5.read_text(encoding="utf-8")))


def test_v5_validates_is_plannable_and_keeps_the_view_turn():
    site_map = _v5()
    assert site_map.map_id == "map_v2_fleet" and site_map.view_turn_deg == 90
    assert site_map.body() == json.loads(V5.read_text(encoding="utf-8"))   # stored as the store would keep it
    prepare(build_graph(site_map), RoutingConfig())                        # activation's SITE_MAP_UNPLANNABLE check
    assert all(edge.direction == "one_way" for edge in site_map.edges)
    assert {c.id: c.lanes for c in site_map.crosswalks} == {"cw_west": ["west"], "cw_south": ["east_out"]}


def test_the_ring_turns_counter_clockwise_seen_from_above():
    """Right-hand traffic. The map frame is right-handed seen from above (map_to_image det < 0 with image y down)."""
    edges = {edge.id: edge for edge in _v5().edges}
    ring = [p for name in ("ring_e", "ring_n", "ring_w", "ring_s") for p in edges[name].polyline]
    area = sum(ax * by - bx * ay for (ax, ay), (bx, by) in zip(ring, ring[1:] + ring[:1])) / 2
    assert area > 0


def test_every_lane_is_reachable_from_every_place():
    graph = build_graph(_v5())
    out: dict[str, set[str]] = {}
    for arc in graph.arcs.values():
        out.setdefault(arc.start_place, set()).add(arc.end_place)
    places = {place.id for place in _v5().places}
    for start in places:
        seen, todo = {start}, [start]
        while todo:
            for nxt in out.get(todo.pop(), ()):
                if nxt not in seen:
                    seen.add(nxt)
                    todo.append(nxt)
        assert seen == places, f"from {start} unreachable: {sorted(places - seen)}"


def test_site_config_example_signals_the_two_real_entrances_of_v5():
    """Four painted stripes, two entrances: each spoke is one lane, so on one-way loops NW and SE are exits."""
    args = SimpleNamespace(site_config=EXAMPLE)
    zones, plans = _traffic_zones(args), _traffic_signals(args)
    graph = build_graph(_v5())
    layout = build_layout(graph, DEMO, zones)
    assert signal_phase.entering_arcs(graph, layout, "roundabout") == {"east:fwd", "west:fwd"}
    assert [signal_phase.check(plan, graph, layout) for plan in plans] == [[]]
    # the stop line (zone start) is the painted stripe, not the ring centre line
    places = {place.id: place for place in _v5().places}
    for approach, line in (("east:fwd", "NE_line"), ("west:fwd", "SW_line")):
        assert graph.arcs[approach].end_place == line
        assert math.hypot(places[line].x + 0.3515, places[line].y + 0.0213) > 0.37


def test_the_demo_figure_eight_keeps_room_for_more_than_one_robot():
    graph = build_graph(_v5())
    layout = build_layout(graph, DEMO, _traffic_zones(SimpleNamespace(site_config=EXAMPLE)))
    loop = layout.route(graph, FIGURE_EIGHT)
    assert [s.unit for s in loop].count("roundabout") == 2
    assert loop_capacity(loop, layout, held_per_robot=3) >= 2
