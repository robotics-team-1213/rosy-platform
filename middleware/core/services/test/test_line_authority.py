"""D-517 4 (M2): the Fleet movement authority gate in the real line-follow manager (no ROS)."""
import json

import pytest

from core_features.line_follow.authority import AuthorityRefused
from core_features.line_follow.manager import LineFollowManager
from core_features.line_follow.model import LineFollowConfig, LineFollowDecision, LineFollowMode, LineObservation

CAMERA = LineFollowMode.CAMERA_LINE
WALL = 1_800_000_000.0  # CORE wall clock = line clock + WALL in this rig


class Bus:
    def publish(self, event, **kwargs):
        pass


class Rig:
    def __init__(self, **config):
        self.now, self.x = 1., 0.
        self.m = LineFollowManager(Bus(), clock=lambda: self.now, config=LineFollowConfig(**config))
        self.m._wall = lambda: WALL + self.now
        self.m.set_mode(CAMERA)
        self.stop = self.m.config.derived_stop_gap_m(self.m.config.max_linear)
        self.resume = self.stop + self.m.config.obstacle_resume_hysteresis_m

    def step(self, dx=0., pose=True):
        self.now = round(self.now + .05, 6)
        self.x += dx
        if pose:
            stamp = round(self.now * 1e9)
            self.m.observe_return_pose(stamp_ns=stamp, source_now_ns=stamp, frame='odom',
                                       x=self.x, y=0., yaw=0., received_at=self.now)
        self.m.observe(LineObservation(CAMERA, self.now, True, 0., .9), received_at=self.now)
        return self.m.tick(self.now)

    def send(self, until_m, leg='L1', ttl_s=2., stamp=None, **order):  # order: shrink, seq (D-760 3)
        return self.m.set_authority('A1', leg, WALL + self.now if stamp is None else stamp, until_m, ttl_s, **order)

    def authority(self):
        return self.m.authority_status()


def test_inactive_authority_leaves_line_following_unchanged():
    rig = Rig()
    for _ in range(5):
        decision = rig.step(dx=.004)
    assert decision.linear > 0 and rig.m.status().state == 'TRACKING'
    assert rig.authority() is None  # GET /line-follow keeps its old shape
    assert rig.m._authority_gate(rig.now, decision) is decision


def test_required_without_authority_stands():
    rig = Rig(authority_required=True)
    decision = rig.step()
    assert (decision.linear, decision.angular) == (0., 0.)
    assert (rig.m.status().state, rig.m.status().reason) == ('HOLD', 'authority_none')
    assert rig.authority()['state'] == 'NONE'


def test_remaining_is_anchored_at_the_pose_stamp_odom():
    rig = Rig()
    for _ in range(3):
        rig.step()
    stamp = WALL + rig.now  # Fleet's pose was taken here; its authority arrives 3 steps later
    for _ in range(3):
        rig.step(dx=.01)
    result = rig.send(.5, stamp=stamp)
    assert result['accepted'] is True
    assert rig.authority()['remaining_m'] == pytest.approx(.47, abs=1e-6)
    assert rig.authority()['state'] == 'FREE'


def test_stops_at_remaining_minus_the_body_stop_gap_and_resumes_past_the_hysteresis():
    rig = Rig()
    rig.step()
    rig.send(rig.stop + .045)
    travelled = 0.
    for _ in range(20):
        if rig.step(dx=.01).linear == 0.:
            break
        travelled += .01
        rig.send(rig.stop + .045 - travelled)  # the same end, refreshed by Fleet from the new pose
    assert travelled == pytest.approx(.04, abs=1e-6)  # stood once remaining <= d_stop(v)
    assert rig.authority()['state'] == 'HOLDING' and rig.m.status().reason == 'authority_end'
    assert rig.authority()['remaining_m'] <= rig.stop
    rig.send(rig.resume - .001)  # a new end still inside the resume gap: keeps standing
    assert rig.step().linear == 0.
    rig.send(rig.resume + .01)
    assert rig.step().linear > 0. and rig.authority()['state'] == 'FREE'


