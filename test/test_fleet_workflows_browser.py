"""D-439 Fleet task navigation, discovery recovery and owned stage geometry."""
import os
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from browser_harness import browser_tests_enabled

from test_fleet_console_browser import API, _open_console as _open_base, _open_token_access, console_url  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(),
                                reason='optional Chromium regression')


def _open_console(*args, **kwargs):
    browser, page, errors = _open_base(*args, **kwargs)
    # A served mutation outside the checkout proves the guard without changing the product file.
    if candidate := os.environ.get('ROSY_FLEET_MUTATION_ASSET'):
        asset = Path(candidate).resolve()
        assert not asset.is_relative_to(Path(__file__).resolve().parents[1])
        assert asset.name in {'install.js', 'vision-view.js'}
        body = asset.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        def deliver(route):
            route.fulfill(status=200, content_type='text/javascript', body=body)
            asset.with_suffix('.delivery.json').write_text(json.dumps({
                'requested_url': route.request.url, 'fulfilled_sha256': digest,
                'asset': str(asset), 'bytes': len(body)}), encoding='utf-8')
        page.route('**/console/assets/' + asset.name, deliver)
    return browser, page, errors


def test_mutation_assets_stay_outside_checkout(tmp_path, monkeypatch):
    routes = []
    page = SimpleNamespace(route=lambda pattern, callback: routes.append(pattern))
    monkeypatch.setitem(_open_console.__globals__, '_open_base', lambda: (None, page, []))
    asset = tmp_path / 'install.js'
    asset.write_text('// isolated mutation', encoding='utf-8')
    monkeypatch.setenv('ROSY_FLEET_MUTATION_ASSET', str(asset))
    assert _open_console()[1] is page
    assert routes == ['**/console/assets/install.js']

    inside = Path(__file__).resolve().parents[1] / 'install.js'
    monkeypatch.setenv('ROSY_FLEET_MUTATION_ASSET', str(inside))
    with pytest.raises(AssertionError):
        _open_console()
    assert len(routes) == 1


def install_url(console):
    return console.rsplit('/', 1)[0] + '/install.html'


def choose(page, title):
    tab = page.get_by_role('tab', name=title, exact=True)
    if tab.is_visible():
        tab.click()
    else:
        page.get_by_role('combobox', name='작업 선택').select_option(label=title)


def _approved_robot_peer(**changes):
    return dict({'peer_id': 'rosy_01', 'name': 'robot-one', 'role': 'robot',
                 'transport': 'https', 'hostname': 'robot-one.local', 'address': None,
                 'port': 8443, 'approval': 'approved', 'provenance': 'approved-directory',
                 'freshness': 'unavailable', 'readiness': 'unknown'}, **changes)


@pytest.mark.parametrize('viewport', [(390, 844), (1200, 800), (1366, 768)])
def test_robot_app_links_preserve_approved_target_without_dispatch(console_url, viewport):
    from playwright.sync_api import sync_playwright, expect

    api = {**API, '/api/fleet/peers': {'peers': [_approved_robot_peer()]}}
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, api)
        page.set_viewport_size({'width': viewport[0], 'height': viewport[1]})
        writes = []
        page.on('request', lambda request: writes.append(request.url)
                if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') else None)
        page.goto(console_url + '?robot=rosy_01', wait_until='networkidle')
        card = page.locator('#robot-workspace article[data-robot-id="rosy_01"]')
        expect(card.get_by_role('link', name='Rosy Robot · 한 대 관리')).to_have_attribute(
            'href', 'https://robot-one.local:8443/console')
        pilot = card.get_by_role('link', name='Rosy Pilot · 직접 운전')
        expect(pilot).to_have_attribute('href', 'https://robot-one.local:8443/pilot')
        expect(pilot).to_be_visible()
        expect(page.locator('#estop')).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        # Switching apps is ordinary navigation; the target handles its own login/admission.
        page.route('https://robot-one.local:8443/pilot', lambda route: route.fulfill(
            status=200, content_type='text/html', body='<h1>Pilot target</h1>'))
        pilot.click()
        expect(page).to_have_url('https://robot-one.local:8443/pilot')
        assert not [url for url in writes if '/teleop' in url or '/mission' in url or '/goal' in url]
        assert not errors
        browser.close()


@pytest.mark.parametrize('changes', [
    {'approval': 'unapproved'}, {'freshness': 'conflict'}, {'freshness': 'expired'},
    {'peer_id': 'rosy_02'}, {'transport': 'javascript'},
    {'provenance': 'mdns', 'freshness': 'fresh', 'transport': 'http', 'port': 9999},
    {'hostname': 'user@evil.example'}, {'hostname': 'evil.example/path'},
])
def test_untrusted_robot_target_has_guidance_instead_of_app_links(console_url, changes):
    from playwright.sync_api import sync_playwright, expect

    api = {**API, '/api/fleet/peers': {'peers': [_approved_robot_peer(**changes)]}}
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, api)
        page.goto(console_url + '?robot=rosy_01', wait_until='networkidle')
        card = page.locator('#robot-workspace article[data-robot-id="rosy_01"]')
        expect(card.locator('[data-robot-app-guidance]')).to_contain_text('승인된 로봇 주소')
        expect(card.locator('[data-robot-app]')).to_have_count(0)
        assert not errors
        browser.close()


