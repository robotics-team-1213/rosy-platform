"""Only a released, successful native Task can yield navigation to charging."""
import copy
from types import SimpleNamespace

import pytest

from fakes import run
from test_task_native_outcomes import _accepted_native_task
from test_channel_native_outcomes import _readback
from fleet.server.channel.execution.outcomes.reconcile import task_result
from fleet.swarm.dispatch_guard import check_dispatch


def fixture(tmp_path, *, release=True):
    service, task, _, _ = _accepted_native_task(tmp_path)
    value = _readback(task['receipt']['operation'])
    sent = []

    async def get(path):
        assert path.startswith('/api/v1/navigation/state')
        return copy.deepcopy(value)

    async def handover(**body):
        check_dispatch(path='/api/v1/navigation/handover')
        sent.append(body)
        return {'accepted': True, 'mode': 'IDLE'}

    client = SimpleNamespace(robot_id=task['robot_id'], _get=get, navigation_handover=handover)
    if release:
        run(task_result(service.store, client, task))
    return service, task, client, value, sent


def test_released_native_task_handover_uses_exact_current_epoch(tmp_path):
    service, task, client, value, sent = fixture(tmp_path)
    assert run(service.handover_completed_navigation(task['robot_id'], client=client, admission=lambda: None))
    assert sent == [dict(expected_boot_id=value['operation']['boot_id'],
        run_id=value['operation']['run_id'], expected_owner_generation=7,
        correlation_id=task['attempt_id'])]
    assert service.store.get_task(task['task_id'])['receipt']['safe_released'] is True
    assert not service.store.resource_claims(resource_kind='robot', resource_id=task['robot_id'])


@pytest.mark.parametrize('change', ['unreleased', 'failed', 'run', 'boot', 'correlation',
    'busy', 'pending', 'missing', 'stopped', 'claim', 'source', 'client'])
def test_unverified_or_changed_task_cannot_handover(tmp_path, change):
    service, task, client, value, sent = fixture(tmp_path, release=change != 'unreleased')
    admission = lambda: None
    if change in {'run', 'boot', 'correlation'}:
        from uuid import uuid4
        key = {'run': 'run_id', 'boot': 'boot_id', 'correlation': 'correlation_id'}[change]
        value['operation'][key] = str(uuid4())
    elif change == 'failed':
        value['operation']['result'] = 'FAILED'
    elif change == 'busy':
        value['owner']['owner_run_id'] = value['operation']['run_id']
    elif change == 'pending':
        value['quiescence']['pending_submission'] = True
    elif change == 'missing':
        value['lookup'] = 'NOT_FOUND'
    elif change == 'stopped':
        service.store.trip_stop_latch(actor_id='operator')
    elif change == 'claim':
        service.store.reserve_resources(owner_kind='direct_action', owner_id='new-owner',
            generation=service.store.dispatch_control()['generation'], resources=[('robot', task['robot_id'])])
    elif change == 'source':
        admission = lambda: 'ENERGY_SOURCE_STALE'
    elif change == 'client':
        client.robot_id = 'another-robot'
    assert not run(service.handover_completed_navigation(task['robot_id'], client=client, admission=admission))
    assert sent == []


def test_final_transport_guard_rechecks_stop_after_http_wait(tmp_path):
    service, task, client, _, sent = fixture(tmp_path)
    original = client.navigation_handover

    async def delayed(**body):
        service.store.trip_stop_latch(actor_id='operator')
        return await original(**body)

    client.navigation_handover = delayed
    with pytest.raises(ValueError, match='NAVIGATION_HANDOVER_ADMISSION_CHANGED'):
        run(service.handover_completed_navigation(task['robot_id'], client=client, admission=lambda: None))
    assert not sent


def test_current_task_receipt_rechecked_after_source_admission(tmp_path):
    service, task, client, _, sent = fixture(tmp_path)

    def admission():
        with service.store._connect() as conn:
            conn.execute("UPDATE fleet_tasks SET receipt_json='{}' WHERE task_id=?", (task['task_id'],))

    assert not run(service.handover_completed_navigation(task['robot_id'], client=client, admission=admission))
    assert not sent


def test_source_expires_during_database_read(tmp_path):
    service, task, client, _, sent = fixture(tmp_path)
    calls = []

    def admission():
        calls.append(True)
        return None if len(calls) == 1 else 'ENERGY_SOURCE_STALE'

    assert not run(service.handover_completed_navigation(task['robot_id'], client=client, admission=admission))
    assert len(calls) == 2 and not sent


def test_busy_database_refuses_without_waiting_or_sending(tmp_path):
    service, task, client, _, sent = fixture(tmp_path)
    with service.store._connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        assert not run(service.handover_completed_navigation(task['robot_id'], client=client, admission=lambda: None))
    assert not sent


def test_original_policy_boot_must_match_the_actual_completed_native_task(tmp_path):
    from uuid import uuid4
    service, task, client, _, sent = fixture(tmp_path)
    assert not run(service.handover_completed_navigation(task['robot_id'], client=client,
        expected_boot_id=str(uuid4()), admission=lambda: None))
    assert not sent


def test_completion_callback_receives_only_the_exact_revalidated_task(tmp_path):
    service, task, client, value, sent = fixture(tmp_path)
    completed = []
    def finish(**proof):
        completed.append(proof)
        return True
    assert run(service.handover_completed_navigation(task['robot_id'], client=client,
        admission=lambda: None, completed=finish))
    assert len(sent) == len(completed) == 1
    assert completed[0]['task']['task_id'] == task['task_id']
    assert completed[0]['task']['attempt_id'] == task['attempt_id']
    assert completed[0]['operation'] == value['operation']


@pytest.mark.parametrize('fault', ['policy', 'dispatch', 'receipt'])
def test_changes_while_native_ack_is_in_flight_cannot_reach_completion_callback(tmp_path, fault):
    service, task, client, _, sent = fixture(tmp_path)
    completed, current = [], [None]
    original = client.navigation_handover
    async def changed(**body):
        result = await original(**body)
        if fault == 'policy':
            current[0] = 'ENERGY_SOURCE_STALE'
        elif fault == 'dispatch':
            service.store.close_dispatch_for_startup()
        else:
            with service.store._connect() as conn:
                conn.execute("UPDATE fleet_tasks SET receipt_json='{}' WHERE task_id=?", (task['task_id'],))
        return result
    client.navigation_handover = changed
    assert not run(service.handover_completed_navigation(task['robot_id'], client=client,
        admission=lambda: current[0], completed=lambda **proof: completed.append(proof)))
    assert len(sent) == 1 and not completed
