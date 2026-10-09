"""D-494 decision 4 / D-495: the junction instruction gate and bounded turn in the real
line-follow manager (no ROS, no physical motion)."""
import math

import collections

import pytest

from core_common.protocol.lane_containment import LaneContainmentEvidence
from core_features.line_follow.recovery.junction.gate import JunctionRefused
from core_features.line_follow.manager import LineFollowManager
from core_features.line_follow.model import LineFollowConfig, LineFollowMode, LineObservation

CAMERA = LineFollowMode.CAMERA_LINE
BODY = dict(body_front_x_m=.08, body_rear_x_m=-.08, body_half_width_m=.06,
            body_lidar_x_m=0., body_rotation_radius_m=.1)


class Bus:
    def publish(self, event, **kwargs): pass


class Rig:
    """The robot integrates its own commanded twist into odom when `move` is on."""

    def __init__(self, proof=True, **config):
        self.now, self.x, self.y, self.yaw = 1., 0., 0., 0.
        self.v = self.w = 0.
        self.calibrating = False
        self.odom_lead_ns = 0  # odom source stamp ahead of CORE's source clock
        self.m = LineFollowManager(Bus(), clock=lambda: self.now, config=LineFollowConfig(**config))
        self.m.bind_recovery(calibration_active=lambda: self.calibrating, linear_ceiling=lambda: .1)
        if proof:
            self.m.bind_return_motion(lambda now, v, w: True, proof_configured=lambda: True)
        self.m.set_mode(CAMERA)

    def step(self, *, junction=False, pose=True, dx=0., seen=True, move=False, points=None,
             slope=None):
        self.now = round(self.now + .05, 6)
        if move:
            self.yaw += self.w * .05
            self.x += self.v * math.cos(self.yaw) * .05
            self.y += self.v * math.sin(self.yaw) * .05
        self.x += dx
        if pose:
            stamp = round(self.now * 1e9)
            self.m.observe_return_pose(stamp_ns=stamp+self.odom_lead_ns, source_now_ns=stamp, frame='odom',
                                       x=self.x, y=self.y, yaw=self.yaw, received_at=self.now)
        if points is not None:
            self.m.observe_scan_points(points, received_at=self.now)
        containment = None if slope is None else LaneContainmentEvidence(
            stamp=self.now, geometry_id='rig', ground_source='GAZEBO', uncertainty_m=.005,
            boundaries=[dict(side='left', slope=slope, intercept_m=.09, observed_x_min_m=0.,
                             observed_x_max_m=.3)])
        self.m.observe(LineObservation(CAMERA, self.now, seen, 0. if seen else None,
                                       .9 if seen else 0., containment=containment),
                       received_at=self.now)
        if junction:
            self.m.observe_junction('junction_fork', self.now)
        decision = self.m.tick(self.now)
        self.v, self.w = decision.linear, decision.angular
        return decision, self.m.status()

    def send(self, action, expires_s=10., stop_after_m=None, turn_deg=None, advance_m=None):
        return self.m.set_junction(action, 'J1', expires_s, stop_after_m, turn_deg, advance_m)

    def turn_until(self, state, limit=400, **kwargs):
        for _ in range(limit):
            decision, status = self.step(move=True, **kwargs)
            if status.junction.state != state:
                return decision, status
        raise AssertionError(f'still {state}')


def test_idle_tracks_and_reports_idle():
    rig = Rig()
    decision, status = rig.step()
    assert decision.linear > 0 and status.state == 'TRACKING'
    assert status.junction.model_dump() == dict(pending_action=None, place_id=None, state='idle',
                                                seq=0, turn_deg=None, reason=None, pivot_basis=None)


def test_no_instruction_at_a_junction_waits_and_latches():
    rig = Rig()
    decision, status = rig.step(junction=True)
    assert (decision.linear, decision.angular) == (0., 0.)
    assert (status.state, status.reason, status.junction.state) == ('HOLD', 'junction_waiting', 'waiting')
    rig.now += 1.  # the sighting goes stale: still latched
    decision, status = rig.step()
    assert decision.linear == 0. and status.junction.state == 'waiting'


def test_straight_arms_executes_and_clears_after_the_junction():
    rig = Rig()
    assert rig.send('straight') == (True, 1, 'armed')
    assert rig.m._bridge_hint == 'straight'
    decision, status = rig.step()
    assert decision.linear > 0 and status.junction.state == 'armed'
    assert status.junction.pending_action == 'straight' and status.junction.place_id == 'J1'
    decision, status = rig.step(junction=True)
    assert decision.linear > 0 and status.junction.state == 'executing'
    rig.now += 1.
    decision, status = rig.step()
    assert decision.linear > 0 and status.junction.state == 'idle' and status.junction.seq == 1
    assert rig.m._bridge_hint is None


