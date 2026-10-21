"""D-683 account discovery, verified authentication and no automatic operation replay."""
import threading
import os
import json
import time
from urllib.parse import urlencode
from pathlib import Path

import pytest
import uvicorn
from browser_harness import browser_tests_enabled, safe_listener
from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.site_users import hash_password
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='opt-in Chromium scenario')
ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize('account_page', ['multi'], indirect=True)
def test_denied_login_stays_visible_and_allows_another_account(account_page):
    from playwright.sync_api import expect
    page, origin = account_page
    page.goto(origin + '/console/login')
    _credentials(page)
    page.locator('[data-login=submit]').click()
    expect(page.locator('#user-role')).to_have_attribute('title', 'alice · operator')
    target = '/api/fleet/auth/authorize?' + urlencode({
        'response_type': 'code', 'client_id': 'learning', 'redirect_uri': 'https://learning.test/callback',
        'scope': 'project:one', 'state': 'test-state', 'code_challenge': 'x' * 43,
        'code_challenge_method': 'S256'})
    authorizations = []
    def authorized(route):
        authorizations.append(route.request.url)
        route.fulfill(content_type='text/html', body='<h1>Application authorization</h1>')
    page.route('**/api/fleet/auth/authorize?**', authorized)
    with page.expect_response('**/api/fleet/auth/session'):
        page.goto(origin + '/console/login?' + urlencode({'error': 'access_denied', 'return': target}))
    expect(page.locator('#login-recovery')).to_be_visible()
    expect(page.locator('#login-recovery-status')).to_contain_text('프로젝트 권한')
    expect(page.locator('[data-login=login]')).to_be_visible()
    assert not authorizations
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.locator('[data-login=login]').fill('bob')
    page.locator('[data-login=password]').fill('pw-1234')
    page.locator('[data-login=submit]').click()
    expect(page.get_by_role('heading', name='Application authorization')).to_be_visible()
    assert len(authorizations) == 1 and authorizations[0] == origin + target
    assert page.request.get(origin + '/api/fleet/auth/session').json()['principal_id'] == 'bob'


@pytest.fixture
def account_page(tmp_path, request, account_backend):
    from playwright.sync_api import sync_playwright
    console = FleetConsole([RobotEndpoint('rosy_01', 'http://127.0.0.1:8080', 'robot-only')],
                           [FakeRobot('rosy_01')])
    tasks = FleetTaskService(FleetTaskStore(tmp_path / 'fleet.sqlite3'), robot_ids=console.robot_ids)
    initial = getattr(request, 'param', 'pw-1234')
    logins = {'alice': {'principal_id': 'alice', 'role': 'operator',
                       'password_scrypt': hash_password('pw-1234' if initial == 'multi' else initial)}}
    if initial == 'multi':
        logins['bob'] = {'principal_id': 'bob', 'role': 'viewer', 'password_scrypt': hash_password('pw-1234')}
    app = create_app(console, task_service=tasks, site_users={}, site_logins=logins,
        web_common=ROOT / 'shared' / 'web', start_task_dispatcher=False)
    if account_backend == 'managed':
        app.state.password_sessions.bootstrap_accounts('alice', 'test-site')
    listener = safe_listener()
    origin = f'http://localhost:{listener.getsockname()[1]}'
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', timeout_graceful_shutdown=3))
    worker = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 20
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(.02)
        assert server.started
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context(viewport={'width': 320, 'height': 900})
                yield context.new_page(), origin
            finally:
                browser.close()
    finally:
        server.should_exit = True
        worker.join(timeout=20)
        listener.close()
        assert not worker.is_alive()


@pytest.fixture(params=['legacy', 'managed'])
def account_backend(request):
    return request.param


def _credentials(page):
    page.locator('[data-login=login]').fill('alice')
    page.locator('[data-login=password]').fill('pw-1234')


