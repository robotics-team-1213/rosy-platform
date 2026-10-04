"""D-439 authentication entry uses real CORE assets without operational clients."""
import importlib.util
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[4]
pytestmark = pytest.mark.skipif(os.environ.get('ROSY_RUN_BROWSER_TESTS') != '1', reason='optional Chromium')


@pytest.fixture
def entry(tmp_path):
    spec = importlib.util.spec_from_file_location('entry_core_fixture', Path(__file__).with_name('test_role_g2_browser.py'))
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    client = fixture._core_client(tmp_path)
    asset_responses = {}
    state = {'identity': {'role': 'operator', 'source': 'manual', 'label': 'fixture'},
             'surfaces': [{'id': 'console', 'title': '운용'}, {'id': 'setup', 'title': '작업 준비'}],
             'whoami_status': 200, 'manifest_status': 200, 'pair_status': 201, 'logout_status': 409,
             'state_status': 200, 'stop_status': 200, 'network_error': False,
             'pair_expiry': '2099-01-01T00:00:00Z', 'calls': [], 'assets': [], 'errors': []}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1366, 'height': 768})
        page.set_default_timeout(10_000)
        page.set_default_navigation_timeout(30_000)
        page.on('pageerror', lambda error: state['errors'].append(str(error)))
        page.add_init_script("window.entrySockets=0;window.WebSocket=class {constructor(){window.entrySockets++;throw new Error('entry must not open sockets')}};")

        def serve(route):
            request = route.request
            path = urlparse(request.url).path
            if path.startswith('/api/'):
                body = json.loads(request.post_data) if request.post_data else None
                state['calls'].append((request.method, path, body))
                status, payload = 200, {}
                if path == '/api/v1/auth/whoami':
                    if state['network_error']:
                        route.abort('failed')
                        return
                    status, payload = state['whoami_status'], state['identity']
                elif path == '/api/v1/ui/surfaces/console':
                    status, payload = state['manifest_status'], state.get('manifest_payload', {'surfaces': state['surfaces']})
                elif path == '/api/v1/auth/pair':
                    status, payload = state['pair_status'], {'token': 'fixture-paired', 'role': 'operator', 'source': 'pair-physical',
                                            'expires_at': state['pair_expiry']}
                elif path == '/api/v1/auth/logout':
                    status, payload = state['logout_status'], {'error': {'message': 'manual token'}}
                elif path == '/api/v1/robot/state':
                    status, payload = state['state_status'], {'mode': 'SAFE_STOP', 'safety': {'estop': True}}
                elif path == '/api/v1/safety/stop':
                    status = state['stop_status']
                else:
                    status, payload = 404, {'error': {'message': 'unconfigured operational API'}}
                if status >= 400 and 'error' not in payload:
                    payload = {'error': {'message': 'fixture rejection'}}
                route.fulfill(status=status, content_type='application/json', body=json.dumps(payload))
            elif path in ('/console', '/setup', '/device'):
                route.fulfill(content_type='text/html', body=f'<html lang="ko"><body data-destination="{path}"></body></html>')
            else:
                state['assets'].append(path)
                if path not in asset_responses:
                    asset_responses[path] = client.get(path)
                response = asset_responses[path]
                headers = {key: value for key, value in response.headers.items()
                           if key.lower() not in ('content-encoding', 'content-length')}
                route.fulfill(status=response.status_code, headers=headers, body=response.content)

        page.route('**/*', serve)
        yield page, state
        browser.close()
    client.close()


def _open(page, token='fixture-manual', suffix=''):
    if token:
        page.add_init_script(f"sessionStorage.setItem('rosy.dashboard.token', {json.dumps(token)});")
    page.goto('http://rosy.test/dashboard' + suffix, wait_until='domcontentloaded')
    expect(page.locator('#entry-shell')).to_have_attribute('data-ready', 'true')


