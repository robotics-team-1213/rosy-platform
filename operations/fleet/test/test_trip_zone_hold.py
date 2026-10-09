"""D-517 3 (2026-10-09 signal SIM): no trip stops or holds inside a site zone; a blocked edge is never a
lap's first arc. On ``test_blocks._demo_map()`` (one way) every junction place is a roundabout corner."""

from __future__ import annotations

import pytest

from fleet.routing.execute import arc_id, plan_again, plan_body, route_key
from fleet.routing.graph import build_graph
from fleet.routing.trip import PlanRequest, plan_trip
from fleet.server.site_map_store import SiteMapStore
from fleet.server.trip_ports import TripConfig
from fleet.server.trip_runner import TripError, TripRunner
from fleet.traffic.zone_hold import hold_back_m
from test_blocks import _demo_map
from test_lane_traffic import START_N, Fleet, _s_of, _ticks
from test_routing import demo_site
from test_trip_runner import run

RING = ("ring_n", "ring_s", "ring_e", "ring_w")
#: The SIM's operator closure: every lap is the outer loop east -> ring_n -> west -> ring_s.
CHORDS = frozenset({"ring_e", "ring_w"})
CAPS = {"kind": "pinky_pro", "modes": ["lane"], "max_speed": 0.2, "junction_turn": True, "junction_pivot": True}


def _setup(zones=True):
    fleet = Fleet(("a",))
    fleet.blocked = CHORDS
    store = SiteMapStore(None, clock=lambda: fleet.now)
    store.import_if_empty(demo_site(), source="test")
    runner = TripRunner(store=store, routing_config=store.routing_config, caps=fleet.caps_for, poses=fleet,
                        junction=fleet, goal=fleet.goal, cancel_goal=fleet.cancel_goal,
                        blocked=lambda: fleet.blocked, clock=lambda: fleet.now, config=TripConfig(),
                        traffic_zones={"roundabout": (RING, 1)} if zones else None)
    return runner, store, fleet


def _trip(runner, store, fleet, to="SE", via=("NW",), repeat=True):
    """A trip from start_n on east, planned with ``fleet.blocked`` closed like the console plans it."""
    graph = store.active()[2]
    arc, s = graph.arcs["east:fwd"], _s_of(store, "east:fwd", START_N)
    fleet.at("a", arc, s)
    plan = plan_trip(graph, PlanRequest(store.active()[0], arc.point_at(s), to, via=tuple(via),
                                        blocked_edges=fleet.blocked), store.routing_config)
    store.record_plan(plan_id="a", robot_id="a", principal_id="bob", map_version=plan.map_version,
                      request={"to": to, "via": list(via), "repeat": repeat}, result={"plan": plan_body(plan)})
    return run(runner.start("a", "bob"))


def _zone_units(runner, store, pose):
    traffic = runner.traffic
    return set(traffic._under(traffic._layout_for(store.active()), store.active()[2], pose)) & {"roundabout"}


def _unit(runner, unit_id):
    return next(u for u in runner.traffic.view()["units"] if u["id"] == unit_id)


def test_a_lap_ending_at_a_zone_corner_never_holds_inside_the_zone_and_releases_it():
    runner, store, fleet = _setup()
    graph = store.active()[2]
    view = _trip(runner, store, fleet)
    live = runner._live["a"]
    # SE is the end of ring_s (inside the zone): the lap end moved on to NE, reached over east
    assert (live.request["to"], live.request["via"], live.request["cycle"]) == ("NE", ["NW", "SE"], ["SE", "NW"])
    assert [s["edge_id"] for s in view["plan"]["segments"]] == ["east", "ring_n", "west", "ring_s", "east"]
    assert view["plan"]["places"][-1] == "NE" and view["hold"] is None
    unholdable = set()
    for i, seg in enumerate(live.segments):  # a hold stops clear of the zone, or never happens there
        back = hold_back_m(runner.traffic, seg)
        if live.place(i) and back is None:
            unholdable.add(live.place(i))
        elif live.place(i):
            assert not _zone_units(runner, store, live.arc(i).point_at(seg["s_to"] - back)), live.place(i)
    assert unholdable == {"NW", "SE"}  # reached over ring_n / ring_s, inside the roundabout

    # The robot drives the ring (holds the zone), then reaches the lap's last place with a failed lap check.
    ring_s = graph.arcs["ring_s:fwd"]
    live.view["segment_index"] = 3
    fleet.at("a", ring_s, ring_s.length_m / 2)
    _ticks(runner, fleet)
    assert "a" in _unit(runner, "roundabout")["holders"]
    tail = len(live.segments) - 1
    live.view["segment_index"] = tail
    before = 0.5
    fleet.at("a", live.arc(tail), live.segments[tail]["s_to"] - before, anchor_age_s=2.5)
    _ticks(runner, fleet)
    view = runner.view("a")
    assert (view["hold"]["reason"], view["hold"]["code"]) == ("lap", "TRIP_POSE_UNTRUSTED")
    back = hold_back_m(runner.traffic, live.segments[tail])
    assert back > 0 and fleet.p["a"].sent[-1] == ("stop", "NE", round(before - back, 3))  # short of NE
    # standing where that stop holds it: clear of the zone, and the zone is FREE again
    held_at = live.arc(tail).point_at(live.segments[tail]["s_to"] - back)
    assert not _zone_units(runner, store, held_at)
    fleet.at("a", live.arc(tail), live.segments[tail]["s_to"] - back)
    _ticks(runner, fleet, 2)
    assert _unit(runner, "roundabout")["state"] == "FREE" and runner.view("a")["state"] == "running"


