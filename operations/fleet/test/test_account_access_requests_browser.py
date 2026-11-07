"""D-993 in a real browser: request from the login page, decide on the account page, phone width."""
import threading
import time

import pytest
import uvicorn

from browser_harness import browser_tests_enabled, safe_listener
from test_account_service_separation import standalone  # noqa: F401  (fixture)

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='opt-in Chromium scenario')


def test_request_from_login_then_administrator_approves_and_rejects(standalone, tmp_path):
    from playwright.sync_api import expect, sync_playwright
    from fake_core_ssh import robot_certificate
    app, client, _, _ = standalone
    manager = client.cookies.get('rosy_fleet_session')
    listener = safe_listener()
    origin = f'https://localhost:{listener.getsockname()[1]}'
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
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                errors = []
                person = browser.new_context(ignore_https_errors=True, viewport={'width': 360, 'height': 740})
                page = person.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                for name, username in (('Dana Kim', 'dana'), ('Eve Park', 'eve')):
                    page.goto(origin + '/console/login')
                    page.get_by_role('button', name='계정이 없나요? 가입 요청').click()
                    expect(page.get_by_role('heading', name='가입·권한 요청')).to_be_visible()
                    page.get_by_label('이름').fill(name)
                    page.get_by_label('희망 로그인 ID', exact=False).fill(username)
                    page.get_by_role('button', name='요청 보내기').click()
                    expect(page.get_by_text('요청을 보냈습니다.')).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                denied = person.new_page()
                denied.goto(origin + '/console/login?error=access_denied&return=%2Fconsole')
                expect(denied.get_by_role('button', name='이 앱 사용 권한 요청')).to_be_visible()

                admin = browser.new_context(ignore_https_errors=True)
                admin.add_cookies([{'name': 'rosy_fleet_session', 'value': manager, 'url': origin}])
                page = admin.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(origin + '/console/accounts')
                expect(page.get_by_role('cell', name='dana')).to_be_visible()
                page.get_by_role('button', name='dana 요청 처리').click()
                page.locator('#account-password').fill('initial secret 1')
                page.get_by_role('button', name='승인하고 저장').click()
                expect(page.get_by_text('요청을 승인하고 저장했습니다.')).to_be_visible()
                assert any(a['login'] == 'dana' for a in app.state.password_sessions.list_accounts(manager))

                page.get_by_role('button', name='eve 요청 처리').click()
                page.locator('#request-reason').fill('unknown person')
                page.get_by_role('button', name='거절…').click()
                page.get_by_role('button', name='요청 거절').click()
                expect(page.get_by_text('요청을 거절하고 기록했습니다.')).to_be_visible()
                expect(page.get_by_text('거절됨 · unknown person')).to_be_visible()
                assert errors == []
            finally:
                browser.close()
    finally:
        server.should_exit = True
        worker.join(10)
