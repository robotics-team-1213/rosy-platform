"""Actual Chromium/HTTP/SQLite account collaboration with only HF replaced."""
import hashlib
import json
import threading

import pytest

from browser_harness import browser_tests_enabled, free_port, open_page
from learning_imports import LearningImports
from review_app import make_server
from test_learning_accounts import accounts, sign_in as account_session  # noqa: F401 — shared real encrypted account fixture
from test_learning_collaboration import request
from test_learning_imports import SHA, Transport
from test_review_app import open_store


pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium browser run')


@pytest.mark.parametrize('width', [1440, 390])
def test_login_entry_and_unconfigured_panel_recover_when_accounts_connect(tmp_path, width):
    playwright = pytest.importorskip('playwright.sync_api')
    folder = tmp_path/'review'; folder.mkdir()
    server = make_server(open_store(folder), free_port())
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    try:
        with playwright.sync_playwright() as runtime:
            browser, page, errors = open_page(runtime, width, 900, url=url)
            try:
                expect = playwright.expect
                page.goto(url+'/learning', wait_until='networkidle')
                page.get_by_role('link', name='로그인·계정', exact=True).click()
                expect(page.locator('#login-panel')).to_be_visible()
                assert page.locator('#login-panel input').count() == 0
                expect(page.locator('#login-help')).to_contain_text('계정 서버 연결 준비 중')
                expect(page.locator('#account-login')).to_be_hidden()
                posts = []
                page.on('request', lambda request: posts.append(request.url) if request.method=='POST' else None)
                assert not posts
                page.route('**/api/accounts/session', lambda route: route.fulfill(status=401, json={'error': 'sign in required'}))
                page.route('**/api/accounts/options', lambda route: route.fulfill(json={'enabled': True, 'oauth': False, 'rosy_account': True}))
                page.locator('#account-retry').click()
                expect(page.locator('#account-login')).to_be_visible()
                expect(page.locator('#account-login')).to_have_attribute('href', '/api/account/login?return=/accounts')
                assert page.url == url+'/accounts'
                expect(page.locator('#account-setup')).to_be_hidden()
                page.route('**/api/accounts/options', lambda route: route.fulfill(status=503, json={'error': 'connection unavailable'}))
                page.locator('#account-retry').click()
                expect(page.locator('#login-help')).to_contain_text('연결을 확인할 수 없습니다')
                expect(page.locator('#account-login')).to_be_hidden()
                assert not posts
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert not errors
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_central_profile_refresh_failure_and_logout_browser(tmp_path, accounts):
    """Real HTTPS receiver, signed grants and SQLite; only authority transport is replaced."""
    import base64
    import ssl
    import subprocess
    import time
    from urllib.parse import parse_qs, urlencode, urlsplit
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from core_common.protocol.account_access import sign_access
    from core_common.protocol.account_client import AccountClient, AccountUnavailable
    from learning_rosy_accounts import RosyAccounts
    playwright = pytest.importorskip('playwright.sync_api')
    port = free_port()
    origin = f'https://127.0.0.1:{port}'
    issuer = origin.replace('127.0.0.1', 'localhost')
    callback = origin + '/api/account/callback'
    private = Ed25519PrivateKey.generate()
    pem = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    public = private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    state = {'name': 'Alice', 'offline': False, 'active': True, 'challenge': ''}

    def authority(endpoint, fields):
        if endpoint == 'introspect':
            return {'active': state['active']}
        if endpoint == 'revoke':
            state['active'] = False
            return {}
        if endpoint == 'userinfo':
            if state['offline']:
                raise AccountUnavailable()
            return {'account_id': 'central-alice', 'login': 'alice', 'display_name': state['name']}
        assert endpoint == 'token' and fields['code'] == 'browser-code'
        assert base64.urlsafe_b64encode(hashlib.sha256(fields['code_verifier'].encode()).digest()).rstrip(b'=').decode() == state['challenge']
        now = int(time.time())
        return {'token_type': 'Bearer', 'refresh_token': 'fixture-refresh-credential',
                'access_token': sign_access({'iss': issuer, 'aud': 'project:one', 'sub': 'central-alice',
                    'sid': 'family', 'jti': 'learning-browser-123', 'rev': 1, 'iat': now, 'exp': now + 300,
                    'grants': [{'resource': 'project:one', 'capabilities': ['learning.view']}]}, pem, key_id='key')}

    receiver = AccountClient(tmp_path/'central.sqlite', issuer=issuer, client_id='learning', resource='project:one',
        callback=callback, public_keys={'key': public}, encryption_key=Fernet.generate_key(),
        post=authority, destinations=('/accounts', '/'))
    config = accounts.config()
    config['account_subjects'] = {'central-alice': 'alice'}
    config['public_origin'] = origin
    managed = RosyAccounts(accounts.db_path, accounts.key_path, config, receiver=receiver)
    folder = tmp_path/'central-review'; folder.mkdir()
    server = make_server(open_store(folder), port, accounts=managed)
    class AuthorityHandler(server.RequestHandlerClass):
        def do_GET(self):
            request = urlsplit(self.path)
            if request.path != '/api/fleet/auth/authorize':
                return super().do_GET()
            if not state['active']:
                self.send_response(200); self.end_headers(); self.wfile.write(b'Signed out')
                return
            query = parse_qs(request.query)
            state['challenge'] = query['code_challenge'][0]
            self.send_response(302)
            self.send_header('Location', callback + '?' + urlencode({'state': query['state'][0], 'code': 'browser-code'}))
            self.end_headers()
    server.RequestHandlerClass = AuthorityHandler
    cert, key = tmp_path/'cert.pem', tmp_path/'key.pem'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(key),
                    '-out', str(cert), '-days', '1', '-subj', '/CN=localhost'], check=True, capture_output=True)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); tls.load_cert_chain(cert, key)
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        with playwright.sync_playwright() as runtime:
            browser = runtime.chromium.launch(headless=True)
            page = browser.new_page(ignore_https_errors=True)
            navigation_errors = []
            page.on('requestfailed', lambda request: navigation_errors.append((request.url, request.failure)))
            try:
                expect = playwright.expect
                page.route('**/api/accounts/options', lambda route: route.fulfill(status=503,
                    content_type='application/json', body='{"error":"Account unavailable"}'))
                page.goto(origin + '/accounts')
                expect(page.locator('#account-retry')).to_be_visible()
                with page.expect_response('**/api/accounts/options'):
                    page.locator('#account-retry').click()
                expect(page.locator('#account-status')).to_contain_text('로그인 상태를 확인할 수 없습니다')
                expect(page.locator('#account-retry')).to_be_visible()
                page.unroute('**/api/accounts/options')
                page.goto(origin + '/api/account/callback?state=expired&code=expired')
                expect = playwright.expect
                expect(page.locator('#account-status')).to_contain_text('로그인 연결을 완료하지 못했습니다')
                expect(page.locator('#login-panel')).to_be_visible()
                page.locator('#account-login').click()
                link = page.locator('[data-account-profile]')
                expect = playwright.expect
                try:
                    expect(link).to_contain_text('Alice', timeout=15000)
                except AssertionError:
                    pytest.fail(f'Profile login failed at {page.url}: {navigation_errors}; {page.locator("body").inner_text()[:1000]}')
                expect(link).to_have_attribute('href', issuer + '/console/profile')
                assert page.request.get(origin + '/api/accounts/session').json()['account_id'] == 'central-alice'
                expect(page.locator('#import-panel')).to_be_hidden()
                state['name'] = 'Updated Alice'
                expect(link).to_contain_text('Updated Alice', timeout=15000)
                state['offline'] = True
                expect(link).not_to_contain_text('Alice', timeout=15000)
                expect(link).to_be_visible()
                state['offline'] = False
                expect(link).to_contain_text('Updated Alice', timeout=15000)
                old_cookie = next(item['value'] for item in page.context.cookies()
                                  if item['name'].startswith('rosy_learning_session_'))
                page.route('**/api/accounts/session', lambda route: route.fulfill(status=403,
                    content_type='application/json', body='{"error":"Project view permission required"}'))
                page.goto(origin + '/accounts')
                expect(page.locator('#account-status')).to_have_attribute('state', 'forbidden')
                expect(page.locator('#account-login')).to_be_visible()
                assert page.url == origin + '/accounts'
                assert page.locator('[data-state-missing]').count() == 0
                page.unroute('**/api/accounts/session')
                page.goto(origin + '/accounts')
                expect(link).to_contain_text('Updated Alice')
                # Keep the next login at the issuer so logout cannot immediately reauthenticate.
                page.locator('#logout').click()
                expect(page.locator('#login-panel')).to_be_visible()
                expect(page.locator('#account-login')).to_be_visible()
                assert page.url == origin+'/accounts'
                page.locator('#account-login').click()
                page.wait_for_url(issuer + '/api/fleet/auth/authorize**')
                assert not state['active']
                assert receiver.resolve(old_cookie) is None
                assert page.request.get(origin + '/api/accounts/session').status == 401
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def sign_in(page, url, accounts, name):
    """Stand-in for the Rosy Account return: the server session cookie, then a fresh page."""
    session, _ = account_session(accounts, name)
    page.context.add_cookies([{'name': 'rosy_learning_session', 'value': session, 'url': url}])
    page.reload(wait_until='networkidle')


