"""D-507 addendum (2026-10-08): site-map bend places and the Fleet 'bend' instruction."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from fleet.routing.graph import build_graph
from fleet.server.console_view import TripCaps, trip_caps
from fleet.server.trip_ports import bend_geometry, straight_approach
from fleet.site_map import SiteMap, SitePlace, from_lane_graph
from test_trip_caps import _caps
from test_trip_runner import LANE, LANE_GRAPH, _arc, _plan, _setup, _ticks, run

BEND_CAPS = TripCaps("pinky_pro", frozenset({"lane"}), 0.2, junction_turn=True, junction_pivot=True,
                     lane_bend=True)
#: 260919 SW bend (lane_graph ``west`` centre lines): vertex, drawn direction SW -> NW
#: (down the spoke, then west), r 0.064 m. Driven NW -> SW it is +63.6 deg from heading 0.
SW_BEND = dict(id="B_SW", name="SW bend", kind="bend", x=-0.6924, y=-0.5091,
               yaw=math.radians(63.58 - 180), exit_yaw=math.pi, radius_m=0.064)


def _bend_map(*bends) -> SiteMap:
    base = from_lane_graph(LANE_GRAPH)
    return SiteMap(map_id=base.map_id, places=[*base.places, *(SitePlace(**b) for b in bends)],
                   edges=base.edges)


def _trip(site_map, caps=BEND_CAPS, ahead=0.4, before=None):
    """Start NW -> SE on west:rev with the SW bend's arc start ``ahead`` m in front; tick once
    (``before(runner)`` runs ahead of that tick)."""
    runner, store, ports = _setup(site_map, caps=caps)
    arc = _arc(store, "west:rev")
    s_start = bend_geometry(SitePlace(**SW_BEND), arc)[0]
    _plan(store, ports, arc.id, s_start - ahead, "SE")
    run(runner.start("p1", "bob"))
    ports.at(arc, s_start - ahead)
    if before is not None:
        before(runner)
    _ticks(runner, ports)
    return runner, store, ports, arc, s_start


# ---- the site map ----------------------------------------------------------------------------

def test_bend_place_needs_its_geometry_and_only_bends_carry_it():
    assert SitePlace(**SW_BEND).radius_m == 0.064
    for missing in ("yaw", "exit_yaw", "radius_m"):
        with pytest.raises(ValidationError):
            SitePlace(**{k: v for k, v in SW_BEND.items() if k != missing})
    for bad in ({"radius_m": 0.0}, {"radius_m": 0.51}, {"exit_yaw": SW_BEND["yaw"] + 0.1},  # 5.7 deg
                {"exit_yaw": SW_BEND["yaw"] + math.radians(95)}):
        with pytest.raises(ValidationError):
            SitePlace(**{**SW_BEND, **bad})
    with pytest.raises(ValidationError):
        SitePlace(id="J", name="J", x=0, y=0, kind="junction", radius_m=0.1)


def test_maps_without_bends_keep_their_stored_body():
    body = from_lane_graph(LANE_GRAPH).body()
    assert all("exit_yaw" not in p and "radius_m" not in p for p in body["places"])
    bend = next(p for p in _bend_map(SW_BEND).body()["places"] if p["kind"] == "bend")
    assert bend["exit_yaw"] == pytest.approx(math.pi) and bend["radius_m"] == 0.064


def test_bend_geometry_reads_the_travel_direction():
    graph = build_graph(_bend_map(SW_BEND))
    place = SitePlace(**SW_BEND)
    s_start, s_end, turn, radius = bend_geometry(place, graph.arcs["west:rev"])
    assert turn == pytest.approx(63.58, abs=0.1) and radius == 0.064
    assert s_end - s_start == pytest.approx(2 * 0.064 * math.tan(math.radians(63.58) / 2), abs=0.02)
    x, y, _ = graph.arcs["west:rev"].point_at(s_start)
    assert (x, y) == pytest.approx((-0.732, -0.509), abs=0.01)
    assert bend_geometry(place, graph.arcs["west:fwd"])[2] == pytest.approx(-63.58, abs=0.1)
    assert bend_geometry(place, graph.arcs["east:fwd"]) is None


def test_caps_read_lane_bend():
    assert trip_caps(_caps()).lane_bend is False
    assert trip_caps(_caps(lane_bend=True)).lane_bend is True
    assert trip_caps(_caps(lane_bend="true")).lane_bend is False


# ---- the trip loop -------------------------------------------------------------------------

def test_bend_instruction_goes_out_only_on_the_bend_stretch():
    runner, store, ports, arc, s_start = _trip(_bend_map(SW_BEND))
    assert ports.sent == [("bend", "B_SW", None)]
    assert ports.turns == [pytest.approx(63.6, abs=0.1)]
    fields = ports.expects[0]
    assert fields["map_id"] == "site" and fields["bend_radius_m"] == 0.064
    assert fields["bend_in_m"] == pytest.approx(0.4, abs=0.001)          # along the lane
    assert fields["bend_tol_m"] == pytest.approx(0.12, abs=0.001)         # the junction tol rule
    assert set(fields) == {"map_id", "bend_in_m", "bend_tol_m", "bend_radius_m"}
    ports.core.phase("bending")
    ports.at(arc, s_start + 0.02)
    _ticks(runner, ports, 3)
    assert ports.sent == [("bend", "B_SW", None)]                         # nothing during the pass
    ports.core.done()                                                     # CORE idle, same seq
    ports.at(arc, s_start + 0.12)
    _ticks(runner, ports)
    assert ports.sent[1][1] == "SW" and ports.sent[1][0] != "bend"        # then the next place


def test_a_bend_core_ended_on_the_next_junction_counts_done_and_the_place_goes_out():
    """Lap SIM D (rec_4): CORE ended the pass on the SW sighting and waits there (same seq) 6 mm
    before the arc end on Fleet's map; Fleet must count the bend done and send the SW turn."""
    runner, store, ports, arc, s_start = _trip(_bend_map(SW_BEND))
    ports.core.phase("bending")
    ports.at(arc, s_start + 0.02)
    _ticks(runner, ports)
    ports.core.j = None
    ports.core.see_junction()                                             # CORE 'waiting', same seq
    assert ports.core.status()["state"] == "waiting" and ports.core.status()["seq"] == 1
    _ticks(runner, ports)
    assert ports.sent[1][:2] == ("right", "SW") and ports.expects[1]["expect_in_m"] > 0
    assert runner.running()["state"] == "running"