def test_robot_app_links_clear_when_directory_becomes_unavailable(console_url):
    from playwright.sync_api import sync_playwright, expect

    api = {**API, '/api/fleet/peers': {'peers': [_approved_robot_peer()]}}
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, api)
        page.goto(console_url + '?robot=rosy_01', wait_until='networkidle')
        links = page.locator('#robot-workspace [data-robot-app]')
        expect(links).to_have_count(2)
        api['/api/fleet/peers'] = (503, {'detail': 'directory unavailable'})
        expect(links).to_have_count(0, timeout=12_000)
        expect(page.locator('[data-robot-app-guidance]')).to_be_visible()
        assert not errors
        browser.close()


def test_robot_app_links_drop_previous_users_directory_before_new_response(console_url):
    from playwright.sync_api import sync_playwright, expect

    api = {**API, '/api/fleet/peers': {'peers': [_approved_robot_peer()]}}
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, api)
        page.goto(console_url + '?robot=rosy_01', wait_until='networkidle')
        links = page.locator('#robot-workspace [data-robot-app]')
        expect(links).to_have_count(2)
        # Hold the next user's directory response: old links must disappear immediately.
        waiting = []
        page.route('**/api/fleet/peers', lambda route: waiting.append(route))
        _open_token_access(page)
        page.locator('#console-token').fill('next-user-token')
        with page.expect_request('**/api/fleet/peers'):
            page.locator('#token-save').click()
        expect(links).to_have_count(0)
        page.locator('#robot-choice').select_option('rosy_01')
        expect(page.locator('[data-robot-app-guidance]')).to_be_visible()
        for route in waiting:
            route.fulfill(json={'peers': []})
        assert not errors
        browser.close()


def test_bfcache_return_clears_app_directory_before_session_is_revalidated(console_url):
    from playwright.sync_api import sync_playwright, expect

    api = {**API, '/api/fleet/peers': {'peers': [_approved_robot_peer()]}}
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, api)
        page.goto(console_url + '?robot=rosy_01', wait_until='networkidle')
        links = page.locator('#robot-workspace [data-robot-app]')
        expect(links).to_have_count(2)
        waiting = []
        page.route('**/api/fleet/session', lambda route: waiting.append(route))
        page.evaluate('''() => {
          dispatchEvent(new PageTransitionEvent('pagehide', {persisted: true}));
          dispatchEvent(new PageTransitionEvent('pageshow', {persisted: true}));
        }''')
        # Existing page cleanup drops selection; reselecting must not revive the old directory.
        page.locator('#robot-choice').select_option('rosy_01')
        expect(links).to_have_count(0)
        for route in waiting:
            route.fulfill(status=401, json={'detail': {'code': 'TOKEN_REQUIRED'}})
        assert not errors
        browser.close()


