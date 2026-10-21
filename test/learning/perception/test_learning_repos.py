"""Stored Hugging Face connections manage private dataset and model repositories."""
import json
import sqlite3
import threading
import urllib.error
import urllib.request

import pytest
from cryptography.fernet import Fernet

from learning_accounts import AccountError, Accounts, token_scopes
from learning_repos import create_private, delete_private, hub_transport, list_repos
from review_app import make_server
from test_learning_accounts import accounts, identity, sign_in
from test_review_app import open_store


def publisher(accounts):
    cfg = json.loads(accounts.config_path.read_text())
    membership = cfg['users'][0]['memberships']['one']
    if 'publish' not in membership:
        membership.append('publish')
    accounts.config_path.write_text(json.dumps(cfg))
    return sign_in(accounts, 'alice')


def identified(role, scopes=None, gated=False):
    def transport(token):
        access = {'role': role}
        if gated:
            access['canReadGatedRepos'] = True
        if scopes is not None:
            access['scopes'] = scopes
        return {'id': 'subject-' + token[-1], 'name': 'account-' + token[-1], 'type': 'user',
                'auth': {'accessToken': access}}
    return transport


class Hub:
    def __init__(self):
        self.calls = []
        self.private = True
        self.create_status = 200
        self.delete_status = 200
        self.missing = set()
        self.listed = None

    def __call__(self, method, url, token, body=None):
        assert isinstance(token, str) and token not in url
        self.calls.append((method, url, token, None if body is None else dict(body)))
        if url.endswith('/repos/create'):
            return self.create_status, {}
        if url.endswith('/repos/delete'):
            return self.delete_status, {}
        if '?' in url:
            return 200, [] if self.listed is None else self.listed
        repo_id = url.split('/api/', 1)[1].split('/', 1)[1]
        if repo_id in self.missing:
            return 404, None
        return 200, {'id': repo_id, 'private': self.private, 'sha': 'a' * 40}


def test_token_roles_record_only_known_repo_scopes():
    assert token_scopes({'id': 'a', 'name': 'a', 'type': 'user'}) == []
    assert token_scopes({'auth': {'accessToken': {'role': 'read'}}}) == ['read-repos']
    assert token_scopes({'auth': {'accessToken': {'role': 'read', 'canReadGatedRepos': True}}}) == [
        'read-repos', 'gated-repos']
    assert token_scopes({'auth': {'accessToken': {'role': 'write'}}}) == [
        'read-repos', 'gated-repos', 'write-repos', 'manage-repos']
    assert token_scopes({'auth': {'accessToken': {'role': 'fineGrained'}}}) == []
    assert token_scopes({'auth': {'accessToken': {'role': 'fineGrained', 'scopes': ['write-repos', 'jobs']}}}) == [
        'write-repos']


def test_read_connection_imports_but_cannot_create(accounts):
    _session, alice = publisher(accounts)
    conn = accounts.connect_token(alice, 'hf_read_x', transport=identified('read'))
    assert conn['scopes'] == ['read-repos']
    assert 'token' not in conn
    assert accounts.credential(alice, conn['connection_id'])['token'] == 'hf_read_x'
    hub = Hub()
    with pytest.raises(ValueError, match='필요한 저장소 권한'):
        create_private(accounts, alice, conn['connection_id'], 'dataset', 'account-x/data', transport=hub)
    assert hub.calls == []


def test_missing_scope_proof_keeps_import_and_refuses_management(accounts):
    _session, alice = publisher(accounts)
    conn = accounts.connect_token(alice, 'hf_plain_x', transport=identity)
    assert conn['scopes'] == []
    with accounts._db() as db:
        db.execute('UPDATE learning_connections SET scopes=NULL WHERE id=?', (conn['connection_id'],))
    assert accounts.credential(alice, conn['connection_id'])['token'] == 'hf_plain_x'
    with pytest.raises(AccountError, match='scope denied'):
        accounts.management_credential(alice, conn['connection_id'], scope='read-repos')


