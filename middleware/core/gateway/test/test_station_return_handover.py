"""Return handover uses the actual navigation owner and GoalTracker transport evidence."""
from types import SimpleNamespace
import threading

import pytest

from core.bridge.goal_tracker import GoalTracker
from core_api_web.api.deps import Mode
from test_station_docking_api import station_api
from test_station_return_authority import prepared, grant
from test_cmd_vel_cycle import run
from core.bridge.docking_mode import motion_ready


class TrackedNavigation:
    """SIM backend results; real owner receipts and transport generation bookkeeping."""
    def __init__(self, nav):
        self.nav, self.tracker = nav, GoalTracker()
        self.current = None
        self.canceled = 0

    def send_native_goal(self, spec, run_id, *, correlation_id):
        generation = self.tracker.opening(correlation_id, run_id)
        assert self.tracker.accepted(generation, object())
        self.current = generation, run_id, correlation_id
        self.spec = spec
        self.nav.on_goal_accepted(native_run_id=run_id)

    def done(self, success=True):
        generation, run_id, correlation = self.current
        self.tracker.finished(generation)
        self.nav.on_result(success, correlation_id=correlation, native_run_id=run_id)

    def native_transport_snapshot(self):
        return self.tracker.transport_snapshot()

    def cancel_goal(self):
        self.canceled += 1


def terminal_navigation(svc, kind='navigate'):
    backend = TrackedNavigation(svc.nav)
    svc.nav.executor = backend
    svc.modes.transition(Mode.NAVIGATION)
    svc.nav.goal(svc.nav.resolve_goal(x=1., y=0., yaw=0.), correlation_id='SIM-return-goal', kind=kind)
    backend.done()
    assert svc.nav.nav_state.value == 'ARRIVED' and svc.modes.mode is Mode.NAVIGATION
    return backend


def finish(client, auth, permit, **changes):
    return client.post('/api/v1/docking/station-return/finish', headers=auth['fleet-a'], json=dict(
        session_id=permit['session_id'], correlation_id=permit['correlation_id'],
        expected_boot_id=permit['boot_id'], expected_owner_generation=permit['expected_owner_generation'], **changes))


@pytest.mark.parametrize('kind', ['navigate', 'home'])
def test_terminal_backend_hands_over_to_idle_then_requires_new_measured_stop(station_api, kind):
    client, svc, now, auth, permit = prepared(station_api)
    assert grant(client, auth, permit).status_code == 200
    backend = terminal_navigation(svc, kind)
    reply = finish(client, auth, permit)
    assert reply.status_code == 409 and reply.json()['error']['code'] == 'STATION_RETURN_STANDSTILL_REQUIRED'
    assert svc.modes.mode is Mode.IDLE, 'actual terminal navigation never handed over to IDLE'
    assert svc.station_docking.state == 'RETURNING' and backend.canceled == 0
    assert svc.trip_lease.current()['lease_id'] == permit['lease_id']
    motion = dict(odom_epoch='odom-1', measured_linear_m_s=0., measured_angular_rad_s=0.)
    svc.station_docking.motion_feed = SimpleNamespace(snapshot=lambda: dict(motion), clear=lambda: None)
    for _ in range(6):
        now[0] += .1
        motion.update(captured_at=now[0], valid_until=now[0]+.25)
        svc.station_docking.tick()
    assert finish(client, auth, permit).status_code == 200
    assert svc.station_docking.state == 'BOUND'


@pytest.mark.parametrize('fault', ['active', 'admission', 'pending', 'callback', 'missing', 'failed', 'receipt_missing',
                                  'mapping', 'moving_session', 'unstable'])
def test_active_or_unknown_backend_never_changes_mode_or_cancels_a_goal(station_api, fault):
    client, svc, _, auth, permit = prepared(station_api)
    assert grant(client, auth, permit).status_code == 200
    backend = terminal_navigation(svc)
    if fault in ('active', 'failed'):
        svc.nav.goal(svc.nav.resolve_goal(x=2., y=0., yaw=0.), correlation_id='other-goal')
        if fault == 'failed':
            backend.done(False)
    elif fault == 'admission':
        svc.nav.reserve_goal()
    elif fault == 'pending':
        backend.tracker.opening('late')
    elif fault == 'callback':
        generation = backend.tracker.opening('late')
        backend.tracker.accepted(generation, object())
    elif fault == 'missing':
        svc.nav.executor = SimpleNamespace()
    elif fault == 'receipt_missing':
        svc.nav.native.current = None
        svc.nav.native.terminal.clear()
    elif fault == 'mapping':
        svc.nav.mapping_active = True
    elif fault == 'moving_session':
        svc.nav.open_moving_session()
    else:
        original = backend.native_transport_snapshot
        def unstable():
            generation = backend.tracker.opening('unstable')
            backend.tracker.rejected(generation)
            return original()
        backend.native_transport_snapshot = unstable
    reply = finish(client, auth, permit)
    assert reply.status_code == 409
    assert svc.modes.mode is Mode.NAVIGATION and svc.station_docking.state == 'RETURNING'
    assert backend.canceled == 0


