"""Actual native owners and sole writer, with synthetic limits; no device permit."""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from core.bridge.cmd_vel import cmd_vel_cycle
from core_common.protocol.native_receipts import BOOT_ID
from core_features.command.arbitration import Mode
from core_features.command.manager import Twist
from core_features.command._execution_budget import Budget, Limits, Pose
from core_features.command._execution_ledger import Ledger, ExecutionIdentity, ChildIdentity
from core_features.navigation.manager import NavGoalSpec, NavigationError
from core_features.docking.database import DockError
from test_docking_parking_wiring import sim_overrides


def _robot(core_client, *, admit=True, energy=True, energy_age=30.):
    from core.drive.execution import install_native_execution
    _, svc = core_client(config_overrides=sim_overrides())
    clock = [10.]
    clock_read = [None]
    def trusted_clock():
        captured = clock[0]
        if clock_read[0] is not None:
            clock_read[0]()
        return captured
    svc.docking._clock = lambda: clock[0]
    svc.nav.lease_clock = lambda: clock[0]
    ledger = Ledger(robot_id=svc.identity.robot_id, boot_id=BOOT_ID,
                    profile_revision='SYNTHETIC', max_parents=8, max_children=8,
                    clock=trusted_clock)
    limits = Limits('SYNTHETIC', 1., 2., 2., 4., .1, .2, .1, .01, .5, .4, 10.)
    binding = install_native_execution(svc, ledger, source_limits=limits)
    assert binding is not None
    energy_source = energy_provider = energy_ingress = energy_value = None
    if energy:
        from core_features.power.execution_energy import EnergyProfile, EnergyReading, PackEnergySource
        energy_profile = EnergyProfile(svc.identity.robot_id, BOOT_ID, 'pack', 'bench',
            'pack-boot', 'capacity-1', 'SYNTHETIC', limits.whole_load_w, 20., energy_age,
            70., 0., 45.)
        energy_provider = object()
        energy_source = PackEnergySource(profile=energy_profile, provider=energy_provider,
                                         clock=ledger._clock)
        energy_ingress = binding.install_energy_source(energy_source)
        assert energy_ingress is not None
        energy_value = EnergyReading(1, 1000000000, 'pack', 'pack-boot', 'capacity-1',
                                     1., 80., 90., 25., False)
        assert energy_ingress.receive(energy_provider, lambda: (energy_value, 1000000000))
    identity = ExecutionIdentity(svc.identity.robot_id, BOOT_ID, uuid4(), 'SYNTHETIC',
                                 'map', '1', 'odom', '0', '0' * 64)
    pose = Pose(1000000000, 1000000000, 'odom', '0', 0., 0.)
    budget = Budget(limits=limits, initial=pose, before_mono=10., after_mono=10.,
                    now_utc=100., captured_utc=99.9, admit_until_utc=100.1,
                    duration_s=10., path_m=10., rotation_rad=20., radius_m=5.)
    parent = binding.fence.admit(identity, budget) if admit else None
    if admit:
        assert parent is not None
    sends, cancels = [], []
    svc.nav.executor = SimpleNamespace(
        send_native_goal=lambda spec, run_id, **kw: sends.append((spec, run_id)),
        cancel_goal=lambda: cancels.append('cancel'))
    svc.docking.executor = SimpleNamespace(
        drive=lambda l, a: svc.command.set_docking_twist(Twist(l, a), now=clock[0]),
        stop=lambda: svc.command.clear_docking(), set_collision_exemption=lambda _: None,
        cancel_navigation=lambda: svc.nav.cancel(source='dock_backend'),
        reset_odometry_mark=lambda: None, odometry_pose=lambda: (0., 0., 0.),
        odometry_available=lambda: True, travelled_m=lambda: 0.)
    return SimpleNamespace(**locals())


@pytest.fixture
def unbound_robot(core_client):
    return _robot(core_client)


@pytest.fixture
def robot(core_client):
    result = _robot(core_client)
    assert bind_map(result) and deliver_map(result)
    return result


