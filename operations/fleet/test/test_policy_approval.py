"""D-1024 3: proposer != approver, 15/30 min window, 1/2 s lease renewed at half period inside the window, HOLD after."""
from hashlib import sha256

from fastapi.testclient import TestClient
import pytest

from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.policy_approval import PolicyApprovals
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore

DIGEST = 'ab' * 32


class Clock:
    now = 1000.0

    def __call__(self):
        return self.now


def _setup(deliver=True, lease_s=1.0):
    clock, grants, holds = Clock(), [], []
    sink = (lambda g: grants.append(g) or True) if deliver is True else deliver
    approvals = PolicyApprovals(monotonic=clock, hold=lambda cell, why: holds.append((cell, why)),
                                deliver=sink, lease_s=lease_s)
    return approvals, clock, grants, holds


def proposal(approvals, **change):
    args = dict(workcell_id='cell-1', proposer='Alice', policy_digest=DIGEST, rig_revision='rig-1',
                calibration_revision='cal-1', scope='stack-t1')
    return approvals.propose(**{**args, **change})['id']


def test_same_person_cannot_approve_even_with_case_change():
    approvals, *_ = _setup()
    pid = proposal(approvals)
    with pytest.raises(PermissionError):
        approvals.approve(pid, 'alice')
    assert approvals.view(pid)['state'] == 'proposed'
    assert approvals.approve(pid, 'Bob')['state'] == 'active'


@pytest.mark.parametrize('seconds', [0, -1, 1801, float('nan')])
def test_window_is_capped_at_thirty_minutes(seconds):
    approvals, *_ = _setup()
    with pytest.raises(ValueError):
        proposal(approvals, window_s=seconds)


def test_default_window_is_fifteen_minutes_and_lease_cap_is_two_seconds():
    approvals, *_ = _setup()
    pid = proposal(approvals)
    assert approvals.view(pid)['window_s'] == 900
    with pytest.raises(ValueError):
        PolicyApprovals(lease_s=2.5)


def test_lease_renews_at_half_period_and_never_outlives_the_window():
    approvals, clock, grants, holds = _setup()
    pid = proposal(approvals, window_s=60)
    approvals.approve(pid, 'Bob')
    assert approvals.tick(pid)['ttl_s'] == 1.0 and len(grants) == 1
    clock.now += 0.4
    assert approvals.tick(pid) is None
    clock.now += 0.1
    assert approvals.tick(pid) is not None and len(grants) == 2
    assert {g['lease_id'] for g in grants} == {grants[0]['lease_id']}  # same lease renewed, as OwnerPolicySession.renew needs
    clock.now = 1000.0 + 59.8
    assert approvals.tick(pid)['ttl_s'] == pytest.approx(0.2)  # cut to the window end
    assert holds == []


def test_window_end_holds_and_nothing_reapproves():
    approvals, clock, grants, holds = _setup()
    pid = proposal(approvals, window_s=60)
    approvals.approve(pid, 'Bob')
    clock.now += 61
    assert approvals.tick(pid) is None
    assert approvals.view(pid)['state'] == 'ended' and holds == [('cell-1', 'window_ended')] and grants == []
    clock.now += 1
    assert approvals.tick(pid) is None and len(holds) == 1
    with pytest.raises(ValueError):
        approvals.approve(pid, 'Carol')


def test_no_delivery_port_refuses_approval_and_failed_delivery_holds():
    approvals, clock, grants, holds = _setup(deliver=None)
    pid = proposal(approvals)
    with pytest.raises(ValueError, match='delivery'):
        approvals.approve(pid, 'Bob')
    assert approvals.view(pid)['state'] == 'proposed' and holds == []
    for sink in (lambda g: False, lambda g: 1 / 0):
        approvals, clock, grants, holds = _setup(deliver=sink)
        pid = proposal(approvals)
        approvals.approve(pid, 'Bob')
        assert approvals.tick(pid) is None and approvals.view(pid)['state'] == 'held'
        assert holds == [('cell-1', 'lease_delivery_failed')]


def test_due_window_ends_and_holds_on_read_or_tick_all_without_a_ticker():
    for reader in (lambda a, p: a.view(p), lambda a, p: a.listing(), lambda a, p: a.tick_all()):
        approvals, clock, grants, holds = _setup()
        pid = proposal(approvals, window_s=60)
        approvals.approve(pid, 'Bob')
        clock.now += 61
        reader(approvals, pid)
        assert approvals.view(pid)['state'] == 'ended' and holds == [('cell-1', 'window_ended')]


def test_failed_hold_is_retried_and_the_window_stays_closed():
    approvals, clock, grants, holds = _setup()
    calls = []
    approvals._hold = lambda cell, why: calls.append(why) or (1 / 0 if len(calls) == 1 else None)
    pid = proposal(approvals, window_s=60)
    approvals.approve(pid, 'Bob')
    clock.now += 61
    assert approvals.tick(pid) is None and calls == ['window_ended']
    assert approvals.view(pid)['state'] == 'ended' and calls == ['window_ended'] * 2  # the read retried it
    approvals.tick(pid)
    assert len(calls) == 2


