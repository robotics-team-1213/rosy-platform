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
WEB_COMMON = (ROOT.parents[2] / "shared") / "web"
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


def test_lane_perception_admin_idle_gate_pending_failure_and_readback(panel):
    page = panel("console/line-follow.js", role="administrator")
    page.evaluate("""() => {
      window.__callbacks['/api/v1/line-follow'].onData({mode:'OFF'});
      window.__callbacks['/api/v1/robot/state'].onData({mode:'MANUAL',velocity:{linear:0,angular:0}});
      window.__callbacks['/api/v1/line-follow/perception'].onData({paint_source:'denoise',applied_paint_source:null});
    }""")
    apply = page.locator("ui-button", has_text="인식 적용")
    assert apply.evaluate("e=>e.disabled")
    page.evaluate("""() => {
      window.__callbacks['/api/v1/robot/state'].onData({mode:'IDLE',velocity:{linear:0,angular:0}});
      window.__api = async (path, options) => {
        if (options?.method === 'PUT') return new Promise((resolve,reject)=>{window.failApply=()=>reject(new Error('restart failed'));});
        return {paint_source:'learned',applied_paint_source:null};
      };
    }""")
    page.select_option("select[aria-label='차선 인식 방식']", "learned")
    apply.evaluate("button=>{window.__callbacks['/api/v1/robot/state'].onData({mode:'IDLE',velocity:{linear:0,angular:0}}); button.click();}")
    assert apply.evaluate("e=>e.disabled")
    assert page.locator("ui-button", has_text="추종 시작").evaluate("e=>e.disabled")
    page.evaluate("window.failApply()")
    page.wait_for_function("document.body.textContent.includes('인식 적용 실패')")
    assert "설정 적용: 학습 모델" not in page.inner_text("body")
    page.evaluate("""() => {
      window.__callbacks['/api/v1/line-follow/perception'].onData({paint_source:'denoise'});
      window.__api=async (path,options)=>options?.method==='PUT' ? {applied:true} : {paint_source:'learned',applied_paint_source:null};
    }""")
    page.select_option("select[aria-label='차선 인식 방식']", "learned")
    apply.evaluate("button=>{window.__callbacks['/api/v1/robot/state'].onData({mode:'IDLE',velocity:{linear:0,angular:0}}); button.click();}")
    page.wait_for_function("document.body.textContent.includes('설정 적용: 학습 모델')")
    assert "실제 추론: 확인 대기" in page.inner_text("body")
    page.evaluate("window.__callbacks['/api/v1/line-follow/perception'].onData({paint_source:'learned',applied_paint_source:'denoise_fallback',applied_source_age_s:0.3})")
    assert "학습 미사용 · 전처리 대체" in page.inner_text("body")
    page.evaluate("window.__callbacks['/api/v1/line-follow/perception'].onData({paint_source:'learned',applied_paint_source:'learned',applied_source_age_s:0.3,applied_model_revision:'lane-test-r2'})")
    assert "모델 lane-test-r2" in page.inner_text("body")
    page.evaluate("window.__callbacks['/api/v1/line-follow/perception'].onData({paint_source:'learned',applied_paint_source:'learned',applied_source_age_s:3})")
    assert "실제 추론: 확인 대기" in page.inner_text("body")


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
    prompt = page.locator('dialog[open] p').inner_text()
    assert prompt.startswith("내비게이션 모드로 바꿀까요?")
    assert "NAVIGATION" not in prompt
    page.get_by_role('button', name='취소', exact=True).click()


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
    # D-398 — 나이 뒤처리 규격: `지연 · N초 전`(4200 ms → 4.2).
    assert status.inner_text() == "지연 · 4.2초 전"
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


def test_camera_explains_lane_object_labels_and_disables_expansion_without_a_frame(panel):
    page = panel('console/camera.js', role='viewer', width=390, height=844)
    expand = page.locator('#vision-expand')
    assert expand.is_disabled()
    assert expand.get_attribute('reason') == '영상 수신 후 확대할 수 있습니다'
    page.locator('.surface-camera-legend summary').click()
    assert 'LEFT LANE' in page.locator('.surface-camera-legend').inner_text()
    assert 'UNCLASSIFIED' in page.locator('.surface-camera-legend').inner_text()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