class SelectedAccountTransport(Transport):
    def __init__(self):
        super().__init__()
        self.selected = []

    def resolve(self, kind, repo, revision, token):
        self.selected.append(token)
        return super().resolve(kind, repo, revision, 'selected-secret')


@pytest.mark.parametrize('width', [1440, 320])
def test_named_multi_account_import_logout_real_browser(tmp_path, monkeypatch, accounts, width):
    playwright = pytest.importorskip('playwright.sync_api')
    monkeypatch.setattr('learning_accounts.whoami', lambda token: {
        'id': 'subject-' + token[-1], 'name': 'account-' + token[-1], 'type': 'user'})
    transport = SelectedAccountTransport()
    transport.fail = True

    def credential(actor, project, connection, generation=None, resource=None):
        accounts.authorize(actor, project, 'import')
        return accounts.credential(actor, connection, generation, resource=resource)

    imports = LearningImports(tmp_path / 'imports', accounts.authorize, credential, transport=transport)
    review = tmp_path / 'review'
    review.mkdir()
    store = open_store(review)
    before = store.get(0)
    server = make_server(store, free_port(), accounts=accounts, imports=imports)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    try:
        with playwright.sync_playwright() as runtime:
            browser, page, errors = open_page(runtime, width, 900, url=url)
            try:
                def enable_oauth(route):
                    response = route.fetch()
                    options = response.json()
                    options['oauth'] = True
                    route.fulfill(response=response, json=options)
                page.route('**/api/accounts/options', enable_oauth)
                page.route('**/api/accounts/oauth', lambda route: route.fulfill(
                    json={'url': url + '/accounts?hf-write-reconnected=1'}))
                page.goto(url + '/accounts', wait_until='networkidle')
                expect = playwright.expect
                expect(page.locator('#login-panel')).to_be_visible()
                expect(page.locator('#account-status')).to_have_attribute('state', 'empty')
                expect(page.get_by_role('region', name='Rosy Account 로그인')).to_be_visible()
                expect(page.locator('#account-login')).to_have_attribute('href', '/api/account/login?return=/accounts')
                assert page.locator('#login-panel input').count() == 0
                sign_in(page, url, accounts, 'alice')
                expect(page.locator('#identity')).to_contain_text('작업자 alice')
                expect(page.locator('#identity')).to_contain_text('프로젝트 one')
                page.get_by_text('토큰으로 연결', exact=True).click()
                for index, name in enumerate(('a', 'b'), 1):
                    page.locator('#provider-token').fill('hf_browser_' + name)
                    page.locator('#connect-form button[type=submit]').click()
                    expect(page.locator('#connection option')).to_have_count(index)
                    expect(page.locator('#provider-token')).to_have_value('')
                expect(page.locator('#connections')).to_contain_text('account-a')
                expect(page.locator('#connections')).to_contain_text('account-b')
                expect(page.locator('#hf-manage')).to_have_count(0)
                with page.expect_request('**/api/accounts/oauth') as reconnect:
                    page.get_by_role('button', name='쓰기 권한으로 다시 연결').first.click()
                assert reconnect.value.post_data_json == {'purpose': 'link'}
                expect(page).to_have_url(url + '/accounts?hf-write-reconnected=1')
                expect(page.locator('#connection option')).to_have_count(2)
                page.keyboard.press('Control+k')
                page.get_by_role('textbox', name='기능 검색어').fill('사용 계정')
                page.keyboard.press('Enter')
                expect(page.locator('#connection')).to_be_focused()
                page.locator('#connection').select_option(label='account-b')
                page.locator('#repo-id').fill('org/data')
                page.locator('#files').fill('clip.mp4\nmeta.json')
                page.locator('#license').fill('Apache-2.0')
                page.locator('#rights-evidence').fill('Fixture license reviewed for project one')
                page.locator('#internal-use').check()
                page.locator('#import-form button[type=submit]').click()
                expect(page.locator('#imports')).to_contain_text('실패', timeout=20000)
                expect(page.locator('#imports')).to_contain_text('진행')
                expect(page.locator('#imports')).to_contain_text('clip.mp4')
                summary = page.locator('#imports summary')
                summary.click()
                summary.focus()
                with page.expect_response('**/api/learning/imports', timeout=10000):
                    pass
                expect(page.locator('#imports details')).to_have_attribute('open', '')
                expect(page.locator('#imports summary')).to_be_focused()
                transport.fail = False
                page.get_by_role('button', name='같은 버전 재시도').click()
                expect(page.locator('#imports')).to_contain_text('가져옴 · 검수 대기', timeout=20000)
                expect(page.locator('#imports')).to_contain_text(SHA)
                assert not page.locator('#account-error').is_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')
                state = page.request.get(url + '/api/learning/imports').json()['jobs']
                assert len(state) == 1
                job = state[0]
                assert job['status'] == 'completed' and job['revision'] == SHA
                assert job['requester_id'] == 'alice' and job['project_id'] == 'one'
                assert job['curation_status'] == 'pending_curation'
                assert job['eligibility']['imitation_learning']['status'] == 'blocked'
                assert job['eligibility']['perception']['status'] == 'hold'
                assert job['rights']['license'] == 'Apache-2.0'
                assert transport.selected == ['hf_browser_b']
                assert all(row[2] == 'hf_browser_b' for row in transport.downloads)
                destination = imports.root / 'artifacts' / job['id']
                for entry in job['files']:
                    content = (destination / 'files' / entry['path']).read_bytes()
                    assert hashlib.sha256(content).hexdigest() == entry['sha256']
                assert json.loads((destination / 'manifest.json').read_text())['id'] == job['id']
                assert store.get(0) == before
                assert 'hf_browser_' not in page.locator('body').inner_text()
                assert 'hf_browser_' not in json.dumps(job)
                assert 'hf_browser_' not in page.evaluate('JSON.stringify(localStorage)')
                assert 'hf_browser_' not in page.evaluate('JSON.stringify(sessionStorage)')
                page.once('dialog', lambda dialog: dialog.accept())
                page.locator('#connections article', has_text='account-a').get_by_role('button', name='연결 해제').click()
                expect(page.locator('#connections')).not_to_contain_text('account-a')
                old_session = next(item['value'] for item in page.context.cookies()
                                   if item['name'] == 'rosy_learning_session')
                page.locator('#logout').click()
                expect(page.locator('#login-panel')).to_be_visible()
                assert request(url, '/api/workspace', old_session)[0] == 401
                assert page.request.get(url + '/api/learning/imports').status == 401
                assert not errors
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_permissions_session_expiry_and_network_recovery_browser(tmp_path, accounts):
    playwright = pytest.importorskip('playwright.sync_api')
    cfg = json.loads(accounts.config_path.read_text())
    cfg['users'].append({'user_id': 'viewer', 'username': 'viewer', 'memberships': {'one': ['view']}})
    accounts.config_path.write_text(json.dumps(cfg))
    _, alice = account_session(accounts, 'alice')
    connection = accounts.connect_token(alice, 'hf_team', transport=lambda _: {'id': 'team', 'name': 'team', 'type': 'user'},
        sharing='project', resources=['dataset:org/data'])
    def credential(actor, project, connection_id, generation=None, resource=None):
        accounts.authorize(actor, project, 'import')
        return accounts.credential(actor, connection_id, generation, resource=resource)
    imports = LearningImports(tmp_path / 'imports', accounts.authorize, credential,
                              transport=SelectedAccountTransport())
    imports.create(alice, 'one', connection['connection_id'], 'dataset', 'org/data', 'main',
                   ['clip.mp4'], {'internal_use': True, 'evidence': 'fixture license'})
    folder = tmp_path / 'review'; folder.mkdir()
    server = make_server(open_store(folder), free_port(), accounts=accounts, imports=imports)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    try:
        with playwright.sync_playwright() as runtime:
            browser, page, errors = open_page(runtime, 320, 900, url=url)
            try:
                expect = playwright.expect
                page.goto(url + '/accounts', wait_until='networkidle')
                def login(name):
                    sign_in(page, url, accounts, name)
                    expect(page.locator('#identity')).to_contain_text('작업자 ' + name)
                login('viewer')
                expect(page.locator('#import-panel')).to_be_hidden()
                expect(page.locator('summary', has_text='토큰으로 연결')).to_be_hidden()
                expect(page.locator('#connections button')).to_have_count(0)
                expect(page.locator('#imports')).to_contain_text('org/data')
                expect(page.locator('#imports button')).to_have_count(0)
                page.locator('#logout').click()
                expect(page.locator('#login-panel')).to_be_visible()
                expect(page.locator('#identity')).to_have_text('')
                expect(page.locator('#connections')).to_have_text('')
                login('bob')
                page.get_by_text('토큰으로 연결', exact=True).click()
                page.locator('#sharing').focus()
                page.keyboard.press('End')
                expect(page.locator('#sharing')).to_have_value('personal')
                expect(page.locator('#connections button')).to_have_count(0)
                expect(page.locator('#imports button')).to_have_count(0)
                # An unavailable backend must not masquerade as a logged-out session.
                page.route('**/api/accounts/session', lambda route: route.fulfill(
                    status=503, content_type='application/json', body='{"error":"temporarily unavailable"}'))
                page.locator('#reload').click()
                expect(page.locator('#account-error')).to_contain_text('temporarily unavailable')
                expect(page.locator('#login-panel')).to_be_hidden()
                page.unroute('**/api/accounts/session')
                page.locator('#reload').click()
                expect(page.locator('#account-error')).to_be_hidden()
                page.locator('#provider-token').fill('hf_unsent_secret')
                page.locator('#rights-evidence').fill('private draft')
                session = next(item['value'] for item in page.context.cookies()
                               if item['name'] == 'rosy_learning_session')
                accounts.logout(session)
                expect(page.locator('#login-panel')).to_be_visible(timeout=12000)
                expect(page.locator('#signed-in')).to_be_hidden()
                expect(page.locator('#identity')).to_have_text('')
                expect(page.locator('#imports')).to_have_text('')
                expect(page.locator('#provider-token')).to_have_value('')
                expect(page.locator('#rights-evidence')).to_have_value('')
                login('bob')
                expect(page.locator('#import-panel')).to_be_visible()
                assert not errors
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


