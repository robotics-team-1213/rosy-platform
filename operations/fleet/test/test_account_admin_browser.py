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
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", timeout_graceful_shutdown=3, log_config=None))
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
                # D-955: a new account starts from the team default bundle.
                expect(page.locator("#account-grants > fieldset")).to_have_count(3)
                for index, value in enumerate(["test-site", "*", "*"]):
                    expect(page.locator("[data-grant=id]").nth(index)).to_have_value(value)
                for label in ['관제 조회', '관제 조작', '게임 조작', '로봇 조회', '로봇 조작', '학습 조회', '학습 편집', '데이터 가져오기']:
                    expect(page.get_by_label(label, exact=True)).to_be_checked()
                for label in ['계정 관리', '관제 정책', '카메라 관리', '로봇 관리', '학습 승인', '모델 게시', '프로젝트 관리']:
                    expect(page.get_by_label(label, exact=True)).not_to_be_checked()
                expect(page.locator("#account-role")).to_have_value("operator")
                # Choosing a role swaps the editor to that role's bundle.
                page.locator("#account-role").select_option("policy-admin")
                for label in ['계정 관리', '관제 정책', '카메라 관리', '로봇 관리', '학습 승인', '모델 게시', '프로젝트 관리']:
                    expect(page.get_by_label(label, exact=True)).to_be_checked()
                expect(page.get_by_label('Vault 조회', exact=True)).not_to_be_checked()
                page.locator("#account-role").select_option("viewer")
                for label in ['관제 조회', '로봇 조회', '학습 조회']:
                    expect(page.get_by_label(label, exact=True)).to_be_checked()
                for label in ['관제 조작', '로봇 조작', '학습 편집', '계정 관리']:
                    expect(page.get_by_label(label, exact=True)).not_to_be_checked()
                page.locator("#account-role").select_option("operator")
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
                # An existing account keeps its hand-tuned grants unless the admin confirms the role bundle.
                page.once("dialog", lambda dialog: dialog.dismiss())
                page.locator("#account-role").select_option("viewer")
                expect(page.locator("#account-role")).to_have_value("operator")
                expect(page.get_by_label('Vault 조회', exact=True)).to_be_checked()
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
                assert bob["grants"] == [
                    {"resource": "site:test-site", "capabilities": [
                        "fleet.read", "fleet.operate", "games.operate", "vault.read", "vault.operate", "vault.manage"]},
                    {"resource": "robot:*", "capabilities": ["robot.read", "robot.operate"]},
                    {"resource": "project:*", "capabilities": ["learning.view", "learning.edit", "learning.import"]}]
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
