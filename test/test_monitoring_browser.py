"""Real Chromium reads the independent Monitoring backend; never intercept its API."""

import json
import asyncio
import os
from pathlib import Path
import threading
import time
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
import uvicorn

from browser_harness import browser_tests_enabled, launch_options, safe_listener


pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='opt-in real Chromium Monitoring scenario')
ROOT = Path(__file__).resolve().parents[1]
KEY_A, KEY_B = 'a' * 32, 'b' * 32


class AccountStub:
    """The Account side of the receiver; Monitoring's routes, cookies and screen stay real."""
    resource, profile_url, callback = 'site:site-a', None, ''

    def __init__(self):
        self.capabilities, self.logged_out = None, []

    def resolve(self, cookie):
        from core_common.protocol.account_access import AccountAccess
        if cookie != 'good' or not self.capabilities:
            return None
        now = int(time.time())
        return AccountAccess.model_validate({
            'iss': 'https://account.example.test', 'aud': self.resource, 'sub': 'person', 'sid': 'session', 'jti': 'j' * 16,
            'rev': 1, 'iat': now, 'exp': now + 60, 'grants': [{'resource': self.resource, 'capabilities': self.capabilities}]})

    def profile(self, _cookie):
        return None

    def apps(self, _cookie):
        return [{'client_id': 'fleet', 'label': '관제', 'home_url': 'https://site.example.test/console'}]

    def logout(self, cookie):
        self.capabilities = None
        self.logged_out.append(cookie)

    def retry_revocations(self):
        pass


@pytest.fixture
def monitoring_backend(tmp_path, request):
    from rosy.monitoring.config import MonitoringConfig, load_credentials
    from rosy.monitoring.service import Collector, create_app
    from rosy.monitoring.store import MonitoringStore

    mode = getattr(request, 'param', None)
    web_root = None
    if mode in {'account', 'web', 'xss', 'delayed', 'unavailable', 'empty', 'error', 'disconnected', 'prefix'}:
        from rosy.monitoring.web_assets import build_web
        web_root = tmp_path / 'web'
        build_web(ROOT, web_root)
    sources, paths = [], {}
    for site in ('a', 'b'):
        path = tmp_path / f'host-{site}.json'
        path.write_text(json.dumps({'time': int(time.time()) - (2101 if mode == 'delayed' and site == 'a' else 0),
                                    'fixed': [], 'drift': [], 'awaiting_approval': [],
                                    'errors': ['private owner detail'] if site == 'b' or mode == 'error' else []}))
        paths[site] = path
        label = '<img src=x onerror=window.monitoringInjected=1>' if mode == 'xss' else f'검증 호스트 {site.upper()}'
        if not (mode == 'empty' and site == 'a'):
            sources.append({'id': f'host-{site}', 'site_id': f'site-{site}', 'kind': 'host_state', 'path': str(path), 'label': label})
        if mode == 'unavailable' and site == 'a':
            path.unlink()
    config = MonitoringConfig(collector_id='browser-monitoring', site_id='site-a', sources=sources,
                              readers=[{'principal_id': f'operator-{site}', 'token_env': f'READ_{site.upper()}',
                                        'sites': [f'site-{site}']} for site in ('a', 'b')])
    store = MonitoringStore(tmp_path / 'monitoring.sqlite3', config.collector_id)
    collector = Collector(config, load_credentials(config, {'READ_A': KEY_A, 'READ_B': KEY_B}), store)
    account = AccountStub() if mode == 'account' else None
    app = create_app(collector, web_root=web_root, account=account)
    slow = SimpleNamespace(key=None, entered=threading.Event(), release=threading.Event())
    @app.middleware('http')
    async def delayed_actual_response(request, call_next):
        response = await call_next(request)
        if (slow.key is not None and request.url.path == '/api/monitoring/v1/snapshot'
                and request.headers.get('authorization') == slow.key and not slow.entered.is_set()):
            slow.entered.set()
            until = time.monotonic() + 10
            while not slow.release.is_set() and time.monotonic() < until:
                await asyncio.sleep(0.01)
        return response
    listener = safe_listener()
    origin = f'http://127.0.0.1:{listener.getsockname()[1]}'
    if account:
        account.callback = origin + '/api/monitoring/v1/account/callback'
    async def prefix_gateway(scope, receive, send):
        from starlette.responses import Response
        if scope['type'] != 'http':
            return await app(scope, receive, send)
        path = scope['path']
        if path.startswith('/monitoring/'):
            scope = {**scope, 'path': path[len('/monitoring'):]}
        elif not path.startswith('/api/monitoring/') and path != '/health':
            return await Response(status_code=404)(scope, receive, send)
        await app(scope, receive, send)
    server = uvicorn.Server(uvicorn.Config(prefix_gateway if mode == 'prefix' else app, log_level='error', access_log=False,
                                         proxy_headers=False, timeout_graceful_shutdown=3, log_config=None))
    worker = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        yield SimpleNamespace(origin=origin, server=server, worker=worker, collector=collector,
                              paths=paths, slow=slow, account=account)
    finally:
        server.should_exit = True
        worker.join(15)
        listener.close()
        assert not worker.is_alive()