def test_an_armed_bend_holds_the_next_place_back():
    runner, store, ports, arc, s_start = _trip(_bend_map(SW_BEND), ahead=0.15)  # SW within 0.6 m
    _ticks(runner, ports, 3)
    assert ports.sent == [("bend", "B_SW", None)]


@pytest.mark.parametrize("site_map, caps", [(None, BEND_CAPS), ("bend", LANE)])
def test_no_bend_place_or_no_lane_bend_robot_sends_no_bend(site_map, caps):
    runner, store, ports = _setup(_bend_map(SW_BEND) if site_map else None, caps=caps)
    arc = _arc(store, "west:rev")
    s = bend_geometry(SitePlace(**SW_BEND), arc)[0] - 0.05
    _plan(store, ports, arc.id, s, "SE")
    run(runner.start("p1", "bob"))
    ports.at(arc, s)
    _ticks(runner, ports, 3)
    assert ports.sent and all(action != "bend" for action, *_ in ports.sent)


def test_core_unresolved_bend_stops_the_trip():
    runner, store, ports, arc, s_start = _trip(_bend_map(SW_BEND))
    ports.core.phase("unresolved")
    _ticks(runner, ports)
    view = runner.view("p1")
    assert (view["state"], view["reason"]) == ("stopped", "junction")


def test_bend_waits_until_the_lane_before_it_is_straight():
    """bend_in_m is odom travel in CORE: not sent while the W->S corner is still ahead of the arc."""
    graph = build_graph(_bend_map(SW_BEND))
    arc = graph.arcs["west:rev"]
    s_start = bend_geometry(SitePlace(**SW_BEND), arc)[0]
    assert straight_approach(arc, s_start - 0.40, s_start)
    assert not straight_approach(arc, s_start - 0.58, s_start)            # inside the corner
    runner, store, ports, arc, s_start = _trip(_bend_map(SW_BEND), ahead=0.58)
    assert ports.sent == []
    ports.at(arc, s_start - 0.40)
    _ticks(runner, ports)
    assert ports.sent == [("bend", "B_SW", None)]


# ---- holds gate the bend (a held robot never gets an instruction that restarts motion) ----

def _hold(runner, hold):
    runner._live["rosy_60"].view["hold"] = hold


def test_a_held_trip_sends_no_bend_then_sends_it_once_on_release():
    runner, store, ports, arc, s_start = _trip(
        _bend_map(SW_BEND), before=lambda r: _hold(r, {"reason": "replan", "plan": None}))
    _ticks(runner, ports, 3)
    assert ports.sent == []
    _hold(runner, None)
    _ticks(runner, ports, 3)
    assert ports.sent == [("bend", "B_SW", None)]
    ports.core.phase("bending")
    ports.at(arc, s_start + 0.02)
    _ticks(runner, ports, 2)
    ports.core.done()
    _ticks(runner, ports, 3)
    assert [a for a, *_ in ports.sent].count("bend") == 1                 # once per lap


def test_a_held_trip_near_its_place_gets_the_stop_not_the_bend():
    runner, store, ports, arc, s_start = _trip(
        _bend_map(SW_BEND), ahead=0.15, before=lambda r: _hold(r, {"reason": "replan", "plan": None}))
    _ticks(runner, ports, 2)
    assert [a for a, *_ in ports.sent] == ["stop"]


def test_traffic_hold_back_sends_no_bend_until_it_clears():
    held = [True]

    def hold_back(runner):
        runner.traffic.holds = lambda live, index: held[0]
    runner, store, ports, arc, s_start = _trip(_bend_map(SW_BEND), before=hold_back)
    _ticks(runner, ports, 3)
    assert ports.sent == []
    held[0] = False
    _ticks(runner, ports, 3)
    assert ports.sent == [("bend", "B_SW", None)]


def test_no_bend_while_core_executes_another_instruction():
    runner, store, ports, arc, s_start = _trip(_bend_map(SW_BEND), ahead=0.58)  # corner: nothing yet
    ports.core.send("straight", "NW", None, 15, None)
    ports.core.phase("executing")
    ports.at(arc, s_start - 0.40)
    _ticks(runner, ports, 3)
    assert ports.sent == []
    ports.core.done()
    _ticks(runner, ports)
    assert ports.sent == [("bend", "B_SW", None)]


def test_a_trip_closed_mid_step_sends_no_bend(monkeypatch):
    from fleet.server import trip_runner

    def closing(live, *args):
        live.view["state"] = "canceled"
        return real(live, *args)
    real = trip_runner.bend_fields
    monkeypatch.setattr(trip_runner, "bend_fields", closing)
    runner, store, ports, arc, s_start = _trip(_bend_map(SW_BEND))
    assert ports.sent == []
