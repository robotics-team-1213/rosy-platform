"""D-494 6: pure teach rules — point keeping, RDP, end candidates, appending to a map body."""

from __future__ import annotations

import pytest

from fleet.localization.map_pose import MapPose
from fleet.routing.teach import TeachRefused, append_edge, candidates, keep, simplify
from fleet.site_map import SiteMap


def _pose(x, y, state="LOCALIZED", dead_reckon_m=0.0):
    return MapPose(x=x, y=y, yaw=0.0, state=state, source="sighting", dead_reckon_m=dead_reckon_m, age_s=0.0)


def test_keep_spaces_points_and_filters_untrusted_poses():
    points = [(0.0, 0.0)]
    assert keep(points, _pose(0.099, 0.0)) is None                       # under 0.1 m
    assert keep(points, _pose(0.1, 0.0)) == (0.1, 0.0)                    # exactly 0.1 m
    assert keep([], _pose(0.0, 0.0)) == (0.0, 0.0)
    assert keep(points, _pose(1.0, 0.0, "LOCALIZED", 0.5)) == (1.0, 0.0)  # short bridge
    assert keep(points, _pose(1.0, 0.0, "LOCALIZED", 0.51)) is None       # long bridge
    assert keep(points, _pose(1.0, 0.0, "DEGRADED", 0.0)) is None         # DEGRADED is never kept
    assert keep(points, _pose(None, None, "UNKNOWN")) is None
    assert keep(points, None) is None


def test_a_degraded_re_anchor_spike_is_dropped_from_the_line():
    points = []
    for pose in (_pose(0.0, 0.0), _pose(0.2, 0.0), _pose(0.4, 0.3, "DEGRADED", 0.0),  # jump re-anchor
                 _pose(0.4, 0.0, "LOCALIZED", 0.2), _pose(0.6, 0.0)):
        point = keep(points, pose)
        if point is not None:
            points.append(point)
    assert points == [(0.0, 0.0), (0.2, 0.0), (0.4, 0.0), (0.6, 0.0)]


def test_rdp_drops_points_within_tolerance_and_keeps_corners():
    line = [(0.0, 0.0), (0.5, 0.01), (1.0, -0.02), (1.5, 0.0)]
    assert simplify(line) == [(0.0, 0.0), (1.5, 0.0)]              # 0.02 m off is inside
    assert simplify([(0.0, 0.0), (0.5, 0.0201), (1.0, 0.0)]) == [(0.0, 0.0), (0.5, 0.0201), (1.0, 0.0)]
    corner = [(0.0, 0.0), (0.5, 0.0), (1.0, 0.0), (1.0, 0.5), (1.0, 1.0)]
    assert simplify(corner) == [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
    assert simplify([(0.0, 0.0), (1.0, 0.0)]) == [(0.0, 0.0), (1.0, 0.0)]
    loop = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)]   # closed: chord is a point
    assert simplify(loop) == loop


def test_rdp_handles_a_long_recording_without_recursion():
    line = [(i * 0.1, 0.0) for i in range(20_000)]
    assert simplify(line) == [line[0], line[-1]]


PLACES = [{"id": "A", "name": "주차", "x": 0.0, "y": 0.0, "kind": "park"},
          {"id": "B", "name": "충전", "x": 0.1, "y": 0.0, "kind": "charge"},
          {"id": "C", "name": "먼 곳", "x": 3.0, "y": 0.0, "kind": "stop"}]


def test_candidates_are_places_within_015_m_nearest_first():
    assert [c["place_id"] for c in candidates(PLACES, (0.08, 0.0))] == ["B", "A"]
    assert candidates(PLACES, (0.25, 0.0)) == [{"place_id": "B", "name": "충전", "distance_m": 0.15}]
    assert candidates(PLACES, (2.0, 0.0)) == []


BASE = {"schema": "rosy.site_map/1", "map_id": "site", "places": PLACES[:1] + PLACES[2:], "edges": []}


def test_append_edge_pins_ends_and_adds_a_new_place_that_validates():
    body, edge_id = append_edge(BASE, [(0.1, 0.05), (1.0, 0.5), (2.0, 0.0)], start="A",
                                end={"name": "새 주소", "kind": "stop"}, direction="two_way",
                                drive_mode="lane", speed_cap_mps=0.2, width_m=0.185)
    site = SiteMap.model_validate(body)
    edge = next(e for e in site.edges if e.id == edge_id)
    new = next(p for p in site.places if p.id == edge.to)
    assert edge_id == "teach_e1" and edge.from_ == "A" and (new.name, new.kind) == ("새 주소", "stop")
    assert edge.polyline[0] == (0.0, 0.0) and edge.polyline[-1] == (2.0, 0.0)
    assert BASE["edges"] == [] and len(BASE["places"]) == 2      # the base is not changed


@pytest.mark.parametrize("start,code", [("Z", "TEACH_UNKNOWN_PLACE"), ("C", "TEACH_PLACE_TOO_FAR")])
def test_append_edge_refuses_an_unknown_or_far_place(start, code):
    with pytest.raises(TeachRefused) as err:
        append_edge(BASE, [(0.0, 0.0), (1.0, 0.0)], start=start, end={"name": "x"}, direction="one_way",
                    drive_mode="lane", speed_cap_mps=0.2, width_m=0.2)
    assert err.value.code == code and err.value.detail["end"] == "from"


def test_pinning_drops_interior_points_near_the_place_so_the_end_tangent_stays():
    base = {"schema": "rosy.site_map/1", "places": [{"id": "P", "name": "p", "x": 0.14, "y": 0.0, "kind": "stop"}],
            "edges": []}
    body, edge_id = append_edge(base, [(0.0, 0.0), (0.1, 0.0), (0.1, 2.0)], start="P", end={"name": "끝"},
                                direction="one_way", drive_mode="lane", speed_cap_mps=0.2, width_m=0.2)
    assert body["edges"][0]["polyline"] == [[0.14, 0.0], [0.1, 2.0]]   # no hook back through (0.1, 0)
    SiteMap.model_validate(body)
