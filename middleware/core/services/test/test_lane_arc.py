"""D-520 step 1 SOURCE: map-guided arc following, its IR one-time correction, stops and the
arc-off golden. Real LineFollowManager, no ROS, no physical motion (the rig integrates the
commanded twist into odom, optionally with an actuation turn scale)."""
import json
import math
from pathlib import Path

import pytest

from core_features.line_follow.arc.lane_arc import ARC_IR_AWAY_M, ARC_START_IR_GRACE_M
from core_features.line_follow.model import LineFollowMode, LineObservation
from line_follow_golden_scenario import scenario
from test_line_junction import BODY, Rig

IR = LineFollowMode.IR_LINE
CLEAR = [(1.5, 1.5)]
SITE = dict(BODY, ir_guard_enabled=True, obstacle_mode='path', site_floor_map_id='lab-a',
            arc_enabled=True)
K, LENGTH = 3.98, .3739          # 260919 ring_s
V = .08                          # min(cruise .08, max_linear .10, manual ceiling .1)
B = 4.                           # bridge_arm_max_curvature
SEGMENT = dict(curvature_1pm=K, length_m=LENGTH, outer_line_offset_m=.095, end_place_id='SE')
IR_ERROR = {'clear': None, 'left': -.9, 'right': .9, 'centre': 0.}


class Events:
    def __init__(self):
        self.seen = []

    def publish(self, event, **kwargs):
        self.seen.append((event, kwargs))


class ArcRig(Rig):
    """Site basis (D-400 floor proof known not live) unless enforce; IR fed every step.
    turn_scale scales the yaw the robot really turns (1: perfect actuation)."""

    def __init__(self, enforce=False, **config):
        super().__init__(proof=enforce, **{**SITE, **config})
        if not enforce:
            self.m.bind_return_motion(lambda now, v, w: False, floor_proof_live=lambda: False,
                                      proof_configured=lambda: False)
        self.m._events = self.events = Events()
        self.ir, self.ir_conf, self.turn_scale, self.points = 'clear', .9, 1., CLEAR

    def step(self, ir=None, **kwargs):
        t = round(self.now + .05, 6)
        ir = self.ir if ir is None else ir
        if ir != 'stale':
            e = IR_ERROR[ir]
            self.m.observe(LineObservation(IR, t, e is not None, e, self.ir_conf if e is not None else 0.,
                                           ir_calibrated=True, calibration_revision='r'), received_at=t)
        self.w *= self.turn_scale
        kwargs.setdefault('points', self.points)
        return super().step(**kwargs)

    def open(self, segment=SEGMENT, place='SW'):
        self.step()
        with self.m._lock:
            j = dict(place_id=place, action='left', map_id='lab-a', exit_segment=dict(segment))
            assert self.m._open_arc(j, self.now) is None
        return self.m.status()

    def drive(self, n=1, **kwargs):
        for _ in range(n):
            decision, status = self.step(move=True, **kwargs)
        return decision, status

    def until(self, predicate, limit=400, **kwargs):
        for _ in range(limit):
            decision, status = self.step(move=True, **kwargs)
            if predicate(decision, status):
                return decision, status
        raise AssertionError('condition never met')


def running(rig):
    return rig.m.status().arc is not None and rig.m.status().arc.state == 'running'


def send(rig, action, place, turn_deg=None, segment=None, expires_s=10.):
    expect = {'map_id': 'lab-a'} if segment is not None else None
    return rig.m.set_junction(action, place, expires_s, None, turn_deg, None, expect=expect,
                              exit_segment=segment)


# --- golden ------------------------------------------------------------------------------------

def test_arc_off_matches_main_tick_for_tick():
    golden = json.loads(Path(__file__).with_name('test_lane_arc_off_golden.json').read_text(encoding='utf-8'))
    assert scenario(False) == golden['ir_off']
    assert scenario(True) == golden['ir_on']


# --- opening ------------------------------------------------------------------------------------

