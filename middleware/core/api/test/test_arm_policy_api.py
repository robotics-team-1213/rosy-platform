"""CORE HTTP admission over the real OMX session; driver and RGB are host fixtures."""
import base64
import hashlib
import io
import sys
from pathlib import Path
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
import threading
from contextlib import contextmanager, nullcontext

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
    port = CoreArmPolicyPort(session, capture=lambda: nullcontext((rgb, camera)), principal='operator-a')
    app = create_app({}, SimpleNamespace(arm_policy=port,
        safety=SimpleNamespace(estop=False, estop_listeners=[])))
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
    assert source['cameras'] == [source['camera']] and info.json()['cameras'] == [info.json()['camera']]
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


def test_core_estop_stops_arm_without_another_client_request(tmp_path):
    client, session, driver, *_ = setup_api(tmp_path)
    source = observation(client, session)
    assert client.post('/api/v1/arm/actions', json=action(source, session)).status_code == 202
    safety = client.app.state.core.safety
    safety.estop = True
    for listener in safety.estop_listeners:
        listener()
    assert session.hold_reason and driver.handles[0].cancel_calls == 1
    assert not session.fence.is_open(authority_epoch=2, dispatch_generation=7)


def test_stop_does_not_wait_for_blocked_rgb_capture(tmp_path):
    client, session, driver, *_ = setup_api(tmp_path)
    port = client.app.state.core.arm_policy
    capture = port.capture
    entered, release = threading.Event(), threading.Event()

    @contextmanager
    def blocked_capture():
        with capture() as frame:
            entered.set()
            assert release.wait(5)
            yield frame

    port.capture = blocked_capture
    with ThreadPoolExecutor(max_workers=2) as pool:
        reading = pool.submit(client.post, '/api/v1/arm/observations',
                              json={'policy_revision': session.lease.policy_revision})
        assert entered.wait(2)
        stopping = pool.submit(client.post, '/api/v1/arm/stop')
        try:
            assert stopping.result(timeout=0.5).status_code == 200
            assert not session.fence.is_open(authority_epoch=2, dispatch_generation=7)
        finally:
            release.set()
        assert reading.result(timeout=2).status_code == 403
    assert not driver.commands


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


def test_pinned_capture_does_not_refresh_an_aged_observation(tmp_path):
    client, session, driver, clock, *_ = setup_api(tmp_path)
    port = client.app.state.core.arm_policy
    capture = port.capture
    @contextmanager
    def delayed():
        with capture() as frame:
            clock[0] += .051
            yield frame
    port.capture = delayed
    reply = client.post('/api/v1/arm/observations',json={'policy_revision':session.lease.policy_revision})
    assert reply.status_code == 403 and session.hold_reason
    assert not driver.commands


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
    assert client.post('/api/v1/arm/actions', json=body).status_code == 400
    assert not driver.commands


def http_adapter(client, monkeypatch):
    sys.path.insert(0, str(ROOT / 'integrations/robots/omx/src'))
    from rosy.integrations.robots.omx import core_arm_client
    from urllib.error import HTTPError
    from urllib.parse import urlsplit
    calls = []

    def urlopen(request, timeout):
        path = urlsplit(request.full_url).path
        calls.append((request.method, path))
        response = client.request(request.method, path, content=request.data,
                                  headers=dict(request.header_items()))
        stream = io.BytesIO(response.content)
        if response.status_code >= 400:
            raise HTTPError(request.full_url, response.status_code, 'refused', {}, stream)
        return stream

    monkeypatch.setattr(core_arm_client, 'urlopen', urlopen)
    return core_arm_client, calls


def test_lerobot_client_uses_core_for_observation_action_and_stop(tmp_path, monkeypatch):
    api, session, driver, *_ = setup_api(tmp_path)
    module, calls = http_adapter(api, monkeypatch)
    robot = module.CoreArmClient('http://localhost:8080', token='test-token',
                                 policy_revision=session.lease.policy_revision)
    robot.connect()
    source = robot.get_observation()
    assert source['positions']['joint_1'] == 0.1
    sent = robot.send_action({'joint_1': 0.101, 'joint_2': 0.001})
    assert sent == {'joint_1': 0.101, 'joint_2': 0.001}
    with pytest.raises(RuntimeError, match='observation'):
        robot.send_action(sent)
    assert len(driver.commands) == 1
    robot.disconnect()
    assert calls == [('GET', '/api/v1/arm/policy'), ('POST', '/api/v1/arm/observations'),
                     ('POST', '/api/v1/arm/actions'), ('POST', '/api/v1/arm/stop')]


def test_lerobot_client_refuses_wrong_model_pin(tmp_path, monkeypatch):
    api, *_ = setup_api(tmp_path)
    module, calls = http_adapter(api, monkeypatch)
    robot = module.CoreArmClient('http://localhost:8080', token='test-token', policy_revision='b' * 64)
    with pytest.raises(ValueError, match='policy'):
        robot.connect()
    assert calls == [('GET', '/api/v1/arm/policy')]


