"""Signed OIDC responses and one-time browser-bound callbacks."""
import base64
import json
import time
from urllib.parse import parse_qs, urlsplit
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes
from learning_oauth import OAuth
from learning_accounts import AccountError
from test_learning_accounts import accounts, sign_in


def b64(value): return base64.urlsafe_b64encode(value).rstrip(b'=').decode()


class Provider:
    def __init__(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.claims = {}; self.calls = []; self.scope = 'openid profile read-repos gated-repos write-repos manage-repos'

    def __call__(self, method, url, *, data=None, headers=None):
        self.calls.append((method, url, data))
        if url.endswith('/jwks'):
            n = self.key.public_key().public_numbers()
            return {'keys': [{'kty': 'RSA', 'kid': 'test', 'alg': 'RS256', 'use': 'sig',
                'n': b64(n.n.to_bytes(256, 'big')), 'e': b64(n.e.to_bytes(3, 'big'))}]}
        if url.endswith('/token'):
            header = b64(json.dumps({'alg': 'RS256', 'kid': 'test'}).encode())
            payload = b64(json.dumps(self.claims).encode()); message = (header + '.' + payload).encode()
            signature = self.key.sign(message, padding.PKCS1v15(), hashes.SHA256())
            return {'access_token': 'oauth-private', 'token_type': 'Bearer', 'scope': self.scope,
                    'expires_in': 3600, 'id_token': message.decode() + '.' + b64(signature)}
        if url.endswith('/userinfo'): return {'sub': self.claims['sub'], 'preferred_username': 'Alice'}
        raise AssertionError(url)


def setup_flow(accounts, purpose='link', session=None):
    if session is None:
        session, _ = sign_in(accounts, 'alice')
    cfg = json.loads(accounts.config_path.read_text())
    cfg['oauth'] = {'client_id': 'client', 'redirect_uri': 'https://review.example/oauth/callback'}
    accounts.config_path.write_text(json.dumps(cfg))
    provider = Provider(); oauth = OAuth(accounts, transport=provider)
    url, binding = oauth.begin(purpose, session=session)
    query = parse_qs(urlsplit(url).query)
    provider.claims = {'iss': 'https://huggingface.co', 'aud': 'client', 'sub': 'invited-alice',
                       'exp': int(time.time()) + 300, 'iat': int(time.time()), 'nonce': query['nonce'][0]}
    return oauth, provider, query, binding, session


def test_pkce_link_callback_replay_and_browser_binding(accounts):
    oauth, provider, query, binding, session = setup_flow(accounts)
    assert query['code_challenge_method'] == ['S256']
    assert query['prompt'] == ['select_account']
    callback = {'state': query['state'][0], 'code': 'x'}
    with pytest.raises(AccountError): oauth.complete(callback, 'wrong', session=session)
    # Wrong browser must not destroy the legitimate browser's pending flow.
    new_session, connection = oauth.complete(callback, binding, session=session)
    assert new_session is None and connection['subject'] == 'invited-alice'
    token_call = next(call for call in provider.calls if call[1].endswith('/token'))
    assert token_call[2]['code_verifier']
    with pytest.raises(AccountError): oauth.complete(callback, binding, session=session)


def test_provider_sign_in_is_not_a_purpose(accounts):
    session, _ = sign_in(accounts, 'alice')
    with pytest.raises(AccountError):
        setup_flow(accounts, 'login', session)


@pytest.mark.parametrize('field,value', [('nonce', 'wrong'), ('iss', 'https://evil.example'),
    ('aud', 'other'), ('exp', 0)])
def test_invalid_claims_never_connect(accounts, field, value):
    oauth, provider, query, binding, session = setup_flow(accounts)
    provider.claims[field] = value
    with pytest.raises(AccountError): oauth.complete({'state': query['state'][0], 'code': 'x'}, binding, session=session)
    assert accounts.connections(accounts.authenticate(session)) == []


def test_explicit_link_is_session_bound(accounts):
    oauth, provider, query, binding, session = setup_flow(accounts)
    provider.claims['sub'] = 'second-subject'
    assert 'read-repos' in query['scope'][0]
    accounts.logout(session)
    with pytest.raises(AccountError): oauth.complete({'state': query['state'][0], 'code': 'x'}, binding, session=session)


def test_oidc_signature_is_checked(accounts):
    oauth, provider, query, binding, session = setup_flow(accounts)
    def transport(method, url, **kwargs):
        result = provider(method, url, **kwargs)
        if url.endswith('/token'): provider.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        return result
    oauth.transport = transport
    with pytest.raises(AccountError): oauth.complete({'state': query['state'][0], 'code': 'x'}, binding, session=session)


def test_explicit_oauth_link_keeps_identity_and_expires_connection(accounts):
    oauth, provider, query, binding, session = setup_flow(accounts)
    alice = accounts.authenticate(session)
    provider.claims['sub'] = 'another-hf-account'
    new_session, connection = oauth.complete({'state': query['state'][0], 'code': 'x'}, binding, session=session)
    assert new_session is None
    assert connection['subject'] == 'another-hf-account'
    assert accounts.credential(alice, connection['connection_id'])['token'] == 'oauth-private'
    now = accounts.clock(); accounts.clock = lambda: now + 3601
    with pytest.raises(AccountError, match='expired'): accounts.credential(alice, connection['connection_id'])
    # Repository token expiry does not release the verified provider identity to someone else.
    assert accounts._subject_owner('another-hf-account') == 'alice'


def publisher(accounts):
    cfg = json.loads(accounts.config_path.read_text())
    membership = cfg['users'][0]['memberships']['one']
    if 'publish' not in membership:
        membership.append('publish')
    accounts.config_path.write_text(json.dumps(cfg))
    return sign_in(accounts, 'alice')


def test_manage_oauth_keeps_only_requested_repo_scopes(accounts):
    session, alice = publisher(accounts)
    oauth, provider, query, binding, _ = setup_flow(accounts, 'manage', session)
    assert query['scope'] == ['openid profile read-repos gated-repos write-repos manage-repos']
    assert query['prompt'] == ['select_account']
    provider.scope = 'openid profile read-repos write-repos manage-repos inference-api'
    provider.claims['sub'] = 'manage-subject'
    _session, connection = oauth.complete({'state': query['state'][0], 'code': 'x'}, binding, session=session)
    assert connection['scopes'] == ['manage-repos', 'read-repos', 'write-repos']
    assert 'token' not in connection
    assert accounts.credential(alice, connection['connection_id'])['token'] == 'oauth-private'


def test_account_link_requests_and_keeps_write_scopes(accounts):
    session, _alice = sign_in(accounts, 'alice')
    oauth, provider, query, binding, _ = setup_flow(accounts, 'link', session)
    assert query['scope'] == ['openid profile read-repos gated-repos write-repos manage-repos']
    provider.scope = 'openid profile read-repos gated-repos write-repos manage-repos'
    provider.claims['sub'] = 'read-link-subject'
    _session, connection = oauth.complete({'state': query['state'][0], 'code': 'x'}, binding, session=session)
    assert connection['scopes'] == ['gated-repos', 'manage-repos', 'read-repos', 'write-repos']


@pytest.mark.parametrize('purpose', ['link', 'manage'])
def test_repo_connection_needs_no_second_publish_approval_but_requires_provider_write(accounts, purpose):
    session, _alice = sign_in(accounts, 'alice')
    oauth, provider, query, binding, _ = setup_flow(accounts, purpose, session)
    provider.scope = 'openid profile read-repos'
    provider.claims['sub'] = 'write-only-subject'
    with pytest.raises(AccountError, match='management permission'):
        oauth.complete({'state': query['state'][0], 'code': 'x'}, binding, session=session)
    assert accounts.connections(_alice) == []


def test_expired_oauth_state_makes_no_provider_request(accounts):
    oauth, provider, query, binding, session = setup_flow(accounts)
    now = accounts.clock(); accounts.clock = lambda: now + 601
    with pytest.raises(AccountError): oauth.complete({'state': query['state'][0], 'code': 'x'}, binding, session=session)
    assert provider.calls == []
