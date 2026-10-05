import math

import pytest

from core_common.robot_body import RobotBody
from core_features.line_follow.clearance import return_scan_view

BODY=RobotBody(front_x_m=.08,rear_x_m=-.08,half_width_m=.06,
    rotation_radius_m=.1,lidar_x_m=0.,lidar_forward_deg=180.)


def scan(values=None, **changes):
    count=360
    inc=2*math.pi/count
    sample=dict(ranges=[1.5]*count if values is None else values,
        angle_min=-math.pi,angle_max=-math.pi+inc*(count-1),angle_increment=inc,
        range_min=.03,range_max=2.,frame_id='laser',source_stamp_ns=1_000_000_000)
    sample.update(changes)
    return sample


def test_full_finite_scan_provides_measured_obstacle_points():
    evidence=return_scan_view(scan(),body=BODY,source_now_ns=1_000_000_000,
                              clearance_horizon_m=.5)
    assert evidence is not None
    view,age,_=evidence
    assert len(view.points)==360 and not view.unknown and age==0.


def test_infinity_stays_unknown_and_cannot_support_rotation():
    sample=scan([math.inf]*360) | {'range_min':.3}
    evidence=return_scan_view(sample,body=BODY,source_now_ns=1_000_000_000,
                              clearance_horizon_m=.5)
    assert evidence is not None
    view,_,_=evidence
    assert not view.points and len(view.unknown)==360
    assert BODY.rotation_reason(view) is not None


def test_single_no_return_beam_is_unknown_for_turn_and_forward_sweep():
    values=[1.5]*360
    values[0]=math.inf
    evidence=return_scan_view(scan(values) | {'range_min':.3},body=BODY,source_now_ns=1_000_000_000,
                              clearance_horizon_m=.5)
    assert evidence is not None
    view,_,_=evidence
    assert view.unknown
    assert BODY.rotation_reason(view) is not None
    assert BODY.unknown_blocks(view)


@pytest.mark.parametrize('sample',[
    scan([math.nan]+[1.5]*359),
    scan([True]+[math.inf]*359),
    scan() | {'angle_max':0.0},
    scan() | {'angle_increment':math.radians(2)},
    scan() | {'range_max':.2},
    scan() | {'frame_id':''},
])
def test_incomplete_or_unusable_scan_cannot_prove_open_space(sample):
    assert return_scan_view(sample,body=BODY,source_now_ns=1_000_000_000,
                             clearance_horizon_m=.5) is None


def test_self_mask_disables_swept_space_claims():
    assert return_scan_view(scan(),body=BODY,source_now_ns=1_000_000_000,
        clearance_horizon_m=.5,self_mask=((-10.,10.,.2),)) is None


def test_old_or_replayed_source_timestamp_cannot_refresh_scan_evidence():
    sample=scan(source_stamp_ns=500_000_000)
    assert return_scan_view(sample,body=BODY,source_now_ns=1_000_000_000,
                            clearance_horizon_m=.5) is None
