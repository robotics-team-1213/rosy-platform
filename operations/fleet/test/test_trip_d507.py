"""D-507 Fleet side: junction expectation fields (2), site floor map binding (9), unexpected junction (3)."""

from __future__ import annotations

import dataclasses
import json

import httpx

from fleet.routing.cost import STOP
from fleet.server.console_view import TripCaps, trip_caps
from fleet.site_map import SiteMap
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import HttpRobotClient
from test_trip_caps import _caps
from test_trip_runner import LANE, _arc, _free_map, _map, _plan, _setup, _ticks, run

PIVOT = TripCaps("pinky_pro", frozenset({"lane"}), 0.2, junction_turn=True, junction_pivot=True)


def _straight_map():
    """A -> B -> C straight through B."""
    return _map(("A", 0, 0), ("B", 1, 0), ("C", 2, 0),
                edges=[("ab", "A", "B", [[0, 0], [1, 0]], "lane"), ("bc", "B", "C", [[1, 0], [2, 0]], "lane")])


def _sent_at(site_map, caps, s, to="C"):
    """Start A -> ``to`` and tick once with the robot ``s`` along ``ab``; the junction sends made."""
    runner, store, ports = _setup(site_map, caps=caps)
    _plan(store, ports, "ab:fwd", 0.1, to)
    run(runner.start("p1", "bob"))
    ports.at(_arc(store, "ab:fwd"), s)
    _ticks(runner, ports)
    return ports


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
    # pose: a sighting (0 m dead-reckoned) 0.1 s old at 0.2 m/s -> 0.02 + ENDPOINT_TOL_M 0.05
    assert ports.expects == [{"map_id": "site", "expect_in_m": 0.5, "expect_tol_m": 0.07,
                              "pivot_past_line_m": 0.1}]  # outgoing lane 0.2 m wide


def test_straight_carries_the_expectation_without_a_pivot():
    ports = _sent_at(_straight_map(), PIVOT, 0.6)
    assert ports.sent[0][0] == "straight"
    assert ports.expects == [{"map_id": "site", "expect_in_m": 0.4, "expect_tol_m": 0.07}]


def test_the_last_stop_carries_the_expectation_without_a_pivot():
    ports = _sent_at(_straight_map(), PIVOT, 0.7, to="B")
    assert ports.sent[0][0] == STOP
    assert ports.expects == [{"map_id": "site", "expect_in_m": 0.3, "expect_tol_m": 0.07}]


def test_tolerance_grows_with_dead_reckoning_and_is_capped():
    runner, store, ports = _setup(_free_map("lane"), caps=PIVOT)
    _plan(store, ports, "ab:fwd", 0.1, "C")
    run(runner.start("p1", "bob"))
    ports.at(_arc(store, "ab:fwd"), 0.5)
    ports.pose = dataclasses.replace(ports.pose, source="bridged", dead_reckon_m=1.0)  # + 0.05
    _ticks(runner, ports)
    assert ports.expects[-1]["expect_tol_m"] == 0.12
    runner, store, ports = _setup(_free_map("lane"), caps=PIVOT)
    _plan(store, ports, "ab:fwd", 0.1, "C")
    run(runner.start("p1", "bob"))
    ports.at(_arc(store, "ab:fwd"), 0.5)
    ports.pose = dataclasses.replace(ports.pose, source="bridged", dead_reckon_m=9.0)
    _ticks(runner, ports)
    assert ports.expects[-1]["expect_tol_m"] == 0.30


def test_pivot_is_capped_at_0_30():
    wide = _free_map("lane").model_dump()
    for edge in wide["edges"]:
        edge["width_m"] = 0.8
    ports = _sent_at(SiteMap.model_validate(wide), PIVOT, 0.5)
    assert ports.expects[0]["pivot_past_line_m"] == 0.30


def test_a_place_outside_the_expectation_range_sends_only_the_map_id():
    ports = _sent_at(_free_map("lane"), PIVOT, 1.0)   # on the place: expect_in_m 0 is out of (0, 2]
    assert ports.sent[0][0] == "left" and ports.expects == [{"map_id": "site"}]


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
