"""D-457: camera map coordinates and source transitions in the actual console DOM."""

import os
from urllib.parse import urlparse

import pytest

from browser_harness import open_page
from test_fleet_console_browser import console_url  # noqa: F401
from test_console_lifetime_browser import _serve_api

pytestmark = pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
                                reason="set ROSY_RUN_BROWSER_TESTS=1 for Chromium acceptance")


def test_coordinates_switch_from_marker_to_anonymous_and_clear_when_stale(console_url):  # noqa: F811
    from playwright.sync_api import sync_playwright

    body = {"sources": [{"source_id": "north", "status": "OK", "fps": 3}],
            "robots": [{"robot_id": "rosy_01", "status": "MARKER",
                        "camera": {"x": -1.234, "y": .456}, "pose": None, "offset_m": None}],
            "unknown": []}

    def serve(route):
        if urlparse(route.request.url).path == "/api/fleet/tracking":
            route.fulfill(status=200, json=body)
        else:
            _serve_api(route)

    with sync_playwright() as playwright:
        browser, page, errors = open_page(playwright, 1440, 900)
        page.add_init_script("sessionStorage.setItem('rosy-console-token', 'tracking-browser')")
        page.route("**/api/**", serve)
        page.goto(console_url, wait_until="domcontentloaded")
        row = page.locator("#tracking-position-rows tr").first
        page.wait_for_function("document.querySelector('#tracking-position-rows').textContent.includes('rosy_01')")
        assert row.locator("td").all_text_contents() == ["rosy_01", "-1.23", "0.46", "마커 관측"]

        body["robots"] = []
        body["unknown"] = [{"x": .25, "y": -.5}]
        page.wait_for_function("document.querySelector('#tracking-position-rows').textContent.includes('미확인')")
        assert row.locator("td").all_text_contents() == ["미확인 1", "0.25", "-0.50", "무마커 추론 · 이름 미확정"]
        assert "rosy_01" not in page.locator("#tracking-position-rows").inner_text()

        body["unknown"] = []
        body["sources"][0]["status"] = "STALE"
        page.wait_for_function("document.querySelector('#tracking-positions').hidden")
        assert page.locator("#tracking-position-rows tr").count() == 0
        assert not errors
        browser.close()


def test_position_expires_even_when_the_next_poll_never_returns(console_url):  # noqa: F811
    from playwright.sync_api import sync_playwright

    requests = []
    body = {"lease_s": 1, "sources": [{"source_id": "north", "status": "OK", "age_ms": 200}],
            "robots": [], "unknown": [{"x": .25, "y": -.5}]}

    def serve(route):
        if urlparse(route.request.url).path == "/api/fleet/tracking":
            requests.append(route)
            if len(requests) == 1:
                route.fulfill(status=200, json=body)
        else:
            _serve_api(route)

    with sync_playwright() as playwright:
        browser, page, errors = open_page(playwright, 1440, 900)
        page.add_init_script("sessionStorage.setItem('rosy-console-token', 'tracking-browser')")
        page.route("**/api/**", serve)
        page.goto(console_url, wait_until="domcontentloaded")
        page.wait_for_function("!document.querySelector('#tracking-positions').hidden")
        page.wait_for_function("document.querySelector('#tracking-positions').hidden")
        assert page.locator("#tracking-position-rows tr").count() == 0
        assert not errors
        browser.close()


def test_background_relearn_requires_the_owned_confirmation(console_url):  # noqa: F811
    from playwright.sync_api import sync_playwright

    posts = []
    body = {"sources": [{"source_id": "north", "status": "OK", "fps": 3}],
            "robots": [], "unknown": []}

    def serve(route):
        path = urlparse(route.request.url).path
        if path == "/api/fleet/tracking":
            route.fulfill(status=200, json=body)
        elif path == "/api/fleet/tracking/relearn":
            posts.append(route.request.post_data_json)
            route.fulfill(status=200, json={})
        else:
            _serve_api(route)

    with sync_playwright() as playwright:
        browser, page, errors = open_page(playwright, 1440, 900)
        page.add_init_script("sessionStorage.setItem('rosy-console-token', 'tracking-browser')")
        page.route("**/api/**", serve)
        page.goto(console_url, wait_until="domcontentloaded")
        button = page.locator("#tracking-relearn")
        button.wait_for(state="visible")
        button.click()
        dialog = page.locator("dialog.ui-confirm")
        dialog.wait_for()
        assert not posts
        dialog.locator('ui-button[kind=quiet]').click()
        dialog.wait_for(state="detached")
        assert not posts
        button.click()
        dialog.wait_for()
        dialog.locator('ui-button[kind=irreversible]').click()
        page.wait_for_function("document.querySelector('#tracking-state').dataset.state === 'warn'")
        assert posts == [{"source_id": "north"}]
        assert not errors
        browser.close()