def bind_map(r):
    """Synthetic readbacks bound to the actual private CORE composition."""
    from core_features.navigation.map_evidence import GridContent
    from core_features.navigation.native_map_adoption import NativeMapEvidence, Consumer
    source = r.svc.nav._map_evidence
    token = source.begin(1000000000, 1000000000)
    assert source.complete(token, GridContent('map', 2, 2, .05,
        (-1., -.5, 0., 0., 0., 0., 1.), (0, 100, -1, 50), 1000000000, 1000000000))
    r.map_profiles = tuple(Consumer(role, '/unit/' + node, 'a'*64, 'b'*64, object())
        for role, node in [('amcl', 'amcl'), ('static_layer', 'global_costmap/global_costmap')])
    r.map_owner = NativeMapEvidence(source=lambda: r.svc.nav._map_evidence,
        parent=lambda: r.ledger._current, consumers=r.map_profiles,
        clock=lambda: r.clock[0], stop=r.binding.fence.request_stop)
    r.map_nonce = 0
    return r.binding.install_map_evidence(r.map_owner)


def deliver_map(r, *, generation=1, roles=2):
    from core_features.navigation.native_map_reply import NativeReply
    round_ = r.map_owner.begin()
    if round_ is None:
        return False
    observation = r.svc.nav._map_evidence.snapshot()
    for index, profile in enumerate(r.map_profiles[:roles], start=1):
        r.map_nonce += 1
        ticket = r.map_owner.issue(round_, profile.role, profile.provider, r.map_nonce.to_bytes(16, 'big'))
        if ticket is None:
            return False
        reply = NativeReply(1, ticket.nonce, bytes([index])*16, generation, True, True,
            'adopted', profile.role, profile.node_fqn, profile.build_id, profile.config_digest,
            observation.digest, observation.frame, observation.width, observation.height,
            observation.resolution, observation.origin, observation.stamp_ns, observation.load_time_ns)
        if not r.map_owner.reply(ticket, profile.provider, reply):
            return False
    return True


def wheels(r, **kwargs):
    sent = []
    cmd_vel_cycle(r.svc.command, SimpleNamespace(on_activity=lambda _: None), sent.append, **kwargs)
    return sent


def start_nav(r):
    assert r.svc.modes.transition(Mode.NAVIGATION)[0]
    r.binding.navigation(r.parent, NavGoalSpec(1., 0., 0.),
                         correlation_id='work', lease_ttl_s=1., lease_owner='owner')
    current = r.svc.nav.native.current
    assert current is not None and current.phase == 'SUBMITTED'
    r.svc.command.set_nav_twist(Twist(.1, 0.), now=r.clock[0])
    assert wheels(r) == [Twist()]
    r.svc.nav.on_goal_accepted(native_run_id=current.run_id)
    r.svc.command.set_nav_twist(Twist(.1, 0.), now=r.clock[0])
    assert wheels(r) == [Twist(.1, 0.)]
    return current


def test_actual_run_and_generation_are_the_only_installed_child_source(robot):
    r = robot
    declared = ChildIdentity('navigation', BOOT_ID, uuid4(), 1)
    assert not r.binding.fence.attach(r.parent, declared)
    run = start_nav(r)
    child = r.ledger.read().child
    assert (child.boot_id, child.run_id, child.generation) == (
        run.boot_id, run.run_id, r.svc.nav.native.generation)


def test_actual_lease_refresh_drops_old_selection_and_preserves_parent_budget(robot):
    r = robot
    start_nav(r)
    before = r.ledger.read().remaining

    def renew():
        r.clock[0] = 10.1
        r.svc.nav.renew_goal_lease('work', 1., owner='owner')
        return True
    assert wheels(r, motion_ready=renew) == [Twist()]
    status = r.ledger.read()
    assert status.state == 'ACTIVE' and r.ledger._current is r.parent
    assert status.child.generation == r.svc.nav.native.generation
    assert status.remaining.duration_s < before.duration_s
    assert status.remaining.path_m < before.path_m
    assert status.remaining.energy_upper_j > before.energy_upper_j
    assert r.budget._start == 10. and r.budget._duration == 10.
    assert wheels(r) == [Twist(.1, 0.)]


def test_cancel_closes_actual_output_before_backend_call_even_if_it_fails(robot):
    r = robot
    run = start_nav(r)
    during = []

    def cancel():
        during.extend(wheels(r))
        raise RuntimeError('backend cancellation unknown')
    r.svc.nav.executor.cancel_goal = cancel
    with pytest.raises(RuntimeError):
        r.svc.nav.cancel(run_id=run.run_id)
    assert during == [Twist()]
    assert r.ledger.read().state == 'STOPPED' and wheels(r) == [Twist()]


