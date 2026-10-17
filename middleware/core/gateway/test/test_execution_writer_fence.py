"""Private restriction on the actual sole writer; synthetic bounds, no device permit."""
from dataclasses import replace
import copy
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest

from core.bridge.cmd_vel import cmd_vel_cycle
from core_common.protocol.native_receipts import BOOT_ID
from core_features.command.arbitration import Mode, ModeMachine, SourceRegistry
from core_features.command.manager import CommandManager, Twist
from core_features.command._execution_budget import Budget, Limits, Pose
from core_features.command._execution_ledger import Ledger, ExecutionIdentity, ChildIdentity
from core_features.safety.manager import SafetyManager, SpeedLimits, BatteryPolicy


def setup(*, admit=True, duration=10.):
    clock = [10.]
    modes = ModeMachine()
    command = CommandManager(SourceRegistry(), modes, SafetyManager(SpeedLimits(), BatteryPolicy()))
    ledger = Ledger(robot_id='synthetic', boot_id=BOOT_ID, profile_revision='SYNTHETIC',
                    max_parents=8, max_children=8, clock=lambda: clock[0])
    fence = command._install_execution_restriction(ledger)
    assert fence is not None
    select = command.select_output
    command.select_output = lambda now=None: select(now=clock[0])
    identity = ExecutionIdentity('synthetic', BOOT_ID, uuid4(), 'SYNTHETIC',
                                 'map', '1', 'odom', 'epoch', '0' * 64)
    limits = Limits('SYNTHETIC', 1., 2., 2., 4., .1, .2, .1, .01, .5, .4, 10.)
    pose = Pose(1000000000, 1000000000, 'odom', 'epoch', 0., 0.)
    budget = Budget(limits=limits, initial=pose, before_mono=10., after_mono=10.,
                    now_utc=100., captured_utc=99.9, admit_until_utc=100.1,
                    duration_s=duration, path_m=10., rotation_rad=20., radius_m=5.)
    parent = fence.admit(identity, budget) if admit else None
    child = ChildIdentity('navigation', BOOT_ID, uuid4(), 1)
    if admit:
        assert parent is not None and fence.attach(parent, child)
    assert modes.transition(Mode.NAVIGATION)[0]
    command.set_nav_twist(Twist(.1, -.1), now=10.)
    return SimpleNamespace(**locals())


def cycle(s, **kwargs):
    sent = []
    cmd_vel_cycle(s.command, SimpleNamespace(on_activity=lambda _: None), sent.append, **kwargs)
    return sent


def test_installed_restriction_waits_for_parent_and_child_on_actual_cycle():
    s = setup(admit=False)
    assert cycle(s) == [Twist()]
    s = setup()
    assert cycle(s) == [Twist(.1, -.1)]
    assert s.fence.revoke(s.parent, s.child)
    assert cycle(s) == [Twist()]


@pytest.mark.parametrize('change', ['clear', 'mode', 'child', 'parent', 'payload'])
def test_original_selection_cannot_be_relabelled_after_readiness_callback(change):
    s = setup()

    def changed():
        if change == 'clear':
            s.command.clear_navigation()
        elif change == 'mode':
            s.modes.transition(Mode.IDLE)
        elif change == 'child':
            assert s.fence.advance(s.parent, s.child, replace(s.child, generation=2))
        elif change == 'parent':
            assert s.fence.stop(s.parent, 'replace') and s.fence.retire(s.parent)
            assert s.fence.admit(replace(s.identity, parent_id=uuid4()), new_budget()) is not None
        else:
            s.fence.receipt_for(s.fence._receipt.output).output.linear = .2
        return True
    assert cycle(s, motion_ready=changed) == [Twist()]


def new_budget():
    s = setup(admit=False)
    return s.budget


@pytest.mark.parametrize('change', ['child', 'parent'])
def test_policy_cannot_stamp_old_output_with_replacement_execution(change):
    s = setup()

    def policy(*args, **kwargs):
        if change == 'child':
            s.fence.advance(s.parent, s.child, replace(s.child, generation=2))
        else:
            s.fence.stop(s.parent, 'replace'); s.fence.retire(s.parent)
            s.fence.admit(replace(s.identity, parent_id=uuid4()), new_budget())
        return .1, -.1
    s.command._safety.evaluate_candidate = policy
    assert cycle(s) == [Twist()]
    assert s.command._pending_shadow is None


