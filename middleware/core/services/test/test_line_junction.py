"""D-491 decision 4 / D-492: the junction instruction gate and bounded turn in the real
line-follow manager (no ROS, no physical motion)."""
import math

import pytest

from core_features.line_follow.manager import LineFollowManager
from core_features.line_follow.model import LineFollowConfig, LineFollowMode, LineObservation

CAMERA = LineFollowMode.CAMERA_LINE
BODY = dict(body_front_x_m=.08, body_rear_x_m=-.08, body_half_width_m=.06,
            body_lidar_x_m=0., body_rotation_radius_m=.1)


class Bus:
    def publish(self, event, **kwargs): pass


class Rig:
    """The robot integrates its own commanded twist into odom when `move` is on."""

    def __init__(self, **config):
        self.now, self.x, self.y, self.yaw = 1., 0., 0., 0.
        self.v = self.w = 0.
        self.m = LineFollowManager(Bus(), clock=lambda: self.now, config=LineFollowConfig(**config))
        self.m.bind_recovery(calibration_active=lambda: False, linear_ceiling=lambda: .1)
        self.m.set_mode(CAMERA)

    def step(self, *, junction=False, pose=True, dx=0., seen=True, move=False, points=None):
        self.now = round(self.now + .05, 6)
        if move:
            self.yaw += self.w * .05
            self.x += self.v * math.cos(self.yaw) * .05
            self.y += self.v * math.sin(self.yaw) * .05
        self.x += dx
        if pose:
            stamp = round(self.now * 1e9)
            self.m.observe_return_pose(stamp_ns=stamp, source_now_ns=stamp, frame='odom',
                                       x=self.x, y=self.y, yaw=self.yaw, received_at=self.now)
        if points is not None:
            self.m.observe_scan_points(points, received_at=self.now)
        self.m.observe(LineObservation(CAMERA, self.now, seen, 0. if seen else None,
                                       .9 if seen else 0.), received_at=self.now)
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
                                                seq=0, turn_deg=None, reason=None)


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
    assert rig.send('straight') is None


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


# --- D-492 bounded turn -------------------------------------------------------------------

def _to_turning(rig, turn_deg=90., advance_m=None):
    rig.step()
    assert rig.send('left' if turn_deg > 0 else 'right', turn_deg=turn_deg,
                    advance_m=advance_m) == (True, 1, 'armed')
    decision, status = rig.step()  # armed: ordinary following until the junction
    assert decision.linear > 0 and status.junction.state == 'armed'
    decision, status = rig.step(junction=True, seen=False, move=True)
    assert status.junction.state == 'turning' and status.junction.turn_deg == turn_deg
    return decision, status


@pytest.mark.parametrize('turn_deg', [90., -90., 150., -30.])
def test_turn_advance_reacquire_completes(turn_deg):
    rig = Rig()
    decision, status = _to_turning(rig, turn_deg)
    assert decision.linear == 0. and math.copysign(1, decision.angular) == math.copysign(1, turn_deg)
    assert abs(decision.angular) <= .7 and (status.state, status.reason) == ('RECOVERING', 'junction_turning')
    decision, status = rig.turn_until('turning', seen=False)
    error = math.degrees(math.atan2(math.sin(rig.yaw - math.radians(turn_deg)),
                                    math.cos(rig.yaw - math.radians(turn_deg))))
    assert abs(error) <= 5.
    assert status.junction.state == 'advancing' and decision.angular == 0.
    assert 0 < decision.linear <= .05  # half of min(max_linear .10, manual ceiling .1)
    start = (rig.x, rig.y)
    decision, status = rig.turn_until('advancing', seen=False)
    assert status.junction.state == 'reacquiring' and decision.linear == 0.
    assert math.hypot(rig.x - start[0], rig.y - start[1]) == pytest.approx(.10, abs=.01)
    decision, status = rig.step(seen=True, move=True)
    assert status.junction.state == 'idle' and decision.linear > 0 and status.state == 'TRACKING'
    assert rig.m._bridge_hint is None


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
    assert (status.junction.state, status.junction.reason, decision.angular) == ('aborted', 'odom', 0.)


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


def test_d422_near_stop_aborts_the_turn():
    rig = Rig(**BODY)
    clear = [(1.5, 1.5)]
    rig.step(points=clear)
    rig.send('left', turn_deg=90.)
    decision, status = rig.step(junction=True, seen=False, move=True, points=clear)
    assert status.junction.state == 'turning' and decision.angular > 0
    decision, status = rig.step(seen=False, move=True, points=[(0., .105)])  # inside the swing
    assert (status.junction.state, status.junction.reason, decision.angular) == ('aborted', 'near_stop', 0.)


def test_motion_proof_refusal_aborts():
    rig = Rig()
    rig.m.bind_return_motion(lambda now, v, w: w == 0.)
    rig.step()
    rig.send('left', turn_deg=90.)
    decision, status = rig.step(junction=True, seen=False)  # the first turning tick asks it
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