def test_successful_navigation_then_dock_uses_same_parent_and_real_dock_receipt(robot):
    r = robot
    run = start_nav(r)
    r.clock[0] = 10.1
    r.svc.nav.on_result(True, native_run_id=run.run_id, correlation_id='work')
    assert r.ledger.read().child is None
    assert r.ledger.read().state == 'ACTIVE'
    r.binding.dock(r.parent, 'parking', correlation_id='return')
    current = r.svc.docking.native.current
    child = r.ledger.read().child
    assert child.domain == 'docking' and child.run_id == current.run_id
    assert child.generation == r.svc.docking.native.generation
    assert current.phase == 'SUBMITTED'  # Do not rewrite the public native phase.
    r.svc.command.set_docking_twist(Twist(.05, 0.), now=10.1)
    assert wheels(r) == [Twist(.05, 0.)]
    assert r.ledger._current is r.parent and r.budget._start == 10.


@pytest.mark.parametrize('entry', ['goal', 'reserve', 'moving', 'mapping', 'dock', 'undock'])
def test_unbound_admission_is_rejected_before_any_owner_or_backend_change(robot, entry):
    r = robot
    start_nav(r)
    nav, dock = r.svc.nav, r.svc.docking
    before = (nav.native.current, nav.native.generation, dock.native.current,
              dock.native.generation, r.svc.modes.epoch, len(r.sends), len(r.cancels))
    calls = {'goal': lambda: nav.goal(NavGoalSpec(2., 0., 0.)),
             'reserve': nav.reserve_goal, 'moving': nav.open_moving_session,
             'mapping': nav.start_mapping, 'dock': dock.dock, 'undock': dock.undock}
    with pytest.raises((NavigationError, DockError)) as rejected:
        calls[entry]()
    assert rejected.value.code == 'CAPABILITY_NOT_SUPPORTED'
    assert before == (nav.native.current, nav.native.generation, dock.native.current,
                      dock.native.generation, r.svc.modes.epoch, len(r.sends), len(r.cancels))
    assert wheels(r) == [Twist(.1, 0.)]


def test_late_result_for_prior_native_run_cannot_close_new_child(robot):
    r = robot
    first = start_nav(r)
    r.svc.nav.on_result(True, native_run_id=first.run_id, correlation_id='work')
    r.binding.navigation(r.parent, NavGoalSpec(2., 0., 0.), correlation_id='second')
    second = r.svc.nav.native.current
    r.svc.nav.on_goal_accepted(native_run_id=second.run_id)
    r.svc.nav.on_result(False, native_run_id=first.run_id, correlation_id='work')
    r.svc.command.set_nav_twist(Twist(.1, 0.), now=10.)
    assert r.ledger.read().child.run_id == second.run_id
    assert wheels(r) == [Twist(.1, 0.)]


def test_installer_never_replaces_installed_binding(robot):
    from core.drive.execution import install_native_execution
    r = robot
    assert install_native_execution(r.svc, r.ledger, source_limits=r.limits) is None
    assert r.svc.nav._execution_binding is r.binding._navigation


def test_installer_refuses_after_a_legacy_cycle(core_client):
    from core.drive.execution import install_native_execution
    _, svc = core_client()
    cmd_vel_cycle(svc.command, SimpleNamespace(on_activity=lambda _: None), lambda _: None)
    ledger = Ledger(robot_id=svc.identity.robot_id, boot_id=BOOT_ID,
                    profile_revision='SYNTHETIC', max_parents=8, max_children=8)
    limits = Limits('SYNTHETIC', 1., 2., 2., 4., .1, .2, .1, .01, .5, .4, 10.)
    assert install_native_execution(svc, ledger, source_limits=limits) is None
    assert svc.command._execution_fence is None


def test_foreign_cancel_does_not_revoke_a_new_reservation_in_legacy_owner(core_client):
    _, svc = core_client()
    token = svc.nav.reserve_goal()
    generation = svc.nav.native.generation
    assert not svc.nav.cancel(run_id=uuid4())
    assert svc.nav._admitting == token and svc.nav.native.generation == generation
    # A plain cancel still clears reservation-only admission, despite no backend run.
    assert not svc.nav.cancel()
    assert svc.nav._admitting is None and svc.nav.native.generation > generation


@pytest.mark.parametrize('late_input', [False, True])
def test_next_native_run_requires_input_after_its_own_acceptance(robot, late_input):
    r = robot
    first = start_nav(r)
    r.svc.nav.on_result(True, native_run_id=first.run_id, correlation_id='work')
    r.binding.navigation(r.parent, NavGoalSpec(2., 0., 0.), correlation_id='second')
    if late_input:
        r.svc.command.set_nav_twist(Twist(.2, 0.), now=10.)
    r.svc.nav.on_goal_accepted(native_run_id=r.svc.nav.native.current.run_id)
    assert wheels(r) == [Twist()]
    r.svc.command.set_nav_twist(Twist(.05, 0.), now=10.)
    assert wheels(r) == [Twist(.05, 0.)]


