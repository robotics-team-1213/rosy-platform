"""The /dashboard bridge offers the caller's role surfaces.

Critique P1 (2026-09-26): /dashboard stays the authentication bridge, and its
destination must be explicit. The bridge renders the same manifest `surfaces`
metadata the role surfaces' own switch uses — one declarative source, filtered
server-side by role; the client only draws registered role surfaces.
"""

from __future__ import annotations

from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from threading import Thread

import pytest
from browser_harness import browser_tests_enabled, safe_http_server
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[2]
BROWSER_GATE = pytest.mark.skipif(
    not browser_tests_enabled(),
    reason="set ROSY_RUN_BROWSER_TESTS=1 to run the optional Chromium regression",
)


class _Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(REPO_ROOT), **kwargs)

    def log_message(self, _format, *_args):
        pass


def test_the_home_declares_the_role_surface_destination():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert '<nav id="surface-bridge" class="surface-bridge" aria-label="역할 화면" hidden></nav>' in html


def test_the_bridge_draws_only_registered_role_surfaces_from_the_manifest():
    source = (ROOT / "surface-navigation.js").read_text(encoding="utf-8")
    assert "export function dashboardSurfaceBridge(nav, surfaces)" in source
    assert "ROLE_SURFACES.has(`/${surface.id}`)" in source, (
        "등록되지 않은 표면으로 걸어 나가면 안 된다 — return_to 허용과 같은 대장"
    )
    assert "nav.replaceChildren(...links)" in source
    assert "nav.hidden = links.length === 0" in source


def test_the_shell_wires_the_bridge_to_the_callers_identity():
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    assert 'import { completeDashboardAuthentication, dashboardSurfaceBridge } from "./surface-navigation.js";' in app
    assert 'api("/api/v1/ui/surfaces/console", {signal: owner.signal})' in app, (
        "역할 추측 금지 — 목록은 console 매니페스트(viewer까지 200)가 말한다"
    )
    identity = app.split("async function detectRole(owner = authTicket())", 1)[1]
    identity = identity.split("async function refreshSurfaceBridge(owner = authTicket())", 1)[0]
    assert "await refreshSurfaceBridge(owner);" in identity
    assert identity.index('await api("/api/v1/auth/whoami"') < identity.index("await refreshSurfaceBridge(owner);")
    bridge = app.split("async function refreshSurfaceBridge(owner = authTicket())", 1)[1].split("function renderIdentity()", 1)[0]
    fetched = bridge.split('await api("/api/v1/ui/surfaces/console", {signal: owner.signal})', 1)[1]
    assert fetched.index("if (!owner.current()) return;") < fetched.index("dashboardSurfaceBridge(nav, manifest?.surfaces)")
    render = app.split("function renderIdentity()", 1)[1].split("\n}", 1)[0]
    assert 'dashboardSurfaceBridge(elements["surface-bridge"], []);' in render, (
        "로그아웃·만료 뒤에는 목적지도 비워야 한다"
    )


def test_the_bridge_stays_a_quiet_topbar_link_and_owns_its_states():
    # D-362 P1: the shell ships two linked sheets; responsive rules live in the
    # detail sheet, so read them concatenated in link order (like dashboard_css).
    css = (ROOT / "styles.css").read_text(encoding="utf-8") + "\n" \
        + (ROOT / "console-detail.css").read_text(encoding="utf-8")
    assert ".surface-bridge a" in css
    assert ".surface-bridge a:hover" in css
    assert ".surface-bridge a:focus-visible" in css
    assert "var(--target-secondary)" in css
    mobile = css.split("@media (width < 64rem) {", 1)[1]
    assert "flex-wrap: wrap" in mobile, "좁은 폭에서는 목적지 줄이 아래로 내려간다"


@BROWSER_GATE
def test_the_bridge_builder_draws_manifest_surfaces_and_hides_when_empty():
    server = safe_http_server(_Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{server.server_port}/middleware/ui/robot/surface-navigation.js",
                      wait_until="load")
            outcome = page.evaluate("""async () => {
              const nav = document.createElement('nav');
              document.body.append(nav);
              const bridge = await import('/middleware/ui/robot/surface-navigation.js');
              bridge.dashboardSurfaceBridge(nav, [
                {id: 'console', title: '운용'},
                {id: 'setup', title: '작업 준비'},
                {id: 'garage', title: '외부 표면'},
                null,
              ]);
              const drawn = [...nav.querySelectorAll('a')].map((a) => [a.getAttribute('href'), a.textContent]);
              const hiddenWhenEmpty = (() => {
                bridge.dashboardSurfaceBridge(nav, []);
                return nav.hidden && nav.querySelectorAll('a').length === 0;
              })();
              bridge.dashboardSurfaceBridge(nav, [{id: 'console', title: '운용'}]);
              return {drawn, hiddenWhenEmpty, visible: !nav.hidden};
            }""")
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert outcome["drawn"] == [["/console", "운용"], ["/setup", "작업 준비"]], outcome
    assert outcome["hiddenWhenEmpty"] is True
    assert outcome["visible"] is True


@BROWSER_GATE
def test_clicking_a_bridge_link_opens_the_role_surface():
    server = safe_http_server(_Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.route("**/console", lambda route: route.fulfill(
                status=200, content_type="text/html",
                body='<!doctype html><html lang="ko"><body data-console="1"></body></html>'))
            page.goto(f"http://127.0.0.1:{server.server_port}/middleware/ui/robot/surface-navigation.js",
                      wait_until="load")
            page.evaluate("""async () => {
              const nav = document.createElement('nav');
              nav.id = 'surface-bridge';
              document.body.append(nav);
              nav.hidden = false;
              const bridge = await import('/middleware/ui/robot/surface-navigation.js');
              bridge.dashboardSurfaceBridge(nav, [{id: 'console', title: '운용'}]);
            }""")
            page.click('#surface-bridge a[href="/console"]')
            page.wait_for_function("() => document.body.dataset.console === '1'")
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