def test_slow_existing_trial_rechecks_budget_inside_actual_submission(tmp_path, monkeypatch):
    from core_features.command.bounded_trial import BoundedTrial, Bounds
    s = setup(duration=.95)
    trial = BoundedTrial(tmp_path / 'trial.db', trial_id='one', robot_id='synthetic',
                         boot_id='boot', frame_id='odom',
                         bounds=Bounds(.2, .5, 1., .01, .1, .2, .001, 1., 5., 'a' * 64), now=10.)
    trial.observe(x=0., y=0., stamp_ns=1, source_now_ns=1, frame_id='odom', now=10.)
    original = trial.submit_fenced

    def slow(linear, angular, submit, **kwargs):
        def delayed():
            s.clock[0] = 10.2
            return submit()
        return original(linear, angular, delayed, **kwargs)
    monkeypatch.setattr(trial, 'submit_fenced', slow)
    assert cycle(s, trial_guard=trial, now=10.) == [Twist()]
    assert s.ledger.read().state == 'STOPPED'
    trial.close()


@pytest.mark.parametrize('which', ['mode', 'ledger'])
def test_final_lock_contention_writes_zero_without_waiting_and_consumes_parent(which):
    s = setup()
    held, release = Event(), Event()
    owners = []
    lock = s.modes._lock if which == 'mode' else s.ledger._lock

    def owner():
        with lock:
            held.set()
            assert release.wait(8.)

    def gate():
        owners.append(worker.submit(owner))
        assert held.wait(2.)
        return True
    with ThreadPoolExecutor(max_workers=2) as worker:
        try:
            result = worker.submit(cycle, s, motion_ready=gate).result(timeout=2.)
            assert result == [Twist()] and not release.is_set()
        finally:
            release.set()
        for task in owners:
            task.result(timeout=2.)
    assert s.ledger.read().state == 'STOPPED'


def test_unknown_delivery_consumes_receipt_and_parent_without_motion_retry():
    s = setup(); sent = []

    def unknown(out):
        sent.append(out)
        if out.linear:
            raise RuntimeError('unknown transport')
    cmd_vel_cycle(s.command, SimpleNamespace(on_activity=lambda _: None), unknown)
    assert sent == [Twist(.1, -.1), Twist()]
    assert cycle(s) == [Twist()]
    assert s.ledger.read().state == 'STOPPED'


def test_writer_reentry_cannot_emit_an_extra_zero_or_motion():
    s = setup(); sent = []

    def writer(out):
        sent.append(out)
        assert cycle(s) == []
    cmd_vel_cycle(s.command, SimpleNamespace(on_activity=lambda _: None), writer)
    assert sent == [Twist(.1, -.1)]
    assert cycle(s) == [Twist()]


def test_manual_takeover_consumes_parent_without_losing_manual_authority(monkeypatch):
    s = setup()
    assert s.modes.transition(Mode.MANUAL)[0]
    monkeypatch.setattr('core_features.command.manager.time.monotonic', lambda: s.clock[0])
    assert s.command.teleop(.1, 0.)[0]
    assert cycle(s) == [Twist(.1, 0.)]
    assert s.ledger.read().state == 'STOPPED'
    assert s.modes.transition(Mode.IDLE)[0] and s.modes.transition(Mode.NAVIGATION)[0]
    s.command.set_nav_twist(Twist(.1, 0.), now=10.)
    assert cycle(s) == [Twist()]


def test_installation_is_once_before_first_cycle_including_legacy_zero():
    s = setup()
    assert s.command._install_execution_restriction(s.ledger) is None
    modes = ModeMachine()
    command = CommandManager(SourceRegistry(), modes, SafetyManager(SpeedLimits(), BatteryPolicy()))
    cmd_vel_cycle(command, SimpleNamespace(on_activity=lambda _: None), lambda _: None)
    ledger = Ledger(robot_id='synthetic', boot_id=BOOT_ID, profile_revision='SYNTHETIC',
                    max_parents=8, max_children=8)
    assert command._install_execution_restriction(ledger) is None


