"""Real CORE arbitration consuming the absorbed Control semantic policy."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import logging

import pytest

from core_features.command.arbitration import Mode, ModeMachine, SourceRegistry
from core_features.command.manager import CommandManager, Twist
from core_features.safety.manager import SafetyManager, SpeedLimits, BatteryPolicy


@pytest.fixture
def linked(monkeypatch):
    # Host tests use the absorbed package in this checkout, never the archive.
    monkeypatch.syspath_prepend(str((Path(__file__).resolve().parents[4] / "src" / "runtime") / 'control'))
    from control.control.command_gate import CommandPolicy, GateInputs, GateSnapshot
    policy = CommandPolicy('revision-1')
    safety = SafetyManager(SpeedLimits(), BatteryPolicy())
    # These contract tests exercise policy semantics, not host scheduling.
    # The dedicated budget test below replaces this clock with over-budget
    # ticks; keeping the default deterministic prevents suite load from
    # turning a collision-limit assertion into an unrelated e-stop.
    safety._policy_clock = lambda: 1.0
    modes = ModeMachine()
    command = CommandManager(SourceRegistry(), modes, safety)
    safety.bind_control_policy(policy)
    modes.transition(Mode.NAVIGATION)
    snapshot = GateSnapshot(policy.session, 1, 'revision-1', 10., 10.2, GateInputs())
    assert policy.update(snapshot)
    return command, safety, modes, policy, snapshot


def test_real_control_obstacle_restriction_and_explicit_escape(linked):
    command, safety, modes, policy, snapshot = linked
    assert policy.update(replace(snapshot, sequence=2, inputs=replace(snapshot.inputs, obstacle=True)))
    command.set_nav_twist(Twist(.1, 0.), now=10.)
    assert command.select_output(now=10.01) == Twist()
    assert not safety.estop
    command.set_nav_twist(Twist(-.1, 0.), now=10.02)
    assert command.select_output(now=10.03) == Twist(-.1, 0.)
    command.set_nav_twist(Twist(0., .2), now=10.04)
    assert command.select_output(now=10.05) == Twist(0., .2)


def test_expired_observation_stops_a_fresh_command(linked):
    command, safety, modes, policy, snapshot = linked
    command.set_nav_twist(Twist(.1, 0.), now=10.21)
    assert command.select_output(now=10.22) == Twist()
    assert safety.estop


def test_policy_failure_is_logged_once_after_the_zero_writer(linked, monkeypatch, caplog):
    from core.bridge.cmd_vel import cmd_vel_cycle
    command, safety, modes, policy, snapshot = linked
    command.set_nav_twist(Twist(.1, 0.), now=10.21)
    select = command.select_output
    monkeypatch.setattr(command, 'select_output', lambda: select(now=10.22))
    sent = []
    def send(out):
        assert not caplog.records
        sent.append(out)
    with caplog.at_level(logging.ERROR, logger='core_features.safety.manager'):
        cmd_vel_cycle(command, SimpleNamespace(on_activity=lambda _: None), send)
        command.announce_pending()
    assert sent == [Twist()]
    assert safety.estop and modes.mode is Mode.EMERGENCY
    assert len(caplog.records) == 1
    assert 'snapshot_expired' in caplog.text
    assert "'observed_at': 10.0" in caplog.text
    assert 'command=1' in caplog.text and 'now=10.22' in caplog.text
    assert issubclass(caplog.records[0].exc_info[0], ValueError)   # PolicyObservationUnavailable


def test_genuine_exception_keeps_traceback_and_first_failure(linked, monkeypatch, caplog):
    command, safety, modes, policy, snapshot = linked
    def broken(*args, **kwargs):
        raise RuntimeError('diagnostic-test-failure')
    monkeypatch.setattr(policy, 'evaluate', broken)
    safety.bind_control_policy(policy)
    assert safety.evaluate_candidate(11, 'navigation', .1, 0., 10.1) is None
    assert safety.evaluate_candidate(12, 'navigation', .1, 0., 10.1) is None
    with caplog.at_level(logging.ERROR, logger='core_features.safety.manager'):
        command.announce_pending()
    assert len(caplog.records) == 1
    assert 'command=11' in caplog.text and 'command=12' not in caplog.text
    assert 'diagnostic-test-failure' in caplog.text
    assert caplog.records[0].exc_info[0] is RuntimeError


def test_failed_zero_writer_retains_diagnostic_until_a_successful_cycle(linked, monkeypatch, caplog):
    from core.bridge.cmd_vel import cmd_vel_cycle
    command, safety, modes, policy, snapshot = linked
    command.set_nav_twist(Twist(.1, 0.), now=10.21)
    select = command.select_output
    monkeypatch.setattr(command, 'select_output', lambda: select(now=10.22))
    power = SimpleNamespace(on_activity=lambda _: None)
    def broken(out):
        raise RuntimeError('writer failed')
    with caplog.at_level(logging.ERROR, logger='core_features.safety.manager'):
        with pytest.raises(RuntimeError, match='writer failed'):
            cmd_vel_cycle(command, power, broken)
        assert not caplog.records
        sent = []
        cmd_vel_cycle(command, power, sent.append)
    assert sent == [Twist()] and safety.estop
    assert len(caplog.records) == 1 and 'snapshot_expired' in caplog.text


def test_failed_diagnostic_sink_cannot_escape_or_change_the_latched_zero(linked, monkeypatch):
    command, safety, modes, policy, snapshot = linked
    command.set_nav_twist(Twist(.1, 0.), now=10.21)
    assert command.select_output(now=10.22) == Twist()
    def broken(*args, **kwargs):
        raise RuntimeError('sink failed')
    monkeypatch.setattr(logging.getLogger('core_features.safety.manager'), 'error', broken)
    command.announce_pending()
    assert command.announce_errors == 1
    assert safety.estop and modes.mode is Mode.EMERGENCY
    assert command.select_output(now=10.23) == Twist()
    command.announce_pending()
    assert command.announce_errors == 1


def test_snapshot_speed_limit_reaches_core_before_final_clip(linked):
    command, safety, modes, policy, snapshot = linked
    assert policy.update(replace(snapshot, sequence=2, linear_limit=.005))
    command.set_nav_twist(Twist(.01, .2), now=10.)
    output = command.select_output(now=10.01)
    assert output.linear == pytest.approx(.005)
    assert output.angular == pytest.approx(.1)
    assert safety.policy_reason == ''


def test_repeated_read_or_replayed_update_cannot_extend_observation(linked):
    command, safety, modes, policy, snapshot = linked
    assert not policy.update(replace(snapshot, expires_at=10.4))
    command.set_nav_twist(Twist(.1, 0.), now=10.)
    assert command.select_output(now=10.1) == Twist(.1, 0.)
    command.set_nav_twist(Twist(.1, 0.), now=10.25)
    assert command.select_output(now=10.26) == Twist()
    assert safety.estop


@pytest.mark.parametrize('changes', [
    {'calibration_revision': 'other'}, {'session': 'previous-process'},
    {'observed_at': 11.}, {'expires_at': 12.}, {'sequence': True},
    {'linear_limit': float('nan')}, {'linear_limit': -.01},
])
def test_invalid_or_wrong_identity_snapshot_cannot_authorize_motion(linked, changes):
    command, safety, modes, policy, snapshot = linked
    policy.invalidate()
    policy.update(replace(snapshot, **({'sequence': 2} | changes)))
    command.set_nav_twist(Twist(.1, 0.), now=10.)
    assert command.select_output(now=10.01) == Twist()
    assert safety.estop


def test_rebinding_policy_discards_old_candidate(linked):
    command, safety, modes, policy, snapshot = linked
    command.set_nav_twist(Twist(.1, 0.), now=10.)
    safety.bind_control_policy(policy)
    assert command.select_output(now=10.01) == Twist()


def test_sensor_receive_and_source_clocks_reach_core_expiry(linked):
    from control.sensing.observation import Observations
    command, safety, modes, policy, snapshot = linked
    samples = Observations(max_age=.5)
    samples.add('lidar', 10.1, source=100., source_now=100.1)
    samples.add('imu', 10.1)
    assert policy.update_observations(samples, ('lidar', 'imu'), snapshot.inputs, 10.1, 2, policy.revision)
    command.set_nav_twist(Twist(.1, 0.), now=10.1)
    assert command.select_output(now=10.2) == Twist(.1, 0.)
    # A fresh command does not make the old scan fresh.
    command.set_nav_twist(Twist(.1, 0.), now=10.51)
    assert command.select_output(now=10.52) == Twist()
    assert safety.estop


def test_geometry_permission_is_recomputed_for_each_selected_candidate(linked):
    from control.control.lidar_guard import TranslationEvidence
    command, safety, modes, policy, snapshot = linked
    geometry = TranslationEvidence(scan_received_at=10., scan_source_at=10., enabled=True,
        lidar_fresh=True, mount=(-.017, 0.), travel=(.02, .02), radius=.076, ranges=(.2,) * 6,
        radial_front=True, radial_rear=True, previous_front=True, previous_rear=True,
        linear_gains=(1., 1.))
    assert policy.update(replace(snapshot, sequence=2, translation=geometry))
    command.set_nav_twist(Twist(.01, 0.), now=10.)
    assert command.select_output(now=10.01) == Twist(.01, 0.)
    command.set_nav_twist(Twist(.1, 0.), now=10.02)
    assert command.select_output(now=10.03) == Twist()
    assert not safety.estop
    command.set_nav_twist(Twist(.01, .1), now=10.04)
    # D-424 (F): the arc's translation is refused, its clear turn passes in place.
    assert command.select_output(now=10.05) == Twist(0., .1)
    command.set_nav_twist(Twist(-.01, 0.), now=10.06)
    assert command.select_output(now=10.07) == Twist(-.01, 0.)
    # A tighter non-lidar restriction remains in force.
    assert policy.update(replace(snapshot, sequence=3, translation=geometry,
                                 inputs=replace(snapshot.inputs, obstacle=True)))
    command.set_nav_twist(Twist(.01, 0.), now=10.08)
    assert command.select_output(now=10.09) == Twist()


def test_geometry_deadline_is_not_extended_by_snapshot_publication(linked):
    from control.control.lidar_guard import TranslationEvidence
    command, safety, modes, policy, snapshot = linked
    geometry = TranslationEvidence(9.9, 9.9, True, True, (-.017, 0.), (.02, .02), .076,
                                   (.2,) * 6, True, True, True, True, (1., 1.))
    assert policy.update(replace(snapshot, sequence=2, translation=geometry))
    command.set_nav_twist(Twist(.01, 0.), now=10.15)
    assert command.select_output(now=10.16) == Twist()
    assert not safety.estop


def test_sensor_updates_cannot_silently_drop_required_geometry(linked):
    from control.control.lidar_guard import TranslationEvidence
    from control.sensing.observation import Observations
    command, safety, modes, policy, snapshot = linked
    geometry = TranslationEvidence(10., 10., True, True, (-.017, 0.), (.02, .02), .076,
                                   (.2,) * 6, True, True, True, True, (1., 1.))
    samples = Observations(max_age=.2)
    samples.add('lidar', 10.)
    assert policy.update_observations(samples, ('lidar',), snapshot.inputs, 10.01, 2,
                                      policy.revision, translation=geometry)
    assert not policy.update_observations(samples, ('lidar',), snapshot.inputs, 10.02, 3, policy.revision)
    command.set_nav_twist(Twist(.1, 0.), now=10.02)
    assert command.select_output(now=10.03) == Twist()
    assert safety.estop


def test_tracked_obstacle_uses_current_candidate_direction(linked):
    from control.control.obstacle_risk import TrackedEvidence
    command, safety, modes, policy, snapshot = linked
    tracks = {'stamp': 100., 'frame': 'odom', 'tracks': [dict(position=[.2, 0.], velocity=[0., 0.],
              radius=.02, age=0., observed=True, state='stationary')]}
    camera = {'stamp': 100., 'blocked': False}
    evidence = TrackedEvidence.capture(tracks, camera, (0., 0., 0.), 100.,
                                       source_now=100., received_at=10., radius=.076, margin=.02)
    assert policy.update(replace(snapshot, sequence=2, tracking=evidence))
    command.set_nav_twist(Twist(.1, 0.), now=10.)
    assert command.select_output(now=10.01) == Twist()
    assert not safety.estop
    command.set_nav_twist(Twist(-.1, 0.), now=10.02)
    assert command.select_output(now=10.03) == Twist(-.1, 0.)
    # Mutating the producer's original packet cannot rewrite the snapshot.
    tracks['tracks'].clear()
    command.set_nav_twist(Twist(.1, 0.), now=10.04)
    assert command.select_output(now=10.05) == Twist()


def test_tracking_source_delay_and_missing_updates_stop_core(linked):
    from control.control.obstacle_risk import TrackedEvidence
    command, safety, modes, policy, snapshot = linked
    evidence = TrackedEvidence.capture({'stamp': 99.75, 'frame': 'odom', 'tracks': []},
        {'stamp': 100., 'blocked': False}, (0., 0., 0.), 100.,
        source_now=100., received_at=10., radius=.076, margin=.02)
    assert policy.update(replace(snapshot, sequence=2, tracking=evidence))
    command.set_nav_twist(Twist(.1, 0.), now=10.1)
    assert command.select_output(now=10.11) == Twist()
    assert safety.estop
    assert not policy.update(replace(snapshot, sequence=3))


@pytest.fixture
def simulation_actuation(linked, monkeypatch):
    from control.control.actuation import SimulationActuation
    command, safety, modes, policy, snapshot = linked
    monkeypatch.setenv('ROSY_SIMULATION_ACTUATION', '1')
    calibration = SimulationActuation(revision=policy.revision, observed_at=10., expires_at=10.2,
        linear_gains=(1.25, .75), angular_gains=(1., 1.), linear_sign=-1.,
        points=((.5, 0.), (0., .5), (-.5, 0.), (0., -.5)), center=(0., 0.), uncertainty=.003,
        body_radius=.076, scan_received_at=10., scan_source_at=10., scan_complete=True)
    safety.bind_simulation_actuation(calibration, simulation_clock_enabled=lambda: True)
    return (*linked, calibration)


def test_calibrated_final_candidate_is_swept_and_signed_by_core(simulation_actuation):
    command, safety, modes, policy, snapshot, calibration = simulation_actuation
    command.set_nav_twist(Twist(.01, 0.), now=10.)
    assert command.select_output(now=10.01) == Twist(pytest.approx(-.0125), 0.)
    safety.set_session_speed(.005)
    command.set_nav_twist(Twist(.01, 0.), now=10.02)
    assert command.select_output(now=10.03) == Twist(pytest.approx(-.005), 0.)


def test_final_sweep_blocks_collision_without_synthesizing_escape(simulation_actuation):
    command, safety, modes, policy, snapshot, calibration = simulation_actuation
    safety.bind_simulation_actuation(replace(calibration, points=((.08, 0.), (1., 1.), (-1., 1.))),
                                    simulation_clock_enabled=lambda: True)
    command.set_nav_twist(Twist(.01, 0.), now=10.)
    assert command.select_output(now=10.01) == Twist()
    assert not safety.estop


def test_bounded_arc_uses_final_sweep_instead_of_full_spin_permission(simulation_actuation):
    command, safety, modes, policy, snapshot, calibration = simulation_actuation
    assert policy.update(replace(snapshot, sequence=2,
        inputs=replace(snapshot.inputs, bounded_motion=True, can_rotate=False)))
    command.set_nav_twist(Twist(.005, .05), now=10.)
    assert command.select_output(now=10.01) == Twist(-.005, .05)
    assert not safety.estop


def test_actuation_environment_change_and_policy_rebind_cannot_reuse_calibration(simulation_actuation, monkeypatch):
    command, safety, modes, policy, snapshot, calibration = simulation_actuation
    monkeypatch.setenv('ROSY_SIMULATION_ACTUATION', '0')
    command.set_nav_twist(Twist(.01, 0.), now=10.)
    assert command.select_output(now=10.01) == Twist()
    assert safety.estop
    monkeypatch.setenv('ROSY_SIMULATION_ACTUATION', '1')
    safety.bind_control_policy(policy)
    safety.release('administrator')
    modes.release_emergency()
    modes.transition(Mode.NAVIGATION)
    command.set_nav_twist(Twist(.01, 0.), now=10.02)
    assert command.select_output(now=10.03) == Twist()
    assert safety.estop


def test_complete_policy_and_actuation_budget_is_enforced(simulation_actuation):
    command, safety, modes, policy, snapshot, calibration = simulation_actuation
    ticks = iter([1., 1.001, 1.021])
    safety._policy_clock = lambda: next(ticks)
    command.set_nav_twist(Twist(.01, 0.), now=10.)
    assert command.select_output(now=10.01) == Twist()
    assert safety.estop


def test_simulation_clock_must_remain_enabled(simulation_actuation):
    command, safety, modes, policy, snapshot, calibration = simulation_actuation
    enabled = [True]
    safety.bind_simulation_actuation(calibration, simulation_clock_enabled=lambda: enabled[0])
    enabled[0] = False
    command.set_nav_twist(Twist(.01, 0.), now=10.)
    assert command.select_output(now=10.01) == Twist()
    assert safety.estop


def test_new_sequence_cannot_refresh_the_same_sensor_sample(linked):
    command, safety, modes, policy, snapshot = linked
    assert not policy.update(replace(snapshot, sequence=2, expires_at=10.4))
    command.set_nav_twist(Twist(.1, 0.), now=10.25)
    assert command.select_output(now=10.26) == Twist()
    assert safety.estop


@pytest.mark.parametrize('changes', [{'pickup': True}, {'localization_ready': False},
                                   {'observation_failure': 'imu_unavailable'},
                                   {'legacy_tilt_recovery': True}, {'bounded_motion': True},
                                   {'can_rotate': 1}, {'profile_valid': 'true'}])
def test_hazard_or_unintegrated_actuation_mode_stops(linked, changes):
    command, safety, modes, policy, snapshot = linked
    policy.update(replace(snapshot, sequence=2, inputs=replace(snapshot.inputs, **changes)))
    command.set_nav_twist(Twist(.1, 0.), now=10.)
    assert command.select_output(now=10.01) == Twist()
    assert safety.estop


# D-400 4: the real CommandPolicy's missing / future / expired observation is a sensor gap.

def hold_two_seconds(linked):
    command, safety, modes, policy, snapshot = linked
    clock = [100.]
    safety._policy_clock = lambda: clock[0]
    safety.bind_control_policy(policy, 2.)
    return clock


def drive(command, now):
    command.set_nav_twist(Twist(.1, 0.), now=now)
    return command.select_output(now=now + .01)


@pytest.mark.parametrize('gap', ['snapshot_expired', 'snapshot_future', 'snapshot_missing'])
def test_observation_gap_holds_resumes_and_latches_after_the_hold(linked, gap):
    command, safety, modes, policy, snapshot = linked
    clock = hold_two_seconds(linked)
    if gap == 'snapshot_missing':
        policy.invalidate()
    assert drive(command, 9.9 if gap == 'snapshot_future' else 10.21) == Twist()
    assert not safety.estop and modes.mode is Mode.NAVIGATION
    assert safety.policy_hold and safety.policy_reason == 'policy_failed'
    assert policy.update(replace(snapshot, sequence=2, observed_at=10.3, expires_at=10.5))
    clock[0] = 100.1
    assert drive(command, 10.31) == Twist(.1, 0.)
    assert not safety.policy_hold and not safety.estop
    clock[0] = 101.
    assert drive(command, 10.6) == Twist() and not safety.estop      # a new gap: expired again
    for step in range(1, 5):                                          # asked on, every 0.4 s
        clock[0] = 101. + step * .4
        assert drive(command, 10.6 + step * .01) == Twist() and not safety.estop
    clock[0] = 103.
    assert drive(command, 10.7) == Twist()
    assert safety.estop and safety.estop_source == 'control:policy_failed'
    assert modes.mode is Mode.EMERGENCY


def test_held_gap_is_logged_when_it_opens_and_when_it_latches(linked, caplog):
    command, safety, modes, policy, snapshot = linked
    clock = hold_two_seconds(linked)
    with caplog.at_level(logging.ERROR, logger='core_features.safety.manager'):
        for step in range(3):
            clock[0] = 100. + step * .02
            assert drive(command, 10.21 + step * .02) == Twist()
            command.announce_pending()
        assert len(caplog.records) == 1 and 'snapshot_expired' in caplog.text
        assert not safety.estop
        for step in range(1, 6):
            clock[0] = 100.04 + step * .4
            assert drive(command, 10.25 + step * .01) == Twist()
            command.announce_pending()
    assert safety.estop and len(caplog.records) == 2


def test_a_stand_still_between_two_stalls_is_two_gaps(linked):
    """Review: a gap tick, 3 s without a question (zero commands at a junction), another gap
    tick: a new 2 s hold, not a latch. Asked on without a break it still latches at 2 s."""
    command, safety, modes, policy, snapshot = linked
    clock = hold_two_seconds(linked)
    assert drive(command, 10.21) == Twist() and safety.policy_hold
    clock[0] = 103.5
    assert drive(command, 10.22) == Twist()
    assert safety.policy_hold and not safety.estop and modes.mode is Mode.NAVIGATION


def test_genuine_exception_latches_at_once_even_with_a_hold(linked, monkeypatch):
    command, safety, modes, policy, snapshot = linked
    def broken(*args, **kwargs):
        raise RuntimeError('diagnostic-test-failure')
    monkeypatch.setattr(policy, 'evaluate', broken)
    hold_two_seconds(linked)
    assert drive(command, 10.) == Twist()
    assert safety.estop and safety.estop_source == 'control:policy_failed'
    assert not safety.policy_hold
