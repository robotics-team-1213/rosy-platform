"""Real Chromium account creation, grants, reset, revocation and durable readback."""
import threading
import time

import pytest
import uvicorn
from browser_harness import browser_tests_enabled, safe_listener
from test_password_session import _app, _accounts
from fleet.server.app import create_app
from fleet.cli import default_web_common


pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in Chromium account scenario")


def test_account_administration_uses_real_ledger(tmp_path):
    from playwright.sync_api import expect, sync_playwright
    base, tasks = _app(tmp_path)
    app = create_app(base.state.console, task_service=tasks, site_users={}, site_logins=_accounts(),
                     web_common=default_web_common(), start_task_dispatcher=False)
    sessions = app.state.password_sessions
    sessions.bootstrap_accounts("alice", "test-site")
    listener = safe_listener()
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
                page = browser.new_page(viewport={"width": 390, "height": 844})
                page.goto(origin + "/console/login?return=%2Fconsole%2Faccounts")
                page.locator("[data-login=login]").fill("alice")
                page.locator("[data-login=password]").fill("correct horse")
                page.locator("[data-login=submit]").click()
                expect(page).to_have_url(origin + "/console/accounts")
                expect(page.locator("#account-content")).to_be_visible()
                page.locator("#account-name").fill("bob")
                page.locator("#account-principal").fill("bob")
                page.locator("#account-password").fill("temporary secret")
                page.locator("#account-add-grant").click()
                page.locator("[data-grant=id]").fill("test-site")
                page.get_by_label("관제 조회", exact=True).check()
                page.locator("#account-save").click()
                expect(page.locator("#account-list")).to_contain_text("bob")
                expect(page.locator("#account-password")).to_have_value("")
                page.get_by_role("button", name="bob · 사용 중", exact=True).click()
                page.locator("#account-reset-password").fill("new temporary secret")
                page.locator("#account-reset").click()
                expect(page.locator("#account-status")).to_contain_text("처리했습니다")
                page.get_by_role("button", name="bob · 사용 중", exact=True).click()
                page.locator("#account-revoke").click()
                expect(page.locator("#account-heading")).to_have_text("새 계정")
                page.get_by_role("button", name="bob · 사용 중", exact=True).click()
                page.locator("#account-enabled").uncheck()
                page.locator("#account-save").click()
                expect(page.locator("#account-list")).to_contain_text("bob · 정지됨")
                value = next(c["value"] for c in page.context.cookies() if c["name"] == "rosy_fleet_session")
                bob = next(row for row in sessions.list_accounts(value) if row["login"] == "bob")
                assert bob["enabled"] is False and bob["revision"] == 4
                assert bob["grants"] == [{"resource": "site:test-site", "capabilities": ["fleet.read"]}]
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            finally:
                browser.close()
    finally:
        server.should_exit = True
        worker.join(timeout=20)
        listener.close()
        assert not worker.is_alive()
