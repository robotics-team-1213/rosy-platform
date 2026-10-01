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


CAUSE = "호스트 에이전트에 연결할 수 없어"


def _holders(page, text):
    """Elements whose own text (not a descendant's) says `text`, visible or not."""
    return page.evaluate("""(text) => [...document.querySelectorAll('#root *')].filter((node) =>
      [...node.childNodes].some((child) => child.nodeType === 3 && child.textContent.includes(text)))
      .map((node) => ({id: node.id, hidden: node.hidden || !node.offsetParent}))""", text)


def test_host_agent_outage_is_said_once_and_buttons_point_at_it(panel):
    page = panel("host/operations.js", role="administrator")
    page.evaluate("""() => {
      const down = {available: false, code: 'HOST_AGENT_UNAVAILABLE', evidence: {evidence: 'disconnected'}};
      __callbacks['/api/v1/host/network'].onData(down);
      __callbacks['/api/v1/host/release'].onData(down);
    }""")
    visible = [row for row in _holders(page, CAUSE) if not row["hidden"]]
    assert len(visible) == 1, _holders(page, CAUSE)
    group = page.locator(f"#{visible[0]['id']}")
    assert group.inner_text() == ("호스트 에이전트에 연결할 수 없어 네트워크·릴리스 작업을 막았습니다. "
                                  "장치 전원과 서비스를 확인하세요.")
    buttons = page.locator("ui-button")
    assert buttons.count() == 6
    for i in range(6):
        button = buttons.nth(i)
        assert button.evaluate("b => b.disabled")
        assert button.get_attribute("reason") == "위 사유"
        assert visible[0]["id"] in button.get_attribute("aria-describedby").split()
    assert "Host Agent" not in page.inner_text("#root")

    # Only the network agent is down: its own section note says it, once.
    page.evaluate("""() => __callbacks['/api/v1/host/release'].onData({available: true, ok: true,
      evidence: {evidence: 'fresh', age_s: 0}, data: {state: 'IDLE', previous: 'r1'}})""")
    visible = [row for row in _holders(page, CAUSE) if not row["hidden"]]
    assert len(visible) == 1
    network_note = page.locator(f"#{visible[0]['id']}")
    assert "네트워크 작업을 막았습니다" in network_note.inner_text()
    sta = page.locator("ui-button").filter(has_text="사업장 Wi-Fi로 전환")
    assert visible[0]["id"] in sta.get_attribute("aria-describedby").split()
    rollback = page.locator("ui-button").filter(has_text="이전 릴리스로 복귀")
    assert not rollback.evaluate("b => b.disabled")


def test_camera_status_speaks_korean_with_evidence_and_waits_on_one_line(panel):
    page = panel("console/camera.js")
    status = page.locator("#vision-status")
    assert status.inner_text() == "수신 대기"
    assert status.get_attribute("data-evidence") == "unavailable"
    assert status.get_attribute("title") == "WAITING"
    # The waiting sentence lives on the stage only; the capture line under the actions is hidden.
    assert page.locator("#vision-empty").inner_text() == "카메라 프레임 수신 대기"
    assert page.locator("#vision-capture-status").is_hidden()
    assert len([row for row in _holders(page, "카메라 프레임 수신 대기") if not row["hidden"]]) == 1

    page.evaluate("""async () => {
      const {createVisionPreview} = await import('/assets/vision.js');
      const ids = ['vision-stage', 'vision-frame', 'vision-empty', 'vision-status', 'vision-source',
                   'vision-resolution', 'vision-age', 'vision-captured'];
      const elements = Object.fromEntries(ids.map((id) => [id, document.getElementById(id)]));
      const preview = createVisionPreview({elements,
        setText: (id, value) => { elements[id].textContent = value ?? '—'; },
        api: async () => ({available: false, stale: true, age_ms: 4200}),
        authHeaders: () => ({}), hasToken: () => true, isHidden: () => false});
      await preview.refresh();
    }""")
    assert status.inner_text() == "지연 · 4초"
    assert status.get_attribute("data-evidence") == "delayed"
    assert status.get_attribute("title") == "STALE"
    assert "STALE" not in page.inner_text("#root") and "WAITING" not in page.inner_text("#root")


def test_robot_map_read_failure_is_an_overlay_with_retry_and_no_target_row(panel):
    page = panel("console/map.js", role="operator")
    page.evaluate("""() => { window.__api = async (path) => {
      if (path === '/api/v1/map') { const error = new Error('HTTP 500'); error.status = 500; throw error; }
      if (path === '/api/v1/navigation/path') return {poses: []};
      return null;
    }; }""")
    # Remount so the first map read already sees the 500 (the fixture mount read before __api existed).
    page.evaluate("""async () => { const {mount} = await import('/assets/panels/console/map.js');
      document.getElementById('root').replaceChildren(); window.__unmount?.();
      const store = {poll() { return () => {}; }};
      window.__unmount = mount(document.getElementById('root'), {role: 'operator', store, surfaces: [],
        api: (path, options) => window.__api(path, options)}); }""")
    failure = page.locator(".surface-map-overlay ui-empty")
    failure.wait_for(state="visible")
    assert "지도를 불러오지 못했습니다" in failure.inner_text()
    retry = page.locator(".surface-map-overlay ui-button")
    assert retry.inner_text() == "다시 시도"
    assert page.locator(".surface-map-readout").is_hidden()
    assert page.locator("#map-status").is_hidden()
    box, stage = failure.bounding_box(), page.locator(".surface-map-frame").bounding_box()
    assert stage["y"] <= box["y"] and box["y"] + box["height"] <= stage["y"] + stage["height"]

    page.evaluate("""() => { window.__api = async (path) => path === '/api/v1/map'
      ? {width: 4, height: 4, resolution: 0.1, origin: {x: 0, y: 0}, data: Array(16).fill(0)}
      : path === '/api/v1/navigation/path' ? {poses: []} : null; }""")
    retry.click()
    failure.wait_for(state="hidden")
    assert retry.is_hidden()
    assert page.locator(".surface-map-readout").is_visible()


@pytest.mark.parametrize(("module", "path", "payload", "text"), [
    ("setup/docking.js", "/api/v1/docking/docks", {"docks": []}, "등록된 도크가 없습니다."),
    ("setup/dock-admin.js", "/api/v1/docking/docks", {"docks": []}, "등록된 도크가 없습니다."),
    ("setup/waypoints.js", "/api/v1/waypoints", {"waypoints": []}, "저장된 웨이포인트가 없습니다."),
])
def test_setup_empty_lists_are_one_ui_empty_outside_the_list(panel, module, path, payload, text):
    page = panel(module, role="administrator")
    page.evaluate("([path, payload]) => __callbacks[path].onData(payload)", [path, payload])
    empty = page.locator("#root > ui-empty")
    assert empty.count() == 1 and empty.is_visible() and empty.inner_text() == text
    assert page.locator("#root ul ui-empty, #root ul li").count() == 0
    assert page.locator("#root ul").evaluate_all("lists => lists.every((list) => list.hidden)")


@pytest.mark.parametrize("module", ["setup/docking.js", "console/docking.js"])
def test_dock_state_reads_korean_with_the_enum_in_title(panel, module):
    page = panel(module, role="administrator")
    page.evaluate("() => __callbacks['/api/v1/docking/status'].onData({supported: true, state: 'UNDOCKED'})")
    value = page.locator("dl dd").filter(has_text="도크 밖")
    assert value.count() == 1 and value.get_attribute("title") == "UNDOCKED"
    assert "UNDOCKED" not in page.inner_text("#root")
