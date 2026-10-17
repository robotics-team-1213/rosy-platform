"""Selected work and physical release share the existing durable claim transaction."""
import pytest

from core_common.protocol.station_charging import StationDeparturePermit, StationDepartureReceipt
from fleet.server.charge_policy_admission import work_request_digest
from fleet.server.charge_store import ChargeStore
from test_charge_store import store, session, _queue, FleetTaskScheduler


def charged(tmp_path, *, session_changes=None, dock_operation_id='native-dock'):
    ledger, tasks = store(tmp_path)
    current = ledger.reserve(session(**(session_changes or {})))
    for index, state in enumerate(('RETURNING', 'DOCKING', 'CHARGE_CONFIRMING', 'CHARGED_HOLD'), 1):
        current = ledger.transition(current.session_id, expected_state=current.state, next_state=state,
            attempt_id=current.attempt_id, now=100.+index*.1, reason='SIM_FIXTURE',
            operation_id=dock_operation_id if state != 'DOCKING' else None,
            intent_kind='dock' if state == 'DOCKING' else None,
            correlation_id='dock-1' if state == 'DOCKING' else None)
        if state == 'DOCKING':
            current = ledger.acknowledge_operation(current.session_id, correlation_id='dock-1',
                operation_id=dock_operation_id, now=100.+index*.1)
    _queue(tasks, task_id='work-1', robot_id='robot-1')
    task = tasks.get_task('work-1')
    permission = StationDeparturePermit(**{key: getattr(current, key) for key in (
        'robot_id', 'station_id', 'session_id', 'attempt_id', 'boot_id', 'battery_id',
        'map_id', 'map_revision', 'pose_revision')}, correlation_id='undock-1', work_task_id='work-1',
        work_request_digest=work_request_digest(task), expected_owner_generation=2,
        policy_profile_revision='energy-1', capacity_revision='capacity-1', captured_at=100.5, valid_until=102.)
    return ledger, tasks, permission


def receipt(permission, **changes):
    body = permission.model_dump(exclude={'expected_owner_generation', 'policy_profile_revision',
        'capacity_revision', 'captured_at', 'valid_until'})
    return StationDepartureReceipt.model_validate(body | dict(operation_id='native-undock', owner_generation=4,
        odom_epoch='odom-1', departure_profile_revision='departure-1', source_id='local-departure',
        source_epoch='source-boot', captured_at=101.5, valid_until=101.7, stopped_since=101.1,
        motion_sample_at=101.5, contact_sample_at=101.5, space_sample_at=101.5, isolation_sample_at=101.5,
        contact_released=True, power_isolated=True, route_clear=True, stopped=True) | changes)


def test_preparation_pins_queued_work_and_native_intent_before_any_submission(tmp_path):
    ledger, tasks, permission = charged(tmp_path)
    current = ledger.prepare_departure(permission, clock=lambda: 101., admission=lambda: True)
    assert current.state == 'UNDOCKING' and current.operation_id is None
    intent = ledger.operation_intent('charge-1')
    assert intent['kind'] == 'undock' and intent['status'] == 'PREPARED'
    assert intent['correlation_id'] == permission.correlation_id
    reopened = ChargeStore(tasks)
    assert reopened.departure_context('charge-1')['permit'] == permission.model_dump()
    with pytest.raises(ValueError):
        reopened.prepare_departure(permission, clock=lambda: 101., admission=lambda: True)
    assert FleetTaskScheduler(tasks, worker_id='worker').claim_next({'robot-1'}) is None


def acknowledged(tmp_path):
    ledger, tasks, permission = charged(tmp_path)
    ledger.prepare_departure(permission, clock=lambda: 101., admission=lambda: True)
    ledger.acknowledge_operation('charge-1', correlation_id='undock-1',
        operation_id='native-undock', now=101.)
    return ledger, tasks, permission


def renewed(permission, **changes):
    return StationDeparturePermit.model_validate(permission.model_dump() | dict(
        captured_at=101.6, valid_until=103., expected_owner_generation=3) | changes)


