"""Actual native reverse controller; local departure facts are explicit SIM inputs."""
import importlib

import pytest

from core_common.protocol.station_charging import StationMotionCommand
from core_features.docking.agent import DockReachability, DockStatus
from test_station_departure_feed import configured
from test_station_docking_owner import seated_owner, charge_evidence


def departure():
    owner, manager, now = seated_owner()
    evidence = charge_evidence(now[0], termination='NORMAL', charging=False)
    status = DockStatus(DockReachability.OK, load_present=True, charging=False, termination='NORMAL',
        termination_source='charger', termination_sample_at=now[0], battery_id='pack-1')
    assert owner.update_charge(status, evidence, received_at=now[0])
    module, _, body, _ = configured()
    assert hasattr(module, 'StationDepartureController'), 'scoped native departure controller is missing'
    feed = module.StationDepartureFeed(profile=configured()[1].profile,
        clock=lambda: now[0], source_clock=lambda: now[0])
    controller = module.StationDepartureController(owner, feed=feed)
    owner.departure = controller
    body.update(boot_id=owner.session.boot_id)
    sequence = [0]

    def sample(**changes):
        sequence[0] += 1
        at = now[0]
        values = body | dict(sequence=sequence[0], captured_at=at, valid_until=at+.2,
            motion_sample_at=at, space_sample_at=at, power_sample_at=at, current_sample_at=at,
            contact_sample_at=at, pose=dict(zip(('x', 'y', 'yaw'), manager.executor.pose))) | changes
        assert feed.ingest(module.StationDepartureSample.model_validate(values))

    schema = importlib.import_module('core_common.protocol.station_charging')
    permit = schema.StationDeparturePermit(**{k: getattr(owner.session, k) for k in (
        'robot_id', 'station_id', 'session_id', 'attempt_id', 'boot_id', 'battery_id',
        'map_id', 'map_revision', 'pose_revision')}, correlation_id='undock-1', work_task_id='work-1',
        work_request_digest='a'*64, expected_owner_generation=manager.native_owner()['owner_generation'],
        policy_profile_revision='energy-1', capacity_revision='capacity-1',
        captured_at=now[0], valid_until=now[0]+8.)
    sample()
    return owner, manager, now, sample, permit


@pytest.mark.parametrize('changes', [dict(output_enabled=True), dict(current_a=.2),
    dict(rear_clearance_m=.1), dict(sweep_verified=False), dict(charging=True), dict(faults=('HOT',)),
    dict(attempt_id='foreign'), dict(odom_epoch='other')])
def test_departure_refuses_before_native_admission(changes):
    owner, manager, _, sample, permit = departure()
    previous = manager.native.current.run_id
    sample(**changes)
    with pytest.raises(ValueError):
        owner.start_departure(permit, principal_id=None)
    assert manager.native.current.run_id == previous
    assert manager.executor.command == (0., 0.)


def test_final_gate_closes_on_stale_measurements_without_waiting_for_tick():
    owner, manager, now, _, permit = departure()
    operation = owner.start_departure(permit, principal_id=None)
    assert operation.kind == 'undock' and owner.motion_ready('DOCKING')
    owner.tick()
    assert manager.executor.command == (-.08, 0.)
    now[0] += .21
    assert not owner.motion_ready('DOCKING')
    owner.tick()
    assert owner.state == 'HOLD' and manager.executor.command == (0., 0.)


def stopped_departure():
    owner, manager, now, sample, permit = departure()
    operation = owner.start_departure(permit, principal_id=None)
    for _ in range(100):
        owner.tick()
        if owner.state == 'DEPARTURE_CHECK':
            break
        manager.executor.step(.05)
        now[0] += .05
        sample(load_present=False, measured_linear_m_s=-.08)
    assert owner.state == 'DEPARTURE_CHECK'
    assert manager.native.current.result == 'SUCCEEDED'
    command = StationMotionCommand(session_id=permit.session_id, correlation_id=permit.correlation_id,
        expected_boot_id=permit.boot_id, expected_owner_generation=manager.native_owner()['owner_generation'])
    with pytest.raises(ValueError):
        owner.finish_departure(command, principal_id=None)
    for _ in range(7):
        now[0] += .1
        sample(load_present=False)
        owner.tick()
    return owner, manager, now, sample, operation, command


