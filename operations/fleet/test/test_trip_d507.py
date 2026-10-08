"""D-507 Fleet side: junction expectation fields (2), site floor map binding (9), unexpected junction (3)."""

from __future__ import annotations

import dataclasses
import json
import math

import httpx
import pytest

from fleet.routing.cost import STOP
from fleet.server.console_view import TripCaps, trip_caps
from fleet.routing.graph import build_graph
from fleet.site_map import from_lane_graph
from fleet.server.trip_ports import HttpLaneJunction, TripConfig, TripError, line_past
from fleet.site_map import SiteMap
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import HttpRobotClient, RobotApiError
from test_trip_caps import _caps
from test_trip_runner import LANE, LANE_GRAPH, _activate_again, _arc, _free_map, _map, _plan, _setup, _ticks, run
import fleet.server.trip_ports as trip_ports

PIVOT = TripCaps("pinky_pro", frozenset({"lane"}), 0.2, junction_turn=True, junction_pivot=True)


def test_west_edge_bend_candidate_needs_a_fresh_aligned_pose():
    arc = build_graph(from_lane_graph(LANE_GRAPH)).arcs["west:rev"]
    _, s, _ = arc.project(-0.951, -0.491)
    pose = {"x": -0.951, "y": -0.491, "yaw": -0.068, "age_s": 0.1, "dead_reckon_m": 0.0}
    candidate = trip_ports.bend_candidate(arc, s, pose)
    assert candidate["arc_id"] == "west:rev"
    assert 0.20 < candidate["bend_in_m"] < 0.30
    assert 55 < candidate["heading_change_deg"] < 70
    for rejected in ({"age_s": 0.4}, {"dead_reckon_m": 0.1}, {"yaw": 1.0},
                     {"y": -0.40}):
        assert trip_ports.bend_candidate(arc, s, {**pose, **rejected}) is None
    _, straight_s, _ = arc.project(-1.15, -0.511)
    assert trip_ports.bend_candidate(arc, straight_s,
                                     {**pose, "x": -1.15, "y": -0.511, "yaw": 0.0}) is None


def test_live_trip_exposes_only_a_map_bound_bend_diagnostic():
    runner, store, ports = _setup(caps=PIVOT)
    arc = _arc(store, "west:rev")
    _plan(store, ports, arc.id, 2.0, "SE")
    run(runner.start("p1", "bob"))
    ports.at(arc, arc.project(-0.951, -0.491)[1])
    ports.pose = dataclasses.replace(ports.pose, x=-0.951, y=-0.491, yaw=-0.068,
                                     age_s=0.1, dead_reckon_m=0.0)
    _ticks(runner, ports)
    view = runner.view("p1")
    assert view["detail"]["bend_candidate"]["map_id"] == "site"
    assert view["detail"]["bend_candidate"]["arc_id"] == arc.id
    assert view["detail"]["bend_candidate"]["map_version"] == view["map_version"]
    assert ports.sent == []  # the cue is not a robot command
    ports.pose = dataclasses.replace(ports.pose, age_s=0.304)
    _ticks(runner, ports)
    assert "bend_candidate" not in runner.view("p1")["detail"]
    ports.pose = dataclasses.replace(ports.pose, age_s=0.1, map_id="other")
    _ticks(runner, ports)
    assert "bend_candidate" not in runner.view("p1")["detail"]
    ports.pose = dataclasses.replace(ports.pose, map_id=None)
    _activate_again(store)
    _ticks(runner, ports)
    assert "bend_candidate" not in runner.view("p1")["detail"]
    run(runner.cancel("p1", "bob"))
    assert "bend_candidate" not in runner.view("p1")["detail"]


def _straight_map():
    """A -> B -> C straight through B."""
    return _map(("A", 0, 0), ("B", 1, 0), ("C", 2, 0),
                edges=[("ab", "A", "B", [[0, 0], [1, 0]], "lane"), ("bc", "B", "C", [[1, 0], [2, 0]], "lane")])