@pytest.mark.parametrize('peers', [
    [None],
    [_approved_robot_peer(), _approved_robot_peer(hostname='other.local')],
    [_approved_robot_peer(), _approved_robot_peer(freshness='conflict')],
])
def test_malformed_or_ambiguous_directory_never_selects_a_robot_app(console_url, peers):
    from playwright.sync_api import sync_playwright, expect

    api = {**API, '/api/fleet/peers': {'peers': peers}}
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, api)
        page.goto(console_url + '?robot=rosy_01', wait_until='networkidle')
        expect(page.locator('[data-robot-app-guidance]')).to_be_visible()
        expect(page.locator('[data-robot-app]')).to_have_count(0)
        assert not errors
        browser.close()


def test_install_tasks_stay_mounted_and_navigate_while_role_locked(console_url):
    from playwright.sync_api import sync_playwright, expect

    api = {**API, '/api/fleet/session': {'principal_id': 'installer', 'role': 'operator'},
           '/api/fleet/enrollment/robots': {'available': True, 'robots': [], 'identity': {}},
           '/api/fleet/discovery': {'scanner_online': True, 'devices': []},
           '/api/fleet/device-profiles': {'profiles': []}}
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, api)
        page.goto(install_url(console_url), wait_until='networkidle')
        tabs = page.get_by_role('tab')
        expect(tabs).to_have_text(['장비 찾기', '로봇 등록', '장치 정보', '카메라 연결 승인', '카메라 설치·보정', '호스트 서비스'])
        for tab in tabs.all():
            expect(tab).to_be_enabled()
        expect(page.locator('#peer-picker')).to_be_visible()
        choose(page, '호스트 서비스')
        expect(page.get_by_role('tab', name='호스트 서비스', exact=True)).to_have_attribute('aria-selected', 'true')
        choose(page, '로봇 등록')
        expect(page.locator('#robot-enrollment')).to_be_visible()
        page.locator('#enroll-address').fill('192.0.2.55:8080')
        page.locator('#robot-enrollment').evaluate('node=>window.retainedEnrollment=node')
        api['/api/fleet/session'] = {'principal_id': 'reader', 'role': 'viewer'}
        _open_token_access(page)
        page.locator('#token-save').click()
        expect(page.locator('#user-role')).to_contain_text('보기 전용')  # D-540 2
        choose(page, '장치 정보')
        expect(page.locator('#device-profiles')).to_be_visible()
        expect(page.locator('[data-profile="save"]')).to_be_disabled()
        choose(page, '카메라 연결 승인')
        expect(page.locator('#camera-link')).to_be_visible()
        choose(page, '카메라 설치·보정')
        expect(page.locator('#camera-calibration')).to_be_visible()
        expect(page.locator('[data-corner="0"][data-axis="0"]')).to_be_disabled()
        choose(page, '호스트 서비스')
        expect(page.get_by_role('tab', name='호스트 서비스', exact=True)).to_have_attribute('aria-selected', 'true')
        assert page.locator('#host-services').get_attribute('data-role-lock') is not None
        choose(page, '카메라 설치·보정')
        assert page.locator('[role=tabpanel]:visible').count() == 1
        api['/api/fleet/session'] = (401, {'detail': {'code': 'TOKEN_REQUIRED'}})
        _open_token_access(page)
        page.locator('#token-save').click()
        expect(page.locator('#user-role')).to_have_text('인증 필요')
        choose(page, '로봇 등록')
        assert page.evaluate('retainedEnrollment===document.querySelector("#robot-enrollment")')
        expect(page.locator('#enroll-address')).to_have_value('192.0.2.55:8080')
        page.set_viewport_size({'width': 390, 'height': 844})
        compact = page.get_by_role('combobox', name='작업 선택')
        expect(compact).to_be_enabled()
        compact.select_option('device-profiles')
        expect(page.locator('#device-profiles')).to_be_visible()
        compact.select_option('calibration')
        expect(page.locator('#camera-calibration')).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert errors == []
        browser.close()