def test_installed_ledger_and_budget_reject_mutation_through_old_metadata_references():
    s = setup()
    assert not s.ledger.advance(s.parent, s.child, replace(s.child, generation=2))
    assert not s.ledger.stop(s.parent, 'bypass')
    assert not s.budget.stop('bypass')
    assert not s.budget.observe(s.pose, before_mono=10., after_mono=10.)
    assert s.budget.remaining(now_mono=11.) is None
    assert not s.budget.adoption_open(now_mono=11.)
    assert cycle(s) == [Twist(.1, -.1)]


def test_late_fault_for_old_parent_does_not_stop_replacement():
    s = setup()
    assert s.fence.stop(s.parent, 'replace') and s.fence.retire(s.parent)
    parent = s.fence.admit(replace(s.identity, parent_id=uuid4()), new_budget())
    assert parent is not None
    assert s.fence.attach(parent, replace(s.child, run_id=uuid4(), generation=2))
    s.fence.request_stop(s.parent)
    assert cycle(s) == [Twist(.1, -.1)]


def test_simultaneous_cycle_does_not_issue_a_second_write():
    s = setup(); entered, release = Event(), Event(); sent = []

    def writer(out):
        sent.append(out)
        entered.set()
        assert release.wait(3.)
    with ThreadPoolExecutor(max_workers=1) as worker:
        task = worker.submit(cmd_vel_cycle, s.command,
                             SimpleNamespace(on_activity=lambda _: None), writer)
        try:
            assert entered.wait(2.)
            assert cycle(s) == []
        finally:
            release.set()
        task.result(timeout=2.)
    assert sent == [Twist(.1, -.1)]
    assert cycle(s) == [Twist()]


def test_installation_cannot_overtake_an_inflight_legacy_selection():
    modes = ModeMachine()
    command = CommandManager(SourceRegistry(), modes, SafetyManager(SpeedLimits(), BatteryPolicy()))
    entered, release = Event(), Event()
    errors = []
    select = command.select_output

    def delayed():
        out = select()
        entered.set()
        if not release.wait(8.):
            errors.append('selection holder timed out')
            raise RuntimeError(errors[-1])
        return out
    command.select_output = delayed
    ledger = Ledger(robot_id='synthetic', boot_id=BOOT_ID, profile_revision='SYNTHETIC',
                    max_parents=8, max_children=8)
    with ThreadPoolExecutor(max_workers=2) as worker:
        task = worker.submit(cmd_vel_cycle, command,
                             SimpleNamespace(on_activity=lambda _: None), lambda _: None)
        try:
            assert entered.wait(2.)
            assert modes.mode is Mode.IDLE
            installed = worker.submit(command._install_execution_restriction, ledger).result(timeout=2.)
            assert installed is None and not release.is_set()
        finally:
            release.set()
        task.result(timeout=2.)
    assert not errors
    assert command._install_execution_restriction(ledger) is None


def test_budget_claim_cannot_overtake_an_old_operation_inflight(monkeypatch):
    s = setup(admit=False)
    entered, release = Event(), Event()
    original = s.budget._clock

    def paused(now):
        if now == 10.1:
            entered.set()
            assert release.wait(8.)
        return original(now)
    monkeypatch.setattr(s.budget, '_clock', paused)
    with ThreadPoolExecutor(max_workers=2) as worker:
        old = worker.submit(s.budget.observe,
                            replace(s.pose, stamp_ns=1100000000, source_now_ns=1100000000),
                            before_mono=10.1, after_mono=10.1)
        try:
            assert entered.wait(2.)
            adopted = worker.submit(s.fence.admit, s.identity, s.budget).result(timeout=2.)
            assert adopted is None and not release.is_set()
        finally:
            release.set()
        assert old.result(timeout=2.)
    assert s.ledger.read().parent is None


