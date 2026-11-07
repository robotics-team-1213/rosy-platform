"""D-989: the fit from camera track to site map, and its refusals. Synthetic: no scan or camera record pairs them yet."""

import asyncio
import math
from types import SimpleNamespace

import pytest

from fleet.localization.auto_locate import (ALIGNED, DEGRADED, UNKNOWN, AlignmentTracker, fit_rigid,
                                            heading_from_peers)
from fleet.server.auto_locate_service import AutoLocateService

YAW, TX, TY = 0.7, 1.2, -0.4


def to_site(x, y, yaw=YAW, tx=TX, ty=TY):
    c, s = math.cos(yaw), math.sin(yaw)
    return c * x - s * y + tx, s * x + c * y + ty


def track(x, y, *, age=0.1, revision="r1", state="CONFIRMED"):
    return {"state": state, "reason": None, "x": x, "y": y, "age_s": age, "map_id": "world",
            "calibration_revision": revision, "source_id": "ceiling_north"}


def robot(x, y, yaw=0.0, *, loc="LOCALIZED", frame="map", map_id="slam", objects=(), stamp=None):
    return {"pose": {"x": x, "y": y, "yaw": yaw}, "map_id": map_id,
            "localization": {"state": loc, "pose_frame": frame, "unmapped_objects": list(objects),
                             "objects_stamp": stamp}}


def walk(tracker, points, *, t0=0.0, site=to_site, **kw):
    for i, (x, y) in enumerate(points):
        tracker.observe(t0 + i, track(*site(x, y), **kw), robot(x, y), {})
    return t0 + len(points) - 1


PATH = [(0.0, 0.0), (0.2, 0.0), (0.4, 0.1), (0.6, 0.3)]


def test_the_fit_recovers_the_transform_from_a_drive():
    tracker = AlignmentTracker("r1")
    view = tracker.view(walk(tracker, PATH))
    assert view["state"] == ALIGNED and view["evidence"] == "span" and view["use"] == "observation-only"
    assert view["transform"]["yaw"] == pytest.approx(YAW, abs=1e-3)
    assert (view["transform"]["tx"], view["transform"]["ty"]) == pytest.approx((TX, TY), abs=1e-3)


def test_noise_at_the_camera_error_keeps_the_yaw_close():
    noise = [(0.03, -0.03), (-0.04, 0.02), (0.05, 0.01), (-0.03, -0.04)]
    pairs = [((x, y), (to_site(x, y)[0] + n[0], to_site(x, y)[1] + n[1])) for (x, y), n in zip(PATH, noise)]
    fit = fit_rigid(pairs)
    assert abs(math.degrees(fit.yaw - YAW)) < 15.0 and fit.residual_max_m < 0.15


def test_a_standing_robot_alone_is_not_aligned():
    tracker = AlignmentTracker("r1")
    view = tracker.view(walk(tracker, [(0.5, 0.5)] * 3))
    assert (view["state"], view["reason"], view["transform"]) == (UNKNOWN, "NOT_ENOUGH_SPREAD", None)


def test_a_short_drive_is_not_enough():
    tracker = AlignmentTracker("r1")
    assert tracker.view(walk(tracker, [(0.0, 0.0), (0.2, 0.0)]))["state"] == UNKNOWN


@pytest.mark.parametrize("state,expected", [
    (None, "ROBOT_NOT_LOCALIZED"),
    (robot(0, 0, loc="CANDIDATES"), "ROBOT_NOT_LOCALIZED"),
    (robot(0, 0, frame="odom"), "ROBOT_NOT_LOCALIZED"),
    (robot(0, 0, map_id=None), "ROBOT_MAP_UNKNOWN"),
    (robot(float("nan"), 0), "ROBOT_NOT_LOCALIZED"),
])
def test_robot_input_it_cannot_trust_reads_unknown(state, expected):
    tracker = AlignmentTracker("r1")
    tracker.observe(0.0, track(0, 0), state, {})
    assert (tracker.view(0.0)["state"], tracker.view(0.0)["reason"]) == (UNKNOWN, expected)


def test_a_stale_camera_track_makes_no_pair():
    tracker = AlignmentTracker("r1")
    tracker.observe(0.0, track(0, 0, age=2.0), robot(0, 0), {})
    assert tracker.view(0.0)["reason"] == "STALE_CAMERA_TRACK" and tracker.view(0.0)["pairs"] == 0


