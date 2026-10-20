"""Real application documents on the standalone sample origin; no intercepted API calls."""
import threading
import time
from urllib.parse import urlsplit

import pytest
from browser_harness import browser_tests_enabled

from test_sample_server import load_engine

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='opt-in Chromium scenario')


@pytest.fixture
def sample_site():
    engine = load_engine()
    from http_host import make_server
    server = make_server(engine, 'http://localhost:0')
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield engine, f'http://localhost:{server.server_address[1]}'
    finally:
        server.shutdown()
        server.server_close()
        worker.join(5)


@pytest.mark.parametrize('path', ['/console', '/console/install', '/console/site-map', '/console/cell',
                                  '/console/accounts', '/console/policy', '/console/profile', '/console/login'])
def test_eight_pages_use_same_frontend_without_unhandled_requests(sample_site, path):
    from playwright.sync_api import sync_playwright, expect
    engine, origin = sample_site
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            response = context.request.post(origin + '/api/fleet/auth/login',
                headers={'Origin': origin}, data={'login': 'sample', 'password': 'sample-password'})
            assert response.status == 204
            page = context.new_page()
            errors, external, failed = [], [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda req: external.append(req.url)
                    if urlsplit(req.url).netloc != urlsplit(origin).netloc and req.url.startswith('http') else None)
            page.on('response', lambda res: failed.append((res.status, res.url)) if res.status >= 500 else None)
            assert page.goto(origin + path).status == 200
            expect(page.locator('body')).to_be_visible()
            page.wait_for_timeout(1800)
            assert not external, external
            assert not errors, errors
            assert not engine.unhandled, engine.unhandled
            assert not failed, failed
        finally:
            browser.close()


def test_profile_save_and_logout_use_sample_session(sample_site):
    from playwright.sync_api import sync_playwright, expect
    _, origin = sample_site
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(origin + '/console/login?return=/console/profile')
            page.locator('[data-login=login]').fill('sample')
            page.locator('[data-login=password]').fill('sample-password')
            page.locator('[data-login=submit]').click()
            expect(page.locator('#profile-id')).to_have_text('sample')
            page.locator('#profile-name').fill('프런트 개발자')
            page.locator('#profile-name-save').click()
            expect(page.locator('#profile-status')).to_contain_text('저장하고 다시 확인')
            page.reload()
            expect(page.locator('#profile-name')).to_have_value('프런트 개발자')
            response = page.request.post(origin + '/api/fleet/auth/logout', headers={'Origin': origin}, data={})
            assert response.status == 204
            page.reload()
            expect(page.locator('#profile-login')).to_be_visible()
        finally:
            browser.close()
