"""D-468 real manager arbitration; no ROS or physical motion in this test."""
import pytest
import math
from core_common.robot_body import ScanView
from core_features.line_follow.manager import LineFollowManager
from core_features.line_follow.model import LineFollowConfig, LineFollowMode, LineObservation
from core_common.protocol.lane_containment import LaneContainmentEvidence


class Bus:
    def __init__(self): self.events=[]
    def publish(self,event,**kwargs): self.events.append(event)


def rig(probe=lambda now,v,w: True, **config):
    clock=[1.]
    bus=Bus()
    manager=LineFollowManager(bus,clock=lambda:clock[0],config=LineFollowConfig(
        body_front_x_m=.08,body_rear_x_m=-.08,body_half_width_m=.06,
        cruise_speed=.04,max_linear=.04,**{"recovery_local_enabled":True,**config}))
    manager.bind_recovery(calibration_active=lambda:False,linear_ceiling=lambda:.04)
    manager.bind_return_motion(probe)
    manager.set_mode(LineFollowMode.CAMERA_LINE)
    return clock,bus,manager


def frame(r,t,y=0.,uncertainty=.001,ground='CALIBRATED',x=0.,yaw=0.):
    clock,_,manager=r
    clock[0]=t
    manager.observe_return_pose(stamp_ns=round(t*1e9),source_now_ns=round(t*1e9),
        frame='odom',x=x,y=y,yaw=yaw,received_at=t)
    containment=LaneContainmentEvidence.model_validate(dict(stamp=t,geometry_id='rig-a',
        ground_source=ground,uncertainty_m=uncertainty,boundaries=[dict(side=side,
        slope=-math.tan(yaw),intercept_m=(edge-y)/math.cos(yaw),observed_x_min_m=0.,observed_x_max_m=.4)
        for side,edge in (('left',.1),('right',-.1))]))
    manager.observe(LineObservation(LineFollowMode.CAMERA_LINE,t,True,0.,.9,
        ground='NOMINAL' if ground=='NOMINAL' else None,containment=containment),received_at=t,source_now=t)
    return manager.tick(t)


def scan_view(*points):
    return ScanView(tuple(points),(),.03)


def test_departure_blocks_normal_forward_before_attempting_local_return():
    r=rig()
    for t in (1.,1.05,1.1): assert frame(r,t).linear>0
    # Measured sideways drift; the body corner crosses the estimated line at y > .04 (step 9).
    for step in range(1,9): assert frame(r,1.1+step*.05,step*.0047).linear>0
    action=frame(r,1.55,9*.0047)
    assert action.linear == action.angular == 0
    assert r[2].status().reason == 'lane_return_containment_unconfirmed'
    assert 'nav.line_stuck_opened' not in r[1].events


def test_no_checkpoint_approach_is_a_fenced_manager_decision():
    r=rig()
    assert frame(r,1.,.055).linear==0
    action=frame(r,1.05,.055)
    assert action.linear>0 and action.angular<0
    assert action.mode is LineFollowMode.CAMERA_LINE
    r[2].stop()
    assert not r[2].apply_if_current(action,lambda decision:pytest.fail('old motion applied'))
    assert r[2].tick(1.1).linear == 0


@pytest.mark.parametrize('probe',[None,lambda now,v,w:False,lambda now,v,w:1])
def test_unbound_denied_or_nonboolean_motion_proof_never_moves(probe):
    r=rig()
    if probe is None: r[2]._return_motion=None
    else: r[2].bind_return_motion(probe)
    frame(r,1.,.055)
    action=frame(r,1.05,.055)
    assert action.linear==action.angular==0
    assert 'nav.line_stuck_opened' not in r[1].events


def test_actual_curved_candidate_is_checked_after_straight_space_probes():
    r=rig(lambda now,v,w: not(v and w))
    frame(r,1.,.055)
    action=frame(r,1.05,.055)
    assert action.linear==action.angular==0
    assert r[2].status().reason=='lane_return_motion_unconfirmed'


def test_local_return_requires_fresh_body_clearance_for_each_motion_candidate():
    _,_,manager=rig(body_lidar_x_m=0.,body_rotation_radius_m=.1)
    manager.observe_return_scan(scan_view((.6, .4)),source_age_s=0.,source_stamp_ns=1_000_000_000,received_at=1.)
    assert manager.return_body_clear(1.1,.03,0.)
    assert not manager.return_body_clear(1.51,.03,0.)
    manager.observe_return_scan(scan_view((.10, 0.)),source_age_s=0.,source_stamp_ns=1_520_000_000,received_at=1.52)
    assert not manager.return_body_clear(1.53,.03,0.)