@pytest.mark.parametrize('path', ['/console', '/console/install', '/console/site-map', '/console/cell'])
def test_profile_entry_preserves_work_context_and_verifies_own_name(account_page, path, account_backend):
    from playwright.sync_api import expect
    page, origin = account_page
    page.goto(origin + '/console/login?return=' + path)
    _credentials(page)
    page.locator('[data-login=submit]').click()
    expect(page.locator('#user-role')).to_have_attribute('title', 'alice · operator')
    expect(page.locator('#fleet-login')).to_be_hidden()  # D-683 1: login link or account menu, never both
    page.locator('#topbar-more').click()
    expect(page.locator('#fleet-account')).to_be_visible()
    expect(page.locator('#fleet-profile')).to_be_visible()
    writes = []
    page.context.on('request', lambda req: writes.append(req.url) if req.method in ('POST', 'PATCH') else None)
    if path in ('/console/site-map', '/console/cell'):
        with page.expect_popup() as popup:
            page.locator('#fleet-profile').click()
        profile = popup.value
        expect(page).to_have_url(origin + path)
    else:
        page.locator('#fleet-profile').click()
        profile = page
    expect(profile.locator('#profile-id')).to_have_text('alice')
    expect(profile.locator('#profile-role')).to_have_text('운영자')
    if account_backend == 'managed':
        expect(profile.locator('#profile-grants')).to_be_visible()
        expect(profile.locator('#profile-grant-list')).to_contain_text('site:test-site')
        expect(profile.locator('#profile-grant-list')).to_contain_text('계정 관리')
    else:
        expect(profile.locator('#profile-grants')).to_be_hidden()
    assert profile.locator('#profile-id input, #profile-email input, #profile-role input').count() == 0
    assert profile.evaluate('document.documentElement.scrollWidth <= innerWidth')
    name = '<b>현장 운영자</b>'
    profile.locator('#profile-name').fill(name)
    profile.locator('#profile-name').press('Enter')
    expect(profile.locator('#profile-status')).to_contain_text('저장하고 다시 확인')
    expect(profile.locator('#profile-name')).to_have_value(name)
    assert profile.locator('#profile-content b').count() == 0
    profile.reload()
    expect(profile.locator('#profile-name')).to_have_value(name)
    if output := os.environ.get('ROSY_SHOT_DIR'):
        for width in (320, 1366):
            profile.set_viewport_size({'width': width, 'height': 900})
            assert profile.evaluate('document.documentElement.scrollWidth <= innerWidth')
            profile.screenshot(path=str(Path(output) / f'profile-{path.rsplit("/", 1)[-1]}-{width}.png'), full_page=True)
    assert writes == [origin + '/api/fleet/auth/profile']
    assert profile.locator('#profile-back').get_attribute('href') == path


def test_profile_password_checks_current_clears_secrets_and_revokes_old_sessions(account_page):
    from playwright.sync_api import expect
    page, origin = account_page
    page.goto(origin + '/console/login?return=%2Fconsole%2Fprofile')
    _credentials(page)
    page.locator('[data-login=submit]').click()
    expect(page.locator('#profile-id')).to_have_text('alice')
    old_context = page.context.browser.new_context(storage_state=page.context.storage_state())
    try:
        page.locator('#profile-current').fill('wrong-current')
        page.locator('#profile-new').fill('new-credential-123')
        page.locator('#profile-confirm').fill('new-credential-123')
        page.locator('#profile-confirm').press('Enter')
        expect(page.locator('#profile-status')).to_contain_text('현재 비밀번호가 맞지 않습니다')
        for field in ('current', 'new', 'confirm'):
            expect(page.locator('#profile-' + field)).to_have_value('')
        assert old_context.request.get(origin + '/api/fleet/auth/profile').status == 200
        page.locator('#profile-current').fill('pw-1234')
        page.locator('#profile-new').fill('new-credential-123')
        page.locator('#profile-confirm').fill('new-credential-123')
        writes = []
        page.on('request', lambda req: writes.append(req.url) if req.method == 'POST' else None)
        page.evaluate("""() => {
          document.getElementById('profile-password-save').click();
          document.getElementById('profile-password-form').requestSubmit();
        }""")
        expect(page.locator('#profile-status')).to_contain_text('새 로그인 상태를 확인했습니다')
        assert writes == [origin + '/api/fleet/auth/change-password']
        assert old_context.request.get(origin + '/api/fleet/auth/profile').status == 401
        for field in ('current', 'new', 'confirm'):
            expect(page.locator('#profile-' + field)).to_have_value('')
        page.reload()
        expect(page.locator('#profile-id')).to_have_text('alice')
    finally:
        old_context.close()