def test_expired_instruction_at_a_junction_waits():
    rig = Rig()
    rig.send('straight', expires_s=.5)
    rig.now += 1.
    decision, status = rig.step(junction=True)
    assert decision.linear == 0. and status.reason == 'junction_waiting'
    assert status.junction.pending_action is None and rig.m._bridge_hint is None


def test_expired_instruction_without_a_junction_is_dropped():
    rig = Rig()
    rig.send('straight', expires_s=.5)
    rig.now += 1.
    decision, status = rig.step()
    assert decision.linear > 0 and status.junction.state == 'idle'


@pytest.mark.parametrize('action', ['left', 'right'])
def test_left_and_right_without_turn_deg_are_unresolved_and_hold_at_once(action):
    rig = Rig()
    assert rig.send(action) == (True, 1, 'unresolved')
    decision, status = rig.step()
    assert (decision.linear, decision.angular) == (0., 0.)
    assert (status.state, status.reason, status.junction.state) == ('HOLD', 'junction_unresolved', 'unresolved')
    assert rig.m._bridge_hint == action


def test_stop_zero_holds_at_once_until_the_next_instruction():
    rig = Rig()
    assert rig.send('stop') == (True, 1, 'executing')
    decision, status = rig.step()
    assert decision.linear == 0. and status.reason == 'junction_stop'
    rig.send('straight')
    decision, status = rig.step()
    assert decision.linear > 0 and status.junction.seq == 2


def test_stop_after_m_drives_the_measured_distance_then_holds():
    rig = Rig()
    rig.step()
    rig.send('stop', stop_after_m=.09)
    moving = [rig.step(dx=.02)[0].linear > 0 for _ in range(6)]
    assert moving == [True] * 5 + [False]  # 0, .02, .04, .06, .08 then .10 >= .09
    rig.step(dx=0.)
    assert rig.m.status().reason == 'junction_stop'


def test_stop_after_m_holds_when_odom_jumps():
    rig = Rig()
    rig.step()
    rig.send('stop', stop_after_m=.5)
    assert rig.step(dx=.01)[0].linear > 0
    decision, status = rig.step(dx=.2)  # PoseTrail drops the jump: distance unknown
    assert decision.linear == 0. and status.reason == 'junction_stop'


def test_stop_after_m_without_fresh_odom_holds_at_once():
    rig = Rig()
    rig.send('stop', stop_after_m=.5)
    decision, status = rig.step(pose=False)
    assert decision.linear == 0. and status.reason == 'junction_stop'


def test_refused_unless_camera_or_ir_line_and_cleared_by_mode_change():
    rig = Rig()
    rig.send('left')
    rig.m.set_mode(LineFollowMode.OFF)
    assert rig.m.status().junction.state == 'idle'
    with pytest.raises(JunctionRefused) as refused:
        rig.send('straight')
    assert refused.value.code == 'LINE_FOLLOW_NOT_ACTIVE'


@pytest.mark.parametrize('args', [
    ('north', 5., None, None, None), ('stop', 31., None, None, None), ('stop', 0., None, None, None),
    ('straight', 5., .2, None, None), ('stop', 5., 2.5, None, None),
    ('left', 5., None, -90., None), ('right', 5., None, 90., None), ('left', 5., None, 151., None),
    ('left', 5., None, 0., None), ('straight', 5., None, 10., None), ('left', 5., None, None, .1),
    ('left', 5., None, 90., .31), ('left', 5., None, math.nan, None)])
def test_invalid_instructions_raise(args):
    with pytest.raises(ValueError):
        Rig().m.set_junction(args[0], 'J1', args[1], *args[2:])


def test_only_junction_reasons_count_as_a_sighting():
    rig = Rig()
    rig.m.observe_junction('no_boundary', rig.now + .05)
    decision, status = rig.step()
    assert decision.linear > 0 and status.junction.state == 'idle'


# --- D-495 bounded turn -------------------------------------------------------------------

def _to_turning(rig, turn_deg=90., advance_m=None):
    rig.step()
    assert rig.send('left' if turn_deg > 0 else 'right', turn_deg=turn_deg,
                    advance_m=advance_m) == (True, 1, 'armed')
    decision, status = rig.step()  # armed: ordinary following until the junction
    assert decision.linear > 0 and status.junction.state == 'armed'
    decision, status = rig.step(junction=True, seen=False, move=True)
    assert status.junction.state == 'turning' and status.junction.turn_deg == turn_deg
    return decision, status