def test_local_return_checks_reverse_in_the_rear_body_frame():
    _,_,manager=rig(body_lidar_x_m=0.,body_rotation_radius_m=.1)
    manager.observe_return_scan(scan_view((-.6, .4)),source_age_s=0.,source_stamp_ns=1_000_000_000,received_at=1.)
    assert manager.return_body_clear(1.1,-.03,0.)
    manager.observe_return_scan(scan_view((-.10, 0.)),source_age_s=0.,source_stamp_ns=1_110_000_000,received_at=1.11)
    assert not manager.return_body_clear(1.12,-.03,0.)


def test_local_return_clearance_covers_motion_since_the_measured_scan():
    _,_,manager=rig(body_lidar_x_m=0.,body_rotation_radius_m=.1)
    manager.observe_return_scan(scan_view((.5, 0.)),source_age_s=0.,source_stamp_ns=1_000_000_000,received_at=1.)
    assert manager.return_body_clear(1.1,.03,0.)
    assert not manager.return_body_clear(1.5,.03,0.)


def test_replayed_scan_stamp_cannot_refresh_receipt_age():
    _,_,manager=rig(body_lidar_x_m=0.,body_rotation_radius_m=.1)
    view=scan_view((.6,.4))
    manager.observe_return_scan(view,source_age_s=0.,source_stamp_ns=1_000_000_000,received_at=1.)
    manager.observe_return_scan(view,source_age_s=0.,source_stamp_ns=1_000_000_000,received_at=9.)
    assert not manager.return_body_clear(9.1,.03,0.)


def test_unknown_projection_follows_like_recovery_off_without_d468_motion():
    # D-507 7: recovery_local_enabled on (robot default) with uncertainty unknown is not a
    # departure. Following matches recovery off; D-468 neither stops nor moves the robot.
    on,off=rig(lambda now,v,w:False),rig(lambda now,v,w:False,recovery_local_enabled=False)
    for t in (1.,1.05,1.1):
        a,b=frame(on,t,y=.01,uncertainty=None),frame(off,t,y=.01,uncertainty=None)
        assert (a.linear,a.angular)==(b.linear,b.angular) and a.linear>0
    status=on[2].status()
    assert status.state=='TRACKING' and status.lane_return_containment=='unknown'
    assert on[2]._return_controller.checkpoint is None
    assert off[2].status().lane_return_containment is None


def test_missing_body_geometry_follows_like_recovery_off():
    clock=[1.]
    manager=LineFollowManager(Bus(),clock=lambda:clock[0],config=LineFollowConfig(
        cruise_speed=.04,max_linear=.04,recovery_local_enabled=True))
    manager.bind_recovery(calibration_active=lambda:False,linear_ceiling=lambda:.04)
    manager.bind_return_motion(lambda now,v,w:True)
    manager.set_mode(LineFollowMode.CAMERA_LINE)
    assert frame((clock,None,manager),1.).linear>0
    assert manager.status().lane_return_containment=='unknown'


def test_nominal_without_driver_and_expired_driver_stay_zero():
    r=rig()
    frame(r,1.,.055,ground='NOMINAL')
    assert frame(r,1.05,.055,ground='NOMINAL').linear==0
    r[2].set_mode(LineFollowMode.CAMERA_LINE,hold_s=.1)
    frame(r,1.1,.055)
    assert frame(r,1.3,.055).linear==0
    assert r[2].mode is LineFollowMode.OFF


def test_local_exhaustion_opens_existing_stuck_only_as_last_resort():
    r=rig(lambda now,v,w: v==0,body_lidar_x_m=0.,body_rotation_radius_m=.1)
    for step in range(101):
        now=1.+step*.05
        r[2].observe_body_points(((.6,.6),),range_min=.03,received_at=now)
        frame(r,now,.055)
    assert 'nav.line_stuck_opened' in r[1].events
    stuck=r[2].status().stuck
    assert stuck is not None
    assert r[2].status().linear==r[2].status().angular==0
    assert r[2]._recovery._last.geometry_known
    assert r[2].stuck_decision(stuck.stuck_id,'YIELD',by='operator',now=6.1,
                               yield_m=.1,yield_turn_rad=0.)=='yield'
    r[2].observe_body_points(((.6,.6),),range_min=.03,received_at=6.15)
    action=frame(r,6.15,.055)
    assert action.linear>0 and action.angular==0


def test_new_pose_and_expired_space_reject_precomputed_return_command():
    r=rig()
    frame(r,1.,.055)
    action=frame(r,1.05,.055)
    r[2].invalidate_return_pose()
    assert not r[2].apply_if_current(action,lambda d:pytest.fail('reset pose command applied'))
    frame(r,1.1,.055)
    action=frame(r,1.15,.055)
    # The same provider can revoke its evidence between compute and submit.
    permit=[True]
    r[2].bind_return_motion(lambda now,v,w:permit[0])
    action=frame(r,1.2,.055)
    permit[0]=False
    assert not r[2].apply_if_current(action,lambda d:pytest.fail('expired space command applied'))