def test_entry_loads_only_identity_and_destinations_with_stop_on_demand(entry):
    page, state = entry
    _open(page)
    expect(page.get_by_role('navigation', name='작업 화면')).to_be_visible()
    expect(page.get_by_role('link', name='작업 준비', exact=True)).to_be_visible()
    assert [(method, path) for method, path, _ in state['calls']] == [
        ('GET', '/api/v1/auth/whoami'), ('GET', '/api/v1/ui/surfaces/console')]
    assert page.evaluate('window.entrySockets') == 0
    assert not any(path.endswith(('/app.js', '/vision.js', '/state-socket.js', '/teleop.js')) for path in state['assets'])
    for width in (320, 390):
        page.set_viewport_size({'width': width, 'height': 844})
        brand = page.locator('#entry-shell ui-brand').bounding_box()
        role = page.locator('#entry-role').bounding_box()
        stop_box = page.locator('#entry-stop').bounding_box()
        assert role['x'] >= brand['x'] + brand['width']
        assert stop_box['x'] >= role['x'] + role['width'] - 1
        assert stop_box['x'] + stop_box['width'] <= width
        assert page.evaluate('document.documentElement.scrollWidth-innerWidth') == 0
    stop = page.get_by_role('button', name='비상 정지', exact=True)
    expect(stop).to_be_enabled()
    stop.click()
    expect(page.locator('#entry-stop-notice')).to_contain_text('CORE 정지 상태 확인')
    assert state['calls'][-2:] == [('POST', '/api/v1/safety/stop', None), ('GET', '/api/v1/robot/state', None)]
    assert state['errors'] == []
    assert page.locator('[data-state-missing]').count() == 0


def test_entry_invalid_session_clears_links_but_manifest_error_retries(entry):
    page, state = entry
    state['whoami_status'] = 401
    _open(page)
    expect(page.locator('#auth-drawer')).to_be_visible()
    expect(page.locator('#entry-status')).to_contain_text('다시 로그인')
    assert page.evaluate("sessionStorage.getItem('rosy.dashboard.token')") is None
    expect(page.get_by_role('button', name='비상 정지', exact=True)).to_be_disabled()
    assert page.get_by_role('navigation', name='작업 화면').get_by_role('link').count() == 0
    state['whoami_status'], state['manifest_status'] = 200, 503
    page.get_by_role('tab', name='API 토큰', exact=True).click()
    page.locator('#token-input').fill('fixture-manual')
    page.locator('#auth-form').get_by_role('button', name='연결', exact=True).click()
    expect(page.locator('#entry-status')).to_contain_text('화면 목록')
    assert page.evaluate("sessionStorage.getItem('rosy.dashboard.token')") == 'fixture-manual'
    state['manifest_status'] = 200
    page.get_by_role('button', name='화면 목록 다시 불러오기').click()
    expect(page.get_by_role('link', name='운용', exact=True)).to_be_visible()
    assert state['errors'] == []


def test_entry_code_pairing_and_local_logout_use_existing_credential_helpers(entry):
    page, state = entry
    _open(page, token='')
    expect(page.locator('#auth-drawer')).to_be_visible()
    assert state['calls'] == []
    page.locator('#code-input').fill('ABCD-EFGH')
    page.locator('#code-label').fill('fixture tablet')
    page.locator('#code-remember').check()
    page.locator('#code-submit').click()
    expect(page.get_by_role('navigation', name='작업 화면')).to_be_visible()
    assert state['calls'][0] == ('POST', '/api/v1/auth/pair', {'code': 'ABCDEFGH', 'label': 'fixture tablet'})
    # A response beyond seven days may never become a remembered browser token.
    assert page.evaluate("localStorage.getItem('rosy.dashboard.paired')") is None
    assert page.evaluate("sessionStorage.getItem('rosy.dashboard.token')") == 'fixture-paired'
    page.get_by_role('button', name='이 브라우저에서 잊기', exact=True).click()
    expect(page.locator('#auth-drawer')).to_be_visible()
    assert any(path == '/api/v1/auth/logout' and method == 'POST' for method, path, _ in state['calls'])
    assert page.evaluate("sessionStorage.getItem('rosy.dashboard.token')") is None
    assert state['errors'] == []


