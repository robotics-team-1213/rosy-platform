"""Long server feedback stays readable without moving the always-live stop outside the viewport."""
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from browser_harness import browser_tests_enabled
from playwright.sync_api import expect, sync_playwright
from test_role_g2_browser import TOKENS, _core_client, _response

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='opt-in Chromium notice scenario')


@pytest.mark.parametrize('width', [320, 390, 768, 1440])
@pytest.mark.parametrize('theme', ['dark', 'light'])
def test_long_stop_error_wraps_and_scrolls_without_hiding_stop(tmp_path, width, theme):
    client, token = _core_client(tmp_path), TOKENS['administrator']
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': width, 'height': 900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.add_init_script(f"sessionStorage.setItem('rosy.dashboard.token', '{token}');localStorage.setItem('rosy.theme', '{theme}')")
        def serve(route):
            path = urlsplit(route.request.url).path
            if path == '/api/v1/safety/stop':
                route.fulfill(status=503, json={'error': {'code': 'INTERNAL_ERROR', 'message': '상태 확인: fixture-' + 'x' * 600}})
                return
            if route.request.method != 'GET':
                route.fulfill(status=501, json={'detail': 'fixture blocks writes'}); return
            response = _response(client, path, token, 'normal', 'setup')
            route.fulfill(status=response.status_code, headers={'content-type': response.headers.get('content-type', 'application/octet-stream')},
                          body=response.content if hasattr(response, 'content') else response.body)
        page.route('**/*', serve)
        page.goto('http://rosy.test/setup')
        stop, notice = page.locator('#shell-estop'), page.locator('#shell-notice')
        stop.click()
        expect(notice).to_contain_text('fixture-')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert notice.evaluate('n => n.scrollWidth <= n.clientWidth + 1')
        assert page.locator('ui-topbar').bounding_box()['height'] <= 180
        box = stop.bounding_box()
        assert box['x'] >= 0 and box['x'] + box['width'] <= width + 1 and box['y'] + box['height'] < 180
        brand, feedback = page.locator('ui-topbar ui-brand').bounding_box(), notice.bounding_box()
        assert (brand['x'] + brand['width'] <= feedback['x'] or
                brand['y'] + brand['height'] <= feedback['y']), (brand, feedback)
        notice.focus()
        page.keyboard.press('End')
        page.wait_for_function("() => { const n = document.querySelector('#shell-notice'); return n.scrollHeight <= n.clientHeight + 1 || n.scrollTop > 0; }")
        if value := os.environ.get('ROSY_SHOT_DIR'):
            root = Path(value).expanduser(); root.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(root / f'robot-notice-{theme}-{width}.png'))
        assert not errors
        browser.close()