def test_camera_can_expand_live_image_and_return_focus_after_exit(panel):
    import cv2
    import numpy as np
    image = cv2.imencode('.jpg', np.full((240, 320, 3), 90, np.uint8))[1].tobytes()
    page = panel('console/camera.js', role='viewer')
    page.route('**/api/v1/vision/front/frame?sequence=1&overlay=false',
               lambda route: route.fulfill(body=image, content_type='image/jpeg',
                                          headers={'X-Rosy-Camera-Sequence': '1', 'X-Rosy-Camera-Variant':'raw',
                                                   'X-Rosy-Camera-Captured-At':'5', 'X-Rosy-Camera-Frame-Id':'front'}))
    page.evaluate("""async () => {
      __unmount();
      const {session} = await import('/assets/client.js'); session.token = 'rosy-dev-viewer';
      const {mount} = await import('/assets/panels/console/camera.js');
      document.querySelector('#root').replaceChildren();
      __unmount = mount(document.querySelector('#root'), {role:'viewer', api:async () => ({
        available:true, stale:false, sequence:1, raw_available:true,raw_sequence:1, source:'GAZEBO', width:320, height:240,
        captured_at:5, age_ms:20}), store:{poll(){return () => {};}}});
    }""")
    page.locator('#vision-frame').wait_for(state='visible')
    page.locator('#vision-expand').click()
    page.wait_for_function("document.fullscreenElement?.id === 'vision-stage'")
    assert page.locator('.surface-camera-close').is_visible()
    page.locator('.surface-camera-close').click()
    page.wait_for_function('document.fullscreenElement === null')
    page.wait_for_function("document.activeElement.id === 'vision-expand'")
    assert page.evaluate("document.activeElement.id === 'vision-expand'")
    page.evaluate('typeof __unmount === "function" ? __unmount() : __unmount.unmount()')


def _live_camera_with_shell(panel):
    import cv2
    import numpy as np
    from urllib.parse import parse_qs, urlsplit
    image = cv2.imencode('.jpg', np.full((240, 320, 3), 90, np.uint8))[1].tobytes()
    page = panel('console/camera.js', role='viewer')
    page.route('**/api/v1/vision/front/frame?sequence=*',
               lambda route: route.fulfill(body=image, content_type='image/jpeg', headers={
                   'X-Rosy-Camera-Sequence': parse_qs(urlsplit(route.request.url).query)['sequence'][0],
                   'X-Rosy-Camera-Variant': 'raw', 'X-Rosy-Camera-Captured-At': '5',
                   'X-Rosy-Camera-Frame-Id': 'front_camera_link'}))
    page.evaluate("""async () => {
      __unmount();
      const {session}=await import('/assets/client.js'); session.token='fixture-viewer';
      const bar=document.createElement('ui-topbar');
      bar.innerHTML='<ui-text id="shell-notice" role="status">fixture notice</ui-text><ui-button id="shell-estop" data-always-live kind="irreversible">비상 정지</ui-button>';
      document.body.prepend(bar); window.ownedStop=document.querySelector('#shell-estop');
      window.ownedNotice=document.querySelector('#shell-notice'); window.stopCalls=0;
      ownedStop.addEventListener('click',()=>{window.stopCalls++;ownedNotice.textContent='fixture stop received'});
      const {mount}=await import('/assets/panels/console/camera.js');
      document.querySelector('#root').replaceChildren();
      let sequence=0;
      __unmount=mount(document.querySelector('#root'),{role:'viewer',api:async()=>({available:true,stale:false,sequence:++sequence,raw_available:true,raw_sequence:sequence,source:'GAZEBO',width:320,height:240,captured_at:5,age_ms:20}),store:{poll(){return()=>{}}}});
      window.ownedRecordStop=document.querySelector('#vision-record-stop');
    }""")
    page.locator('#vision-frame').wait_for(state='visible')
    return page


