"""Stage-3 parking dock: pose geometry, odometry carry and control laws.

docs/plans/2026-09-23-lane-network-parking-design.md §4. The spot sits
`tag_offset_m` in front of the tag; one tag observation in base_link gives
the robot's pose in the dock frame (origin at the spot, x toward the tag).
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from core_features.docking.parking import (
    DockPoseTracker,
    ParkingGains,
    approach_twist,
    between,
    compose,
    robot_in_dock_frame,
    turn_twist,
    reverse_twist,
)

OFFSET = 0.2502


def observation_from(pose, at=0.0, offset=OFFSET):
    """What the camera reports for a robot at dock-frame `pose`."""
    ex, ey, th = pose
    dx, dy = offset - ex, -ey
    c, s = math.cos(th), math.sin(th)
    return SimpleNamespace(x=c * dx + s * dy, y=-s * dx + c * dy, yaw=-th, at=at)


@pytest.mark.parametrize("pose", [(0.0, 0.0, 0.0), (-0.12, 0.02, math.radians(5)),
                                  (-0.2, -0.03, math.radians(-8)), (0.01, 0.004, 0.02)])
def test_one_observation_places_the_robot_in_the_dock_frame(pose):
    obs = observation_from(pose)
    assert robot_in_dock_frame(obs.x, obs.y, obs.yaw, OFFSET) == pytest.approx(pose, abs=1e-9)


def test_at_the_spot_facing_the_tag_is_the_origin():
    assert robot_in_dock_frame(OFFSET, 0.0, 0.0, OFFSET) == pytest.approx((0.0, 0.0, 0.0))


def test_compose_and_between_are_inverse():
    a, b = (0.3, -0.2, 1.0), (0.1, 0.4, -2.5)
    assert compose(a, between(a, b)) == pytest.approx(b)


def test_the_tracker_carries_the_last_observation_by_odometry():
    tracker = DockPoseTracker(OFFSET)
    # The odometry frame is arbitrary: the robot sits at odom (5, 5, 90 deg)
    # while it is at dock pose (-0.1, 0.01, 0).
    tracker.record_odometry(1.0, (5.0, 5.0, math.pi / 2))
    assert tracker.observe(observation_from((-0.1, 0.01, 0.0), at=1.0))
    # It drives 0.05 m straight ahead: odom +y.
    tracker.record_odometry(1.2, (5.0, 5.05, math.pi / 2))
    assert tracker.pose((5.0, 5.05, math.pi / 2)) == pytest.approx((-0.05, 0.01, 0.0))


def test_an_observation_pairs_with_the_odometry_of_its_capture_time():
    """Processed late, a frame captured at t=1.0 must not be credited with
    the motion since: it pairs with the odometry recorded at 1.0."""
    tracker = DockPoseTracker(OFFSET)
    tracker.record_odometry(1.0, (0.0, 0.0, 0.0))
    tracker.record_odometry(1.4, (0.02, 0.0, 0.0))        # moved 2 cm since capture
    assert tracker.observe(observation_from((-0.1, 0.0, 0.0), at=1.0))
    assert tracker.pose((0.02, 0.0, 0.0)) == pytest.approx((-0.08, 0.0, 0.0))


def test_an_old_observation_does_not_replace_a_newer_anchor():
    tracker = DockPoseTracker(OFFSET)
    tracker.record_odometry(2.0, (0.0, 0.0, 0.0))
    assert tracker.observe(observation_from((-0.1, 0.0, 0.0), at=2.0))
    assert not tracker.observe(observation_from((-0.2, 0.0, 0.0), at=1.5))
    assert not tracker.observe(observation_from((-0.2, 0.0, 0.0), at=2.0))
    assert tracker.anchored_at == 2.0


def test_without_odometry_there_is_no_pose():
    tracker = DockPoseTracker(OFFSET)
    assert not tracker.observe(observation_from((-0.1, 0.0, 0.0), at=1.0))
    assert tracker.pose((0.0, 0.0, 0.0)) is None


def _drive(pose, law, steps=400, dt=0.05):
    for _ in range(steps):
        v, w, arrived = law(pose)
        if arrived:
            return pose, True
        mid = pose[2] + w * dt / 2
        pose = (pose[0] + v * dt * math.cos(mid), pose[1] + v * dt * math.sin(mid),
                pose[2] + w * dt)
    return pose, False


@pytest.mark.parametrize("start", [(-0.12, 0.02, math.radians(5)), (-0.12, -0.02, math.radians(-5)),
                                   (-0.12, 0.02, math.radians(-5)), (-0.10, -0.015, 0.0),
                                   (-0.15, 0.0, math.radians(5))])
def test_the_approach_law_arrives_on_the_axis(start):
    """From the acquisition envelope (the creep aims at the spot, so the
    tag is first seen ~0.1 m out within ~2 cm and a few degrees)."""
    gains = ParkingGains()
    end, arrived = _drive(start, lambda p: approach_twist(p, gains))
    assert arrived
    assert end[0] == pytest.approx(0.0, abs=0.004)
    assert abs(end[1]) < 0.006
    assert abs(end[2]) < math.radians(12)      # the heading is aligned in place after


def test_a_worse_start_still_ends_inside_the_acceptance_band():
    """30 mm off with 0.08 m left is beyond one pass's reach (the heading
    reference is capped to keep the tag in view): it still ends inside
    20 mm, and SETTLING's tighter check reseats it."""
    end, arrived = _drive((-0.08, 0.03, math.radians(8)),
                          lambda p: approach_twist(p, ParkingGains()))
    assert arrived and 0.006 < abs(end[1]) < 0.02