def _window_rig(**expect):
    """At a junction with a D-507 window: drive to x .2 and sight the cross line .2 ahead."""
    rig = ArcRig()
    rig.step()
    seg = dict(SEGMENT)
    assert rig.m.set_junction('left', 'SW', 10., None, 64., .2,
                              expect=dict(map_id='lab-a', expect_in_m=.4, expect_tol_m=.1, **expect),
                              exit_segment=seg) == (True, 1, 'armed')
    while rig.x < .2 - 1e-9:
        rig.step(dx=.01)
    rig.m.observe_junction('junction_transverse', round(rig.now + .05, 6), ahead_m=.2)
    rig.step(seen=False)
    return rig


def test_turn_end_with_map_pivot_opens_the_arc_and_the_instruction_is_done():
    rig = _window_rig(pivot_past_line_m=0.)
    decision, status = rig.until(lambda d, s: s.arc is not None, seen=False)
    assert status.junction.state == 'idle' and status.arc.state == 'running'
    assert (status.arc.arc_seq, status.arc.from_place_id, status.arc.end_place_id) == (1, 'SW', 'SE')
    assert rig.m._junction_done_place == ('SW', 'left')
    assert (decision.linear, decision.angular) == (0., 0.) and status.reason == 'lane_arc'
    decision, status = rig.drive(seen=False)
    assert decision.linear == pytest.approx(V) and decision.angular == pytest.approx(V*K)
    with pytest.raises(Exception, match='already ran'):
        send(rig, 'left', 'SW', 64., SEGMENT)


def test_stop_point_opens_no_arc_and_advances_the_default():
    """Review fix 2: exit_segment without an arc (stop_point) is today's turn: DEFAULT_ADVANCE_M."""
    rig = _window_rig()                       # no pivot_past_line_m: stop_point
    decision, status = rig.until(lambda d, s: s.junction.state not in ('turning', 'armed'), seen=False)
    assert status.arc is None and status.junction.pivot_basis == 'stop_point'
    assert status.junction.state == 'advancing' and rig.m._junction['advance_m'] == .10
    start = (rig.x, rig.y)
    rig.until(lambda d, s: s.junction.state != 'advancing', seen=False)
    assert math.hypot(rig.x - start[0], rig.y - start[1]) == pytest.approx(.10, abs=.01)


# --- command ------------------------------------------------------------------------------------

@pytest.mark.parametrize('k, gain', [(K, 1.), (K, .9), (-K, 1.25), (1.5, 1.)])
def test_command_is_gain_v_kappa(k, gain):
    rig = ArcRig(arc_curvature_gain=gain)
    rig.open(dict(SEGMENT, curvature_1pm=k))
    decision, status = rig.drive()
    assert decision.linear == pytest.approx(V) and decision.angular == pytest.approx(gain*V*k)
    assert (status.state, status.reason) == ('RECOVERING', 'lane_arc')
    assert rig.m._intended == (decision.linear, decision.angular)


def test_angular_cap_keeps_the_curvature_slower():
    rig = ArcRig(max_angular=.2)
    rig.open()
    decision, _ = rig.drive()
    assert decision.angular == pytest.approx(.2)
    assert decision.angular/decision.linear == pytest.approx(K)


# --- segment end -------------------------------------------------------------------------------

def test_ends_on_odom_path_length_and_follows_unarmed_with_the_event():
    rig = ArcRig()
    rig.open()
    decision, status = rig.until(lambda d, s: not running(rig), seen=False)
    assert status.arc.state == 'ended' and status.arc.reason == 'lane_arc_end_unarmed'
    assert LENGTH <= status.arc.travelled_m <= LENGTH + V*.05 + 1e-6
    # the arc covered its angle: heading turned by about kappa * length
    assert rig.yaw == pytest.approx(K*LENGTH, abs=K*V*.05 + .01)
    assert [e for e, _ in rig.events.seen] == ['nav.lane_arc_end_unarmed']
    data = rig.events.seen[0][1]
    assert data['severity'] == 'warning' and set(data['data']) == {'end_place_id', 'arc_seq', 'travelled_m'}
    decision, status = rig.drive()            # today's following, next frame
    assert status.state == 'TRACKING' and decision.linear > 0


def test_does_not_end_before_the_segment_length():
    rig = ArcRig()
    rig.open()
    last = 0.
    while running(rig):
        last = rig.m._arc['travelled']
        rig.drive(seen=False)
    assert last < LENGTH <= rig.m._arc['travelled']


