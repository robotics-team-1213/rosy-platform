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
                context.add_cookies([{'name': 'rosy_fleet_session', 'value': value, 'url': origin,
                                      'secure': True, 'httpOnly': True, 'sameSite': 'Lax'}])
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(entry)
                expect(page.get_by_role('heading', name='Registered callback')).to_be_visible(timeout=15000)
                assert 'code=' in page.url and 'state=standalone-browser' in page.url
                context.clear_cookies()
                page.goto(entry)
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
                assert sessions.check('browser-check', 'bob', 'bob-final-password').password_change_required is False
            finally:
                browser.close()
    finally:
        server.should_exit = True
        worker.join(timeout=10)
        listener.close()
