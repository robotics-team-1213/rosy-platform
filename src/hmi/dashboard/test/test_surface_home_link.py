"""Role-surface brand returns to the dashboard home.

`/dashboard` owns the brand-as-home-link (`index.html`). The role surfaces
(`/console`, `/setup`, `/device`) render `surface.html`, whose topbar brand used
to be plain text — clicking the ROSY mark did nothing. These tests pin the link.
"""

from __future__ import annotations

import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[2]
BROWSER_GATE = pytest.mark.skipif(
    os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
    reason="set ROSY_RUN_BROWSER_TESTS=1 to run the optional Chromium regression",
)


class _Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(REPO_ROOT), **kwargs)

    def log_message(self, _format, *_args):
        pass


def test_the_role_surface_brand_is_a_link_to_the_dashboard_home():
    html = (ROOT / "surface.html").read_text(encoding="utf-8")
    brand = html.split("<ui-brand>", 1)[1].split("</ui-brand>", 1)[0]
    assert '<a href="/dashboard" aria-label="Rosy OS 대시보드 홈">' in brand
    assert "<b>ROSY</b>" in brand


def test_the_brand_link_keeps_the_surface_keyboard_focus_ring():
    shell = (ROOT / "shell" / "shell.css").read_text(encoding="utf-8")
    assert ("ui-brand a:focus-visible { outline: var(--focus-ring-width) solid "
            "var(--focus-ring); outline-offset: var(--focus-ring-offset-outer); }" in shell)


@BROWSER_GATE
def test_clicking_the_role_surface_brand_opens_the_dashboard_home():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{server.server_port}/src/hmi/dashboard/surface.html")
            page.route("**/dashboard", lambda route: route.fulfill(
                status=200, content_type="text/html",
                body='<!doctype html><html lang="ko"><body data-home="1"></body></html>'))
            page.click("ui-brand a")
            page.wait_for_function("() => document.body.dataset.home === '1'")
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