def test_discovery_empty_failure_unsupported_and_explicit_retry(console_url):
    from playwright.sync_api import sync_playwright, expect

    api = {**API, '/api/fleet/discovery': {'scanner_online': True, 'devices': []}}
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, api)
        page.goto(install_url(console_url), wait_until='networkidle')
        choose(page, '로봇 등록')
        expect(page.locator('#discovery-empty')).to_contain_text('아직 발견된 로봇이 없습니다')
        api['/api/fleet/discovery'] = (503, {'detail': {'code': 'SCANNER_UNAVAILABLE'}})
        page.locator('#discovery-retry').click()
        expect(page.locator('#discovery-empty')).to_contain_text('확인할 수 없습니다')
        api['/api/fleet/discovery'] = (404, {'detail': 'Not Found'})
        page.locator('#discovery-retry').click()
        expect(page.locator('#discovery-empty')).to_contain_text('설정되지 않았습니다')
        api['/api/fleet/discovery'] = {'scanner_online': False, 'scanner_state': 'expired',
                                    'scanner_age_s': 61, 'devices': []}
        page.locator('#discovery-retry').click()
        expect(page.locator('#discovery-empty')).to_contain_text('마지막 스캔 61초 전')
        api['/api/fleet/discovery'] = {'scanner_online': True, 'devices': [{
            'name': 'fixture-robot', 'address': '192.0.2.8', 'port': 8080,
            'stage': 'CORE_READY', 'status': 'registration_pending', 'enrollable': True}]}
        page.locator('#discovery-retry').click()
        expect(page.locator('#discovery-list')).to_contain_text('192.0.2.8')
        api['/api/fleet/discovery'] = (503, {'detail': {'code': 'SCANNER_UNAVAILABLE'}})
        page.locator('#discovery-retry').click()
        expect(page.locator('#discovery-list')).to_be_hidden()
        assert '192.0.2.8' not in page.locator('#discovery-list').text_content()
        assert errors == []
        browser.close()


def _peer_api():
    return {**API, '/api/fleet/session': {'principal_id': 'reader', 'role': 'viewer'},
            '/api/fleet/peers': {'scanner_state': 'online', 'scanner_age_s': 1,
                'peers': [{'name': 'Fixture Pink', 'role': 'robot', 'peer_id': 'rosy_02',
                           'approval': 'approved', 'freshness': 'fresh', 'readiness': 'unknown'}]},
            '/api/fleet/discovery': {'scanner_online': True, 'devices': []}}


def test_actual_install_viewer_chooser_navigation_and_401_clear_owner_links(console_url):
    """Run actual install.js; synthetic identity is not operator authentication evidence."""
    from playwright.sync_api import sync_playwright, expect

    api, calls = _peer_api(), []
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, api, posts=calls,
            init_script="sessionStorage.setItem('rosy-console-token','fixture-token');")
        page.goto(install_url(console_url), wait_until='networkidle')
        expect(page.locator('#peer-picker')).to_be_visible()
        expect(page.locator('#peer-role')).to_be_enabled()
        expect(page.locator('#peer-retry')).to_be_enabled()
        expect(page.locator('#peer-list a')).to_have_attribute('href', '/console?robot=rosy_02')
        choose(page, '로봇 등록')
        expect(page.locator('#enroll-address')).to_be_disabled()
        choose(page, '장비 찾기')
        expect(page.locator('#peer-picker')).to_be_visible()
        api['/api/fleet/session'] = (401, {'detail': {'code': 'TOKEN_REQUIRED'}})
        _open_token_access(page)
        page.locator('#token-save').click()
        expect(page.locator('#user-role')).to_have_text('인증 필요')
        expect(page.locator('#peer-list')).to_be_hidden()
        expect(page.locator('#peer-list a')).to_have_count(0)
        expect(page.locator('#peer-empty')).to_contain_text('접속 후')
        assert not [method for method, _ in calls if method != 'GET']
        assert errors == []
        browser.close()


