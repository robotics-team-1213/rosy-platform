"""A transient evidence gap while stationary at zero holds, bounded; it is not a trial failure.

Rig evidence (2026-09-23): endpoint registration blocks this node's executor for
0.3-0.6 s, so its own gate/scan inputs go briefly stale while the robot is at
zero. Moving trials, e-stop and hard hazards must still fail at once.
"""
import math
from types import SimpleNamespace as NS

from test.mixin_method import mixin_method

LAPSE = 'Fresh final safety command evidence required'
HAZARDS = ('/safety/blocked', '/safety/cliff', '/safety/tilt', '/safety/pickup')


def method(name, monotonic=10.):
    return mixin_method('control.calibration_rotation', name, time=NS(monotonic=lambda: monotonic))


def node(speed=0., gate=LAPSE, clear=True, clearance='current_safety_gate_clearance'):
    calls = []
    trial = NS(last_speed=speed, last_time=10., started=8., leg_started=10., index=0,
               targets=[0.]*10, error=None, done=False, update=lambda *args: .06)
    state = NS(rotation_phase_started=9., rotation_trial=trial, wander_state=('stop', 10.), requested=0.,
               rotation_handoff_started=None, rotation_wait=0., rotation_start_observation_wait=None,
               rotation_imu_yaw=.18, rotation_imu_origin=0., rotation_odom_origin=(0., 0., 0.),
               rotation_alignment={'yaw': .18}, rotation_clearance_diagnostic={'reason': clearance},
               pose=(0., 0., .18), last_report=10., message='',
               phase='validating_rotation', estop=False, hazards={}, gate=gate, clear=clear,
               gate_decision=None, rotation_scan=None, relocation_scan_deadline=99.,
               zero=lambda: calls.append('zero'), publish=lambda: calls.append('publish'),
               finish=lambda *args: calls.append(args),
               drive_trial=lambda angular=0.: calls.append(('drive', angular)),
               pause_rotation_scan=lambda now: False)
    # Like control.calibration.Baseline: rows are (seen, value, valid); latest() is the
    # newest row's value only when that row is valid.
    state.baseline = NS(samples={})
    state.baseline.latest = lambda name: (
        state.baseline.samples[name][-1][1] if state.baseline.samples.get(name) and
        state.baseline.samples[name][-1][2] else None)
    state.trial_gate_reason = lambda now: state.gate
    state.rotation_clear = lambda now: state.clear
    for name in ('rotation_eligibility', 'rotation_hazard', 'hold_freshness_lapse'):
        bound = method(name)
        setattr(state, name, lambda *args, bound=bound, **kwargs: bound(state, *args, **kwargs))
    return state, calls


def fresh(state, now):
    """Sources that keep reporting fresh, valid, hazard-free rows; odom carries the pose."""
    state.wander_state = ('stop', now)
    state.baseline.samples = {name: [(now, state.pose if name == 'odom' else None, True)]
                              for name in ('odom', 'imu', 'ir', 'tf')}
    state.hazards = {key: (now, False) for key in HAZARDS}


def tick(state, now, monotonic=None):
    fresh(state, now)
    method('tick_rotation', now if monotonic is None else monotonic)(state, now)


def test_stationary_gate_lapse_holds_zero_instead_of_failing():
    state, calls = node()
    tick(state, 10.1)
    assert calls == ['zero']
    assert state.rotation_trial.last_time == 10.1  # a held interval is not integrated as motion


def test_stationary_stale_sensor_lapse_holds_zero():
    state, calls = node(gate=None)
    fresh(state, 10.1)
    state.baseline.samples['odom'] = [(9.7, state.pose, True)]  # 0.4 s old: stale, still valid
    method('tick_rotation')(state, 10.1)
    assert calls == ['zero']


def test_stale_queued_odom_marked_invalid_still_holds_on_the_last_valid_pose():
    # Rig 2026-09-23 (prof-fix-2/6): after the block, the queued odom fails stamped(.25)
    # and is recorded invalid, so latest('odom') is None although the pose is known.
    state, calls = node()
    fresh(state, 10.1)
    state.baseline.samples['odom'] = [(9.9, state.pose, True), (10.1, state.pose, False)]
    method('tick_rotation')(state, 10.1)
    assert calls == ['zero']