def test_live_same_work_renewal_preserves_original_motion_and_allows_later_measured_release(tmp_path):
    ledger, tasks, original = acknowledged(tmp_path)
    active = renewed(original)
    ledger.renew_departure_permission(active, previous=original, clock=lambda: 101.6, admission=lambda: True)
    context = ChargeStore(tasks).departure_context('charge-1')
    assert context['permit'] == original.model_dump()
    assert context['active_permit'] == active.model_dump()
    assert tasks.resource_claims(resource_kind='robot', resource_id='robot-1')
    # Dwell may begin before renewal; the initial motion fence remains authoritative.
    proof = receipt(original, captured_at=102.1, valid_until=102.3, motion_sample_at=102.1,
        contact_sample_at=102.1, space_sample_at=102.1, isolation_sample_at=102.1)
    assert ledger.complete_departure(proof, clock=lambda: 102.1, admission=lambda: True).state == 'WORK_AVAILABLE'


@pytest.mark.parametrize('fault', ['expired_previous', 'same_capture', 'changed_work', 'changed_policy',
    'backward_generation', 'future_capture', 'denied_policy', 'stopped', 'canceled_work', 'unacknowledged'])
def test_renewal_cannot_revive_or_replace_motion_or_policy(tmp_path, fault):
    ledger, tasks, original = acknowledged(tmp_path)
    changes = {'same_capture': dict(captured_at=original.captured_at),
        'changed_work': dict(work_task_id='other'), 'changed_policy': dict(capacity_revision='other'),
        'backward_generation': dict(expected_owner_generation=2),
        'future_capture': dict(captured_at=101.8)}.get(fault, {})
    if fault == 'stopped':
        tasks.trip_stop_latch(actor_id='operator')
    elif fault == 'canceled_work':
        tasks.cancel_queued('work-1', actor_id='operator')
    elif fault == 'unacknowledged':
        with tasks._connect() as db:
            db.execute("UPDATE fleet_charge_operations SET status='PREPARED' WHERE kind='undock'")
    with pytest.raises(ValueError):
        ledger.renew_departure_permission(renewed(original, **changes), previous=original,
            clock=lambda: 102. if fault == 'expired_previous' else 101.6,
            admission=lambda: fault != 'denied_policy')
    assert ledger.departure_context('charge-1')['active_permit'] == original.model_dump()
    assert ledger.get('charge-1').state == 'UNDOCKING'
    assert tasks.resource_claims(resource_kind='station', resource_id='charger-1')


def test_delayed_renewal_rolls_back_and_stale_ack_cannot_overwrite_new_permission(tmp_path, monkeypatch):
    ledger, tasks, original = acknowledged(tmp_path)
    active = renewed(original)
    now = [101.6]
    calls = []
    def admission():
        calls.append(True)
        if len(calls) == 2:
            now[0] = 102.
        return True
    with pytest.raises(ValueError):
        ledger.renew_departure_permission(active, previous=original, clock=lambda: now[0], admission=admission)
    assert ledger.departure_context('charge-1')['active_permit'] == original.model_dump()
    ledger.renew_departure_permission(active, previous=original, clock=lambda: 101.6, admission=lambda: True)
    with pytest.raises(ValueError):
        ledger.renew_departure_permission(renewed(original, captured_at=101.7, valid_until=104.),
            previous=original, clock=lambda: 101.7, admission=lambda: True)
    assert ledger.departure_context('charge-1')['active_permit'] == active.model_dump()


def test_receipt_cannot_precede_the_latest_acknowledged_native_owner_fence(tmp_path):
    ledger, tasks, original = acknowledged(tmp_path)
    active = renewed(original, expected_owner_generation=4)
    ledger.renew_departure_permission(active, previous=original, clock=lambda: 101.6, admission=lambda: True)
    with pytest.raises(ValueError):
        ledger.complete_departure(receipt(original, owner_generation=3,
            captured_at=101.7, valid_until=101.9), clock=lambda: 101.7, admission=lambda: True)
    assert tasks.resource_claims(resource_kind='robot', resource_id='robot-1')
    # Renewing a terminal native run does not increment its generation.
    assert ledger.complete_departure(receipt(original, owner_generation=4,
        captured_at=101.7, valid_until=101.9), clock=lambda: 101.7, admission=lambda: True).state == 'WORK_AVAILABLE'


