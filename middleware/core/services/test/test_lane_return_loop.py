"""D-468 synthetic planar closed loop: outputs move measured pose, not elapsed distance."""
import math

from core_features.line_follow.lane_return import (
    Boundary, Corridor, Footprint, Pose, ReturnController, ReturnInput,
)

BODY = Footprint(.08, -.08, .06)


def inputs(t, x=0., y=0., yaw=0., **changes):
    # Actual straight painted world edges y=+/- .10, observed in the current body frame.
    c = math.cos(yaw)
    corridor = Corridor(Boundary(-math.tan(yaw),(.10-y)/c),
                        Boundary(-math.tan(yaw),(-.10-y)/c),"rig-a")
    raw = dict(now=t, pose=Pose(t,round(t*1e9),"odom",x,y,yaw), corridor=corridor,
        corridor_at=t, corridor_stamp_ns=round(t*1e9), clearance_at=t, floor_safe=True,
        front_clear=True,rear_clear=True,turn_clear=True,authorized=True,
        linear_limit=.04,angular_limit=.3)
    raw.update(changes)
    return ReturnInput(**raw)


def advance(state, action, dt=.05, slip=1.):
    x,y,yaw = state
    v,w = action.linear*slip,action.angular*slip
    return x+v*math.cos(yaw)*dt,y+v*math.sin(yaw)*dt,yaw+w*dt


def test_no_checkpoint_recovers_current_lane_with_measured_low_speed_approach():
    ctl = ReturnController(BODY)
    state = (0.,.055,0.)
    phases = set()
    for step in range(241):
        t = 1.+step*.05
        action = ctl.tick(inputs(t,*state))
        phases.add(action.phase)
        assert abs(action.linear) <= .04 and abs(action.angular) <= .3
        if action.recovered:
            assert inputs(t,*state).corridor.margin(BODY) >= .015
            assert abs(state[2]) <= .12
            break
        assert not action.fleet_required
        state = advance(state,action)
    else:
        raise AssertionError(f"local recovery failed; phases={phases}, state={state}")
    assert 'approach' in phases
    assert 'verify' in phases


def test_approach_does_not_report_recovery_when_wheels_do_not_move():
    ctl = ReturnController(BODY)
    phases = set()
    for step in range(100):
        t=1.+step*.05
        action=ctl.tick(inputs(t,0.,.055,0.))
        phases.add(action.phase)
        assert not action.recovered
    assert 'approach' in phases
    assert 'search' in phases or action.fleet_required


def test_missing_front_space_forbids_approach_but_allows_proven_in_place_search():
    ctl=ReturnController(BODY)
    ctl.tick(inputs(1.,0.,.055,0.,front_clear=False))
    action=ctl.tick(inputs(1.1,0.,.055,0.,front_clear=False))
    assert action.linear == 0
    assert action.phase == 'search'


def test_current_corridor_recovery_tolerates_measured_slip_but_remains_bounded():
    ctl=ReturnController(BODY)
    state=(0.,.045,0.)
    for step in range(241):
        t=1.+step*.05
        action=ctl.tick(inputs(t,*state))
        if action.recovered: break
        assert not action.fleet_required
        state=advance(state,action,slip=.8)
    else: raise AssertionError('slip case did not recover within local deadline')


def test_checkpoint_path_retrace_and_heading_reacquisition_close_the_loop():
    ctl=ReturnController(BODY)
    for t in (1.,1.1,1.2): ctl.tick(inputs(t))
    state=(0.,0.,0.)
    triggered=False
    for step in range(1,80):
        t=1.2+step*.05
        # A continuous steering disturbance, not an odometry frame jump.
        state=advance(state,type('ExternalDrift',(),dict(
            linear=.04,angular=.3 if step<=17 else 0.))())
        action=ctl.tick(inputs(t,*state))
        if action.phase=='departure_stop':
            triggered=True
            break
    assert triggered
    phases=set()
    for step in range(1,241):
        now=t+step*.05
        action=ctl.tick(inputs(now,*state))
        phases.add(action.phase)
        if action.recovered: break
        state=advance(state,action)
    else: raise AssertionError(f'path return failed: phases={phases}, state={state}')
    assert 'retrace' in phases
    assert inputs(now,*state).corridor.margin(BODY)>=.015


def test_checkpoint_stays_at_a_normal_pose_before_boundary_invasion():
    ctl=ReturnController(BODY)
    for t in (1.,1.1,1.2): ctl.tick(inputs(t))
    home=ctl.checkpoint
    for step in range(1,11):
        ctl.tick(inputs(1.2+step*.05,0.,step*.002,0.))
    # Normal = at most half of the .04 m lateral play used (D-468 implementation note).
    assert ctl.checkpoint[0].y <= .02+1e-9
    assert ctl.checkpoint[1].margin(BODY) >= .02-1e-9
    assert home is not None


def test_running_approach_immediately_yields_zero_when_proof_expires():
    for missing in ('floor_safe','authorized','clearance_at','pose'):
        ctl=ReturnController(BODY)
        ctl.tick(inputs(1.,0.,.055))
        moving=ctl.tick(inputs(1.05,0.,.055))
        assert moving.linear > 0
        value=None if missing in ('clearance_at','pose') else False
        held=ctl.tick(inputs(1.1,0.,.055,**{missing:value}))
        assert held.linear == held.angular == 0
        assert not held.recovered


def test_fleet_is_requested_only_after_local_search_candidates():
    ctl=ReturnController(BODY)
    state=(0.,.055,0.)
    directions=set()
    for step in range(200):
        action=ctl.tick(inputs(1.+step*.05,*state,front_clear=False))
        if action.fleet_required: break
        if action.angular: directions.add(math.copysign(1,action.angular))
        state=advance(state,action)
    else: raise AssertionError('exhausted candidates never requested Fleet')
    assert directions == {-1.,1.}
    assert action.linear == action.angular == 0


def test_verified_near_boundary_pose_does_not_become_normal_checkpoint():
    ctl=ReturnController(BODY)
    ctl.tick(inputs(1.,0.,.055))
    for t in (1.05,1.1,1.15):
        action=ctl.tick(inputs(t,0.,.03))  # contained, but 3/4 of the lateral play used
    assert action.recovered
    assert ctl.checkpoint is None
    for t in (1.2,1.25,1.3): ctl.tick(inputs(t))
    assert ctl.checkpoint is not None
    assert ctl.checkpoint[1].margin(BODY) >= .02