def test_entry_filters_destinations_and_requires_manifest_permission_for_return(entry):
    page, state = entry
    state['surfaces'] = [{'id': 'console', 'title': '운용'}, {'id': '../device', 'title': 'invalid'}]
    _open(page, suffix='?return_to=%2Fdevice')
    expect(page.get_by_role('link', name='운용', exact=True)).to_be_visible()
    assert page.url.endswith('return_to=%2Fdevice')
    assert page.get_by_role('link', name='invalid', exact=True).count() == 0
    state['surfaces'] = []
    page.reload(wait_until='domcontentloaded')
    expect(page.locator('#entry-status')).to_contain_text('허용된 작업 화면이 없습니다')
    state['surfaces'] = [{'id': 'setup', 'title': '작업 준비'}]
    page.goto('http://rosy.test/dashboard?return_to=%2Fsetup', wait_until='domcontentloaded')
    page.wait_for_function("() => document.body.dataset.destination === '/setup'")


def test_entry_compact_auth_keyboard_and_themes(entry):
    page, state = entry
    _open(page, token='')
    for width, theme in ((320, 'dark'), (390, 'light')):
        page.set_viewport_size({'width': width, 'height': 844})
        page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
        page.get_by_role('tab', name='로봇 화면 코드', exact=True).focus()
        page.keyboard.press('ArrowRight')
        expect(page.get_by_role('tab', name='API 토큰', exact=True)).to_have_attribute('aria-selected', 'true')
        expect(page.locator('#token-input')).to_be_focused()
        page.get_by_role('tab', name='로봇 화면 코드', exact=True).click()
        assert page.evaluate('document.documentElement.scrollWidth-innerWidth') == 0
        stop = page.get_by_role('button', name='비상 정지', exact=True)
        expect(stop).to_be_visible()
        assert stop.bounding_box()['y'] < 120
    assert state['errors'] == []
    assert page.locator('[data-state-missing]').count() == 0


def test_entry_remembers_only_expiring_paired_login_and_revokes_on_logout(entry):
    page, state = entry
    state['pair_expiry'] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    state['identity'].update(source='pair-physical', expires_at=state['pair_expiry'])
    state['logout_status'] = 200
    _open(page, token='')
    page.locator('#code-input').fill('ABCD')
    page.locator('#code-submit').click()
    expect(page.locator('#code-message')).to_contain_text('8자')
    assert state['calls'] == []
    page.locator('#code-input').fill('ABCD-EFGH')
    page.locator('#code-remember').check()
    page.locator('#code-submit').click()
    expect(page.get_by_role('navigation', name='작업 화면')).to_be_visible()
    saved = page.evaluate("JSON.parse(localStorage.getItem('rosy.dashboard.paired'))")
    assert saved == {'token': 'fixture-paired', 'expires_at': state['pair_expiry']}
    page.get_by_role('button', name='로그아웃', exact=True).click()
    expect(page.locator('#entry-status')).to_contain_text('로그아웃했습니다')
    assert page.evaluate("localStorage.getItem('rosy.dashboard.paired')") is None


def test_entry_network_retry_preserves_key_and_stop_ack_does_not_invent_readback(entry):
    page, state = entry
    state['network_error'] = True
    _open(page)
    expect(page.locator('#entry-status')).to_contain_text('로그인을 확인하지 못했습니다')
    assert page.evaluate("sessionStorage.getItem('rosy.dashboard.token')") == 'fixture-manual'
    state['network_error'] = False
    state['identity']['role'] = 'new_server_role'
    page.get_by_role('button', name='화면 목록 다시 불러오기').click()
    expect(page.locator('#entry-role')).to_have_text('new_server_role')
    state['state_status'] = 503
    page.get_by_role('button', name='비상 정지', exact=True).click()
    expect(page.locator('#entry-stop-notice')).to_contain_text('상태 확인 불가')
    state['stop_status'] = 503
    page.get_by_role('button', name='비상 정지', exact=True).click()
    expect(page.locator('#entry-stop-notice')).to_contain_text('비상 정지 실패')
    assert not any(path.endswith('/reset') for _, path, _ in state['calls'])
    assert page.evaluate('window.entrySockets') == 0


