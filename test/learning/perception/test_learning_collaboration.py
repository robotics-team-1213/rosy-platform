"""The existing review routes enforce project identity when collaboration is enabled."""
import json
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from types import SimpleNamespace
from http.cookies import SimpleCookie

import pytest
from test_review_app import open_store
from review_app import make_server
from test_learning_accounts import accounts, sign_in


def test_central_project_cookies_coexist_on_shared_https_host(tmp_path):
    from learning_collaboration import Collaboration, COOKIE, BINDING
    jar = SimpleCookie()
    apps = []
    try:
        for project, port in [('alpha', 9444), ('beta', 9445), ('alpha', 9446)]:
            folder = tmp_path / str(port); folder.mkdir()
            account = Accounts()
            account.project_id = project
            account.public_origin = f'https://learning.example:{port}'
            account.receiver = SimpleNamespace(retry_revocations=lambda: None)
            app = Collaboration(account, open_store(folder))
            apps.append(app)
            handler = SimpleNamespace(extra_headers=[])
            for name in (COOKIE, BINDING, 'rosy_account_flow'):
                app.set_cookie(handler, name, f'{port}-value')
            for _, value in handler.extra_headers:
                parsed = SimpleCookie(value)
                morsel = next(iter(parsed.values()))
                assert morsel['secure'] and morsel['httponly'] and morsel['samesite'] == 'Lax'
                assert morsel['path'] == '/' and not morsel['domain']
                jar.load(value)
        assert len(jar) == 9
        for app, port in zip(apps, (9444, 9445, 9446)):
            assert app.cookie(SimpleNamespace(headers={'Cookie': COOKIE + '=legacy'}), COOKIE) == ''
            seen = []
            app.accounts.authenticate = lambda value: seen.append(value) or {'capabilities': ['view']}
            handler = SimpleNamespace(headers={'Cookie': jar.output(header='', sep=';')})
            app.identity(handler)
            assert seen == [f'{port}-value']
            handler.extra_headers = []
            app.set_cookie(handler, COOKIE, '', clear=True)
            assert 'Max-Age=0' in handler.extra_headers[0][1]
            jar.load(handler.extra_headers[0][1])
    finally:
        for app in apps:
            app.shutdown()


@pytest.mark.parametrize('cookie_scope,expected', [('own', 403), ('legacy', 401), ('other', 401)])
def test_central_session_without_project_grant_uses_scoped_cookie(tmp_path, cookie_scope, expected):
    from learning_collaboration import Collaboration, COOKIE

    class NoGrant(Accounts):
        def authenticate(self, session):
            principal = super().authenticate(session)
            principal['capabilities'] = []
            return principal

    account = NoGrant()
    account.public_origin = 'https://learning.example:9444'
    account.receiver = SimpleNamespace(retry_revocations=lambda: None)
    app = Collaboration(account, open_store(tmp_path))
    try:
        name = COOKIE + (app.cookie_suffix if cookie_scope == 'own' else '_other' if cookie_scope == 'other' else '')
        responses = []
        handler = SimpleNamespace(headers={'Cookie': name + '=reader'}, extra_headers=[],
                                  path='/api/accounts/session',
                                  send=lambda body, status=200: responses.append((body, status)))
        assert app.get(handler, '/api/accounts/session', 'csrf-token')
        assert responses[0][1] == expected
        assert not handler.extra_headers  # No login redirect or session replacement.
    finally:
        app.shutdown()


class Accounts:
    project_id = 'alpha'
    public_origin = None

    def __init__(self):
        self.active = True

    def authenticate(self, session):
        if session not in ('reader', 'editor', 'reviewer') or not self.active:
            raise PermissionError('login required')
        caps = ['view'] + ([] if session == 'reader' else ['edit'])
        if session == 'reviewer':
            caps += ['approve', 'manage', 'import']
        return dict(user_id=session, project_id='alpha', capabilities=caps)

    def require(self, principal, capability):
        if not self.active or capability not in principal['capabilities']:
            raise PermissionError('project permission required')

    def connections(self, principal):
        self.require(principal, 'view')
        return []


@contextmanager
def running(tmp_path):
    accounts = Accounts()
    store = open_store(tmp_path)
    server = make_server(store, 0, accounts=accounts)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', accounts, store
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_session_without_view_is_forbidden_not_signed_out(tmp_path):
    with running(tmp_path) as (base, accounts, _):
        def deny(principal, capability):
            raise PermissionError('denied')
        accounts.require = deny
        assert request(base, '/api/accounts/session', 'reader')[0] == 403
        assert request(base, '/api/accounts/session')[0] == 401


