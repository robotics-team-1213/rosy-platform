from types import SimpleNamespace
import pytest
from learning_rosy_accounts import RosyAccounts
from learning_accounts import AccountError
from test_learning_accounts import accounts, sign_in


def receiver_request(accounts):
    from functools import partial
    from learning_collaboration import Collaboration, COOKIE
    from test_learning_collaboration import request
    scope = SimpleNamespace(receiver=accounts.receiver, accounts=accounts, origin=accounts.config().get('public_origin'))
    return partial(request, cookie_name=Collaboration.cookie_name(scope, COOKIE))


@pytest.mark.parametrize('failure, expected', [('denied', 'account_callback_failed'),
                                              ('offline', 'account_unavailable'),
                                              ('malformed', 'account_callback_failed')])
def test_callback_failure_returns_to_account_recovery_without_credentials(failure, expected):
    from core_common.protocol.account_client import AccountDenied, AccountUnavailable
    from learning_collaboration import Collaboration
    def finish(*args):
        raise (AccountDenied if failure == 'denied' else AccountUnavailable)('private credential')
    collaboration = object.__new__(Collaboration)
    collaboration.receiver = SimpleNamespace(finish=finish)
    collaboration.unavailable = (AccountUnavailable,)
    collaboration.origin = 'https://learning.example.test'
    collaboration.accounts = SimpleNamespace(project_id='one')
    sent = []
    handler = SimpleNamespace(path='/api/account/callback?state=s&code=secret', headers={},
                              extra_headers=[], send=lambda body, status: sent.append((body, status)))
    if failure == 'malformed':
        handler.path = '/api/account/callback?state=s'
    assert collaboration.get(handler, '/api/account/callback', 'token')
    assert sent == [(b'', 303)]
    assert ('Location', '/accounts?error=' + expected) in handler.extra_headers
    assert any(name == 'Set-Cookie' and 'Max-Age=0' in value for name, value in handler.extra_headers)
    assert 'credential' not in repr(sent) + repr(handler.extra_headers)


def test_central_subject_preserves_owner_and_rechecks_grants(accounts):
    old_cookie, _ = sign_in(accounts, 'alice')
    record = SimpleNamespace(sub='central-alice', aud='project:one',
        permits=lambda resource, capability: capability in {'learning.view','learning.import'})
    receiver = SimpleNamespace(resource='project:one', resolve_session_id=lambda sid: record)
    config = accounts.config()
    config['account_subjects'] = {'central-alice':'alice'}
    managed = RosyAccounts(accounts.db_path, accounts.key_path, config, receiver=receiver)
    with pytest.raises(AccountError): accounts.authenticate(old_cookie)
    actor = managed.authenticate('browser-session')
    assert actor['user_id'] == 'alice'
    assert actor['capabilities'] == ['import', 'view']
    assert managed.require(actor, 'import')
    with pytest.raises(AccountError): managed.require(actor, 'manage')
    record.permits = lambda resource, capability: capability == 'learning.view'
    with pytest.raises(AccountError): managed.require(actor, 'import')
    record.sub = 'unmapped'
    with pytest.raises(AccountError): managed.require(actor, 'view')


def test_subject_cannot_be_remapped_to_another_existing_owner(accounts):
    config = accounts.config()
    config['account_subjects'] = {'central-alice':'alice'}
    record = SimpleNamespace(sub='central-alice', aud='project:one', permits=lambda *args:True)
    receiver = SimpleNamespace(resource='project:one', resolve_session_id=lambda sid:record)
    managed = RosyAccounts(accounts.db_path, accounts.key_path, config, receiver=receiver)
    actor = managed.authenticate('browser-session')
    managed._config['account_subjects']['central-alice'] = 'bob'
    with pytest.raises(AccountError): managed.require(actor,'view')


def test_shared_credential_rechecks_central_owner_without_legacy_permissions(accounts):
    from hashlib import sha256
    from test_learning_accounts import identity
    config = accounts.config()
    config['account_subjects'] = {'central-alice':'alice','central-bob':'bob'}
    for user in config['users']: user['memberships'] = {}
    records = {sha256(name.encode()).hexdigest(): SimpleNamespace(sub='central-'+name,
        aud='project:one', permits=lambda *args:True) for name in ['alice','bob']}
    receiver = SimpleNamespace(resource='project:one', resolve_session_id=records.get)
    managed = RosyAccounts(accounts.db_path, accounts.key_path, config, receiver=receiver)
    alice, bob = managed.authenticate('alice'), managed.authenticate('bob')
    conn = managed.connect_token(alice,'hf_x',transport=identity,sharing='project',resources=['dataset:org/data'])
    assert managed.credential(bob,conn['connection_id'],resource='dataset:org/data')['token'] == 'hf_x'
    owner = records[sha256(b'alice').hexdigest()]
    owner.permits = lambda resource, cap: cap != 'learning.manage'
    with pytest.raises(AccountError): managed.credential(bob,conn['connection_id'])
    owner.permits = lambda *args:True
    records.pop(sha256(b'alice').hexdigest())
    with pytest.raises(AccountError): managed.assert_connection(bob,conn['connection_id'],conn['generation'])


