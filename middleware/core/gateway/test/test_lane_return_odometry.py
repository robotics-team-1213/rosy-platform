"""D-468 gateway carries original odometry header into the real manager ledger."""
from types import SimpleNamespace
import pytest

from core.bridge.odometry import observe_lane_return
from core_features.line_follow.manager import LineFollowManager
from core_features.line_follow.model import LineFollowConfig, LineFollowMode, LineObservation
from core_common.protocol.lane_containment import LaneContainmentEvidence


class Bus:
    def publish(self, *args, **kwargs): pass


def bridge():
    manager = LineFollowManager(Bus(), clock=lambda: 10., config=LineFollowConfig(
        body_front_x_m=.08, body_rear_x_m=-.08, body_half_width_m=.06))
    manager.set_mode(LineFollowMode.CAMERA_LINE)
    return SimpleNamespace(_svc=SimpleNamespace(line_follow=manager),
        _line_clock=lambda: 10., _node=SimpleNamespace(get_clock=lambda:
            SimpleNamespace(now=lambda: SimpleNamespace(nanoseconds=100100000000))))


def msg(sec=100, nanos=0):
    return SimpleNamespace(header=SimpleNamespace(frame_id="odom",
        stamp=SimpleNamespace(sec=sec, nanosec=nanos)), child_frame_id="base_link",
        pose=SimpleNamespace(pose=SimpleNamespace(orientation=SimpleNamespace(x=0.,y=0.,z=0.,w=1.))))


def test_original_ros_time_and_frame_are_preserved_with_source_age():
    b = bridge()
    observe_lane_return(b, msg(), dict(x=0., y=0., yaw=0.), now=10.)
    view = b._svc.line_follow.return_evidence(now=10.)
    assert view.pose.stamp_ns == 100000000000
    assert view.pose.frame == "odom"
    assert view.pose.received_at == pytest.approx(9.9)


@pytest.mark.parametrize("bad", [msg(nanos=-1), msg(nanos=1000000000), msg(sec=True)])
def test_bad_original_header_invalidates_previous_path(bad):
    b = bridge()
    observe_lane_return(b, msg(), dict(x=0., y=0., yaw=0.), now=10.)
    epoch = b._svc.line_follow.return_evidence(now=10.).epoch
    observe_lane_return(b, bad, dict(x=0., y=0., yaw=0.), now=10.)
    view = b._svc.line_follow.return_evidence(now=10.)
    assert view.epoch > epoch
    assert view.pose is None


def test_mode_off_drops_the_old_return_checkpoint_evidence():
    b = bridge()
    observe_lane_return(b, msg(), dict(x=0., y=0., yaw=0.), now=10.)
    b._svc.line_follow.stop()
    assert b._svc.line_follow.return_evidence(now=10.).pose is None


@pytest.mark.parametrize("values", [(0.,0.,0.,0.), (0.,0.,0.,float('nan')), (0.,0.,0.,2.)])
def test_invalid_original_rotation_cannot_become_a_plausible_finite_yaw(values):
    b = bridge()
    m = msg()
    m.pose.pose.orientation = SimpleNamespace(**dict(zip(("x","y","z","w"), values)))
    observe_lane_return(b, m, dict(x=0., y=0., yaw=0.), now=10.)
    assert b._svc.line_follow.return_evidence(now=10.).pose is None


def test_manager_routes_source_stamped_containment_to_pose_alignment():
    b = bridge()
    observe_lane_return(b, msg(), dict(x=0., y=0., yaw=0.), now=10.)
    observe_lane_return(b, msg(nanos=100000000), dict(x=.01, y=0., yaw=0.), now=10.1)
    lane = LaneContainmentEvidence.model_validate(dict(stamp=100.05, geometry_id="rig-a",
        ground_source="CALIBRATED", uncertainty_m=.005, boundaries=[dict(side=side,
        slope=0., intercept_m=y, observed_x_min_m=.1, observed_x_max_m=.4)
        for side,y in (("left",.1),("right",-.1))]))
    b._svc.line_follow.observe(LineObservation(LineFollowMode.CAMERA_LINE, 100.05, True,
        0., .9, containment=lane), received_at=10.1, source_now=100.1)
    view = b._svc.line_follow.return_evidence(now=10.1)
    assert view.reason == "ready"
    assert view.image_pose.x == pytest.approx(.005)
    # Same frame received later cannot update the recovery's receipt freshness.
    assert not b._svc.line_follow.observe(LineObservation(LineFollowMode.CAMERA_LINE,100.05,True,
        0.,.9,containment=lane), received_at=10.2,source_now=100.1)
    assert b._svc.line_follow.return_evidence(now=10.2).received_at == pytest.approx(10.05)
    b._svc.line_follow.invalidate(received_at=10.2)
    assert b._svc.line_follow.return_evidence(now=10.2).corridor is None
    # Invalid observation stamps use receipt time; never compare them with ROS time.
    b._svc.line_follow.invalidate(received_at=1000.)
    next_lane = lane.model_copy(update={"stamp":100.15})
    assert b._svc.line_follow.observe(LineObservation(LineFollowMode.CAMERA_LINE,100.15,True,
        0.,.9,containment=next_lane), received_at=1000.2,source_now=100.2)
