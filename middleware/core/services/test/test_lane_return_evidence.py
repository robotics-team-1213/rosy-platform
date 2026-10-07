"""D-468 source-time odometry admission; receipt time cannot replace image time."""
import pytest

from core_common.protocol.lane_containment import LaneContainmentEvidence
from core_features.line_follow.recovery.lane_return import Footprint
from core_features.line_follow.recovery.lane_return_evidence import LaneReturnEvidence


BODY = Footprint(.08, -.08, .06)


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