def test_source_read_window_can_span_a_final_output_check():
    s = setup()
    s.clock[0] = 10.1
    first = replace(s.pose, stamp_ns=1100000000, source_now_ns=1100000000)
    assert s.fence.observe(s.parent, first, before_mono=10.09, after_mono=10.1)
    before = s.ledger.read().remaining.duration_s
    # The next read starts at10.19; a writer checks its clock at10.2 before ingest.
    s.clock[0] = 10.2
    assert cycle(s) == [Twist(.1, -.1)]
    s.clock[0] = 10.21
    second = replace(first, stamp_ns=1200000000, source_now_ns=1200000000)
    assert s.fence.observe(s.parent, second, before_mono=10.19, after_mono=10.21)
    assert s.ledger.read().remaining.duration_s < before


def test_budget_and_input_final_checks_use_the_same_latest_sampled_clock(monkeypatch):
    s = setup(duration=.95)
    budget_times, written = [], []
    remaining = s.budget.remaining

    def checked(**kwargs):
        result = remaining(**kwargs)
        budget_times.append(kwargs['now_mono'])
        return result
    monkeypatch.setattr(s.budget, 'remaining', checked)

    def arm_clock():
        values = iter([10.1, 10.2])
        s.ledger._clock = lambda: next(values, 10.2)
        return True

    def writer(out):
        written.append((out, budget_times[-1], s.ledger._last_clock))
    cmd_vel_cycle(s.command, SimpleNamespace(on_activity=lambda _: None), writer,
                  motion_ready=arm_clock)
    assert all(budget_time == latest for out, budget_time, latest in written if out.linear)
    if s.ledger._last_clock >= 10.2:
        assert [out for out, _, _ in written] == [Twist()]


def test_manual_watchdog_is_rechecked_after_readiness_callback(monkeypatch):
    s = setup()
    monkeypatch.setattr('core_features.command.manager.time.monotonic', lambda: s.clock[0])
    assert s.modes.transition(Mode.MANUAL)[0] and s.command.teleop(.1, 0.)[0]

    def delay():
        s.clock[0] = 10.6
        return True
    assert cycle(s, motion_ready=delay) == [Twist()]
    assert s.command.teleop(.1, 0.)[0]
    assert cycle(s) == [Twist(.1, 0.)]


def test_candidate_ttl_expires_even_when_budget_pose_is_refreshed():
    s = setup()
    first = replace(s.pose, stamp_ns=1300000000, source_now_ns=1300000000)
    s.clock[0] = 10.3
    assert s.fence.observe(s.parent, first, before_mono=10.3, after_mono=10.3)

    def delayed():
        s.clock[0] = 10.51
        assert s.fence.observe(s.parent, replace(first, stamp_ns=1510000000,
                                                source_now_ns=1510000000),
                               before_mono=10.51, after_mono=10.51)
        return True
    assert cycle(s, motion_ready=delayed) == [Twist()]
    assert s.ledger.read().state == 'STOPPED'


def test_docking_mode_requires_its_own_typed_child():
    s = setup()
    assert s.modes.transition(Mode.IDLE)[0] and s.modes.transition(Mode.DOCKING)[0]
    s.command.set_docking_twist(Twist(.1, -.1), now=10.)
    assert cycle(s) == [Twist()]
    assert s.fence.revoke(s.parent, s.child)
    assert s.fence.attach(s.parent, ChildIdentity('docking', BOOT_ID, uuid4(), 1))
    assert cycle(s) == [Twist(.1, -.1)]


def test_observer_runs_outside_new_mode_ledger_and_budget_locks():
    s = setup(); errors = []

    def inspect():
        for lock in (s.modes._lock, s.ledger._lock, s.budget._lock):
            assert lock.acquire(blocking=False)
            lock.release()

    def notified(_):
        try:
            with ThreadPoolExecutor(max_workers=1) as worker:
                worker.submit(inspect).result(timeout=2.)
        except Exception as exc:
            errors.append(exc)
    assert cycle(s, notify_written=notified) == [Twist(.1, -.1)]
    assert not errors