def test_time_limit_stops_a_robot_that_does_not_move():
    rig = ArcRig()
    rig.open()
    limit = LENGTH/V + 2.
    for _ in range(200):
        decision, status = rig.step(seen=False)       # commanded, but odom stays put
        if not running(rig):
            break
    assert status.arc.state == 'stopped' and status.arc.reason == 'lane_arc_timeout'
    assert status.reason == 'lane_arc_timeout' and (decision.linear, decision.angular) == (0., 0.)
    assert limit - .1 <= rig.now - 1.05 <= limit + .15
    decision, status = rig.drive()                    # stopped holds until a mode change
    assert (decision.linear, status.state, status.reason) == (0., 'HOLD', 'lane_arc_timeout')
    rig.m.set_mode(LineFollowMode.CAMERA_LINE)
    decision, status = rig.drive()
    assert status.state == 'TRACKING' and status.arc.state == 'stopped'


# --- the instruction slot during an arc --------------------------------------------------------

def test_next_place_instruction_is_armed_and_pivots_at_segment_end():
    rig = ArcRig()
    rig.open()
    rig.drive(3)
    assert send(rig, 'left', 'SE', 90.) == (True, 1, 'armed')
    decision, status = rig.drive(junction=True)       # keeper junction sighting is not used
    assert running(rig) and decision.linear > 0 and status.junction.state == 'armed'
    decision, status = rig.until(lambda d, s: not running(rig))
    assert status.arc.reason == 'segment_end' and status.junction.state == 'turning'
    assert status.junction.pivot_basis == 'segment_end' and status.reason == 'junction_stopping'
    start = rig.yaw
    decision, status = rig.until(lambda d, s: s.junction.state != 'turning', seen=False)
    assert math.degrees(rig.yaw - start) == pytest.approx(90., abs=5.)
    assert status.junction.state == 'advancing' and status.arc.state == 'ended'


def test_straight_with_exit_segment_chains_the_next_arc():
    rig = ArcRig()
    rig.open()
    send(rig, 'straight', 'SE', segment=dict(SEGMENT, end_place_id='NE', length_m=.4595))
    decision, status = rig.until(lambda d, s: s.arc.arc_seq == 2)
    assert status.arc.state == 'running' and status.arc.from_place_id == 'SE'
    assert status.junction.state == 'idle' and decision.linear > 0      # no stop between arcs
    assert rig.m._junction_done_place == ('SE', 'straight')


@pytest.mark.parametrize('action, turn_deg, state, reason', [
    ('straight', None, 'idle', 'tracking'),    # executing, then passed: the sighting is gone
    ('stop', None, 'executing', 'junction_stop'),
    ('right', None, 'unresolved', 'junction_unresolved')])
def test_other_actions_at_segment_end(action, turn_deg, state, reason):
    rig = ArcRig()
    rig.open()
    assert send(rig, action, 'SE', turn_deg)[2] == 'armed'   # even stop / right without turn_deg
    rig.until(lambda d, s: not running(rig))
    decision, status = rig.drive()
    assert status.junction.state == state and status.reason == reason


def test_other_place_instruction_is_aborted_arc_mismatch_and_follows():
    rig = ArcRig()
    rig.open()
    send(rig, 'left', 'NE', 90.)
    decision, status = rig.until(lambda d, s: not running(rig))
    assert status.junction.state == 'aborted' and status.junction.reason == 'arc_mismatch'
    assert status.arc.reason == 'lane_arc_end_unarmed'
    assert [e for e, _ in rig.events.seen] == ['nav.lane_arc_end_unarmed']
    decision, status = rig.drive()
    assert status.state == 'TRACKING' and decision.linear > 0   # not a junction_aborted HOLD


def test_expired_instruction_is_an_unarmed_end():
    rig = ArcRig()
    rig.open()
    send(rig, 'left', 'SE', 90., expires_s=.2)
    _, status = rig.until(lambda d, s: not running(rig))
    assert status.arc.reason == 'lane_arc_end_unarmed' and status.junction.state == 'idle'