def test_native_success_requires_new_measured_stop_and_contact_release_before_finish():
    owner, _, _, _, operation, command = stopped_departure()
    receipt = owner.finish_departure(command, principal_id=None)
    assert receipt.operation_id == str(operation.run_id)
    assert receipt.stopped and receipt.contact_released and receipt.power_isolated and receipt.route_clear
    assert owner.state == 'WORK_AVAILABLE'
    assert owner.motion_ready('NAVIGATION')
    assert owner.finish_departure(command, principal_id=None) == receipt


@pytest.mark.parametrize('changed', [dict(load_present=True), dict(measured_linear_m_s=-.04)])
def test_changing_final_sample_cannot_be_reported_as_contact_release_or_standstill(changed):
    owner, _, _, sample, _, command = stopped_departure()
    controller = owner.departure
    original = controller._sample
    calls = [0]

    def interleaved():
        calls[0] += 1
        if calls[0] == 2:
            sample(**changed)
        return original()

    controller._sample = interleaved
    with pytest.raises(ValueError):
        owner.finish_departure(command, principal_id=None)
    assert controller.receipt is None and owner.state == 'DEPARTURE_CHECK'


def test_another_terminal_native_generation_cannot_be_adopted_as_departure():
    owner, manager, _, _, permit = departure()
    operation = owner.start_departure(permit, principal_id=None)
    # Simulate a replacement native writer, bypassing normal admission for the negative test.
    manager.native.update(operation.run_id, phase='TERMINAL', result='SUCCEEDED')
    replacement = manager.native.admit('dock', 'replacement')
    manager.native.update(replacement.run_id, phase='TERMINAL', result='SUCCEEDED')
    assert not owner.motion_ready('DOCKING')
    assert owner.departure.terminal_generation is None


def test_permission_refresh_is_scoped_to_current_run_and_cannot_replay_or_revive():
    owner, manager, now, sample, permit = departure()
    owner.start_departure(permit, principal_id=None)
    now[0] += .1
    sample()
    renewed = permit.model_copy(update=dict(captured_at=now[0], valid_until=now[0]+1.,
        expected_owner_generation=manager.native_owner()['owner_generation']))
    owner.renew_departure(renewed, principal_id=None)
    deadline = owner.departure.deadline
    owner.renew_departure(renewed, principal_id=None)
    assert owner.departure.deadline == deadline
    with pytest.raises(ValueError):
        owner.renew_departure(renewed.model_copy(update=dict(work_task_id='foreign')), principal_id=None)
    now[0] = renewed.valid_until
    sample()
    with pytest.raises(ValueError):
        owner.renew_departure(renewed.model_copy(update=dict(captured_at=now[0], valid_until=now[0]+1.)),
            principal_id=None)


def test_fresh_facts_cannot_renew_cached_receipt_after_original_monotonic_expiry():
    owner, _, now, sample, _, command = stopped_departure()
    controller = owner.departure
    mono = [now[0]]
    owner.clock = lambda: mono[0]
    receipt = owner.finish_departure(command, principal_id=None)
    mono[0] += receipt.valid_until-receipt.captured_at+.01
    now[0] += .01
    sample(load_present=False)
    with pytest.raises(ValueError, match='RECEIPT_EXPIRED'):
        owner.finish_departure(command, principal_id=None)
    mono[0] -= .1
    with pytest.raises(ValueError, match='RECEIPT_EXPIRED'):
        owner.finish_departure(command, principal_id=None)


def test_duplicate_receipt_checks_original_lifetime_after_local_snapshot_io():
    owner, _, now, sample, _, command = stopped_departure()
    controller = owner.departure
    mono = [now[0]]
    owner.clock = lambda: mono[0]
    owner.finish_departure(command, principal_id=None)
    original = controller._sample

    def delayed():
        result = original()
        mono[0] = controller.receipt_deadline
        return result

    controller._sample = delayed
    with pytest.raises(ValueError, match='RECEIPT_EXPIRED'):
        owner.finish_departure(command, principal_id=None)


