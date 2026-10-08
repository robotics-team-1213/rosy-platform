"""D-520 Fleet side: ``exit_segment`` on the junction instruction (1) and the arc handshake (2)."""

from __future__ import annotations

import dataclasses

import pytest

from fleet.routing.execute import theta, turn_target
from fleet.server.console_view import trip_caps
from test_trip_caps import _caps
from test_trip_d507 import SW_POSE
from test_trip_runner import LANE, _arc, _plan, _setup, _ticks, run

ARC = dataclasses.replace(LANE, lane_arc=True)
RING_K = pytest.approx(1 / 0.2514, abs=0.01)


def _sw_entry(caps=ARC, to="NE"):
    """The 260919 SW spoke 0.3 m before SW, going round the ring to ``to``; one tick."""
    runner, store, ports = _setup(caps=caps)
    arc = _arc(store, "west:rev")
    _plan(store, ports, "west:rev", arc.length_m - 0.5, to)
    run(runner.start("p1", "bob"))
    ports.at(arc, arc.length_m - 0.3)
    ports.pose = dataclasses.replace(ports.pose, **SW_POSE)
    _ticks(runner, ports)
    return runner, store, ports


def test_caps_read_lane_arc():
    assert trip_caps(_caps()).lane_arc is False
    assert trip_caps(_caps(lane_arc=True)).lane_arc is True
    assert trip_caps(_caps(lane_arc="true")).lane_arc is False


def test_a_lane_arc_robot_gets_the_ring_segment_the_tangent_and_no_advance():
    runner, store, ports = _sw_entry()
    graph, segments = store.active()[2], runner.view("p1")["plan"]["segments"]
    assert ports.sent[0][:2] == ("right", "SW")
    assert ports.expects[0]["exit_segment"] == {"curvature_1pm": RING_K, "length_m": pytest.approx(0.3739, abs=6e-4),
                                                "outer_line_offset_m": 0.095, "end_place_id": "SE"}
    assert ports.turns[0] == round(theta(graph, segments, 0), 1)          # no TURN_OVERTURN_DEG
    assert ports.turns[0] != round(turn_target(graph, segments, 0), 1)
    assert ports.advances == [None]


def test_without_lane_arc_the_instruction_is_todays():
    runner, store, ports = _sw_entry(caps=LANE)
    graph, segments = store.active()[2], runner.view("p1")["plan"]["segments"]
    assert "exit_segment" not in ports.expects[0]
    assert ports.turns[0] == round(turn_target(graph, segments, 0), 1)    # tangent - 6 deg
    assert ports.advances == [0.10]


def _on_ring_s(caps=ARC, to="NE"):
    """On ``ring_s`` 0.2 m before SE (inside arm_distance_m), going on to ``to``; one tick."""
    runner, store, ports = _setup(caps=caps)
    ring = _arc(store, "ring_s:fwd")
    _plan(store, ports, "ring_s:fwd", 0.05, to)
    run(runner.start("p1", "bob"))
    ports.at(ring, ring.length_m - 0.2)
    _ticks(runner, ports)
    return runner, store, ports


def test_a_straight_onto_the_next_ring_lane_carries_its_segment():
    runner, store, ports = _on_ring_s()
    assert ports.sent[0][:2] == ("straight", "SE") and ports.turns == [None] and ports.advances == [None]
    assert ports.expects[0]["exit_segment"] == {"curvature_1pm": RING_K, "length_m": pytest.approx(0.4595, abs=6e-4),
                                                "outer_line_offset_m": 0.095, "end_place_id": "NE"}


def test_no_map_id_means_no_exit_segment():
    """A lane_arc robot without junction_pivot gets no map_id, so no exit_segment (CORE would 400)."""
    runner, store, ports = _on_ring_s(caps=dataclasses.replace(ARC, junction_pivot=False))
    assert ports.sent[0][:2] == ("straight", "SE") and ports.expects == [None]


# ---- 2: the arc handshake --------------------------------------------------------------------

def _with_arc(ports, arc=None):
    """CORE's ``line_follow.arc`` beside the junction state (``ports.arc``, set by the test)."""
    ports.arc, plain = arc, ports.junction_state

    async def junction_state(robot_id):
        state = await plain(robot_id)
        return None if state is None else {**state, "arc": ports.arc}
    ports.junction_state = junction_state
    return ports


def _arc_rec(seq, place, end, state="running", reason=None):
    return {"arc_seq": seq, "from_place_id": place, "end_place_id": end, "curvature_1pm": 3.978,
            "length_m": 0.37, "travelled_m": 0.0, "state": state, "reason": reason}


def _entered_ring(arc_seq=1):
    """SW right sent; CORE turned (unseen by a tick), marked it done and opened arc ``arc_seq``."""
    runner, store, ports = _sw_entry()
    _with_arc(ports)
    west, ring = _arc(store, "west:rev"), _arc(store, "ring_s:fwd")
    ports.core.done()                                       # (a): done at the end of turning
    ports.arc = _arc_rec(arc_seq, "SW", "SE")
    ports.at(west, west.length_m)                           # on SW
    _ticks(runner, ports)
    return runner, store, ports, ring