def _sent_at(site_map, caps, s, to="C", pose=None, **config):
    """Start A -> ``to`` and tick once with the robot ``s`` along ``ab``; the junction sends made."""
    runner, store, ports = _setup(site_map, caps=caps, **config)
    _plan(store, ports, "ab:fwd", 0.1, to)
    run(runner.start("p1", "bob"))
    ports.at(_arc(store, "ab:fwd"), s)
    if pose:
        ports.pose = dataclasses.replace(ports.pose, **pose)
    _ticks(runner, ports)
    return ports


def _tol(pose=None, **config):
    return _sent_at(_free_map("lane"), PIVOT, 0.5, pose=pose, **config).expects[0]["expect_tol_m"]


# ---- 2: junction instruction fields --------------------------------------------------------

def test_caps_read_junction_pivot_and_site_floor_map_id():
    assert trip_caps(_caps()).junction_pivot is False
    assert trip_caps(_caps(junction_pivot=True)).junction_pivot is True
    assert trip_caps(_caps(junction_pivot="true")).junction_pivot is False
    assert trip_caps(_caps()).site_floor_map_id is None              # absent: older CORE
    assert trip_caps(_caps(site_floor_map_id=None)).site_floor_map_id is None
    assert trip_caps(_caps(site_floor_map_id="hall_a")).site_floor_map_id == "hall_a"


def test_fields_go_only_to_a_junction_pivot_robot():
    assert _sent_at(_free_map("lane"), LANE, 0.5).expects == [None]
    ports = _sent_at(_free_map("lane"), PIVOT, 0.5)
    assert ports.sent[0][0] == "left"
    # a sighting 0.1 s old at 0.2 m/s: 0.2 x (0.1 + ~0 measured + 0.2 allowance) + 0.05 = 0.11 -> floor 0.12
    # the corner's outer line is the far edge of the 0.2 m outgoing lane, 0.1 m past B
    assert ports.expects == [{"map_id": "site", "pivot_past_line_m": -0.1,
                              "expect_in_m": 0.5, "expect_tol_m": 0.12}]


def test_straight_through_has_no_line_so_half_width_and_no_window():
    ports = _sent_at(_straight_map(), PIVOT, 0.6)
    assert ports.sent[0][0] == "straight"
    assert ports.expects == [{"map_id": "site", "pivot_past_line_m": 0.1}]


def test_the_last_stop_carries_the_expectation_without_a_pivot():
    ports = _sent_at(_straight_map(), PIVOT, 0.7, to="B")
    assert ports.sent[0][0] == STOP
    assert ports.expects == [{"map_id": "site", "expect_in_m": 0.3, "expect_tol_m": 0.12}]


def test_tolerance_adds_drift_and_the_measured_latency_and_is_capped():
    low = {"expect_tol_min_m": 0.01}
    # 0.2 m/s x (age 0.1 + read-to-send ~0 + SEND_ALLOWANCE_S 0.2) + ENDPOINT_TOL_M 0.05
    assert _tol(**low) == pytest.approx(0.11, abs=0.002)
    assert _tol({"age_s": 0.6}, **low) == pytest.approx(0.21, abs=0.002)        # older pose: + 0.1
    assert _tol({"source": "bridged", "dead_reckon_m": 1.0}, **low) == pytest.approx(0.16, abs=0.002)
    assert _tol({"source": "bridged", "dead_reckon_m": 9.0}, **low) == 0.30     # capped


def test_tolerance_counts_the_time_between_the_pose_read_and_the_send(monkeypatch):
    import fleet.server.trip_ports as trip_ports
    clock = iter([100.0, 100.5])  # read at 100.0 (live.see), send 0.5 s later
    monkeypatch.setattr(trip_ports, "_monotonic", lambda: next(clock, 100.5))
    # 0.2 x (0.1 + 0.5 + 0.2) + 0.05
    assert _tol(expect_tol_min_m=0.01) == pytest.approx(0.21, abs=1e-6)


def test_tolerance_is_floored_by_the_site_knob():
    assert _tol() == 0.12                                         # 0.11 computed, default knob 0.12
    assert _tol(expect_tol_min_m=0.2) == 0.2
    assert TripConfig.from_mapping({"expect_tol_min_m": 0.15}).expect_tol_min_m == 0.15
    with pytest.raises(ValueError):
        TripConfig(expect_tol_min_m=0.31)


