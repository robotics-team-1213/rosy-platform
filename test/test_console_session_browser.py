"""Actual Console documents share a same-origin session and own their lock UI."""

from __future__ import annotations

from urllib.parse import urlparse

import pytest

from browser_harness import browser_tests_enabled, open_page
from test_fleet_console_browser import API, WEB, console_url  # noqa: F401 - shared HTTP fixture

pytestmark = pytest.mark.skipif(not browser_tests_enabled(),
                                reason="set ROSY_RUN_BROWSER_TESTS=1 for Chromium acceptance")


@pytest.mark.parametrize("first,second", [("index.html", "install.html"), ("install.html", "index.html")])
def test_console_documents_share_session_and_recover_from_expiry(console_url, first, second):
    from playwright.sync_api import sync_playwright

    requests = []
    accepted_token = "fleet-session-a"
    expired = False

    def serve_api(route):
        path = urlparse(route.request.url).path
        auth = route.request.headers.get("authorization")
        requests.append((path, route.request.method, auth))
        if expired or auth != f"Bearer {accepted_token}":
            route.fulfill(status=401, json={"detail": "unauthorized"})
            return
        body = {
            **API,
            "/api/fleet/session": {"principal_id": "local-operator", "role": "operator"},
            "/api/fleet/estop": {"stopped": 0, "total": 0, "robots": []},
            "/api/fleet/discovery": {"scanner_online": True, "devices": []},
            "/api/fleet/enrollment/robots": {"available": False, "robots": [], "alarms": []},
            "/api/fleet/vision/sources": {"sources": []},
        }.get(path)
        route.fulfill(status=200 if body is not None else 404,
                      json=body if body is not None else {"detail": "Not Found"})

    base = console_url.rsplit("/", 1)[0]
    with sync_playwright() as playwright:
        browser, page, errors = open_page(playwright, 1440, 900)
        page.route("**/api/**", serve_api)
        page.goto(f"{base}/{first}", wait_until="domcontentloaded")
        asset = first.replace(".html", ".js").replace("index.js", "console.js")
        assert page.request.get(f"{base}/console/assets/{asset}").body() == (WEB / asset).read_bytes()
        page.wait_for_function("document.querySelector('#user-role').textContent === '인증 필요'")
        page.fill("#console-token", accepted_token)
        page.locator("#token-save").click()
        page.wait_for_function("document.querySelector('#user-role').textContent.includes('local-operator')")
        page.goto(f"{base}/{second}", wait_until="domcontentloaded")
        asset = second.replace(".html", ".js").replace("index.js", "console.js")
        assert page.request.get(f"{base}/console/assets/{asset}").body() == (WEB / asset).read_bytes()
        page.wait_for_function("document.querySelector('#user-role').textContent.includes('local-operator')")
        assert page.input_value("#console-token") == accepted_token
        assert page.evaluate("localStorage.getItem('rosy-console-token')") is None

        expired = True
        page.locator("#estop").click()
        page.wait_for_function("document.querySelector('#user-role').textContent === '인증 필요'")
        posts = [row for row in requests if row[1] == "POST" and row[0] == "/api/fleet/estop"]
        assert posts == [("/api/fleet/estop", "POST", "Bearer fleet-session-a")]
        assert page.locator("#console-token").get_attribute("aria-invalid") == "true"

        accepted_token = "fleet-session-b"
        expired = False
        page.fill("#console-token", accepted_token)
        page.locator("#token-save").click()
        page.wait_for_function("document.querySelector('#user-role').textContent.includes('local-operator')")
        assert page.locator("#console-token").get_attribute("aria-invalid") is None
        # Reauthentication does not replay the command that received 401.
        assert len([row for row in requests if row[1] == "POST" and row[0] == "/api/fleet/estop"]) == 1
        page.locator("#estop").click()
        page.wait_for_function("document.querySelector('#log').textContent.includes('정지 요청 응답')")
        posts = [row for row in requests if row[1] == "POST" and row[0] == "/api/fleet/estop"]
        assert [row[2] for row in posts] == ["Bearer fleet-session-a", "Bearer fleet-session-b"]
        assert not errors
        browser.close()


def test_console_session_does_not_follow_the_document_to_another_origin(console_url):
    from playwright.sync_api import sync_playwright

    seen = []

    def serve_api(route):
        request = route.request
        auth = request.headers.get("authorization")
        seen.append((urlparse(request.url).hostname, auth))
        if auth != "Bearer origin-scoped-fleet":
            route.fulfill(status=401, json={"detail": "unauthorized"})
            return
        body = {**API, "/api/fleet/session": {"principal_id": "origin-operator", "role": "operator"}}
        response = body.get(urlparse(request.url).path)
        route.fulfill(status=200 if response else 404,
                      json=response if response else {"detail": "Not Found"})

    with sync_playwright() as playwright:
        browser, page, errors = open_page(playwright, 1440, 900)
        page.route("**/api/**", serve_api)
        page.goto(console_url, wait_until="domcontentloaded")
        page.fill("#console-token", "origin-scoped-fleet")
        page.locator("#token-save").click()
        page.wait_for_function("document.querySelector('#user-role').textContent.includes('origin-operator')")
        other_origin = console_url.replace("127.0.0.1", "localhost")
        page.goto(other_origin, wait_until="domcontentloaded")
        page.wait_for_function("document.querySelector('#user-role').textContent === '인증 필요'")
        assert page.input_value("#console-token") == ""
        assert page.evaluate("sessionStorage.getItem('rosy-console-token')") is None
        assert all(auth is None for host, auth in seen if host == "localhost")
        assert any(host == "localhost" for host, _auth in seen)
        page.goto(console_url, wait_until="domcontentloaded")
        page.wait_for_function("document.querySelector('#user-role').textContent.includes('origin-operator')")
        assert page.input_value("#console-token") == "origin-scoped-fleet"
        assert not errors
        browser.close()