def request(base, path, session=None, body=None, token=None, *, cookie_name='rosy_learning_session'):
    headers = {'Origin': base}
    if session:
        headers['Cookie'] = cookie_name + '=' + session
    if token:
        headers['X-Pinky-Token'] = token
    raw = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=raw, headers=headers)
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def test_cancel_retry_waits_for_previous_worker_then_runs_via_http(tmp_path, accounts):
    import time
    from learning_imports import LearningImports
    from test_learning_imports import Transport, RIGHTS
    session, actor = sign_in(accounts, 'alice')
    connection = accounts.connect_token(actor, 'hf_test', transport=lambda _: {'id': 'id', 'name': 'test', 'type': 'user'})
    transport = Transport()
    entered, release = threading.Event(), threading.Event()
    original = transport.chunks
    first = True
    def pause_once(*args, **kwargs):
        nonlocal first
        if first:
            first = False; entered.set()
            assert release.wait(10)
        yield from original(*args, **kwargs)
    transport.chunks = pause_once
    def credential(actor, project, connection_id, generation=None, resource=None):
        return accounts.credential(actor, connection_id, generation, resource=resource)
    # The fixture's metadata resolver checks this synthetic token only.
    resolve = transport.resolve
    transport.resolve = lambda *args: resolve(*args[:-1], 'selected-secret')
    imports = LearningImports(tmp_path / 'imports', accounts.authorize, credential, transport=transport)
    folder = tmp_path / 'review'; folder.mkdir()
    server = make_server(open_store(folder), 0, accounts=accounts, imports=imports)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    try:
        _, state = request(url, '/api/accounts/session', session)
        code, job = request(url, '/api/learning/imports/create', session,
            dict(connection_id=connection['connection_id'], repo_type='dataset', repo_id='org/data',
                 revision='main', files=['clip.mp4'], rights=RIGHTS), state['token'])
        assert code == 200 and entered.wait(10)
        for action in ('cancel', 'retry'):
            assert request(url, '/api/learning/imports/' + action, session, {'id': job['id']}, state['token'])[0] == 200
        release.set()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            _, result = request(url, '/api/learning/imports', session)
            if result['jobs'][0]['status'] == 'completed': break
            time.sleep(0.05)
        assert result['jobs'][0]['status'] == 'completed'
    finally:
        release.set(); server.shutdown(); server.server_close(); thread.join(5)


@pytest.mark.parametrize('path', ['/api/workspace', '/api/learning', '/api/catalog',
                                  '/api/images/0', '/api/history/0', '/api/decisions'])
def test_all_existing_data_routes_require_identity(tmp_path, path):
    with running(tmp_path) as (url, _, store):
        assert request(url, path)[0] == 401
        assert request(url, '/api/workspace', 'reader')[0] == 200
        assert store.get(0)['version'] == 1


def test_viewer_cannot_write_and_revocation_blocks_open_session(tmp_path):
    with running(tmp_path) as (url, accounts, store):
        _, workspace = request(url, '/api/workspace', 'reader')
        before = store.get(0)
        assert request(url, '/api/frames/0', 'reader',
                       {'version': 1, 'action': 'exclude'}, workspace['token'])[0] == 403
        assert store.get(0) == before
        accounts.active = False
        assert request(url, '/api/workspace', 'reader')[0] == 401


def test_editor_cannot_approve_and_reviewer_identity_is_server_owned(tmp_path):
    with running(tmp_path) as (url, _, store):
        _, workspace = request(url, '/api/workspace', 'editor')
        body = {'version': 1, 'action': 'approve', 'reviewer': 'spoofed', 'complete_frame_review': True}
        assert request(url, '/api/frames/0', 'editor', body, workspace['token'])[0] == 403
        status, result = request(url, '/api/frames/0', 'reviewer', body, workspace['token'])
        assert status == 200
        assert result['review']['reviewer'] == 'reviewer'
        assert store.history(0)['events']['object'][0]['actor'] == 'reviewer'
        assert request(url, '/api/frames/0', 'reviewer', body, workspace['token'])[0] == 409


def test_collaboration_rejects_missing_origin(tmp_path):
    with running(tmp_path) as (url, _, store):
        _, workspace = request(url, '/api/workspace', 'reviewer')
        req = urllib.request.Request(url + '/api/frames/0',
            data=json.dumps({'version': 1, 'action': 'exclude'}).encode(),
            headers={'Cookie': 'rosy_learning_session=reviewer', 'X-Pinky-Token': workspace['token']})
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(req)
        assert error.value.code == 403
        assert store.get(0)['version'] == 1


def test_project_manager_cannot_register_other_project_server_paths(tmp_path):
    with running(tmp_path) as (url, _, store):
        _, workspace = request(url, '/api/workspace', 'reviewer')
        for path in ('/api/import', '/api/cad', '/api/learning/register'):
            assert request(url, path, 'reviewer', {'path': str(tmp_path / 'another-project')},
                           workspace['token'])[0] == 403


def test_collaboration_binding_cannot_be_reopened_without_auth(tmp_path):
    with running(tmp_path) as (_, _, store):
        pass
    with pytest.raises(ValueError, match='account configuration'):
        make_server(store, 0)