def test_entry_expiry_returns_to_authentication_without_operational_poll(entry):
    page, state = entry
    now = datetime(2026, 10, 4, tzinfo=timezone.utc)
    page.clock.install(time=now)
    state['identity']['expires_at'] = (now + timedelta(minutes=1)).isoformat()
    _open(page)
    expect(page.get_by_role('navigation', name='작업 화면')).to_be_visible()
    calls = len(state['calls'])
    page.clock.fast_forward(60_001)
    expect(page.locator('#entry-status')).to_contain_text('만료되었습니다')
    expect(page.locator('#auth-drawer')).to_be_visible()
    expect(page.get_by_role('button', name='비상 정지', exact=True)).to_be_disabled()
    assert page.evaluate("sessionStorage.getItem('rosy.dashboard.token')") is None
    assert len(state['calls']) == calls


def test_entry_malformed_manifest_is_recoverable_error_not_permission_empty(entry):
    page, state = entry
    state['manifest_payload'] = {}
    _open(page)
    for payload in ({}, []):
        state['manifest_payload'] = payload
        page.reload(wait_until='domcontentloaded')
        expect(page.locator('#entry-status')).to_contain_text('화면 목록을 받지 못했습니다')
        expect(page.locator('#entry-retry')).to_be_visible()
        assert '허용된 작업 화면이 없습니다' not in page.locator('#entry-status').inner_text()
    state.pop('manifest_payload')
    state['surfaces'] = []
    page.get_by_role('button', name='화면 목록 다시 불러오기').click()
    expect(page.locator('#entry-status')).to_contain_text('허용된 작업 화면이 없습니다')


def test_entry_malformed_identity_cannot_enable_stop_and_unknown_string_role_retries(entry):
    page, state = entry
    state['identity'] = {}
    _open(page)
    for identity in ({}, {'role': None}, {'role': ['operator']}, {'role': 3}, {'role': ' '}):
        state['identity'] = identity
        page.reload(wait_until='domcontentloaded')
        expect(page.locator('#entry-status')).to_contain_text('로그인을 확인하지 못했습니다')
        expect(page.locator('#entry-stop')).to_be_disabled()
        expect(page.locator('#auth-drawer')).to_be_visible()
        assert page.locator('#entry-navigation a').count() == 0
    state['identity'] = {'role': 'new_server_role', 'source': 'manual'}
    page.get_by_role('button', name='화면 목록 다시 불러오기').click()
    expect(page.locator('#entry-role')).to_have_text('new_server_role')
    expect(page.locator('#entry-stop')).to_be_enabled()
    expect(page.get_by_role('navigation', name='작업 화면')).to_be_visible()


def test_entry_pair_timeout_releases_controls_and_never_saves_late_adapter_key(entry):
    page, state = entry
    _open(page, token='')
    page.evaluate("""() => {
      window.entryFetch = window.fetch;
      window.fetch = (input, options) => String(input).endsWith('/auth/pair')
        ? new Promise(resolve => options.signal.addEventListener('abort', () => resolve(new Response(
          JSON.stringify({token:'late-adapter-key',role:'operator'}), {status:201})), {once:true}))
        : window.entryFetch(input, options);
    }""")
    page.locator('#code-input').fill('ABCD-EFGH')
    page.locator('#code-submit').click()
    expect(page.locator('#code-submit')).to_be_disabled()
    expect(page.locator('#code-message')).to_contain_text('시간이 지났습니다', timeout=15_000)
    expect(page.locator('#code-submit')).to_be_enabled()
    assert page.evaluate("sessionStorage.getItem('rosy.dashboard.token')") is None
    assert page.evaluate("localStorage.getItem('rosy.dashboard.paired')") is None
    page.evaluate('window.fetch = window.entryFetch')
    page.locator('#code-submit').click()
    expect(page.get_by_role('navigation', name='작업 화면')).to_be_visible()


