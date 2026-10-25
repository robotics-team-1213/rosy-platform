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


@pytest.mark.parametrize('managed', [True, False])
def test_account_administration_uses_real_ledger(tmp_path, managed):
    from playwright.sync_api import expect, sync_playwright
    base, tasks = _app(tmp_path)
    app = create_app(base.state.console, task_service=tasks, site_users={},
                     site_logins=_accounts(role='policy-admin'),
                     web_common=default_web_common(), start_task_dispatcher=False)
    sessions = app.state.password_sessions
    if managed:
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
                expect(page.locator('#account-setup')).to_be_visible()
                expect(page.locator('#account-setup-state')).to_contain_text('아직 설정되지 않았습니다')
                page.get_by_text('최초 설정과 앱 추가 방법', exact=True).click()
                expect(page.get_by_role('link', name='서버 설치 안내')).to_be_visible()
                if not managed:
                    expect(page.locator('#account-content')).to_be_hidden()
                    page.locator('#account-setup-reload').click()
                    expect(page.locator('#account-setup')).to_be_visible()
                    page.evaluate("window.dispatchEvent(new StorageEvent('storage', {key:'rosy.fleet.account.identity', newValue:'changed'}))")
                    expect(page.locator('#account-setup')).to_be_hidden()
                    return
                expect(page.locator("#account-content")).to_be_visible()
                page.locator("#account-name").fill("bob")
                page.locator("#account-principal").fill("bob")
                page.locator("#account-password").fill("bob!")
                page.locator("#account-add-grant").click()
                page.locator("[data-grant=id]").fill("test-site")
                page.get_by_label("관제 조회", exact=True).check()
                for label in ['Vault 조회', 'Vault 조작', 'Vault 장부 정리']:
                    expect(page.get_by_label(label, exact=True)).not_to_be_checked()
                    page.get_by_label(label, exact=True).check()
                page.locator("#account-save").click()
                expect(page.locator("#account-list")).to_contain_text("bob")
                expect(page.locator("#account-password")).to_have_value("")
                page.get_by_role("button", name="bob · 사용 중", exact=True).click()
                page.locator("#account-reset-password").fill("bob!")
                page.locator("#account-reset").click()
                expect(page.locator("#account-status")).to_contain_text("처리했습니다")
                bob_page = browser.new_page()
                try:
                    bob_page.goto(origin + "/console/login?return=%2Fconsole%2Fprofile")
                    bob_page.locator("[data-login=login]").fill("bob")
                    bob_page.locator("[data-login=password]").fill("bob!")
                    bob_page.locator("[data-login=submit]").click()
                    expect(bob_page.locator("[data-login=confirm]")).to_be_visible()
                    bob_page.locator("[data-login=password]").fill("a permanent secret")
                    bob_page.locator("[data-login=confirm]").fill("a permanent secret")
                    bob_page.locator("[data-login=submit]").click()
                    expect(bob_page).to_have_url(origin + "/console/profile")
                    for label in ['Vault 조회', 'Vault 조작', 'Vault 장부 정리']:
                        expect(bob_page.locator('#profile-grant-list')).to_contain_text(label)
                finally:
                    bob_page.close()
                page.locator("#account-reload").click()
                expect(page.locator("#account-heading")).to_have_text("새 계정")
                page.get_by_role("button", name="bob · 사용 중", exact=True).click()
                page.locator("#account-revoke").click()
                expect(page.locator("#account-heading")).to_have_text("새 계정")
                page.get_by_role("button", name="bob · 사용 중", exact=True).click()
                value = next(c["value"] for c in page.context.cookies() if c["name"] == "rosy_fleet_session")
                bob = next(row for row in sessions.list_accounts(value) if row["login"] == "bob")
                sessions.update_account(value, bob["account_id"], revision=bob["revision"], role="operator")
                page.locator("#account-enabled").uncheck()
                page.locator("#account-save").click()
                expect(page.locator("#account-status")).to_contain_text("다른 관리자가 변경했습니다")
                page.locator("#account-reload").click()
                expect(page.locator("#account-heading")).to_have_text("새 계정")
                page.get_by_role("button", name="bob · 사용 중", exact=True).click()
                page.locator("#account-enabled").uncheck()
                page.locator("#account-save").click()
                expect(page.locator("#account-list")).to_contain_text("bob · 정지됨")
                bob = next(row for row in sessions.list_accounts(value) if row["login"] == "bob")
                assert bob["enabled"] is False and bob["revision"] == 6
                assert bob["grants"] == [{"resource": "site:test-site", "capabilities": [
                    "fleet.read", "vault.read", "vault.operate", "vault.manage"]}]
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.goto(origin + "/console")
                expect(page.locator("#fleet-accounts")).to_have_js_property("hidden", False)
            finally:
                browser.close()
    finally:
        server.should_exit = True
        worker.join(timeout=20)
        listener.close()
        assert not worker.is_alive()