def test_http_mutation_from_previous_account_is_refused(accounts, tmp_path):
    import threading
    from hashlib import sha256
    from test_review_app import open_store
    from review_app import make_server
    config = accounts.config()
    config['account_subjects'] = {'central-alice':'alice','central-bob':'bob'}
    records = {sha256(name.encode()).hexdigest():SimpleNamespace(sub='central-'+name,
        aud='project:one',permits=lambda *args:True) for name in ['alice','bob']}
    receiver = SimpleNamespace(resource='project:one',resolve_session_id=records.get,retry_revocations=lambda:None,
        profile_url='https://account.test/console/profile',
        profile_session_id=lambda sid: {'account_id':records[sid].sub,'login':'member','display_name':'Member'})
    managed = RosyAccounts(accounts.db_path,accounts.key_path,config,receiver=receiver)
    request = receiver_request(managed)
    (tmp_path/'workspace').mkdir()
    store = open_store(tmp_path/'workspace')
    server = make_server(store,0,accounts=managed)
    worker = threading.Thread(target=server.serve_forever,daemon=True); worker.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        status, alice = request(base,'/api/accounts/session','alice')
        assert status == 200
        status, bob = request(base,'/api/accounts/session','bob')
        assert status == 200 and bob['token'] != alice['token']
        assert alice['profile']['account_id'] == alice['account_id'] == 'central-alice'
        assert bob['profile']['account_id'] == bob['account_id'] == 'central-bob'
        receiver.profile_session_id = lambda sid: alice['profile']
        assert request(base,'/api/accounts/session','bob')[1]['profile'] is None
        assert bob['account_session'] != alice['account_session']
        before = store.get(0)
        assert request(base,'/api/frames/0','bob',{'version':1,'action':'exclude'},alice['token'])[0] == 403
        assert store.get(0) == before
        assert request(base,'/api/frames/0','bob',{'version':1,'action':'exclude'},bob['token'])[0] == 200
    finally:
        server.shutdown(); server.server_close(); worker.join()


def test_account_grant_admits_without_learning_invitation(accounts, tmp_path):
    import threading
    from test_review_app import open_store
    from review_app import make_server
    record = SimpleNamespace(sub='central-carol', aud='project:one', permits=lambda resource, cap: cap == 'learning.view')
    receiver = SimpleNamespace(resource='project:one', resolve_session_id=lambda sid: record, retry_revocations=lambda: None,
        profile_url='https://account.test/console/profile', profile_session_id=lambda sid: None)
    config = accounts.config()
    config['users'] = []
    managed = RosyAccounts(accounts.db_path, accounts.key_path, config, receiver=receiver)
    request = receiver_request(managed)
    actor = managed.authenticate('browser-session')
    assert actor['user_id'] == 'central-carol' and actor['capabilities'] == ['view']
    # An Account subject never takes over an unmapped learning owner by matching its name.
    named = RosyAccounts(accounts.db_path, accounts.key_path, accounts.config(),
        receiver=SimpleNamespace(resource='project:one', resolve_session_id=lambda sid: SimpleNamespace(
            sub='alice', aud='project:one', permits=lambda *args: True)))
    with pytest.raises(AccountError, match='unmapped learning owner'): named.authenticate('browser-session')
    (tmp_path / 'workspace').mkdir()
    server = make_server(open_store(tmp_path / 'workspace'), 0, accounts=managed)
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        assert request(base, '/api/accounts/session', 'browser-session')[0] == 200
        record.permits = lambda *args: False
        status, body = request(base, '/api/accounts/session', 'browser-session')
        assert status == 403 and '권한' in body['error']  # signed in: no redirect back to login
        managed.receiver.resolve_session_id = lambda sid: None
        assert request(base, '/api/accounts/session', 'browser-session')[0] == 401
    finally:
        server.shutdown(); server.server_close(); worker.join()


def test_first_unmapped_sign_in_can_be_mapped_later_and_conflicts_are_403(accounts, tmp_path):
    import threading
    from test_review_app import open_store
    from review_app import make_server
    record = SimpleNamespace(sub='central-alice', aud='project:one', permits=lambda *args: True)
    receiver = SimpleNamespace(resource='project:one', resolve_session_id=lambda sid: record, retry_revocations=lambda: None,
        profile_url='https://account.test/console/profile', profile_session_id=lambda sid: None)
    managed = RosyAccounts(accounts.db_path, accounts.key_path, accounts.config(), receiver=receiver)
    request = receiver_request(managed)
    assert managed.authenticate('browser-session')['user_id'] == 'central-alice'
    # The legacy owner signed in once before the operator mapped them; the mapping still applies.
    managed._config['account_subjects'] = {'central-alice': 'alice'}
    assert managed.authenticate('browser-session')['user_id'] == 'alice'
    managed._config['account_subjects'] = {'central-alice': 'bob'}
    with pytest.raises(AccountError, match='reassigned'): managed.authenticate('browser-session')
    (tmp_path / 'workspace').mkdir()
    server = make_server(open_store(tmp_path / 'workspace'), 0, accounts=managed)
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        # A live Account session with a refused owner binding must not bounce back to login.
        assert request(base, '/api/accounts/session', 'browser-session')[0] == 403
    finally:
        server.shutdown(); server.server_close(); worker.join()