def test_an_unknown_pose_error_sends_the_widest_window():
    low = {"expect_tol_min_m": 0.01}
    assert _tol({"age_s": None}, **low) == 0.30
    assert _tol({"dead_reckon_m": None}, **low) == 0.30


def test_pivot_is_capped_at_0_30():
    wide = _free_map("lane").model_dump()
    for edge in wide["edges"]:
        edge["width_m"] = 0.8
    ports = _sent_at(SiteMap.model_validate(wide), PIVOT, 0.5)
    assert ports.expects[0]["pivot_past_line_m"] == 0.30


def test_a_place_outside_the_expectation_range_sends_no_window():
    ports = _sent_at(_free_map("lane"), PIVOT, 1.0)   # on the place: expect_in_m 0 is out of (0, 2]
    # the far line is there (-0.1) but without a window a negative pivot goes unchecked: stop_point
    assert ports.sent[0][0] == "left" and ports.expects == [{"map_id": "site"}]


def test_a_heading_off_the_lane_sends_the_distance_along_the_heading():
    ports = _sent_at(_free_map("lane"), PIVOT, 0.5, pose={"yaw": math.radians(10)})
    assert ports.expects[0]["expect_in_m"] == round(0.5 * math.cos(math.radians(10)), 3)


def _ring_map():
    """A quarter circle (radius 0.25) from A into B, then straight on to C: the 260919 ring leg."""
    arc = [[round(0.25 * math.sin(t), 4), round(0.25 - 0.25 * math.cos(t), 4)]
           for t in (math.radians(d) for d in range(0, 91, 10))]
    return _map(("A", 0, 0), ("B", 0.25, 0.25), ("C", 0.25, 1.0),
                edges=[("ab", "A", "B", arc, "lane"), ("bc", "B", "C", [[0.25, 0.25], [0.25, 1.0]], "lane")])


def test_a_ring_arc_sends_no_window():
    ports = _sent_at(_ring_map(), PIVOT, 0.05)
    assert ports.sent[0][0] == "straight"
    assert ports.expects == [{"map_id": "site", "pivot_past_line_m": 0.1}]


# 2026-10-08 D-507 SIM findings 1-2 (docs/validation/d507-lane-trip-sim-2026-10-08): the SIM
# place pose (-0.655, -0.432, 64 deg) before the 260919 SW spoke. The ring's outer line is broken
# at the spoke mouth, so the keeper measured the inner line, 0.402 m ahead; SW is 0.296 m ahead.
SW_POSE = {"x": -0.655, "y": -0.432, "yaw": math.radians(64)}


def _sw_spoke_sends(pose=SW_POSE, back=0.3, to="SE"):
    runner, store, ports = _setup(caps=PIVOT)  # the 260919 lane graph
    arc = _arc(store, "west:rev")
    _plan(store, ports, "west:rev", arc.length_m - 0.5, to)
    run(runner.start("p1", "bob"))
    ports.at(arc, arc.length_m - back)
    if pose:
        ports.pose = dataclasses.replace(ports.pose, **pose)
    _ticks(runner, ports)
    return ports


def test_260919_sw_spoke_pivots_on_the_place_before_the_far_line():
    ports = _sw_spoke_sends()
    sent = ports.expects[0]
    assert ports.sent[0][0] in ("left", "right") and sent["expect_in_m"] == pytest.approx(0.296, abs=0.002)
    assert sent["pivot_past_line_m"] == pytest.approx(-0.10, abs=0.01)    # place 0.296, line 0.402
    expected_line = sent["expect_in_m"] - sent["pivot_past_line_m"]       # CORE's window point
    assert expected_line == pytest.approx(0.402, abs=0.01)
    assert abs(expected_line - 0.402) < sent["expect_tol_m"]              # SIM measured: inside


def test_260919_sw_spoke_without_a_window_sends_no_negative_pivot():
    ports = _sw_spoke_sends(pose=None, back=0.0)          # on the place: expect_in_m 0, no window
    assert ports.expects == [{"map_id": "site"}]          # CORE turns at its stop point


def test_without_a_window_and_without_a_line_the_old_half_width_stays():
    ports = _sent_at(_ring_map(), PIVOT, 0.05)            # a ring bend: no window, straight on
    assert ports.expects == [{"map_id": "site", "pivot_past_line_m": 0.1}]


