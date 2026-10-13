"""D-468 containment rule from URDF body, measured projection uncertainty and lane width.

Pinky body from the URDF footprint (core_common.robot_body.PINKY_PRO_GEOMETRY: front .04205,
rear -.076, half width .05655, 113.1 mm wide). 260919 straights (STL nominal, unmeasured):
paint centres 185 mm apart, tape 25 mm, so the inner (drivable) edges the producer sends are
160 mm apart and a centred Pinky has 23.45 mm play per side. The sim measured 4.3 mm
uncertainty. VERY_NARROW_EDGE (5 mm play) is a stress case, not the 260919 track.
"""
import math

import pytest

from core_common.protocol.lane_containment import LaneContainmentEvidence
from core_features.line_follow.recovery.lane_return_evidence import LaneReturnEvidence
from core_features.line_follow.recovery.lane_return import Boundary, Corridor, Footprint, Pose, ReturnController, ReturnInput
from core_features.line_follow.manager import LineFollowManager
from core_features.line_follow.model import LineFollowConfig, LineFollowMode, LineObservation
from core_common.robot_body import PINKY_PRO_GEOMETRY

FOOTPRINT = PINKY_PRO_GEOMETRY["footprint"]
FRONT, REAR, HALF = FOOTPRINT["front_x_m"], PINKY_PRO_GEOMETRY["caster"]["rear_x_m"], FOOTPRINT["half_width_m"]
# 260919 STL straights: lane_half_width_m .0925 (paint centre) less half the 25 mm tape.
TRACK_260919_EDGE = .0925-.0125
TRACK_260919_PLAY = TRACK_260919_EDGE-HALF
VERY_NARROW_EDGE = HALF+.005


class Bus:
    def __init__(self): self.events = []
    def publish(self, event, **kwargs): self.events.append(event)


def rig(**config):
    clock = [1.]
    raw = dict(body_front_x_m=FRONT, body_rear_x_m=REAR, body_half_width_m=HALF,
               cruise_speed=.04, max_linear=.04, recovery_local_enabled=True)
    raw.update(config)
    manager = LineFollowManager(Bus(), clock=lambda: clock[0], config=LineFollowConfig(**raw))
    manager.bind_recovery(calibration_active=lambda: False, linear_ceiling=lambda: .04)
    manager.bind_return_motion(lambda now, v, w: True)
    manager.set_mode(LineFollowMode.CAMERA_LINE)
    return clock, manager


def frame(r, t, y=0., uncertainty=.0043, yaw=0., edge=VERY_NARROW_EDGE):
    clock, manager = r
    clock[0] = t
    manager.observe_return_pose(stamp_ns=round(t*1e9), source_now_ns=round(t*1e9),
                                frame='odom', x=0., y=y, yaw=yaw, received_at=t)
    containment = LaneContainmentEvidence.model_validate(dict(
        stamp=t, geometry_id='lane-rig', ground_source='CALIBRATED', uncertainty_m=uncertainty,
        boundaries=[dict(side=side, slope=-math.tan(yaw), intercept_m=(edge-y)/math.cos(yaw), observed_x_min_m=0.,
                         observed_x_max_m=.4) for side, edge in (('left', edge), ('right', -edge))]))
    manager.observe(LineObservation(LineFollowMode.CAMERA_LINE, t, True, 0., .9, containment=containment),
                    received_at=t, source_now=t)
    return manager.tick(t)


def test_centred_pinky_in_very_narrow_lane_is_contained_and_checkpointed():
    r = rig()
    for t in (1., 1.05, 1.1, 1.15):
        assert frame(r, t).linear > 0
    assert not r[1].status().reason.startswith('lane_return')
    assert r[1]._return_controller.checkpoint is not None


def test_contained_tracking_holds_through_heading_and_offset_jitter():
    # +/-1 deg and +/-1 mm: the eroded margin goes negative (about -0.6 mm at 1 deg) but
    # every corner stays geometrically inside, so following must not flap.
    r = rig()
    for t in (1., 1.05, 1.1):
        assert frame(r, t).linear > 0
    deg = math.radians(1)
    for step in range(1, 21):
        sign = 1 if step % 2 else -1
        assert frame(r, 1.1+step*.05, y=sign*.001, yaw=sign*deg).linear > 0
    assert not r[1].status().reason.startswith('lane_return')


