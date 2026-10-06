"""D-468 containment rule from URDF body, measured projection uncertainty and lane width.

Pinky body from the URDF footprint (front .042, rear -.076, half width .0566). The 260919
track leaves ~5 mm per side at the lane centre; the sim measured 4.3 mm uncertainty.
"""
import math

import pytest

from core_common.protocol.lane_containment import LaneContainmentEvidence
from core_features.line_follow.lane_return import Boundary, Corridor, Footprint, Pose, ReturnController, ReturnInput
from core_features.line_follow.manager import LineFollowManager
from core_features.line_follow.model import LineFollowConfig, LineFollowMode, LineObservation

HALF = .0566
LANE_EDGE = HALF+.005


class Bus:
    def __init__(self): self.events = []
    def publish(self, event, **kwargs): self.events.append(event)


def rig(**config):
    clock = [1.]
    raw = dict(body_front_x_m=.042, body_rear_x_m=-.076, body_half_width_m=HALF,
               cruise_speed=.04, max_linear=.04, recovery_local_enabled=True)
    raw.update(config)
    manager = LineFollowManager(Bus(), clock=lambda: clock[0], config=LineFollowConfig(**raw))
    manager.bind_recovery(calibration_active=lambda: False, linear_ceiling=lambda: .04)
    manager.bind_return_motion(lambda now, v, w: True)
    manager.set_mode(LineFollowMode.CAMERA_LINE)
    return clock, manager


def frame(r, t, y=0., uncertainty=.0043):
    clock, manager = r
    clock[0] = t
    manager.observe_return_pose(stamp_ns=round(t*1e9), source_now_ns=round(t*1e9),
                                frame='odom', x=0., y=y, yaw=0., received_at=t)
    containment = LaneContainmentEvidence.model_validate(dict(
        stamp=t, geometry_id='track-260919', ground_source='CALIBRATED', uncertainty_m=uncertainty,
        boundaries=[dict(side=side, slope=0., intercept_m=edge-y, observed_x_min_m=0.,
                         observed_x_max_m=.4) for side, edge in (('left', LANE_EDGE), ('right', -LANE_EDGE))]))
    manager.observe(LineObservation(LineFollowMode.CAMERA_LINE, t, True, 0., .9, containment=containment),
                    received_at=t, source_now=t)
    return manager.tick(t)


def test_centred_pinky_in_narrow_lane_is_contained_and_checkpointed():
    r = rig()
    for t in (1., 1.05, 1.1, 1.15):
        assert frame(r, t).linear > 0
    assert not r[1].status().reason.startswith('lane_return')
    assert r[1]._return_controller.checkpoint is not None


def test_body_corner_outside_narrow_lane_is_not_contained():
    r = rig()
    action = frame(r, 1., y=.008)   # 3 mm of the body past the boundary
    assert action.linear == action.angular == 0
    assert r[1].status().reason == 'lane_return_containment_unconfirmed'


def test_uncertainty_larger_than_raw_margin_is_not_contained():
    r = rig()
    action = frame(r, 1., uncertainty=.006)   # 5 mm geometric margin, 6 mm projection error
    assert action.linear == action.angular == 0
    assert r[1].status().reason == 'lane_return_containment_unconfirmed'


def test_required_body_clearance_parameter_is_applied():
    r = rig(lane_return_body_margin_m=.002)   # eroded centred margin is only .0007
    assert frame(r, 1.).linear == 0
    assert r[1].status().reason == 'lane_return_containment_unconfirmed'


def test_off_keeps_legacy_following_even_when_body_is_outside():
    r = rig(recovery_local_enabled=False)
    for t in (1., 1.05):
        assert frame(r, t, y=.008).linear > 0
    assert r[1]._return_controller is None


BODY = Footprint(.042, -.076, HALF)


def tick(ctl, t, lane, linear_limit=.04):
    return ctl.tick(ReturnInput(now=t, pose=Pose(t, round(t*1e9), 'odom', 0., 0., 0.), corridor=lane,
        corridor_at=t, corridor_stamp_ns=round(t*1e9), clearance_at=t, floor_safe=True,
        front_clear=True, rear_clear=True, turn_clear=True, authorized=True,
        linear_limit=linear_limit, angular_limit=.15))


def test_heading_into_the_boundary_spends_margin_before_the_next_frame():
    # 0.1 rad toward the left boundary: up to .04*sin(.1)*.3 = 1.2 mm before evidence expires.
    s, body = math.tan(.1), Footprint(.08, -.08, .06)
    lane = Corridor(Boundary(s, .10-.0314), Boundary(s, -.10-.0314), 'rig-a')
    assert 0 < lane.margin(body) < .04*math.sin(.1)*.3
    assert tick(ReturnController(body), 1., lane).phase == 'departure_stop'
    assert tick(ReturnController(body), 1., lane, linear_limit=0.).phase == 'tracking'


def test_off_centre_contained_pose_is_not_a_normal_checkpoint():
    lane = Corridor(Boundary(0, LANE_EDGE-.004), Boundary(0, -LANE_EDGE-.004), 'track-260919')
    ctl = ReturnController(BODY)
    for t in (1., 1.05, 1.1, 1.15):
        assert tick(ctl, t, lane).phase == 'tracking'   # 1 mm in, 4 of 5 mm play used
    assert ctl.checkpoint is None


@pytest.mark.parametrize('bad', [dict(lane_return_body_margin_m=-.001), dict(lane_return_body_margin_m=.06),
                                 dict(lane_return_checkpoint_fraction=1.1),
                                 dict(lane_return_checkpoint_fraction=float('nan'))])
def test_margin_parameters_are_validated(bad):
    with pytest.raises(ValueError):
        LineFollowConfig(**bad)