def test_actual_console_identity_link_focuses_card_without_arming_or_post(console_url):
    from playwright.sync_api import sync_playwright, expect
    from test_fleet_console_browser import WEB

    calls = []
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, _peer_api(), posts=calls,
            init_script="sessionStorage.setItem('rosy-console-token','fixture-token');")
        # The local static server has no FastAPI /console route; deliver its actual source page.
        page.route('**/console?robot=*', lambda route: route.fulfill(status=200,
            content_type='text/html', body=(WEB / 'index.html').read_text(encoding='utf-8')))
        page.goto(install_url(console_url), wait_until='networkidle')
        page.locator('#peer-list a').click()
        page.wait_for_function("document.activeElement?.dataset.robotId==='rosy_02'")
        expect(page.locator("#context-status")).to_be_visible()
        expect(page.locator('[data-context-tab="status"]')).to_have_attribute("aria-selected", "true")
        expect(page.locator('#roster article.selected')).to_have_count(1)
        expect(page.locator('#roster article.selected')).to_have_attribute('data-robot-id', 'rosy_02')
        expect(page.locator('#map-canvas')).to_have_class('idle')
        expect(page.locator('#map-canvas')).to_have_attribute('tabindex', '-1')
        expect(page.locator('[data-goal-robot-id="rosy_02"]')).to_have_attribute('aria-pressed', 'false')
        assert not [method for method, _ in calls if method != 'GET']
        assert errors == []
        browser.close()


def test_calibration_stage_recomputes_handles_after_hidden_resize_and_disposes_observer(console_url):
    from playwright.sync_api import sync_playwright, expect

    api = {**API, '/api/fleet/vision/sources': {'sources': ['fixture-camera']},
           '/api/fleet/vision/lease': {'source_id': 'fixture-camera', 'lease': 'preview-lease',
                                     'frame_path': '/api/vision/sources/fixture-camera/frame', 'expires_in_s': 60}}
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, api, init_script="""
            sessionStorage.setItem('rosy-console-token','fixture-token');
            const NativeResizeObserver=ResizeObserver;window.stageObservers=[];
            window.ResizeObserver=class extends NativeResizeObserver {
              observe(node,...args){if(node.id==='vision-image-stage')stageObservers.push(this);return super.observe(node,...args);}
              disconnect(){this.wasDisconnected=true;super.disconnect();}
            };
        """)
        page.route('**/api/vision/**', lambda route: route.fulfill(status=200,
                   content_type='image/svg+xml', body='<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480"/>',
                   headers={'X-Frame-Rectified': 'false', 'X-Frame-Seq': '42', 'X-Frame-Age-Ms': '20'}))
        page.goto(install_url(console_url), wait_until='networkidle')
        choose(page, '카메라 설치·보정')
        page.get_by_text('왜곡 및 사각 보정', exact=True).click()
        page.get_by_role('button', name='원본에서 영역 조정').click()
        expect(page.locator('#vision-corner-overlay')).to_be_visible()
        # Freeze incidental frame refresh: only owned layout observation may update geometry.
        page.route('**/api/vision/**', lambda route: None)
        before = page.locator('[data-corner-handle="0"]').get_attribute('r')
        choose(page, '로봇 등록')
        page.set_viewport_size({'width': 390, 'height': 844})
        choose(page, '카메라 설치·보정')
        page.wait_for_function("() => {const w=document.querySelector('#vision-image-stage').getBoundingClientRect().width;const r=+document.querySelector('[data-corner-handle]').getAttribute('r');return w>0&&Math.abs(r-Math.max(3,Math.min(8,2200/w)))<.01;}")
        after = page.locator('[data-corner-handle="0"]').get_attribute('r')
        assert before != after
        assert page.evaluate('stageObservers.length') == 1
        page.evaluate("dispatchEvent(new PageTransitionEvent('pagehide'))")
        assert page.evaluate('stageObservers.every(observer=>observer.wasDisconnected)')
        assert errors == []
        browser.close()