def test_profile_save_failure_preserves_name_and_does_not_claim_success(account_page):
    from playwright.sync_api import expect
    page, origin = account_page
    page.goto(origin + '/console/login?return=%2Fconsole%2Fprofile')
    _credentials(page)
    page.locator('[data-login=submit]').click()
    expect(page.locator('#profile-id')).to_have_text('alice')
    page.locator('#profile-name').fill('저장 확인 필요')
    page.route('**/api/fleet/auth/profile', lambda route: route.fulfill(status=503, body='{}')
               if route.request.method == 'PATCH' else route.continue_())
    page.locator('#profile-name-save').click()
    expect(page.locator('#profile-status')).to_contain_text('처리 결과를 확인할 수 없습니다')
    expect(page.locator('#profile-grants')).to_be_hidden()
    expect(page.locator('#profile-name')).to_have_value('저장 확인 필요')
    page.unroute('**/api/fleet/auth/profile')
    page.locator('#profile-reload').click()
    expect(page.locator('#profile-name')).to_have_value('alice')


@pytest.mark.parametrize('account_page', ['multi'], indirect=True)
@pytest.mark.parametrize('action', ['focus', 'save'])
def test_profile_changed_cookie_account_stops_stale_edits(account_page, action):
    from playwright.sync_api import expect
    page, origin = account_page
    page.goto(origin + '/console/login?return=%2Fconsole%2Fprofile')
    _credentials(page)
    page.locator('[data-login=submit]').click()
    expect(page.locator('#profile-id')).to_have_text('alice')
    page.locator('#profile-name').fill('다른 계정에 저장 금지')
    page.locator('#profile-current').fill('pw-1234')
    assert page.request.post(origin + '/api/fleet/auth/logout', headers={'Origin': origin}).status == 204
    assert page.request.post(origin + '/api/fleet/auth/login', headers={'Origin': origin},
                             data={'login': 'bob', 'password': 'pw-1234'}).status == 204
    writes = []
    page.on('request', lambda req: writes.append(req.url) if req.method in ('PATCH', 'POST') else None)
    if action == 'focus':
        page.evaluate("window.dispatchEvent(new Event('focus'))")
    else:
        page.locator('#profile-name-save').click()
    expect(page.locator('#profile-status')).to_contain_text('로그인 계정이 바뀌었습니다')
    expect(page.locator('#profile-content')).to_be_hidden()
    assert page.locator('#profile-current').input_value() == ''
    assert writes == []
    page.locator('#profile-reload').click()
    expect(page.locator('#profile-id')).to_have_text('bob')
    expect(page.locator('#profile-name')).to_have_value('bob')


def test_profile_expired_reload_clears_hidden_password_fields(account_page):
    from playwright.sync_api import expect
    page, origin = account_page
    page.goto(origin + '/console/login?return=%2Fconsole%2Fprofile')
    _credentials(page)
    page.locator('[data-login=submit]').click()
    expect(page.locator('#profile-id')).to_have_text('alice')
    for field in ('current', 'new', 'confirm'):
        page.locator('#profile-' + field).fill('new-credential-123')
    assert page.request.post(origin + '/api/fleet/auth/logout', headers={'Origin': origin}).status == 204
    page.locator('#profile-reload').click()
    expect(page.locator('#profile-login')).to_be_visible()
    for field in ('current', 'new', 'confirm'):
        assert page.locator('#profile-' + field).input_value() == ''


