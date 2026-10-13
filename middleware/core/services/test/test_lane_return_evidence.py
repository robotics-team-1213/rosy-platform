"""D-468 source-time odometry admission; receipt time cannot replace image time."""
import pytest

from core_common.protocol.lane_containment import LaneContainmentEvidence
from core_features.line_follow.recovery.lane_return import Footprint
from core_features.line_follow.recovery.lane_return_evidence import LaneReturnEvidence


BODY = Footprint(.08, -.08, .06)


def test_boundary_revision_ignores_motion_jitter_duplicates_and_needs_three_changed_frames():
    from core_features.line_follow.recovery.lane_return import Boundary, Corridor, Pose
    from core_features.line_follow.recovery.lane_return_evidence import ReturnEvidenceView
    from dataclasses import replace

    feed = LaneReturnEvidence()

    def view(stamp, offset=0, camera_y=0):
        return ReturnEvidenceView("ready", 1,
            pose=Pose(stamp, stamp, "odom", 0, camera_y, 0),
            corridor=Corridor(Boundary(0, .1-camera_y+offset), Boundary(0, -.1-camera_y+offset), "rig-a"),
            source_stamp_ns=stamp)

    assert feed.boundary_change(view(1))["state"] == "baseline"
    assert feed.boundary_change(view(2, camera_y=.02))["revision"] == 0
    assert feed.boundary_change(view(3, offset=.005))["revision"] == 0
    candidate = view(4, offset=.03)
    assert feed.boundary_change(candidate)["state"] == "confirming"
    assert feed.boundary_change(candidate)["revision"] == 0
    assert feed.boundary_change(view(5, offset=.03))["revision"] == 0
    assert feed.boundary_change(view(6, offset=.03))["revision"] == 1
    assert feed.boundary_change(view(7, offset=.03))["revision"] == 1
    assert feed.boundary_change(replace(view(8), reason="lane_stale"))["state"] == "unknown"
    assert feed.boundary_change(replace(view(9), epoch=2))["state"] == "baseline"
    assert feed.boundary_change(view(10))["revision"] == 1


def lane(stamp=100.05, **changes):
    raw = dict(stamp=stamp, geometry_id="rig-a", ground_source="CALIBRATED",
        uncertainty_m=.005, boundaries=[dict(side=side, slope=0., intercept_m=y,
        observed_x_min_m=.1, observed_x_max_m=.4) for side, y in (("left", .1), ("right", -.1))])
    raw.update(changes)
    return LaneContainmentEvidence.model_validate(raw)


def sample(feed, stamp, x=0, frame="odom", now=10.):
    return feed.observe_pose(stamp_ns=int(stamp*1e9), source_now_ns=int(stamp*1e9),
        frame=frame, x=x, y=0., yaw=0., received_at=now)


def test_image_pose_is_interpolated_on_source_clock_then_transformed_to_latest_pose():
    feed = LaneReturnEvidence()
    sample(feed, 100., 0., now=10.)
    sample(feed, 100.1, .01, now=10.1)
    assert feed.observe_lane(lane(), received_at=10.05)
    view = feed.snapshot(now=10.1, body=BODY)
    assert view.reason == "ready"
    assert view.image_pose.x == pytest.approx(.005)
    assert view.pose.x == pytest.approx(.01)
    assert view.source_stamp_ns == 100050000000
    assert view.corridor.margin(BODY) == pytest.approx(.035)


def test_odom_stamp_slightly_ahead_of_core_clock_is_kept_as_fresh():
    """D-495 SIM finding 2: 1 ms of clock skew must not reset the trail or bump the epoch."""
    feed = LaneReturnEvidence()
    sample(feed, 100., now=10.)
    epoch = feed.epoch
    assert feed.observe_pose(stamp_ns=100_101_000_000, source_now_ns=100_100_000_000,
                             frame="odom", x=.01, y=0., yaw=0., received_at=10.1)
    assert len(feed.trail.samples) == 2 and feed.epoch == epoch
    assert feed.trail.samples[-1].received_at == 10.1


def test_odom_stamp_far_ahead_is_dropped_without_reset():
    feed = LaneReturnEvidence()
    sample(feed, 100., now=10.)
    epoch = feed.epoch
    assert not feed.observe_pose(stamp_ns=100_300_000_000, source_now_ns=100_100_000_000,
                                 frame="odom", x=.01, y=0., yaw=0., received_at=10.1)
    assert len(feed.trail.samples) == 1 and feed.epoch == epoch


def test_receive_time_cannot_make_replayed_image_fresh():
    feed = LaneReturnEvidence()
    sample(feed, 100., now=10.)
    sample(feed, 100.1, now=10.1)
    assert feed.observe_lane(lane(), received_at=10.05)
    assert not feed.observe_lane(lane(), received_at=10.2)
    assert feed.snapshot(now=10.4, body=BODY).corridor is None


def test_unknown_projection_uncertainty_does_not_become_safe_margin():
    feed = LaneReturnEvidence()
    sample(feed, 100., now=10.)
    sample(feed, 100.1, now=10.1)
    feed.observe_lane(lane(uncertainty_m=None), received_at=10.05)
    assert feed.snapshot(now=10.1, body=BODY).reason == "projection_uncertainty_unknown"


def test_unbracketed_image_or_long_pose_gap_cannot_be_used_for_world_corridor():
    feed = LaneReturnEvidence()
    sample(feed, 100., now=10.)
    feed.observe_lane(lane(), received_at=10.05)
    assert feed.snapshot(now=10.1, body=BODY).corridor is None


def test_pose_reset_invalidates_pending_image_and_exposes_new_continuity_epoch():
    feed = LaneReturnEvidence()
    sample(feed, 100., now=10.)
    sample(feed, 100.1, now=10.1)
    feed.observe_lane(lane(), received_at=10.05)
    epoch = feed.snapshot(now=10.1, body=BODY).epoch
    assert not sample(feed, 99., now=10.2)
    view = feed.snapshot(now=10.2, body=BODY)
    assert view.epoch > epoch
    assert view.corridor is None


def test_boundary_extrapolation_is_bounded():
    feed = LaneReturnEvidence()
    sample(feed, 100., now=10.)
    sample(feed, 100.1, now=10.1)
    raw = lane().model_dump()
    for boundary in raw["boundaries"]:
        boundary["observed_x_min_m"] = .8
        boundary["observed_x_max_m"] = 1.
    feed.observe_lane(LaneContainmentEvidence.model_validate(raw), received_at=10.05)
    assert feed.snapshot(now=10.1, body=BODY).reason == "boundary_support_insufficient"


def test_future_sample_beyond_the_tolerance_is_dropped_and_the_trail_continues():
    # D-507 8: the dropped sample leaves no gap; the next in-time sample still continues.
    feed = LaneReturnEvidence()
    sample(feed, 100., now=10.)
    epoch = feed.epoch
    assert not feed.observe_pose(stamp_ns=100_250_000_000, source_now_ns=100_050_000_000,
                                 frame="odom", x=.005, y=0., yaw=0., received_at=10.05)
    assert sample(feed, 100.1, now=10.1)
    assert len(feed.trail.samples) == 2 and feed.epoch == epoch


def test_real_discontinuity_still_breaks_the_trail():
    feed = LaneReturnEvidence()
    sample(feed, 100., now=10.)
    epoch = feed.epoch
    assert not feed.observe_pose(stamp_ns=100_100_000_000, source_now_ns=100_100_000_000,
                                 frame="odom", x=.5, y=0., yaw=0., received_at=10.1)
    assert len(feed.trail.samples) == 1 and feed.epoch == epoch+1
