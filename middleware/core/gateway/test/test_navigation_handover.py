"""A completed native navigation owner may passively yield CORE's mode, never cancel."""
import pytest

from core_api_web.api.deps import Mode
from test_station_docking_api import station_api  # noqa: F401
from test_station_return_handover import terminal_navigation


def request(svc):
    body = svc.nav.native_readback()
    operation = body['operation']
    return dict(expected_boot_id=body['owner']['boot_id'], run_id=operation['run_id'],
        expected_owner_generation=body['owner']['owner_generation'], correlation_id=operation['correlation_id'])


def test_exact_terminal_handover_is_idempotent_and_preserves_native_receipt(station_api):
    client, svc, _, auth, _, _ = station_api
    backend = terminal_navigation(svc)
    body = request(svc)
    for _ in range(2):
        response = client.post('/api/v1/navigation/handover', json=body, headers=auth['fleet-a'])
        assert response.status_code == 200, response.text
        assert response.json() == dict(accepted=True, mode='IDLE', run_id=body['run_id'],
            boot_id=body['expected_boot_id'], owner_generation=body['expected_owner_generation'])
        assert svc.modes.mode is Mode.IDLE and backend.canceled == 0
        assert svc.nav.native_readback()['operation']['run_id'] == body['run_id']
    events = [event for event in svc.events.history(since_seq=None, limit=1000)
        if event.type == 'mode.changed' and event.data.get('by') == 'navigation_handover']
    assert len(events) == 1
    assert events[0].data == {
        'from': 'NAVIGATION', 'to': 'IDLE', 'by': 'navigation_handover',
        'run_id': body['run_id'], 'boot_id': body['expected_boot_id']}


def test_grid_bound_handover_records_idle_epoch_and_refuses_a_changed_grid(station_api):
    client, svc, _, auth, _, _ = station_api
    backend = terminal_navigation(svc)
    svc.state.set_map_id("robot-grid", "occupancy:0123456789ab")
    body = dict(request(svc), expected_map_grid_id="occupancy:0123456789ab")
    before = svc.modes.epoch
    rejected = client.post('/api/v1/navigation/handover',
        json={**body, "expected_map_grid_id": "occupancy:fedcba987654"}, headers=auth['fleet-a'])
    assert rejected.status_code == 409 and rejected.json()["error"]["code"] == "NAVIGATION_MAP_GRID_CHANGED"
    assert svc.modes.mode is Mode.NAVIGATION and svc.modes.epoch == before and backend.canceled == 0

    for _ in range(2):
        response = client.post('/api/v1/navigation/handover', json=body, headers=auth['fleet-a'])
        assert response.status_code == 200, response.text
        assert response.json() == dict(accepted=True, mode='IDLE', run_id=body['run_id'],
            boot_id=body['expected_boot_id'], owner_generation=body['expected_owner_generation'],
            map_grid_id=body['expected_map_grid_id'], idle_mode_epoch=before + 1)
    assert svc.modes.mode is Mode.IDLE and backend.canceled == 0
    assert svc.nav.native_readback()["operation"]["run_id"] == body["run_id"]


def test_grid_bound_handover_does_not_certify_an_intervening_idle_epoch(station_api):
    client, svc, _, auth, _, _ = station_api
    backend = terminal_navigation(svc)
    svc.state.set_map_id("robot-grid", "occupancy:0123456789ab")
    body = dict(request(svc), expected_map_grid_id=svc.state.map_grid_id)
    cycle = []

    def change_mode_after_handover(old, new):
        if new is Mode.IDLE and not cycle:
            cycle.append(True)
            assert svc.modes.transition(Mode.NAVIGATION)[0]
            assert svc.modes.transition(Mode.IDLE)[0]

    svc.modes.change_listeners.append(change_mode_after_handover)
    before = svc.modes.epoch
    response = client.post('/api/v1/navigation/handover', json=body, headers=auth['fleet-a'])
    assert cycle and svc.modes.epoch == before + 3
    assert response.status_code == 409 and "idle_mode_epoch" not in response.json()
    assert svc.modes.mode is Mode.IDLE and backend.canceled == 0


@pytest.mark.parametrize('fault', ['wrong_run', 'wrong_boot', 'wrong_correlation', 'old_generation',
    'pending_backend', 'active_callback', 'transport_missing', 'new_goal', 'manual', 'mapping', 'line_follow'])
def test_mismatched_or_unfinished_owner_cannot_yield_mode_or_cancel_a_replacement(station_api, fault):
    client, svc, _, auth, _, _ = station_api
    backend = terminal_navigation(svc)
    body = request(svc)
    if fault in ('wrong_run', 'wrong_boot'):
        body['run_id' if fault == 'wrong_run' else 'expected_boot_id'] = '00000000-0000-0000-0000-000000000001'
    elif fault == 'wrong_correlation':
        body['correlation_id'] = 'other-work-attempt'
    elif fault == 'old_generation':
        body['expected_owner_generation'] -= 1
    elif fault in ('pending_backend', 'active_callback', 'transport_missing'):
        original = backend.native_transport_snapshot
        backend.native_transport_snapshot = lambda: (None if fault == 'transport_missing' else
            (original()[0], fault == 'pending_backend', fault == 'active_callback'))
    elif fault == 'new_goal':
        svc.nav.goal(svc.nav.resolve_goal(x=2., y=0., yaw=0.), correlation_id='new-work')
    elif fault == 'manual':
        svc.modes.transition(Mode.MANUAL)
    elif fault == 'mapping':
        svc.nav.mapping_active = True
    elif fault == 'line_follow':
        from types import SimpleNamespace
        svc.line_follow = SimpleNamespace(active=True)
    before, operation = svc.modes.mode, svc.nav.native_readback()['operation']
    response = client.post('/api/v1/navigation/handover', json=body, headers=auth['fleet-a'])
    assert response.status_code == 409, response.text
    assert svc.modes.mode is before and backend.canceled == 0
    assert svc.nav.native_readback()['operation'] == operation