def test_the_approach_crawls_near_the_spot_and_never_exceeds_its_cap():
    gains = ParkingGains()
    v_far, _, _ = approach_twist((-0.3, 0.0, 0.0), gains)
    v_near, _, _ = approach_twist((-0.01, 0.0, 0.0), gains)
    assert v_far == gains.speed_max and v_near == gains.speed_min
    _, w, _ = approach_twist((-0.1, 0.2, 0.0), gains)
    assert abs(w) <= gains.max_angular
    assert approach_twist((0.001, 0.0, 0.0), gains) == (0.0, 0.0, True)


def test_reversing_steers_the_lateral_error_out():
    gains = ParkingGains()
    pose = (0.0, 0.02, 0.0)
    dt = 0.05
    for _ in range(40):                           # 2 s at 0.05 m/s
        v, w = reverse_twist(pose, gains)
        mid = pose[2] + w * dt / 2
        pose = (pose[0] + v * dt * math.cos(mid), pose[1] + v * dt * math.sin(mid),
                pose[2] + w * dt)
    assert pose[0] == pytest.approx(-0.1, abs=0.01)
    assert abs(pose[1]) < 0.012


def test_the_turn_law_has_a_floor_and_a_tolerance():
    gains = ParkingGains()
    assert turn_twist(math.radians(0.5), gains) == (0.0, True)
    w, done = turn_twist(math.radians(3), gains)
    assert not done and w == pytest.approx(gains.turn_min_angular)
    w, done = turn_twist(-math.pi / 2, gains)
    assert not done and w == -gains.max_angular


# --- dock/observation feed (control's evidence behind the detector port) ---

from core_features.docking.database import DockInstance, DockType  # noqa: E402
from core_features.docking.detector import SimulatedDetector, select_detector  # noqa: E402
from core_features.docking.feed import DockObservationFeed, FeedDetector  # noqa: E402


def payload(**kwargs):
    body = {"source": "CAMERA_TAG", "stamp": 100.0, "visible": True, "tag_id": 7,
            "x": 0.25, "y": 0.01, "yaw": 0.02, "range_m": 0.2502,
            "confidence": 0.9, "revision": "dock-tag-v1"}
    body.update(kwargs)
    return body


def test_the_feed_restamps_the_capture_on_the_manager_clock():
    feed = DockObservationFeed()
    assert feed.ingest(payload(stamp=100.0), received_at=50.3, source_now=100.2)
    obs = feed.latest()
    assert (obs.x, obs.y, obs.yaw, obs.confidence) == (0.25, 0.01, 0.02, 0.9)
    assert obs.at == pytest.approx(50.1)             # captured 0.2 s before receipt


def test_a_not_visible_payload_clears_the_last_sighting():
    feed = DockObservationFeed()
    feed.ingest(payload(), received_at=1.0, source_now=100.0)
    assert not feed.ingest(payload(visible=False, x=None, y=None, yaw=None, tag_id=None),
                           received_at=1.2, source_now=100.2)
    assert feed.latest() is None


@pytest.mark.parametrize("bad", [payload(source="CAMERA_LINE"), payload(visible="yes"),
                                 payload(x=float("nan")), payload(tag_id=7.0),
                                 payload(stamp=None), "not a dict"])
def test_a_malformed_payload_raises_and_clears(bad):
    feed = DockObservationFeed()
    feed.ingest(payload(), received_at=1.0, source_now=100.0)
    with pytest.raises((ValueError, TypeError)):
        feed.ingest(bad, received_at=1.2, source_now=100.2)
    assert feed.latest() is None


def test_the_feed_detector_sees_only_our_fresh_tag_while_started():
    now = [10.0]
    feed = DockObservationFeed()
    detector = FeedDetector(feed, tag_id=7, clock=lambda: now[0], staleness_s=0.6)
    feed.ingest(payload(), received_at=10.0, source_now=100.0)
    assert detector.relative_pose() is None           # not started
    detector.start()
    assert detector.relative_pose().x == 0.25
    now[0] = 10.7
    assert detector.relative_pose() is None           # stale on the manager clock
    feed.ingest(payload(tag_id=8), received_at=10.7, source_now=100.7)
    assert detector.relative_pose() is None           # someone else's tag
    detector.stop()
    feed.ingest(payload(), received_at=10.7, source_now=100.7)
    assert detector.relative_pose() is None


def test_the_observation_detector_is_selected_only_with_a_feed():
    dock = DockInstance(id="parking", type="parking")
    parking = DockType(name="parking", detector="observation", tag_id=7, tag_size_m=0.05)
    assert isinstance(select_detector(dock, parking), SimulatedDetector)
    assert isinstance(select_detector(dock, parking, feed=DockObservationFeed()), FeedDetector)
    other = DockType(name="d", detector="simulated")
    assert isinstance(select_detector(dock, other, feed=DockObservationFeed()),
                      SimulatedDetector)