def test_the_window_pivot_follows_the_robot_heading_not_the_lane():
    """SW: the robot heads 64 deg, the lane's last stretch 53.8 deg (about 10 deg apart)."""
    ports = _sw_spoke_sends()
    graph = build_graph(from_lane_graph(LANE_GRAPH))
    x, y, lane_heading = graph.arcs["west:rev"].point_at(graph.arcs["west:rev"].length_m)
    robot, lane = line_past(graph, x, y, SW_POSE["yaw"]), line_past(graph, x, y, lane_heading)
    assert abs(robot - lane) >= 0.005                     # the two choices differ here
    assert ports.expects[0]["pivot_past_line_m"] == -robot


def test_line_past_is_the_edge_of_the_lanes_union():
    graph = build_graph(_free_map("lane"))
    assert line_past(graph, 1.0, 0.0, 0.0) == pytest.approx(0.1, abs=0.001)   # the corner's outer line
    assert line_past(graph, 0.5, 0.0, 0.0) is None                            # 0.6 m on: past 0.30
    assert line_past(graph, 0.5, 0.5, 0.0) is None                            # off the lanes
    assert line_past(build_graph(_straight_map()), 1.0, 0.0, 0.0) is None     # straight through


def test_a_free_arc_is_not_paint():
    """A free arc on through B neither breaks the corner's outer line nor carries one."""
    lane = _free_map("lane")
    body = lane.model_dump(by_alias=True)
    body["places"].append({"id": "D", "name": "D", "x": 1.6, "y": 0.0, "kind": "junction"})
    body["edges"].append({"id": "bd", "from": "B", "to": "D", "polyline": [[1, 0], [1.6, 0]], "width_m": 0.2,
                          "speed_cap_mps": 0.2, "drive_mode": "free"})
    graph = build_graph(SiteMap.model_validate(body))
    assert line_past(graph, 1.0, 0.0, 0.0) == pytest.approx(0.1, abs=0.001)
    assert line_past(graph, 1.3, 0.0, 0.0) is None                            # on the free arc only


@pytest.mark.parametrize("width, past", [(0.6, 0.3), (0.598, 0.299), (0.604, None), (0.62, None)])
def test_line_past_cuts_off_past_0_30(width, past):
    body = _free_map("lane").model_dump(by_alias=True)
    for edge in body["edges"]:
        edge["width_m"] = width
    assert line_past(build_graph(SiteMap.model_validate(body)), 1.0, 0.0, 0.0) == past


def _bent_map(bend_deg, straight=0.7, bent=0.3):
    """A ``straight`` run, then ``bent`` m turned by ``bend_deg`` into B, then a left corner to C."""
    c, s = math.cos(math.radians(bend_deg)), math.sin(math.radians(bend_deg))
    b = (round(straight + bent * c, 4), round(bent * s, 4))
    end = (round(b[0] - s, 4), round(b[1] + c, 4))
    return _map(("A", 0, 0), ("B", *b), ("C", *end),
                edges=[("ab", "A", "B", [[0, 0], [straight, 0], list(b)], "lane"),
                       ("bc", "B", "C", [list(b), list(end)], "lane")])


def test_a_bend_widens_the_window_by_how_far_the_lane_runs_beside_the_heading():
    lateral = 0.5 * math.sin(math.radians(10))                  # 0.087 m at B
    tol = _sent_at(_bent_map(10.0, straight=0.5, bent=0.5), PIVOT, 0.45).expects[0]["expect_tol_m"]
    assert tol >= 0.12 + lateral - 0.001 and tol == pytest.approx(0.12 + lateral, abs=0.002)
    assert _sent_at(_free_map("lane"), PIVOT, 0.5).expects[0]["expect_tol_m"] == 0.12   # a straight lane adds 0


def test_a_bend_of_15_degrees_keeps_the_window_and_more_drops_it():
    within = _sent_at(_bent_map(15.0), PIVOT, 0.5).expects[0]
    assert within["expect_in_m"] == round(0.2 + 0.3 * math.cos(math.radians(15)), 3)
    beyond = _sent_at(_bent_map(16.0), PIVOT, 0.5).expects[0]
    assert "expect_in_m" not in beyond and "expect_tol_m" not in beyond and beyond["map_id"] == "site"