@pytest.mark.parametrize('account_page', ['alice'], indirect=True)
def test_first_login_changes_password_before_return_and_does_not_replay_commands(account_page):
    from playwright.sync_api import expect
    page, origin = account_page
    writes = []
    page.on('request', lambda req: writes.append(req.url) if req.method == 'POST' else None)
    page.goto(origin + '/console/login?return=%2Fconsole%3Fview%3Dwork')
    page.locator('[data-login=login]').fill('alice')
    page.locator('[data-login=password]').fill('alice')
    page.locator('[data-login=password]').press('Enter')
    expect(page.locator('[data-login=form]')).to_have_attribute('aria-label', '첫 로그인 비밀번호 변경')
    expect(page.locator('[data-login=password]')).to_be_focused()
    if output := os.environ.get('ROSY_SHOT_DIR'):
        page.screenshot(path=str(Path(output) / 'first-password-change-320.png'), full_page=True)
    expect(page).to_have_url(origin + '/console/login?return=%2Fconsole%3Fview%3Dwork')
    assert page.request.get(origin + '/api/fleet/session').status == 403
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    for path in ('/console', '/console/install', '/console/site-map', '/console/cell'):
        tab = page.context.new_page()
        tab.goto(origin + path)
        expect(tab.locator('#fleet-login')).to_have_text('비밀번호 변경')
        expect(tab.locator('#fleet-account')).to_be_hidden()
        expect(tab.locator('#estop')).to_be_disabled()
        tab.close()
    page.reload()
    expect(page.locator('[data-login=form]')).to_have_attribute('aria-label', '첫 로그인 비밀번호 변경')
    page.locator('[data-login=password]').fill('new-credential-123')
    page.locator('[data-login=confirm]').fill('different-credential')
    page.locator('[data-login=submit]').click()
    expect(page.locator('[data-login=error]')).to_contain_text('일치하지 않습니다')
    expect(page.locator('[data-login=password]')).to_have_value('')
    expect(page.locator('[data-login=confirm]')).to_have_value('')
    assert writes == [origin + '/api/fleet/auth/login']
    page.locator('[data-login=password]').fill('new-credential-123')
    page.locator('[data-login=confirm]').fill('new-credential-123')
    page.evaluate("""() => {
      document.querySelector('[data-login=submit]').click();
      document.querySelector('[data-login=form]').requestSubmit();
    }""")
    expect(page).to_have_url(origin + '/console?view=work')
    expect(page.locator('#user-role')).to_have_attribute('title', 'alice · operator')
    assert writes == [origin + '/api/fleet/auth/login', origin + '/api/fleet/auth/change-password']
    session = page.request.get(origin + '/api/fleet/auth/session').json()
    assert session['password_change_required'] is False