def test_client_stops_on_uncertain_action_without_resubmitting(tmp_path, monkeypatch):
    api, session, driver, *_ = setup_api(tmp_path)
    module, calls = http_adapter(api, monkeypatch)
    robot = module.CoreArmClient('http://localhost:8080', token='test-token',
                                 policy_revision=session.lease.policy_revision)
    robot.connect()
    robot.get_observation()
    original = module.urlopen

    def lost_response(request, timeout):
        response = original(request, timeout)
        if request.full_url.endswith('/actions'):
            raise TimeoutError('response lost after admission')
        return response

    monkeypatch.setattr(module, 'urlopen', lost_response)
    with pytest.raises(TimeoutError):
        robot.send_action({'joint_1': 0.101, 'joint_2': 0.001})
    assert len(driver.commands) == 1 and driver.handles[0].cancel_calls == 1
    assert calls[-1] == ('POST', '/api/v1/arm/stop')


def test_two_installed_cameras_reach_owner_in_installed_order(tmp_path):
    """D-854: N cameras; the one-camera ``camera`` field is absent and every frame binds the action."""
    session, runtime, driver, clock, authority, *_ = attached(tmp_path, camera=2)
    front, top = bytes(range(12)), bytes(range(12, 24))
    cameras = (CameraSnapshot('front', 'cam-front', 'a' * 64, (3, 2, 2), 10_000_000_000, hashlib.sha256(front).hexdigest()),
               CameraSnapshot('top', 'cam-top', 'b' * 64, (3, 2, 2), 10_000_000_000, hashlib.sha256(top).hexdigest()))
    session._cameras = lambda: cameras
    from rosy.execution.local.core_arm_policy import CoreArmPolicyPort
    port = CoreArmPolicyPort(session, capture=lambda: nullcontext(((front, cameras[0]), (top, cameras[1]))),
                             principal='operator-a')
    app = create_app({}, SimpleNamespace(arm_policy=port, safety=SimpleNamespace(estop=False, estop_listeners=[])))
    app.dependency_overrides[operator] = lambda: SimpleNamespace(token_id='operator-a', role='operator')
    client = TestClient(app)
    info = client.get('/api/v1/arm/policy').json()
    assert [c['name'] for c in info['cameras']] == ['front', 'top'] and 'camera' not in info
    source = observation(client, session)
    assert 'camera' not in source
    assert [base64.b64decode(c['rgb_base64']) for c in source['cameras']] == [front, top]
    result = client.post('/api/v1/arm/actions', json=action(source, session))
    assert result.status_code == 202 and result.json()['accepted'] is True
    assert len(driver.commands) == 1


def test_camera_capture_must_match_every_installed_camera(tmp_path):
    session, *_ = attached(tmp_path, camera=2)
    front = bytes(range(12))
    camera = CameraSnapshot('front', 'cam-front', 'a' * 64, (3, 2, 2), 10_000_000_000, hashlib.sha256(front).hexdigest())
    session._cameras = lambda: (camera, CameraSnapshot('top', 'cam-top', 'b' * 64, (3, 2, 2), 10_000_000_000, 'd' * 64))
    with pytest.raises(ValueError):
        session.capture_inference_inputs(((front, camera),))
    with pytest.raises(ValueError):
        session.capture_inference_input(front, camera)


def two_camera_api(tmp_path, *, swap=False):
    session, runtime, driver, clock, authority, *_ = attached(tmp_path, camera=2)
    clock[0] = 10.01
    front, top = bytes(range(12)), bytes(range(12, 24))
    # top arrives after the joint snapshot (10.0 s): only the latest receipt time keeps action causality.
    cameras = (CameraSnapshot('front', 'cam-front', 'a' * 64, (3, 2, 2), 9_995_000_000, hashlib.sha256(front).hexdigest()),
               CameraSnapshot('top', 'cam-top', 'b' * 64, (3, 2, 2), 10_005_000_000, hashlib.sha256(top).hexdigest()))
    session._cameras = lambda: cameras
    pairs = ((front, cameras[0]), (top, cameras[1]))
    from rosy.execution.local.core_arm_policy import CoreArmPolicyPort
    port = CoreArmPolicyPort(session, capture=lambda: nullcontext(pairs[::-1] if swap else pairs), principal='operator-a')
    app = create_app({}, SimpleNamespace(arm_policy=port, safety=SimpleNamespace(estop=False, estop_listeners=[])))
    app.dependency_overrides[operator] = lambda: SimpleNamespace(token_id='operator-a', role='operator')
    return TestClient(app), session, driver, cameras


def test_latest_camera_receipt_bounds_action_causality(tmp_path):
    client, session, driver, cameras = two_camera_api(tmp_path)
    source = observation(client, session)
    assert [(c['received_at_ns'], c['frame_sha256']) for c in source['cameras']] == [
        (c.received_at_ns, c.frame_sha256) for c in cameras]
    result = client.post('/api/v1/arm/actions', json=action(source, session))
    assert result.status_code == 202 and result.json()['accepted'] is True and len(driver.commands) == 1


def test_cameras_out_of_installed_order_are_refused(tmp_path):
    client, session, driver, _ = two_camera_api(tmp_path, swap=True)
    reply = client.post('/api/v1/arm/observations', json={'policy_revision': session.lease.policy_revision})
    assert reply.status_code == 409 and driver.commands == []
