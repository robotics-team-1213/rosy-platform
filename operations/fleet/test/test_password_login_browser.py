"""D-519 6 — paired console login with 아이디·비밀번호 in real Chromium: reload and new tab keep it, logout ends it."""

import threading
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


pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in Chromium scenario")
ROOT = Path(__file__).resolve().parents[3]


def test_console_login_survives_reload_and_new_tab_then_logs_out(tmp_path):
    from playwright.sync_api import expect, sync_playwright

    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "robot-only")],
                           [FakeRobot("rosy_01")])
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids=console.robot_ids)
    app = create_app(console, task_service=tasks, site_users={}, site_logins={"alice": {
        "principal_id": "alice", "role": "operator", "password_scrypt": hash_password("pw-1234")}},
        web_common=ROOT / "shared" / "web", start_task_dispatcher=False)
    listener = safe_listener()
    # Chromium keeps Secure cookies from http://localhost (a potentially trustworthy origin).
    origin = f"http://localhost:{listener.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", timeout_graceful_shutdown=3))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 20
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context()
                page = context.new_page()
                page.goto(origin + "/console")
                page.locator('#fleet-login').click()
                form = page.locator("#password-login [data-login=form]")
                expect(form).to_be_visible(timeout=15000)
                expect(page.get_by_role('region', name='관제 로그인')).to_be_visible()
                for width in (320, 390, 1440):
                    page.set_viewport_size({'width': width, 'height': 844})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    assert page.locator('[data-login=login]').bounding_box()['height'] >= 44
                    assert page.locator('[data-login=password]').bounding_box()['height'] >= 44
                page.keyboard.press('Tab')
                expect(page.locator('.skip-link')).to_be_focused()
                page.keyboard.press('Enter')
                expect(page.locator('#login-main')).to_be_focused()
                expect(page.locator('#token-access')).to_have_count(0)
                page.locator("#password-login [data-login=login]").fill("alice")
                page.locator("#password-login [data-login=password]").fill("wrong")
                page.locator("#password-login [data-login=submit]").click()
                expect(page.locator("#password-login [data-login=error]")).to_contain_text("맞지 않습니다")
                expect(page.locator('[data-login=password]')).to_have_value('')
                page.locator("#password-login [data-login=password]").fill("pw-1234")
                page.locator("#password-login [data-login=password]").press("Enter")
                expect(page.locator("#user-role")).to_have_attribute("title", "alice · operator", timeout=15000)
                page.locator('#topbar-more').click()
                expect(page.locator('#fleet-account-identity')).to_contain_text('alice')
                page.locator('#topbar-more').click()
                assert page.evaluate("sessionStorage.getItem('rosy-console-token')") is None

                page.reload()
                expect(page.locator("#user-role")).to_have_attribute("title", "alice · operator", timeout=15000)
                # D-540 2: every document reads the same login in the same header (#user-role, Korean role).
                for path in ("/console", "/console/install", "/console/site-map", "/console/cell"):
                    tab = context.new_page()
                    tab.goto(origin + path)
                    expect(tab.locator("#user-role")).to_have_attribute("title", "alice · operator", timeout=15000)
                    expect(tab.locator("#user-role")).to_contain_text("운영자")
                    expect(tab.locator("#estop")).to_be_enabled()
                    for width in (320, 390, 480, 640, 768, 1366, 1440, 1920):
                        tab.set_viewport_size({"width": width, "height": 900})
                        toggle = tab.locator("#topbar-more")
                        if toggle.is_visible() and toggle.get_attribute("aria-expanded") == "true":
                            toggle.click()
                        principal = tab.locator("#fleet-account-identity")
                        expect(principal).to_be_hidden()
                        # D-741 3: the link seat holds no control; the account button sits with the alerts button.
                        assert tab.locator('[data-header-region="status"] ui-button').count() == 0
                        assert tab.locator('[data-header-region="actions"] > #topbar-more').count() == 1
                        height = tab.locator("ui-topbar").bounding_box()["height"]
                        toggle.click()
                        expect(principal).to_be_visible()
                        expect(tab.locator("#fleet-account [data-login=logout]")).to_be_visible()
                        assert tab.evaluate("document.documentElement.scrollWidth <= innerWidth")
                        toggle.click()
                        assert tab.locator("ui-topbar").bounding_box()["height"] == height
                    tab.close()

                page.locator('#topbar-more').click()
                logout = page.locator("#fleet-account [data-login=logout]")
                expect(logout).to_be_visible()
                logout.click()
                expect(page.locator("#user-role")).to_have_text("인증 필요", timeout=15000)
                expect(page.locator('#fleet-login')).to_be_visible()
                expect(page.locator('#fleet-account')).to_be_hidden()
            finally:
                browser.close()
    finally:
        server.should_exit = True
        worker.join(timeout=20)
        listener.close()
        assert not worker.is_alive()
