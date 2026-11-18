"""D-1024 3: CORE's lease and hold routes. Only the Fleet principal delivers, the runner's never; HOLD removes authority."""
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_arm_policy_api import setup_api, observation, action  # noqa: E402
from rosy.execution.local.omx_policy import JointStateSnapshot  # noqa: E402
from rosy.execution.local.policy_lease import LeaseScope  # noqa: E402
from rosy.execution.local.policy_lease_push import PushLeaseReceiver  # noqa: E402

DIGEST = 'e' * 64


def wired(tmp_path):
    client, session, driver, clock, authority, auth = setup_api(tmp_path)
    lease = session.lease
    scope = LeaseScope(lease.identity, lease.episode_id, lease.policy_revision, lease.owner_session_id,
                       'w', 'rig', 'cal-7', 'scope')
    receiver = PushLeaseReceiver(scope, monotonic=lambda: clock[0], policy_digest=DIGEST)
    grant = dict(lease_id=lease.lease_id, episode_id=lease.episode_id, workcell_id=lease.identity.workcell_id,
                 policy_digest=DIGEST, rig_revision='rig', calibration_revision='cal-7', ttl_s=0.9, seq=1,
                 window_remaining_s=600.0)
    assert receiver.deliver(grant)
    grant = dict(grant, seq=2)
    session._authority = receiver.authority  # the session's authority is the pushed lease
    receiver.attach(session)
    client.port.lease_receiver, client.port.lease_principal = receiver, 'fleet'
    return client, session, clock, auth, grant


def as_(auth, who):
    auth.token_id = who


def test_fleet_principal_delivers_and_the_runner_principal_cannot(tmp_path):
    client, session, clock, auth, grant = wired(tmp_path)
    clock[0] = 10.3
    camera = session._cameras()[0]  # the installed camera frame must be as fresh as the joint state
    session._cameras = lambda: (replace(camera, received_at_ns=int(clock[0] * 1e9)),)
    session.observe(JointStateSnapshot({'joint_1': 0.1, 'joint_2': 0.0}, 99, 10.3, 'cal-7'))
    as_(auth, 'operator-a')
    refused = client.post('/api/v1/arm/lease', json=grant)
    assert refused.status_code == 403 and refused.json()['error']['code'] == 'ARM_POLICY_FORBIDDEN'
    assert session.lease.expires_at_ns == 10_900_000_000
    as_(auth, 'fleet')
    ok = client.post('/api/v1/arm/lease', json=grant)
    assert ok.status_code == 200, ok.text
    assert session.lease.expires_at_ns == 11_200_000_000 and not session.hold_reason


def test_fleet_principal_cannot_observe_or_act(tmp_path):
    client, session, clock, auth, grant = wired(tmp_path)
    as_(auth, 'fleet')
    reply = client.post('/api/v1/arm/observations', json={'policy_revision': session.lease.policy_revision})
    assert reply.status_code == 403
    reply = client.post('/api/v1/arm/actions', json=dict(observation_id='x', positions={'joint_1': 0.1},
                                                         policy_revision=session.lease.policy_revision))
    assert reply.status_code == 403 and not session.hold_reason


@pytest.mark.parametrize('change', [dict(extra=1), dict(ttl_s=3.0), dict(ttl_s=0), dict(ttl_s='1'),
                                    dict(policy_digest='nothex'),
                                    dict(seq=0), dict(window_remaining_s=0), dict(window_remaining_s=1801)])
def test_malformed_grants_are_400(tmp_path, change):
    client, session, clock, auth, grant = wired(tmp_path)
    as_(auth, 'fleet')
    assert client.post('/api/v1/arm/lease', json=dict(grant, **change)).status_code == 400