@pytest.fixture
def monitoring_page(monitoring_backend):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        options = launch_options()
        options['args'] = [f'--explicitly-allowed-ports={urlsplit(monitoring_backend.origin).port}']
        browser = playwright.chromium.launch(**options)
        try:
            page = browser.new_page()
            page.goto(monitoring_backend.origin + '/health')
            yield page
        finally:
            browser.close()


def read(page, path, key):
    return page.evaluate('''async ({path, key}) => {
      const response = await fetch(path, {cache: 'no-store', credentials: 'omit',
        headers: key ? {Authorization: 'Bearer ' + key} : {}});
      return {status: response.status, cache: response.headers.get('cache-control'), body: await response.json()};
    }''', {'path': path, 'key': key})


def test_browser_reads_scoped_cache_without_fleet(monitoring_page):
    response = read(monitoring_page, '/api/monitoring/v1/snapshot', KEY_A)
    assert response['status'] == 200 and response['cache'] == 'no-store'
    assert response['body']['scope_sites'] == ['site-a']
    assert all(row['site_id'] == 'site-a' for row in response['body']['nodes'])
    assert KEY_A not in json.dumps(response['body'])


def test_browser_cannot_read_another_site_or_without_key(monitoring_page):
    assert read(monitoring_page, '/api/monitoring/v1/snapshot', None)['status'] == 401
    denied = read(monitoring_page, '/api/monitoring/v1/snapshot?site_id=site-b', KEY_A)
    assert denied['status'] == 403 and 'site-b' not in json.dumps(denied['body'])
    other = read(monitoring_page, '/api/monitoring/v1/snapshot', KEY_B)
    assert other['body']['scope_sites'] == ['site-b']


def test_browser_history_keeps_the_same_reader_scope(monitoring_page):
    assert read(monitoring_page, '/api/monitoring/v1/sites/site-b/events', KEY_A)['status'] == 403
    response = read(monitoring_page, '/api/monitoring/v1/sites/site-a/events', KEY_A)
    assert response['status'] == 200 and response['cache'] == 'no-store'
    assert 'private owner detail' not in json.dumps(response['body'])


def login(page, key):
    page.get_by_label('조회 키', exact=True).fill(key)
    page.get_by_role('button', name='조회 시작', exact=True).click()


@pytest.mark.parametrize('monitoring_backend', ['web'], indirect=True)
@pytest.mark.parametrize('width', [320, 1366])
def test_monitoring_uses_shared_chrome_and_keyboard_navigation(monitoring_backend, monitoring_page, width):
    from playwright.sync_api import expect

    page = monitoring_page
    page.set_viewport_size({'width': width, 'height': 844})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(monitoring_backend.origin + '/', wait_until='domcontentloaded')
    expect(page.get_by_role('link', name='Rosy Monitoring 홈')).to_have_attribute('href', '#main')
    expect(page.locator('main')).to_have_class('ui-task-page')
    expect(page.locator('main h1')).to_have_text('시스템 상태')
    page.locator('.skip-link').focus()
    page.keyboard.press('Enter')
    expect(page.locator('main')).to_be_focused()
    page.locator('[data-theme-cycle]').click()
    expect(page.locator('html')).to_have_attribute('data-theme', 'light')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert not errors, errors


