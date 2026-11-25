"""Eligibility of a bounded camera finish after a confirmed native Nav2 failure."""

from types import SimpleNamespace as NS
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from fakes import run
from fleet.server import trip_nav2_route
from fleet.server.trip_nav2_route import camera_finish_segment
from fleet.server.trip_ports import TripError
from fleet.server.trip_routes import TripRequest
from fleet.server.trip_runner import TripRunner
from fleet.swarm.dispatch_guard import check_dispatch


def example():
    expected = NS(status="reviewed", source="camera", reference_revision="survey-1")
    edge = NS(id="paint", evidence=expected)
    site = NS(map_id="site", survey=NS(reviewed=True, revision="survey-1"), edges=[edge], crosswalks=[])
    arc = NS(edge_id=edge.id, drive_mode="lane", polyline=((0., 0.), (1., 0.)),
             length_m=1., end_place="finish", width_m=.25)
    finish = NS(kind="stop", pinned=True, precision_stop=None, stop_zone=None)
    trip = NS(
        nav2=True, repeat=False, request={"to": "finish", "camera_lane_fallback": True},
        segments=[{"edge_id": "paint", "s_from": 0., "s_to": 1.}],
        view={"detail": {"nav2_binding_id": "bind-1"}, "map_version": 3, "hold": None,
              "caps": {"kind": "pinky_pro"}},
        graph=NS(places={"finish": finish}), arc=lambda _index: arc,
    )
    return trip, site, arc, finish, expected


def test_reviewed_straight_with_ordinary_stop_has_bounded_continuation():
    trip, site, *_ = example()
    assert camera_finish_segment(trip, 0, (3, site), .5) == "finish"


def test_request_requires_explicit_approved_slam_and_finite_named_trip():
    baseline = {"to": "finish", "drive_mode": "nav2"}
    assert TripRequest(**baseline).camera_lane_fallback is False
    approved = {**baseline, "approved_slam_required": True, "camera_lane_fallback": True}
    assert TripRequest(**approved).camera_lane_fallback is True
    for changes in ({"approved_slam_required": False}, {"repeat": True, "via": ["start"]},
                    {"to": {"x": 1., "y": 0.}}, {"drive_mode": None}):
        with pytest.raises(ValidationError):
            TripRequest(**(approved | changes))


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


@pytest.mark.parametrize("outcome", ["success", "stale_camera", "changed_binding", "stop_unknown",
                                     "velocity_repeated", "body_outside"])
def test_camera_start_requires_ack_two_fresh_zero_samples_and_same_binding(monkeypatch, outcome):
    trip, site, arc, *_ = example()
    events = []
    clock = [1_800_000_000.]
    binding = {"binding_id": "bind-1"}
    trip.open = True
    trip.view.update(robot_id="r1", lease={"lease_id": "lease-1"})
    trip.progress = lambda _index, along: along
    trip.graph.arcs = {"paint:fwd": arc}
    trip.segments[0]["forward"] = True
    arc.project = lambda _x, _y: (.05 if outcome == "body_outside" else 0., .5, 0.)

    async def call(value):
        return await value

    async def cancel(_robot):
        events.append("cancel")
        return {"cancel_confirmed": outcome != "stop_unknown"}

    async def read(_robot):
        events.append("zero")
        if outcome != "velocity_repeated" or events.count("zero") == 1:
            clock[0] += .01
        return {
            "mode": "IDLE", "navigation": "CANCELED", "line_follow": {"mode": "OFF"},
            "safety": {"estop": False}, "trip_lease": {"lease_id": "lease-1"},
            "velocity": {"linear": 0., "angular": 0.},
            "evidence": {"velocity": {"evidence": "fresh",
                                      "sampled_at": datetime.fromtimestamp(clock[0], timezone.utc).isoformat()}},
        }

    async def caps(*_args):
        return NS(line_follow_authority_required=True)

    async def front(_robot):
        events.append("front")
        return {"stale": outcome == "stale_camera", "available": True, "age_ms": 20}

    async def pose(*_args):
        return NS(x=.5, y=0., yaw=0., odom_stamp=clock[0], age_s=0.)

    async def start(_robot):
        events.append("wire")
        if outcome == "changed_binding":
            binding["binding_id"] = "replaced"
        check_dispatch(path="/api/v1/line-follow/mode")
        events.append("camera")

    async def after(_trip):
        pass

    monkeypatch.setattr(trip_nav2_route, "precision_map_pose", pose)
    runner = NS(
        named_stop_state=read, _cancel_goal=cancel, _call=call, _caps_checks=caps, _clock=lambda: clock[0],
        _store=NS(active=lambda: (3, site), map_bindings=NS(active=lambda _rid: binding)),
        _junction=NS(front_camera=front, start_camera_line=start), _check_human_hold=lambda: None,
        _save=lambda _trip: events.append("saved"), _after_send=after,
        authority=NS(mode=lambda _caps: "core"), lease=NS(required=True),
        traffic=NS(holds=lambda *_: False, _signals={}),
        config=NS(start_heading_tol_deg=15., period_s=0., arm_distance_m=.6),
    )
    runner._start_line = lambda live: TripRunner._start_line(runner, live)
    if outcome == "success":
        assert run(trip_nav2_route._start_camera_finish(runner, trip, 0, .5, (3, site)))
        assert events == ["cancel", "zero", "zero", "front", "saved", "wire", "camera", "saved", "saved"]
        assert trip.view["detail"]["camera_lane_fallback"]["phase"] == "running"
        return
    with pytest.raises(TripError):
        run(trip_nav2_route._start_camera_finish(runner, trip, 0, .5, (3, site)))
    assert "camera" not in events
    if outcome == "stop_unknown":
        assert events == ["cancel"]
    if outcome == "velocity_repeated":
        assert events == ["cancel", "zero", "zero", "zero", "zero"]
