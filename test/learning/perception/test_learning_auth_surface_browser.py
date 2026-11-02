"""The real review server's anonymous account entry has one clear next action."""
import threading

import pytest

from browser_harness import browser_tests_enabled, free_port, open_page
from review_app import make_server
from test_review_app import open_store


pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="requires explicit Chromium browser run")


@pytest.mark.parametrize("width", [320, 1366])
@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("session_status", [401, 403])
@pytest.mark.parametrize("text_scale", [1, 2, 4])
def test_anonymous_account_entry_separates_login_from_denied_access(tmp_path, width, theme, session_status, text_scale):
    api = pytest.importorskip("playwright.sync_api")
    folder = tmp_path / "review"
    folder.mkdir()
    server = make_server(open_store(folder), free_port())
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    try:
        with api.sync_playwright() as runtime:
            browser, page, errors = open_page(runtime, width, 844, url=origin)
            try:
                page.route("**/api/accounts/options", lambda route: route.fulfill(
                    json={"enabled": True, "rosy_account": True, "oauth": False}))
                page.route("**/api/accounts/session", lambda route: route.fulfill(
                    status=session_status, json={"error": "프로젝트 접근 권한을 확인하세요."}))
                page.goto(origin + "/accounts", wait_until="domcontentloaded")
                page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
                status = page.locator("#account-status")
                api.expect(status).to_have_attribute("state", "empty" if session_status == 401 else "forbidden")
                page.evaluate('(scale) => document.documentElement.style.fontSize = `${scale * 100}%`', text_scale)
                api.expect(page.locator("h1")).to_have_count(1)
                api.expect(page.locator(".ui-rail")).to_be_hidden()
                api.expect(page.locator("#review-command-open")).to_be_hidden()
                login = page.get_by_role("link", name="Rosy Account로 로그인", exact=True)
                if session_status == 401:
                    api.expect(login).to_be_visible()
                    assert login.bounding_box()["height"] >= 48
                    api.expect(page.locator("#account-retry")).to_be_hidden()
                    api.expect(status).to_be_hidden()
                    page.keyboard.press("Tab")
                    page.keyboard.press("Enter")
                    api.expect(page.locator("#accounts-main")).to_be_focused()
                    page.keyboard.press("Tab")
                    api.expect(login).to_be_focused()
                else:
                    api.expect(page.get_by_role("link", name="다른 계정으로 로그인")).to_be_visible()
                    api.expect(page.locator("#account-login")).to_have_attribute("data-kind", "quiet")
                    api.expect(page.locator("#account-retry")).to_be_visible()
                    api.expect(status).to_contain_text("접근할 권한이 없습니다")
                    assert page.url == origin + "/accounts"
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert not errors, errors
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
