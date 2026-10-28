"""MediaMTX callback and browser intent routes use the real lease authority."""

import importlib
from pathlib import Path
import sys

from fastapi.testclient import TestClient
import pytest

from test_media_authority import media  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def client_for(authority):
    assert (ROOT / 'src/rosy_media/server.py').is_file(), 'D-789 media HTTP adapter missing'
    module = importlib.import_module('rosy_media.server')
    return TestClient(module.create_app(authority, admin_token='local-admin-only', clock=lambda: 101))


def test_mediamtx_auth_callback_requires_scoped_intent_and_protocol(media):
    authority, token, _, _ = media
    with client_for(authority) as client:
        payload = dict(token=token(), action='read', path='robots/rosy_01/front',
                       protocol='webrtc', id='viewer-1')
        assert client.post('/auth', json=payload).status_code == 403
        auth = {'Authorization': 'Bearer ' + token()}
        assert client.post('/v1/intents', headers=auth).status_code == 201
        assert client.post('/auth', json=payload).status_code == 200
        assert client.post('/auth', json={**payload, 'protocol': 'rtsp'}).status_code == 403
        assert client.post('/auth', json={**payload, 'id': 'other'}).status_code == 403
        assert client.post('/auth', json={'action': 'api', 'token': token()}).status_code == 403
        assert client.post('/auth', json={'action': 'api', 'token': 'local-admin-only'}).status_code == 200


def test_source_demand_requires_publish_grant_and_own_robot(media):
    authority, token, _, _ = media
    with client_for(authority) as client:
        assert client.get('/v1/sources/rosy_01/demand').status_code == 401
        read = {'Authorization': 'Bearer ' + token()}
        assert client.get('/v1/sources/rosy_01/demand', headers=read).status_code == 403
        source = {'Authorization': 'Bearer ' + token('publish', 'b'*32)}
        assert client.get('/v1/sources/rosy_01/demand', headers=source).json()['active'] is False
        assert client.get('/v1/sources/rosy_02/demand', headers=source).status_code == 403
        client.post('/v1/intents', headers=read)
        assert client.get('/v1/sources/rosy_01/demand', headers=source).json()['active'] is True


def test_media_session_close_checks_exact_grant_owner(media):
    authority, token, _, kicked = media
    with client_for(authority) as client:
        auth = {'Authorization': 'Bearer ' + token()}
        client.post('/v1/intents', headers=auth)
        client.post('/auth', json=dict(token=token(), action='read', path='robots/rosy_01/front',
                                      protocol='webrtc', id='viewer-1'))
        other = {'Authorization': 'Bearer ' + token(grant_id='c'*32)}
        assert client.delete('/v1/sessions/viewer-1', headers=other).status_code == 403
        assert client.delete('/v1/sessions/viewer-1', headers=auth).status_code == 204
        assert kicked == ['viewer-1']


def test_active_session_renewal_is_bound_to_grant_not_whep_secret_url(media):
    authority, token, _, kicked = media
    with client_for(authority) as client:
        auth = {'Authorization': 'Bearer ' + token()}
        assert client.get('/v1/session', headers=auth).status_code == 404
        client.post('/v1/intents', headers=auth)
        client.post('/auth', json=dict(token=token(), action='read', path='robots/rosy_01/front',
                                      protocol='webrtc', id='actual-management-session-id'))
        assert client.get('/v1/session', headers=auth).json()['session_id'] == 'actual-management-session-id'
        renewed = {'Authorization': 'Bearer ' + token(now=101)}
        assert client.post('/v1/session/renew', headers=renewed).status_code == 200
        other = {'Authorization': 'Bearer ' + token(grant_id='c'*32)}
        assert client.post('/v1/session/renew', headers=other).status_code == 403
        assert client.delete('/v1/session', headers=renewed).status_code == 204
        assert kicked == ['actual-management-session-id']