@pytest.mark.parametrize('monitoring_backend', ['web'], indirect=True)
@pytest.mark.parametrize('width', [320, 390, 1366, 1920])
def test_actual_status_ui_is_scoped_responsive_and_read_only(monitoring_backend, monitoring_page, width):
    from playwright.sync_api import expect
    page = monitoring_page
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.set_viewport_size({'width': width, 'height': 844 if width < 600 else 1080})
    page.goto(monitoring_backend.origin + '/')
    login(page, KEY_A)
    expect(page.locator('#observation-rows')).to_contain_text('host-a')
    expect(page.locator('#observation-rows')).not_to_contain_text('host-b')
    expect(page.locator('#graph .edge')).to_have_count(1)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert KEY_A not in page.content() and 'private owner detail' not in page.content()
    assert page.evaluate('Object.values(localStorage).every(value => !value.includes("a".repeat(32)))')
    page.get_by_role('button', name='로그아웃', exact=True).click()
    expect(page.locator('#observation-rows')).to_be_empty()
    expect(page.get_by_label('조회 키', exact=True)).to_have_value('')
    assert errors == []


@pytest.mark.parametrize('monitoring_backend', ['web'], indirect=True)
def test_api_outage_expires_previous_evidence_in_the_actual_ui(monitoring_backend, monitoring_page):
    from playwright.sync_api import expect
    page = monitoring_page
    page.goto(monitoring_backend.origin + '/')
    login(page, KEY_A)
    expect(page.locator('#observation-rows [data-evidence=fresh]')).to_have_count(1)
    monitoring_backend.server.should_exit = True
    monitoring_backend.worker.join(10)
    expect(page.locator('#connection-status')).to_contain_text('조회 연결 끊김', timeout=12000)
    expect(page.locator('#observation-rows [data-evidence=fresh]')).to_have_count(0)
    capture(page, 'api-disconnected')


@pytest.mark.parametrize('monitoring_backend', ['xss'], indirect=True)
def test_labels_are_text_and_an_old_authenticated_response_cannot_cross_logout(monitoring_backend, monitoring_page):
    from playwright.sync_api import expect
    page = monitoring_page
    page.add_init_script('''window.AbortController = class extends AbortController { abort() {} };''')
    page.goto(monitoring_backend.origin + '/')
    monitoring_backend.slow.key = 'Bearer ' + KEY_A
    login(page, KEY_A)
    assert monitoring_backend.slow.entered.wait(5)
    page.get_by_role('button', name='로그아웃', exact=True).click()
    login(page, KEY_B)
    expect(page.locator('#observation-rows')).to_contain_text('host-b')
    expect(page.locator('#observation-rows')).to_contain_text('<img src=x onerror=window.monitoringInjected=1>')
    monitoring_backend.slow.release.set()
    page.wait_for_timeout(300)
    expect(page.locator('#observation-rows')).not_to_contain_text('host-a')
    expect(page.locator('#observation-rows img')).to_have_count(0)
    assert page.evaluate('window.monitoringInjected') is None


VIEWPORTS = [(320, 844), (390, 844), (1366, 768), (1920, 1080)]


def capture(page, state):
    directory = os.environ.get('ROSY_MONITORING_CAPTURE_DIR')
    for theme in ('dark', 'light'):
        page.evaluate('(theme) => RosyTheme.set(theme)', theme)
        for width, height in VIEWPORTS:
            page.set_viewport_size({'width': width, 'height': height})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            if directory:
                root = Path(directory).expanduser()
                root.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(root / f'{state}-{width}x{height}-{theme}.png'), full_page=True)