def _yaw_error_deg(yaw, turn_deg):
    e = yaw - math.radians(turn_deg)
    return math.degrees(math.atan2(math.sin(e), math.cos(e)))


def _reacquire(rig, frames=3, **kwargs):
    for _ in range(frames):
        decision, status = rig.step(seen=True, move=True, **kwargs)
    return decision, status


@pytest.mark.parametrize('turn_deg', [90., -90., 150., -30.])
def test_turn_advance_reacquire_completes(turn_deg):
    rig = Rig()
    decision, status = _to_turning(rig, turn_deg)
    assert (decision.linear, decision.angular) == (0., 0.)          # standing still first (L1)
    assert (status.state, status.reason) == ('RECOVERING', 'junction_stopping')
    for _ in range(8):
        decision, status = rig.step(seen=False, move=True)
        if decision.angular:
            break
    assert math.copysign(1, decision.angular) == math.copysign(1, turn_deg)
    assert abs(decision.angular) <= .7 and status.reason == 'junction_turning'
    decision, status = rig.turn_until('turning', seen=False)
    assert abs(_yaw_error_deg(rig.yaw, turn_deg)) <= 5.
    assert status.junction.state == 'advancing' and decision.angular == 0.
    assert 0 < decision.linear <= .05  # half of min(max_linear .10, manual ceiling .1)
    start = (rig.x, rig.y)
    decision, status = rig.turn_until('advancing', seen=False)
    assert status.junction.state == 'reacquiring' and decision.linear == 0.
    assert math.hypot(rig.x - start[0], rig.y - start[1]) == pytest.approx(.10, abs=.01)
    decision, status = rig.step(seen=True, move=True)
    decision, status = rig.step(seen=True, move=True)
    assert status.junction.state == 'reacquiring' and decision.linear > 0   # 2 of 3 frames
    decision, status = rig.step(seen=True, move=True)
    assert status.junction.state == 'idle' and decision.linear > 0 and status.state == 'TRACKING'
    assert rig.m._bridge_hint is None


def test_turn_completes_with_odom_stamps_1_ms_ahead_of_core_clock():
    """D-495 SIM finding 2: a 1 ms future stamp wiped the trail every sample (aborted odom)."""
    rig = Rig()
    rig.odom_lead_ns = 1_000_000
    _to_turning(rig, 90.)
    decision, status = rig.turn_until('turning', seen=False)
    assert status.junction.state == 'advancing' and abs(_yaw_error_deg(rig.yaw, 90.)) <= 5.


def test_turn_waits_for_the_robot_to_stand_still():
    rig = Rig()
    _to_turning(rig, 90.)
    for _ in range(10):
        decision, status = rig.step(seen=False, dx=.005)   # still creeping 0.1 m/s
        assert decision.angular == 0. and status.reason == 'junction_stopping'
    for _ in range(40):
        decision, status = rig.step(seen=False, dx=.005)
    assert (status.junction.state, status.junction.reason) == ('aborted', 'not_still')


def test_advance_of_the_full_030_m_completes():
    rig = Rig()
    _to_turning(rig, 90., advance_m=.30)
    rig.turn_until('turning', seen=False)
    start = (rig.x, rig.y)
    decision, status = rig.turn_until('advancing', seen=False)
    assert status.junction.state == 'reacquiring'
    assert math.hypot(rig.x - start[0], rig.y - start[1]) == pytest.approx(.30, abs=.01)


@pytest.mark.parametrize('turn_deg', [90., -150., 30.])
def test_turn_settles_inside_5_deg_under_actuation_and_odom_lag(turn_deg):
    """Review M6: 3 ticks (150 ms) of odom lag and a 0.15 s first-order wheel response."""
    rig = Rig()
    rig.send('left' if turn_deg > 0 else 'right', turn_deg=turn_deg)
    history, w_actual, states, yaw_at_advance = collections.deque(maxlen=4), 0., [], None
    for i in range(800):
        rig.now = round(rig.now + .05, 6)
        w_actual += (rig.w - w_actual) * (.05 / .15)
        rig.yaw += w_actual * .05
        rig.x += rig.v * math.cos(rig.yaw) * .05
        rig.y += rig.v * math.sin(rig.yaw) * .05
        history.append((rig.now, rig.x, rig.y, rig.yaw))
        if len(history) < 4:
            continue
        t, x, y, yaw = history[0]
        rig.m.observe_return_pose(stamp_ns=round(t * 1e9), source_now_ns=round(rig.now * 1e9),
                                  frame='odom', x=x, y=y, yaw=yaw, received_at=rig.now)
        rig.m.observe(LineObservation(CAMERA, rig.now, False, None, 0.), received_at=rig.now)
        if i < 8:
            rig.m.observe_junction('junction_fork', rig.now)
        decision = rig.m.tick(rig.now)
        rig.v, rig.w = decision.linear, decision.angular
        state = rig.m.status().junction.state
        if not states or states[-1] != state:
            states.append(state)
        if state == 'advancing' and yaw_at_advance is None:
            yaw_at_advance = rig.yaw
        if state in ('aborted', 'unresolved', 'reacquiring'):
            break
    assert states[:2] == ['turning', 'advancing'], (states, rig.m.status().junction.reason)
    assert abs(_yaw_error_deg(yaw_at_advance, turn_deg)) <= 5.