def test_first_native_acceptance_waits_for_input_without_consuming_parent(robot):
    r = robot
    assert r.svc.modes.transition(Mode.NAVIGATION)[0]
    r.binding.navigation(r.parent, NavGoalSpec(1., 0., 0.))
    r.svc.nav.on_goal_accepted(native_run_id=r.svc.nav.native.current.run_id)
    r.clock[0] = 10.1
    assert wheels(r) == [Twist()]
    assert r.ledger.read().state == 'ACTIVE' and r.ledger._current is r.parent
    r.svc.command.set_nav_twist(Twist(.05, 0.), now=10.1)
    assert wheels(r) == [Twist(.05, 0.)]
    assert r.budget._start == 10. and r.budget._duration == 10.


@pytest.mark.parametrize('change', ['expire', 'manual', 'spec'])
def test_readiness_callback_cannot_change_bound_admission_before_native_send(robot, monkeypatch, change):
    r = robot
    assert r.svc.modes.transition(Mode.NAVIGATION)[0]
    spec = NavGoalSpec(1., 0., 0.)

    def ready():
        if change == 'expire':
            r.clock[0] = 20.
        elif change == 'spec':
            spec.x = 2.
        else:
            assert r.svc.modes.transition(Mode.MANUAL)[0]
            assert r.svc.modes.transition(Mode.IDLE)[0]
            assert r.svc.modes.transition(Mode.NAVIGATION)[0]
    monkeypatch.setattr(r.svc.nav, 'require_ready', ready)
    with pytest.raises(NavigationError):
        r.binding.navigation(r.parent, spec)
    assert r.svc.nav.native.current is None and r.svc.nav.native.generation == 0
    assert r.sends == [] and r.ledger.read().state == 'STOPPED'


def test_dock_admission_callback_expiry_is_rechecked_before_taking_mode(robot):
    r = robot
    epoch = r.svc.modes.epoch
    r.svc.docking.motion_admission = lambda *args: r.clock.__setitem__(0, 20.)
    with pytest.raises(DockError):
        r.binding.dock(r.parent, 'parking')
    assert r.svc.modes.epoch == epoch and r.svc.docking.native.current is None
    assert r.cancels == [] and r.ledger.read().state == 'STOPPED'


def test_terminal_run_cancel_does_not_touch_a_later_reservation(core_client):
    _, svc = core_client()
    svc.nav.executor = SimpleNamespace(send_goal=lambda *args, **kw: None)
    svc.nav.goal(NavGoalSpec(1., 0., 0.))
    old = svc.nav.native.current
    svc.nav.on_result(True, native_run_id=old.run_id)
    token = svc.nav.reserve_goal()
    generation = svc.nav.native.generation
    assert not svc.nav.cancel(run_id=old.run_id)
    assert svc.nav._admitting == token and svc.nav.native.generation == generation


def test_unscoped_staging_callback_is_ignored_after_leaving_staging(robot):
    from core_features.docking.model import DockPhase
    r = robot
    r.svc.docking.database.type_of('parking').staging = True
    r.svc.docking.executor.navigate_to = lambda pose: r.svc.nav.external_goal_sent()
    r.binding.dock(r.parent, 'parking')
    assert r.svc.docking.phase is DockPhase.STAGING
    r.svc.nav.on_goal_accepted()
    before = r.svc.nav.nav_state
    with r.svc.docking._lock:
        r.svc.docking._enter(DockPhase.ACQUIRING)
    r.svc.nav.on_result(False)
    assert r.svc.nav.nav_state is before


def test_injected_dock_completion_then_native_undock_keeps_remaining_parent(robot):
    r = robot
    r.binding.dock(r.parent, 'parking')
    dock_run = r.svc.docking.native.current
    # Exercise owner composition after an injected completion, not seating proof.
    with r.svc.docking._lock:
        r.svc.docking._mark_docked()
        r.svc.docking._release_mode_when_done()
    assert r.svc.docking.native.current.result == 'SUCCEEDED'
    assert r.ledger.read().child is None and r.ledger.read().state == 'ACTIVE'
    r.clock[0] = 10.1
    r.binding.undock(r.parent, correlation_id='departure')
    departure = r.svc.docking.native.current
    assert departure.kind == 'undock' and departure.run_id != dock_run.run_id
    assert r.ledger.read().child.run_id == departure.run_id
    assert wheels(r) == [Twist()]
    r.svc.docking.tick(now=10.1)
    assert wheels(r) == [Twist(-r.svc.docking._cfg.undock_speed, 0.)]
    assert r.ledger._current is r.parent and r.budget._start == 10.


