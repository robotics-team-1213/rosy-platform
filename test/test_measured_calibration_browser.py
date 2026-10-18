"""D-775 user workflow in Chromium; route fixtures are not physical evidence."""
import hashlib
from io import BytesIO
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from browser_harness import browser_tests_enabled, open_page
from test_fleet_console_browser import console_url  # noqa: F401
from test_console_lifetime_browser import _serve_api

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='set ROSY_RUN_BROWSER_TESTS=1')


@pytest.mark.parametrize('width', [1440, 390])
def test_approve_confirm_read_revoke_and_discard_old_source_response(console_url, width):  # noqa: F811
    from playwright.sync_api import expect, sync_playwright
    from PIL import Image
    bundle = json.loads((Path(__file__).parent/'fixtures/protocol/measured-calibration.v1.json').read_text())
    bundle['evidence_kind'] = 'measured'  # Simulated operator claim in a mocked API.
    bundle.pop('digest')
    bundle['digest'] = hashlib.sha256(json.dumps(bundle, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    image = BytesIO()
    Image.new('RGB', (640, 360), (100, 110, 120)).save(image, format='JPEG')
    state = {'row': None, 'applied': False, 'hold': False, 'pending': [], 'approvals': [], 'revoked': False,
             'hold_frame': False, 'pending_frames': [], 'session': 'receiver:1'}

    def status(source):
        row = state['row'] if source == 'ceiling_north' else None
        return {'source_id': source, 'session_id': state['session'],
                'calibration_revision': row['calibration_revision'] if row else None,
                'state': ('applied' if state['applied'] else 'confirmation_required') if row else 'waiting',
                'reason': ('ok' if state['applied'] else 'confirmation_required') if row else 'not_approved',
                'frame_seq': 2 if state['applied'] else None,
                'geometry': {'image_size': [640, 360], 'rotation_deg': 0, 'lens': bundle['capture']['lens']}}

    def serve(route):
        parsed = urlparse(route.request.url)
        path = parsed.path
        if path == '/api/fleet/vision/sources':
            return route.fulfill(status=200, json={'sources': ['ceiling_north', 'ceiling_south']})
        if path == '/api/fleet/calibrations' and route.request.method == 'POST':
            body = route.request.post_data_json
            state['approvals'].append(body)
            state['row'] = {'source_id': 'ceiling_north', 'bundle': body['bundle'], 'use': 'preview-only',
                            'calibration_revision': 'measured-browser', 'persistent': True}
            return route.fulfill(status=200, json=state['row'])
        if path == '/api/fleet/calibrations' and parse_qs(parsed.query).get('purpose') == ['preview']:
            return route.fulfill(status=200, json={'calibrations': [state['row']] if state['row'] else [],
                                                   'persistent': True, 'use': 'preview-only'})
        if path == '/api/fleet/calibrations/ceiling_north' and route.request.method == 'DELETE':
            assert parse_qs(parsed.query)['expected_revision'] == ['measured-browser']
            state.update(row=None, applied=False, revoked=True)
            return route.fulfill(status=200, json={'removed': True, 'source_id': 'ceiling_north'})
        if path == '/api/fleet/vision/lease':
            body = route.request.post_data_json
            measured = body.get('measured')
            token = ('confirm' if measured['confirm_conditions'] else 'measured') if measured else 'raw'
            return route.fulfill(status=200, json={'lease': token, 'expires_in_s': 60,
                'frame_path': f"/api/vision/sources/{body['source_id']}/frame"})
        if path.endswith('/measured-status'):
            source = path.split('/')[-2]
            if state['hold'] and source == 'ceiling_north':
                state['pending'].append(route)
                return
            return route.fulfill(status=200, json=status(source))
        if path.startswith('/api/vision/') and path.endswith('/frame'):
            token = route.request.headers.get('authorization', '')
            measured = token in ('Bearer confirm', 'Bearer measured')
            if measured and token == 'Bearer confirm':
                state['applied'] = True
            if measured and not state['applied']:
                return route.fulfill(status=409, json={'reason': 'confirmation_required'})
            headers = {'X-Frame-Seq': '2', 'X-Frame-Age-Ms': '50', 'X-Frame-Width': '640',
                       'X-Frame-Height': '360', 'X-Frame-Rotation-Deg': '0',
                       'X-Frame-Rectified': 'measured-map' if measured else 'false',
                       'X-Frame-Calibration': 'measured-browser', 'X-Frame-Session': state['session'],
                       'X-Frame-Observed-Fraction': '0.8'}
            if measured and state['hold_frame']:
                state['pending_frames'].append((route, headers))
                return
            return route.fulfill(status=200, content_type='image/jpeg', headers=headers, body=image.getvalue())
        return _serve_api(route)

    with sync_playwright() as playwright:
        browser, page, errors = open_page(playwright, width, 1000)
        static_failures = []
        page.on('response', lambda r: static_failures.append(r.url)
                if r.status >= 400 and '/api/' not in r.url else None)
        page.add_init_script("sessionStorage.setItem('rosy-console-token','measured-browser')")
        page.route('**/api/**', serve)
        page.goto(console_url.rsplit('/', 1)[0]+'/install.html', wait_until='domcontentloaded')
        try:
            page.wait_for_function("document.querySelector('#install-chooser .ui-task-chooser')", timeout=5000)
        except Exception as exc:
            pytest.fail(f'install mount failed: {errors}; static failures={static_failures}; {exc}')
        if width < 700:
            page.get_by_role('combobox', name='작업 선택').select_option('calibration')
        else:
            page.get_by_role('tab', name='카메라 설치·보정').click()
        page.locator('#vision-source').select_option('ceiling_north')
        page.locator('#measured-bundle').set_input_files({'name': 'bundle.json', 'mimeType': 'application/json',
                                                        'buffer': json.dumps(bundle).encode()})
        page.locator('#measured-p95').fill('0.01')
        page.locator('#measured-max').fill('0.02')
        page.locator('#measured-approve').click()
        page.wait_for_function("document.querySelector('#measured-state').textContent.includes('저장')")
        assert page.locator('#measured-confirm').is_disabled()
        page.locator('#measured-conditions').hover()
        page.mouse.down()
        state['hold'] = True
        with page.expect_request('**/measured-status'):
            pass  # Hold the scheduled read without racing its disabled refresh button.
        expect(page.locator('#measured-confirm')).to_be_disabled()
        expect(page.locator('#measured-read')).to_be_disabled()
        expect(page.locator('#measured-revoke')).to_be_disabled()
        assert state['pending']
        page.mouse.up()
        expect(page.locator('#measured-conditions')).to_be_checked()
        expect(page.locator('#measured-conditions')).to_be_enabled()
        state['hold'] = False
        for pending in state['pending']:
            pending.fulfill(status=200, json=status('ceiling_north'))
        state['pending'].clear()
        page.locator('#measured-confirm').click()
        page.locator('#measured-image').wait_for(state='visible')
        assert state['approvals'][0]['purpose'] == 'preview'
        assert state['approvals'][0]['limits'] == {'p95_m': .01, 'max_m': .02}
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        state.update(session='receiver:2', applied=False)
        with page.expect_request('**/measured-status'):
            page.locator('#measured-refresh').click()
        page.wait_for_function("document.querySelector('#measured-state').textContent.includes('촬영 조건 확인 필요')")
        assert not page.locator('#measured-conditions').is_checked()
        assert page.locator('#measured-confirm').is_disabled()
        page.locator('#measured-conditions').check()
        page.locator('#measured-confirm').click()
        page.locator('#measured-image').wait_for(state='visible')
        with page.expect_response(lambda r: r.url.endswith('/frame')
                                  and r.request.headers.get('authorization') == 'Bearer measured'):
            page.locator('#measured-read').click()
        state['hold_frame'] = True
        with page.expect_request(lambda r: r.url.endswith('/frame') and r.headers.get('authorization') == 'Bearer measured'):
            pass  # The scheduled read refreshes the visible image.
        expect(page.locator('#measured-read')).to_be_disabled()
        assert state['pending_frames']
        if width < 700:
            page.get_by_role('combobox', name='작업 선택').select_option('hosts')
        else:
            page.get_by_role('tab', name='호스트 서비스').click()
        state['hold_frame'] = False
        for pending, headers in state['pending_frames']:
            pending.fulfill(status=200, content_type='image/jpeg', headers=headers, body=image.getvalue())
        page.wait_for_timeout(100)  # Allow the held response's async continuation to run.
        assert page.locator('#measured-image').evaluate('(image) => image.hidden && !image.hasAttribute("src")')
        if width < 700:
            page.get_by_role('combobox', name='작업 선택').select_option('calibration')
        else:
            page.get_by_role('tab', name='카메라 설치·보정').click()
        state['hold'] = True
        with page.expect_request('**/measured-status'):
            pass
        expect(page.locator('#measured-confirm')).to_be_disabled()
        assert state['pending']
        page.locator('#vision-source').select_option('ceiling_south')
        state['hold'] = False
        for pending in state['pending']:
            pending.fulfill(status=200, json=status('ceiling_north'))
        page.locator('#measured-image').wait_for(state='hidden')
        page.wait_for_function("document.querySelector('#measured-state').textContent.includes('승인 없음')")
        page.locator('#vision-source').select_option('ceiling_north')
        page.locator('#measured-revoke').click()
        page.wait_for_function("document.querySelector('#measured-state').textContent.includes('승인 없음')")
        assert state['revoked'] and not errors
        browser.close()