def test_reacquire_needs_consecutive_frames():
    rig = Rig()
    _to_turning(rig, 45., advance_m=0.)
    rig.turn_until('turning', seen=False)
    rig.step(seen=True, move=True)
    rig.step(seen=True, move=True)
    rig.step(seen=False, move=True)                          # the run breaks
    _reacquire(rig, frames=2)
    assert rig.m.status().junction.state == 'reacquiring'
    _reacquire(rig, frames=1)
    assert rig.m.status().junction.state == 'idle'


def test_reacquire_rejects_a_lane_heading_off_the_turn():
    rig = Rig()
    _to_turning(rig, 45., advance_m=0.)
    rig.turn_until('turning', seen=False)
    _reacquire(rig, frames=3, slope=1.0)                     # lane 45 deg off the turned heading
    assert rig.m.status().junction.state == 'reacquiring'
    _reacquire(rig, frames=3, slope=.1)                      # lane along the turn
    assert rig.m.status().junction.state == 'idle'


def test_advance_zero_goes_straight_to_reacquiring():
    rig = Rig()
    _to_turning(rig, 45., advance_m=0.)
    decision, status = rig.turn_until('turning', seen=False)
    assert status.junction.state == 'reacquiring' and decision.linear == 0.


def test_reacquire_fails_after_reacquire_m_without_lane():
    rig = Rig()
    _to_turning(rig, 45., advance_m=0.)
    rig.turn_until('turning', seen=False)
    for _ in range(11):  # the lane is not seen; the robot is pushed .019 m a tick (.209 m)
        decision, status = rig.step(seen=False, dx=.019)
    assert status.junction.state == 'unresolved' and decision.linear == 0.
    assert status.reason == 'junction_unresolved'


def test_reacquire_times_out_when_the_robot_cannot_move():
    rig = Rig()
    _to_turning(rig, 45., advance_m=0.)
    rig.turn_until('turning', seen=False)
    rig.m._junction['phase_at'] -= 5.1  # odom stays fresh and continuous
    decision, status = rig.step(seen=False)
    assert status.junction.state == 'unresolved'


def test_turn_times_out():
    rig = Rig()
    _to_turning(rig, 90.)
    for _ in range(8):
        rig.step(seen=False, move=True)
    rig.m._junction['phase_at'] -= 10.
    decision, status = rig.step(seen=False, move=True)
    assert (status.junction.state, status.junction.reason, decision.angular) == ('aborted', 'timeout', 0.)
    assert status.reason == 'junction_aborted'


def test_odom_stale_aborts():
    rig = Rig()
    _to_turning(rig, 90.)
    rig.now += .3  # the last odom sample is now older than 0.3 s
    decision, status = rig.step(seen=False, pose=False)
    assert (status.junction.state, status.junction.reason) == ('aborted', 'odom')
    assert (decision.linear, decision.angular) == (0., 0.)
    decision, status = rig.step(seen=True)
    assert decision.linear == 0. and status.junction.state == 'aborted'  # held until a new instruction


def test_odom_jump_aborts():
    rig = Rig()
    _to_turning(rig, 90.)
    decision, status = rig.step(seen=False, dx=.3)
    assert (status.junction.state, status.junction.reason, decision.angular) == ('aborted', 'odom', 0.)