def test_no_valid_odom_at_all_is_not_held():
    state, calls = node()
    fresh(state, 10.1)
    state.baseline.samples['odom'] = [(10.1, state.pose, False)]
    method('tick_rotation')(state, 10.1)
    assert calls == [(False, LAPSE)]


def test_stationary_stale_scan_clearance_holds_zero():
    state, calls = node(gate=None, clear=False, clearance='stale_scan')
    tick(state, 10.1)
    assert calls == ['zero']


def test_moving_trial_still_fails_at_once():
    state, calls = node(speed=.06)
    tick(state, 10.1)
    assert calls == [(False, LAPSE)]


def test_estop_during_a_lapse_fails_at_once():
    state, calls = node()
    fresh(state, 10.1)
    state.estop = True
    method('tick_rotation')(state, 10.1)
    assert calls == [(False, LAPSE)]  # the gate lapse is reported first, but nothing is held


def test_hard_hazard_during_a_lapse_fails_at_once():
    for key in ('/safety/cliff', '/safety/tilt', '/safety/pickup'):
        state, calls = node()
        fresh(state, 10.1)
        state.hazards[key] = (10.1, True)
        method('tick_rotation')(state, 10.1)
        assert calls == [(False, LAPSE)], key


def test_hard_hazard_alone_still_fails_at_once_while_stationary():
    state, calls = node(gate=None)
    fresh(state, 10.1)
    state.hazards['/safety/pickup'] = (10.1, True)
    method('tick_rotation')(state, 10.1)
    assert calls == [(False, 'Rotation safety hazard or missing state')]


def test_non_finite_imu_yaw_is_not_held():
    state, calls = node()
    state.rotation_imu_yaw = math.nan
    tick(state, 10.1)
    assert calls == [(False, LAPSE)]


def test_hold_is_bounded_to_one_second():
    state, calls = node()
    tick(state, 10.1)
    tick(state, 11.2)
    assert calls[-1][0] is False
    assert calls[-1][1].startswith(LAPSE)


def test_hold_fails_if_the_stationary_pose_changes():
    state, calls = node()
    tick(state, 10.1)
    state.pose = (.003, 0., .18)
    tick(state, 10.2)
    assert calls[-1][0] is False
    assert 'stationary pose changed' in calls[-1][1]


def test_fresh_evidence_resumes_the_trial_and_rearms_the_bound():
    state, calls = node()
    tick(state, 10.1)
    state.gate = None
    tick(state, 10.3)
    assert ('drive', .06) in calls
    state.gate = LAPSE
    state.rotation_trial.last_speed = 0.
    before = len(calls)
    tick(state, 11.2)  # 1.1 s after the first hold began: only a re-armed bound still holds
    assert calls[before:] == ['zero', 'publish']  # held and reported, not failed


def settle_then_move(trial):
    """First update settles an endpoint (index advances at zero); later ones start the next leg."""
    def update(*args):
        if trial.index == 0:
            trial.index, trial.last_speed = 1, 0.
            return 0.
        trial.last_speed = .06
        return .06
    return update


def test_next_leg_waits_for_evidence_received_after_endpoint_registration():
    # Rig 2026-09-23 (prof-fix-4): the sim clock is frozen while registration blocks,
    # so the next tick sees "fresh" evidence on a stale clock and must not start a leg.
    state, calls = node(gate=None)
    state.gate_decision, state.rotation_scan = (10.3, {'id': 'a'}), (10.1, 'a')
    state.rotation_trial.update = settle_then_move(state.rotation_trial)
    state.record_rotation_endpoint = lambda alignment, odom: True
    tick(state, 10.1)
    tick(state, 10.15)  # nothing new received since registration
    assert ('drive', .06) not in calls
    assert calls[-1] == 'zero'
    state.gate_decision = (99., {'id': 'b'})
    tick(state, 10.2)  # a new decision, but the scan is still the pre-registration one
    assert ('drive', .06) not in calls
    state.rotation_scan = (99., 'b')
    tick(state, 10.25)
    assert calls[-1] == ('drive', .06)