def test_turn_then_arc_is_carried_and_never_sent_again():
    """Carried, so done at SW: the trip is on ring_s and SE's straight went out, never a second right."""
    runner, store, ports, ring = _entered_ring()
    assert runner.view("p1")["current_edge"] == "ring_s"
    assert [s[:2] for s in ports.sent] == [("right", "SW"), ("straight", "SE")]


def test_the_next_place_goes_out_during_the_arc():
    """D-520 2: no MANOEUVRE-style hold during the arc; SE's straight is armed while it runs."""
    runner, store, ports, ring = _entered_ring()
    ports.at(ring, 0.1)                                     # 0.27 m before SE, arc still running
    _ticks(runner, ports)
    view = runner.view("p1")
    assert (view["state"], view["current_edge"]) == ("running", "ring_s")
    assert [s[:2] for s in ports.sent] == [("right", "SW"), ("straight", "SE")]
    assert ports.core.status()["state"] == "armed"
    assert ports.expects[-1]["exit_segment"]["end_place_id"] == "NE"


def test_a_chained_straight_is_carried_by_the_next_arc_and_the_trip_moves_on():
    runner, store, ports, ring = _entered_ring()
    ports.at(ring, 0.1)
    _ticks(runner, ports)                                   # SE straight armed during arc 1
    ports.core.done()                                       # (b): done at the arc end, never executing
    ports.arc = _arc_rec(2, "SE", "NE")
    ports.at(ring, ring.length_m)                           # on SE
    _ticks(runner, ports)
    assert runner.view("p1")["current_edge"] == "ring_e"   # carried: done at SE on this tick
    ring_e = _arc(store, "ring_e:fwd")
    ports.at(ring_e, ring_e.length_m - 0.3)
    _ticks(runner, ports)
    assert runner.view("p1")["current_edge"] == "ring_e"
    assert [s[:2] for s in ports.sent] == [("right", "SW"), ("straight", "SE"), ("stop", "NE")]


def _sw_entry_after(arc):
    """``_sw_entry`` with CORE already showing ``arc`` (an earlier visit) before the first send."""
    runner, store, ports = _setup(caps=ARC)
    _with_arc(ports, arc)
    west = _arc(store, "west:rev")
    _plan(store, ports, "west:rev", west.length_m - 0.5, "NE")
    run(runner.start("p1", "bob"))
    ports.at(west, west.length_m - 0.3)
    ports.pose = dataclasses.replace(ports.pose, **SW_POSE)
    _ticks(runner, ports)
    return runner, store, ports, west


def test_an_older_arc_from_the_same_place_does_not_carry():
    runner, store, ports, west = _sw_entry_after(_arc_rec(4, "SW", "SE", state="ended"))
    assert ports.sent[0][:2] == ("right", "SW")
    _ticks(runner, ports)
    assert runner._live["rosy_60"].sent.get("carried") is not True


def test_an_unarmed_arc_end_is_shown_and_the_trip_goes_on():
    runner, store, ports, ring = _entered_ring()
    ports.arc = {**_arc_rec(1, "SW", "SE", state="ended", reason="lane_arc_end_unarmed"), "travelled_m": 0.374}
    ports.at(ring, ring.length_m - 0.05)
    _ticks(runner, ports)
    view = runner.view("p1")
    assert view["state"] == "running"
    assert view["detail"]["arc_end_unarmed"] == {"end_place_id": "SE", "travelled_m": 0.374}


def test_a_stopped_arc_of_this_trip_stops_it():
    runner, store, ports, ring = _entered_ring()
    ports.arc = _arc_rec(1, "SW", "SE", state="stopped", reason="lane_arc_edge")
    ports.at(ring, 0.15)
    _ticks(runner, ports)
    view = runner.view("p1")
    assert (view["state"], view["reason"]) == ("stopped", "lane_arc")
    assert (view["detail"]["arc_reason"], view["detail"]["arc_place"]) == ("lane_arc_edge", "SW")


def test_a_stopped_arc_from_before_the_trip_is_not_ours():
    runner, store, ports, west = _sw_entry_after(_arc_rec(7, "SE", "NE", state="stopped", reason="lane_arc_edge"))
    _ticks(runner, ports)
    assert runner.view("p1")["state"] == "running" and ports.sent[0][:2] == ("right", "SW")


def test_an_arc_mismatch_abort_stops_the_trip_with_its_reason():
    """CORE dropped our armed instruction at an arc end of another place (``arc_mismatch``)."""
    runner, store, ports, ring = _entered_ring()
    ports.at(ring, 0.1)
    _ticks(runner, ports)
    ports.core.j.update(state="aborted", reason="arc_mismatch")
    _ticks(runner, ports)
    view = runner.view("p1")
    assert (view["state"], view["reason"], view["detail"]["junction_reason"]) == ("stopped", "junction", "arc_mismatch")


def test_the_http_port_passes_line_follow_arc():
    from fleet.server.trip_ports import HttpLaneJunction

    class Client:
        async def state(self):
            return {"line_follow": {"junction": {"state": "idle", "seq": 3}, "arc": _arc_rec(2, "SE", "NE")}}

    assert run(HttpLaneJunction(lambda: {"r": Client()}).junction_state("r"))["arc"]["arc_seq"] == 2