def test_camera_fullscreen_keeps_owned_stop_feedback_and_record_stop(panel):
    page = _live_camera_with_shell(panel)
    assert page.locator('.surface-camera-close').is_hidden()
    page.locator('.surface-camera-tools summary').click()
    page.locator('#vision-record-start').click()
    page.wait_for_function('() => !document.querySelector("#vision-record-stop").disabled')
    page.locator('.surface-camera-tools summary').click()
    assert page.locator('#vision-record-stop').is_visible()
    page.locator('#vision-expand').click()
    page.wait_for_function("() => document.fullscreenElement?.id==='vision-stage'")
    assert page.evaluate("() => document.fullscreenElement.contains(ownedStop)&&document.fullscreenElement.contains(ownedNotice)&&document.fullscreenElement.contains(ownedRecordStop)")
    assert page.locator('#shell-estop').count() == 1
    assert page.locator('#vision-record-stop').is_visible()
    assert page.evaluate('document.fullscreenElement.contains(document.querySelector("#vision-capture-status"))')
    page.locator('#shell-estop').click()
    assert page.evaluate('window.stopCalls') == 1
    assert page.locator('#shell-notice').inner_text() == 'fixture stop received'
    page.locator('.surface-camera-close').click()
    page.wait_for_function('() => document.fullscreenElement===null')
    assert page.evaluate("() => ownedStop.parentElement.localName==='ui-topbar' && ownedNotice.parentElement===ownedStop.parentElement && !document.querySelector('#vision-stage').contains(ownedRecordStop)")
    page.wait_for_function("() => document.activeElement.id==='vision-expand'")


def test_camera_rejected_and_late_fullscreen_requests_restore_owned_nodes(panel):
    page = _live_camera_with_shell(panel)
    page.evaluate("() => { const stage=document.querySelector('#vision-stage');window.nativeExpand=stage.requestFullscreen.bind(stage);stage.requestFullscreen=()=>Promise.reject(new Error('fixture rejected')); }")
    page.locator('#vision-expand').click()
    page.get_by_text('영상 확대를 열지 못했습니다.', exact=True).wait_for()
    assert page.evaluate("ownedStop.parentElement.localName==='ui-topbar'")
    page.evaluate("() => { document.querySelector('#vision-stage').requestFullscreen=()=>new Promise((resolve,reject)=>window.rejectPending=reject); }")
    page.locator('#vision-expand').click()
    assert page.locator('#shell-estop').is_visible()
    assert page.locator('#vision-record-stop').is_visible()
    page.evaluate("window.rejectPending(new Error('pending rejected'))")
    page.wait_for_function('() => !document.querySelector("#vision-expand").disabled')
    page.evaluate("() => { document.querySelector('#vision-stage').requestFullscreen=async()=>{await window.nativeExpand();await new Promise(resolve=>window.finishExpand=resolve);}; }")
    page.locator('#vision-expand').click()
    page.wait_for_function("() => document.fullscreenElement?.id==='vision-stage' && typeof window.finishExpand==='function'")
    page.evaluate("__unmount();window.finishExpand();")
    page.wait_for_function('() => document.fullscreenElement===null')
    assert page.evaluate("() => ownedStop.parentElement.localName==='ui-topbar' && ownedNotice.parentElement===ownedStop.parentElement && !document.querySelector('#vision-stage').contains(ownedRecordStop)")
    assert page.locator('.surface-camera-close').is_hidden()


def test_confirmation_abort_cleans_live_dialog_and_preserves_stop(panel):
    page = panel('console/overview.js')
    page.evaluate("""async () => {
      const {confirmIrreversible}=await import('/common/ui.js');
      const stop=document.createElement('ui-button');stop.id='fixture-stop';stop.dataset.alwaysLive='';stop.textContent='fixture stop';document.body.prepend(stop);
      window.controller=new AbortController();window.answer=null;
      window.confirmResult=confirmIrreversible({message:'fixture confirm',action:'fixture apply',signal:controller.signal}).then(value=>window.answer=value);
    }""")
    page.locator('dialog[open]').wait_for()
    assert page.locator('#fixture-stop').is_enabled()
    assert not page.locator('#fixture-stop').evaluate('(node)=>node.closest("[inert]")')
    page.evaluate('window.controller.abort()')
    page.wait_for_function('() => window.answer===false && !document.querySelector("dialog[open]")')
    assert page.locator('.ui-confirm-scrim').count() == 0
    assert not page.locator('#root').evaluate('(node)=>node.inert')
    page.evaluate("""async () => {
      const {confirmIrreversible}=await import('/common/ui.js');
      window.answer=await confirmIrreversible({message:'never open',action:'never apply',signal:controller.signal});
    }""")
    assert page.locator('dialog').count() == 0
    page.evaluate("""async () => {
      const {confirmIrreversible}=await import('/common/ui.js');
      window.stopClicks=0;document.querySelector('#fixture-stop').addEventListener('click',()=>window.stopClicks++);
      window.answer=null;confirmIrreversible({message:'stop stays live',action:'never apply'}).then(value=>window.answer=value);
    }""")
    page.locator('dialog[open]').wait_for()
    page.locator('#fixture-stop').click()
    page.wait_for_function('() => window.answer===false && window.stopClicks===1')
    assert page.locator('.ui-confirm-scrim').count() == 0