@pytest.mark.parametrize('width', [1440, 390])
def test_catalog_sends_a_verified_hf_import_to_review_browser(tmp_path, width):
    """자료 stage: a completed import gets 「검수로 보내기」 and then shows its pending state."""
    import cv2
    import numpy as np
    import review_masks
    from test_learning_collaboration import Accounts
    from test_learning_imports import RIGHTS
    from test_review_cycle import CLASSES
    playwright = pytest.importorskip('playwright.sync_api')
    fake = Accounts()
    def authorize(actor, project, capability):
        fake.require(actor, capability)
    transport = Transport()
    transport.data = {'img/a.png': cv2.imencode('.png', np.full((24, 32, 3), 90, np.uint8))[1].tobytes()}
    imports = LearningImports(tmp_path / 'imports', authorize, transport=transport,
                              credential=lambda *args, **kwargs: {'token': 'selected-secret', 'generation': 1})
    reviewer = fake.authenticate('reviewer')
    job = imports.create(reviewer, 'alpha', 'hf-a', 'dataset', 'org/data', 'main', ['img/a.png'], RIGHTS)
    imports.run(job['id'], reviewer)
    store = open_store(tmp_path)
    review_masks.bind_classes(store, CLASSES)
    server = make_server(store, free_port(), accounts=fake, imports=imports)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    try:
        with playwright.sync_playwright() as runtime:
            browser, page, errors = open_page(runtime, width, 900, url=url)
            try:
                expect = playwright.expect
                page.context.add_cookies([{'name': 'rosy_learning_session', 'value': 'reviewer', 'url': url}])
                page.goto(url + '/catalog', wait_until='networkidle')
                send = page.locator('#hf-imports ui-button', has_text='검수로 보내기')
                expect(send).to_be_visible()
                assert send.bounding_box()['height'] >= 44
                send.click()
                expect(page.locator('#hf-imports ui-tag')).to_have_text('검수 대기로 보냄')
                expect(page.locator('#hf-imports')).to_contain_text('새 사진 1장')
                expect(page.locator('#hf-imports ui-button')).to_have_count(0)
                assert page.locator('#hf-imports a').bounding_box()['height'] >= 44
                assert imports.get(reviewer, 'alpha', job['id'])['review']['registered_by'] == 'reviewer'
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert not errors
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
