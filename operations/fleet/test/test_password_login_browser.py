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
                form = page.locator("#password-login [data-login=form]")
                expect(form).to_be_visible(timeout=15000)
                expect(page.locator("#token-access")).not_to_have_attribute("open", "")
                page.locator("#password-login [data-login=login]").fill("alice")
                page.locator("#password-login [data-login=password]").fill("wrong")
                page.locator("#password-login [data-login=submit]").click()
                expect(page.locator("#password-login [data-login=error]")).to_contain_text("맞지 않습니다")
                page.locator("#password-login [data-login=password]").fill("pw-1234")
                page.locator("#password-login [data-login=password]").press("Enter")
                expect(page.locator("#user-role")).to_contain_text("alice", timeout=15000)
                expect(page.locator("#password-login [data-login=principal]")).to_have_text("alice")
                assert page.evaluate("sessionStorage.getItem('rosy-console-token')") is None

                page.reload()
                expect(page.locator("#user-role")).to_contain_text("alice", timeout=15000)
                # D-540 2: every document reads the same login in the same header (#user-role, Korean role).
                for path in ("/console/install", "/console/site-map", "/console/cell"):
                    tab = context.new_page()
                    tab.goto(origin + path)
                    expect(tab.locator("#user-role")).to_contain_text("alice", timeout=15000)
                    expect(tab.locator("#user-role")).to_contain_text("운영자")
                    expect(tab.locator("#estop")).to_be_enabled()
                    tab.close()

                logout = page.locator("#password-login [data-login=logout]")
                if not logout.is_visible():  # compact widths fold principal and 로그아웃 behind 설정
                    page.locator("#topbar-more").click()
                logout.click()
                expect(page.locator("#user-role")).to_have_text("인증 필요", timeout=15000)
                expect(form).to_be_visible()
            finally:
                browser.close()
    finally:
        server.should_exit = True
        worker.join(timeout=20)
        listener.close()
        assert not worker.is_alive()