def test_readback_exposes_only_live_scoped_permission_and_never_old_charge_completion():
    owner, _, _, _, permission = departure()
    operation = owner.start_departure(permission, principal_id=None)
    status = owner.readback()
    assert status.departure_permit is not None
    assert status.departure_permit.work_request_digest == permission.work_request_digest
    assert status.operation_id == str(operation.run_id)
    assert status.valid_until <= status.departure_permit.valid_until
    assert not status.completion_verified and not status.charging_verified
    assert status.departure_receipt is None


def test_lost_finish_reply_is_readable_only_with_original_receipt_lifetime():
    owner, _, now, sample, operation, command = stopped_departure()
    proof = owner.finish_departure(command, principal_id=None)
    live = owner.readback()
    assert live.departure_receipt.operation_id == str(operation.run_id)
    assert live.valid_until <= live.departure_receipt.valid_until <= proof.valid_until
    assert live.departure_permit is None
    now[0] = proof.valid_until
    sample(load_present=False)
    assert owner.readback().departure_receipt is None
    assert owner.state == 'WORK_AVAILABLE'


def test_receipt_readback_does_not_outlive_monotonic_lease_or_revive_after_clock_recovery():
    owner, _, now, sample, _, command = stopped_departure()
    mono = [now[0]]
    owner.clock = lambda: mono[0]
    owner.finish_departure(command, principal_id=None)
    mono[0] = owner.departure.receipt_deadline
    now[0] += .01
    sample(load_present=False)
    assert owner.readback().departure_receipt is None
    mono[0] -= .1
    assert owner.readback().departure_receipt is None


def test_contradictory_contact_permanently_closes_old_receipt_even_if_contact_clears_again():
    owner, _, _, sample, _, command = stopped_departure()
    owner.finish_departure(command, principal_id=None)
    sample(load_present=True)
    assert owner.readback().departure_receipt is None
    sample(load_present=False)
    assert owner.readback().departure_receipt is None
    with pytest.raises(ValueError):
        owner.finish_departure(command, principal_id=None)


@pytest.mark.parametrize('change', [dict(state='CHARGED_HOLD'), dict(operation_id='foreign'),
    dict(correlation_id='foreign'), dict(session_id='old'), dict(battery_id='other'), dict(valid_until=200.)])
def test_shared_status_rejects_mixed_or_unscoped_departure_receipt(change):
    from core_common.protocol.station_charging import StationTargetStatus
    owner, _, _, _, _, command = stopped_departure()
    owner.finish_departure(command, principal_id=None)
    body = owner.readback().model_dump()
    with pytest.raises(ValueError):
        StationTargetStatus.model_validate(body | change)


@pytest.mark.parametrize('kind', ['permission', 'receipt'])
def test_readback_rechecks_source_deadline_after_local_scope_read(kind):
    if kind == 'permission':
        owner, _, now, _, permission = departure()
        owner.start_departure(permission, principal_id=None)
    else:
        owner, _, now, _, _, command = stopped_departure()
        owner.finish_departure(command, principal_id=None)
    started, before = now[0], owner.local_scope_nowait
    def delayed_scope():
        value = before()
        now[0] += .21
        return value
    owner.local_scope_nowait = delayed_scope
    status = owner.readback()
    assert status.departure_permit is None and status.departure_receipt is None
    assert not status.completion_verified
    now[0], owner.local_scope_nowait = started+.01, before
    recovered = owner.readback()
    assert recovered.departure_permit is None and recovered.departure_receipt is None


def test_owner_readback_final_clock_cannot_relabel_expired_departure_fields_as_live():
    owner, _, now, _, _, command = stopped_departure()
    owner.finish_departure(command, principal_id=None)
    original = owner.departure.status_fields
    def delayed_status():
        fields = original()
        now[0] += .21
        return fields
    owner.departure.status_fields = delayed_status
    status = owner.readback()
    assert status.departure_receipt is None
    assert not status.binding_valid and not status.seating_verified