def test_pixel_actor_and_approval_are_preserved(tmp_path):
    import review_masks
    from review_app import Conflict
    store = open_store(tmp_path)
    import review_ingest
    from test_review_cycle import catalog
    folder, classes, _ = catalog(tmp_path)
    review_ingest.import_frames(store, {'path': str(folder), 'classes': str(classes)})
    review = review_masks.get(store, 0)
    # Fixtures have a full existing class binding; use the established fill path.
    value = review_masks.update(store, 0, {'version': review['version'], 'action': 'fill',
        'label': review['classes']['classes'][0]['index']}, Conflict, actor='alice')
    approved = review_masks.update(store, 0, {'version': value['version'], 'action': 'approve',
        'complete_frame_review': True, 'background_reviewed': True}, Conflict, actor='bob')
    assert approved['status'] == 'approved'
    import review_evidence
    review_evidence.decisions(store)
    store.prepare()
    with store.connect() as db:
        events = [json.loads(row[0]) for row in db.execute('SELECT review FROM pixel_events ORDER BY id')]
    assert events[0]['actor'] == 'alice'
    assert events[-1]['actor'] == 'bob'


def test_configured_https_origin_secure_cookie_and_live_logout(tmp_path, accounts):
    config = json.loads(accounts.config_path.read_text())
    config['public_origin'] = 'https://learning.example'
    accounts.config_path.write_text(json.dumps(config))
    folder = tmp_path / 'review'; folder.mkdir()
    server = make_server(open_store(folder), 0, accounts=accounts)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    session, _ = sign_in(accounts, 'alice')
    headers = {'Host': 'learning.example', 'Origin': 'https://learning.example',
               'Cookie': 'rosy_learning_session=' + session}
    try:
        with urllib.request.urlopen(urllib.request.Request(base + '/api/accounts/session', headers=headers)) as response:
            principal = json.load(response)
            assert principal['project_id'] == 'one'
            assert not any(key.startswith('_') for key in principal)
        headers['X-Pinky-Token'] = principal['token']
        with urllib.request.urlopen(urllib.request.Request(base + '/api/accounts/logout', data=b'{}', headers=headers)) as response:
            cleared = response.headers['Set-Cookie']
            assert '; Secure' in cleared and '; HttpOnly' in cleared and 'Max-Age=0' in cleared
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(urllib.request.Request(base + '/api/workspace', headers=headers))
        assert error.value.code == 401
    finally:
        server.shutdown(); server.server_close(); thread.join()


@pytest.mark.parametrize('path,body', [
    ('/api/accounts/login', {'username': 'alice', 'password': 'alice-password'}),
    ('/api/accounts/oauth', {'purpose': 'login'}),
])
def test_app_local_and_provider_sign_in_are_not_served(tmp_path, accounts, path, body):
    """D-757: people sign in through Rosy Account only."""
    folder = tmp_path / 'review'; folder.mkdir()
    server = make_server(open_store(folder), 0, accounts=accounts)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        status, _ = request(base, path, body=body)
        assert status == 403
        with accounts._db() as db:
            assert db.execute('SELECT COUNT(*) FROM learning_sessions').fetchone()[0] == 0
    finally:
        server.shutdown(); server.server_close(); thread.join()


def test_collaboration_config_without_rosy_account_is_refused(tmp_path, accounts):
    from learning_collaboration import load
    config = json.loads(accounts.config_path.read_text())
    config.update(accounts_db=str(accounts.db_path), key_file=str(accounts.key_path), imports_root=str(tmp_path / 'imports'))
    path = tmp_path / 'collaboration.json'; path.write_text(json.dumps(config))
    folder = tmp_path / 'review'; folder.mkdir()
    with pytest.raises(ValueError, match='Rosy Account'):
        load(path, open_store(folder))


@pytest.mark.parametrize('origin,callback', [
    (None, 'https://learning.example/oauth/huggingface/callback'),
    ('https://learning.example', 'https://other.example/oauth/huggingface/callback'),
    ('https://learning.example', 'https://learning.example/wrong-path'),
    ('https://learning.example', 'http://learning.example/oauth/huggingface/callback'),
])
def test_oauth_setup_rejected_before_workspace_binding(tmp_path, accounts, origin, callback):
    from learning_collaboration import Collaboration
    from learning_oauth import OAuth
    cfg = json.loads(accounts.config_path.read_text())
    cfg.update(public_origin=origin, oauth={'client_id': 'client', 'redirect_uri': callback})
    accounts.config_path.write_text(json.dumps(cfg))
    folder = tmp_path / 'review'; folder.mkdir()
    store = open_store(folder)
    with pytest.raises((ValueError, PermissionError)):
        Collaboration(accounts, store, oauth=OAuth(accounts))
    with store.connect() as db:
        assert db.execute("SELECT value FROM metadata WHERE key='collaboration_project'").fetchone() is None
