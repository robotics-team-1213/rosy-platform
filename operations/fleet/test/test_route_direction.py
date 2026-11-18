"""Direction priors follow the selected trip, not a nearby unselected lane."""

import math
from dataclasses import replace
from types import SimpleNamespace

import pytest

from fleet.routing.graph import Arc, _knots
from fleet.routing.direction import route_direction


def _arc(name, start, end, points, mode="lane"):
    points = tuple(points)
    return Arc(name + ":fwd", name, True, start, end, points, _knots(points), .185, .08, mode, None)


def _segment(name, start=0., end=1.):
    return dict(edge_id=name, forward=True, s_from=start, s_to=end)


def test_preview_uses_selected_outgoing_lane_and_source_relative_angles():
    arcs = [_arc("in", "a", "b", [(0., 0.), (1., 0.)]),
            _arc("left", "b", "c", [(1., 0.), (1., 1.)]),
            _arc("straight", "b", "d", [(1., 0.), (2., 0.)])]
    graph = SimpleNamespace(arcs={a.id: a for a in arcs})
    result = route_direction(graph, [_segment("in"), _segment("left")], 0, .9, math.pi / 6)
    assert result["heading_here_deg"] == pytest.approx(-30.)
    assert result["heading_ahead_deg"] == pytest.approx(60.)
    assert result["ahead_m"] == pytest.approx(.25)
    assert result["s_m"] == pytest.approx(.9)


@pytest.mark.parametrize("station,turn,expected", [(.8, 90., 0.), (.86, 90., 90.), (.8, 30., 30.)])
def test_preview_crosses_a_corner_node_only_near_it(station, turn, expected):
    # ring_entry sim 2026-11-18: the NE corner previewed 0.23 m early turned the robot off the road
    end = (1. + math.cos(math.radians(turn)), math.sin(math.radians(turn)))
    arcs = [_arc("in", "a", "b", [(0., 0.), (1., 0.)]), _arc("out", "b", "c", [(1., 0.), end])]
    graph = SimpleNamespace(arcs={a.id: a for a in arcs})
    result = route_direction(graph, [_segment("in"), _segment("out")], 0, station, 0.)
    assert result["heading_ahead_deg"] == pytest.approx(expected)
    assert result["ahead_m"] == pytest.approx(.25)


def test_near_a_corner_the_preview_ends_on_the_heading_leaving_it():
    # a lane curving back after the corner (a ring) must not hide the corner's turn
    arcs = [_arc("in", "a", "b", [(0., 0.), (1., 0.)]), _arc("out", "b", "c", [(1., 0.), (1., .05), (1.3, .1)])]
    graph = SimpleNamespace(arcs={a.id: a for a in arcs})
    result = route_direction(graph, [_segment("in"), _segment("out", end=arcs[1].length_m)], 0, .9, 0.)
    assert result["heading_ahead_deg"] == pytest.approx(90., abs=1.)
    assert result["heading_here_deg"] == pytest.approx(0.)
    assert result["ahead_m"] == pytest.approx(.25)
    # at the node the robot pivots: the lane here is the corner's mid direction
    assert route_direction(graph, [_segment("in"), _segment("out", end=arcs[1].length_m)],
                           0, .97, 0.)["heading_here_deg"] == pytest.approx(45., abs=1.)


@pytest.mark.parametrize("next_mode", ["free", "lane"])
def test_preview_stops_at_partial_destination_or_free_segment(next_mode):
    first = _arc("in", "a", "b", [(0., 0.), (1., 0.)])
    second = _arc("left", "b", "c", [(1., 0.), (1., 1.)], next_mode)
    graph = SimpleNamespace(arcs={a.id: a for a in (first, second)})
    segments = [_segment("in", end=.95)] if next_mode == "lane" else [_segment("in"), _segment("left")]
    result = route_direction(graph, segments, 0, .9, 0.)
    assert result["heading_ahead_deg"] == pytest.approx(0.)
    assert result["ahead_m"] == pytest.approx(.05 if next_mode == "lane" else .1)


def test_disconnected_selected_segments_cannot_supply_a_direction():
    first = _arc("in", "a", "b", [(0., 0.), (1., 0.)])
    second = _arc("other", "x", "y", [(4., 0.), (4., 1.)])
    graph = SimpleNamespace(arcs={a.id: a for a in (first, second)})
    assert route_direction(graph, [_segment("in"), _segment("other")], 0, .9, 0.) is None


@pytest.mark.parametrize('length', [.99996, 1.00004])
def test_serialized_full_arc_endpoint_uses_canonical_map_length(length):
    first = _arc('in', 'a', 'b', [(0., 0.), (length, 0.)])
    turn = _arc('turn', 'b', 'c', [(length, 0.), (length, 1.)])
    graph = SimpleNamespace(arcs={a.id: a for a in (first, turn)})
    result = route_direction(graph, [_segment('in'), _segment('turn')], 0, .9, 0.)
    assert result['heading_ahead_deg'] == pytest.approx(90.)
    assert result['ahead_m'] == pytest.approx(.25)


def test_reverse_arc_and_later_station_preserve_selected_travel_direction():
    first = _arc("in", "a", "b", [(0., 0.), (1., 0.)])
    reverse = replace(first, id="in:rev", forward=False, start_place="b", end_place="a",
                      polyline=((1., 0.), (0., 0.)))
    graph = SimpleNamespace(arcs={a.id: a for a in (first, reverse)})
    segments = [_segment("in", start=.4), dict(_segment("in"), forward=False)]
    result = route_direction(graph, segments, 1, .2, math.pi)
    assert result["heading_ahead_deg"] == pytest.approx(0.)
    assert result["s_m"] == pytest.approx(.8)


@pytest.mark.parametrize("station,yaw", [(-.01, 0.), (1.01, 0.), (.5, float("nan"))])
def test_invalid_source_geometry_has_no_prior(station, yaw):
    arc = _arc("in", "a", "b", [(0., 0.), (1., 0.)])
    assert route_direction(SimpleNamespace(arcs={arc.id: arc}), [_segment("in")],
                           0, station, yaw) is None