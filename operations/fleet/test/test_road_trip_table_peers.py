"""D-1009 road trips: standing peers the block table counted are left to the table, which cuts the route at the
place before their units; pins behind a robot's rear do not refuse the unit under its front (2026-11-27 live run)."""

from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from core_common.robot_body import PINKY_PRO
from fleet.server import trip_nav2_route as nav2
from fleet.server.console import FleetConsole
from fleet.swarm.robots import RobotEndpoint
from fleet.traffic.blocks import Layout, Robot, Span, TableState, Unit, step
from fleet.traffic.lane_traffic import PAST_PLACE_M
from fleet.traffic.lane_traffic_helpers import occupied_ahead
from fakes import FakeClock, run
from test_lane_traffic import _arc, _setup, _ticks, _trip
from test_trip_nav2_route import RouteFakeRobot

BODY = PINKY_PRO.front_x_m - PINKY_PRO.rear_x_m


# ---- the table: a pin behind the rear (C) --------------------------------------------------------

def _two_units():
    layout = Layout({"u0": Unit("u0"), "u1": Unit("u1")}, {})
    spans = (Span("u0", 0.0, 1.0), Span("u1", 1.0, 2.0))
    return layout, spans


@pytest.mark.parametrize("behind, granted", [({}, False), ({"m": ["p"]}, True), ({"m": ["q"]}, False)])
def test_only_a_pin_measured_behind_leaves_the_unit_under_the_front(behind, granted):
    layout, spans = _two_units()
    state = TableState()
    state.pinned["p"] = {"u0": True}
    robot = Robot("m", spans, 0.6, 0.2, 0.1, BODY, route_id="t:1")
    result = step(layout, [robot], state, 0.0, behind=behind)
    assert (0 in state.held["m"]) is granted
    assert result.waiting_for["m"] == (() if granted else ("p",))
    if granted:  # the unit it holds is not a cut; nothing else is taken
        from fleet.traffic.lane_traffic_helpers import unit_owners
        assert occupied_ahead(robot, state, unit_owners(state)) is None


def test_a_trip_robot_named_behind_still_refuses_the_unit():
    layout, spans = _two_units()
    state = TableState()
    other = Robot("q", (Span("u0", 0.0, 1.0),), 0.9, 0.0, 0.1, BODY, route_id="q:1")
    mover = Robot("m", spans, 0.4, 0.2, 0.1, BODY, route_id="t:1")
    result = step(layout, [other, mover], state, 0.0, behind={"m": ["q"]})
    assert 0 not in state.held["m"] and result.waiting_for["m"] == ("q",)


def _pinned_then(start_peer, start_mover):
    """'a' ends its trip and stands as a pin at ``start_peer`` on east; 'b' starts at ``start_mover``."""
    runner, store, fleet = _setup()
    east = _arc(store, "east:fwd")
    unit = east.length_m / 6  # east is cut into 6 (test_blocks)
    _trip(runner, store, fleet, "a", "east:fwd", unit * start_peer)
    _ticks(runner, fleet)
    run(runner.cancel("a", "bob"))
    _ticks(runner, fleet, n=2)
    assert runner.traffic.pinned() == ["a"]
    _trip(runner, store, fleet, "b", "east:fwd", unit * start_mover)
    _ticks(runner, fleet)
    return runner, runner._live["b"].traffic


def test_a_departure_away_from_a_pin_behind_is_granted():
    runner, traffic = _pinned_then(1.02, 1.7)  # same unit; the pin ends before b's rear
    assert traffic["refused_at_m"] is None and list(traffic["peers"]) == ["a"]
    assert traffic["route_rev"] == runner._live["b"].route_rev


def test_only_pins_on_the_route_ahead_are_counted():
    from fleet.traffic.lane_traffic_helpers import route_occupants
    robot = Robot("m", (Span("u0", 0.0, 1.0), Span("u1", 1.0, 2.0)), 0.6, 0.2, 0.1, BODY)
    owners = {"u1": {"p", "m"}, "elsewhere": {"q"}, "u0": {"r"}}
    fresh = {"p": (1.0, 2.0, 0.0), "q": (0.0, 0.0, 0.0)}  # r has no pose read this period
    assert route_occupants(robot, owners, fresh, "site") == {"p": ["site", 1.0, 2.0]}


def test_a_departure_towards_a_pin_ahead_is_refused():
    _runner, traffic = _pinned_then(1.7, 1.02)
    assert traffic["refused_at_m"] is not None and traffic["waiting_for"] == ["a"]


# ---- the route cut: never into an occupied block (f) ---------------------------------------------

def _live(traffic, lengths=(0.5, 0.5, 0.5), convoy=None):
    clock = FakeClock()
    segs = [{"s_from": 0.0, "s_to": length} for length in lengths]
    live = NS(segments=segs, convoy=convoy, route_rev=1,
              progress=lambda i, s: sum(lengths[:i]) + s, traffic=None)
    if traffic is not None:
        live.traffic = {"waiting_for": [], "authority_end_m": 0.4, "refused_at_m": None, "front_d_m": 0.05,
                        "pose_stamp": clock(), "route_rev": 1, "peers": {"p": ["site", 1.0, 0.0]},
                        "occupied_ahead_m": None, **traffic}
    holds = lambda lv, k: (lv.traffic or {}).get("refused_at_m") is not None and \
        lv.traffic["refused_at_m"] < lv.progress(k, lv.segments[k]["s_to"]) + PAST_PLACE_M
    return NS(_clock=clock, traffic=NS(holds=holds)), live


