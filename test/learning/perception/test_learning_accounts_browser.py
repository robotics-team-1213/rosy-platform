"""Actual Chromium/HTTP/SQLite account collaboration with only HF replaced."""
import hashlib
import json
import threading

import pytest

from browser_harness import browser_tests_enabled, free_port, open_page
from learning_imports import LearningImports
from review_app import make_server
from test_learning_accounts import accounts  # noqa: F401 — shared real encrypted account fixture
from test_learning_collaboration import request
from test_learning_imports import SHA, Transport
from test_review_app import open_store


pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium browser run')


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
                page.goto(url + '/accounts', wait_until='networkidle')
                expect = playwright.expect
                expect(page.locator('#login-panel')).to_be_visible()
                page.locator('#username').fill('alice')
                page.locator('#password').fill('alice-password')
                page.locator('#login-form button[type=submit]').click()
                expect(page.locator('#identity')).to_contain_text('작업자 alice')
                expect(page.locator('#identity')).to_contain_text('프로젝트 one')
                page.get_by_text('읽기 토큰으로 연결', exact=True).click()
                for index, name in enumerate(('a', 'b'), 1):
                    page.locator('#provider-token').fill('hf_browser_' + name)
                    page.locator('#connect-form button[type=submit]').click()
                    expect(page.locator('#connection option')).to_have_count(index)
                    expect(page.locator('#provider-token')).to_have_value('')
                expect(page.locator('#connections')).to_contain_text('account-a')
                expect(page.locator('#connections')).to_contain_text('account-b')
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
    cfg['users'].append({'user_id': 'viewer', 'username': 'viewer',
        'password_hash': cfg['users'][1]['password_hash'], 'memberships': {'one': ['view']}})
    accounts.config_path.write_text(json.dumps(cfg))
    _, alice = accounts.login('alice', 'alice-password')
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
                    page.locator('#username').fill(name)
                    page.locator('#password').fill('bob-password')
                    page.locator('#login-form button[type=submit]').click()
                    expect(page.locator('#identity')).to_contain_text('작업자 ' + name)
                login('viewer')
                expect(page.locator('#import-panel')).to_be_hidden()
                expect(page.locator('summary', has_text='읽기 토큰으로 연결')).to_be_hidden()
                expect(page.locator('#connections button')).to_have_count(0)
                expect(page.locator('#imports')).to_contain_text('org/data')
                expect(page.locator('#imports button')).to_have_count(0)
                page.locator('#logout').click()
                expect(page.locator('#login-panel')).to_be_visible()
                expect(page.locator('#identity')).to_have_text('')
                expect(page.locator('#connections')).to_have_text('')
                login('bob')
                page.get_by_text('읽기 토큰으로 연결', exact=True).click()
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