def test_pre_handover_motion_cannot_count_toward_new_stop_dwell(station_api):
    client, svc, now, auth, permit = prepared(station_api)
    assert grant(client, auth, permit).status_code == 200
    terminal_navigation(svc)
    old = dict(odom_epoch='odom-1', measured_linear_m_s=0., measured_angular_rad_s=0.,
               captured_at=now[0]-.1, valid_until=now[0]+.15)
    motion = dict(old)
    svc.station_docking.motion_feed = SimpleNamespace(snapshot=lambda: dict(motion), clear=lambda: None)
    assert finish(client, auth, permit).status_code == 409
    assert svc.modes.mode is Mode.IDLE
    assert finish(client, auth, permit).status_code == 409
    assert svc.station_docking.return_authority.since is None
    for step in range(1, 5):
        now[0] = 100.+step*.1
        motion.update(captured_at=now[0], valid_until=now[0]+.25)
        svc.station_docking.tick()
    # Only 0.3 s since first post-handover sample, despite 0.5 s since the old sample.
    assert finish(client, auth, permit).status_code == 409
    now[0] = 100.6
    motion.update(captured_at=now[0], valid_until=now[0]+.25)
    svc.station_docking.tick()
    assert finish(client, auth, permit).status_code == 200


def test_wrong_docking_generation_cannot_change_mode_before_refusal(station_api):
    client, svc, _, auth, permit = prepared(station_api)
    assert grant(client, auth, permit).status_code == 200
    backend = terminal_navigation(svc)
    command = dict(session_id=permit['session_id'], correlation_id=permit['correlation_id'],
                   expected_boot_id=permit['boot_id'], expected_owner_generation=999)
    reply = client.post('/api/v1/docking/station-return/finish', headers=auth['fleet-a'], json=command)
    assert reply.status_code == 409 and svc.modes.mode is Mode.NAVIGATION
    assert backend.canceled == 0


@pytest.mark.parametrize('race', ['manual', 'emergency', 'admission', 'expired', 'replacement_lease'])
def test_scope_or_owner_change_during_native_proof_cannot_be_overwritten(station_api, race):
    client, svc, now, auth, permit = prepared(station_api)
    assert grant(client, auth, permit).status_code == 200
    backend = terminal_navigation(svc)
    original, changed = backend.native_transport_snapshot, []
    def race_snapshot():
        if not changed:
            changed.append(True)
            if race in ('manual', 'emergency'):
                svc.modes.transition(Mode.MANUAL if race == 'manual' else Mode.EMERGENCY)
            elif race == 'admission':
                svc.nav.reserve_goal()
            elif race == 'expired':
                now[0] += 2.1
            else:
                svc.trip_lease.release(permit['lease_id'], 'fleet-a')
                svc.trip_lease.open(lease_id='replacement', trip_id='other', holder='other',
                    operator_name='SIM', ttl_s=5., owner_id='fleet-b')
        return original()
    backend.native_transport_snapshot = race_snapshot
    assert finish(client, auth, permit).status_code == 409
    expected = Mode.MANUAL if race == 'manual' else Mode.EMERGENCY if race == 'emergency' else Mode.NAVIGATION
    assert svc.modes.mode is expected and backend.canceled == 0
    if race == 'replacement_lease':
        assert svc.trip_lease.current()['lease_id'] == 'replacement'


def test_waiting_navigation_lock_closes_final_output_and_cannot_handover_after_expiry(station_api):
    client, svc, now, auth, permit = prepared(station_api)
    assert grant(client, auth, permit).status_code == 200
    terminal_navigation(svc)
    original = svc.nav.with_terminal_navigation
    entered, replies = threading.Event(), []
    def waiting(*args):
        entered.set()
        return original(*args)
    svc.nav.with_terminal_navigation = waiting
    worker = threading.Thread(target=lambda: replies.append(finish(client, auth, permit)), daemon=True)
    with svc.nav._lock:
        worker.start()
        assert entered.wait(1.), 'finish did not reach the actual navigation lock'
        assert run(motion_ready=lambda: motion_ready(svc)).sent == [(0., 0.)]
        now[0] += 2.1
    worker.join(2.)
    assert not worker.is_alive() and replies[0].status_code == 409
    assert svc.modes.mode is Mode.NAVIGATION and not motion_ready(svc)