def test_the_next_lap_holds_where_it_can_stand_outside_the_zone():
    """Every lap after the first runs NE -> NE and never holds inside the roundabout."""
    runner, store, fleet = _setup()
    _trip(runner, store, fleet)
    live = runner._live["a"]
    tail = len(live.segments) - 1
    live.view["segment_index"] = tail
    fleet.at("a", live.arc(tail), live.segments[tail]["s_to"] - 0.3)
    _ticks(runner, fleet)
    view = runner.view("a")
    assert view["lap"] == 2 and view["hold"] is None  # the same cycle: no operator hold at lap 1's end
    assert view["plan"]["places"][-1] == "NE"


def test_a_trip_that_would_stop_inside_a_zone_is_refused():
    runner, store, fleet = _setup()
    with pytest.raises(TripError) as err:  # a one-way trip ends at NE: its nose and body pin the roundabout
        _trip(runner, store, fleet, to="NE", via=(), repeat=False)
    assert (err.value.code, err.value.detail) == ("TRIP_STOP_IN_ZONE", {"place": "NE", "repeat": False})
    assert runner._live == {}
    runner, store, fleet = _setup()
    fleet.blocked = frozenset()  # open chords: SE via NW laps the ring itself, no place outside the zone
    with pytest.raises(TripError) as err:
        _trip(runner, store, fleet)
    assert (err.value.code, err.value.detail) == ("TRIP_STOP_IN_ZONE", {"place": "SE", "repeat": True})
    runner, store, fleet = _setup(zones=False)  # no site zones: unchanged
    view = _trip(runner, store, fleet, to="NE", via=(), repeat=False)
    assert view["state"] == "started"


def test_a_blocked_edge_is_never_the_first_arc_of_a_lap():
    graph = build_graph(_demo_map(), version=1)
    store = SiteMapStore(None)
    store.import_if_empty(_demo_map(), source="test")
    active, config = store.active(), store.routing_config
    blocked = frozenset({"ring_e", "ring_w"})
    start = graph.arcs["east:fwd"].point_at(2.9)
    plan = plan_body(plan_trip(active[2], PlanRequest(active[0], start, "SE", via=("NW",), blocked_edges=blocked),
                               config))
    end = active[2].arcs[arc_id(plan["segments"][-1])].point_at(plan["segments"][-1]["s_to"])
    for closed in (blocked, frozenset({"ring_e"}), frozenset({"east"})):
        lap = plan_trip(active[2], PlanRequest(active[0], end, "SE", via=("NW",), blocked_edges=closed), config)
        assert all(edge not in closed for edge, *_ in lap.segments), (closed, lap.segments)
    body, hold = plan_again(active, end, {"to": "SE", "via": ["NW"], "repeat": True}, CAPS, blocked, set(), config)
    assert hold is None and route_key(body["segments"]) == route_key(plan["segments"])  # the same lap again


def test_a_lap_with_closed_chords_carries_on_without_a_hold():
    """The SIM case: ring_e/ring_w closed, lap SE via NW; lap 2 was planned onto ring_e and held at SE."""
    runner, store, fleet = _setup(zones=False)
    _trip(runner, store, fleet)
    live = runner._live["a"]
    tail = len(live.segments) - 1
    live.view["segment_index"] = tail
    fleet.at("a", live.arc(tail), live.segments[tail]["s_to"] - 0.3)
    _ticks(runner, fleet)
    view = runner.view("a")
    assert view["lap"] == 2 and view["hold"] is None
    assert not {s["edge_id"] for s in view["plan"]["segments"]} & fleet.blocked


def test_a_coordinate_lap_end_whose_last_place_is_in_the_zone_moves_on():
    """The earlier SIM's laps: the goal is the start point on east, so the lap's last place is SE (in the zone)."""
    runner, store, fleet = _setup()
    graph = store.active()[2]
    arc, s = graph.arcs["east:fwd"], _s_of(store, "east:fwd", START_N)
    fleet.at("a", arc, s)
    x, y, yaw = arc.point_at(s)
    plan = plan_trip(graph, PlanRequest(store.active()[0], (x, y, yaw), (x, y, yaw), via=("NW",),
                                        blocked_edges=fleet.blocked), store.routing_config)
    store.record_plan(plan_id="a", robot_id="a", principal_id="bob", map_version=plan.map_version,
                      request={"to": {"x": x, "y": y, "yaw": yaw}, "via": ["NW"], "repeat": True},
                      result={"plan": plan_body(plan)})
    view = run(runner.start("a", "bob"))
    live = runner._live["a"]
    assert (live.request["to"], live.request["via"]) == ("NE", ["NW"]) and view["plan"]["places"][-1] == "NE"
    tail = len(live.segments) - 1
    live.view["segment_index"] = tail
    fleet.at("a", live.arc(tail), live.segments[tail]["s_to"] - 0.3)
    _ticks(runner, fleet)
    assert runner.view("a")["lap"] == 2 and runner.view("a")["hold"] is None