def test_authority_never_shrinks_on_the_same_leg():
    rig = Rig()
    rig.step()
    rig.send(1.)
    ignored = rig.send(.5)
    assert ignored['accepted'] is False and ignored['reason'] == 'shrink'
    assert rig.authority()['remaining_m'] == pytest.approx(1.)
    assert rig.send(.99)['accepted'] is True  # inside the noise band: the held end stays
    assert rig.authority()['remaining_m'] == pytest.approx(1.)
    assert rig.send(.5, leg='L2')['accepted'] is True  # another leg replaces it
    assert rig.authority()['remaining_m'] == pytest.approx(.5)


def test_an_ignored_shrink_does_not_refresh_the_ttl():
    rig = Rig()
    rig.step()
    rig.send(1., ttl_s=.52)
    for _ in range(10):  # 0.5 s of shrinking sends, each ignored
        assert rig.send(.3)['accepted'] is False
        assert rig.step().linear > 0.
    decision = rig.step()
    assert decision.linear == 0. and rig.authority()['state'] == 'EXPIRED'
    assert rig.send(.3)['accepted'] is True  # after expiry a smaller end is a new authority


def test_ttl_expiry_on_cores_clock_stands_the_robot():
    rig = Rig()
    rig.step()
    rig.send(1., ttl_s=.52)
    for _ in range(10):  # 0.5 s: still inside the ttl
        assert rig.step().linear > 0.
    decision = rig.step()
    assert (decision.linear, decision.angular) == (0., 0.)
    assert rig.authority()['state'] == 'EXPIRED' and rig.m.status().reason == 'authority_expired'
    rig.send(1.)
    assert rig.step().linear > 0.


@pytest.mark.parametrize('stamp_offset, code', [(-6., 'AUTHORITY_POSE_STALE'), (.5, 'AUTHORITY_POSE_FUTURE')])
def test_a_pose_stamp_outside_the_odom_history_is_refused_and_the_robot_stands(stamp_offset, code):
    rig = Rig()
    for _ in range(3):
        rig.step()
    rig.send(1.)
    with pytest.raises(AuthorityRefused) as err:
        rig.send(2., stamp=WALL + rig.now + stamp_offset)
    assert err.value.code == code
    assert rig.authority()['state'] == 'NONE' and rig.step().linear == 0.


def test_without_fresh_odom_nothing_is_accepted_or_driven():
    rig = Rig()
    rig.step(pose=False)
    with pytest.raises(AuthorityRefused) as err:
        rig.send(1.)
    assert err.value.code == 'AUTHORITY_ODOM_STALE'
    rig.step()
    rig.send(1.)
    for _ in range(7):  # odom stops: travel cannot be measured
        decision = rig.step(pose=False)
    assert decision.linear == 0. and rig.authority()['reason'] == 'authority_odom_stale'


def test_an_odom_jump_drops_the_measurement():
    rig = Rig()
    rig.step()
    rig.send(1.)
    rig.step(dx=.5)  # a reset or jump starts a new odom run
    assert rig.step().linear == 0. and rig.authority()['state'] == 'HOLDING'


def test_body_stop_and_estop_come_before_the_authority():
    rig = Rig()
    rig.step()
    rig.send(1.)
    rig.m.observe_clearance(.01, received_at=rig.now + .05)  # something right ahead
    decision = rig.step()
    assert decision.linear == 0. and rig.m.status().reason == 'obstacle_ahead'
    assert rig.authority()['state'] == 'FREE'
    rig.m.stop('estop')
    with pytest.raises(AuthorityRefused) as err:
        rig.send(1.)
    assert err.value.code == 'LINE_FOLLOW_NOT_ACTIVE'
    assert rig.step().linear == 0.


def test_config_flag_is_a_boolean():
    with pytest.raises(ValueError, match='^authority_required must be a boolean$'):
        LineFollowConfig(authority_required='yes')
    with pytest.raises(ValueError, match='^ir_guard_enabled must be a boolean$'):  # unchanged by D-517
        LineFollowConfig(ir_guard_enabled='yes')


def test_the_stop_gap_is_from_max_linear_not_cruise():
    # Line follow may command up to max_linear (D-468 return included), not only cruise.
    rig = Rig(cruise_speed=.04, max_linear=.10)
    rig.step()
    rig.send(rig.m.config.derived_stop_gap_m(.10) - .001)
    assert rig.step().linear == 0. and rig.authority()['state'] == 'HOLDING'
    assert rig.m.config.derived_stop_gap_m(.04) < rig.m.config.derived_stop_gap_m(.10) - .001