@pytest.mark.parametrize('fault', ['selection', 'binding', 'hardware', 'devices', 'trial'])
def test_fault_paths_write_zero_consume_parent_and_release_cycle_lock(monkeypatch, fault):
    from core.bridge import cmd_vel as module
    s = setup()

    def fail(*args, **kwargs):
        raise RuntimeError('fault')
    kwargs = {}
    if fault == 'selection':
        monkeypatch.setattr(s.command, '_select_output', fail)
    elif fault == 'binding':
        monkeypatch.setattr(module.PinkyTwistPort, '_bind', fail)
    elif fault == 'hardware':
        kwargs['readiness'] = SimpleNamespace(is_ready=fail)
    elif fault == 'devices':
        kwargs['motion_ready'] = fail
    else:
        kwargs['trial_guard'] = SimpleNamespace(stop=lambda _: None)
    assert cycle(s, **kwargs) == [Twist()]
    assert s.command._cycle_lock.acquire(blocking=False)
    s.command._cycle_lock.release()
    assert s.ledger.read().state == 'STOPPED'


def test_install_rejects_unaccepted_python_runtime(monkeypatch):
    from core_features.command import _execution_fence
    monkeypatch.setattr(_execution_fence, '_supported_runtime', lambda: False)
    modes = ModeMachine()
    command = CommandManager(SourceRegistry(), modes, SafetyManager(SpeedLimits(), BatteryPolicy()))
    ledger = Ledger(robot_id='synthetic', boot_id=BOOT_ID, profile_revision='SYNTHETIC',
                    max_parents=8, max_children=8)
    assert command._install_execution_restriction(ledger) is None
    assert ledger._owner is None and modes._execution_fence is None


def test_budget_lock_contention_stays_requested_until_stop_can_commit():
    s = setup(); held, release = Event(), Event()

    def owner():
        with s.budget._lock:
            held.set()
            assert release.wait(8.)
    with ThreadPoolExecutor(max_workers=2) as worker:
        task = worker.submit(owner)
        try:
            assert held.wait(2.)
            assert worker.submit(cycle, s).result(timeout=2.) == [Twist()]
            status = s.ledger.read()
            assert status.state == 'STOP_REQUESTED' and s.budget.reason is None
            assert not release.is_set()
        finally:
            release.set()
        task.result(timeout=2.)
    assert s.ledger.read().state == 'STOPPED'
    assert cycle(s) == [Twist()]


@pytest.mark.parametrize('mode', [Mode.MANUAL, Mode.EMERGENCY])
def test_takeover_consumes_parent_even_when_no_writer_tick_observes_it(mode):
    s = setup()
    assert s.modes.transition(mode)[0]
    assert (s.modes.release_emergency() if mode is Mode.EMERGENCY else
            s.modes.transition(Mode.IDLE))[0]
    assert s.modes.transition(Mode.NAVIGATION)[0]
    s.command.set_nav_twist(Twist(.1, 0.), now=10.)
    assert cycle(s) == [Twist()]
    assert s.ledger.read().state == 'STOPPED'


@pytest.mark.parametrize('fault', ['hardware', 'devices'])
def test_callback_fault_targets_old_receipt_after_parent_replacement(fault):
    s = setup(); replacement = []

    def replace_then_fail():
        assert s.fence.stop(s.parent, 'replace') and s.fence.retire(s.parent)
        parent = s.fence.admit(replace(s.identity, parent_id=uuid4()), new_budget())
        assert parent is not None
        assert s.fence.attach(parent, replace(s.child, run_id=uuid4(), generation=2))
        replacement.append(parent)
        raise RuntimeError('old callback failed after replacement')
    kwargs = (dict(readiness=SimpleNamespace(is_ready=replace_then_fail)) if fault == 'hardware'
              else dict(motion_ready=replace_then_fail))
    assert cycle(s, **kwargs) == [Twist()]
    # Assertions inside faulting callbacks cannot stand in for this outside evidence.
    assert len(replacement) == 1 and s.ledger.read().state == 'ACTIVE'
    assert cycle(s) == [Twist(.1, -.1)]


def test_receipt_is_consumed_before_raw_writer_can_attempt_replay():
    s = setup(); saved = []; sent = []; replays = []

    def capture():
        saved.append(s.fence._receipt)
        return True

    def writer(out):
        sent.append(out)
        receipt = saved[0]
        s.fence.submit(receipt, receipt.output, (receipt.linear, receipt.angular),
                       lambda: replays.append('unauthorized second submit'))
    cmd_vel_cycle(s.command, SimpleNamespace(on_activity=lambda _: None), writer,
                  motion_ready=capture)
    assert sent == [Twist(.1, -.1)] and not replays
    assert cycle(s) == [Twist()]