@pytest.mark.parametrize('account_page', ['alice'], indirect=True)
def test_first_password_change_waits_for_readback_and_recovers_expired_login(account_page):
    from playwright.sync_api import expect
    page, origin = account_page
    page.goto(origin + '/console/login')
    page.locator('[data-login=login]').fill('alice')
    page.locator('[data-login=password]').fill('alice')
    page.locator('[data-login=submit]').click()
    expect(page.locator('[data-login=form]')).to_have_attribute('aria-label', '첫 로그인 비밀번호 변경')
    page.route('**/api/fleet/auth/change-password', lambda route: route.fulfill(status=503, body='{}'))
    page.locator('[data-login=password]').fill('new-credential-123')
    page.locator('[data-login=confirm]').fill('new-credential-123')
    page.locator('[data-login=submit]').click()
    expect(page.locator('[data-login=error]')).to_contain_text('화면을 새로고침해 계정 상태')
    expect(page.locator('[data-login=password]')).to_have_value('')
    expect(page.locator('[data-login=confirm]')).to_have_value('')
    expect(page).to_have_url(origin + '/console/login')
    page.unroute('**/api/fleet/auth/change-password')
    page.route('**/api/fleet/auth/change-password', lambda route: route.fulfill(status=401, body='{}'))
    page.locator('[data-login=password]').fill('new-credential-123')
    page.locator('[data-login=confirm]').fill('new-credential-123')
    page.locator('[data-login=submit]').click()
    expect(page.locator('[data-login=error]')).to_contain_text('로그인이 만료')
    expect(page.locator('[data-login=form]')).to_have_attribute('aria-label', '관제 로그인')
    expect(page.locator('[data-login=login]')).to_be_focused()
    expect(page.locator('[data-login=password]')).to_have_value('')


@pytest.mark.parametrize('account_page', ['alice'], indirect=True)
def test_changed_password_with_failed_readback_recovers_by_reload(account_page):
    from playwright.sync_api import expect
    page, origin = account_page
    page.goto(origin + '/console/login')
    page.locator('[data-login=login]').fill('alice')
    page.locator('[data-login=password]').fill('alice')
    page.locator('[data-login=submit]').click()
    expect(page.locator('[data-login=form]')).to_have_attribute('aria-label', '첫 로그인 비밀번호 변경')
    page.route('**/api/fleet/auth/session', lambda route: route.fulfill(status=503, body='{}'))
    page.locator('[data-login=password]').fill('new-credential-123')
    page.locator('[data-login=confirm]').fill('new-credential-123')
    page.locator('[data-login=submit]').click()
    expect(page.locator('[data-login=error]')).to_contain_text('화면을 새로고침해 계정 상태')
    expect(page).to_have_url(origin + '/console/login')
    expect(page.locator('[data-login=password]')).to_have_value('')
    expect(page.locator('[data-login=confirm]')).to_have_value('')
    page.unroute('**/api/fleet/auth/session')
    page.reload()
    expect(page).to_have_url(origin + '/console')
    expect(page.locator('#user-role')).to_have_attribute('title', 'alice · operator')


@pytest.mark.parametrize('path', ['/console', '/console/install', '/console/site-map', '/console/cell'])
def test_account_entry_returns_to_each_document_without_commands(account_page, path):
    from playwright.sync_api import expect
    page, origin = account_page
    writes = []
    page.context.on('request', lambda req: writes.append(req.url) if req.method == 'POST' else None)
    page.goto(origin + path)
    expect(page.locator('#fleet-login')).to_be_visible()
    if path in ['/console/site-map', '/console/cell']:
        with page.expect_popup() as popup:
            page.locator('#fleet-login').click()
        login = popup.value
        expect(login.locator('#login-context')).to_contain_text('초안')
    else:
        page.locator('#fleet-login').click()
        login = page
    _credentials(login)
    if output := os.environ.get('ROSY_SHOT_DIR'):
        for width in (320, 1366):
            login.set_viewport_size({'width': width, 'height': 900})
            login.screenshot(path=str(Path(output) / f'account-login-{width}.png'), full_page=True)
    login.locator('[data-login=password]').press('Enter')
    expect(login).to_have_url(origin + path)
    expect(login.locator('#user-role')).to_have_attribute('title', 'alice · operator')
    login.locator('#topbar-more').click()
    expect(login.locator('#fleet-account')).to_be_visible()
    expect(login.locator('#fleet-account-identity')).to_contain_text('alice')
    expect(login.locator('[data-login=logout]')).to_be_enabled()
    for width in (320, 1366):
        login.set_viewport_size({'width': width, 'height': 900})
        assert login.evaluate('document.documentElement.scrollWidth <= innerWidth')
        if output := os.environ.get('ROSY_SHOT_DIR'):
            login.screenshot(path=str(Path(output) / f'account-{path.rsplit("/", 1)[-1]}-{width}.png'), full_page=True)
    assert writes == [origin + '/api/fleet/auth/login']