def test_personal_create_and_delete_use_that_connection_only(accounts):
    _session, alice = publisher(accounts)
    _session, bob = sign_in(accounts, 'bob')
    conn = accounts.connect_token(alice, 'hf_write_x', transport=identified('write'))
    hub = Hub()
    with pytest.raises(ValueError, match='그 계정의 저장소만'):
        create_private(accounts, alice, conn['connection_id'], 'dataset', 'other/data', transport=hub)
    assert hub.calls == []
    created = create_private(accounts, alice, conn['connection_id'], 'dataset', 'account-x/data', transport=hub)
    assert created == {'repo_id': 'account-x/data', 'private': True, 'sha': 'a' * 40}
    assert 'hf_write_x' not in json.dumps(created)
    assert hub.calls[0][:3] == ('POST', 'https://huggingface.co/api/repos/create', 'hf_write_x')
    assert hub.calls[0][3] == {'name': 'data', 'organization': 'account-x', 'visibility': 'private', 'type': 'dataset'}
    with accounts._db() as db:
        recorded = db.execute("SELECT object_id FROM learning_audit WHERE action='repo_create'").fetchone()['object_id']
    assert recorded == 'dataset:account-x/data'
    assert 'hf_write_x' not in recorded
    cfg = json.loads(accounts.config_path.read_text())
    cfg['users'][1]['memberships']['one'].append('publish')
    accounts.config_path.write_text(json.dumps(cfg))
    _session, bob = sign_in(accounts, 'bob')
    with pytest.raises(AccountError, match='connection access denied'):
        accounts.management_credential(bob, conn['connection_id'], scope='write-repos')
    hub.private = False
    with pytest.raises(ValueError, match='비공개로 확인'):
        create_private(accounts, alice, conn['connection_id'], 'model', 'account-x/weights', transport=hub)
    assert not any(call[0] == 'DELETE' for call in hub.calls)
    hub.private = True
    hub.create_status = 409
    before = len(hub.calls)
    with pytest.raises(ValueError, match='이미 있습니다'):
        create_private(accounts, alice, conn['connection_id'], 'dataset', 'account-x/data', transport=hub)
    assert [call[0] for call in hub.calls[before:]] == ['POST']
    with pytest.raises(ValueError, match='삭제 확인'):
        delete_private(accounts, alice, conn['connection_id'], 'dataset', 'account-x/data', 'nope', transport=hub)
    hub.private = False
    before = len(hub.calls)
    with pytest.raises(ValueError, match='공개 저장소'):
        delete_private(accounts, alice, conn['connection_id'], 'dataset', 'account-x/data', 'account-x/data', transport=hub)
    assert [call[0] for call in hub.calls[before:]] == ['GET']
    hub.private = True
    deleted = delete_private(accounts, alice, conn['connection_id'], 'dataset', 'account-x/data',
                             'account-x/data', transport=hub)
    assert deleted == {'ok': True, 'repo_type': 'dataset', 'repo_id': 'account-x/data'}
    assert hub.calls[-1][0] == 'DELETE'
    assert hub.calls[-1][2] == 'hf_write_x'
    assert hub.calls[-1][3] == {'name': 'data', 'organization': 'account-x', 'type': 'dataset'}


def test_project_management_stays_on_the_allowlist(accounts):
    _session, alice = publisher(accounts)
    conn = accounts.connect_token(alice, 'hf_write_x', transport=identified('write'), sharing='project',
                                  resources=['dataset:org/allowed', 'model:org/weights'])
    hub = Hub()
    hub.missing.add('org/allowed')
    listed = list_repos(accounts, alice, conn['connection_id'], 'dataset', transport=hub)
    assert listed == {'repos': [{'repo_id': 'org/allowed', 'missing': True, 'private': False, 'sha': ''}]}
    assert all('author=' not in call[1] for call in hub.calls)
    with pytest.raises(ValueError, match='허용된 저장소'):
        create_private(accounts, alice, conn['connection_id'], 'dataset', 'org/other', transport=hub)
    hub.missing.clear()
    created = create_private(accounts, alice, conn['connection_id'], 'dataset', 'org/allowed', transport=hub)
    assert created['repo_id'] == 'org/allowed'
    hub.listed = [{'id': 'account-y/data', 'private': True, 'sha': 'b' * 40},
                  {'id': 'org/secret', 'private': True, 'sha': 'c' * 40}, {'private': True}]
    personal = accounts.connect_token(alice, 'hf_read_y', transport=identified('read'))
    listed = list_repos(accounts, alice, personal['connection_id'], 'dataset', transport=hub)
    assert listed['repos'] == [{'repo_id': 'account-y/data', 'private': True, 'sha': 'b' * 40}]
    assert 'hf_read_y' not in json.dumps(listed)


