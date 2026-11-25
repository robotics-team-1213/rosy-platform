"""Eligibility of a bounded camera finish after a confirmed native Nav2 failure."""

from types import SimpleNamespace as NS

import pytest

from fleet.server.trip_nav2_route import camera_finish_segment


def example():
    expected = NS(status="reviewed", source="camera", reference_revision="survey-1")
    edge = NS(id="paint", evidence=expected)
    site = NS(map_id="site", survey=NS(reviewed=True, revision="survey-1"), edges=[edge])
    arc = NS(edge_id=edge.id, drive_mode="lane", polyline=((0., 0.), (1., 0.)),
             length_m=1., end_place="finish", width_m=.25)
    finish = NS(kind="stop", pinned=True, precision_stop=None, stop_zone=None)
    trip = NS(
        nav2=True, repeat=False, request={"to": "finish", "camera_lane_fallback": True},
        segments=[{"edge_id": "paint", "s_from": 0., "s_to": 1.}],
        view={"detail": {"nav2_binding_id": "bind-1"}, "map_version": 3, "hold": None},
        graph=NS(places={"finish": finish}), arc=lambda _index: arc,
    )
    return trip, site, arc, finish, expected


def test_reviewed_straight_with_ordinary_stop_has_bounded_continuation():
    trip, site, *_ = example()
    assert camera_finish_segment(trip, 0, (3, site), .5) == "finish"


@pytest.mark.parametrize("change", [
    "disabled", "repeat", "no_binding", "changed_map", "held", "unreviewed",
    "old_review", "free", "curve", "precision", "stop_zone", "unpinned", "off_segment",
])
def test_camera_finish_refuses_uncommissioned_or_unbound_section(change):
    trip, site, arc, stop, evidence = example()
    version, along = 3, .5
    if change == "disabled":
        trip.request["camera_lane_fallback"] = False
    elif change == "repeat":
        trip.repeat = True
    elif change == "no_binding":
        trip.view["detail"].clear()
    elif change == "changed_map":
        version += 1
    elif change == "held":
        trip.view["hold"] = {"reason": "traffic"}
    elif change == "unreviewed":
        evidence.status = "observed"
    elif change == "old_review":
        evidence.reference_revision = "survey-0"
    elif change == "free":
        arc.drive_mode = "free"
    elif change == "curve":
        arc.polyline = ((0., 0.), (.5, .1), (1., 0.))
    elif change == "precision":
        stop.precision_stop = object()
    elif change == "stop_zone":
        stop.stop_zone = object()
    elif change == "unpinned":
        stop.pinned = False
    elif change == "off_segment":
        along = 0.0
    assert camera_finish_segment(trip, 0, (version, site), along) is None
