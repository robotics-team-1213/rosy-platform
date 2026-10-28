"""D-789 media credentials are separate from ordinary CORE bearer tokens."""

import importlib.util
import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


AUTH = {'Authorization': 'Bearer rosy-dev-viewer'}
PATH = '/api/v1/vision/media/grants'


def enable(tc, svc):
    assert importlib.util.find_spec('core_features.vision.media_grants')
    from core_features.vision.media_grants import MediaGrantService
    from core_api_web.api.deps import token_alive
    key = Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    service = MediaGrantService(robot_id='rosy_01', audience='site:lab', private_key=key,
        key_id='media-1', owner_allowed=lambda owner, action:
        action == 'read' and token_alive(svc.config, owner))
    tc.app.state.media_grants = service
    tc.app.state.media_site_url = 'https://media.example'
    return service


def test_media_grant_requires_core_auth_and_explicit_configuration(core_client):
    tc, _ = core_client()
    assert tc.post(PATH, json={'robot_id': 'rosy_01'}).status_code == 401
    disabled = tc.post(PATH, json={'robot_id': 'rosy_01'}, headers=AUTH)
    assert disabled.status_code == 503
    assert disabled.json()['error']['code'] == 'MEDIA_UNAVAILABLE'


def test_media_grant_issue_validate_renew_and_revoke(core_client):
    tc, svc = core_client()
    service = enable(tc, svc)
    response = tc.post(PATH, json={'robot_id': 'rosy_01'}, headers=AUTH)
    assert response.status_code == 201
    assert response.headers['cache-control'] == 'no-store'
    grant = response.json()
    assert grant['action'] == 'read'
    assert grant['site_url'] == 'https://media.example'
    assert 0 < grant['expires_at'] - time.time() <= 60
    media_auth = {'Authorization': 'Bearer ' + grant['token']}
    active = tc.post('/api/v1/vision/media/validate', headers=media_auth)
    assert active.status_code == 200
    assert active.json()['active'] is True
    assert tc.post('/api/v1/vision/media/validate', headers=AUTH).json() == {'active': False}
    renewed = tc.post(PATH + '/' + grant['grant_id'] + '/renew', headers=AUTH)
    assert renewed.status_code == 200
    assert renewed.json()['grant_id'] == grant['grant_id']
    assert tc.delete(PATH + '/' + grant['grant_id'], headers=AUTH).status_code == 204
    assert service.check(grant['token'], now=time.time()) == {'active': False}


def test_media_grant_blocks_cross_robot_publish_and_cross_owner_revoke(core_client):
    tc, svc = core_client()
    enable(tc, svc)
    assert tc.post(PATH, json={'robot_id': 'rosy_02'}, headers=AUTH).status_code == 403
    assert tc.post(PATH, json={'robot_id': 'rosy_01', 'action': 'publish'}, headers=AUTH).status_code == 400
    grant = tc.post(PATH, json={'robot_id': 'rosy_01'}, headers=AUTH).json()
    other = {'Authorization': 'Bearer rosy-dev-operator'}
    assert tc.delete(PATH + '/' + grant['grant_id'], headers=other).status_code == 403


def test_media_validate_never_accepts_url_credentials(core_client):
    tc, svc = core_client()
    enable(tc, svc)
    grant = tc.post(PATH, json={'robot_id': 'rosy_01'}, headers=AUTH).json()
    assert tc.post('/api/v1/vision/media/validate?token=' + grant['token']).status_code == 401


def configured_media(tmp_path, **changes):
    private = Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    (tmp_path / 'key.pem').write_bytes(private)
    (tmp_path / 'source.token').write_text('source-only-test-token-32-character-value')
    return dict(enabled=True, site_url='https://media.example', audience='site:lab', key_id='media-1',
                signing_key_file=str(tmp_path / 'key.pem'), source_credential_file=str(tmp_path / 'source.token'),
                **changes)


def test_source_credential_cannot_be_replaced_by_viewer_and_rotation_revokes(core_client, tmp_path):
    media = configured_media(tmp_path)
    tc, _ = core_client(config_overrides={'vision': {'media': media}})
    endpoint = '/api/v1/vision/media/source-grant'
    assert tc.post(endpoint, json={'robot_id': 'rosy_01'}, headers=AUTH).status_code == 403
    source = {'Authorization': 'Bearer source-only-test-token-32-character-value'}
    response = tc.post(endpoint, json={'robot_id': 'rosy_01'}, headers=source)
    assert response.status_code == 201
    grant = response.json()
    assert grant['action'] == 'publish'
    renewed = tc.post(endpoint, json={'robot_id': 'rosy_01', 'grant_id': grant['grant_id']}, headers=source)
    assert renewed.status_code == 201
    assert renewed.json()['grant_id'] == grant['grant_id']
    (tmp_path / 'source.token').write_text('rotated-source-test-token-32-character-value')
    media_auth = {'Authorization': 'Bearer ' + grant['token']}
    assert tc.post('/api/v1/vision/media/validate', headers=media_auth).json() == {'active': False}


def test_site_media_configuration_makes_webrtc_the_default_and_false_opts_out(core_client, tmp_path):
    media = configured_media(tmp_path)
    del media['enabled']
    tc, _ = core_client(config_overrides={'vision': {'media': media}})
    assert tc.post(PATH, json={'robot_id': 'rosy_01'}, headers=AUTH).status_code == 201
    pilot = tc.get('/pilot').headers.get('content-security-policy', '')
    assert "connect-src 'self' ws: wss: https://media.example;" in pilot
    dashboard = tc.get('/dashboard').headers.get('content-security-policy', '')
    assert "connect-src 'self' ws: wss: https://media.example;" in dashboard
    disabled = {**configured_media(tmp_path), 'enabled': False}
    opted_out, _ = core_client(config_overrides={'vision': {'media': disabled}})
    assert opted_out.post(PATH, json={'robot_id': 'rosy_01'}, headers=AUTH).status_code == 503
    no_site = configured_media(tmp_path)
    del no_site['site_url']
    jpeg_only, _ = core_client(config_overrides={'vision': {'media': no_site}})
    assert jpeg_only.post(PATH, json={'robot_id': 'rosy_01'}, headers=AUTH).status_code == 503
    assert "https://" not in jpeg_only.get('/pilot').headers.get('content-security-policy', '')
    assert "https://" not in jpeg_only.get('/dashboard').headers.get('content-security-policy', '')


def test_invalid_media_audience_disables_media_without_blocking_core(core_client, tmp_path):
    media = configured_media(tmp_path)
    media['audience'] = 'robot:wrong-kind'
    tc, _ = core_client(config_overrides={'vision': {'media': media}})
    assert tc.get('/api/v1', headers=AUTH).status_code == 200
    assert tc.post(PATH, json={'robot_id': 'rosy_01'}, headers=AUTH).status_code == 503
