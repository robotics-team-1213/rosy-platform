"""D-439 Fleet task navigation, discovery recovery and owned stage geometry."""
import os
import hashlib
import json
from pathlib import Path

import pytest

from test_fleet_console_browser import API, _open_console as _open_base, console_url  # noqa: F401

pytestmark = pytest.mark.skipif(os.environ.get('ROSY_RUN_BROWSER_TESTS') != '1',
                                reason='optional Chromium regression')


def _open_console(*args, **kwargs):
    browser, page, errors = _open_base(*args, **kwargs)
    # X-only served mutation proves the guard without ever changing the product file.
    if candidate := os.environ.get('ROSY_FLEET_MUTATION_ASSET'):
        asset = Path(candidate).resolve()
        assert asset.drive.upper() == 'X:'
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


def install_url(console):
    return console.rsplit('/', 1)[0] + '/install.html'


def choose(page, title):
    tab = page.get_by_role('tab', name=title, exact=True)
    if tab.is_visible():
        tab.click()
    else:
        page.get_by_role('combobox', name='작업 선택').select_option(label=title)


def test_install_tasks_stay_mounted_and_navigate_while_role_locked(console_url):
    from playwright.sync_api import sync_playwright, expect

    api = {**API, '/api/fleet/session': {'principal_id': 'installer', 'role': 'operator'},
           '/api/fleet/enrollment/robots': {'available': True, 'robots': [], 'identity': {}},
           '/api/fleet/discovery': {'scanner_online': True, 'devices': []}}
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, api)
        page.goto(install_url(console_url), wait_until='networkidle')
        tabs = page.get_by_role('tab')
        expect(tabs).to_have_count(3)
        for tab in tabs.all():
            expect(tab).to_be_enabled()
        expect(page.locator('#robot-enrollment')).to_be_visible()
        page.locator('#enroll-address').fill('192.0.2.55:8080')
        page.locator('#robot-enrollment').evaluate('node=>window.retainedEnrollment=node')
        api['/api/fleet/session'] = {'principal_id': 'reader', 'role': 'viewer'}
        page.locator('#token-save').click()
        expect(page.locator('#user-role')).to_contain_text('조회 전용')
        choose(page, '카메라 연결 승인')
        expect(page.locator('#camera-link')).to_be_visible()
        choose(page, '카메라 설치·보정')
        expect(page.locator('#camera-calibration')).to_be_visible()
        expect(page.locator('[data-corner="0"][data-axis="0"]')).to_be_disabled()
        assert page.locator('[role=tabpanel]:visible').count() == 1
        api['/api/fleet/session'] = (401, {'detail': {'code': 'TOKEN_REQUIRED'}})
        page.locator('#token-save').click()
        expect(page.locator('#user-role')).to_have_text('인증 필요')
        choose(page, '로봇 등록')
        assert page.evaluate('retainedEnrollment===document.querySelector("#robot-enrollment")')
        expect(page.locator('#enroll-address')).to_have_value('192.0.2.55:8080')
        page.set_viewport_size({'width': 390, 'height': 844})
        compact = page.get_by_role('combobox', name='작업 선택')
        expect(compact).to_be_enabled()
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