def test_no_fresh_odom_at_the_junction_aborts_before_turning():
    rig = Rig()
    rig.step()
    rig.send('left', turn_deg=90.)
    rig.now += .3
    decision, status = rig.step(junction=True, pose=False)
    assert (status.junction.state, status.reason, decision.linear, decision.angular) == (
        'armed', 'junction_stopping', 0., 0.)                 # waits up to POSE_MAX_AGE_S
    waited_from = rig.now
    while status.junction.state == 'armed':
        decision, status = rig.step(junction=True, pose=False)
    assert (status.junction.state, status.junction.reason, decision.angular) == ('aborted', 'odom', 0.)
    assert .3 < rig.now - waited_from <= .35


def test_turn_armed_right_after_mode_select_waits_for_the_first_odom_sample():
    """D-495 SIM finding 3: PUT CAMERA_LINE empties the pose trail; a turn armed at a junction
    already in view must wait for the first odom sample, not abort 'odom'."""
    rig = Rig()                                               # set_mode: no odom sample yet
    assert rig.send('right', turn_deg=-90.) == (True, 1, 'armed')
    decision, status = rig.step(junction=True, seen=False, pose=False)
    assert (status.junction.state, status.state, status.reason) == ('armed', 'HOLD', 'junction_stopping')
    assert (decision.linear, decision.angular) == (0., 0.)
    decision, status = rig.step(junction=True, seen=False)    # first odom sample
    assert status.junction.state == 'turning' and status.reason == 'junction_stopping'
    decision, status = rig.turn_until('turning', seen=False)
    assert status.junction.state == 'advancing' and abs(_yaw_error_deg(rig.yaw, -90.)) <= 5.


def test_mode_change_and_estop_abort_and_the_next_session_starts_clean():
    rig = Rig()
    _to_turning(rig, 90.)
    rig.m.stop('estop')
    status = rig.m.status()
    assert (status.junction.state, status.junction.reason) == ('aborted', 'mode_change')
    rig.m.set_mode(CAMERA)
    assert rig.m.status().junction.state == 'idle'


def test_new_instruction_aborts_the_maneuver_and_is_not_accepted():
    rig = Rig()
    _to_turning(rig, 90.)
    assert rig.send('straight') == (False, 1, 'aborted')
    decision, status = rig.step(seen=False, move=True)
    assert (decision.linear, decision.angular) == (0., 0.)
    assert (status.junction.state, status.junction.reason) == ('aborted', 'new_instruction')
    assert rig.send('straight') == (True, 2, 'armed')


def test_identical_instruction_during_a_maneuver_is_a_no_op():
    rig = Rig()
    _to_turning(rig, 90.)
    assert rig.send('left', turn_deg=90.) == (True, 1, 'turning')
    assert rig.send('left', turn_deg=90., advance_m=.10) == (True, 1, 'turning')  # default spelled out
    assert rig.m.status().junction.state == 'turning'
    assert rig.send('left', turn_deg=80.) == (False, 1, 'aborted')


def test_calibration_lease_mid_turn_aborts():
    rig = Rig()
    _to_turning(rig, 90.)
    rig.calibrating = True
    decision, status = rig.step(seen=False, move=True)
    assert (status.junction.state, status.junction.reason, decision.angular) == (
        'aborted', 'calibration_active', 0.)


def test_unbound_motion_check_refuses_the_turn():
    rig = Rig(proof=False)
    rig.step()
    rig.send('left', turn_deg=90.)
    decision, status = rig.step(junction=True, seen=False)
    assert (status.junction.state, status.junction.reason) == ('aborted', 'motion_unconfirmed')


def test_d422_near_stop_aborts_the_turn():
    rig = Rig(**BODY)
    clear = [(1.5, 1.5)]
    rig.step(points=clear)
    rig.send('left', turn_deg=90.)
    for _ in range(10):
        decision, status = rig.step(junction=True, seen=False, move=True, points=clear)
        if decision.angular:
            break
    assert status.junction.state == 'turning' and decision.angular > 0
    decision, status = rig.step(seen=False, move=True, points=[(0., .105)])  # inside the swing
    assert (status.junction.state, status.junction.reason, decision.angular) == ('aborted', 'near_stop', 0.)


def test_motion_proof_refusal_aborts():
    rig = Rig()
    rig.m.bind_return_motion(lambda now, v, w: w == 0., proof_configured=lambda: True)
    _to_turning(rig, 90.)  # standing still passes the (0, 0) proof
    decision, status = rig.turn_until('turning', seen=False)
    assert decision.angular == 0.
    assert (status.junction.state, status.junction.reason) == ('aborted', 'motion_unconfirmed')


def test_driver_hold_reasons_abort():
    rig = Rig()
    _to_turning(rig, 90.)
    rig.m._recovery_providers['linear_ceiling'] = lambda: 0.
    rig.turn_until('turning', seen=False)
    status = rig.m.status()
    assert (status.junction.state, status.junction.reason) == ('aborted', 'linear_limit_zero')