# --- D-760 1: ttl_s up to 5 s ---

def test_a_five_second_ttl_is_free_at_4_9_s_and_expired_at_5_1_s():
    rig = Rig()
    rig.step()
    rig.send(10., ttl_s=5.)
    sent = rig.now
    while rig.now < sent + 4.9 - 1e-6:
        decision = rig.step()
    assert decision.linear > 0. and rig.authority()['state'] == 'FREE'
    while rig.now < sent + 5.1 - 1e-6:
        decision = rig.step()
    assert (decision.linear, decision.angular) == (0., 0.)
    assert rig.authority()['state'] == 'EXPIRED' and rig.m.status().reason == 'authority_expired'


def test_the_ttl_is_not_moved_by_a_wall_clock_step():
    rig = Rig()
    rig.step()
    rig.send(10., ttl_s=1.)
    rig.m._wall = lambda: WALL + rig.now + 3600.  # the wall clock jumps an hour ahead
    assert rig.step().linear > 0. and rig.authority()['expires_in_s'] == pytest.approx(.95)
    rig.m._wall = lambda: WALL + rig.now - 3600.  # and two hours back
    assert rig.step().linear > 0. and rig.authority()['expires_in_s'] == pytest.approx(.9)


# --- D-760 3: seq and shrink ---

def test_a_late_older_extend_does_not_undo_a_shrink():
    rig = Rig()
    rig.step()
    assert rig.send(1., seq=3)['accepted'] is True
    shrunk = rig.send(.4, shrink=True, seq=4)
    assert shrunk['accepted'] is True and shrunk['authority']['remaining_m'] == pytest.approx(.4)
    late = rig.send(1., seq=2)  # the extend sent before the shrink arrives after it
    assert (late['accepted'], late['reason']) == (False, 'stale_seq')
    assert rig.authority()['remaining_m'] == pytest.approx(.4)
    assert rig.send(1., seq=4)['reason'] == 'stale_seq'  # a repeat of the last seq too
    assert rig.send(1., seq=5)['accepted'] is True  # a newer extend lengthens it again
    assert rig.authority()['remaining_m'] == pytest.approx(1.)


def test_a_stale_seq_leaves_the_end_and_the_ttl_untouched():
    rig = Rig()
    rig.step()
    rig.send(1., ttl_s=.52, seq=7)
    for _ in range(10):  # 0.5 s of older requests, each ignored
        assert rig.send(2., ttl_s=5., seq=6)['accepted'] is False
        assert rig.step().linear > 0.
    assert rig.step().linear == 0. and rig.authority()['state'] == 'EXPIRED'
    assert rig.send(2., seq=6)['reason'] == 'stale_seq'  # still older after the expiry
    assert rig.step().linear == 0.


def test_seq_is_per_leg_and_outlives_a_mode_change():
    rig = Rig()
    rig.step()
    rig.send(1., seq=9)
    assert rig.send(.5, leg='L2', seq=0)['accepted'] is True  # another leg starts its own order
    assert rig.send(1., leg='L2', seq=1)['accepted'] is True
    rig.m.set_mode(LineFollowMode.OFF)
    rig.m.set_mode(CAMERA)
    rig.step()
    assert rig.send(1., leg='L2', seq=1)['reason'] == 'stale_seq'  # sent before the mode change
    assert rig.authority()['state'] == 'NONE' and rig.step().linear == 0.
    assert rig.send(1., leg='L2', seq=2)['accepted'] is True


def test_a_request_without_seq_or_shrink_behaves_as_before():
    rig = Rig()
    rig.step()
    rig.send(1.)
    assert rig.send(1.5)['accepted'] is True  # a Fleet before D-760: no order, the end extends
    assert rig.authority()['remaining_m'] == pytest.approx(1.5)
    ignored = rig.send(.5)
    assert (ignored['accepted'], ignored['reason']) == (False, 'shrink')
    assert rig.send(.5, shrink=False)['reason'] == 'shrink'
    assert rig.m._authority_seq == {}  # nothing without seq is remembered