def test_a_camera_track_that_is_lost_stops_the_report():
    tracker = AlignmentTracker("r1")
    end = walk(tracker, PATH)
    tracker.observe(end + 1, track(0, 0, state="UNKNOWN"), robot(0, 0), {})
    assert tracker.view(end + 2)["state"] == ALIGNED
    assert tracker.view(end + 30)["state"] == ALIGNED  # the camera session is over; two maps do not move
    view = tracker.view(end + 901)
    assert (view["state"], view["reason"], view["transform"]) == (UNKNOWN, "EXPIRED", None)


def test_an_identity_swap_degrades_and_is_never_corrected():
    tracker = AlignmentTracker("r1")
    end = walk(tracker, PATH)
    x, y = to_site(0.6, 0.3)
    tracker.observe(end + 1, track(x + 0.8, y), robot(0.6, 0.3), {})
    view = tracker.view(end + 1)
    assert (view["state"], view["reason"], view["transform"]) == (DEGRADED, "CAMERA_DISAGREES", None)
    tracker.observe(end + 2, track(x, y), robot(0.6, 0.3), {})  # the right blob back does not clear it
    assert tracker.view(end + 2)["state"] == DEGRADED


def test_a_camera_moved_without_a_new_revision_degrades():
    tracker = AlignmentTracker("r1")
    end = walk(tracker, PATH)
    x, y = to_site(0.6, 0.3)
    tracker.observe(end + 1, track(x + 0.2, y + 0.2), robot(0.6, 0.3), {})
    assert tracker.view(end + 1)["reason"] == "CAMERA_DISAGREES"


def test_a_new_calibration_revision_starts_over():
    tracker = AlignmentTracker("r1")
    end = walk(tracker, PATH)
    tracker.observe(end + 1, track(*to_site(0.6, 0.3), revision="r2"), robot(0.6, 0.3), {})
    view = tracker.view(end + 1)
    assert (view["state"], view["pairs"], view["calibration_revision"]) == (UNKNOWN, 1, "r2")


def test_pairs_that_fit_no_rigid_transform_degrade():
    tracker = AlignmentTracker("r1")
    points = [(0.0, 0.0), (0.5, 0.0), (1.0, 0.0)]
    bent = {points[0]: (0.0, 0.0), points[1]: (0.5, 0.0), points[2]: (0.5, 0.5)}
    for i, point in enumerate(points):
        tracker.observe(float(i), track(*bent[point]), robot(*point), {})
    assert tracker.view(2.0)["state"] == DEGRADED


def obj(x, y):
    return SimpleNamespace(x=x, y=y)


def test_lidar_toward_a_peer_gives_the_heading_of_a_standing_robot():
    # The peer is 1 m along site +x. The robot's yaw 30 deg puts it at -30 deg in base_link.
    bearing = math.radians(-30.0)
    yaw, reason = heading_from_peers([obj(0.95 * math.cos(bearing), 0.95 * math.sin(bearing))], (0.0, 0.0),
                                     {"p": (1.0, 0.0)})
    assert reason is None and math.degrees(yaw) == pytest.approx(30.0, abs=0.1)


def test_two_objects_at_the_peer_distance_are_no_evidence():
    objects = [obj(1.0, 0.0), obj(0.0, 1.0)]
    assert heading_from_peers(objects, (0.0, 0.0), {"p": (1.0, 0.0)}) == (None, "NO_PEER_EVIDENCE")


def test_a_peer_too_close_for_the_bearing_is_no_evidence():
    assert heading_from_peers([obj(0.2, 0.0)], (0.0, 0.0), {"p": (0.2, 0.0)}) == (None, "NO_PEER_EVIDENCE")


def test_peers_that_disagree_are_refused():
    objects = [obj(1.0, 0.0), obj(2.0, 0.0)]
    yaw, reason = heading_from_peers(objects, (0.0, 0.0), {"a": (1.0, 0.0), "b": (0.0, 2.0)})
    assert (yaw, reason) == (None, "PEERS_DISAGREE")