def test_required_energy_absence_refuses_parent_before_actual_native_dispatch(core_client):
    """A real native composition must never adopt a positive energy-free parent."""
    r = _robot(core_client, admit=False, energy=False)
    assert bind_map(r)  # Independent original map holder/transport is installed.
    parent = r.binding.fence.admit(r.identity, r.budget)
    assert parent is None, 'native parent accepted without original measured energy'
    assert r.ledger._current is None or r.ledger.read().state == 'STOPPED'
    assert r.sends == r.cancels == []
    assert r.svc.nav.native.current is None and r.svc.docking.native.current is None
    assert wheels(r) == [Twist()]


@pytest.mark.parametrize('entry', ['navigation', 'dock'])
def test_energy_slot_loss_refuses_actual_native_child_with_valid_map(core_client, entry):
    r = _robot(core_client)
    assert bind_map(r) and deliver_map(r)
    # Model loss of the installed energy context while independent map proof is valid.
    # At the pre-feature baseline there is no required slot, so this is ignored.
    r.binding.fence._native_energy = None
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
    assert r.ledger.read().state == 'STOPPED'
    assert wheels(r) == [Twist()]


def test_energy_low_then_higher_publication_never_revives_current_parent(robot):
    from dataclasses import replace
    r = robot
    start_nav(r)
    low = replace(r.energy_value, sequence=2, stamp_ns=1100000000, usable_wh_lower=.001)
    r.clock[0] = 10.1
    assert r.energy_ingress.receive(r.energy_provider, lambda: (low, low.stamp_ns))
    assert r.ledger.read().state == 'STOPPED'
    high = replace(low, sequence=3, stamp_ns=1200000000, usable_wh_lower=2.)
    r.clock[0] = 10.2
    assert r.energy_ingress.receive(r.energy_provider, lambda: (high, high.stamp_ns))
    assert r.ledger.read().state == 'STOPPED' and wheels(r) == [Twist()]
    assert r.budget._start == 10. and r.budget._duration == 10.


def test_energy_decode_failure_stops_and_releases_pending_for_newer_facts(robot):
    from dataclasses import replace
    r = robot
    start_nav(r)
    def broken():
        raise ValueError('unsupported raw provider data')
    assert not r.energy_ingress.receive(r.energy_provider, broken)
    assert r.ledger.read().state == 'STOPPED'
    newer = replace(r.energy_value, sequence=2, stamp_ns=1100000000)
    r.clock[0] = 10.1
    assert r.energy_ingress.receive(r.energy_provider, lambda: (newer, newer.stamp_ns))
    assert r.binding.fence._native_energy.admission_open()
    assert wheels(r) == [Twist()]


def test_energy_expiry_alone_stops_with_map_pose_and_lease_still_fresh(core_client):
    r = _robot(core_client, energy_age=.15)
    assert bind_map(r) and deliver_map(r)
    start_nav(r)
    r.clock[0] = 10.16
    assert wheels(r) == [Twist()] and r.ledger.read().state == 'STOPPED'


def test_new_energy_does_not_extend_selected_original_deadline(core_client):
    from dataclasses import replace
    r = _robot(core_client, energy_age=.15)
    assert bind_map(r) and deliver_map(r)
    start_nav(r)
    newer = replace(r.energy_value, sequence=2, stamp_ns=1100000000)
    def refresh():
        r.clock[0] = 10.1
        assert r.energy_ingress.receive(r.energy_provider, lambda: (newer, newer.stamp_ns))
        r.clock[0] = 10.16
        return True
    assert wheels(r, motion_ready=refresh) == [Twist()]
    assert r.ledger.read().state == 'STOPPED'