def test_a_pin_at_the_lap_end_cuts_the_route_at_the_place_before_and_extends_once_clear():
    runner, live = _live({"occupied_ahead_m": 1.2})  # the last segment's unit is taken
    assert list(nav2._table_answer(runner, live)["peers"]) == ["p"]
    assert nav2._traffic_end_index(runner, live, 0) == 1
    live.traffic["occupied_ahead_m"] = None  # the pin left
    assert nav2._traffic_end_index(runner, live, 0) == 2


def test_an_occupied_unit_in_the_first_segment_sends_nothing():
    runner, live = _live({"occupied_ahead_m": 0.3})
    assert nav2._traffic_end_index(runner, live, 0) is None


@pytest.mark.parametrize("change", ["no_answer", "stale", "other_revision", "convoy", "no_front"])
def test_without_a_fresh_answer_for_this_revision_no_peer_is_left_to_the_table(change):
    runner, live = _live({"occupied_ahead_m": 1.2}, convoy="lead" if change == "convoy" else None)
    if change == "no_answer":
        live.traffic = None
    elif change == "stale":
        runner._clock.advance(5.0)
    elif change == "other_revision":
        live.route_rev = 2
    elif change == "no_front":
        live.traffic["front_d_m"] = None
    assert nav2._table_answer(runner, live) is None
    assert nav2._traffic_end_index(runner, live, 0) == 2  # as before: the console checks every standing peer


def test_two_trips_naming_each_other_only_the_approved_one_has_a_route():
    approved, a = _live({"peers": {"b": ["site", 0.0, 0.0]}})
    refused, b = _live({"peers": {"a": ["site", 1.0, 0.0]}, "refused_at_m": 0.0, "waiting_for": ["a"]})
    assert nav2._traffic_end_index(approved, a, 0) == 2
    assert nav2._traffic_end_index(refused, b, 0) is None


# ---- the console: which standing peers stay a pre-dispatch refusal (b) ----------------------------

PTS = [{"x": 0.4, "y": 0.0, "kind": "pass"}, {"x": 0.8, "y": 0.0, "kind": "stop", "yaw": 0.0}]
COUNTED = {"rosy_45": ["site", 0.75, 0.0]}  # where the block table saw the peer this period


def _console(peer_state=None):
    mover, peer = RouteFakeRobot("rosy_42"), RouteFakeRobot("rosy_45")
    mover._state.update(pose={"x": 0.0, "y": 0.0, "yaw": 0.0}, navigation="IDLE")
    peer._state.update(pose={"x": 0.75, "y": 0.0, "yaw": 0.0}, navigation="IDLE", **(peer_state or {}))
    console = FleetConsole([RobotEndpoint("rosy_42", "http://127.0.0.1:8080", "t"),
                            RobotEndpoint("rosy_45", "http://127.0.0.1:8081", "t")],
                           [mover, peer], clock=FakeClock(), goal_lease_ttl_s=4.0)
    site = {"rosy_42": ("site", 0.0, 0.0, 0.0), "rosy_45": ("site", 0.75, 0.0, 0.0)}
    console.set_site_pose_providers(mover=site.get)
    console.site = site
    return console, mover


def test_a_standing_peer_on_the_sent_route_waits_unless_the_table_counted_it():
    console, mover = _console()
    reply = run(console.route("rosy_42", PTS, lease_source="trip"))
    assert reply["reason"] == "YIELDING" and reply["waiting_on"] == ["rosy_45"] and mover.routes == []
    assert reply["stage"] == "pre_dispatch_peer_check" and reply["dispatch_attempted"] is False
    reply = run(console.route("rosy_42", PTS, lease_source="trip", table_peers=COUNTED))
    assert reply["accepted"] is True and len(mover.routes) == 1, {k: reply.get(k) for k in ("reason", "stage", "waiting_on")}


def test_a_counted_peer_that_moved_since_the_table_saw_it_still_waits():
    console, mover = _console()
    console.site["rosy_45"] = ("site", 0.62, 0.0, 0.0)  # 0.13 m from where the table counted it
    reply = run(console.route("rosy_42", PTS, lease_source="trip", table_peers=COUNTED))
    assert reply["reason"] == "YIELDING" and mover.routes == []
    reply = run(console.route("rosy_42", PTS, lease_source="trip", table_peers={"rosy_45": ["other", 0.75, 0.0]}))
    assert reply["reason"] == "YIELDING" and mover.routes == []


def test_table_peers_count_only_for_a_trip_route():
    console, mover = _console()
    reply = run(console.route("rosy_42", PTS, table_peers=COUNTED))
    assert reply["reason"] == "YIELDING" and mover.routes == []


@pytest.mark.parametrize("peer_state, reason", [
    ({"localization": {"state": "UNKNOWN", "pose_frame": "odom"}}, "LOCALIZATION_UNTRUSTED"),
    ({"map_id": "other"}, None),
])
def test_untrusted_or_other_frame_peers_still_refuse_with_table_peers(peer_state, reason):
    console, mover = _console(peer_state)
    reply = run(console.route("rosy_42", PTS, lease_source="trip", table_peers=COUNTED))
    assert reply["accepted"] is False and mover.routes == [] and reply["waiting_on"] == ["rosy_45"]
    if reason:
        assert reply["reason"] == reason


def test_an_offline_marker_peer_still_refuses_with_table_peers():
    console, mover = _console()
    console._site_marker_clearance = NS(offline={"rosy_45": 0.0}, evidence=lambda rid: None, link=lambda row: None,
                                         clear=lambda *args: False)
    reply = run(console.route("rosy_42", PTS, lease_source="trip", table_peers=COUNTED))
    assert reply["accepted"] is False and mover.routes == []