def test_one_position_and_a_peer_align_a_standing_robot():
    tracker = AlignmentTracker("r1")
    slam_yaw = 0.2
    x, y = to_site(0.5, 0.5)
    peer = (x + 1.0, y)
    # In the site frame the robot's heading is slam_yaw + YAW; the peer is along site +x.
    bearing = -(slam_yaw + YAW)
    seen = {"x": math.cos(bearing), "y": math.sin(bearing)}
    tracker.observe(0.0, track(x, y), robot(0.5, 0.5, slam_yaw, objects=[seen], stamp=1.0), {"p": peer})
    view = tracker.view(0.0)
    assert (view["state"], view["evidence"]) == (ALIGNED, "peer_heading")
    assert view["transform"]["yaw"] == pytest.approx(YAW, abs=1e-3)


def test_a_stale_lidar_report_gives_no_heading():
    tracker = AlignmentTracker("r1")
    x, y = to_site(0.5, 0.5)
    state = robot(0.5, 0.5, 0.2, objects=[{"x": 1.0, "y": 0.0}], stamp=1.0)
    tracker.observe(0.0, track(x, y, state="UNKNOWN"), state, {})
    tracker.observe(5.0, track(x, y), robot(0.5, 0.5, 0.2, stamp=None), {"p": (x + 1.0, y)})
    assert tracker.view(5.0)["state"] == UNKNOWN


def test_a_drive_that_contradicts_the_peer_heading_degrades():
    tracker = AlignmentTracker("r1")
    x, y = to_site(0.0, 0.0)
    wrong = -(YAW + math.radians(90.0))
    seen = {"x": math.cos(wrong), "y": math.sin(wrong)}
    tracker.observe(0.0, track(x, y), robot(0.0, 0.0, 0.0, objects=[seen], stamp=1.0), {"p": (x + 1.0, y)})
    assert tracker.view(0.0)["state"] == ALIGNED
    for i, (px, py) in enumerate(PATH[1:], start=1):
        tracker.observe(float(i), track(*to_site(px, py)), robot(px, py), {})
    assert tracker.view(3.0)["state"] == DEGRADED


class FakeIdentity:
    def __init__(self):
        self.asked, self.tracks = [], {}

    def confirmed_track_pose(self, robot_id):
        return self.tracks.get(robot_id, {"state": "UNKNOWN", "reason": None})

    async def request(self, robot_id, reason="operator"):
        assert reason != "operator"  # an operator request may use amber, the caution lamp, and chirps
        self.asked.append(robot_id)
        raise RuntimeError("busy")  # a refusal must not break the tick


def service(clock):
    tracking = SimpleNamespace(identity=FakeIdentity(), sources=[SimpleNamespace(robot_ids=("a", "b"))],
                               robot_state=lambda rid: robot(0.0, 0.0) | {"safety": {"estop": False}})
    return AutoLocateService(tracking, clock=clock), tracking


def test_a_session_is_bounded_and_wakes_the_camera_only_while_open():
    now = [0.0]
    locate, _ = service(lambda: now[0])
    assert locate.stream_wanted() is False
    locate.start(["a"])
    assert locate.stream_wanted() is True
    now[0] = 121.0
    assert locate.stream_wanted() is False


def test_a_session_asks_for_the_blink_again_only_after_the_retry():
    now = [0.0]
    locate, tracking = service(lambda: now[0])
    locate.start(["a"])
    asyncio.run(locate.tick())
    now[0] = 5.0
    asyncio.run(locate.tick())
    assert tracking.identity.asked == ["a"]
    now[0] = 11.0
    asyncio.run(locate.tick())
    assert tracking.identity.asked == ["a", "a"]
    now[0] = 200.0
    asyncio.run(locate.tick())
    assert tracking.identity.asked == ["a", "a"]


@pytest.mark.parametrize("state", [None, {}, {"safety": {"estop": True}}, {"safety": {}},
                                   {"safety": {"estop": False}, "docking": {"state": "DOCK_FAILED"}}])
def test_a_session_never_blinks_a_stopped_unknown_or_cautioning_robot(state):
    locate, tracking = service(lambda: 0.0)
    tracking.robot_state = lambda rid: state
    locate.start(["a"])
    asyncio.run(locate.tick())
    assert tracking.identity.asked == []


def test_a_new_session_clears_a_degraded_latch_and_the_same_session_does_not():
    now = [0.0]
    locate, _ = service(lambda: now[0])
    locate.start(["a"])
    locate._trackers["a"]._degraded = "CAMERA_DISAGREES"
    locate.start(["a"])
    assert locate.snapshot()["robots"][0]["state"] == DEGRADED
    now[0] = 121.0
    locate.start(["a"])
    assert locate.snapshot()["robots"][0]["state"] == UNKNOWN
