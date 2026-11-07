"""Exercise Account's own page composition, including its first-password browser flow."""
import threading
import time
from urllib.parse import quote, urlencode

import pytest
import uvicorn

from browser_harness import browser_tests_enabled, safe_listener
from test_account_service_separation import standalone
from test_account_authority import CHALLENGE

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='opt-in Chromium scenario')


def test_standalone_existing_cookie_and_initial_password_resume_registered_app(standalone, tmp_path):
    from playwright.sync_api import expect, sync_playwright
    from fastapi.responses import HTMLResponse
    from fake_core_ssh import robot_certificate
    app, client, _, _ = standalone
    value = client.cookies.get('rosy_fleet_session')
    sessions = app.state.password_sessions
    sessions.create_account(value, login='bob', principal_id='bob', role='viewer', password='bob!',
                            grants=[{'resource': 'site:test-site', 'capabilities': ['fleet.read']}])
    listener = safe_listener()
    origin = f'https://localhost:{listener.getsockname()[1]}'
    callback = origin + '/registered-fleet-callback'
    app.state.account_authority.clients['fleet']['redirect_uris'] = [callback]
    @app.get('/registered-fleet-callback')
    def callback_page():
        return HTMLResponse('<h1>Registered callback</h1>')
    cert, key = robot_certificate(tmp_path / 'tls', 'localhost')
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', log_config=None, timeout_graceful_shutdown=3,
                                         ssl_certfile=str(cert), ssl_keyfile=str(key)))
    worker = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 20
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        target = '/api/fleet/auth/authorize?' + urlencode({
            'response_type': 'code', 'client_id': 'fleet',
            'redirect_uri': callback, 'scope': 'site:test-site',
            'state': 'standalone-browser', 'code_challenge': CHALLENGE, 'code_challenge_method': 'S256'})
        entry = origin + '/console/login?return=' + quote(target, safe='')
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context(ignore_https_errors=True)  # Disposable self-signed fixture only.
                page = context.new_page()
                errors = []
                resources_failed = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('response', lambda response: resources_failed.append(response.url)
                        if response.status >= 400 and any(p in response.url for p in
                            ('/common/', '/console/assets/')) else None)
                page.goto(origin + '/console/login')
                expect(page.get_by_role('heading', name='Rosy Account 로그인', exact=True)).to_be_visible()
                expect(page.get_by_role('form', name='Rosy Account 로그인', exact=True)).to_be_visible()
                expect(page.locator('#login-back')).to_be_hidden()
                page.goto(origin + '/console/profile')
                expect(page).to_have_title('Rosy Account — 내 계정')
                expect(page.locator('#profile-back')).to_be_hidden()
                page.locator('#profile-login').click()
                expect(page.get_by_role('heading', name='Rosy Account 로그인', exact=True)).to_be_visible()
                assert '/console/login?return=%2Fconsole%2Fprofile' in page.url
                expect(page.locator('#login-back')).to_be_hidden()
                page.goto(origin + '/console/accounts')
                expect(page).to_have_title('Rosy Account — 계정 관리')
                expect(page.locator('ui-brand a')).to_have_attribute('href', '/console/profile')
                expect(page.get_by_role('link', name='관제로 돌아가기')).to_have_count(0)
                page.locator('#account-login').click()
                expect(page.get_by_role('heading', name='Rosy Account 로그인', exact=True)).to_be_visible()
                expect(page.locator('#login-back')).to_be_hidden()
                page.goto('about:blank')  # This login page leaves for /console/accounts once it sees the cookie, which can beat the goto below.
                context.add_cookies([{'name': 'rosy_fleet_session', 'value': value, 'url': origin,
                                      'secure': True, 'httpOnly': True, 'sameSite': 'Lax'}])
                page.goto(entry)
                expect(page.get_by_role('heading', name='Registered callback')).to_be_visible(timeout=15000)
                assert 'code=' in page.url and 'state=standalone-browser' in page.url
                page.goto(origin + '/console/profile')
                expect(page.locator('ui-brand b')).to_have_text('Rosy Account')
                expect(page.locator('#profile-content')).to_be_visible()
                expect(page.locator('#profile-role')).to_have_text('운영자')
                page.locator('#profile-name').fill('Account artifact administrator')
                with page.expect_response(lambda response: response.url.endswith('/api/fleet/auth/profile')
                                          and response.request.method == 'PATCH') as saved:
                    page.locator('#profile-name-save').click()
                assert saved.value.status == 200
                page.goto(origin + '/console/accounts')
                expect(page.locator('ui-brand b')).to_have_text('Rosy Account')
                expect(page.locator('#account-list')).to_contain_text('bob')
                context.clear_cookies()
                page.goto(entry)
                expect(page.get_by_role('heading', name='Rosy Account 로그인')).to_be_visible()
                expect(page.locator('ui-brand b')).to_have_text('Rosy Account')
                expect(page.locator('[data-login=form]')).to_be_visible()
                page.locator('[data-login=login]').fill('bob')
                page.locator('[data-login=password]').fill('bob!')
                page.locator('[data-login=submit]').click()
                expect(page.locator('[data-login=confirm]')).to_be_visible(timeout=15000)
                page.locator('[data-login=password]').fill('bob-final-password')
                page.locator('[data-login=confirm]').fill('bob-final-password')
                page.locator('[data-login=submit]').click()
                expect(page.get_by_role('heading', name='Registered callback')).to_be_visible(timeout=15000)
                assert errors == []
                assert resources_failed == []
                assert sessions.check('browser-check', 'bob', 'bob-final-password').password_change_required is False
            finally:
                browser.close()
    finally:
        server.should_exit = True
        worker.join(timeout=10)
        listener.close()