def test_entry_real_pair_fetch_abort_preserves_timeout_reason_for_retry(entry):
    page, state = entry
    _open(page, token='')
    page.evaluate("""() => {
      window.entryFetch = window.fetch;
      window.fetch = (input, options) => String(input).endsWith('/auth/pair')
        ? new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => reject(options.signal.reason), {once:true}))
        : window.entryFetch(input, options);
    }""")
    page.locator('#code-input').fill('ABCD-EFGH')
    page.locator('#code-submit').click()
    expect(page.locator('#code-message')).to_contain_text('코드 확인 시간이 지났습니다', timeout=15_000)
    expect(page.locator('#code-submit')).to_be_enabled()
    assert page.evaluate("sessionStorage.getItem('rosy.dashboard.token')") is None
    page.evaluate('window.fetch = window.entryFetch')
    page.locator('#code-submit').click()
    expect(page.get_by_role('navigation', name='작업 화면')).to_be_visible()


def test_entry_logout_timeout_keeps_uncertain_key_and_allows_retry(entry):
    page, state = entry
    _open(page)
    expect(page.get_by_role('navigation', name='작업 화면')).to_be_visible()
    page.evaluate("""() => {
      window.entryFetch = window.fetch;
      window.fetch = (input, options) => String(input).endsWith('/auth/logout')
        ? new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => reject(options.signal.reason), {once:true}))
        : window.entryFetch(input, options);
    }""")
    logout_button = page.get_by_role('button', name='이 브라우저에서 잊기', exact=True)
    logout_button.click()
    expect(logout_button).to_be_disabled()
    expect(page.locator('#entry-status')).to_contain_text('로그아웃하지 못했습니다', timeout=15_000)
    expect(logout_button).to_be_enabled()
    assert page.evaluate("sessionStorage.getItem('rosy.dashboard.token')") == 'fixture-manual'
    page.evaluate('window.fetch = window.entryFetch')
    logout_button.click()
    expect(page.locator('#auth-drawer')).to_be_visible()
    assert page.evaluate("sessionStorage.getItem('rosy.dashboard.token')") is None


def test_entry_old_stop_ack_cannot_fetch_state_with_expired_session(entry):
    page, state = entry
    now = datetime(2026, 10, 4, tzinfo=timezone.utc)
    page.clock.install(time=now)
    state['identity']['expires_at'] = (now + timedelta(minutes=1)).isoformat()
    _open(page)
    expect(page.get_by_role('navigation', name='작업 화면')).to_be_visible()
    page.evaluate("""() => {
      const fetch = window.fetch;
      window.oldStopReadbackTokens = [];
      window.fetch = (input, options) => {
        if (String(input).endsWith('/robot/state')) window.oldStopReadbackTokens.push(options.headers.Authorization);
        if (!String(input).endsWith('/safety/stop')) return fetch(input, options);
        return new Promise(resolve => window.releaseOldStop = () => {
          const response = new Response('{}', {status:200});
          const json = response.json.bind(response);
          response.json = async () => { const body = await json(); window.oldStopDecoded = true; return body; };
          resolve(response);
        });
      };
    }""")
    page.get_by_role('button', name='비상 정지', exact=True).click()
    page.clock.fast_forward(60_001)
    expect(page.locator('#entry-status')).to_contain_text('만료되었습니다')
    state['identity']['expires_at'] = (now + timedelta(minutes=5)).isoformat()
    page.get_by_role('tab', name='API 토큰', exact=True).click()
    page.locator('#token-input').fill('fixture-new-token')
    page.locator('#auth-form').get_by_role('button', name='연결', exact=True).click()
    expect(page.get_by_role('navigation', name='작업 화면')).to_be_visible()
    page.evaluate('window.releaseOldStop()')
    page.wait_for_function('() => window.oldStopDecoded === true')
    assert page.evaluate('window.oldStopReadbackTokens') == []
    assert not any(path == '/api/v1/robot/state' for _, path, _ in state['calls'])
    expect(page.locator('#entry-stop-notice')).to_be_hidden()