def test_scope_mismatch_is_409_and_holds(tmp_path):
    client, session, clock, auth, grant = wired(tmp_path)
    as_(auth, 'fleet')
    reply = client.post('/api/v1/arm/lease', json=dict(grant, policy_digest='f' * 64))
    assert reply.status_code == 409 and reply.json()['error']['code'] == 'ARM_POLICY_CONFLICT'
    assert session.hold_reason.startswith('requested_hold:lease_delivery_failed')
    assert client.post('/api/v1/arm/lease', json=grant).status_code == 409  # nothing re-arms


def test_hold_by_fleet_or_runner_latches_and_a_stranger_cannot(tmp_path):
    client, session, clock, auth, grant = wired(tmp_path)
    as_(auth, 'stranger')
    assert client.post('/api/v1/arm/hold', json={'reason': 'x'}).status_code == 403
    assert not session.hold_reason
    as_(auth, 'fleet')
    reply = client.post('/api/v1/arm/hold', json={'reason': 'window_ended'})
    assert reply.status_code == 200 and session.hold_reason == 'requested_hold:window_ended'
    assert client.post('/api/v1/arm/hold', json={'reason': ''}).status_code == 400
    as_(auth, 'operator-a')
    assert client.post('/api/v1/arm/hold', json={'reason': 'again'}).status_code == 200


def test_no_receiver_installed_refuses_both(tmp_path):
    client, session, driver, clock, authority, auth = setup_api(tmp_path)
    grant = dict(lease_id='l', episode_id='e', workcell_id='w', policy_digest=DIGEST, rig_revision='r',
                 calibration_revision='c', ttl_s=1.0, seq=1, window_remaining_s=5.0)
    assert client.post('/api/v1/arm/lease', json=grant).status_code == 403
    assert client.post('/api/v1/arm/hold', json={'reason': 'x'}).status_code == 403


def test_port_refuses_equal_principals_and_foreign_receivers(tmp_path):
    client, session, clock, auth, grant = wired(tmp_path)
    from rosy.execution.local.core_arm_policy import CoreArmPolicyPort
    port = client.port
    with pytest.raises(ValueError):
        CoreArmPolicyPort(session, capture=port.capture, principal='operator-a',
                          lease_receiver=port.lease_receiver, lease_principal='operator-a')
    with pytest.raises(ValueError):
        CoreArmPolicyPort(session, capture=port.capture, principal='operator-a',
                          lease_receiver=object(), lease_principal='fleet')


def test_fleet_token_is_refused_on_every_non_arm_route_with_a_real_token_record(tmp_path):
    """D-807: authenticate() against real token records; the Fleet credential reaches only lease, hold and stop."""
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from core_api_web.api.app import create_app
    from core_api_web.api.deps import token_digest
    client, session, clock, auth, grant = wired(tmp_path)
    config = {'auth': {'tokens': [
        {'id': 'fleet', 'role': 'operator', 'sha256': token_digest('fleet-secret')},
        {'id': 'operator-a', 'role': 'operator', 'sha256': token_digest('runner-secret')}]}}
    services = SimpleNamespace(arm_policy=client.port, config=config,
                               safety=SimpleNamespace(estop=False, estop_listeners=[]))
    real = TestClient(create_app(config, services), raise_server_exceptions=False)
    fleet, runner = {'Authorization': 'Bearer fleet-secret'}, {'Authorization': 'Bearer runner-secret'}
    for method, path in (('GET', '/api/v1/teleop/state'), ('GET', '/api/v1/arm/policy'),
                         ('POST', '/api/v1/navigation/goal'), ('POST', '/api/v1/arm/observations'),
                         ('GET', '/api/v1/system/tokens')):
        assert real.request(method, path, headers=fleet).status_code == 403, path
    assert real.post('/api/v1/arm/hold', headers=fleet, json={'reason': 'x'}).status_code == 200
    assert real.get('/api/v1/teleop/state', headers=runner).status_code != 403  # the runner token is unaffected
    assert real.post('/api/v1/arm/lease', headers=runner, json=grant).status_code == 403  # and cannot deliver