@pytest.mark.parametrize('monitoring_backend', ['web', 'delayed', 'unavailable', 'empty', 'error', 'disconnected'], indirect=True)
def test_declared_g2_evidence_states_use_the_actual_backend(monitoring_backend, monitoring_page, request):
    from playwright.sync_api import expect
    mode = request.node.callspec.params['monitoring_backend']
    page = monitoring_page
    page.goto(monitoring_backend.origin + '/')
    if mode == 'web':
        capture(page, 'startup')
        login(page, 'x' * 32)
        expect(page.locator('#connection-status')).to_contain_text('조회 키를 확인하세요.')
        capture(page, 'auth-denied')
    login(page, KEY_A)
    if mode == 'empty':
        expect(page.locator('#node-empty')).to_be_visible()
    elif mode == 'disconnected':
        expect(page.locator('#observation-rows [data-evidence=fresh]')).to_have_count(1)
        monitoring_backend.paths['a'].unlink()
        expect(page.locator('#observation-rows [data-evidence=disconnected]')).to_have_count(1, timeout=22000)
    else:
        expected = {'web': 'fresh', 'error': 'fresh', 'delayed': 'delayed', 'unavailable': 'unavailable'}[mode]
        expect(page.locator(f'#observation-rows [data-evidence={expected}]')).to_have_count(1)
        if mode == 'delayed':
            expect(page.locator('#observation-rows [data-evidence=delayed]')).to_contain_text('초 전')
        if mode == 'error':
            expect(page.locator('#observation-rows .danger')).to_contain_text('오류')
    capture(page, 'fresh' if mode == 'web' else mode)
    if mode == 'web':
        # A modified selector still goes through the real server's scope boundary.
        page.locator('#scope-select').evaluate("select => select.add(new Option('site-b', 'site-b'))")
        page.locator('#scope-select').select_option('site-b')
        expect(page.locator('#connection-status')).to_contain_text('허용된 사이트를 확인하세요.')
        expect(page.locator('#observation-rows')).to_be_empty()
        capture(page, 'scope-denied')


@pytest.mark.parametrize('monitoring_backend', ['account'], indirect=True)
def test_account_session_opens_the_screen_without_a_key(monitoring_backend, monitoring_page):
    from playwright.sync_api import expect
    page, account = monitoring_page, monitoring_backend.account
    status, workspace = page.locator('#connection-status'), page.locator('#workspace')
    page.goto(monitoring_backend.origin + '/')
    expect(page.locator('#account-login')).to_be_visible()
    expect(page.locator('#reader-key')).to_be_hidden()  # the emergency key stays folded
    expect(workspace).to_be_hidden()

    page.context.add_cookies([{'name': 'rosy_monitoring_account', 'value': 'good', 'url': monitoring_backend.origin}])
    account.capabilities = ['fleet.read']
    page.reload()
    expect(status).to_contain_text('권한이 없습니다')
    expect(workspace).to_be_hidden()
    expect(page.locator('#account-login')).to_be_hidden()

    account.capabilities = ['monitoring.read']
    page.reload()
    expect(workspace).to_be_visible()
    expect(page.locator('#login')).to_be_hidden()
    expect(status).to_contain_text('자료 수신')
    apps = page.locator('[data-account-apps]')
    apps.locator('summary').click()
    expect(apps.get_by_role('link', name='관제')).to_have_attribute('href', 'https://site.example.test/console')
    page.wait_for_timeout(11000)  # one session poll must not overwrite the read status
    expect(apps.get_by_role('link', name='관제')).to_be_visible()  # nor close the open menu
    expect(status).to_contain_text('자료 수신')

    page.locator('#logout').click()
    expect(page.locator('#account-login')).to_be_visible()
    expect(workspace).to_be_hidden()
    assert account.logged_out == ['good']

    # A session that ends while reading returns to the login button, not to a key-only dead end.
    account.capabilities = ['monitoring.read']
    page.reload()
    expect(workspace).to_be_visible()
    account.capabilities = None
    expect(page.locator('#account-login')).to_be_visible(timeout=20000)

    # With Account unreachable the emergency key opens instead of a dead login button.
    page.route('**/api/monitoring/v1/account/session', lambda route: route.fulfill(status=503, body='{}'))
    page.reload()
    expect(status).to_contain_text('연결할 수 없습니다')
    expect(page.locator('#reader-key')).to_be_visible()
    page.locator('#reader-key').fill(KEY_A)
    page.wait_for_timeout(11000)  # a later failed poll must not fold the field being typed in
    expect(page.locator('#reader-key')).to_have_value(KEY_A)
    expect(page.locator('#reader-key')).to_be_visible()


@pytest.mark.parametrize('monitoring_backend', ['prefix'], indirect=True)
def test_prefixed_ui_assets_do_not_depend_on_fleet_common_routes(monitoring_backend, monitoring_page):
    from playwright.sync_api import expect
    page = monitoring_page
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(monitoring_backend.origin + '/monitoring/')
    login(page, KEY_A)
    expect(page.locator('#observation-rows')).to_contain_text('host-a')
    assert errors == []