@pytest.mark.parametrize('module,selector,callbacks', [
    ('mode.js', '[data-mode="NAVIGATION"]', "__callbacks['/api/v1/robot/state'].onData({mode:'MANUAL'});__callbacks['/api/v1/system/capabilities'].onData({navigation:{goal_navigation:true}})"),
    ('docking.js', '.ui-form ui-button', "__callbacks['/api/v1/docking/status'].onData({supported:true,state:'UNDOCKED'});__callbacks['/api/v1/docking/docks'].onData({docks:[{id:'fixture-dock'}]})"),
    ('line-follow.js', '.ui-form ui-button', "__callbacks['/api/v1/line-follow'].onData({mode:'OFF',state:'OFF'});__callbacks['/api/v1/system/capabilities'].onData({navigation:{goal_navigation:true}})"),
])
def test_console_confirmation_is_nonblocking_and_unmount_cancels_late_action(panel, module, selector, callbacks):
    page = panel('console/' + module)
    page.evaluate(callbacks)
    page.locator(selector).first.click()
    page.locator('dialog[open]').wait_for(timeout=5000)
    assert not page.evaluate('window.__prompts.length')
    page.locator(selector).first.dispatch_event('click')
    assert page.locator('dialog[open]').count() == 1
    page.get_by_role('button', name='취소', exact=True).click()
    page.wait_for_function('() => !document.querySelector("dialog[open]")')
    assert page.locator(selector).first.evaluate('(node)=>node===document.activeElement')
    assert page.evaluate('window.__calls.length') == 0
    page.locator(selector).first.click()
    page.locator('dialog[open]').wait_for()
    if module == 'mode.js':
        page.evaluate("__callbacks['/api/v1/system/capabilities'].onData({navigation:{goal_navigation:false}})")
    elif module == 'docking.js':
        page.evaluate("__callbacks['/api/v1/docking/status'].onData({supported:false,state:'UNDOCKED'})")
    else:
        page.evaluate("__callbacks['/api/v1/system/capabilities'].onData({navigation:{goal_navigation:false}})")
    page.locator('dialog[open] ui-button[kind="irreversible"]').click()
    page.wait_for_function('() => !document.querySelector("dialog[open]")')
    assert page.evaluate('window.__calls.length') == 0
    page.evaluate(callbacks)
    page.locator(selector).first.click()
    page.locator('dialog[open]').wait_for()
    page.evaluate('typeof __unmount === "function" ? __unmount() : __unmount.unmount()')
    page.wait_for_function('() => !document.querySelector("dialog[open]")')
    assert page.locator('.ui-confirm-scrim').count() == 0
    assert page.evaluate('window.__calls.length') == 0