def test_logout_failure_does_not_claim_the_session_ended(account_page):
    from playwright.sync_api import expect
    page, origin = account_page
    page.goto(origin + '/console/login')
    _credentials(page)
    page.locator('[data-login=submit]').click()
    expect(page.locator('#user-role')).to_have_attribute('title', 'alice · operator')
    page.locator('#topbar-more').click()
    expect(page.locator('#fleet-account')).to_be_visible()
    page.route('**/api/fleet/auth/logout', lambda route: route.fulfill(status=503, body='{}'))
    page.locator('[data-login=logout]').click()
    expect(page.locator('[data-login=error]')).to_contain_text('확인 불가')
    expect(page.locator('#fleet-account')).to_be_visible()
    expect(page.locator('#user-role')).to_have_attribute('title', 'alice · operator')
    page.unroute('**/api/fleet/auth/logout')
    page.locator('[data-login=logout]').click()
    expect(page.locator('#fleet-login')).to_be_visible()


def test_login_waits_for_session_readback_and_rejects_duplicate_submit(account_page):
    from playwright.sync_api import expect
    page, origin = account_page
    page.goto(origin + '/console/login?return=%2Fconsole%3Fview%3Dwork')
    _credentials(page)
    page.route('**/api/fleet/auth/session', lambda route: route.fulfill(status=503, body='{}'))
    writes = []
    page.on('request', lambda req: writes.append(req.url) if req.method == 'POST' else None)
    page.evaluate("""() => {
      document.querySelector('[data-login=submit]').click();
      document.querySelector('[data-login=form]').requestSubmit();
    }""")
    expect(page.locator('[data-login=error]')).to_contain_text('확인할 수 없습니다')
    expect(page.locator('[data-login=password]')).to_have_value('')
    expect(page.locator('[data-login=login]')).to_have_value('alice')
    assert '/console/login?' in page.url
    assert writes == [origin + '/api/fleet/auth/login']


def test_focus_revalidates_changed_role_for_the_same_principal(account_page):
    from playwright.sync_api import expect
    page, origin = account_page
    page.goto(origin + '/console/login')
    _credentials(page)
    page.locator('[data-login=submit]').click()
    expect(page.locator('#user-role')).to_have_attribute('title', 'alice · operator')
    identity = {'principal_id': 'alice', 'role': 'viewer', 'via': 'cookie'}
    for path in ['/api/fleet/auth/session', '/api/fleet/session']:
        page.route('**' + path, lambda route: route.fulfill(content_type='application/json', body=json.dumps(identity)))
    page.evaluate("window.dispatchEvent(new Event('focus'))")
    expect(page.locator('#user-role')).to_have_attribute('title', 'alice · viewer')
    expect(page.locator('#estop')).to_be_disabled()


def test_empty_cell_token_uses_cookie_despite_stale_storage(account_page):
    from playwright.sync_api import expect
    from browser_harness import open_token_access
    page, origin = account_page
    page.goto(origin + '/console/login?return=%2Fconsole%2Fcell')
    _credentials(page)
    page.locator('[data-login=submit]').click()
    expect(page.locator('#user-role')).to_have_attribute('title', 'alice · operator')
    page.evaluate("sessionStorage.setItem('rosy-console-token', 'stale-token')")
    open_token_access(page)
    page.locator('#console-token').fill('')
    page.locator('#token-save').click()
    expect(page.locator('#fleet-account')).to_be_visible()  # open_token_access가 계정 단추를 이미 열었다
    expect(page.locator('[data-login=logout]')).to_be_visible()
    expect(page.locator('[data-login=logout]')).to_have_text('로그아웃')
    expect(page.locator('[data-login=logout]')).to_be_enabled()
