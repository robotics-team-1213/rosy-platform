"""Actual native managers / sole writer, synthetic map readbacks and odometry."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event

import pytest

from core_features.command.arbitration import Mode
from core_features.command.manager import Twist
from core_features.command._execution_budget import Budget, Pose
from core_features.navigation.manager import NavGoalSpec, NavigationError
from core_features.docking.database import DockError
from core_features.navigation.map_evidence import MapEvidence, GridContent
from test_native_execution_binding import (unbound_robot, bind_map, deliver_map, start_nav, wheels)  # noqa: F401


@pytest.fixture
def proven(unbound_robot):
    r = unbound_robot
    assert bind_map(r) and deliver_map(r)
    return r


def heartbeat(r, now):
    """Keep the independent original pose budget fresh without renewing it."""
    r.clock[0] = now
    stamp = 1000000000 + round((now-10.)*1000000000)
    assert r.binding.fence.observe(r.parent, Pose(stamp, stamp, 'odom', '0', 0., 0.),
        before_mono=now, after_mono=now)


@pytest.mark.parametrize('entry', ['navigation', 'dock'])
def test_required_map_closed_refuses_actual_admission_without_backend_effects(unbound_robot, entry):
    r = unbound_robot
    if entry == 'navigation':
        assert r.svc.modes.transition(Mode.NAVIGATION)[0]
    before = r.svc.modes.epoch
    with pytest.raises((NavigationError, DockError)):
        if entry == 'navigation':
            r.binding.navigation(r.parent, NavGoalSpec(1., 0., 0.))
        else:
            r.binding.dock(r.parent, 'parking')
    assert r.sends == r.cancels == [] and r.svc.modes.epoch == before
    assert r.svc.nav.native.current is None and r.svc.docking.native.current is None
    assert r.ledger.read().state == 'STOPPED' and wheels(r) == [Twist()]


def test_unfinished_first_pair_cannot_admit_actual_native_child(unbound_robot):
    r = unbound_robot
    assert bind_map(r) and deliver_map(r, roles=1)
    assert r.svc.modes.transition(Mode.NAVIGATION)[0]
    with pytest.raises(NavigationError):
        r.binding.navigation(r.parent, NavGoalSpec(1., 0., 0.))
    assert not r.sends and r.ledger.read().state == 'STOPPED'


def test_installation_is_unique_and_failure_cannot_be_repaired(unbound_robot):
    r = unbound_robot
    assert not r.binding.install_map_evidence(object())
    assert not bind_map(r) and deliver_map(r)
    assert r.svc.modes.transition(Mode.NAVIGATION)[0]
    with pytest.raises(NavigationError):
        r.binding.navigation(r.parent, NavGoalSpec(1., 0., 0.))
    assert r.ledger.read().state == 'STOPPED' and not r.sends


def test_installation_refuses_after_even_a_zero_cycle(unbound_robot):
    r = unbound_robot
    assert wheels(r) == [Twist()]
    assert not bind_map(r)
    assert not r.binding.install_map_evidence(r.map_owner)


def test_installed_map_owner_cannot_be_replaced_even_before_first_cycle(proven):
    r = proven
    assert not r.binding.install_map_evidence(object())
    assert not r.binding.install_map_evidence(r.map_owner)
    start_nav(r)
    assert r.ledger.read().state == 'ACTIVE'


def test_selection_and_final_writer_do_not_call_evidence_producers(proven, monkeypatch):
    r = proven
    start_nav(r)
    calls = []
    def forbidden():
        calls.append(True)
        raise AssertionError('producer callback at final command boundary')
    r.map_owner._source = r.map_owner._parent = r.map_owner._clock = forbidden
    monkeypatch.setattr(MapEvidence, 'snapshot', lambda _: forbidden())
    assert wheels(r) == [Twist(.1, 0.)] and calls == []


def test_final_writer_expires_while_evidence_callback_lock_is_blocked(proven):
    r = proven
    start_nav(r)
    heartbeat(r, 10.2)
    heartbeat(r, 10.4)
    r.svc.command.set_nav_twist(Twist(.1, 0.), now=10.4)
    entered, release = Event(), Event()
    def hold():
        with r.map_owner._lock:
            entered.set()
            assert release.wait(3.)
    def delayed():
        heartbeat(r, 10.51)
        return True
    with ThreadPoolExecutor(max_workers=2) as pool:
        blocker = pool.submit(hold)
        assert entered.wait(1.)
        try:
            written = pool.submit(wheels, r, motion_ready=delayed).result(timeout=1.)
        finally:
            release.set()
        blocker.result(timeout=1.)
    assert written == [Twist()] and r.ledger.read().state == 'STOPPED'
    assert r.budget.reason == 'execution-fault-request'
    assert r.budget._start == 10. and r.budget._duration == 10.


def test_new_poll_cannot_extend_an_old_selected_writer_deadline(proven):
    r = proven
    start_nav(r)
    heartbeat(r, 10.2)
    heartbeat(r, 10.4)
    r.svc.command.set_nav_twist(Twist(.1, 0.), now=10.4)
    old = r.map_owner.sample(r.parent)
    def refresh():
        assert deliver_map(r)
        newer = r.map_owner.sample(r.parent)
        assert newer is not old and newer.expires_at == 10.9
        heartbeat(r, 10.51)
        return True
    assert wheels(r, motion_ready=refresh) == [Twist()]
    assert r.ledger.read().state == 'STOPPED'
    assert deliver_map(r)  # Fresh sampled facts cannot restore a consumed Budget.
    r.svc.command.set_nav_twist(Twist(.1, 0.), now=10.51)
    assert wheels(r) == [Twist()]
    assert r.budget._start == 10. and r.budget._duration == 10.


def test_normal_poll_during_selected_write_preserves_original_parent_budget(proven):
    r = proven
    start_nav(r)
    before = r.ledger.read().remaining
    def refresh():
        heartbeat(r, 10.2)
        assert deliver_map(r)
        return True
    assert wheels(r, motion_ready=refresh) == [Twist(.1, 0.)]
    after = r.ledger.read().remaining
    assert after.duration_s < before.duration_s and after.energy_upper_j > before.energy_upper_j
    assert r.budget._start == 10. and r.budget._duration == 10.


@pytest.mark.parametrize('phase', ['entry', 'select'])
def test_normal_refresh_after_clock_sample_is_not_a_clock_fault(proven, phase):
    r = proven
    if phase == 'select':
        start_nav(r)
    else:
        assert r.svc.modes.transition(Mode.NAVIGATION)[0]
    fired = []
    def refresh():
        if not fired:
            fired.append(True)
            r.clock[0] = 10.01
            assert deliver_map(r)
    r.clock_read[0] = refresh
    assert r.energy_source._clock is r.ledger._clock
    if phase == 'entry':
        r.binding.navigation(r.parent, NavGoalSpec(1., 0., 0.),
            correlation_id='clock-race', lease_ttl_s=1.)
        r.svc.nav.on_goal_accepted(native_run_id=r.svc.nav.native.current.run_id)
    r.svc.command.set_nav_twist(Twist(.1, 0.), now=10.01)
    assert wheels(r) == [Twist(.1, 0.)]
    assert fired and r.ledger.read().state == 'ACTIVE' and not r.ledger._clock_fault


def test_replacing_trusted_clock_closes_execution_even_with_identical_clock_values(proven):
    r = proven
    start_nav(r)
    r.ledger._clock = lambda: r.clock[0]
    assert r.energy_source._clock is not r.ledger._clock
    assert wheels(r) == [Twist()]
    assert r.ledger.read().state == 'STOPPED'


@pytest.mark.parametrize('change', ['source', 'generation', 'close'])
def test_native_map_change_after_selection_closes_actual_final_writer(proven, change):
    r = proven
    start_nav(r)
    def changed():
        if change == 'source':
            source = MapEvidence(robot_id=r.svc.identity.robot_id, boot_id=r.identity.boot_id)
            token = source.begin(1000000000, 1000000000)
            assert source.complete(token, GridContent('map', 2, 2, .05,
                (-1., -.5, 0., 0., 0., 0., 1.), (0, 100, -1, 50), 1000000000, 1000000000))
            r.svc.nav._map_evidence = source
        elif change == 'generation':
            assert not deliver_map(r, generation=2)  # Same map after native reset/reapplication.
        else:
            r.map_owner.close()
        return True
    assert wheels(r, motion_ready=changed) == [Twist()]
    assert r.ledger.read().state == 'STOPPED'


def test_gap_with_unchanged_native_tuple_cannot_resume_original_parent(proven):
    r = proven
    start_nav(r)
    heartbeat(r, 10.2)
    heartbeat(r, 10.4)
    heartbeat(r, 10.51)
    assert not deliver_map(r)
    r.svc.command.set_nav_twist(Twist(.1, 0.), now=10.51)
    assert wheels(r) == [Twist()] and r.ledger.read().state == 'STOPPED'


def test_old_query_callback_cannot_stop_replacement_native_run(proven):
    from uuid import uuid4
    r = proven
    first = start_nav(r)
    round_ = r.map_owner.begin()
    profile = r.map_profiles[0]
    old = r.map_owner.issue(round_, profile.role, profile.provider, b'x'*16)
    assert old is not None
    r.svc.nav.cancel(run_id=first.run_id)
    assert r.binding.fence.retire(r.parent)
    old_parent = r.parent
    budget = Budget(limits=r.limits, initial=Pose(1000000000, 1000000000, 'odom', '0', 0., 0.),
        before_mono=10., after_mono=10., now_utc=100., captured_utc=99.9,
        admit_until_utc=100.1, duration_s=10., path_m=10., rotation_rad=20., radius_m=5.)
    r.parent = r.binding.fence.admit(replace(r.identity, parent_id=uuid4()), budget)
    assert r.parent is not None and deliver_map(r)
    start_nav(r)
    assert not r.map_owner.reply(old, profile.provider, None)
    assert r.ledger._current is r.parent and r.parent is not old_parent
    assert r.ledger.read().state == 'ACTIVE' and wheels(r) == [Twist(.1, 0.)]


@pytest.mark.parametrize('domain', ['navigation', 'docking'])
def test_frame_loss_consumes_actual_native_parent_with_map_readbacks_still_valid(proven, domain):
    r = proven
    r.svc.localization.on_state('{"status":{"state":"LOCALIZED","pose_frame":"map"}}')
    if domain == 'navigation':
        start_nav(r)
    else:
        r.binding.dock(r.parent, 'parking')
        r.svc.command.set_docking_twist(Twist(.05, 0.), now=10.)
        assert wheels(r) == [Twist(.05, 0.)]
    sample = r.map_owner.peek()
    r.svc.localization.tick(True)
    assert r.map_owner.valid(sample, r.parent, raw_source=r.svc.nav._map_evidence, now=10.)
    assert r.ledger.read().state == 'STOPPED' and wheels(r) == [Twist()]
    r.svc.localization.tick(False)
    r.svc.command.set_nav_twist(Twist(.1, 0.), now=10.)
    r.svc.command.set_docking_twist(Twist(.05, 0.), now=10.)
    assert wheels(r) == [Twist()] and r.ledger.read().state == 'STOPPED'


def test_frame_restore_requires_new_budget_new_ack_and_explicit_new_navigation(proven):
    from uuid import uuid4
    r = proven
    r.svc.localization.on_state('{"status":{"state":"LOCALIZED","pose_frame":"map"}}')
    first = start_nav(r)
    old_parent, old_sample = r.parent, r.map_owner.peek()
    r.svc.localization.tick(True)
    assert r.ledger.read().state == 'STOPPED' and wheels(r) == [Twist()]
    r.svc.localization.tick(False)
    r.svc.localization.on_state('{"status":{"state":"LOCALIZED","pose_frame":"map"}}')
    assert wheels(r) == [Twist()] and r.ledger.read().state == 'STOPPED'
    assert r.binding.fence.retire(old_parent)
    budget = Budget(limits=r.limits, initial=Pose(1000000000, 1000000000, 'odom', '0', 0., 0.),
        before_mono=10., after_mono=10., now_utc=100., captured_utc=99.9,
        admit_until_utc=100.1, duration_s=10., path_m=10., rotation_rad=20., radius_m=5.)
    r.parent = r.binding.fence.admit(replace(r.identity, parent_id=uuid4()), budget)
    assert r.parent is not None and r.parent is not old_parent
    assert r.map_owner.sample(r.parent) is None
    assert deliver_map(r)
    assert not r.map_owner.valid(old_sample, r.parent, raw_source=r.svc.nav._map_evidence, now=10.)
    second = start_nav(r)
    assert second.run_id != first.run_id
    assert r.ledger.read().state == 'ACTIVE' and wheels(r) == [Twist(.1, 0.)]
    with pytest.raises(NavigationError):
        r.binding.navigation(old_parent, NavGoalSpec(1., 2., 0., 'map'), lease_ttl_s=1.)
    assert r.ledger._current is r.parent and wheels(r) == [Twist(.1, 0.)]
