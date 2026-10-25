"""Real Chromium reads the independent Monitoring backend; never intercept its API."""

import json
import asyncio
import os
from pathlib import Path
import shutil
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


@pytest.fixture
def monitoring_backend(tmp_path, request):
    from rosy.monitoring.config import MonitoringConfig, load_credentials
    from rosy.monitoring.service import Collector, create_app
    from rosy.monitoring.store import MonitoringStore

    mode = getattr(request, 'param', None)
    web_root = None
    if mode in {'web', 'xss', 'delayed', 'unavailable', 'empty', 'error', 'disconnected', 'prefix'}:
        web_root = tmp_path / 'web'
        (web_root / 'common').mkdir(parents=True)
        for name in ('index.html', 'monitoring.css', 'monitoring.js'):
            source = ROOT / 'applications/monitoring/web' / name
            assert source.is_file(), f'Monitoring UI asset missing: {name}'
            shutil.copy2(source, web_root / name)
        for name in ('tokens.css', 'components.css', 'app-shell.css', 'theme.js', 'core_ui_logic.js'):
            shutil.copy2(ROOT / 'shared/web' / name, web_root / 'common' / name)
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
    app = create_app(collector, web_root=web_root)
    slow = SimpleNamespace(key=None, entered=threading.Event(), release=threading.Event())
    @app.middleware('http')
    async def delayed_actual_response(request, call_next):
        response = await call_next(request)
        if (request.url.path == '/api/monitoring/v1/snapshot'
                and request.headers.get('authorization') == slow.key and not slow.entered.is_set()):
            slow.entered.set()
            until = time.monotonic() + 10
            while not slow.release.is_set() and time.monotonic() < until:
                await asyncio.sleep(0.01)
        return response
    listener = safe_listener()
    origin = f'http://127.0.0.1:{listener.getsockname()[1]}'
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
                                         proxy_headers=False, timeout_graceful_shutdown=3))
    worker = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        yield SimpleNamespace(origin=origin, server=server, worker=worker, collector=collector,
                              paths=paths, slow=slow)
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
    for width, height in VIEWPORTS:
        page.set_viewport_size({'width': width, 'height': height})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        if directory:
            root = Path(directory).expanduser()
            root.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(root / f'{state}-{width}x{height}.png'), full_page=True)


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