@pytest.mark.parametrize('state_change', ['abort', 'end', 'hold'])
def test_abort_of_a_terminal_window_is_a_conflict(state_change):
    approvals, clock, grants, holds = _setup(deliver=lambda g: state_change != 'hold')
    pid = proposal(approvals, window_s=60)
    approvals.approve(pid, 'Bob')
    if state_change == 'abort':
        approvals.abort(pid, 'Bob')
    elif state_change == 'end':
        clock.now += 61
    else:
        approvals.tick(pid)
    with pytest.raises(ValueError):
        approvals.abort(pid, 'Bob')
    assert len(holds) == 1


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), 999.0, '1'])
def test_non_finite_or_backwards_clock_holds_every_window_and_latches(bad):
    approvals, clock, grants, holds = _setup()
    pid = proposal(approvals, window_s=60)
    approvals.approve(pid, 'Bob')
    clock.now = bad
    with pytest.raises(ValueError, match='clock'):
        approvals.tick(pid)
    assert approvals.view(pid)['state'] == 'held' and holds == [('cell-1', 'clock_fault')]
    clock.now = 2000.0
    with pytest.raises(ValueError):
        proposal(approvals)


def test_abort_stops_leases_and_one_open_window_per_workcell():
    approvals, clock, grants, holds = _setup()
    first = proposal(approvals)
    approvals.approve(first, 'Bob')
    second = proposal(approvals, proposer='Carol')
    with pytest.raises(ValueError):
        approvals.approve(second, 'Bob')
    approvals.abort(first, 'Bob')
    assert approvals.tick(first) is None and holds[0][1] == 'aborted_by:Bob'
    assert approvals.approve(second, 'Bob')['state'] == 'active'


def test_stale_proposal_cannot_be_approved():
    approvals, clock, *_ = _setup()
    pid = proposal(approvals)
    clock.now += 16 * 60
    with pytest.raises(ValueError):
        approvals.approve(pid, 'Bob')


@pytest.mark.parametrize('change', [{'policy_digest': 'XYZ'}, {'proposer': ' '}, {'scope': ''}, {'workcell_id': None}])
def test_proposal_fields_are_validated(change):
    approvals, *_ = _setup()
    with pytest.raises(ValueError):
        proposal(approvals, **change)


def client_for(tmp_path):
    store = FleetTaskStore(tmp_path / 'fleet.db')
    tasks = FleetTaskService(store, robot_ids=())
    users = {sha256(b'a-token').hexdigest(): {'principal_id': 'operator-a', 'role': 'operator'},
             sha256(b'b-token').hexdigest(): {'principal_id': 'operator-b', 'role': 'operator'},
             sha256(b'v-token').hexdigest(): {'principal_id': 'viewer-a', 'role': 'viewer'}}

    class Transport:
        pass

    app = create_app(FleetConsole([], []), task_service=tasks, site_users=users, omx_instances={'cell-1': 'arm-1'},
                     omx_stop_transport=Transport(), start_task_dispatcher=False)
    return TestClient(app)


A = {'Authorization': 'Bearer a-token'}
B = {'Authorization': 'Bearer b-token'}
V = {'Authorization': 'Bearer v-token'}
BODY = dict(workcell_id='cell-1', policy_digest=DIGEST, rig_revision='rig-1', calibration_revision='cal-1',
            scope='stack-t1')


def test_routes_enforce_two_named_operators_and_refuse_approval_without_lease_transport(tmp_path):
    client = client_for(tmp_path)
    created = client.post('/api/fleet/policy-approvals', headers=A, json=BODY)
    assert created.status_code == 201 and created.json()['proposer'] == 'operator-a'
    pid = created.json()['id']
    same = client.post(f'/api/fleet/policy-approvals/{pid}/approve', headers=A)
    assert same.status_code == 403 and same.json()['detail']['code'] == 'PROPOSER_APPROVER_MUST_DIFFER'
    no_port = client.post(f'/api/fleet/policy-approvals/{pid}/approve', headers=B)
    assert no_port.status_code == 409 and no_port.json()['detail']['code'] == 'APPROVAL_STATE_CONFLICT'
    listing = client.get('/api/fleet/policy-approvals', headers=V).json()
    assert listing['lease_delivery_connected'] is False and listing['approvals'][0]['state'] == 'proposed'
    assert client.post(f'/api/fleet/policy-approvals/{pid}/abort', headers=B).json()['state'] == 'aborted'
    again = client.post(f'/api/fleet/policy-approvals/{pid}/abort', headers=B)
    assert again.status_code == 409 and again.json()['detail']['code'] == 'APPROVAL_STATE_CONFLICT'


def test_routes_refuse_viewer_unknown_workcell_long_window_and_extra_fields(tmp_path):
    client = client_for(tmp_path)
    assert client.post('/api/fleet/policy-approvals', headers=V, json=BODY).status_code in (401, 403)
    assert client.post('/api/fleet/policy-approvals', headers=A, json={**BODY, 'workcell_id': 'x'}).status_code == 404
    assert client.post('/api/fleet/policy-approvals', headers=A, json={**BODY, 'window_minutes': 31}).status_code == 422
    assert client.post('/api/fleet/policy-approvals', headers=A, json={**BODY, 'proposer': 'mallory'}).status_code == 422
    assert client.post('/api/fleet/policy-approvals/none/approve', headers=B).status_code == 404