def test_a_leg_that_has_seen_a_seq_ignores_requests_without_one():
    rig = Rig()
    rig.step()
    rig.send(1., ttl_s=.52, seq=3)
    assert rig.send(0., shrink=True, ttl_s=.52, seq=4)['accepted'] is True
    for _ in range(10):  # 0.5 s of seq-less extends: none re-extends the shrunk end or its ttl
        late = rig.send(1.)
        assert (late['accepted'], late['reason']) == (False, 'seq_required')
        assert late['authority']['remaining_m'] == pytest.approx(0.)
        assert rig.step().linear == 0. and rig.m.status().reason == 'authority_end'
    assert rig.step().linear == 0. and rig.authority()['state'] == 'EXPIRED'
    assert rig.send(1.)['reason'] == 'seq_required' and rig.step().linear == 0.
    assert rig.send(1., leg='L2')['accepted'] is True  # a leg that never had a seq keeps the old rule


def test_a_late_request_for_an_older_leg_does_not_reopen_the_newer_legs_order():
    rig = Rig()
    rig.step()
    rig.send(1., leg='L1', seq=5)
    rig.send(1., leg='L2', seq=1)
    assert rig.send(0., leg='L2', shrink=True, seq=2)['accepted'] is True
    late = rig.send(2., leg='L1', seq=4)  # an old leg's request arrives late
    assert (late['accepted'], late['reason']) == (False, 'stale_seq')
    assert rig.send(2., leg='L2', seq=1)['reason'] == 'stale_seq'  # L2's order is still remembered
    assert rig.authority()['leg_id'] == 'L2' and rig.authority()['remaining_m'] == pytest.approx(0.)
    assert rig.step().linear == 0.


def test_a_leg_is_forgotten_only_once_its_late_requests_are_older_than_the_odom_log():
    rig = Rig()
    rig.step()
    seen = WALL + rig.now
    rig.send(1., leg='L1', seq=5)
    for _ in range(199):  # the log keeps 200 samples: L1's last sight is still inside it
        rig.step()
    rig.send(1., leg='L2', seq=1)
    assert set(rig.m._authority_seq) == {'L1', 'L2'}
    for _ in range(2):
        rig.step()
    rig.send(1., leg='L2', seq=2)
    assert set(rig.m._authority_seq) == {'L2'}  # L1 was last seen before the oldest odom sample
    with pytest.raises(AuthorityRefused) as err:  # whatever was sent before that sight is older still
        rig.send(2., leg='L1', seq=4, stamp=seen)
    assert err.value.code == 'AUTHORITY_POSE_STALE'
    assert rig.authority()['state'] == 'NONE' and rig.step().linear == 0.


def test_more_live_legs_than_the_memory_holds_are_refused_not_forgotten():
    from core_features.line_follow.authority import SEQ_LEGS

    rig = Rig()
    rig.step()
    for n in range(SEQ_LEGS):
        assert rig.send(1., leg=f'L{n}', seq=1)['accepted'] is True
    full = rig.send(2., leg='one-more', seq=1)
    assert (full['accepted'], full['reason']) == (False, 'seq_legs_full')
    assert rig.authority()['leg_id'] == f'L{SEQ_LEGS-1}' and rig.authority()['remaining_m'] == pytest.approx(1.)
    assert rig.send(2., leg='L0', seq=1)['reason'] == 'stale_seq'  # the first leg was not pushed out


@pytest.mark.parametrize('held', ['none', 'expired', 'other_leg'])
def test_a_shrink_never_grants(held):
    rig = Rig()
    rig.step()
    if held == 'expired':
        rig.send(1., ttl_s=.04)
        rig.step()
    elif held == 'other_leg':
        rig.send(1., leg='L0')
        assert rig.step().linear > 0.
    answer = rig.send(1., shrink=True)
    assert (answer['accepted'], answer['reason']) == (False, 'shrink_none_held')
    assert answer['authority']['state'] == 'NONE' and rig.m._authority is None
    decision = rig.step()
    assert decision.linear == 0. and rig.m.status().reason == 'authority_none'