def test_precision_claim_requires_the_exact_live_navigation_predecessor(station_api):
    _, svc, _, _, _, _ = station_api
    backend = terminal_navigation(svc)
    view = svc.nav.native_readback()
    previous = dict(view["owner"], **{key: view["operation"][key] for key in ("run_id", "correlation_id")})
    assert svc.nav.claim_precision({**previous, "correlation_id": "different"}) is None
    assert svc.nav.claim_precision({**previous, "owner_generation": previous["owner_generation"] - 1}) is None
    for key in ("boot_id", "run_id", "owner_generation", "correlation_id"):
        assert svc.nav.claim_precision({**previous, key: None}) is None
        assert svc.nav.claim_precision({k: v for k, v in previous.items() if k != key}) is None
    assert svc.nav.claim_precision({**previous, "owner_generation": float(previous["owner_generation"])}) is None
    token = svc.nav.claim_precision(previous)
    assert token is not None and backend.canceled == 0
    assert not svc.nav.native_readback()["quiescence"]["quiescent"]
    svc.nav.release_precision(token)
    assert svc.nav.native_readback()["quiescence"]["quiescent"]


def test_another_trip_owner_fences_passive_handover(station_api):
    client, svc, now, auth, _, _ = station_api
    terminal_navigation(svc)
    body = request(svc)
    svc.trip_lease._monotonic = lambda: now[0]
    response = client.put('/api/v1/trip-lease', headers=auth['human'], json=dict(
        lease_id='other-lease', trip_id='other-trip', job_id='other-job', holder='station',
        operator_name='SIM other owner', ttl_s=5.))
    assert response.status_code == 200, response.text
    response = client.post('/api/v1/navigation/handover', json=body, headers=auth['fleet-a'])
    assert response.status_code == 409 and response.json()['error']['code'] == 'TRIP_LEASED'
    assert svc.modes.mode is Mode.NAVIGATION


def test_trip_owner_acquired_while_handover_waits_for_native_lock_prevents_mode_write(station_api):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    client, svc, now, auth, _, _ = station_api
    backend = terminal_navigation(svc)
    body = request(svc)
    svc.trip_lease._monotonic = lambda: now[0]
    waiting, original = Event(), svc.nav.with_terminal_navigation
    def enter(*args, **kwargs):
        waiting.set()
        return original(*args, **kwargs)
    svc.nav.with_terminal_navigation = enter
    with ThreadPoolExecutor(max_workers=1) as pool:
        with svc.nav._lock:
            future = pool.submit(client.post, '/api/v1/navigation/handover', json=body, headers=auth['fleet-a'])
            assert waiting.wait(2.)
            response = client.put('/api/v1/trip-lease', headers=auth['human'], json=dict(
                lease_id='late-lease', trip_id='late-trip', job_id='late-job', holder='station',
                operator_name='SIM late owner', ttl_s=5.))
            assert response.status_code == 200, response.text
        response = future.result(timeout=2.)
    assert response.status_code == 409 and response.json()['error']['code'] == 'TRIP_LEASED'
    assert svc.modes.mode is Mode.NAVIGATION and backend.canceled == 0


def test_busy_lease_admission_does_not_wait_while_holding_native_lock(station_api):
    from concurrent.futures import ThreadPoolExecutor
    client, svc, _, auth, _, _ = station_api
    backend = terminal_navigation(svc)
    body = request(svc)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with svc.modes.idle_admission:
            response = pool.submit(client.post, '/api/v1/navigation/handover',
                json=body, headers=auth['fleet-a']).result(timeout=2.)
    assert response.status_code == 409
    assert svc.modes.mode is Mode.NAVIGATION and backend.canceled == 0


def test_reentrant_guard_callback_cannot_reuse_the_prior_native_proof(station_api):
    client, svc, _, auth, _, _ = station_api
    terminal_navigation(svc)
    body = request(svc)
    original, calls, clears = svc.calibration.blocking, [], []
    clear = svc.command.clear_navigation
    def guard(token):
        calls.append(token)
        if len(calls) == 2:
            svc.nav.goal(svc.nav.resolve_goal(x=2., y=0., yaw=0.), correlation_id='SIM-reentrant-new-work')
        return original(token)
    def cleared():
        clears.append(True)
        return clear()
    svc.calibration.blocking, svc.command.clear_navigation = guard, cleared
    response = client.post('/api/v1/navigation/handover', json=body, headers=auth['fleet-a'])
    assert response.status_code == 409 and len(calls) == 2
    assert not clears and svc.modes.mode is Mode.NAVIGATION
    assert svc.nav.native_readback()['operation']['correlation_id'] == 'SIM-reentrant-new-work'
