"""D-757 first-party code exchange and refresh replay boundaries."""
from copy import deepcopy
import base64
import hashlib
import json
from urllib.parse import urlencode, urlsplit, parse_qs

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from fleet.server.account_authority import AccountAuthority

ISSUER = 'https://account.example.test'
CALLBACK = 'https://robot.example.test/account/callback'
VERIFIER = 'x' * 64
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b'=').decode()


@pytest.fixture
def authority(tmp_path):
    private = Ed25519PrivateKey.generate()
    pem = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
    context = {'account_id': 'account-1', 'login': 'alice', 'principal_id': 'alice',
               'role': 'viewer', 'grants': [{'resource': 'robot:r1', 'capabilities': ['robot.read']}],
               'revision': 1, 'session_family': 'family-1'}
    families = {'family-1': context}
    instance = AccountAuthority(tmp_path / 'accounts.sqlite3', issuer=ISSUER, private_key=pem,
        key_id='key-1', clients={'robot-app': {'redirect_uris': [CALLBACK], 'resources': ['robot:r1']}},
        resolve_family=lambda db, family: deepcopy(families.get(family)),
        revoke_family=lambda db, family: families.pop(family, None), clock=lambda: 1000)
    return instance, context, families


def authorize(instance, context, **changes):
    params = {'response_type': 'code', 'client_id': 'robot-app', 'redirect_uri': CALLBACK,
              'scope': 'robot:r1', 'state': 'browser-state', 'code_challenge': CHALLENGE,
              'code_challenge_method': 'S256', **changes}
    return instance.authorize(urlencode(params), context)


def exchange(instance, code, **changes):
    params = {'grant_type': 'authorization_code', 'client_id': 'robot-app', 'code': code,
              'redirect_uri': CALLBACK, 'code_verifier': VERIFIER, **changes}
    return instance.token(urlencode(params))


def get_code(instance, context):
    headers, body, status = authorize(instance, context)
    assert status == 302
    query = parse_qs(urlsplit(headers['Location']).query)
    assert query['state'] == ['browser-state']
    return query['code'][0]


def test_code_exchange_is_single_use_scoped_and_introspected(authority):
    instance, context, _ = authority
    code = get_code(instance, context)
    headers, body, status = exchange(instance, code)
    assert status == 200
    assert headers['Cache-Control'] == 'no-store'
    tokens = json.loads(body)
    assert tokens['expires_in'] == 300
    assert instance.introspect(tokens['access_token'])['active'] is True
    assert exchange(instance, code)[2] == 400


@pytest.mark.parametrize('change', [{'redirect_uri': 'https://evil.example.test/callback'},
    {'scope': 'robot:r2'}, {'code_challenge_method': 'plain'}, {'response_type': 'token'},
    {'code_challenge': 'short'}, {'state': ''}])
def test_invalid_authorization_never_redirects_to_untrusted_target(authority, change):
    instance, context, _ = authority
    headers, _, status = authorize(instance, context, **change)
    assert status in (400, 403)
    assert 'Location' not in headers


def test_wrong_pkce_does_not_issue_access(authority):
    instance, context, _ = authority
    code = get_code(instance, context)
    assert exchange(instance, code, code_verifier='z' * 64)[2] == 400


def test_account_revocation_between_code_and_exchange_is_enforced(authority):
    instance, context, families = authority
    code = get_code(instance, context)
    families.clear()
    assert exchange(instance, code)[2] == 400


def test_refresh_rotation_replay_revokes_family(authority):
    instance, context, families = authority
    tokens = json.loads(exchange(instance, get_code(instance, context))[1])
    form = urlencode({'grant_type': 'refresh_token', 'client_id': 'robot-app',
                      'refresh_token': tokens['refresh_token']})
    _, body, status = instance.token(form)
    assert status == 200
    rotated = json.loads(body)
    assert rotated['refresh_token'] != tokens['refresh_token']
    assert instance.token(form)[2] == 400
    assert not families
    assert instance.introspect(rotated['access_token']) == {'active': False}


def test_revision_change_and_family_logout_invalidate_access(authority):
    instance, context, families = authority
    tokens = json.loads(exchange(instance, get_code(instance, context))[1])
    families['family-1']['revision'] = 2
    assert instance.introspect(tokens['access_token']) == {'active': False}
