"""Role-surface authentication return-path browser contract."""

from __future__ import annotations

import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[2]
pytestmark = pytest.mark.skipif(
    os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
    reason="set ROSY_RUN_BROWSER_TESTS=1 to run the optional Chromium regression",
)


class _Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(REPO_ROOT), **kwargs)

    def log_message(self, _format, *_args):
        pass


def test_role_surface_keyboard_can_skip_to_named_main_content():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{server.server_port}/src/hmi/dashboard/surface.html")
            page.keyboard.press("Tab")
            assert page.locator(":focus").get_attribute("href") == "#surface-main"
            page.keyboard.press("Enter")
            assert page.locator(":focus").get_attribute("id") == "surface-main"
            assert page.get_by_role("heading", level=1).count() == 1
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_auth_return_target_allows_only_registered_local_surfaces():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{server.server_port}/", wait_until="load")
            allowed = page.evaluate("""async () => {
              const nav = await import('/src/hmi/dashboard/surface-navigation.js');
              const targets = ['/console','/setup','/device','https://evil.example','//evil.example','/dashboard','/console?x=1']
                .map((path) => nav.dashboardReturnTarget(`?return_to=${encodeURIComponent(path)}`));
              const fakeLocation = {pathname:'/dashboard', search:'?return_to=%2Fsetup', replace:(path) => { window.__replaced = path; }};
              const redirected = nav.completeDashboardAuthentication(fakeLocation);
              const invalidLocation = {pathname:'/dashboard', search:'?return_to=https%3A%2F%2Fevil.example', replace:() => { window.__invalidReplaced = true; }};
              const invalidRedirected = nav.completeDashboardAuthentication(invalidLocation);
              return {targets, href:nav.dashboardLoginHref('/device'), redirected, replaced:window.__replaced,
                invalidRedirected, invalidReplaced:window.__invalidReplaced || null};
            }""")
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert allowed["targets"] == ["/console", "/setup", "/device", None, None, None, None]
    assert allowed["href"] == "/dashboard?return_to=%2Fdevice"
    assert allowed["redirected"] is True
    assert allowed["replaced"] == "/setup"
    assert allowed["invalidRedirected"] is False
    assert allowed["invalidReplaced"] is None
