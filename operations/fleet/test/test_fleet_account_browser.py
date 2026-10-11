"""D-683 account discovery, verified authentication and no automatic operation replay."""
import threading
import os
import time
from pathlib import Path

import pytest
import uvicorn
from browser_harness import browser_tests_enabled, safe_listener
from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.site_users import hash_password
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='opt-in Chromium scenario')
ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def account_page(tmp_path):
    from playwright.sync_api import sync_playwright
    console = FleetConsole([RobotEndpoint('rosy_01', 'http://127.0.0.1:8080', 'robot-only')],
                           [FakeRobot('rosy_01')])
    tasks = FleetTaskService(FleetTaskStore(tmp_path / 'fleet.sqlite3'), robot_ids=console.robot_ids)
    app = create_app(console, task_service=tasks, site_users={}, site_logins={'alice': {
        'principal_id': 'alice', 'role': 'operator', 'password_scrypt': hash_password('pw-1234')}},
        web_common=ROOT / 'shared' / 'web', start_task_dispatcher=False)
    listener = safe_listener()
    origin = f'http://localhost:{listener.getsockname()[1]}'
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', timeout_graceful_shutdown=3))
    worker = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 20
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(.02)
        assert server.started
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                yield browser.new_page(viewport={'width': 320, 'height': 900}), origin
            finally:
                browser.close()
    finally:
        server.should_exit = True
        worker.join(timeout=20)
        listener.close()
        assert not worker.is_alive()


def _credentials(page):
    page.locator('[data-login=login]').fill('alice')
    page.locator('[data-login=password]').fill('pw-1234')


@pytest.mark.parametrize('path', ['/console', '/console/install', '/console/site-map', '/console/cell'])
def test_account_entry_returns_to_each_document_without_commands(account_page, path):
    from playwright.sync_api import expect
    page, origin = account_page
    writes = []
    page.context.on('request', lambda req: writes.append(req.url) if req.method == 'POST' else None)
    page.goto(origin + path)
    expect(page.locator('#fleet-login')).to_be_visible()
    if path in ['/console/site-map', '/console/cell']:
        with page.expect_popup() as popup:
            page.locator('#fleet-login').click()
        login = popup.value
        expect(login.locator('#login-context')).to_contain_text('초안')
    else:
        page.locator('#fleet-login').click()
        login = page
    _credentials(login)
    if output := os.environ.get('ROSY_SHOT_DIR'):
        for width in (320, 1366):
            login.set_viewport_size({'width': width, 'height': 900})
            login.screenshot(path=str(Path(output) / f'account-login-{width}.png'), full_page=True)
    login.locator('[data-login=password]').press('Enter')
    expect(login).to_have_url(origin + path)
    expect(login.locator('#fleet-account')).to_be_visible()
    login.locator('#fleet-account > summary').click()
    expect(login.locator('#fleet-account-identity')).to_contain_text('alice')
    for width in (320, 1366):
        login.set_viewport_size({'width': width, 'height': 900})
        assert login.evaluate('document.documentElement.scrollWidth <= innerWidth')
        if output := os.environ.get('ROSY_SHOT_DIR'):
            login.screenshot(path=str(Path(output) / f'account-{path.rsplit("/", 1)[-1]}-{width}.png'), full_page=True)
    assert writes == [origin + '/api/fleet/auth/login']


def test_logout_failure_does_not_claim_the_session_ended(account_page):
    from playwright.sync_api import expect
    page, origin = account_page
    page.goto(origin + '/console/login')
    _credentials(page)
    page.locator('[data-login=submit]').click()
    expect(page.locator('#fleet-account')).to_be_visible()
    page.locator('#fleet-account > summary').click()
    page.route('**/api/fleet/auth/logout', lambda route: route.fulfill(status=503, body='{}'))
    page.locator('[data-login=logout]').click()
    expect(page.locator('[data-login=error]')).to_contain_text('확인 불가')
    expect(page.locator('#fleet-account')).to_be_visible()
    expect(page.locator('#user-role')).to_have_attribute('title', 'alice · operator')
    page.unroute('**/api/fleet/auth/logout')
    page.locator('[data-login=logout]').click()
    expect(page.locator('#fleet-login')).to_be_visible()


def test_login_waits_for_session_readback_and_rejects_duplicate_submit(account_page):
    from playwright.sync_api import expect
    page, origin = account_page
    page.goto(origin + '/console/login?return=%2Fconsole%3Fview%3Dwork')
    _credentials(page)
    page.route('**/api/fleet/auth/session', lambda route: route.fulfill(status=503, body='{}'))
    writes = []
    page.on('request', lambda req: writes.append(req.url) if req.method == 'POST' else None)
    page.evaluate("""() => {
      document.querySelector('[data-login=submit]').click();
      document.querySelector('[data-login=form]').requestSubmit();
    }""")
    expect(page.locator('[data-login=error]')).to_contain_text('확인할 수 없습니다')
    expect(page.locator('[data-login=password]')).to_have_value('')
    expect(page.locator('[data-login=login]')).to_have_value('alice')
    assert '/console/login?' in page.url
    assert writes == [origin + '/api/fleet/auth/login']