# --- muting: keeper reasons, loss clock, D-476 / D-468 / D-407 ---------------------------------

def test_keeper_loss_neither_stops_nor_latches_lost(monkeypatch):
    rig = ArcRig(lost_after_s=.5, bridge_time_margin_s=.2, bridge_enabled=True,
                 recovery_local_enabled=True)
    rig.open(dict(SEGMENT, length_m=1.))
    for name in ('_apply_lane_return', '_apply_recovery', '_junction_gate'):
        monkeypatch.setattr(rig.m, name, lambda *a: pytest.fail(f'{name} ran during the arc'))
    for _ in range(40):                                  # 2 s, four times lost_after_s
        decision, status = rig.drive(seen=False, junction=True)
        assert decision.linear > 0 and status.reason == 'lane_arc'
        assert rig.m._loss_started_at is None and not rig.m._lost_latched
        assert rig.m._bridge is None and rig.m._return_controller is None
    rig.m.invalidate(rig.now)                             # invalid vision
    assert rig.drive(seen=False)[0].linear > 0


# --- stops ------------------------------------------------------------------------------------

def test_pose_lost_stops():
    rig = ArcRig()
    rig.open()
    for _ in range(8):
        decision, status = rig.step(pose=False)
    assert status.arc.reason == 'lane_arc_pose_lost' and decision.linear == 0.


def test_odom_frame_change_stops():
    rig = ArcRig()
    rig.open()
    rig.now = round(rig.now + .05, 6)
    stamp = round(rig.now*1e9)
    rig.m.observe_return_pose(stamp_ns=stamp, source_now_ns=stamp, frame='odom2', x=0., y=0., yaw=0.,
                              received_at=rig.now)
    rig.m.tick(rig.now)
    assert rig.m.status().arc.reason == 'lane_arc_pose_lost'


def test_stale_scan_stops_motion_unconfirmed():
    rig = ArcRig()
    rig.open()
    for _ in range(12):
        decision, status = rig.drive(points=None)
    assert status.arc.reason == 'lane_arc_motion_unconfirmed' and decision.linear == 0.


def test_wrong_map_is_motion_unconfirmed():
    rig = ArcRig()
    rig.step()
    with rig.m._lock:
        rig.m._open_arc(dict(place_id='SW', action='left', map_id='other', exit_segment=SEGMENT), rig.now)
    _, status = rig.drive()
    assert status.arc.reason == 'lane_arc_motion_unconfirmed'


def test_blind_distance_stops():
    rig = ArcRig(arc_blind_max_m=.1)
    rig.open()
    _, status = rig.until(lambda d, s: not running(rig))
    assert status.arc.reason == 'lane_arc_blind' and .1 < status.arc.travelled_m <= .1 + V*.05 + 1e-6


@pytest.mark.parametrize('reason', ['mode_changed', 'mode_off'])
def test_mode_change_stops_with_todays_reason(reason):
    rig = ArcRig()
    rig.open()
    rig.drive(2)
    rig.m.set_mode(LineFollowMode.CAMERA_LINE if reason == 'mode_changed' else LineFollowMode.OFF)
    assert rig.m.status().arc.state == 'stopped' and rig.m.status().arc.reason == reason


def test_calibration_lease_stops():
    rig = ArcRig()
    rig.open()
    rig.calibrating = True
    _, status = rig.drive()
    assert status.arc.reason == 'calibration_active'


def test_arc_sweep_stops_for_a_point_on_the_arc_not_one_straight_ahead():
    rig = ArcRig()
    rig.open()
    rig.points = [(.30, -.06)]               # straight ahead of the body, off the left-turning arc
    decision, status = rig.drive(3)
    assert running(rig) and decision.linear > 0
    rig.points = [(.1257, .0337)]            # on the ring arc 30 deg ahead
    _, status = rig.drive()
    assert status.arc.reason == 'obstacle_ahead'


@pytest.mark.parametrize('ir, reason', [('centre', 'lane_arc_edge'), ('stale', 'lane_arc_motion_unconfirmed')])
def test_ir_centre_and_stale_stop_even_in_the_grace(ir, reason):
    rig = ArcRig()
    rig.open()
    for _ in range(8):                        # a stale IR needs stale_after_s without a sample
        _, status = rig.drive(ir=ir)
        if not running(rig):
            break
    assert status.arc.travelled_m < ARC_START_IR_GRACE_M and status.arc.reason == reason


