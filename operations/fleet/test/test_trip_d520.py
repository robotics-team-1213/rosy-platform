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