def test_barrier_release_is_not_counted_as_a_stall_on_a_frozen_sim_clock():
    # The sim clock is frozen during registration, so monotonic() then equals the tick's
    # now; the executor may deliver new evidence before the next tick at now+0.6.
    state, calls = node(gate=None)
    state.gate_decision, state.rotation_scan = (10.3, {'id': 'a'}), (10.1, 'a')
    trial = state.rotation_trial
    steps = []

    def update(now, *args):  # like RotationTrial.update: a gap over 0.5 s is a stall
        steps.append(now-trial.last_time)
        trial.last_time = now
        if trial.index == 0:
            trial.index, trial.last_speed = 1, 0.
            return 0.
        trial.last_speed = .06
        return .06
    trial.update = update
    state.record_rotation_endpoint = lambda alignment, odom: True
    tick(state, 10.1, monotonic=10.1)
    state.gate_decision, state.rotation_scan = (99., {'id': 'b'}), (99., 'b')
    tick(state, 10.7)
    assert steps[-1] <= .5
    assert calls[-2:] == [('drive', .06), 'publish']


def test_refused_barrier_hold_names_the_missing_pose_evidence():
    state, calls = node(gate=None)
    state.gate_decision, state.rotation_scan = (10.3, {'id': 'a'}), (10.1, 'a')
    state.rotation_trial.update = settle_then_move(state.rotation_trial)
    state.record_rotation_endpoint = lambda alignment, odom: True
    tick(state, 10.1)
    state.rotation_imu_yaw = float('nan')
    tick(state, 10.15)
    assert calls[-1] == (False, 'Rotation evidence barrier requires finite pose evidence')


def test_barrier_needs_evidence_that_outlasts_the_next_tick():
    # Rig 2026-09-23 (prof-fix-4, second run): after a 0.61 s block the first queued
    # decision was accepted at age 0.244 s, 6 ms from expiry. It released the barrier,
    # the leg started, and the moving trial failed one tick later.
    state, calls = node(gate=None)
    state.gate_decision, state.rotation_scan = (10.3, {'id': 'a'}), (10.1, 'a')
    state.rotation_trial.update = settle_then_move(state.rotation_trial)
    state.record_rotation_endpoint = lambda alignment, odom: True
    tick(state, 10.1)
    state.gate_decision, state.rotation_scan = (10.506, {'id': 'b'}), (10.5, 'b')
    tick(state, 10.5)  # new, but expiring in 6 ms
    assert ('drive', .06) not in calls
    state.gate_decision = (10.8, {'id': 'c'})
    tick(state, 10.66)  # the scan received at 10.5 has 0.09 s of its 0.25 s receipt window left
    assert ('drive', .06) not in calls
    state.rotation_scan = (10.66, 'c')
    tick(state, 10.66)
    assert calls[-2:] == [('drive', .06), 'publish']


def test_barrier_scan_margin_uses_receipt_age_not_header_age():
    # A driver that stamps at scan start (5-10 Hz) delivers header ages of 0.1-0.2 s;
    # the trial's clearance judges receipt age, and so must the barrier.
    state, calls = node(gate=None)
    state.gate_decision, state.rotation_scan = (10.3, {'id': 'a'}), (10.1, 'a')
    state.rotation_trial.update = settle_then_move(state.rotation_trial)
    state.record_rotation_endpoint = lambda alignment, odom: True
    tick(state, 10.1)
    state.gate_decision, state.rotation_scan = (10.8, {'id': 'b'}), (10.6, 'b')
    state.relocation_scan_deadline = 10.62  # header already 0.18 s old at receipt
    tick(state, 10.6)
    assert calls[-2:] == [('drive', .06), 'publish']


def test_evidence_barrier_after_registration_is_bounded():
    state, calls = node(gate=None)
    state.gate_decision, state.rotation_scan = (10.3, {'id': 'a'}), (10.1, 'a')
    state.rotation_trial.update = settle_then_move(state.rotation_trial)
    state.record_rotation_endpoint = lambda alignment, odom: True
    tick(state, 10.1)
    tick(state, 10.15)
    tick(state, 11.3)
    assert calls[-1][0] is False
    assert calls[-1][1].startswith(LAPSE)


def test_endpoint_registration_time_is_not_counted_as_a_stall():
    state, calls = node(gate=None)
    trial = state.rotation_trial

    def update(*args):  # the leg settles: the index advances at zero speed
        trial.index, trial.last_speed, trial.last_time = 1, 0., 10.1
        return 0.
    trial.update = update
    state.record_rotation_endpoint = lambda alignment, odom: True
    tick(state, 10.1, monotonic=10.7)  # registration finished 0.6 s after the tick began
    assert trial.last_time == 10.7
    assert ('drive', 0.) in calls