def test_hidden_calibration_does_not_lease_or_fetch_frames_and_late_lease_stays_hidden(console_url):
    from playwright.sync_api import sync_playwright

    lease = {'source_id': 'fixture-camera', 'lease': 'preview-lease',
             'frame_path': '/api/vision/sources/fixture-camera/frame', 'expires_in_s': 60}
    api = {**API, '/api/fleet/vision/sources': {'sources': ['fixture-camera']},
           '/api/fleet/vision/lease': lease}
    with sync_playwright() as p:
        calls, held, frames = [], [], []
        browser, page, errors = _open_console(p, api, posts=calls,
            init_script="sessionStorage.setItem('rosy-console-token','fixture-token');")
        def frame(route):
            frames.append(route.request.url)
            route.fulfill(status=200, content_type='image/svg+xml',
                body='<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480"/>',
                headers={'X-Frame-Rectified': 'true', 'X-Frame-Seq': '42', 'X-Frame-Age-Ms': '20'})
        page.route('**/api/vision/**', frame)
        page.goto(install_url(console_url), wait_until='networkidle')
        page.wait_for_timeout(1650)
        assert not [call for call in calls if call[1] == '/api/fleet/vision/lease']
        assert frames == []
        page.route('**/api/fleet/vision/lease', lambda route: held.append(route))
        choose(page, '카메라 설치·보정')
        page.wait_for_timeout(1650)
        assert len(held) == 1
        choose(page, '로봇 등록')
        held[0].fulfill(status=200, json=lease)
        page.wait_for_timeout(1650)
        assert frames == []
        page.unroute('**/api/fleet/vision/lease')
        choose(page, '카메라 설치·보정')
        page.locator('#vision-image').wait_for(state='visible')
        assert frames
        choose(page, '로봇 등록')
        count = len(frames)
        page.wait_for_timeout(1650)
        assert len(frames) == count
        assert errors == []
        browser.close()


def test_rapid_calibration_return_starts_new_owner_and_old_lease_cannot_paint(console_url):
    from playwright.sync_api import sync_playwright, expect

    api = {**API, '/api/fleet/vision/sources': {'sources': ['fixture-camera']}}
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, api, init_script="""
            sessionStorage.setItem('rosy-console-token','fixture-token');
            window.leaseRequests=0;const originalFetch=fetch;
            window.fetch=(url,options={})=>{
              if(String(url).endsWith('/api/fleet/vision/lease')){
                leaseRequests++;return originalFetch(url,{...options,signal:undefined});
              }
              return originalFetch(url,options);
            };
        """)
        held, frames = [], []
        page.route('**/api/fleet/vision/lease', lambda route: held.append(route))
        def frame(route):
            frames.append(route.request.url)
            route.fulfill(status=200, content_type='image/svg+xml',
                body='<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480"/>',
                headers={'X-Frame-Rectified': 'true', 'X-Frame-Seq': 'new-owner-42', 'X-Frame-Age-Ms': '20'})
        page.route('**/api/vision/**', frame)
        page.goto(install_url(console_url), wait_until='networkidle')
        choose(page, '카메라 설치·보정')
        page.wait_for_function('leaseRequests===1')
        expect(page.locator('#vision-source')).to_have_value('fixture-camera')
        page.get_by_text('왜곡 및 사각 보정', exact=True).click()
        page.locator('[data-corner="0"][data-axis="0"]').fill('17')
        choose(page, '로봇 등록')
        expect(page.locator('#robot-enrollment')).to_be_visible()
        choose(page, '카메라 설치·보정')
        expect(page.locator('#camera-calibration')).to_be_visible()
        page.wait_for_function('leaseRequests===2')
        for _ in range(100):  # the page counts its fetch before Playwright hands the route to this handler
            if len(held) == 2:
                break
            page.wait_for_timeout(50)
        assert len(held) == 2
        def lease(kind):
            return {'source_id': 'fixture-camera', 'lease': f'{kind}-lease',
                    'frame_path': f'/api/vision/sources/fixture-camera/frame?owner={kind}', 'expires_in_s': 60}
        held[1].fulfill(status=200, json=lease('new'))
        expect(page.locator('#vision-meta')).to_contain_text('new-owner-42')
        held[0].fulfill(status=200, json=lease('old'))
        page.wait_for_timeout(1650)
        assert frames and all('owner=new' in url for url in frames)
        expect(page.locator('#vision-source')).to_have_value('fixture-camera')
        expect(page.locator('[data-corner="0"][data-axis="0"]')).to_have_value('17')
        expect(page.locator('#vision-meta')).to_contain_text('new-owner-42')
        assert errors == []
        browser.close()