@pytest.mark.parametrize('clone', [copy.copy, replace])
@pytest.mark.parametrize('operation', ['stop', 'request'])
def test_copied_parent_handle_cannot_request_stop_for_real_parent(clone, operation):
    s = setup()
    copied = clone(s.parent)
    assert copied is not s.parent
    if operation == 'stop':
        assert not s.fence.stop(copied, 'copied handle')
    else:
        s.fence.request_stop(copied)
    assert cycle(s) == [Twist(.1, -.1)]
    assert s.ledger.read().state == 'ACTIVE'


@pytest.mark.parametrize('boundary', ['policy', 'writer'])
@pytest.mark.parametrize('refresh', ['input', 'generation'])
def test_clean_refresh_drops_old_output_without_consuming_lifecycle_budget(boundary, refresh):
    s = setup()
    before = s.ledger.read().remaining
    policy = s.command._safety.evaluate_candidate

    def changed():
        s.clock[0] = 10.1
        if refresh == 'input':
            s.command.set_nav_twist(Twist(.2, .1), now=10.1)
        else:
            assert s.fence.advance(s.parent, s.child, replace(s.child, generation=2))
        return True

    def evaluate(*args, **kwargs):
        out = policy(*args, **kwargs)
        changed()
        return out
    if boundary == 'policy':
        s.command._safety.evaluate_candidate = evaluate
    assert cycle(s, **(dict(motion_ready=changed) if boundary == 'writer' else {})) == [Twist()]
    s.command._safety.evaluate_candidate = policy
    status = s.ledger.read()
    assert status.state == 'ACTIVE' and status.parent == s.identity
    assert s.ledger._current is s.parent and s.parent.budget is s.budget
    assert status.remaining.duration_s < before.duration_s
    assert status.remaining.path_m < before.path_m
    assert status.remaining.rotation_rad < before.rotation_rad
    assert status.remaining.energy_upper_j > before.energy_upper_j
    assert cycle(s) == [Twist(.2, .1) if refresh == 'input' else Twist(.1, -.1)]
    assert s.budget._start == 10. and s.budget._duration == 10.
    # Both the original window and source freshness have expired by this point.
    s.clock[0] = 20.
    assert cycle(s) == [Twist()] and s.ledger.read().state == 'STOPPED'


@pytest.mark.parametrize('fault', ['payload', 'stop', 'ttl', 'budget', 'clock', 'limit', 'replay'])
def test_refresh_cannot_hide_original_receipt_or_budget_fault(fault):
    s = setup(duration=.95 if fault == 'budget' else 10.)
    if fault == 'ttl':
        s.clock[0] = 10.3
        assert s.fence.observe(s.parent, replace(s.pose, stamp_ns=1300000000,
                                                source_now_ns=1300000000),
                               before_mono=10.3, after_mono=10.3)
    if fault == 'limit':
        s.command._safety.evaluate_candidate = lambda *args, **kwargs: (2., -.1)

    def changed():
        receipt = s.fence._receipt
        if fault == 'payload':
            receipt.output.linear = .2
        elif fault == 'stop':
            s.fence.request_stop(s.parent)
        elif fault == 'ttl':
            s.clock[0] = 10.51
            assert s.fence.observe(s.parent, replace(s.pose, stamp_ns=1510000000,
                                                    source_now_ns=1510000000),
                                   before_mono=10.51, after_mono=10.51)
        elif fault == 'budget':
            s.clock[0] = 10.2
        elif fault == 'clock':
            s.clock[0] = 9.9
        elif fault == 'replay':
            assert s.fence.submit(receipt, receipt.output, (.1, -.1),
                                  lambda: SimpleNamespace(accepted=True)).accepted
        s.command.set_nav_twist(Twist(.3, 0.), now=s.clock[0])
        return True
    assert cycle(s, motion_ready=changed) == [Twist()]
    assert s.ledger.read().state == 'STOPPED'
    assert cycle(s) == [Twist()]