def test_the_gate_never_raises_a_decision():
    # D-400 policy_hold and every earlier stop hand the gate a zero decision: it stays zero even when FREE.
    rig = Rig()
    rig.step()
    rig.send(1.)
    zero = LineFollowDecision(mode=CAMERA)
    moving = LineFollowDecision(linear=.05, angular=.2, mode=CAMERA)
    assert rig.authority()['state'] == 'FREE'
    assert rig.m._authority_gate(rig.now, zero) is zero and rig.m._authority_gate(rig.now, moving) is moving
    rig.m._authority = None
    assert rig.m._authority_gate(rig.now, zero) is zero
    held = rig.m._authority_gate(rig.now, moving)
    assert (held.linear, held.angular) == (0., 0.)


def test_shrink_to_zero_holds_on_the_next_tick():
    rig = Rig()
    rig.step()
    rig.send(1., ttl_s=.5)
    assert rig.step(dx=.01).linear > 0.
    answer = rig.send(0., ttl_s=2., shrink=True)
    assert answer['accepted'] is True and answer['authority']['state'] == 'HOLDING'
    assert answer['authority']['expires_in_s'] == pytest.approx(2.)  # ttl_s refreshed
    decision = rig.step()
    assert (decision.linear, decision.angular) == (0., 0.)
    assert (rig.m.status().state, rig.m.status().reason) == ('HOLD', 'authority_end')
    for _ in range(12):  # past the first ttl: still held, not expired
        rig.step()
    assert rig.authority()['state'] == 'HOLDING'


def test_shrink_never_lengthens_the_held_end():
    rig = Rig()
    rig.step()
    rig.send(.5, ttl_s=.5)
    answer = rig.send(2., ttl_s=2., shrink=True)
    assert answer['accepted'] is True and answer['authority']['remaining_m'] == pytest.approx(.5)
    assert answer['authority']['expires_in_s'] == pytest.approx(2.)


def test_a_refused_shrink_drops_the_authority_and_the_robot_stands():
    rig = Rig()
    for _ in range(3):
        rig.step()
    rig.send(1., seq=1)
    with pytest.raises(AuthorityRefused) as err:
        rig.send(0., stamp=WALL + rig.now - 6., shrink=True, seq=3)
    assert err.value.code == 'AUTHORITY_POSE_STALE'
    assert rig.authority()['state'] == 'NONE' and rig.step().linear == 0.
    assert rig.send(1., seq=2)['reason'] == 'stale_seq'  # sent before the refused shrink, whose seq was still seen
    assert rig.step().linear == 0.


# --- D-760 2: enforced while CORE's trip lease is open ---

def _leased(**config):
    rig = Rig(**config)
    rig.leased = True
    rig.m.authority_leased = lambda: rig.leased
    return rig


def test_under_a_lease_line_follow_stands_until_the_first_authority():
    rig = _leased()
    assert rig.m._authority_seen is False and rig.m.config.authority_required is False
    for _ in range(3):
        decision = rig.step()
    assert (decision.linear, decision.angular) == (0., 0.)
    assert (rig.m.status().state, rig.m.status().reason) == ('HOLD', 'authority_none')
    assert rig.authority()['state'] == 'NONE'
    rig.send(1.)
    assert rig.step().linear > 0. and rig.authority()['state'] == 'FREE'


def test_under_a_lease_a_mode_change_still_requires_an_authority():
    rig = _leased()
    rig.step()
    rig.send(1.)
    assert rig.step().linear > 0.
    rig.m.set_mode(LineFollowMode.OFF)
    rig.m.set_mode(CAMERA)
    for _ in range(3):
        decision = rig.step()
    assert decision.linear == 0. and rig.m.status().reason == 'authority_none'


def test_a_lease_that_ends_before_the_first_authority_frees_nothing():
    rig = _leased()  # the lease opens after the mode change: latched by the first tick
    assert rig.step().linear == 0. and rig.m.status().reason == 'authority_none'
    rig.leased = False  # released, expired or taken over while line follow is still on
    for _ in range(3):
        decision = rig.step()
    assert decision.linear == 0. and rig.m.status().reason == 'authority_none'
    assert rig.authority()['state'] == 'NONE'
    rig.send(1.)
    assert rig.step().linear > 0.  # an authority still drives it
    rig.m.set_mode(LineFollowMode.OFF)
    rig.m.set_mode(CAMERA)  # the mode change ends the session: dashboard use is as before
    for _ in range(3):
        decision = rig.step()
    assert decision.linear > 0. and rig.authority() is None