def test_turn_does_not_latch_lost_while_the_lane_is_out_of_view():
    rig = Rig()
    _to_turning(rig, 150.)
    decision, status = rig.turn_until('turning', seen=False)
    assert status.state != 'LOST' and status.junction.state == 'advancing'


def test_lane_lost_before_the_junction_is_not_cleared_by_the_turn():
    """Review M8: a LOST that the junction sighting did not start stays LOST."""
    rig = Rig(lost_after_s=1.)
    rig.send('left', turn_deg=90., expires_s=30.)
    for _ in range(40):
        rig.step(seen=False)                                  # lane lost 2 s, no junction
    decision, status = rig.step(seen=False, junction=True)
    assert (status.junction.state, status.junction.reason) == ('aborted', 'lane_lost_before_junction')
    assert rig.m._lost_latched and decision.angular == 0.


def test_instruction_while_waiting_turns_and_clears_the_junction_loss_clock():
    rig = Rig()
    for _ in range(20):
        decision, status = rig.step(seen=False, junction=True)  # the junction HOLD hides the lane
    assert status.junction.state == 'waiting' and rig.m._loss_started_at is not None
    rig.send('left', turn_deg=90.)
    decision, status = rig.step(seen=False, junction=True)
    assert status.junction.state == 'turning' and rig.m._loss_started_at is None


def test_instruction_after_lost_after_s_at_the_junction_is_too_late():
    """Fleet must arm before arrival: waiting past lost_after_s latches LOST and opens a D-407
    stuck, and the turn does not override the open stuck."""
    rig = Rig(lost_after_s=1.)
    for _ in range(40):
        rig.step(seen=False, junction=True)
    rig.send('left', turn_deg=90.)
    decision, status = rig.step(seen=False, junction=True)
    assert (status.junction.state, status.junction.reason, decision.angular) == ('aborted', 'stuck', 0.)


def test_driver_release_mid_turn_aborts():
    rig = Rig()
    rig.m.set_mode(CAMERA, hold_s=1.)
    _to_turning(rig, 90.)
    rig.now += 1.1  # no POST /hold for longer than hold_s: CORE releases the driver
    decision, status = rig.step(seen=False)
    assert status.mode == 'OFF' and (decision.linear, decision.angular) == (0., 0.)
    assert (status.junction.state, status.junction.reason) == ('aborted', 'mode_change')


def test_stop_instruction_also_holds_at_a_seen_junction():
    """Review M7: stop after the distance or at the junction, whichever comes first."""
    rig = Rig()
    rig.step()
    rig.send('stop', stop_after_m=1.)
    assert rig.step(move=True)[0].linear > 0
    decision, status = rig.step(junction=True, move=True)
    assert decision.linear == 0. and status.reason == 'junction_stop'


def test_ir_line_has_no_junction_gate_and_refuses_instructions():
    """Review M4: no junction detection on IR, so no waiting and no instruction (409)."""
    rig = Rig()
    rig.m.set_mode(LineFollowMode.IR_LINE)
    rig.m.observe(LineObservation(LineFollowMode.IR_LINE, rig.now, True, 0., .9, ir_calibrated=True,
                                  calibration_revision='r'), received_at=rig.now)
    rig.m.observe_junction('junction_fork', rig.now)
    rig.m.tick(rig.now)
    assert rig.m.status().junction.state == 'idle'
    with pytest.raises(JunctionRefused) as refused:
        rig.send('left', turn_deg=90.)
    assert refused.value.code == 'JUNCTION_CAMERA_ONLY'


def test_supports_junction_turn_needs_fresh_keep_evidence_with_corner_turning():
    rig = Rig()
    rig.m.bind_return_motion(lambda now, v, w: True, proof_configured=lambda: True)
    assert rig.m.supports_junction_turn is False            # no keep_debug at all (line mode)
    rig.m.observe_junction('no_boundary', rig.now, corner_turning=True)
    assert rig.m.supports_junction_turn is True             # keep mode + lane_corner_turning
    rig.now += 2.5
    assert rig.m.supports_junction_turn is False            # observer gone or mode switched
    rig.m.observe_junction('no_boundary', rig.now, corner_turning=True)
    rig.m.observe_junction('no_boundary', rig.now, corner_turning=False)
    assert rig.m.supports_junction_turn is False            # keep mode, corner turning off
    rig.m.set_mode(LineFollowMode.OFF)
    rig.m.observe_junction('junction_fork', rig.now, corner_turning=True)
    assert rig.m.supports_junction_turn is True             # independent of the line-follow session