@pytest.mark.parametrize('change', [dict(lease_id=' '), dict(episode_id=' x'), dict(workcell_id=''),
                                    dict(rig_revision='\t'), dict(ttl_s=0.0005)])
def test_whitespace_strings_and_tiny_ttl_are_400_not_a_hold(tmp_path, change):
    client, session, clock, auth, grant = wired(tmp_path)
    as_(auth, 'fleet')
    assert client.post('/api/v1/arm/lease', json=dict(grant, **change)).status_code == 400
    assert not session.hold_reason
    assert client.post('/api/v1/arm/hold', json={'reason': '  '}).status_code == 400


def test_human_account_and_dev_tokens_are_refused_on_the_arm_routes():
    from types import SimpleNamespace
    from core_api_web.api.errors import ApiError
    from core_api_web.api.v1.arm import arm_caller
    machine = SimpleNamespace(account=None, shared_dev=False)
    assert arm_caller(machine) is machine
    for human in (SimpleNamespace(account=object(), shared_dev=False), SimpleNamespace(account=None, shared_dev=True)):
        with pytest.raises(ApiError) as caught:
            arm_caller(human)
        assert caught.value.http_status == 403


def test_real_dev_token_is_refused_on_arm_policy_without_overriding_operator(tmp_path):
    import hashlib
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from core_api_web.api.app import create_app
    from core_api_web.api.deps import DEV_TOKEN_DIGESTS
    client, *_ = wired(tmp_path)
    token = next(t for t in ('rosy-dev-admin', 'rosy-dev-operator', 'rosy-dev-viewer')
                 if hashlib.sha256(t.encode()).hexdigest() in DEV_TOKEN_DIGESTS and 'operator' in t)
    digest = hashlib.sha256(token.encode()).hexdigest()
    config = {'auth': {'tokens': [{'id': 'dev-op', 'role': 'operator', 'sha256': digest}]}}
    services = SimpleNamespace(arm_policy=client.port, config=config,
                               safety=SimpleNamespace(estop=False, estop_listeners=[]))
    real = TestClient(create_app(config, services), raise_server_exceptions=False)
    reply = real.get('/api/v1/arm/policy', headers={'Authorization': 'Bearer ' + token})
    assert reply.status_code in (401, 403) and 'policy_revision' not in reply.text


def test_fleet_token_has_no_websocket_path(tmp_path):
    """The websocket authorizer shares the scope helper, so the Fleet token cannot reach any socket (D-807)."""
    import asyncio
    from types import SimpleNamespace
    from core_api_web.api import ws
    from core_api_web.api.deps import token_digest
    client, *_ = wired(tmp_path)
    asked = []

    class Capability:
        def supports(self, name):
            asked.append(name)
            return False
    config = {'auth': {'tokens': [{'id': 'fleet', 'role': 'operator', 'sha256': token_digest('fleet-secret')},
                                  {'id': 'operator-a', 'role': 'operator', 'sha256': token_digest('runner-secret')}]}}
    services = SimpleNamespace(arm_policy=client.port, config=config, capability=Capability())

    def socket(path, secret):
        closed = []

        async def close(code=1000):
            closed.append(code)
        return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(core=services)), headers={}, client=None,
                               query_params={'token': secret}, url=SimpleNamespace(path=path), close=close,
                               state=SimpleNamespace()), closed

    for path in ('/ws/teleop', '/ws/swarm/reference'):
        for secret, expect_asked in (('fleet-secret', False), ('runner-secret', True)):
            asked.clear()
            websocket, closed = socket(path, secret)
            assert asyncio.run(ws._authorize(websocket, 'operator', 'drive.teleop')) is None and closed == [4403]
            # control: the runner token passes the role check and is stopped only by the capability gate; the Fleet
            # token is refused before the capability is consulted, so reverting the scope check fails this
            assert bool(asked) is expect_asked, (path, secret)