def test_enforce_basis_runs_the_arc_with_the_probe():
    rig = ArcRig(enforce=True)
    rig.open()
    assert rig.drive()[0].linear == pytest.approx(V)


def test_crosswalk_zone_on_the_arc_start_refuses_the_arc():
    rig = ArcRig()
    rig.step()
    pose = rig.m._fresh_pose(rig.now)
    rig.m._crosswalks._zones.append(dict(epoch=rig.m._return_evidence.epoch, stamp_ns=0, near=.05,
                                         far=.15, uncertainty=.01, received_at=rig.now, anchor=pose))
    j = dict(place_id='SW', action='left', map_id='lab-a', exit_segment=dict(SEGMENT), advance_m=0.)
    with rig.m._lock:
        assert rig.m._open_arc(j, rig.now) is False
    assert rig.m._arc is None and j['exit_segment'] is None and j['advance_m'] == .10
    assert j['reason'] == 'arc_crosswalk'
    far = dict(rig.m._crosswalks._zones[0], near=.5, far=.6)  # beyond the arc start
    rig.m._crosswalks._zones[:] = [far]
    with rig.m._lock:
        assert rig.m._open_arc(dict(j, exit_segment=dict(SEGMENT)), rig.now) is None


# --- IR one-time correction -------------------------------------------------------------------

def _past_grace(rig):
    rig.until(lambda d, s: s.arc.travelled_m >= ARC_START_IR_GRACE_M)


@pytest.mark.parametrize('side, sign', [('left', -1), ('right', 1)])
def test_correction_bias_direction_size_and_speed(side, sign):
    rig = ArcRig()
    rig.open()
    _past_grace(rig)
    decision, status = rig.drive(ir=side)
    v_c = V*.5
    assert decision.linear == pytest.approx(v_c) and decision.linear > 0
    assert decision.angular == pytest.approx(v_c*K + sign*v_c*B)
    assert status.reason == 'lane_arc_correcting'
    assert status.arc.ir_correction.side == side and status.arc.ir_correction.phase == 'away'


def test_away_runs_its_distance_then_level_reaches_the_reference():
    rig = ArcRig()
    rig.open(dict(SEGMENT, length_m=1.))
    _past_grace(rig)
    rig.drive(ir='left')
    rig.until(lambda d, s: not running(rig), ir='left')     # left is allowed during away
    a = rig.m._arc
    assert a['reason'] == 'lane_arc_edge' and a['corr']['away_m'] >= ARC_IR_AWAY_M  # still left at its end
    rig = ArcRig()
    rig.open(dict(SEGMENT, length_m=1.))
    _past_grace(rig)
    rig.drive(ir='left')
    _, status = rig.until(lambda d, s: s.arc.ir_correction.phase != 'away')
    c = status.arc.ir_correction
    assert c.phase == 'level' and ARC_IR_AWAY_M <= c.away_m <= ARC_IR_AWAY_M + V*.5*.05 + 1e-6
    decision, status = rig.until(lambda d, s: s.arc.ir_correction.phase != 'level')
    c, a = status.arc.ir_correction, rig.m._arc
    assert c.phase == 'done' and c.used and 0 < c.level_m <= .18
    reference = a['yaw0'] + K*a['travelled']
    assert abs(math.atan2(math.sin(reference-rig.yaw), math.cos(reference-rig.yaw))) <= \
        abs(V*.5*B)*.05 + 1e-6 + V*.5*K*.05
    assert decision.linear == pytest.approx(V) and status.reason == 'lane_arc'


def test_away_end_needs_a_confident_clear():
    rig = ArcRig()
    rig.open(dict(SEGMENT, length_m=1.))
    _past_grace(rig)
    rig.drive(ir='left')
    rig.ir_conf = .2                          # visible but below min_confidence: _ir_guard says clear
    rig.until(lambda d, s: not running(rig), ir='left')
    assert rig.m._arc['reason'] == 'lane_arc_edge' and rig.m._arc['corr']['phase'] == 'away'
    assert rig.m._arc['corr']['away_m'] >= ARC_IR_AWAY_M