def test_a_changed_map_version_sends_no_fields_and_says_so(caplog):
    runner, store, ports = _setup(_free_map("lane"), caps=PIVOT)
    _plan(store, ports, "ab:fwd", 0.1, "C")
    run(runner.start("p1", "bob"))
    _activate_again(store)
    ports.at(_arc(store, "ab:fwd"), 0.5)
    _ticks(runner, ports)
    assert ports.sent and ports.expects[-1] is None
    assert runner.view("p1")["detail"]["junction_fields_dropped"] == "map_version"
    assert "junction fields not sent" in caplog.text


def test_odom_stale_is_retried_on_the_next_tick():
    runner, store, ports = _setup(_free_map("lane"), caps=PIVOT)
    _plan(store, ports, "ab:fwd", 0.1, "C")
    run(runner.start("p1", "bob"))
    ports.at(_arc(store, "ab:fwd"), 0.5)
    ports.junction_error = RobotApiError("rosy_60", 409, "JUNCTION_ODOM_STALE", "no fresh odom")
    _ticks(runner, ports)
    view = runner.view("p1")
    assert view["state"] == "running" and ports.sent == [] and runner._live.sent is None
    assert view["detail"]["junction_retry"] == "JUNCTION_ODOM_STALE"
    _ticks(runner, ports)                                   # still stale: tried again, still running
    assert runner.running() is not None and ports.sent == []
    ports.junction_error = None
    _ticks(runner, ports)
    assert ports.sent[-1][0] == "left" and ports.expects[-1]["map_id"] == "site"
    assert runner._live.sent["action"] == "left" and "junction_retry" not in runner.view("p1")["detail"]


def test_http_client_puts_the_fields_in_the_junction_body():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"accepted": True, "junction_seq": 1, "state": "armed"})

    async def go():
        async with httpx.AsyncClient(base_url="http://robot", transport=httpx.MockTransport(handler)) as http:
            client = HttpRobotClient(RobotEndpoint("one", "http://robot", "t"), http=http)
            await client.line_follow_junction("left", "B", stop_after_m=None, expires_s=15.0, turn_deg=90.0,
                                              expect={"map_id": "site", "expect_in_m": 0.5})

    run(go())
    assert seen["body"] == {"action": "left", "place_id": "B", "expires_s": 15.0, "turn_deg": 90.0,
                            "map_id": "site", "expect_in_m": 0.5}


# ---- 9: site floor map binding -------------------------------------------------------------

def _named(site_map, map_id):
    return SiteMap.model_validate({**site_map.model_dump(), "map_id": map_id})


def _start_code(site_map, caps):
    runner, store, ports = _setup(site_map, caps=caps)
    _plan(store, ports, "ab:fwd", 0.1, "C")
    try:
        return run(runner.start("p1", "bob"))["state"], None
    except TripError as err:
        return err.code, err.detail


def test_a_lane_trip_is_refused_when_the_site_floor_covers_another_map():
    code, detail = _start_code(_named(_free_map("lane"), "hall_a"),
                               dataclasses.replace(PIVOT, site_floor_map_id="hall_b"))
    assert code == "TRIP_SITE_FLOOR_MISMATCH"
    assert detail == {"site_floor_map_id": "hall_b", "map_id": "hall_a"}


def test_a_matching_or_absent_site_floor_starts():
    hall_a = _named(_free_map("lane"), "hall_a")
    assert _start_code(hall_a, dataclasses.replace(PIVOT, site_floor_map_id="hall_a"))[0] == "started"
    assert _start_code(hall_a, PIVOT)[0] == "started"   # absent key (older CORE): no check
    assert _start_code(hall_a, LANE)[0] == "started"


def test_a_free_trip_is_not_bound_to_the_site_floor():
    both = TripCaps("pinky_pro", frozenset({"lane", "free"}), 0.2, junction_turn=True, site_floor_map_id="hall_b")
    assert _start_code(_named(_free_map("free"), "hall_a"), both)[0] == "started"


# ---- 3: unexpected junction ----------------------------------------------------------------

def _running_at(s):
    runner, store, ports = _setup(_free_map("lane"), caps=PIVOT)
    _plan(store, ports, "ab:fwd", 0.1, "C")
    run(runner.start("p1", "bob"))
    ports.at(_arc(store, "ab:fwd"), s)
    _ticks(runner, ports)
    return runner, ports