def test_manager_closes_measured_approach_then_resumes_following():
    r=rig()
    x,y,yaw=0.,.055,0.
    recovered=False
    for step in range(241):
        now=1.+step*.05
        action=frame(r,now,y,x=x,yaw=yaw)
        if r[2].status().reason=='lane_return_corridor_verified':
            recovered=True
            break
        assert 'nav.line_stuck_opened' not in r[1].events
        x+=action.linear*math.cos(yaw)*.05
        y+=action.linear*math.sin(yaw)*.05
        yaw+=action.angular*.05
    assert recovered
    assert frame(r,now+.05,y,x=x,yaw=yaw).linear>0


def test_invisible_camera_keeps_local_sensor_search_instead_of_asking_fleet_first():
    r=rig()
    frame(r,1.,.055)
    r[0][0]=1.05
    r[2].observe_return_pose(stamp_ns=1_050_000_000,source_now_ns=1_050_000_000,
        frame='odom',x=0.,y=.055,yaw=0.,received_at=1.05)
    r[2].invalidate(received_at=1.05)
    action=r[2].tick(1.05)
    assert action.linear==0 and action.angular!=0
    assert 'nav.line_stuck_opened' not in r[1].events


def test_recovery_session_off_requires_new_checkpoint_and_evidence():
    r=rig()
    for t in (1.,1.05,1.1): frame(r,t)
    assert r[2]._return_controller.checkpoint is not None
    r[2].stop()
    r[2].set_mode(LineFollowMode.CAMERA_LINE)
    assert r[2]._return_controller is None
    assert r[2].return_evidence(now=1.1).pose is None


def test_provider_failure_and_nonfinite_live_ceiling_cannot_drive():
    def fail(*args): raise RuntimeError('sensor unavailable')
    r=rig(fail)
    frame(r,1.,.055)
    assert frame(r,1.05,.055).linear==0
    r[2].bind_return_motion(lambda *args:True)
    r[2].bind_recovery(linear_ceiling=lambda:float('nan'))
    action=frame(r,1.1,.055)
    assert action.linear==action.angular==0


@pytest.mark.parametrize('expired',['driver','pose','ceiling','calibration'])
def test_submission_rechecks_live_authority_and_pose_without_another_tick(expired):
    r=rig()
    if expired=='driver': r[2].set_mode(LineFollowMode.CAMERA_LINE,hold_s=.1)
    frame(r,1.,.055,ground='NOMINAL' if expired=='driver' else 'CALIBRATED')
    action=frame(r,1.05,.055,ground='NOMINAL' if expired=='driver' else 'CALIBRATED')
    assert action.linear>0
    if expired=='driver': r[0][0]=1.2
    elif expired=='pose': r[0][0]=1.4
    elif expired=='ceiling': r[2].bind_recovery(linear_ceiling=lambda:0.)
    else: r[2].bind_recovery(calibration_active=lambda:True)
    assert not r[2].apply_if_current(action,lambda d:pytest.fail('expired authority applied'))


def test_console_resume_clears_exhausted_local_sequence_after_real_centered_frames():
    r=rig(lambda now,v,w:v==0)
    for step in range(101): frame(r,1.+step*.05,.055)
    for step in range(1,12): frame(r,6.+step*.05,.055-step*.005)
    stuck=r[2].status().stuck
    assert stuck is not None
    assert r[2].stuck_decision(stuck.stuck_id,'RESUME',by='test',now=6.55)=='resume'
    r[2].bind_return_motion(lambda now,v,w:True)
    for t in (6.6,6.65,6.7):
        action=frame(r,t)
        assert action.linear==action.angular==0
        assert r[2].status().stuck is None
    action=frame(r,6.75)
    assert action.linear>0
    assert r[2].status().stuck is None


def test_zero_live_translation_ceiling_also_revokes_precomputed_search_turn():
    r=rig()
    frame(r,1.,.055)
    r[0][0]=1.05
    r[2].observe_return_pose(stamp_ns=1_050_000_000,source_now_ns=1_050_000_000,
        frame='odom',x=0.,y=.055,yaw=0.,received_at=1.05)
    r[2].invalidate(received_at=1.05)
    action=r[2].tick(1.05)
    assert action.linear==0 and action.angular!=0
    r[2].bind_recovery(linear_ceiling=lambda:0.)
    assert not r[2].apply_if_current(action,lambda d:pytest.fail('revoked search turn applied'))