@pytest.mark.parametrize('fault', ['canceled', 'changed_request', 'other_robot', 'unfinished_attempt', 'stopped', 'expired'])
def test_changed_work_or_dispatch_refuses_atomic_preparation_without_releasing_claims(tmp_path, fault):
    ledger, tasks, permission = charged(tmp_path)
    if fault == 'canceled':
        tasks.cancel_queued('work-1', actor_id='operator')
    elif fault == 'stopped':
        tasks.trip_stop_latch(actor_id='operator')
    else:
        column, value = {'changed_request': ('request_json', '{}'), 'other_robot': ('robot_id', 'robot-2'),
            'unfinished_attempt': ('attempt_id', 'unresolved-attempt'),
            'expired': ('expires_at', '1970-01-01T00:01:40+00:00')}[fault]
        with tasks._connect() as db:
            db.execute(f'UPDATE fleet_tasks SET {column}=? WHERE task_id=?', (value, 'work-1'))
    with pytest.raises(ValueError):
        ledger.prepare_departure(permission, clock=lambda: 101., admission=lambda: True)
    assert ledger.get('charge-1').state == 'CHARGED_HOLD'
    assert ledger.operation_intent('charge-1')['kind'] == 'dock'
    assert tasks.resource_claims(resource_kind='robot', resource_id='robot-1')


def test_only_exact_live_receipt_releases_both_claims_and_existing_scheduler_can_dispatch(tmp_path):
    ledger, tasks, permission = charged(tmp_path)
    ledger.prepare_departure(permission, clock=lambda: 101., admission=lambda: True)
    with pytest.raises(ValueError):
        ledger.complete_departure(receipt(permission), clock=lambda: 101.5, admission=lambda: True)
    ledger.acknowledge_operation('charge-1', correlation_id='undock-1', operation_id='native-undock', now=101.)
    with pytest.raises(ValueError, match='RECEIPT_REQUIRED'):
        ledger.transition('charge-1', expected_state='UNDOCKING', next_state='WORK_AVAILABLE',
            attempt_id='attempt-1', operation_id='native-undock', now=101.5, reason='ACK_IS_NOT_RELEASE')
    proof = receipt(permission)
    assert ledger.complete_departure(proof, clock=lambda: 101.5, admission=lambda: True).state == 'WORK_AVAILABLE'
    assert not tasks.resource_claims(resource_kind='robot', resource_id='robot-1')
    assert not tasks.resource_claims(resource_kind='station', resource_id='charger-1')
    history = len(ledger.history('charge-1'))
    assert ChargeStore(tasks).departure_context('charge-1')['receipt'] == proof.model_dump()
    assert ledger.complete_departure(proof, clock=lambda: 101.5, admission=lambda: True).state == 'WORK_AVAILABLE'
    assert len(ledger.history('charge-1')) == history
    selected = FleetTaskScheduler(tasks, worker_id='worker').claim_next({'robot-1'})
    assert selected['task_id'] == 'work-1'
    assert FleetTaskScheduler(tasks, worker_id='other').claim_next({'robot-1'}) is None


@pytest.mark.parametrize('changes', [dict(attempt_id='old'), dict(operation_id='other'),
    dict(work_request_digest='b'*64), dict(owner_generation=2),
    dict(captured_at=100.8, valid_until=101., stopped_since=100.6, motion_sample_at=100.8,
         contact_sample_at=100.8, space_sample_at=100.8, isolation_sample_at=100.8)])
def test_wrong_or_expired_receipt_never_releases_resources(tmp_path, changes):
    ledger, tasks, permission = charged(tmp_path)
    ledger.prepare_departure(permission, clock=lambda: 101., admission=lambda: True)
    ledger.acknowledge_operation('charge-1', correlation_id='undock-1', operation_id='native-undock', now=101.)
    with pytest.raises(ValueError):
        ledger.complete_departure(receipt(permission, **changes), clock=lambda: 101.5, admission=lambda: True)
    assert ledger.get('charge-1').state == 'UNDOCKING'
    assert tasks.resource_claims(resource_kind='robot', resource_id='robot-1')
    assert tasks.resource_claims(resource_kind='station', resource_id='charger-1')


