"""D-955 step 2: the registry decides at request time, survives restart, and only managers change it."""
from base64 import urlsafe_b64encode
from copy import deepcopy
from hashlib import sha256
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from rosy_account.account_authority import AccountAuthority
from rosy_account.client_registry import ClientRegistry, SCHEMA, import_first, list_clients, validate_client

ISSUER = 'https://account.example.test'
CALLBACK = 'https://app.example.test/callback'
VERIFIER = 'v' * 64
CHALLENGE = urlsafe_b64encode(sha256(VERIFIER.encode()).digest()).rstrip(b'=').decode()
PEM = Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                 serialization.NoEncryption())
CONTEXT = {'account_id': 'account-1', 'login': 'alice', 'principal_id': 'alice', 'role': 'viewer',
           'grants': [{'resource': 'robot:r1', 'capabilities': ['robot.read']},
                      {'resource': 'robot:r2', 'capabilities': ['robot.read']}],
           'revision': 1, 'session_family': 'family-1'}


def make_authority(path, clients):
    return AccountAuthority(path, issuer=ISSUER, private_key=PEM, key_id='key-1', clients=clients,
                            resolve_family=lambda db, family: deepcopy(CONTEXT), revoke_family=lambda db, family: None,
                            clock=lambda: 1000)


class Ledger:
    """The two ledger calls the registry makes, on the authority's own database."""
    def __init__(self, authority):
        self.authority = authority

    def db(self, *, write=False):
        return self.authority.transaction()

    def require_manager(self, _db, value):
        if value != 'manager':
            raise PermissionError('accounts.manage cookie session required')
        return 'account-1'


@pytest.fixture
def registry(tmp_path):
    authority = make_authority(tmp_path / 'accounts.sqlite3', {'app': {'redirect_uris': [CALLBACK], 'resources': ['robot:r1']}})
    return authority, ClientRegistry(Ledger(authority), lambda: 1000)


def code_for(authority, client='app', resource='robot:r1', redirect=CALLBACK):
    query = urlencode({'response_type': 'code', 'client_id': client, 'redirect_uri': redirect, 'scope': resource,
                       'state': 's', 'code_challenge': CHALLENGE, 'code_challenge_method': 'S256'})
    headers, _body, status = authority.authorize(query, {'account_id': 'account-1', 'session_family': 'family-1'})
    return parse_qs(urlsplit(headers['Location']).query)['code'][0] if status == 302 else None


def exchange(authority, code, client='app', redirect=CALLBACK):
    _headers, body, status = authority.token(urlencode({
        'grant_type': 'authorization_code', 'client_id': client, 'code': code, 'redirect_uri': redirect,
        'code_verifier': VERIFIER}))
    return status, body


def test_new_client_works_without_restart(registry):
    authority, clients = registry
    assert code_for(authority, client='new-app') is None
    row = clients.create('manager', client_id='new-app', redirect_uris=[CALLBACK], resources=['robot:r2'])
    assert row == {'client_id': 'new-app', 'redirect_uris': [CALLBACK], 'resources': ['robot:r2'], 'enabled': True, 'revision': 1}
    code = code_for(authority, client='new-app', resource='robot:r2')
    assert code and exchange(authority, code, client='new-app')[0] == 200


def test_stopping_a_client_ends_login_refresh_and_session_checks(registry):
    import json
    authority, clients = registry
    status, body = exchange(authority, code_for(authority))
    tokens = json.loads(body)
    assert status == 200 and authority.introspect(tokens['access_token'])['active'] is True
    stopped = clients.update('manager', 'app', revision=1, enabled=False)
    assert stopped['enabled'] is False and stopped['revision'] == 2
    assert code_for(authority) is None
    assert authority.introspect(tokens['access_token']) == {'active': False}
    assert authority.token(urlencode({'grant_type': 'refresh_token', 'client_id': 'app',
                                      'refresh_token': tokens['refresh_token']}))[2] != 200
    clients.update('manager', 'app', revision=2, enabled=True)
    assert authority.introspect(tokens['access_token'])['active'] is True


def test_narrowing_resources_applies_at_once(registry):
    authority, clients = registry
    clients.update('manager', 'app', revision=1, resources=['robot:r2'])
    assert code_for(authority, resource='robot:r1') is None
    assert code_for(authority, resource='robot:r2')


def test_json_only_seeds_an_empty_registry(tmp_path, registry):
    path = tmp_path / 'accounts.sqlite3'
    authority, clients = registry
    clients.update('manager', 'app', revision=1, enabled=False)
    restarted = make_authority(path, {'app': {'redirect_uris': [CALLBACK], 'resources': ['robot:r1']},
                                      'from-json': {'redirect_uris': [CALLBACK], 'resources': ['robot:r1']}})
    assert restarted.clients == {}, 'a stopped app stays stopped and later JSON rows are ignored'
    with restarted.transaction() as db:
        assert [row['client_id'] for row in list_clients(db)] == ['app']


def test_only_managers_change_the_registry_and_changes_are_audited(registry):
    authority, clients = registry
    with pytest.raises(PermissionError):
        clients.create('viewer', client_id='x', redirect_uris=[CALLBACK], resources=['robot:r1'])
    with pytest.raises(PermissionError):
        clients.update('viewer', 'app', revision=1, enabled=False)
    with pytest.raises(ValueError, match='revision conflict'):
        clients.update('manager', 'app', revision=9, enabled=False)
    with pytest.raises(KeyError):
        clients.update('manager', 'missing', revision=1, enabled=False)
    with pytest.raises(ValueError, match='already registered'):
        clients.create('manager', client_id='app', redirect_uris=[CALLBACK], resources=['robot:r1'])
    clients.update('manager', 'app', revision=1, enabled=False)
    with authority.transaction() as db:
        rows = db.execute('SELECT * FROM account_client_audit').fetchall()
    assert [(r['actor_account_id'], r['client_id'], r['previous_revision'], r['following_revision']) for r in rows] == [
        ('account-1', 'app', 1, 2)]


@pytest.mark.parametrize('uris,resources', [
    ([], ['robot:r1']), ([CALLBACK], []), ('https://a.example.test/', ['robot:r1']),
    (['http://a.example.test/cb'], ['robot:r1']), (['https://a.example.test/cb?x=1'], ['robot:r1']),
    (['https://user:pw@a.example.test/cb'], ['robot:r1']), (['https://a.example.test/cb#f'], ['robot:r1']),
    ([CALLBACK, CALLBACK], ['robot:r1']), ([CALLBACK], ['robot:*']), ([CALLBACK], ['project:*']),
    ([CALLBACK], ['other:r1']), ([CALLBACK], [1]),
])
def test_invalid_registrations_are_refused(uris, resources):
    with pytest.raises(ValueError):
        validate_client('app', uris, resources)


@pytest.mark.parametrize('client_id', ['', 'has space', 'a' * 97, 1, 'a/b'])
def test_invalid_client_ids_are_refused(client_id):
    with pytest.raises(ValueError):
        validate_client(client_id, [CALLBACK], ['robot:r1'])


def test_schema_constant_is_idempotent(tmp_path):
    import sqlite3
    db = sqlite3.connect(tmp_path / 'x.sqlite3')
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    db.executescript(SCHEMA)
    import_first(db, {'a': {'redirect_uris': [CALLBACK], 'resources': ['robot:r1']}})
    import_first(db, {'b': {'redirect_uris': [CALLBACK], 'resources': ['robot:r1']}})
    assert [row['client_id'] for row in list_clients(db)] == ['a']
    db.close()