def test_level_cap_stops():
    rig = ArcRig()
    rig.open(dict(SEGMENT, length_m=1.))
    _past_grace(rig)
    rig.drive(ir='left')
    rig.until(lambda d, s: s.arc.ir_correction.phase == 'level')
    rig.turn_scale = 0.                       # the robot no longer turns: level never levels
    _, status = rig.until(lambda d, s: not running(rig))
    assert status.arc.reason == 'lane_arc_edge' and status.arc.ir_correction.level_m > .18


@pytest.mark.parametrize('phase, ir', [('away', 'right'), ('away', 'centre'), ('level', 'left'),
                                       ('level', 'right')])
def test_correction_stops(phase, ir):
    rig = ArcRig()
    rig.open(dict(SEGMENT, length_m=1.))
    _past_grace(rig)
    rig.drive(ir='left')
    if phase == 'level':
        rig.until(lambda d, s: s.arc.ir_correction.phase == 'level')
    _, status = rig.drive(ir=ir)
    assert status.arc.state == 'stopped' and status.arc.reason == 'lane_arc_edge'


def test_one_correction_per_arc_then_a_new_arc_may_correct_again():
    rig = ArcRig()
    rig.open(dict(SEGMENT, length_m=1.))
    _past_grace(rig)
    rig.drive(ir='left')
    rig.until(lambda d, s: s.arc.ir_correction.phase == 'done')
    _, status = rig.drive(ir='right')
    assert status.arc.reason == 'lane_arc_edge'      # the second verdict on the same arc
    rig.m.set_mode(LineFollowMode.CAMERA_LINE)
    rig.open(dict(SEGMENT, length_m=1.))
    _past_grace(rig)
    _, status = rig.drive(ir='right')
    assert status.arc.arc_seq == 2 and status.arc.ir_correction.phase == 'away'


def test_segment_end_during_the_correction_stops():
    rig = ArcRig()
    rig.open(dict(SEGMENT, length_m=.1))
    _past_grace(rig)
    rig.drive(ir='left')
    send(rig, 'left', 'SE', 90.)
    _, status = rig.until(lambda d, s: not running(rig), ir='left')
    assert status.arc.reason == 'lane_arc_edge' and status.junction.state == 'armed'


def test_correction_time_limit_stops():
    rig = ArcRig()
    rig.open(dict(SEGMENT, length_m=1.))
    _past_grace(rig)
    rig.drive(ir='left')
    for _ in range(400):
        _, status = rig.step(ir='left')               # commanded, the robot does not move
        if not running(rig):
            break
    assert status.arc.reason == 'lane_arc_edge' and status.arc.ir_correction.phase == 'away'


def test_grace_admits_left_right_and_a_same_side_first_verdict_stops():
    rig = ArcRig()
    rig.open()
    decision, status = rig.drive(ir='left')
    assert decision.linear == pytest.approx(V) and status.arc.ir_correction.phase is None
    _, status = rig.until(lambda d, s: s.arc.travelled_m >= ARC_START_IR_GRACE_M or not running(rig),
                          ir='left')
    assert status.arc.reason == 'lane_arc_edge' and status.arc.ir_correction.phase is None


def test_grace_line_end_then_clear_allows_a_later_correction():
    rig = ArcRig()
    rig.open(dict(SEGMENT, length_m=1.))
    rig.drive(ir='left')
    _past_grace(rig)                                     # first verdict after the grace: clear
    rig.drive(3)
    _, status = rig.drive(ir='left')
    assert status.arc.ir_correction.phase == 'away'


def test_no_reverse_in_any_arc_tick():
    rig = ArcRig()
    rig.open(dict(SEGMENT, length_m=1.))
    linears = []
    for ir in ['clear']*3 + ['left']*40 + ['clear']*60:
        decision, _ = rig.drive(ir=ir)
        linears.append(decision.linear)
    assert min(linears) >= 0. and max(linears) > 0.


