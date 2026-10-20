"""Assistant uses existing named operator and CSRF authorization."""
from fakes import FakeRobot
from test_server_app import _named_client


def test_console_assistant_unconfigured_is_visible_but_never_executes(tmp_path):
    client = _named_client(tmp_path, FakeRobot('r1'))
    status = client.get('/api/fleet/assistant/status')
    assert status.status_code == 200, status.text
    assert status.json()['available'] is False and status.json()['mode'] == 'READ_ONLY'
    body = dict(conversation_id='conv-1', request_id='req-1', text='r1을 보내줘')
    received = client.post('/api/fleet/assistant/messages', json=body)
    assert received.status_code == 202, received.text
    assert received.json()['state'] == 'HOLD' and received.json()['action_admissible'] is False
    again = client.post('/api/fleet/assistant/messages', json=body)
    assert again.status_code == 200
    result = client.get('/api/fleet/assistant/messages/req-1')
    assert result.json() == received.json()
    assert result.headers['cache-control'] == 'no-store'
    history = client.get('/api/fleet/assistant/conversations/conv-1').json()
    assert len(history['messages']) == 1
    assert client.get('/api/fleet/assistant/messages/no-such-request').status_code == 404


def test_assistant_rejects_unauthenticated_and_forged_identity(tmp_path):
    client = _named_client(tmp_path, FakeRobot('r1'))
    body = dict(conversation_id='conv-1', request_id='req-1', text='안녕', principal_id='admin')
    assert client.post('/api/fleet/assistant/messages', json=body).status_code == 422
    client.headers.clear()
    assert client.get('/api/fleet/assistant/status').status_code == 401
    assert client.post('/api/fleet/assistant/messages', json=body).status_code == 401