@pytest.mark.parametrize('fault', [True, False])
def test_energy_publication_orders_after_an_already_entered_writer(robot, fault):
    from concurrent.futures import ThreadPoolExecutor
    from dataclasses import replace
    from threading import Event
    r = robot
    start_nav(r)
    entered, release, completed = Event(), Event(), Event()
    value = replace(r.energy_value, sequence=2, stamp_ns=1100000000, fault=fault)
    complete = r.energy_source.complete
    def tracked(*args, **kwargs):
        result = complete(*args, **kwargs)
        completed.set()
        return result
    r.energy_source.complete = tracked
    def decode():
        entered.set()
        assert release.wait(2.)
        return value, value.stamp_ns
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(r.energy_ingress.receive, r.energy_provider, decode)
        try:
            assert entered.wait(2.)  # Pending read; prior finite evidence stays usable.
            output = r.binding.fence.select()
            assert output.linear != 0.
            receipt = r.binding.fence.receipt_for(output)
            def raw_writer():
                release.set()
                assert completed.wait(2.)  # Raw result ready, publication waits on this boundary.
                assert not future.done()
                return SimpleNamespace(accepted=True)
            result = r.binding.fence.submit(receipt, output,
                (output.linear, output.angular), raw_writer)
            assert result.accepted  # Exactly this already-entered write may finish.
        finally:
            release.set()
        assert future.result(timeout=2.) is (not fault)
    assert r.ledger.read().state == ('STOPPED' if fault else 'ACTIVE')
    assert wheels(r) == [Twist() if fault else Twist(.1, 0.)]


@pytest.mark.parametrize('offset', [.1, 10000., -.1])
def test_energy_clock_domain_must_be_the_exact_ledger_clock(core_client, offset):
    from core_features.power.execution_energy import EnergyProfile, PackEnergySource
    r = _robot(core_client, admit=False, energy=False)
    profile = EnergyProfile(r.svc.identity.robot_id, BOOT_ID, 'pack', 'bench',
        'pack-boot', 'capacity-1', 'SYNTHETIC', r.limits.whole_load_w, 20., 30., 70., 0., 45.)
    wrong = PackEnergySource(profile=profile, provider=object(), clock=lambda: r.clock[0]+offset)
    assert r.binding.install_energy_source(wrong) is None
    # An invalid claim is permanently closed, including a later correct clock.
    correct = PackEnergySource(profile=profile, provider=object(), clock=r.ledger._clock)
    assert r.binding.install_energy_source(correct) is None
    assert r.binding.fence.admit(r.identity, r.budget) is None


def test_energy_cache_overflow_closes_instead_of_evicting_live_selection(robot):
    from dataclasses import replace
    r = robot
    start_nav(r)
    selected = r.binding.fence._energy_sample()
    for sequence in range(2, 9):
        value = replace(r.energy_value, sequence=sequence, stamp_ns=1000000000+sequence)
        assert r.energy_ingress.receive(r.energy_provider, lambda: (value, value.stamp_ns))
    assert r.ledger.read().state == 'ACTIVE'
    value = replace(r.energy_value, sequence=9, stamp_ns=1000000009)
    assert not r.energy_ingress.receive(r.energy_provider, lambda: (value, value.stamp_ns))
    assert selected.valid_until_mono > r.clock[0]
    assert r.ledger.read().state == 'STOPPED' and wheels(r) == [Twist()]


def test_energy_full_future_window_refused_even_when_elapsed_energy_would_fit(core_client):
    from dataclasses import replace
    r = _robot(core_client, admit=False)
    value = replace(r.energy_value, sequence=2, stamp_ns=1100000000, usable_wh_lower=.03)
    assert r.energy_ingress.receive(r.energy_provider, lambda: (value, value.stamp_ns))
    # About108J exceeds elapsed/stop-now but cannot cover 10W*10s plus20J reserve.
    assert r.binding.fence.admit(r.identity, r.budget) is None
    assert r.identity.parent_id in r.ledger._used_parents
    assert wheels(r) == [Twist()]


def test_pending_energy_read_denies_new_parent_without_renewing_attempt(core_client):
    from concurrent.futures import ThreadPoolExecutor
    from dataclasses import replace
    from threading import Event
    r = _robot(core_client, admit=False)
    entered, release = Event(), Event()
    value = replace(r.energy_value, sequence=2, stamp_ns=1100000000)
    def decode():
        entered.set()
        assert release.wait(2.)
        return value, value.stamp_ns
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(r.energy_ingress.receive, r.energy_provider, decode)
        try:
            assert entered.wait(2.)
            assert r.binding.fence.admit(r.identity, r.budget) is None
        finally:
            release.set()
        assert future.result(timeout=2.)
    assert r.binding.fence.admit(r.identity, r.budget) is None
    assert r.identity.parent_id in r.ledger._used_parents
