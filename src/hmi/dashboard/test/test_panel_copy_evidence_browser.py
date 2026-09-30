"""D-359 US-009 — robot panels speak Korean, carry evidence, and say a cause once.

Each test mounts one panel module against a fake store (`poll` callbacks the
test drives) the same way the shell does, with the shared /common/ assets.
"""

from __future__ import annotations

import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB_COMMON = ROOT.parent / "web_common"
pytestmark = pytest.mark.skipif(
    os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
    reason="set ROSY_RUN_BROWSER_TESTS=1 to run the optional Chromium regression",
)

PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="/common/tokens.css">
<link rel="stylesheet" href="/common/components.css">
<link rel="stylesheet" href="/assets/styles.css">
<link rel="stylesheet" href="/assets/panels/surface-panels.css">
<script type="module" src="/common/ui.js"></script>
</head><body><main id="root" class="surface-panel"></main></body></html>"""

MOUNT = """async ([module, role]) => {
  await customElements.whenDefined('ui-button');
  const {mount} = await import(module);
  const root = document.getElementById('root');
  const callbacks = {}; window.__callbacks = callbacks; window.__calls = [];
  window.__prompts = [];
  window.confirm = (text) => { window.__prompts.push(text); return false; };
  const store = {poll(path, interval, onData, onError) { callbacks[path] = {onData, onError, interval}; return () => {}; }};
  window.__unmount = mount(root, {role, store, surfaces: [],
    api: async (path, options) => { window.__calls.push(path); if (window.__api) return window.__api(path, options); return {}; }});
}"""


class _Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def translate_path(self, path):
        path = path.split("?", 1)[0]
        if path.startswith("/common/"):
            return str(WEB_COMMON / path.removeprefix("/common/"))
        if path.startswith("/assets/"):
            return str(ROOT / path.removeprefix("/assets/"))
        return super().translate_path(path)

    def do_GET(self):
        if self.path == "/__panel":
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, _format, *_args):
        pass


@pytest.fixture()
def panel():
    from playwright.sync_api import sync_playwright

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except Exception as error:  # pragma: no cover - depends on the local Chromium
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        opened = []

        def open_panel(module, role="operator", width=1366, height=900):
            page = browser.new_page(viewport={"width": width, "height": height})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{server.server_port}/__panel", wait_until="load")
            page.evaluate(MOUNT, [f"/assets/panels/{module}", role])
            opened.append(errors)
            return page

        yield open_panel
        browser.close()
    server.shutdown()
    server.server_close()
    for errors in opened:
        assert errors == []


def test_mode_panel_names_modes_in_korean_and_keeps_the_enum_in_title(panel):
    page = panel("console/mode.js")
    page.evaluate("""() => {
      __callbacks['/api/v1/robot/state'].onData({mode: 'MANUAL'});
      __callbacks['/api/v1/system/capabilities'].onData({navigation: {goal_navigation: true}});
    }""")
    status = page.locator("#root > ui-status").nth(0)
    assert status.inner_text() == "현재 모드: 수동"
    assert status.get_attribute("title") == "MANUAL"
    buttons = page.locator("[data-mode]")
    labels = [text.split("\n")[0] for text in buttons.all_inner_texts()]
    assert labels == ["대기", "수동", "내비게이션"]
    assert [buttons.nth(i).get_attribute("title") for i in range(3)] == ["IDLE", "MANUAL", "NAVIGATION"]
    page.locator('[data-mode="NAVIGATION"]').click()
    prompts = page.evaluate("window.__prompts")
    assert prompts and prompts[0].startswith("내비게이션 모드로 바꿀까요?")
    assert "NAVIGATION" not in prompts[0]


def test_overview_mode_and_navigation_carry_evidence_like_every_other_row(panel):
    page = panel("console/overview.js")
    page.evaluate("""() => {
      const ago = new Date(Date.now() - 7000).toISOString();
      __callbacks['/api/v1/robot/state'].onData({mode: 'MANUAL', navigation: 'NAVIGATING',
        pose: {x: 1, y: 2}, battery: {percent: 80},
        evidence: {navigation: {evidence: 'delayed', received_at: ago},
                   pose: {evidence: 'fresh'}, battery: {evidence: 'fresh'}}});
    }""")
    rows = page.locator("dl.ui-readout dd")
    mode, navigation = rows.nth(0), rows.nth(1)
    assert mode.inner_text() == "수동"
    assert mode.get_attribute("title") == "MANUAL"
    assert mode.get_attribute("data-evidence") == "fresh"
    assert navigation.get_attribute("data-evidence") == "delayed"
    assert navigation.inner_text().startswith("지연 · ") and navigation.inner_text().endswith("초 전")
    assert "NAVIGATING" not in page.inner_text("#root")

    page.evaluate("""() => __callbacks['/api/v1/robot/state'].onData({mode: 'IDLE', navigation: 'ARRIVED',
      evidence: {navigation: {evidence: 'disconnected'}}})""")
    assert rows.nth(1).inner_text() == "연결 끊김"
    assert rows.nth(1).get_attribute("data-evidence") == "disconnected"

    page.evaluate("""() => __callbacks['/api/v1/robot/state'].onData({mode: 'IDLE', navigation: 'ARRIVED',
      evidence: {navigation: {evidence: 'fresh'}}})""")
    assert rows.nth(1).inner_text() == "도착"
    assert rows.nth(1).get_attribute("title") == "ARRIVED"
