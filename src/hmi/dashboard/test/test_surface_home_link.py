"""Role-surface brand returns to the dashboard home — as a shared behaviour.

The home link is not page markup: `ui-brand href` (D-333) makes web_common's
shared element wrap its children in one link, and components.css owns the hover
and focus states. These tests pin the declaration on the surface, the shared
behaviour, and the real click-through.
"""

from __future__ import annotations

import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
WEB_COMMON = ROOT.parent / "web"
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


def test_the_role_surface_declares_the_home_link_on_the_shared_brand():
    html = (ROOT / "surface.html").read_text(encoding="utf-8")
    assert '<ui-brand href="/dashboard" aria-label="Rosy OS 대시보드 홈">' in html
    assert "<a " not in html.split("<ui-topbar>", 1)[1].split("</ui-topbar>", 1)[0], (
        "topbar는 앵커를 따로 적지 않는다 — ui-brand href가 링크를 만든다"
    )


def test_the_home_link_states_live_in_the_shared_stylesheet():
    components = (WEB_COMMON / "components.css").read_text(encoding="utf-8")
    shell = (ROOT / "shell" / "shell.css").read_text(encoding="utf-8")
    assert "ui-brand a:hover b" in components
    assert "ui-brand a:focus-visible" in components
    assert "outline: var(--focus-ring-width) solid var(--focus-ring);" in components
    assert "ui-brand a" not in shell, "브랜드 링크 상태는 표면 CSS에 복제되지 않는다"


@BROWSER_GATE
def test_clicking_the_role_surface_brand_opens_the_dashboard_home():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            # 정적 서버에는 /common/*가 없다 — 공용 ui.js를 실제 파일로 대신 준다.
            page.route("**/common/ui.js", lambda route: route.fulfill(
                status=200, content_type="text/javascript",
                body=(WEB_COMMON / "ui.js").read_text(encoding="utf-8")))
            page.route("**/dashboard", lambda route: route.fulfill(
                status=200, content_type="text/html",
                body='<!doctype html><html lang="ko"><body data-home="1"></body></html>'))
            page.goto(f"http://127.0.0.1:{server.server_port}/src/hmi/dashboard/surface.html")
            page.click("ui-brand a")
            page.wait_for_function("() => document.body.dataset.home === '1'")
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