def test_contained_tracking_departs_when_a_corner_crosses_the_estimated_line():
    r = rig()
    for t in (1., 1.05, 1.1):
        assert frame(r, t).linear > 0
    assert frame(r, 1.15, y=.004).linear > 0    # 1 mm geometric margin, eroded negative
    action = frame(r, 1.2, y=.006)               # corner 1 mm over the estimated line
    assert action.linear == action.angular == 0
    assert r[1].status().reason == 'lane_return_containment_unconfirmed'


def test_jittered_first_frame_does_not_enter_containment():
    # Entry needs the eroded margin; geometrically inside is unknown, not a departure (D-507 7).
    r = rig()
    assert frame(r, 1., yaw=math.radians(1)).linear > 0
    assert r[1].status().lane_return_containment == 'unknown'
    assert r[1]._return_controller.checkpoint is None


def test_body_corner_outside_very_narrow_lane_is_not_contained():
    r = rig()
    action = frame(r, 1., y=.008)   # 3 mm of the body past the boundary
    assert action.linear == action.angular == 0
    assert r[1].status().reason == 'lane_return_containment_unconfirmed'


def test_uncertainty_larger_than_raw_margin_is_not_contained():
    r = rig()
    action = frame(r, 1., uncertainty=.006)   # 5 mm geometric margin, 6 mm projection error
    assert action.linear > 0   # unproven, not departed (D-507 7)
    assert r[1].status().lane_return_containment == 'unknown'


def test_required_body_clearance_parameter_is_applied():
    r = rig(lane_return_body_margin_m=.002)   # eroded centred margin is only .00075
    for t in (1., 1.05, 1.1, 1.15):
        assert frame(r, t).linear > 0
    assert r[1].status().lane_return_containment == 'unknown'
    assert r[1]._return_controller.checkpoint is None


def test_off_keeps_legacy_following_even_when_body_is_outside():
    r = rig(recovery_local_enabled=False)
    for t in (1., 1.05):
        assert frame(r, t, y=.008).linear > 0
    assert r[1]._return_controller is None


BODY = Footprint(FRONT, REAR, HALF)


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
    assert tick(ReturnController(body), 1., lane).reason == 'containment_unknown'
    assert tick(ReturnController(body), 1., lane, linear_limit=0.).reason == 'contained'


def test_off_centre_contained_pose_is_not_a_normal_checkpoint():
    lane = Corridor(Boundary(0, VERY_NARROW_EDGE-.004), Boundary(0, -VERY_NARROW_EDGE-.004), 'very-narrow')
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


def test_260919_play_is_the_stl_inner_width_less_the_urdf_footprint():
    assert 2*TRACK_260919_EDGE == pytest.approx(.160) and 2*HALF == pytest.approx(.1131)
    assert TRACK_260919_PLAY == pytest.approx(.02345)


@pytest.mark.parametrize('uncertainty', [.0043, LaneReturnEvidence.MAX_UNCERTAINTY_M])
def test_centred_pinky_on_the_260919_lane_is_contained_and_checkpointed(uncertainty):
    # Sim 4.3 mm and the receiver's 15 mm cap both leave a positive eroded margin.
    r = rig()
    for t in (1., 1.05, 1.1, 1.15):
        assert frame(r, t, uncertainty=uncertainty, edge=TRACK_260919_EDGE).linear > 0
    assert not r[1].status().reason.startswith('lane_return')
    assert r[1]._return_controller.checkpoint is not None


@pytest.mark.parametrize('uncertainty', [.0235, .03])
def test_uncertainty_at_least_the_260919_play_is_not_contained(uncertainty):
    lane = Corridor(Boundary(0, TRACK_260919_EDGE-uncertainty), Boundary(0, -TRACK_260919_EDGE+uncertainty),
                    'track-260919', uncertainty)
    ctl = ReturnController(BODY)
    assert tick(ctl, 1., lane).reason == 'containment_unknown'   # D-507 7: not a departure
    assert ctl.checkpoint is None
    # Through the receiver: above MAX_UNCERTAINTY_M there is no corridor, so following goes on.
    r = rig()
    assert frame(r, 1., uncertainty=uncertainty, edge=TRACK_260919_EDGE).linear > 0
    assert r[1].status().lane_return_containment == 'unknown'