def test_publish_is_required_and_http_confirm_is_exact(accounts, tmp_path):
    session, alice = sign_in(accounts, 'alice')
    conn = accounts.connect_token(alice, 'hf_write_x', transport=identified('write'))
    hub = Hub()
    folder = tmp_path / 'review'
    folder.mkdir()
    server = make_server(open_store(folder), 0, accounts=accounts, repos=hub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}'

    def request(path, body=None, cookie=session, token=None):
        headers = {'Origin': url, 'Cookie': 'rosy_learning_session=' + cookie}
        if token:
            headers['X-Pinky-Token'] = token
        raw = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(url + path, data=raw, headers=headers)
        try:
            with urllib.request.urlopen(req) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    try:
        _status, state = request('/api/accounts/session')
        body = {'connection_id': conn['connection_id'], 'repo_type': 'dataset', 'repo_id': 'account-x/data'}
        assert request('/api/accounts/repos/create', body, token=state['token'])[0] == 403
        assert hub.calls == []
        assert 'hf_write_x' not in json.dumps(state)
        session, alice = publisher(accounts)
        _status, state = request('/api/accounts/session', cookie=session)
        code, created = request('/api/accounts/repos/create', body, cookie=session, token=state['token'])
        assert code == 200 and created['private'] is True and 'token' not in created
        code, refused = request('/api/accounts/repos/delete', dict(body, confirm='account-x/nope'),
                                cookie=session, token=state['token'])
        assert code == 400 and '삭제 확인' in refused['error']
        hub.listed = [{'id': 'account-x/data', 'private': True, 'sha': 'a' * 40}]
        code, listed = request('/api/accounts/repos?connection_id=' + conn['connection_id'] + '&repo_type=dataset',
                               cookie=session)
        assert code == 200 and listed['repos'][0]['repo_id'] == 'account-x/data'
        assert request('/api/accounts/repos?connection_id=' + conn['connection_id'] + '&repo_type=dataset&extra=1',
                       cookie=session)[0] == 400
        code, deleted = request('/api/accounts/repos/delete', dict(body, confirm='account-x/data'),
                                cookie=session, token=state['token'])
        assert code == 200 and deleted['ok'] is True
        with pytest.raises(ValueError, match='데이터셋 또는 모델'):
            create_private(accounts, alice, conn['connection_id'], 'space', 'account-x/demo', transport=hub)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def test_old_connection_table_gains_scopes(tmp_path):
    key = tmp_path / 'key'
    key.write_bytes(Fernet.generate_key())
    key.chmod(0o600)
    db_path = tmp_path / 'accounts.db'
    with sqlite3.connect(db_path) as db:
        db.execute('''CREATE TABLE learning_connections (
            id TEXT PRIMARY KEY, project_id TEXT, owner TEXT, subject TEXT, username TEXT,
            sharing TEXT, resources TEXT, secret TEXT, generation INTEGER, active INTEGER, expires REAL)''')
    config = {'project_id': 'one', 'users': [
        {'user_id': 'alice', 'username': 'alice',
         'memberships': {'one': ['view', 'import', 'publish']}}]}
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(config))
    opened = Accounts(db_path, key, path)
    with opened._db() as db:
        columns = {row[1] for row in db.execute('PRAGMA table_info(learning_connections)')}
    assert 'scopes' in columns
    _session, alice = sign_in(opened, 'alice')
    conn = opened.connect_token(alice, 'hf_write_x', transport=identified('write'))
    assert 'manage-repos' in conn['scopes']


def test_default_transport_refuses_unlisted_urls():
    with pytest.raises(ValueError, match='실패'):
        hub_transport('GET', 'https://evil.example/api/models?author=a&limit=50', 'secret')
    with pytest.raises(ValueError, match='실패'):
        hub_transport('GET', 'https://huggingface.co/api/datasets?author=a&limit=50&token=secret', 'secret')
    with pytest.raises(ValueError, match='실패'):
        hub_transport('POST', 'https://huggingface.co/api/spaces', 'secret', {})