def test_a_lease_open_at_the_mode_change_latches_before_any_tick():
    rig = _leased()
    rig.m.set_mode(LineFollowMode.OFF)
    rig.m.set_mode(CAMERA)  # under the lease
    rig.leased = False  # gone before the first tick or status read
    for _ in range(3):
        decision = rig.step()
    assert decision.linear == 0. and rig.m.status().reason == 'authority_none'


def test_without_a_lease_the_rule_before_d760_stands():
    rig = _leased()
    rig.leased = False  # never seen open: neither config nor a request this session
    for _ in range(3):
        decision = rig.step()
    assert decision.linear > 0. and rig.authority() is None
    rig.send(1., ttl_s=.1)  # a request this session enforces it, as before
    for _ in range(4):
        decision = rig.step()
    assert decision.linear == 0. and rig.authority()['state'] == 'EXPIRED'


def test_the_default_manager_holds_no_lease():
    assert Rig().m.authority_leased() is False


def test_earlier_stops_keep_their_reason_under_a_lease_without_authority():
    rig = _leased(ir_guard_enabled=True)  # no IR evidence yet: the D-491 guard is stale
    assert rig.step().linear == 0. and rig.m.status().reason == 'lane_guard_stale'
    rig = _leased()
    rig.step()
    rig.m.observe_clearance(.01, received_at=rig.now + .05)  # D-422: something right ahead
    assert rig.step().linear == 0. and rig.m.status().reason == 'obstacle_ahead'
    rig.m.stop('estop')
    decision = rig.step()
    assert decision.linear == 0. and (rig.m.status().state, rig.m.status().reason) == ('OFF', 'mode_off')


# --- D-758 0: the odom log is found by the stamp CORE published, its order and age on the line clock ---

@pytest.mark.parametrize('step_s', [-5., 5.])
def test_a_wall_clock_step_after_fleets_pose_finds_the_same_sample(step_s):
    rig = Rig()
    for _ in range(3):
        rig.step()
    stamp = json.loads(json.dumps(WALL + rig.now))  # snapshot odom_pose.stamp, through Fleet and back
    rig.m._wall = lambda: WALL + rig.now + step_s  # chrony steps the wall clock
    for _ in range(3):
        rig.step(dx=.01)
    assert rig.send(.5, stamp=stamp)['accepted'] is True
    assert rig.authority()['remaining_m'] == pytest.approx(.47, abs=1e-6)


def test_two_samples_on_one_wall_stamp_resolve_to_the_newest():
    rig = Rig()
    rig.step()
    rig.m._wall = lambda: WALL + 9.  # a later sample lands on this stamp after a backward step
    rig.step(dx=.01)
    rig.m._wall = lambda: WALL + rig.now - 9.
    rig.step(dx=.01)
    rig.m._wall = lambda: WALL + 9.
    rig.step(dx=.01)  # the newest sample on WALL + 9
    rig.m._wall = lambda: WALL + rig.now
    rig.step(dx=.01)
    assert rig.send(.5, stamp=WALL + 9.)['accepted'] is True
    assert rig.authority()['remaining_m'] == pytest.approx(.49, abs=1e-6)


def test_an_old_fleet_stamp_between_samples_resolves_as_before():
    rig = Rig()
    rig.step()
    stamp = WALL + rig.now + .03  # not a published stamp: the sample at or before it
    rig.step(dx=.01)
    rig.step(dx=.01)
    assert rig.send(.5, stamp=stamp)['accepted'] is True
    assert rig.authority()['remaining_m'] == pytest.approx(.48, abs=1e-6)


def test_a_backward_wall_step_does_not_forget_a_legs_seq():
    rig = Rig()
    for _ in range(3):
        rig.step()
    rig.m._wall = lambda: WALL + rig.now - 10.
    rig.step()
    stamp = rig.m._odom_log[-1][0]  # the stamp published on the stepped clock
    rig.send(1., leg='L1', seq=5, stamp=stamp)
    rig.send(1., leg='L2', seq=1, stamp=stamp)
    assert set(rig.m._authority_seq) == {'L1', 'L2'}
    assert rig.send(2., leg='L1', seq=4, stamp=stamp)['reason'] == 'stale_seq'