def _core_shows(ports, state, reason=None):
    ports.core.j = {"action": None, "place_id": None, "seq": ports.core.seq, "state": state, "reason": reason}


def test_unexpected_stops_the_trip_at_once_with_the_pose_and_reason():
    runner, ports = _running_at(0.1)                      # 0.9 m before B: nothing sent yet
    _core_shows(ports, "unexpected", "junction_unexpected")
    _ticks(runner, ports)
    view = runner.view("p1")
    assert (view["state"], view["reason"]) == ("stopped", "junction_unexpected")
    assert view["detail"]["junction_state"] == "unexpected"
    assert view["detail"]["junction_reason"] == "junction_unexpected"
    assert view["pose"]["x"] is not None and ports.held == ["rosy_60"]


def test_unexpected_within_the_arm_distance_also_stops_at_once():
    runner, ports = _running_at(0.5)
    _core_shows(ports, "unexpected")
    _ticks(runner, ports)
    assert runner.view("p1")["reason"] == "junction_unexpected"


def test_waiting_beyond_the_arm_distance_stops_without_the_wait():
    runner, ports = _running_at(0.1)
    _core_shows(ports, "waiting")
    _ticks(runner, ports)                                  # 0.5 s, not junction_wait_s (10 s)
    view = runner.view("p1")
    assert (view["state"], view["reason"]) == ("stopped", "junction_unexpected")
    assert view["detail"]["junction_state"] == "waiting"


def test_waiting_within_the_arm_distance_is_answered_as_before():
    """Within 0.6 m the instruction goes out to the waiting CORE and the trip runs on
    (the 10 s timeout there: ``test_trip_runner.test_core_waiting_at_a_junction_stops_the_trip_after_the_timeout``)."""
    runner, ports = _running_at(0.1)
    ports.at(runner._live.arc(0), 0.5)
    _core_shows(ports, "waiting")
    _ticks(runner, ports)
    assert runner.running() is not None and ports.sent[-1][0] == "left"


def test_the_http_port_carries_the_line_follow_reason():
    class Client:
        async def state(self):
            return {"line_follow": {"reason": "junction_waiting", "junction": {"state": "waiting", "seq": 3}}}

    port = HttpLaneJunction(lambda: {"r": Client()})
    assert run(port.junction_state("r")) == {"state": "waiting", "seq": 3, "line_reason": "junction_waiting"}


def test_a_stale_lane_waiting_does_not_end_a_free_segment():
    """A lane segment into a free one: CORE's last lane ``waiting`` is not read on the free segment."""
    site_map = _map(("A", 0, 0), ("B", 1, 0), ("C", 1, 1),
                    edges=[("ab", "A", "B", [[0, 0], [1, 0]], "lane"), ("bc", "B", "C", [[1, 0], [1, 1]], "free")])
    caps = dataclasses.replace(PIVOT, modes=frozenset({"lane", "free"}))
    runner, store, ports = _setup(site_map, caps=caps)
    _plan(store, ports, "ab:fwd", 0.1, "C")
    run(runner.start("p1", "bob"))
    ports.at(_arc(store, "ab:fwd"), 0.95)
    _ticks(runner, ports)
    _core_shows(ports, "waiting")                          # left over at B
    ports.at(_arc(store, "bc:fwd"), 0.3)
    _ticks(runner, ports, 25)                               # 12.5 s, past junction_wait_s
    assert runner.running() is not None and runner.view("p1")["drive_mode"] == "free"


def test_the_site_floor_check_comes_before_trip_busy():
    runner, store, ports = _setup(_named(_free_map("lane"), "hall_a"), caps=PIVOT)
    _plan(store, ports, "ab:fwd", 0.1, "C")
    run(runner.start("p1", "bob"))
    ports.caps = {"rosy_60": dataclasses.replace(PIVOT, site_floor_map_id="hall_b")}
    _plan(store, ports, "ab:fwd", 0.1, "C", plan_id="p2")
    with pytest.raises(TripError) as err:
        run(runner.start("p2", "bob"))
    assert err.value.code == "TRIP_SITE_FLOOR_MISMATCH"