@pytest.mark.parametrize('fault', ['canceled', 'changed_request', 'stopped'])
def test_work_or_authority_change_during_native_departure_prevents_claim_release(tmp_path, fault):
    ledger, tasks, permission = charged(tmp_path)
    ledger.prepare_departure(permission, clock=lambda: 101., admission=lambda: True)
    ledger.acknowledge_operation('charge-1', correlation_id='undock-1', operation_id='native-undock', now=101.)
    if fault == 'canceled':
        tasks.cancel_queued('work-1', actor_id='operator')
    elif fault == 'stopped':
        tasks.trip_stop_latch(actor_id='operator')
    else:
        with tasks._connect() as db:
            db.execute("UPDATE fleet_tasks SET request_json='{}' WHERE task_id='work-1'")
    with pytest.raises(ValueError):
        ledger.complete_departure(receipt(permission), clock=lambda: 101.5, admission=lambda: True)
    assert ledger.departure_context('charge-1')['receipt'] is None
    assert ledger.get('charge-1').state == 'UNDOCKING'
    assert tasks.resource_claims(resource_kind='robot', resource_id='robot-1')
    assert tasks.resource_claims(resource_kind='station', resource_id='charger-1')


def test_release_failure_rolls_back_receipt_and_work_available_in_the_same_database(tmp_path, monkeypatch):
    from fleet.server import charge_departure_store
    ledger, tasks, permission = charged(tmp_path)
    ledger.prepare_departure(permission, clock=lambda: 101., admission=lambda: True)
    ledger.acknowledge_operation('charge-1', correlation_id='undock-1', operation_id='native-undock', now=101.)
    def broken_release(*args, **kwargs):
        raise RuntimeError('injected claim release failure')
    monkeypatch.setattr(charge_departure_store, 'release', broken_release)
    with pytest.raises(RuntimeError):
        ledger.complete_departure(receipt(permission), clock=lambda: 101.5, admission=lambda: True)
    reopened = ChargeStore(tasks)
    assert reopened.get('charge-1').state == 'UNDOCKING'
    assert reopened.departure_context('charge-1')['receipt'] is None
    assert tasks.resource_claims(resource_kind='robot', resource_id='robot-1')
    assert tasks.resource_claims(resource_kind='station', resource_id='charger-1')


@pytest.mark.parametrize('phase', ['prepare', 'release'])
def test_database_acquisition_delay_rechecks_actual_clock_before_any_commit(tmp_path, monkeypatch, phase):
    from contextlib import contextmanager
    ledger, tasks, permission = charged(tmp_path)
    if phase == 'release':
        ledger.prepare_departure(permission, clock=lambda: 101., admission=lambda: True)
        ledger.acknowledge_operation('charge-1', correlation_id='undock-1', operation_id='native-undock', now=101.)
    now = [101.5]
    original = ledger._write
    @contextmanager
    def delayed_acquisition():
        with original() as db:
            now[0] = 103.  # Source clock after actual BEGIN IMMEDIATE has acquired its writer lock.
            yield db
    monkeypatch.setattr(ledger, '_write', delayed_acquisition)
    with pytest.raises(ValueError):
        if phase == 'prepare':
            ledger.prepare_departure(permission, clock=lambda: now[0], admission=lambda: True)
        else:
            ledger.complete_departure(receipt(permission), clock=lambda: now[0], admission=lambda: True)
    assert ledger.get('charge-1').state == ('CHARGED_HOLD' if phase == 'prepare' else 'UNDOCKING')
    assert tasks.resource_claims(resource_kind='robot', resource_id='robot-1')
    assert tasks.resource_claims(resource_kind='station', resource_id='charger-1')


def test_receipt_expiry_during_claim_write_rolls_back_the_entire_release(tmp_path, monkeypatch):
    from fleet.server import charge_departure_store
    ledger, tasks, permission = charged(tmp_path)
    ledger.prepare_departure(permission, clock=lambda: 101., admission=lambda: True)
    ledger.acknowledge_operation('charge-1', correlation_id='undock-1', operation_id='native-undock', now=101.)
    now = [101.5]
    original = charge_departure_store.release
    def delayed_release(*args, **kwargs):
        result = original(*args, **kwargs)
        now[0] = 101.7
        return result
    monkeypatch.setattr(charge_departure_store, 'release', delayed_release)
    with pytest.raises(ValueError):
        ledger.complete_departure(receipt(permission), clock=lambda: now[0], admission=lambda: True)
    assert ledger.get('charge-1').state == 'UNDOCKING'
    assert ledger.departure_context('charge-1')['receipt'] is None
    assert tasks.resource_claims(resource_kind='robot', resource_id='robot-1')
    assert tasks.resource_claims(resource_kind='station', resource_id='charger-1')