def test_browser_annotation_saves_original_and_derivative_and_rejects_missing_raw(panel):
    import cv2
    import numpy as np
    image = cv2.imencode('.jpg', np.full((120, 160, 3), 90, np.uint8))[1].tobytes()
    page = panel('console/camera.js', role='viewer')
    downloads = []
    page.on('download', lambda item: downloads.append(item.suggested_filename))

    def frame(route):
        variant = 'annotated' if route.request.url.endswith('overlay=true') else 'raw'
        route.fulfill(body=image, content_type='image/jpeg', headers={
            'X-Rosy-Camera-Sequence':'1','X-Rosy-Camera-Variant':variant,
            'X-Rosy-Camera-Captured-At':'5','X-Rosy-Camera-Frame-Id':'front'})

    page.route('**/api/v1/vision/front/frame?*', frame)
    page.evaluate("""async () => {
      __unmount();const {session}=await import('/assets/client.js');session.token='rosy-dev-viewer';
      const {mount}=await import('/assets/panels/console/camera.js');document.querySelector('#root').replaceChildren();
      window.rawReady=true;
      window.MediaRecorder=class {
        static isTypeSupported(type){return type==='video/webm';}
        constructor(){this.state='inactive';}start(){this.state='recording';}
        stop(){this.state='inactive';this.ondataavailable({data:new Blob(['VIDEO'])});this.onstop();}
      };
      __unmount=mount(document.querySelector('#root'),{role:'viewer',api:async()=>({available:true,
        sequence:1,raw_sequence:1,raw_available:rawReady,width:160,height:120,age_ms:20}),store:{poll(){return ()=>{};}}});
    }""")
    page.wait_for_function("!document.querySelector('#vision-record-start').disabled")
    assert page.locator('#vision-record-mode').input_value() == 'raw'
    page.locator('.surface-camera-tools summary').click()
    page.select_option('#vision-record-mode', 'annotated')
    page.wait_for_function("!document.querySelector('#vision-record-start').disabled")
    page.locator('#vision-record-start').click()
    assert page.locator('#vision-record-mode').is_disabled()
    page.locator('#vision-record-stop').click()
    page.wait_for_function("!document.querySelector('#vision-record-mode').disabled")
    page.wait_for_timeout(500)
    assert any(name.endswith('-raw.webm') for name in downloads)
    assert any(name.endswith('-annotated.webm') for name in downloads)
    page.evaluate('rawReady=false')
    page.select_option('#vision-record-mode', 'raw')
    page.wait_for_function("document.querySelector('#vision-record-start').disabled")
    assert '원본' in page.inner_text('#vision-empty')
    page.evaluate('__unmount()')


def test_camera_low_light_is_visibility_failure_with_live_raw_frame(panel):
    import cv2
    import numpy as np
    image = cv2.imencode('.jpg', np.zeros((120, 160, 3), np.uint8))[1].tobytes()
    page = panel('console/camera.js', role='viewer')
    page.route('**/api/v1/vision/front/frame?sequence=1&overlay=false',
               lambda route: route.fulfill(body=image, content_type='image/jpeg',
                                          headers={'X-Rosy-Camera-Sequence': '1', 'X-Rosy-Camera-Variant':'raw',
                                                   'X-Rosy-Camera-Captured-At':'5', 'X-Rosy-Camera-Frame-Id':'front'}))
    page.evaluate("""async () => {
      __unmount();
      const {session} = await import('/assets/client.js'); session.token = 'rosy-dev-viewer';
      const {mount} = await import('/assets/panels/console/camera.js');
      document.querySelector('#root').replaceChildren();
      window.cameraQuality={valid:false,reason:'low_light'};
      __unmount = mount(document.querySelector('#root'), {role:'viewer', api:async () => ({
        available:true, stale:false, sequence:1, raw_available:true,raw_sequence:1, source:'CAMERA', width:160, height:120,
        captured_at:5, age_ms:20, quality:window.cameraQuality}), store:{poll(){return () => {};}}});
    }""")
    page.locator('#vision-quality').wait_for(state='visible')
    page.locator('#vision-frame').wait_for(state='visible')
    assert '차선·물체를 판정할 수 없습니다' in page.inner_text('#vision-quality')
    assert page.locator('#vision-status').inner_text() == '실시간'
    page.evaluate("window.cameraQuality={valid:false,reason:'overexposed'}")
    page.wait_for_function("document.querySelector('#vision-quality').textContent.includes('과노출')")
    assert page.inner_text('#vision-quality') == '과노출 · 차선 정보 확인 불가'
    page.evaluate("window.cameraQuality={valid:true,reason:'ok'}")
    page.locator('#vision-quality').wait_for(state='hidden')
    page.evaluate("window.cameraQuality={valid:false,reason:'low_light'}")
    page.locator('#vision-quality').wait_for(state='visible')
    page.evaluate("window.cameraQuality=undefined")
    page.locator('#vision-quality').wait_for(state='hidden')
    page.evaluate('__unmount()')
