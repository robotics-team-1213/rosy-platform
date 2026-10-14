from types import SimpleNamespace
import pytest
from starlette.websockets import WebSocketDisconnect


@pytest.fixture
def account_robot(core_client):
    client, svc = core_client()
    claims = SimpleNamespace(sub='account-1', sid='family-1', exp=9999999999,
        aud='robot:r1', grants=[], permits=lambda resource, capability: capability == 'robot.read')
    class Receiver:
        resource = 'robot:r1'
        callback = 'https://testserver/api/account/callback'
        def resolve(self, cookie):
            return claims if cookie == 'account-cookie' else None
    client.app.state.account_client = Receiver()
    client.cookies.set('rosy_app_account', 'account-cookie')
    return client, claims


def test_cookie_reads_but_does_not_inherit_operator_or_admin(account_robot):
    client, claims = account_robot
    assert client.get('/api/v1/auth/whoami').status_code == 200
    assert client.post('/api/v1/teleop', json={'linear':0, 'angular':0}, headers={'Origin':'https://testserver'}).status_code == 403
    claims.permits = lambda resource, capability: capability == 'robot.admin'
    assert client.get('/api/v1/auth/whoami').status_code == 403


def test_cookie_writes_require_same_origin_and_cannot_mint_legacy_tokens(account_robot):
    client, claims = account_robot
    claims.permits = lambda resource, capability: True
    assert client.post('/api/v1/safety/stop', headers={'Origin':'https://evil.test'}).status_code == 403
    assert client.post('/api/v1/system/tokens', json={'role':'administrator'},
                       headers={'Origin':'https://testserver'}).status_code == 403
    assert client.post('/api/v1/auth/enrollment-codes', json={},
                       headers={'Origin':'https://testserver'}).status_code == 403


def test_cookie_websocket_does_not_wait_for_token_and_rejects_foreign_origin(account_robot):
    client, _ = account_robot
    with client.websocket_connect('/ws/state', headers={'Origin':'https://testserver'}) as ws:
        assert 'robot_id' in ws.receive_json()
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/ws/state', headers={'Origin':'https://evil.test'}) as ws:
            ws.receive_json()
