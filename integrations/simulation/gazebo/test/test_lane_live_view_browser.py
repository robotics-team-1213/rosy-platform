"""Opt-in browser contract for the read-only Gazebo viewer tabs (D-306)."""

import os
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
    reason="set ROSY_RUN_BROWSER_TESTS=1 for the Chromium accessibility check",
)

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture()
def viewer_url():
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(SCRIPTS), **kwargs)

        def log_message(self, *args):
            pass

    for port in range(40100, 40200):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        except OSError:
            continue
        break
    else:
        raise RuntimeError("could not allocate a browser-safe local port")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/lane_live_view.html"
    server.shutdown()


def test_view_tabs_have_keyboard_and_panel_contract(viewer_url):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(viewer_url, wait_until="domcontentloaded")
        page.locator("#tab-live").focus()
        page.keyboard.press("ArrowRight")
        assert page.evaluate("document.activeElement?.id") == "tab-results"
        assert page.locator("#tab-results").get_attribute("aria-selected") == "true"
        assert page.locator("#tab-results").get_attribute("aria-controls") == "results"
        assert page.locator("#results").get_attribute("role") == "tabpanel"
        assert page.locator("#results").is_visible()
        assert not page.locator("#live").is_visible()
        page.keyboard.press("Home")
        assert page.evaluate("document.activeElement?.id") == "tab-live"
        assert page.locator("#tab-live").get_attribute("aria-selected") == "true"
        assert page.locator("#live").is_visible()
        browser.close()