def test_lane_still_out_of_view_past_lost_after_s_is_unresolved_not_aborted():
    rig = Rig(lost_after_s=1.)
    _to_turning(rig, 45., advance_m=0.)
    rig.turn_until('turning', seen=False)
    for _ in range(40):                       # 2 s without a lane while handed back
        decision, status = rig.step(seen=False)
    assert (status.junction.state, decision.linear, decision.angular) == ('unresolved', 0., 0.)


# --- D-495 re-review N1, R1-R3 ------------------------------------------------------------

def test_resend_after_a_mid_turn_abort_aims_at_entry_heading_plus_turn():
    """Review N1: headings must not add up (90 deg was turning into 133.9 deg)."""
    rig = Rig()
    _to_turning(rig, 90.)
    while math.degrees(rig.yaw) < 45.:
        rig.step(seen=False, junction=True, move=True)
    rig.calibrating = True
    assert rig.step(seen=False, junction=True, move=True)[1].junction.state == 'aborted'
    rig.calibrating = False
    assert rig.send('left', turn_deg=90.) == (True, 2, 'armed')   # aborted mid-turn: allowed
    decision, status = rig.turn_until('armed', seen=False, junction=True)
    decision, status = rig.turn_until('turning', seen=False, junction=True)
    assert status.junction.state == 'advancing' and abs(_yaw_error_deg(rig.yaw, 90.)) <= 5.


def test_repeat_after_completion_is_refused_until_another_place_or_mode_change():
    """Review R1: a resend after the turn ran must not arm a second turn at the next junction."""
    rig = Rig()
    _to_turning(rig, 45., advance_m=0.)
    rig.turn_until('turning', seen=False)
    _reacquire(rig)
    assert rig.m.status().junction.state == 'idle'
    with pytest.raises(JunctionRefused) as refused:
        rig.send('left', turn_deg=45., advance_m=0.)
    assert refused.value.code == 'JUNCTION_ALREADY_DONE'
    rig.m.set_mode(LineFollowMode.OFF)                                    # review N2: a mode
    rig.m.set_mode(CAMERA)                                                # change keeps it
    with pytest.raises(JunctionRefused):
        rig.send('left', turn_deg=45., advance_m=0.)
    assert rig.m.set_junction('straight', 'J2', 10.)[0] is True          # next place clears it
    assert rig.send('left', turn_deg=45.)[0] is True


def test_abort_after_the_turn_also_counts_as_done():
    rig = Rig()
    _to_turning(rig, 45.)
    rig.turn_until('turning', seen=False)
    assert rig.m.status().junction.state == 'advancing'
    rig.calibrating = True
    rig.step(seen=False, move=True)
    rig.calibrating = False
    with pytest.raises(JunctionRefused) as refused:
        rig.send('left', turn_deg=45.)
    assert refused.value.code == 'JUNCTION_ALREADY_DONE'


def _unresolved_by_travel(rig):
    for _ in range(11):
        rig.step(seen=False, dx=.019)


def _unresolved_by_timeout(rig):
    rig.m._junction['phase_at'] -= 5.1
    rig.step(seen=False)


def _unresolved_by_stuck(rig):
    for _ in range(40):
        rig.step(seen=False)


@pytest.mark.parametrize('fail', [_unresolved_by_travel, _unresolved_by_timeout, _unresolved_by_stuck])
def test_unresolved_after_the_turn_counts_as_done(fail):
    """D-495 SIM finding 4: the entry heading is gone after the turn, so a resend of the same
    place must be 409, not a second turn stacked on the first."""
    rig = Rig(lost_after_s=1.)
    _to_turning(rig, 45., advance_m=0.)
    rig.turn_until('turning', seen=False)
    fail(rig)
    assert rig.m.status().junction.state == 'unresolved'
    with pytest.raises(JunctionRefused) as refused:
        rig.send('left', turn_deg=45., advance_m=0.)
    assert refused.value.code == 'JUNCTION_ALREADY_DONE'
    assert rig.m.set_junction('straight', 'J2', 10.)[0] is True          # next place clears it


def test_straight_passed_is_done_for_that_place():
    rig = Rig()
    rig.send('straight')
    rig.step(junction=True)
    rig.now += 1.
    rig.step()
    with pytest.raises(JunctionRefused):
        rig.send('straight')


