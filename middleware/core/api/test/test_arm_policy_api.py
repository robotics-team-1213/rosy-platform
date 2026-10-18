"""CORE HTTP admission over the real OMX session; driver and RGB are host fixtures."""
import base64
import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'middleware/robot_execution/local/test'))
from test_omx_policy_session import setup_session, CameraSnapshot
from test_policy_runtime_binding import attached
from core_api_web.api.app import create_app
from core_api_web.api.v1.common import operator


def setup_api(tmp_path):
    session, runtime, driver, clock, authority, *_ = attached(tmp_path, camera=True)
    rgb = bytes(range(12))
    camera = CameraSnapshot('front', 'cam-front', 'a' * 64, (3, 2, 2),
                            10_000_000_000, hashlib.sha256(rgb).hexdigest())
    session._cameras = lambda: (camera,)
    from rosy.execution.local.core_arm_policy import CoreArmPolicyPort
    port = CoreArmPolicyPort(session, capture=lambda: (rgb, camera), principal='operator-a')
    app = create_app({}, SimpleNamespace(arm_policy=port))
    auth = SimpleNamespace(token_id='operator-a', role='operator')
    app.dependency_overrides[operator] = lambda: auth
    return TestClient(app), session, driver, clock, authority, auth


def observation(client, session):
    reply = client.post('/api/v1/arm/observations', json={'policy_revision': session.lease.policy_revision})
    assert reply.status_code == 200, reply.text
    return reply.json()


def action(source, session):
    return dict(observation_id=source['observation_id'], policy_revision=session.lease.policy_revision,
                positions={'joint_1': 0.101, 'joint_2': 0.001})


def test_core_observation_and_action_reach_existing_owner(tmp_path):
    client, session, driver, *_ = setup_api(tmp_path)
    info = client.get('/api/v1/arm/policy')
    assert info.status_code == 200
    assert info.json()['joint_names'] == ['joint_1', 'joint_2']
    source = observation(client, session)
    assert base64.b64decode(source['camera']['rgb_base64']) == bytes(range(12))
    assert source['positions'] == {'joint_1': 0.1, 'joint_2': 0.0}
    result = client.post('/api/v1/arm/actions', json=action(source, session))
    assert result.status_code == 202, result.text
    assert result.json()['accepted'] is True
    assert len(driver.commands) == 1 and driver.commands[0].owner == 'learned_policy'
    assert driver.commands[0].source_state_sequence == 10
    assert client.post('/api/v1/arm/actions', json=action(source, session)).status_code == 409
    assert len(driver.commands) == 1


@pytest.mark.parametrize('failure', ['stale', 'revoked', 'revision', 'principal', 'replaced'])
def test_core_refuses_before_driver_submission(tmp_path, failure):
    client, session, driver, clock, authority, auth = setup_api(tmp_path)
    source = observation(client, session)
    body = action(source, session)
    if failure == 'stale':
        clock[0] += 0.051
    elif failure == 'revoked':
        authority[0] = False
    elif failure == 'revision':
        body['policy_revision'] = 'b' * 64
    elif failure == 'principal':
        auth.token_id = 'operator-b'
    else:
        observation(client, session)
    assert client.post('/api/v1/arm/actions', json=body).status_code in (403, 409)
    assert not driver.commands


def test_port_requires_independent_runtime_watchdog(tmp_path):
    from rosy.execution.local.core_arm_policy import CoreArmPolicyPort
    session, *_ = setup_session(tmp_path)
    with pytest.raises(ValueError, match='watchdog-bound'):
        CoreArmPolicyPort(session, capture=lambda: None, principal='operator-a')


def test_stop_latches_existing_fence_and_cancels_own_goal(tmp_path):
    client, session, driver, *rest = setup_api(tmp_path)
    source = observation(client, session)
    assert client.post('/api/v1/arm/actions', json=action(source, session)).status_code == 202
    rest[-1].token_id = 'another-operator'
    response = client.post('/api/v1/arm/stop')
    assert response.status_code == 200, response.text
    assert response.json()['physical_stop_verified'] is False
    assert driver.handles[0].cancel_calls == 1
    assert not session.fence.is_open(authority_epoch=2, dispatch_generation=7)
    assert session.hold_reason


def test_unbound_core_refuses_arm_execution():
    app = create_app({}, SimpleNamespace())
    app.dependency_overrides[operator] = lambda: SimpleNamespace(token_id='a', role='operator')
    client = TestClient(app)
    assert client.get('/api/v1/arm/policy').status_code == 503


@pytest.mark.parametrize('bad', [True, '0.1', None])
def test_non_numeric_targets_never_reach_owner(tmp_path, bad):
    client, session, driver, *_ = setup_api(tmp_path)
    body = action(observation(client, session), session)
    body['positions']['joint_1'] = bad
    assert client.post('/api/v1/arm/actions', json=body).status_code == 422
    assert not driver.commands