def test_correction_twist_is_swept_by_d422():
    rig = ArcRig()
    rig.open(dict(SEGMENT, length_m=1.))
    _past_grace(rig)
    rig.points = [(.12, -.05)]           # off the plain arc, on the near-straight away path
    assert rig.drive(ir='clear')[0].linear > 0
    _, status = rig.drive(ir='left')
    assert status.arc.reason == 'obstacle_ahead'


@pytest.mark.parametrize('offset, yaw0', [(.04, -.15), (.05, -.10)])
def test_closed_loop_gain_09_corrects_without_heading_outward(offset, yaw0):
    """Ring model: centre (0, r); the robot starts offset outside the centre line, heading yaw0
    outward of the tangent, with arc_curvature_gain 0.9 (under-turning, drifts out). IR row x 0.0295, sensors y +-0.020,
    outer paint at r + 0.095 (0.025 wide). After the correction its heading is not outward."""
    r = 1/K
    rig = ArcRig(arc_curvature_gain=.9)
    rig.y, rig.yaw = -offset, yaw0

    def verdict():
        hits = []
        for lateral in (.02, 0., -.02):
            px = rig.x + .0295*math.cos(rig.yaw) - lateral*math.sin(rig.yaw)
            py = rig.y + .0295*math.sin(rig.yaw) + lateral*math.cos(rig.yaw)
            hits.append(abs(math.hypot(px, py - r) - (r + .095)) <= .0125)
        return 'centre' if hits[1] else 'left' if hits[0] else 'right' if hits[2] else 'clear'

    rig.open(dict(SEGMENT, length_m=1.))
    phase = None
    for _ in range(600):
        _, status = rig.drive(ir=verdict())
        assert status.arc.state == 'running', status.arc.reason
        phase = status.arc.ir_correction.phase
        if phase == 'done':
            break
    assert phase == 'done' and status.arc.ir_correction.side == 'right'
    radial = math.atan2(rig.y - r, rig.x)                 # the ring tangent (CCW) is radial + 90 deg
    outward = math.cos(rig.yaw - radial)                  # > 0: heading away from the centre
    assert outward <= math.sin(V*.5*(K*.9+B)*.05) + 1e-6


# --- safety review fixes 2026-10-08 -------------------------------------------------------------

@pytest.mark.parametrize('place', ['NE', None])
def test_an_armed_stop_of_any_place_holds_at_segment_end(place):
    rig = ArcRig()
    rig.open()
    rig.m.set_junction('stop', place, 10.)
    rig.until(lambda d, s: not running(rig))
    decision, status = rig.drive(junction=True)
    assert (decision.linear, status.reason, status.junction.state) == (0., 'junction_stop', 'executing')
    assert status.arc.reason == 'segment_end' and rig.events.seen == []


def test_limits_use_the_speed_the_angular_cap_leaves():
    """Review fix 3: tight kappa 5 and cap 0.2: v 0.04 on the arc, 0.2/(5+4) in the correction."""
    rig = ArcRig(max_angular=.2)
    rig.open(dict(SEGMENT, curvature_1pm=5., length_m=.4))
    assert rig.m._arc['deadline'] - rig.now == pytest.approx(.4/.04 + 2.)
    _past_grace(rig)
    before = rig.m._arc['deadline']
    rig.drive(ir='left')
    c = rig.m._arc['corr']
    assert c['deadline'] - rig.now == pytest.approx(.30/(.2/9.) + 2.)
    assert rig.m._arc['deadline'] - before == pytest.approx(.30/(.2/9.) + 2.)


@pytest.mark.parametrize('enforce', [False, True])
def test_a_low_confidence_visible_line_is_no_clear(enforce):
    """Review fix 4: kind arc needs a confident clear (fresh, calibrated, not visible) every tick."""
    rig = ArcRig(enforce=enforce)
    rig.open(dict(SEGMENT, length_m=1.))
    _past_grace(rig)
    assert rig.drive()[0].linear > 0
    rig.ir_conf = .2                          # _ir_guard reads it as clear
    decision, status = rig.drive(ir='left')
    assert rig.m._ir_guard(rig.now) == 'clear'
    assert (decision.linear, status.arc.reason) == (0., 'lane_arc_motion_unconfirmed')