def test_settle_also_needs_odom_standing_still():
    """Review R2: inside 5 deg for 0.3 s is not enough while odom still shows rotation."""
    rig = Rig()
    _to_turning(rig, 90.)
    for _ in range(200):
        rig.step(seen=False, move=True)
        if rig.m._junction.get('sub') == 'settling' and rig.m._junction.get('settled_at'):
            break
    assert abs(_yaw_error_deg(rig.yaw, 90.)) <= 5.
    for i in range(12):            # 0.6 s inside tolerance, odom wobbling +-0.08 rad/s
        rig.yaw += .004 if i % 2 else -.004
        decision, status = rig.step(seen=False)
        assert status.junction.state == 'turning' and decision.angular == 0.
    for _ in range(10):
        decision, status = rig.step(seen=False)
    assert status.junction.state == 'advancing'


def test_sighting_gap_while_waiting_keeps_the_first_sighting():
    """Review R3: a keeper gap > 0.3 s at the junction is the same junction stop."""
    rig = Rig()
    for _ in range(10):
        rig.step()
    for _ in range(20):
        rig.step(seen=False, junction=True)
    for _ in range(10):
        rig.step(seen=False)
    for _ in range(4):
        rig.step(seen=False, junction=True)
    rig.send('left', turn_deg=90.)
    decision, status = rig.step(seen=False, junction=True)
    assert status.junction.state == 'turning'


def test_reselect_after_an_abort_in_advancing_does_not_turn_again():
    """Review N2: probe_final turned to 171.5 deg after a CAMERA_LINE re-select."""
    rig = Rig()
    _to_turning(rig, 90.)
    rig.turn_until('turning', seen=False, junction=True)
    assert rig.m.status().junction.state == 'advancing'
    rig.calibrating = True
    rig.step(seen=False, junction=True, move=True)
    rig.calibrating = False
    yaw = rig.yaw
    rig.m.set_mode(CAMERA)                                    # operator re-selects
    with pytest.raises(JunctionRefused) as refused:
        rig.send('left', turn_deg=90.)
    assert refused.value.code == 'JUNCTION_ALREADY_DONE'
    assert rig.send('right', turn_deg=-90.)[0] is True        # another action at the same place
    decision, status = rig.step(seen=False, junction=True, move=True)
    # The re-select restarted the odom trail, so the entry heading cannot be compared: no turn.
    assert (status.junction.state, status.junction.reason, decision.angular) == ('aborted', 'odom', 0.)
    assert rig.yaw == yaw


def test_entry_heading_ends_after_lost_after_s_without_a_sighting():
    rig = Rig()
    rig.step(junction=True)                                   # waiting, entry recorded
    assert rig.m._junction_entry is not None
    rig.m.set_mode(CAMERA)                                    # junction record reset, entry kept
    rig.step(seen=False, junction=True)
    assert rig.m._junction_entry is not None and rig.m.status().junction.state == 'waiting'
    rig.m.set_mode(CAMERA)
    rig.now += .4                                             # the last sighting is stale
    for _ in range(40):                                       # 2.4 s: still inside lost_after_s
        rig.step()
    assert rig.m._junction_entry is not None
    for _ in range(20):                                       # past lost_after_s (3 s)
        rig.step()
    assert rig.m._junction_entry is None


def test_still_thresholds_are_config():
    with pytest.raises(ValueError):
        LineFollowConfig(junction_still_linear=0.)
    with pytest.raises(ValueError):
        LineFollowConfig(junction_still_angular=.5)
    rig = Rig(junction_still_linear=.02, junction_still_angular=.2)
    _to_turning(rig, 90.)
    for _ in range(6):                     # creeping 0.06 m/s is above the 0.02 threshold
        decision, status = rig.step(seen=False, dx=.003)
    assert decision.angular == 0. and status.reason == 'junction_stopping'


@pytest.mark.parametrize('proof', ['unbound', 'not_configured', 'raises'])
def test_supports_junction_turn_needs_a_motion_proof_that_can_admit(proof):
    """Final review 1: without the D-400 enforce floor proof every turn would abort
    motion_unconfirmed, so the capability must be False."""
    rig = Rig(proof=False)
    if proof == 'not_configured':
        rig.m.bind_return_motion(lambda now, v, w: True, proof_configured=lambda: False)
    elif proof == 'raises':
        rig.m.bind_return_motion(lambda now, v, w: True, proof_configured=lambda: 1 / 0)
    rig.m.observe_junction('no_boundary', rig.now, corner_turning=True)
    assert rig.m.supports_junction_turn is False
    rig.m.bind_return_motion(lambda now, v, w: True, proof_configured=lambda: True)
    assert rig.m.supports_junction_turn is True
