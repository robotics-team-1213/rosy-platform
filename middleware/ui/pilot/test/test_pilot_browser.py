"""D-323 — /pilot 브라우저 계약 (dev_server 가짜 CORE).

게이트 플로우 + 주행 화면 마운트 + 카메라 프레임 + 속도 프리셋을 태블릿 뷰포트에서
기계로 판정한다. ROSY_RUN_BROWSER_TESTS=1 옵트인.
"""

from __future__ import annotations

import os
import json
import sys
import threading
import time
from pathlib import Path

import pytest
from browser_harness import browser_tests_enabled, safe_listener

playwright_sync = pytest.importorskip("playwright.sync_api", reason="Playwright 없음")
import uvicorn  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dev_server  # noqa: E402

TABLET_VIEWPORTS = [(2000, 1200), (1200, 2000)]


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
def test_camera_low_light_warning_keeps_raw_preview_and_clears_on_recovery(tablet_page):
    base_url, page, errors = tablet_page
    state = {"quality": {"valid": False, "reason": "low_light"}, "available": True}

    def status(route):
        body = {"available": state["available"], "sequence": dev_server.FRAME_SEQ, "raw_available": True,
                "raw_sequence": dev_server.FRAME_SEQ, "width": 160, "height": 120, "age_ms": 12}
        if state["quality"] is not None:
            body["quality"] = state["quality"]
        route.fulfill(json=body)

    page.route("**/api/v1/vision/front/status", status)
    _enter_drive(page, base_url)
    page.locator("[data-drive-visibility]").wait_for(state="visible")
    page.locator("[data-drive-frame]").wait_for(state="visible")
    assert "차선·물체를 판정할 수 없습니다" in page.inner_text("[data-drive-visibility]")
    state["quality"] = {"valid": False, "reason": "overexposed"}
    page.wait_for_function("document.querySelector('[data-drive-visibility]').textContent.includes('과노출')")
    assert page.inner_text("[data-drive-visibility]") == "과노출 · 차선 정보 확인 불가"
    state["quality"] = {"valid": True, "reason": "ok"}
    page.locator("[data-drive-visibility]").wait_for(state="hidden")
    state["quality"] = {"valid": False, "reason": "low_light"}
    page.locator("[data-drive-visibility]").wait_for(state="visible")
    state["quality"] = None  # A legacy server cannot assert low-light.
    page.locator("[data-drive-visibility]").wait_for(state="hidden")
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
def test_device_recording_option_uses_capability_and_actual_readback(tablet_page):
    base_url, page, errors = tablet_page
    page.goto(f"{base_url}/pilot")
    page.evaluate("""async () => {
      const {mountRobotRecording} = await import('/pilot/assets/screens/robot-recording.js');
      const host=document.createElement('main');document.body.replaceChildren(host);
      const toggle=document.createElement('ui-button'), detail=document.createElement('span'), openButton=document.createElement('ui-button');
      host.append(toggle,detail,openButton);window.recordCalls=[];window.recordSupported=true;
      window.recordActual={state:'idle'};
      window.recordDispose=mountRobotRecording({toggle,detail,openButton,sheetHost:host,anchor:host,save(){},
        schedule(fn){window.recordPoll=fn;return ()=>{};},
        request:async(path,options={})=>{
          if(options.method==='POST'){
            recordCalls.push(JSON.parse(options.body));
            window.recordActual={state:'recording',elapsed_s:1,max_duration_s:600,bytes:5,preview_mode:'raw'};
            return {ok:true,status:201,body:window.recordActual};
          }
          return {status:200,body:{active:window.recordActual,preview_modes:recordSupported?['raw','annotated']:undefined}};
        }});
      toggle.dataset.optionToggle='';detail.dataset.optionReadback='';
    }""")
    page.wait_for_function("!document.querySelector('[data-robot-record-mode] option[value=annotated]').disabled")
    page.select_option('[data-robot-record-mode]', 'annotated')
    page.locator('[data-option-toggle]').click()
    page.wait_for_function("window.recordCalls.length===1")
    assert page.evaluate('recordCalls') == [{'preview_mode': 'annotated'}]
    assert '원본 + 모델 표시본' not in page.inner_text('[data-option-readback]')
    assert '원본' in page.inner_text('[data-option-readback]')
    assert page.locator('[data-robot-record-mode]').is_disabled()
    page.evaluate("recordActual={state:'idle'};recordSupported=false;recordPoll()")
    page.wait_for_function("document.querySelector('[data-robot-record-mode] option[value=annotated]').disabled")
    assert page.locator('[data-robot-record-mode]').input_value() == 'raw'
    page.evaluate('recordDispose.dispose()')
    assert page.locator('[data-robot-record-mode]').count() == 0
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
def test_pilot_browser_confirmation_records_and_saves_paired_variants(tablet_page):
    base_url, page, errors = tablet_page
    downloads = []
    page.on('download', lambda item: downloads.append(item.suggested_filename))
    _enter_drive(page, base_url)
    page.locator('[data-drive-frame]').wait_for(state='visible')
    page.locator('[data-drive-tools]').click()
    page.locator('[data-drive-tools-panel]').wait_for(state='visible')
    page.evaluate("""() => {window.MediaRecorder=class {
      static isTypeSupported(type){return type==='video/webm';}
      constructor(){this.state='inactive';}start(){this.state='recording';}
      stop(){this.state='inactive';this.ondataavailable({data:new Blob(['VIDEO'])});this.onstop();}
    };} """)
    page.select_option('[data-browser-record-mode]', 'annotated')
    page.wait_for_function("!document.querySelector('[data-evidence-record]').disabled")
    page.locator('[data-evidence-record]').click()
    assert page.locator('[data-browser-record-mode]').is_disabled()
    with page.expect_download():
        page.locator('[data-evidence-record]').click()
    while len(downloads) < 3:
        page.wait_for_event('download', timeout=10_000)
    assert any(name.endswith('-raw.webm') for name in downloads)
    assert any(name.endswith('-annotated.webm') for name in downloads)
    assert page.locator('[data-evidence-save]').is_enabled()
    page.locator('[data-drive-exit]').click()
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
def test_lane_perception_failed_apply_idle_guard_and_readback(tablet_page):
    """Configuration never actuates; pending/failure/readback remain distinct."""
    base_url, page, errors = tablet_page
    page.goto(f"{base_url}/pilot")
    page.evaluate("""async () => {
      const {mountLanePerception} = await import('/pilot/assets/screens/drive-auto.js');
      const root = document.createElement('main'); document.body.replaceChildren(root);
      window.selected = 'denoise'; window.mode = 'MANUAL'; window.puts = [];
      window.pending = false; window.fail = true; window.unsupported = false;
      const apiGet = async (path, options={}) => {
        if (path.endsWith('/whoami')) return {status:200, body:{role:'administrator'}};
        if (path.endsWith('/robot/state')) return {status:200, body:{mode:window.mode, velocity:{linear:0,angular:0}}};
        if (path === '/api/v1/line-follow') return {status:200, body:{mode:'OFF'}};
        if (path.endsWith('/perception')) {
          if (options.method === 'PUT') {
            window.applyTimeout = options.timeoutMs;
            window.puts.push(JSON.parse(options.body));
            return new Promise(resolve => { window.finishApply = () => {
              if (window.fail) resolve({status:409, body:{detail:'idle required'}});
              else {window.selected = JSON.parse(options.body).paint_source; window.deferReadback=true; resolve({status:200,body:{applied:true}});}
            }; });
          }
          if (window.deferReadback) return new Promise(resolve=>{window.finishReadback=()=>{
            window.deferReadback=false;
            resolve({status:200,body:{paint_source:window.selected,applied_paint_source:null}});
          };});
          return window.unsupported ? {status:404} : {status:200, body:{paint_source:window.selected,
            applied_paint_source:window.actualSource??null, applied_source_age_s:window.actualAge??null,
            applied_model_revision:window.actualRevision??null}};
        }
        throw new Error('unexpected actuation '+path);
      };
      window.perception = mountLanePerception(root, {apiGet, onPending:value=>{window.pending=value;}});
      root.querySelector('details').open = true;
    }""")
    page.wait_for_function("document.querySelector('[data-lane-apply]').disabled")
    assert page.evaluate("window.puts") == []
    page.evaluate("window.mode = 'IDLE'; window.perception.refresh()")
    page.wait_for_function("!document.querySelector('[data-lane-apply]').disabled")
    page.select_option("[data-lane-perception]", "learned")
    page.click("[data-lane-apply]")
    assert page.evaluate("window.pending") is True
    assert page.evaluate("window.applyTimeout") >= 70000
    assert page.locator("[data-lane-apply]").evaluate("e=>e.disabled")
    page.evaluate("window.finishApply()")
    page.wait_for_function("document.querySelector('[data-lane-perception-status]').textContent.includes('적용 실패')")
    assert "설정 적용: 학습" not in page.inner_text("[data-lane-perception-status]")
    page.evaluate("window.fail = false; window.perception.refresh()")
    page.wait_for_function("!document.querySelector('[data-lane-apply]').disabled")
    page.select_option("[data-lane-perception]", "learned")
    page.click("[data-lane-apply]")
    page.evaluate("window.finishApply()")
    page.wait_for_function("typeof window.finishReadback === 'function'")
    assert page.evaluate("window.pending") is True
    assert page.locator("[data-lane-apply]").evaluate("e=>e.disabled")
    page.evaluate("window.finishReadback()")
    page.wait_for_function("document.querySelector('[data-lane-perception-status]').textContent.includes('설정 적용: 학습 모델')")
    assert "실제 추론: 확인 대기" in page.inner_text("[data-lane-perception-status]")
    page.evaluate("window.actualSource='denoise_fallback'; window.actualAge=0.4; window.actualRevision='old-model'; window.perception.refresh()")
    page.wait_for_function("document.querySelector('[data-lane-perception-status]').textContent.includes('학습 미사용 · 전처리 대체')")
    assert "모델 old-model" not in page.inner_text("[data-lane-perception-status]")
    page.evaluate("window.actualSource='learned'; window.actualRevision='lane-test-r2'; window.perception.refresh()")
    page.wait_for_function("document.querySelector('[data-lane-perception-status]').textContent.includes('모델 lane-test-r2')")
    page.evaluate("window.actualAge=3; window.perception.refresh()")
    page.wait_for_function("document.querySelector('[data-lane-perception-status]').textContent.includes('실제 추론: 확인 대기')")
    page.evaluate("window.unsupported = true; window.perception.refresh()")
    page.wait_for_function("document.querySelector('[data-lane-apply]').disabled")
    assert "지원하지 않습니다" in page.inner_text("[data-lane-perception-status]")
    page.evaluate("window.perception.dispose()")
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
def test_omx_recording_retry_outcome_stale_camera_and_disposal(tablet_page):
    base_url, page, errors = tablet_page
    page.goto(f"{base_url}/pilot")
    page.evaluate("""async () => {
      const {mountArm} = await import('/pilot/assets/screens/arm.js');
      const root = document.createElement('main'); document.body.replaceChildren(root);
      window.recordState = {status:'idle', frame_count:0, issues:[]};
      window.cameraFresh = true; window.startFailures = 1; window.released = 0;
      const driver = {request: async (path, options={}) => {
        if (path === '/pair') return {token:'test-only'};
        if (path === '/whoami') return {role:'operator'};
        if (path === '/seat') return {seat_id:'seat-test'};
        if (options.method === 'DELETE') { window.released++; return null; }
        if (path.startsWith('/seat/')) return {};
        if (path === '/state') return {ready:true, state_sequence:1, positions:{joint1:0}, joint_age_ms:0};
        if (path === '/camera') return {fresh:window.cameraFresh, age_ms:10};
        if (path === '/camera/frame') return new Blob([], {type:'image/jpeg'});
        if (path === '/recordings' && options.method === 'POST') {
          if (window.startFailures-- > 0) throw new Error('409: camera warming up');
          window.recordState = {status:'recording', episode_id:'episode-test', frame_count:2, issues:[]};
        }
        if (path.endsWith('/stop')) {
          window.outcome = JSON.parse(options.body).outcome;
          window.recordState = {...window.recordState, status:'complete'};
        }
        return window.recordState;
      }};
      window.disposeArm = mountArm(root, {joints:['joint1'], gripper:'joint1', camera:true, recording:true}, driver);
    }""")
    page.fill("[data-sim-code]", "test-only")
    page.click("[data-sim-connect]")
    page.wait_for_selector("[data-sim-record-panel]")
    view = page.locator(".arm-view").bounding_box()
    controls = page.locator(".arm-controls").bounding_box()
    assert controls["x"] >= view["x"] + view["width"]
    assert abs(controls["width"] - view["width"]) <= 1, (view, controls)
    if os.environ.get("ROSY_SHOT_DIR"):
        shots = Path(os.environ["ROSY_SHOT_DIR"])
        shots.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(shots / "pilot-arm-camera-controls-2000x1200.png"), full_page=True)
    page.fill("[data-sim-task]", "관절 이동 시연")
    page.click("[data-sim-record-start]")
    page.wait_for_function("document.querySelector('[data-sim-record-status]').textContent.includes('기록 시작 실패')")
    page.wait_for_timeout(1200)
    assert "기록 시작 실패" in page.inner_text("[data-sim-record-status]")
    page.click("[data-sim-record-start]")
    page.wait_for_function("document.querySelector('[data-sim-record-status]').dataset.state === 'recording'")
    page.select_option("[data-sim-outcome]", "success")
    page.click("[data-sim-record-stop]")
    page.wait_for_function("window.outcome === 'success'")
    page.evaluate("window.cameraFresh = false")
    page.wait_for_function("document.querySelector('[data-sim-camera]').hidden")
    assert page.locator("[data-sim-record-start]").evaluate("b => b.disabled")
    page.evaluate("window.disposeArm()")
    page.wait_for_function("window.released === 1")
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
def test_omx_hidden_tab_releases_a_seat_acquired_after_visibility_changed(tablet_page):
    base_url, page, errors = tablet_page
    page.goto(f"{base_url}/pilot")
    page.evaluate("""async () => {
      const {mountArm} = await import('/pilot/assets/screens/arm.js');
      const root = document.createElement('main'); document.body.replaceChildren(root);
      window.testHidden = false; window.released = 0; window.renewed = 0;
      Object.defineProperty(document, 'hidden', {configurable:true, get:()=>window.testHidden});
      const driver = {request: async (path, options={}) => {
        if (path === '/pair') return {token:'test-only'};
        if (path === '/whoami') return {};
        if (path === '/seat') return new Promise(resolve => {window.resolveSeat = resolve;});
        if (options.method === 'DELETE') {window.released++; return null;}
        if (options.method === 'PUT') {window.renewed++; return {};}
        throw new Error('unexpected request '+path);
      }};
      window.disposeArm = mountArm(root, {joints:['joint1'], gripper:'joint1'}, driver);
    }""")
    page.fill("[data-sim-code]", "test-only")
    page.click("[data-sim-connect]")
    page.wait_for_function("typeof window.resolveSeat === 'function'")
    page.evaluate("window.testHidden = true; document.dispatchEvent(new Event('visibilitychange')); window.resolveSeat({seat_id:'late-seat'})")
    page.wait_for_function("window.released === 1")
    page.wait_for_timeout(1100)
    assert page.evaluate("window.renewed") == 0
    page.evaluate("window.disposeArm()")
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
def test_input_preview_stays_live_after_settings_change_and_escape_closes(tablet_page):
    base_url, page, errors = tablet_page
    page.goto(f"{base_url}/pilot")
    page.evaluate("""async () => {
      const {mountInputs} = await import('/pilot/assets/screens/inputs.js');
      const root = document.createElement('section'); document.body.replaceChildren(root);
      window.padAxis = 0.1;
      Object.defineProperty(navigator, 'getGamepads', {configurable:true,
        value: () => [{axes:[window.padAxis, 0]}]});
      mountInputs(root, {onClose: () => root.remove()});
    }""")
    page.wait_for_function("document.querySelector('[data-input-preview]').textContent.includes('0.10')")
    page.get_by_role("button", name="빠름", exact=True).click()
    page.evaluate("window.padAxis = 0.8")
    page.wait_for_function("document.querySelector('[data-input-preview]').textContent.includes('0.80')")
    page.get_by_role("button", name="닫기", exact=True).focus()
    page.keyboard.press("Escape")
    assert page.locator("[data-input-preview]").count() == 0
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
def test_shared_action_icon_preserves_reason_and_button_behavior(tablet_page):
    base_url, page, errors = tablet_page
    page.goto(f"{base_url}/pilot")
    page.evaluate("""async () => {
      const {actionIcon} = await import('/common/ui.js');
      const button = document.createElement('ui-button');
      button.textContent = 'File'; button.setAttribute('kind', 'quiet');
      button.setAttribute('reason', 'Wait'); button.disabled = true;
      button.id = 'shared-icon-test'; document.body.append(button);
      window.iconClicks = 0; button.addEventListener('click', () => window.iconClicks++);
      actionIcon(button, 'download'); actionIcon(button, 'download');
    }""")
    button = page.get_by_role("button", name="File", exact=True)
    assert button.is_disabled()
    assert button.locator("svg").count() == 1
    assert button.locator("small[data-reason]").inner_text() == "Wait"
    page.evaluate("document.getElementById('shared-icon-test').disabled = false")
    button.focus()
    page.keyboard.press("Enter")
    assert page.evaluate("window.iconClicks") == 1
    assert errors == [], errors


@pytest.fixture(scope="module")
def base_url():
    listener = safe_listener()
    server = uvicorn.Server(uvicorn.Config(dev_server.app, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    while not server.started:
        thread.join(0.05)
    yield f"http://127.0.0.1:{listener.getsockname()[1]}"
    server.should_exit = True
    thread.join(timeout=5)
    listener.close()


def _click_tool(page, selector):
    if not page.locator(selector).is_visible():
        page.click("[data-drive-tools]")
    page.click(selector)


def _gate_value(page) -> str:
    readout = page.locator('dl[data-gate-readout]')
    return readout.get_attribute("data-gate-state") or readout.locator("dd").first.inner_text()


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
@pytest.mark.parametrize("width,height", [(2000, 1200), (1200, 2000), (390, 844), (320, 568)])
def test_camera_can_be_seen_in_emergency_without_engaging_motion(tablet_page, width, height):
    base_url, page, errors = tablet_page
    page.set_viewport_size({"width": width, "height": height})
    previous = dev_server.STATE["mode"]
    dev_server.STATE["mode"] = "EMERGENCY"
    before = len(dev_server.MODE_LOG)
    try:
        page.goto(f"{base_url}/pilot")
        page.fill("form[data-pilot-token-form] ui-field input", "devtoken")
        page.click("form[data-pilot-token-form] ui-button")
        page.wait_for_selector("[data-camera-preview]")
        assert page.locator("[data-drive-enter]").evaluate("e => e.disabled")
        assert page.locator("ui-topbar [data-estop]").is_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        if output := os.environ.get("ROSY_SHOT_DIR"):
            shots = Path(output)
            shots.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(shots / f"pilot-emergency-gate-{width}x{height}.png"))
        page.click("[data-camera-preview]")
        page.wait_for_function("document.querySelector('[data-readonly-camera] img')?.naturalWidth > 0")
        assert page.locator("ui-topbar [data-estop]").is_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        if width < 480:
            notice = page.locator("#pilot-notice").bounding_box()
            home = page.locator("ui-topbar [data-goto]").bounding_box()
            stop = page.locator("ui-topbar [data-estop]").bounding_box()
            assert home["y"] >= notice["y"] + notice["height"]
            assert stop["y"] >= notice["y"] + notice["height"]
            assert abs(home["width"] - stop["width"]) <= 1
        if output := os.environ.get("ROSY_SHOT_DIR"):
            page.screenshot(path=str(shots / f"pilot-emergency-camera-{width}x{height}.png"))
        assert dev_server.STATE["mode"] == "EMERGENCY"
        assert len(dev_server.MODE_LOG) == before
        page.click("[data-drive-fill]")
        page.click("[data-drive-fit]")
        page.click("[data-camera-back]")
        page.wait_for_selector("[data-camera-preview]")
        assert len(dev_server.MODE_LOG) == before
        assert errors == []
    finally:
        dev_server.STATE["mode"] = previous


@pytest.fixture
def tablet_page(base_url):
    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 2000, "height": 1200})
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.set_default_timeout(10_000)
        yield base_url, page, errors
        browser.close()


@pytest.fixture(autouse=True)
def _default_controls():
    """D-411 B: every test starts and ends with the default rosy.controls/1 descriptor."""
    dev_server.CONTROLS.update(items=[dev_server._BASE_CONTROL], omit=False)
    yield
    dev_server.CONTROLS.update(items=[dev_server._BASE_CONTROL], omit=False)


@pytest.mark.skipif(not browser_tests_enabled(),
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_gate_panel_at_tablet_viewports(base_url):
    """게이트가 모든 태블릿 뷰포트에서 올바른 조립을 갖는다."""
    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for width, height in TABLET_VIEWPORTS:
                page = browser.new_page(viewport={"width": width, "height": height})
                errors: list[str] = []
                page.on("pageerror", lambda exc: errors.append(str(exc)))
                page.goto(f"{base_url}/pilot")
                page.wait_for_selector("form[data-pilot-token-form] ui-field input")
                assert page.locator('ui-head#pilot-gate-heading').inner_text() == "접속"
                assert page.locator("form[data-pilot-token-form]").count() == 1
                assert page.locator("ui-topbar ui-tag").count() == 1
                assert page.locator('ui-topbar ui-button[data-estop][kind="irreversible"]').count() == 1
                manifest_href = page.evaluate(
                    "document.querySelector('link[rel=manifest]')?.href ?? ''")
                assert manifest_href.endswith("/pilot/assets/manifest.webmanifest")
                step = page.evaluate(
                    "getComputedStyle(document.documentElement).getPropertyValue('--space-1').trim()")
                assert step, "tokens.css 가 적용되지 않았다"
                overflow = page.evaluate(
                    "document.documentElement.scrollWidth - document.documentElement.clientWidth")
                assert overflow <= 0, f"가로 넘침 {overflow}px ({width}x{height})"
                assert errors == [], errors
                page.close()
        finally:
            browser.close()


@pytest.mark.skipif(not browser_tests_enabled(),
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_bad_token_is_refused_with_guidance(tablet_page):
    base_url, page, errors = tablet_page
    page.goto(f"{base_url}/pilot")
    page.wait_for_selector("form[data-pilot-token-form] ui-field input")
    page.fill("form[data-pilot-token-form] ui-field input", "wrong-token")
    page.click("form[data-pilot-token-form] ui-button")
    page.wait_for_selector("text=토큰이 유효하지 않습니다")
    tag = page.locator("[data-gate-state]").inner_text()
    assert tag in ("차단", "대기"), f"gate tag: {tag}"
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
@pytest.mark.parametrize("width,height", [(2000, 1200), (1200, 2000), (390, 844), (320, 568)])
def test_viewer_gate_denial_uses_operator_words_at_declared_widths(base_url, width, height):
    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": width, "height": height})
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.route("**/api/v1/auth/whoami",
                   lambda route: route.fulfill(json={"role": "viewer"}))
        try:
            page.goto(f"{base_url}/pilot")
            page.fill("form[data-pilot-token-form] ui-field input", "devtoken")
            page.click("form[data-pilot-token-form] ui-button")
            readout = page.locator("[data-gate-readout]")
            readout.wait_for(state="visible")
            if os.environ.get("ROSY_SHOT_DIR"):
                shot_dir = Path(os.environ["ROSY_SHOT_DIR"])
                shot_dir.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(shot_dir / f"pilot-viewer-denied-{width}x{height}.png"))
            text = page.locator("[data-screen=connect]").inner_text()
            assert "차단됨" in text and "조회 전용" in text
            assert "viewer" not in text and "BLOCK" not in text
            assert "운전 권한이 없습니다" in text
            assert page.locator("[data-drive-enter]").count() == 0
            assert page.locator("ui-topbar [data-estop]").is_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert errors == [], errors
        finally:
            browser.close()


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
@pytest.mark.parametrize("width,height", [(2000, 1200), (1200, 2000), (390, 844), (320, 568)])
def test_drive_withheld_gate_names_the_no_motion_reason(base_url, width, height):
    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": width, "height": height})
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.route("**/api/v1/system/capabilities", lambda route: route.fulfill(json={
            "teleop": False, "withheld": {"reasons": {"teleop": "drive_disabled:no_motion"}},
            "runtime": {"drive": False}}))
        try:
            page.goto(f"{base_url}/pilot")
            page.fill("form[data-pilot-token-form] ui-field input", "devtoken")
            page.click("form[data-pilot-token-form] ui-button")
            page.get_by_text("수동 운전이 보류되었습니다 — 구동 꺼짐 (무동작)").wait_for()
            if os.environ.get("ROSY_SHOT_DIR"):
                shot_dir = Path(os.environ["ROSY_SHOT_DIR"])
                shot_dir.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(shot_dir / f"pilot-drive-withheld-{width}x{height}.png"))
            text = page.locator("[data-screen=connect]").inner_text()
            assert "drive_disabled" not in text and "BLOCK" not in text
            assert "차단됨" in text and "운영자" in text
            assert page.locator("[data-drive-enter]").count() == 0
            assert page.locator("ui-topbar [data-estop]").is_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert errors == [], errors
        finally:
            browser.close()


@pytest.mark.skipif(not browser_tests_enabled(),
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_lobby_lists_neighbours_and_points_to_their_origin(tablet_page):
    """이웃 방 목록(D-343 2.2-3): 이 기기가 대신 찾은 방들이 보이고, 각 버튼이 그 origin URL 을 가진다."""
    base_url, page, errors = tablet_page
    page.route("**/api/v1/site/rooms",
               lambda route: route.fulfill(json={"rooms": [
                   {"hostname": "rosy-02", "address": "10.0.0.8", "port": 8080,
                    "kind": "robot", "url": "http://rosy-02.local:8080/pilot/#join"}]}))
    page.goto(f"{base_url}/pilot")
    page.wait_for_selector("form[data-pilot-token-form] ui-field input")
    room = page.locator("[data-lobby-room=rosy-02]")
    room.wait_for(state="visible")
    # 이동 목적지는 버튼의 진입 URL 에 명시돼 있다(D-343 2.3). 시험 호스트에서
    # 가짜 LAN 이름은 풀리지 않으므로 클릭하지 않고 목적지를 단언한다.
    assert room.get_attribute("data-lobby-url") == "http://rosy-02.local:8080/pilot/#join"
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(),
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_lobby_failure_shows_retry_and_gate_survives(tablet_page):
    """A failed scan is distinguishable from an empty LAN; login remains usable."""
    base_url, page, errors = tablet_page
    page.route("**/api/v1/site/rooms",
               lambda route: route.fulfill(status=503, json={"code": "DISCOVERY_UNAVAILABLE"}))
    page.goto(f"{base_url}/pilot")
    page.wait_for_selector("form[data-pilot-token-form] ui-field input")
    page.get_by_text("로봇 목록을 가져오지 못했습니다.", exact=False).wait_for(state="visible")
    page.locator("[data-lobby-retry]").wait_for(state="visible")
    assert page.locator("[data-lobby-room]").count() == 0
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
@pytest.mark.parametrize("width,height", [(2000, 1200), (1200, 2000), (390, 844), (320, 568)])
def test_lobby_empty_and_failure_fit_declared_widths(base_url, width, height):
    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": width, "height": height})
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        response = {"fail": False}
        page.route("**/api/v1/site/rooms", lambda route: route.fulfill(
            status=503, json={"code": "DISCOVERY_UNAVAILABLE"}) if response["fail"]
            else route.fulfill(json={"rooms": []}))
        try:
            page.goto(f"{base_url}/pilot")
            page.get_by_text("같은 LAN에서 발견한 다른 로봇이 없습니다").wait_for()
            for state in ("empty", "failed"):
                if state == "failed":
                    response["fail"] = True
                    page.locator("[data-lobby-retry]").click()
                    page.get_by_text("로봇 목록을 가져오지 못했습니다.", exact=False).wait_for()
                if os.environ.get("ROSY_SHOT_DIR"):
                    shot_dir = Path(os.environ["ROSY_SHOT_DIR"])
                    shot_dir.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(shot_dir / f"pilot-lobby-{state}-{width}x{height}.png"))
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert page.locator("[data-lobby-retry]").is_visible()
                assert page.locator("form[data-pilot-token-form] ui-field input").is_visible()
                assert page.locator("form[data-pilot-token-form] label").is_visible()
                estop = page.locator("ui-topbar [data-estop]").bounding_box()
                assert estop and estop["y"] + estop["height"] <= height, (state, width, estop)
                main_width = page.locator(".pilot-main").bounding_box()["width"]
                assert main_width >= min(width, 768) - 1, (state, width, main_width)
                widths = page.evaluate("""() => ['form[data-pilot-token-form] ui-field',
                    'form[data-pilot-token-form] ui-button', '[data-lobby-retry]']
                    .map(selector => document.querySelector(selector).getBoundingClientRect().width)""")
                if width < 480:
                    assert max(widths) - min(widths) <= 1, (state, width, widths)
            assert errors == [], errors
        finally:
            browser.close()


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
def test_lobby_retry_recovers_without_duplicate_scans(tablet_page):
    base_url, page, errors = tablet_page
    calls = []

    def rooms(route):
        calls.append(route.request.method)
        if len(calls) == 1:
            route.fulfill(status=503, json={"code": "DISCOVERY_UNAVAILABLE"})
        else:
            route.fulfill(json={"rooms": [{"hostname": "rosy-02.local", "address": "10.0.0.8",
                "port": 443, "kind": "robot", "url": "https://rosy-02.local/pilot/#join"}]})

    page.route("**/api/v1/site/rooms", rooms)
    page.goto(f"{base_url}/pilot")
    page.locator("[data-lobby-retry]").wait_for(state="visible")
    page.evaluate("""() => {const retry=document.querySelector('[data-lobby-retry]');
        retry.click(); retry.click(); retry.click();}""")
    page.locator('[data-lobby-room="rosy-02.local"]').wait_for(state="visible")
    assert calls == ["GET", "GET"]
    assert page.locator("form[data-pilot-token-form] ui-field input").is_visible()
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
def test_connection_offer_names_this_robot_before_the_neighbour(tablet_page):
    """The page you opened is this robot. The other robot stays a secondary choice."""
    base_url, page, errors = tablet_page
    page.route("**/api/v1/auth/connection", lambda route: route.fulfill(
        json={"mode": "paired", "robot_id": "rosy_26", "transport": "https"}))
    page.route("**/api/v1/site/rooms", lambda route: route.fulfill(json={"rooms": [
        {"hostname": "rosy-pinky-8kcn.local", "address": "10.0.0.8", "port": 8080, "kind": "robot",
         "url": "https://rosy-pinky-8kcn.local:8080/pilot/#join"}]}))
    page.goto(f"{base_url}/pilot")
    page.locator("[data-connection-title]").wait_for()
    page.locator("[data-lobby-room='rosy-pinky-8kcn.local']").wait_for(state="visible")
    offer = page.locator("[data-connection-offer]")
    assert offer.get_attribute("data-connection-mode") == "paired"
    assert offer.get_attribute("data-robot-id") == "rosy_26"
    assert page.locator("[data-connection-title]").inner_text() == "rosy_26"
    assert "로봇 화면에 뜬 로그인 코드" in offer.inner_text()
    assert page.locator("[data-dev-connect]").count() == 0
    text = page.locator("[data-screen=connect]").inner_text()
    assert text.index("rosy_26") < text.index("rosy-pinky-8kcn.local")
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
def test_development_connection_enters_without_a_screen_code(tablet_page):
    """development mode offers a one-hour operator session. paired mode does not."""
    base_url, page, errors = tablet_page
    calls = []

    def connection(route):
        route.fulfill(json={"mode": "development", "robot_id": "rosy_60", "transport": "https"})

    def session(route):
        calls.append(route.request.post_data)
        route.fulfill(status=201, json={
            "id": "dev-session", "token": "devtoken", "role": "operator",
            "label": "Pilot development session", "source": "pair-development", "expires_at": None,
        })

    page.route("**/api/v1/auth/connection", connection)
    page.route("**/api/v1/auth/development-session", session)
    page.goto(f"{base_url}/pilot")
    page.locator("[data-dev-connect]").wait_for(state="visible")
    assert "코드 없이" in page.locator("[data-connection-copy]").inner_text()
    assert page.locator("form[data-pilot-token-form]").is_visible()
    page.locator("[data-dev-connect]").click()
    page.wait_for_selector("[data-drive-enter]")
    assert calls == ["{}"]
    assert "rosy_60" in page.locator("[data-screen=connect]").inner_text()
    recent = page.evaluate("localStorage.getItem('rosy.pilot.recent') || ''")
    assert "devtoken" not in recent
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
def test_development_connection_refusal_keeps_the_code_form(tablet_page):
    base_url, page, errors = tablet_page
    page.route("**/api/v1/auth/connection", lambda route: route.fulfill(
        json={"mode": "development", "robot_id": "rosy_60", "transport": "https"}))
    page.route("**/api/v1/auth/development-session", lambda route: route.fulfill(
        status=403, json={"error": {"code": "FORBIDDEN", "message": "this robot requires pairing"}}))
    page.goto(f"{base_url}/pilot")
    page.locator("[data-dev-connect]").click()
    page.get_by_text("이 로봇은 개발 연결 모드가 아닙니다.", exact=False).wait_for()
    assert page.locator("[data-dev-connect]").is_enabled()
    assert page.locator("form[data-pilot-token-form] ui-field input").is_visible()
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
def test_lobby_rejects_unsafe_urls_and_suppresses_current_robot(tablet_page):
    from urllib.parse import urlsplit
    base_url, page, errors = tablet_page
    local = urlsplit(base_url)
    rows = [{"hostname": "rosy-02.local", "address": "10.0.0.8", "port": 8080, "kind": "robot", "url": url}
            for url in ("javascript:alert(1)", "https://elsewhere.example/pilot/#join",
                        "http://user:secret@rosy-02.local:8080/pilot/#join")]
    rows += [{"hostname": "rosy-01.local", "address": local.hostname, "port": local.port,
              "kind": "robot", "url": f"http://rosy-01.local:{local.port}/pilot/#join"},
             {"hostname": "rosy-03.local", "address": "10.0.0.9", "port": 443, "kind": "robot",
              "url": "https://rosy-03.local/pilot/#join"}]
    page.route("**/api/v1/site/rooms", lambda route: route.fulfill(json={"rooms": rows}))
    page.goto(f"{base_url}/pilot")
    page.locator('[data-lobby-room="rosy-03.local"]').wait_for(state="visible")
    assert page.locator("[data-lobby-room]").count() == 1
    assert "선택한 로봇에서 승인·로그인을 확인합니다" in page.locator("[data-lobby-list]").inner_text()
    assert errors == [], errors


def _refuse_second_session(page):
    calls = []

    def refuse(route):
        calls.append(route.request.url)
        route.fulfill(status=500, body="second session")

    page.route("**/api/v1/auth/development-session", refuse)
    page.route("**/api/v1/auth/pair", refuse)
    return calls


def _open_in_pilot_app(page, base_url, token):
    """Same handoff as PilotProxy: a classic script at the start of <head>, before the modules."""

    def inject(route):
        response = route.fetch()
        store = (
            f"sessionStorage.setItem('rosy.pilot.token',{json.dumps(token)});"
            if token else "")
        script = (
            "<script>document.documentElement.dataset.pilotShell='android';"
            f"{store}</script>")
        headers = {
            key: value for key, value in response.headers.items()
            if key.lower() not in {"content-length", "content-encoding"}}
        route.fulfill(
            status=response.status, headers=headers,
            body=response.text().replace("<head>", "<head>" + script, 1))

    page.route("**/pilot", inject)
    page.goto(f"{base_url}/pilot")


def _assert_visible(page, selector, errors):
    try:
        page.locator(selector).wait_for()
    except Exception:
        shell = page.evaluate("document.documentElement.dataset.pilotShell")
        token = page.evaluate("sessionStorage.getItem('rosy.pilot.token')")
        text = page.locator("body").inner_text()
        raise AssertionError(
            f"missing {selector}; shell={shell!r} token={token!r} text={text!r} errors={errors!r}") from None


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
def test_android_shell_uses_the_app_session(tablet_page):
    """The Pilot app already connected. The page uses that token and does not open another session."""
    base_url, page, errors = tablet_page
    calls = _refuse_second_session(page)
    _open_in_pilot_app(page, base_url, "devtoken")
    _assert_visible(page, "[data-drive-enter]", errors)
    assert calls == []
    assert page.locator("[data-dev-connect]").count() == 0
    assert page.locator("[data-lobby-list]").count() == 0
    assert page.locator("form[data-pilot-token-form]").count() == 0
    assert page.locator("[data-enroll-section]").count() == 0
    assert page.locator("ui-topbar [data-goto]").is_hidden()
    assert page.evaluate("navigator.serviceWorker.getRegistrations().then((list) => list.length)") == 0
    page.click("[data-drive-enter]")
    page.wait_for_selector("[data-drive-stick]")
    assert page.locator("[data-drive-goal]").count() == 0
    assert page.locator("ui-topbar [data-goto]").is_hidden()
    page.locator("ui-topbar [data-goto]").evaluate("node => node.click()")
    page.wait_for_timeout(200)
    assert "/console" not in page.url
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
@pytest.mark.parametrize("token_value", ["", "not-a-session"])
def test_android_shell_without_a_session_stays_with_the_app(tablet_page, token_value):
    base_url, page, errors = tablet_page
    calls = _refuse_second_session(page)
    _open_in_pilot_app(page, base_url, token_value)
    _assert_visible(page, "[data-app-session]", errors)
    assert "Rosy Pilot 앱이 엽니다" in page.locator("[data-app-session]").inner_text()
    assert page.locator("[data-dev-connect]").count() == 0
    assert page.locator("form[data-pilot-token-form]").count() == 0
    assert page.locator("[data-lobby-list]").count() == 0
    assert calls == []
    assert errors == [], errors


def _enter_drive(page, base_url, access_token=None):
    page.goto(f"{base_url}/pilot")
    page.wait_for_selector("form[data-pilot-token-form] ui-field input")
    page.fill("form[data-pilot-token-form] ui-field input", access_token or dev_server.DEV_TOKEN)
    page.click("form[data-pilot-token-form] ui-button")
    page.wait_for_selector("[data-drive-enter]")
    page.click("[data-drive-enter]")
    page.wait_for_selector("[data-drive-stick]")
    page.wait_for_function("document.querySelector('[data-drive-fact=cap]')?.textContent.includes('0.10')")


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
@pytest.mark.parametrize("viewport", [(2000, 1200), (390, 844)])
def test_drive_map_handoff_reaches_console_after_stop_readback(base_url, viewport):
    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            _enter_drive(page, base_url)
            page.wait_for_function("document.querySelector('[data-drive-fact=link]')?.dataset.state === 'OPEN'")
            if output := os.environ.get("ROSY_SHOT_DIR"):
                shots = Path(output)
                shots.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(shots / f"pilot-map-handoff-{viewport[0]}x{viewport[1]}.png"), full_page=True)
            button = page.locator("ui-topbar [data-goto]")
            assert button.get_attribute("data-goto") == "/console"
            assert button.inner_text() == "운용 지도"
            assert page.locator('[aria-label="운전 모드"] [data-drive-goal]').count() == 0
            page.evaluate("sessionStorage.setItem('rosy.dashboard.token', 'old-surface-token')")
            modes_before, teleop_before = len(dev_server.MODE_LOG), len(dev_server.TELEOP_LOG)
            arrived = []

            def console(route):
                arrived.append({"modes": dev_server.MODE_LOG[modes_before:],
                                "teleop": dev_server.TELEOP_LOG[teleop_before:]})
                route.fulfill(status=200, content_type="text/html", body="<h1>운용 지도</h1>")

            page.route("**/console", console)
            button.click()
            page.wait_for_url("**/console")
            assert page.evaluate("sessionStorage.getItem('rosy.dashboard.token')") == dev_server.DEV_TOKEN
            assert page.evaluate("localStorage.getItem('rosy.dashboard.paired')") is None
            assert dev_server.DEV_TOKEN not in page.url
            assert arrived and "IDLE" in arrived[0]["modes"]
            assert any(item["linear"] == 0 and item["angular"] == 0 for item in arrived[0]["teleop"])
            assert errors == []
        finally:
            browser.close()


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
@pytest.mark.parametrize("viewport", [(2000, 1200), (390, 844)])
def test_drive_handoff_opens_real_console_map_in_same_tab(base_url, viewport, tmp_path, monkeypatch):
    """Pilot's live tab reaches the real CORE Console assets with its own token."""
    root = HERE.parents[3]
    for package in ("middleware/core/api_web", "middleware/core/gateway", "middleware/core/events",
                    "middleware/core/services", "contracts/foundation"):
        monkeypatch.syspath_prepend(str(root / package))
    from fastapi.testclient import TestClient
    from core_api_web.api.app import create_app
    from core_common.profile import RobotProfile, robot_config_dir
    from core.services import CoreServices
    import yaml
    from urllib.parse import urlsplit

    config_dir = root / "contracts/foundation/config"
    config = yaml.safe_load((config_dir / "rosy_default.yaml").read_text(encoding="utf-8"))
    config["auth"] = {**config["auth"], **yaml.safe_load(
        (config_dir / "rosy_dev_auth.yaml").read_text(encoding="utf-8"))["auth"]}
    operator = next(item for item in config["auth"]["tokens"] if item["role"] == "operator")
    monkeypatch.setattr(dev_server, "DEV_TOKEN", operator["token"])
    profile = RobotProfile.load(robot_config_dir("pinky_pro") / "profile.yaml")
    capabilities = yaml.safe_load((robot_config_dir("pinky_pro") / "capabilities.yaml").read_text(encoding="utf-8"))
    core = TestClient(create_app(config, CoreServices.build(config, profile, capabilities, tmp_path / "docks.json")))
    phase = {"console": False}
    requests = []

    def serve(route):
        target = urlsplit(route.request.url)
        path = target.path
        if path == "/console":
            phase["console"] = True
        if not phase["console"]:
            route.continue_()
            return
        requests.append((route.request.method, path, route.request.headers.get("authorization")))
        if route.request.method != "GET":
            route.fulfill(status=501, json={"detail": "fixture blocks writes"})
            return
        response = core.get(path + (f"?{target.query}" if target.query else ""),
                            headers={"Authorization": route.request.headers.get("authorization", "")})
        route.fulfill(status=response.status_code, headers={
            "content-type": response.headers.get("content-type", "application/octet-stream"),
            "cache-control": "no-store",
        }, body=response.content)

    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("**/*", serve)
            _enter_drive(page, base_url, operator["token"])
            page.wait_for_function("document.querySelector('[data-drive-fact=link]')?.dataset.state === 'OPEN'")
            if output := os.environ.get("ROSY_SHOT_DIR"):
                shots = Path(output)
                shots.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(shots / f"pilot-before-console-{viewport[0]}x{viewport[1]}.png"), full_page=True)
            modes_before, teleop_before = len(dev_server.MODE_LOG), len(dev_server.TELEOP_LOG)
            page.locator("ui-topbar [data-goto='/console']").click()
            page.wait_for_url("**/console")
            page.locator('[data-panel="console.map"] .surface-map-frame').wait_for(state="visible")
            page.wait_for_function("document.querySelector('#map-status')?.getAttribute('state') === 'empty'")
            assert "지도 데이터가 아직 없습니다" in page.locator('.surface-map-overlay').inner_text()
            assert "지도가 들어오면 읽기 전용으로" in page.locator('#map-action-reason').inner_text()
            assert page.evaluate("sessionStorage.getItem('rosy.dashboard.token')") == operator["token"]
            assert page.evaluate("localStorage.getItem('rosy.dashboard.paired')") is None
            assert ("GET", "/api/v1/ui/surfaces/console", f"Bearer {operator['token']}") in requests
            assert "IDLE" in dev_server.MODE_LOG[modes_before:]
            assert any(item["linear"] == 0 and item["angular"] == 0 for item in dev_server.TELEOP_LOG[teleop_before:])
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert page.locator("#shell-estop").is_visible()
            spacing = page.evaluate("""() => {
              const layers = document.querySelector('[aria-label="지도 레이어"]').getBoundingClientRect();
              const setup = document.querySelector('.surface-link[href="/setup"]').getBoundingClientRect();
              const status = document.querySelector('#map-status').getBoundingClientRect();
              return {layersBottom: layers.bottom, setupTop: setup.top,
                      setupBottom: setup.bottom, statusTop: status.top};
            }""")
            assert spacing["layersBottom"] <= spacing["setupTop"] <= spacing["setupBottom"] <= spacing["statusTop"], spacing
            assert errors == [], errors
            if output:
                page.screenshot(path=str(shots / f"console-after-pilot-{viewport[0]}x{viewport[1]}.png"), full_page=True)
        finally:
            browser.close()


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
@pytest.mark.parametrize("viewport", [(2000, 1200), (1200, 2000), (390, 844), (320, 568)])
def test_drive_hud_uses_operator_labels_at_each_width(base_url, viewport):
    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            _enter_drive(page, base_url)
            link = page.locator("[data-drive-fact=link]")
            page.wait_for_function("document.querySelector('[data-drive-fact=link]').dataset.state === 'OPEN'")
            assert link.inner_text() == "상태 수신"
            assert page.locator("[data-drive-fact=mode]").inner_text() == "수동"
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert errors == []
            if os.environ.get("ROSY_SHOT_DIR"):
                shots = Path(os.environ["ROSY_SHOT_DIR"])
                shots.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(shots / f"pilot-drive-status-{viewport[0]}x{viewport[1]}.png"))
        finally:
            browser.close()


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
def test_drive_hud_does_not_invent_zero_before_velocity_readback(base_url):
    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 320, "height": 568})
            page.route("**/api/v1/robot/state", lambda route: route.fulfill(status=503, json={}))
            page.route_web_socket("**/ws/state", lambda route: route.on_message(lambda raw: None))
            _enter_drive(page, base_url)
            assert page.locator("[data-drive-fact=speed]").inner_text() == "—"
            assert page.locator("[data-drive-fact=turn]").inner_text() != "· 0°/s"
            assert page.locator("[data-drive-fact=battery]").inner_text() == "—"
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        finally:
            browser.close()


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
@pytest.mark.parametrize("failure", ["status", "hang"])
@pytest.mark.parametrize("viewport", [(2000, 1200), (1200, 2000), (390, 844), (320, 568)])
def test_drive_hud_clears_readback_when_open_socket_goes_silent_and_rest_fails(base_url, failure, viewport):
    stamp = "2026-10-07T06:00:00Z"
    frame = {"type": "state", "mode": "MANUAL", "timestamp": stamp,
             "velocity": {"linear": 0.12, "angular": 0.1}, "battery": {"percent": 81},
             "evidence": {channel: {"evidence": "fresh", "received_at": stamp}
                          for channel in ("velocity", "battery")}}
    failing = {"value": ""}
    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})
            def state_reply(route):
                if failing["value"] == "hang":
                    return
                route.fulfill(status=503, json={}) if failing["value"] else route.fulfill(json=frame)

            page.route("**/api/v1/robot/state", state_reply)
            page.route_web_socket("**/ws/state", lambda route: route.on_message(
                lambda raw: route.send(json.dumps(frame)) if json.loads(raw).get("type") == "auth" else None))
            _enter_drive(page, base_url)
            page.wait_for_function("document.querySelector('[data-drive-fact=speed]').textContent === '0.12'")
            page.wait_for_function("document.querySelector('[data-drive-fact=latency]').textContent.startsWith('조작 응답 ')")
            failing["value"] = failure
            page.wait_for_function("document.querySelector('[data-drive-fact=speed]').textContent === '—'", timeout=5000)
            assert page.locator("[data-drive-fact=battery]").inner_text() != "81%"
            assert page.locator("[data-drive-fact=link]").inner_text() == "상태 수신 없음"
            assert page.locator("ui-topbar [data-estop]").is_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            if output := os.environ.get("ROSY_SHOT_DIR"):
                shot_dir = Path(output)
                shot_dir.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(shot_dir / f"pilot-readback-{failure}-{viewport[0]}x{viewport[1]}.png"))
            failing["value"] = ""
            page.wait_for_function("document.querySelector('[data-drive-fact=speed]').textContent === '0.12'")
            assert page.locator("[data-drive-fact=link]").inner_text() == "상태 수신"
        finally:
            browser.close()


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
@pytest.mark.parametrize("state", ["fresh", "delayed", "disconnected", "unavailable"])
def test_drive_telemetry_evidence_at_declared_widths(base_url, state):
    stamp = "2026-10-07T06:00:03Z"
    observed = "2026-10-07T06:00:00Z" if state == "delayed" else stamp
    frame = {"type": "state", "mode": "MANUAL", "timestamp": stamp,
             "velocity": {"linear": 0.12, "angular": 0.1}, "battery": {"percent": 81},
             "evidence": {channel: {"evidence": state, "received_at": observed}
                          for channel in ("velocity", "battery")}}
    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for width, height in [(2000, 1200), (1200, 2000), (390, 844), (320, 568)]:
                page = browser.new_page(viewport={"width": width, "height": height})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.route("**/api/v1/robot/state", lambda route: route.fulfill(json=frame))

                def status_socket(route):
                    route.on_message(lambda raw: route.send(json.dumps(frame))
                                     if json.loads(raw).get("type") == "auth" else None)

                page.route_web_socket("**/ws/state", status_socket)
                _enter_drive(page, base_url)
                page.wait_for_function("document.querySelector('[data-drive-fact=link]').dataset.state === 'OPEN'")
                speed = page.locator("[data-drive-fact=speed]")
                turn = page.locator("[data-drive-fact=turn]").inner_text()
                battery = page.locator("[data-drive-fact=battery]").inner_text()
                assert speed.get_attribute("data-evidence") == state
                if state == "fresh":
                    assert speed.inner_text() == "0.12" and "6°/s" in turn and battery == "81%"
                elif state == "delayed":
                    assert speed.inner_text() == "0.12"
                    assert "지연 · 3초 전" in turn and "지연 · 3초 전" in battery
                else:
                    label = "연결 끊김" if state == "disconnected" else "정보 없음"
                    assert speed.inner_text() == "—"
                    assert label in turn and label in battery
                assert page.locator("ui-topbar [data-estop]").is_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert page.evaluate("document.querySelector('[data-drive-view]').getBoundingClientRect().height / innerHeight > 0.2")
                assert errors == []
                if os.environ.get("ROSY_SHOT_DIR"):
                    shots = Path(os.environ["ROSY_SHOT_DIR"])
                    shots.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(shots / f"pilot-telemetry-{state}-{width}x{height}.png"))
                page.close()
        finally:
            browser.close()


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
@pytest.mark.parametrize("viewport", [(2000, 1200), (1200, 2000), (390, 844), (320, 568)])
def test_drive_reconnect_warning_stays_visible_at_each_width(base_url, viewport):
    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})
            sockets, errors = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))

            def status_socket(route):
                sockets.append(route)
                route.on_message(lambda raw: route.send(json.dumps({"type": "state", "mode": "MANUAL"}))
                                 if json.loads(raw).get("type") == "auth" else None)

            page.route_web_socket("**/ws/state", status_socket)
            _enter_drive(page, base_url)
            page.wait_for_function("document.querySelector('[data-drive-fact=link]').dataset.state === 'OPEN'")
            sockets[-1].close(code=1011)
            link = page.locator("[data-drive-fact=link]")
            page.wait_for_function("document.querySelector('[data-drive-fact=link]').dataset.state === 'RETRYING'")
            assert link.inner_text() == "상태 재연결 중"
            assert link.is_visible()
            assert page.locator("[data-estop]").is_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert errors == []
            if os.environ.get("ROSY_SHOT_DIR"):
                shots = Path(os.environ["ROSY_SHOT_DIR"])
                shots.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(shots / f"pilot-reconnect-{viewport[0]}x{viewport[1]}.png"))
        finally:
            browser.close()


@pytest.mark.skipif(not browser_tests_enabled(),
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_drive_screen_fullscreen_with_camera_and_controls(tablet_page):
    """주행 화면이 풀스크린 카메라 + 2 축 스틱 + 페달 + 제자리 회전 + 프리셋을 갖는다."""
    base_url, page, errors = tablet_page
    _enter_drive(page, base_url)
    layout = page.evaluate("""(() => {
      const box = (s) => { const r = document.querySelector(s)?.getBoundingClientRect(); return r ? {w: Math.round(r.width), h: Math.round(r.height)} : null; };
      return {viewport: {w: innerWidth, h: innerHeight}, body: document.body.dataset.pilotScreen,
              drive: box('.pilot-drive'), stick: box('[data-drive-stick]'), pedals: box('[data-drive-pedals]'),
              pivots: box('[data-drive-pivots]'), hscroll: document.documentElement.scrollWidth > innerWidth};
    })()""")
    assert layout["body"] == "drive"
    assert layout["drive"]["w"] >= layout["viewport"]["w"] * 0.9
    assert layout["stick"]["w"] > 100, "스틱이 너무 작다"
    assert layout["pedals"]["w"] > 50 and layout["pivots"]["w"] > 50
    assert layout["hscroll"] is False
    assert page.locator("[data-drive-preset-row] ui-button").count() == 3
    # 상한은 CORE 한도(0.15 m/s) × 기본 프리셋 중(0.7)
    assert "0.10 m/s" in page.inner_text("[data-drive-fact=cap]")
    page.wait_for_selector("[data-drive-frame][src]", timeout=10_000)
    assert page.evaluate("document.querySelector('[data-drive-frame]')?.naturalWidth ?? 0") > 0
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(),
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_stick_right_turns_clockwise_pivot_holds_position_and_release_zeroes(tablet_page):
    """가제보 실측 규약(REP-103)을 브라우저 종단으로 고정: 오른쪽 = angular 음수."""
    base_url, page, errors = tablet_page
    _enter_drive(page, base_url)
    log = f"{base_url}/__test__/teleop"
    box = page.locator("[data-drive-stick]").bounding_box()
    cx, cy, r = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, box["width"] / 2

    def during(action):
        before = len(page.request.get(log).json())
        action()
        page.wait_for_timeout(600)
        return page.request.get(log).json()[before:]

    def drag(fx, fy):
        page.mouse.move(cx, cy)
        page.mouse.down()
        page.mouse.move(cx + fx * r, cy - fy * r, steps=3)

    right = during(lambda: drag(1, 0))
    page.mouse.up()
    page.wait_for_timeout(500)
    after_release = page.request.get(log).json()
    moving = [c for c in right if c["angular"] or c["linear"]]
    assert moving and all(c["angular"] < 0 and c["linear"] == 0 for c in moving), moving
    assert after_release[-1]["linear"] == 0 and after_release[-1]["angular"] == 0
    assert all(c["mode"] == "MANUAL" for c in after_release), "수동 모드 전에 명령을 보냈다"

    pivot = page.locator("[data-drive-pivot=left]").bounding_box()
    page.mouse.move(pivot["x"] + 10, pivot["y"] + 10)
    left = during(lambda: page.mouse.down())
    badge = page.inner_text("[data-drive-motion]")
    page.mouse.up()
    moving = [c for c in left if c["angular"] or c["linear"]]
    assert moving and all(c["angular"] > 0 and c["linear"] == 0 for c in moving), moving
    assert "제자리" in badge
    assert all(abs(c["angular"]) <= 0.6 + 1e-9 and abs(c["linear"]) <= 0.15 + 1e-9
               for c in page.request.get(log).json()), "CORE 수동 한도를 넘겼다"
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(),
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_speed_preset_and_fine_change_the_cap(tablet_page):
    base_url, page, errors = tablet_page
    _enter_drive(page, base_url)
    page.click("[data-drive-preset-row] [data-preset=high]")
    assert "0.15 m/s" in page.inner_text("[data-drive-fact=cap]")
    page.click("[data-drive-fine]")
    assert "0.04 m/s" in page.inner_text("[data-drive-fact=cap]")   # 0.15 × 0.3
    config = page.evaluate("JSON.parse(localStorage.getItem('rosy.pilot.input') ?? '{}')")
    assert config.get("preset") == "high" and config.get("fine") is True
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(),
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_key_released_while_an_input_has_focus_still_stops(tablet_page):
    """W 를 누른 채 입력 조정 슬라이더를 누르고 W 를 떼도 키가 눌린 채 남지 않는다(리뷰 지적)."""
    base_url, page, errors = tablet_page
    _enter_drive(page, base_url)
    log = f"{base_url}/__test__/teleop"
    _click_tool(page, "[data-drive-inputs]")
    page.wait_for_selector("[data-inputs-panel] input[type=range]")
    page.keyboard.down("KeyW")
    page.wait_for_timeout(400)
    page.focus("[data-inputs-panel] input[type=range]")
    page.keyboard.up("KeyW")
    page.wait_for_timeout(700)
    tail = page.request.get(log).json()[-3:]
    assert any(c["linear"] > 0 for c in page.request.get(log).json()), "W 로 전진 명령이 나가야 한다"
    assert all(c["linear"] == 0 and c["angular"] == 0 for c in tail), tail
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(),
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_login_code_pairs_and_recent_list_keeps_no_token(tablet_page):
    """로그인 코드로 입장하고(D-193), 최근 접속에는 토큰을 남기지 않는다(D-343)."""
    base_url, page, errors = tablet_page
    page.goto(f"{base_url}/pilot")
    page.evaluate("localStorage.setItem('rosy.pilot.recent', JSON.stringify([{host: 'x', label: 'old', token: 'leak'}]))")
    page.reload()
    page.wait_for_selector("form[data-pilot-token-form] ui-field input")
    assert "leak" not in page.evaluate("localStorage.getItem('rosy.pilot.recent')"), "옛 평문 토큰을 걷어내야 한다"
    page.fill("form[data-pilot-token-form] ui-field input", "WRNG-CODE")
    page.click("form[data-pilot-token-form] ui-button")
    page.wait_for_selector("text=코드가 맞지 않거나 만료됐습니다")
    page.fill("form[data-pilot-token-form] ui-field input", "test-code")
    page.click("form[data-pilot-token-form] ui-button")
    page.wait_for_selector("[data-drive-enter]")
    assert page.evaluate("sessionStorage.getItem('rosy.pilot.token')") == "devtoken"
    recent = page.evaluate("localStorage.getItem('rosy.pilot.recent')")
    assert "devtoken" not in recent and "token" not in recent, recent
    assert errors == [], errors


MEASURE_VIDEO = """(() => {
  const frame = document.querySelector('[data-drive-frame]');
  const box = frame.getBoundingClientRect();
  const ratio = frame.naturalWidth / frame.naturalHeight;
  // object-fit: contain 으로 실제 그려지는 사각형
  let w = box.width, h = box.width / ratio;
  if (h > box.height) { h = box.height; w = h * ratio; }
  const video = {x: box.x + (box.width - w) / 2, y: box.y + (box.height - h) / 2, w, h};
  const hit = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
  const rects = [...document.querySelectorAll('[data-drive-controls] ui-button, [data-drive-stick], [data-drive-hud], ui-topbar')]
    .map(e => { const r = e.getBoundingClientRect(); return {x: r.x, y: r.y, w: r.width, h: r.height}; })
    .filter(r => r.w && r.h);
  return {fit: getComputedStyle(frame).objectFit, ratio, shown: w / h, video,
          layout: document.querySelector('[data-screen=drive]').dataset.driveLayout,
          overlaps: rects.filter(r => hit(r, video)).length, videoArea: w * h / (innerWidth * innerHeight)};
})()"""


@pytest.mark.skipif(not browser_tests_enabled(),
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
@pytest.mark.parametrize("viewport", [(2000, 1200), (1333, 760), (1200, 2000), (390, 844), (320, 568)])
def test_camera_keeps_aspect_and_controls_never_cover_it(base_url, viewport):
    """D-363: 카메라는 원본 비율 그대로 전부 보이고, 조작부·HUD·상단 바가 영상을 덮지 않는다."""
    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})
        try:
            _enter_drive(page, base_url)
            page.wait_for_selector("[data-drive-frame][src]", state="attached", timeout=10_000)
            page.wait_for_function("document.querySelector('[data-drive-frame]').naturalWidth > 0")
            page.wait_for_timeout(300)
            m = page.evaluate(MEASURE_VIDEO)
            controls = page.evaluate("""() => ({
              viewport: innerHeight,
              boxes: ['[data-drive-pedal=forward]', '[data-drive-pedal=reverse]',
                      '[data-drive-pivot=left]', '[data-drive-pivot=right]', '[data-drive-stick]']
                .map(selector => ({selector, bottom: document.querySelector(selector).getBoundingClientRect().bottom}))
            })""")
            if os.environ.get("ROSY_SHOT_DIR"):
                shot_dir = Path(os.environ["ROSY_SHOT_DIR"])
                shot_dir.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(shot_dir / f"pilot-drive-current-{viewport[0]}x{viewport[1]}.png"))
            if viewport[0] < 480:
                action_boxes = page.evaluate("""() => {
                  const actions = document.querySelector('[data-drive-hud] ui-actions');
                  const track = actions.getBoundingClientRect();
                  return {track: {left: track.left, right: track.right}, buttons: [...actions.children].map(button => {
                    const box = button.getBoundingClientRect();
                    return {left: box.left, right: box.right, top: box.top, width: box.width, height: box.height};
                  })};
                }""")
                cue = page.locator("[data-drive-scroll-cue]").bounding_box()
                stick = page.locator("[data-drive-stick]").bounding_box()
                if viewport[0] == 320:
                    hud = page.locator("[data-drive-hud]").bounding_box()
                    idle = page.locator("[data-drive-idle]").bounding_box()
                    assert idle and idle["y"] >= hud["y"] and idle["y"] + idle["height"] <= hud["y"] + hud["height"]
                    facts = page.locator("[data-drive-facts]").bounding_box()
                    assert facts and facts["y"] + facts["height"] <= hud["y"] + hud["height"]
                    tools = page.locator("[data-drive-tools]").bounding_box()
                    assert tools and tools["y"] + tools["height"] <= hud["y"] + hud["height"]
                scrolled = page.evaluate("""() => ({
                  panel: (() => { const panel = document.querySelector('[data-drive-controls]');
                    panel.scrollTop = panel.scrollHeight; return panel.scrollTop; })(),
                  pivotBottom: document.querySelector('[data-drive-pivot=right]').getBoundingClientRect().bottom,
                  viewport: innerHeight,
                  page: document.documentElement.scrollTop
                })""")
                if os.environ.get("ROSY_SHOT_DIR"):
                    page.screenshot(path=str(shot_dir / f"pilot-drive-turn-controls-{viewport[0]}x{viewport[1]}.png"))
        finally:
            browser.close()
    assert m["fit"] == "contain", m
    assert abs(m["shown"] - m["ratio"]) / m["ratio"] < 0.01, m
    assert m["overlaps"] == 0, m
    assert m["videoArea"] > 0.2, f"영상이 너무 작다: {m}"
    if viewport[0] < 480:
        buttons = action_boxes["buttons"]
        assert len(buttons) == (2 if viewport[0] == 320 else 4), action_boxes
        assert max(button["width"] for button in buttons) - min(button["width"] for button in buttons) <= 1, action_boxes
        assert all(button["height"] >= 44 for button in buttons), action_boxes
        assert abs(buttons[0]["left"] - action_boxes["track"]["left"]) <= 1, action_boxes
        assert abs(buttons[-1]["right"] - action_boxes["track"]["right"]) <= 1, action_boxes
        assert abs(buttons[0]["top"] - buttons[1]["top"]) <= 1, action_boxes
        if len(buttons) == 4:
            assert abs(buttons[2]["top"] - buttons[3]["top"]) <= 1, action_boxes
        assert all(box["bottom"] <= controls["viewport"] for box in controls["boxes"]
                   if "pedal" in box["selector"] or "stick" in box["selector"]), controls
        assert cue["y"] >= stick["y"] + stick["height"] and cue["y"] + cue["height"] <= viewport[1]
        assert scrolled["panel"] > 0 and scrolled["pivotBottom"] <= scrolled["viewport"] + 1 and scrolled["page"] == 0, scrolled
    else:
        assert all(box["bottom"] <= controls["viewport"] for box in controls["boxes"]), controls


CONTROL_BOXES = """(() => {
  const box = (s) => { const r = document.querySelector(s).getBoundingClientRect();
    return {x: r.x, y: r.y, w: r.width, h: r.height}; };
  return {stick: box('[data-drive-stick]'), pedal: box('[data-drive-pedal=forward]'),
          vw: innerWidth, vh: innerHeight};
})()"""


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
@pytest.mark.parametrize("viewport", [(2000, 1200), (1200, 2000)])
def test_camera_direct_views_pan_crop_and_restore_whole_frame(base_url, viewport):
    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})
        try:
            _enter_drive(page, base_url)
            page.wait_for_function("document.querySelector('[data-drive-frame]').naturalWidth > 0")
            page.click("[data-drive-fill]")
            page.wait_for_function("document.querySelector('[data-screen=drive]').dataset.viewMode === 'full'")
            assert "잘림" in page.inner_text("[data-drive-fact=zoom]")
            frame = page.locator("[data-drive-frame]")
            before = frame.evaluate("e => getComputedStyle(e).objectPosition")
            box = page.locator("[data-drive-view]").bounding_box()
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            page.mouse.down()
            page.mouse.move(box["x"] + box["width"] / 2 + 100, box["y"] + box["height"] / 2 + 100)
            page.mouse.up()
            assert frame.evaluate("e => getComputedStyle(e).objectPosition") != before
            assert frame.evaluate("e => e.style.objectPosition") == ""
            assert frame.evaluate("e => e.style.transform") == ""
            page.click("[data-drive-fit]")
            page.wait_for_function("getComputedStyle(document.querySelector('[data-drive-frame]')).objectFit === 'contain'")
            assert page.locator("[data-drive-fact=zoom]").is_hidden()
            assert frame.evaluate("e => e.getAttribute('data-pan-x')") is None
            assert frame.evaluate("e => e.style.objectPosition") == ""
            assert frame.evaluate("e => e.style.transform") == ""
        finally:
            browser.close()


@pytest.mark.skipif(not browser_tests_enabled(),
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
@pytest.mark.parametrize("viewport", [(2000, 1200), (1200, 2000)])
def test_zoom_cycles_and_always_reports_crop(base_url, viewport):
    """D-363 §5: 맞춤 → 1.2× → 1.4× → 가득 → 전체화면 → 맞춤. 1.0× 을 넘으면 잘림을 늘 보인다.

    어느 배율에서도 스틱과 페달은 화면 안에 손가락 크기로 남는다(세로 전체화면 포함).
    """
    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.set_default_timeout(10_000)
        try:
            _enter_drive(page, base_url)
            page.wait_for_function("document.querySelector('[data-drive-frame]').naturalWidth > 0")
            seen, boxes = [], []
            for step in range(6):
                label = page.inner_text("[data-drive-zoom]")
                crop = page.locator("[data-drive-fact=zoom]:not([hidden])")
                seen.append((label, crop.inner_text() if crop.count() else ""))
                boxes.append((label, page.evaluate(CONTROL_BOXES)))
                if step < 5:
                    _click_tool(page, "[data-drive-zoom]")
                    page.wait_for_timeout(200)
            stored_zoom = page.evaluate("JSON.parse(localStorage.getItem('rosy.pilot.input')).zoom")
        finally:
            browser.close()
    for label, m in boxes:
        for name in ("stick", "pedal"):
            r = m[name]
            assert r["w"] > 100, (viewport, label, name, r)
            assert r["x"] >= 0 and r["y"] >= 0 and r["x"] + r["w"] <= m["vw"] + 1 \
                and r["y"] + r["h"] <= m["vh"] + 1, (viewport, label, name, r)
    assert seen[0] == ("확대 맞춤", "")
    assert seen[-1][0] == "확대 맞춤", seen                      # 한 바퀴 돌면 맞춤
    assert all("잘림" in crop for label, crop in seen[1:5]), seen
    assert seen[4][0] == "전체화면", seen
    assert stored_zoom == 1
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(),
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_auto_intent_strip_shows_target_and_core_steer(tablet_page):
    """D-364 §6: 진행을 누르는 동안 영상 아래에 겨누는 점과 CORE 의 실제 조향 방향."""
    import json
    import urllib.request
    base_url, page, errors = tablet_page

    def script(status):
        req = urllib.request.Request(base_url + "/__test__/line-follow", data=json.dumps(status).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req).read()

    _enter_drive(page, base_url)
    page.wait_for_selector("[data-drive-frame][src]", timeout=10_000)
    script({"state": "TRACKING", "error": 0.4, "confidence": 0.9, "linear": 0.03,
            "angular": -0.32, "reason": "tracking"})
    page.click("[data-drive-auto]")
    box = page.locator("[data-drive-go]").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.wait_for_selector("[data-drive-intent]:not([hidden])", timeout=5_000)
    page.wait_for_function("document.querySelector('[data-intent-steer]').textContent.includes('▶')")
    got = page.evaluate("""(() => {
      const r = (s) => document.querySelector(s).getBoundingClientRect();
      const track = r('[data-intent-track]'), dot = r('[data-intent-target]'), view = r('[data-drive-view]');
      const strip = r('[data-drive-intent]'), img = document.querySelector('[data-drive-frame]');
      const fb = img.getBoundingClientRect(), k = Math.min(fb.width / img.naturalWidth, fb.height / img.naturalHeight);
      const picL = fb.left + (fb.width - img.naturalWidth * k) / 2, picR = picL + img.naturalWidth * k;
      return {steer: document.querySelector('[data-intent-steer]').textContent,
              state: document.querySelector('[data-drive-intent]').dataset.state,
              at: (dot.left + dot.width / 2 - track.left) / track.width,
              inside: strip.left >= Math.max(view.left, picL) - 1 && strip.right <= Math.min(view.right, picR) + 1 && strip.bottom <= view.bottom + 1};
    })()""")
    page.screenshot(path=str(Path(os.environ.get("ROSY_SHOT_DIR", "X:/DevTemp")) / "pilot-intent-tracking.png"))
    assert got["steer"] == "오른쪽 18°/s ▶" and got["state"] == "tracking"
    assert abs(got["at"] - 0.70) < 0.03 and got["inside"], got
    script({"state": "HOLD", "error": None, "linear": 0.0, "angular": 0.0, "reason": "obstacle_ahead"})
    page.wait_for_function("document.querySelector('[data-drive-intent]').dataset.state === 'hold'")
    assert page.inner_text("[data-intent-steer]") == "멈춤"
    page.mouse.up()
    page.wait_for_selector("[data-drive-intent][hidden]", state="attached", timeout=5_000)
    assert errors == [], errors


def _arm_auto(page, base_url):
    """주행 진입 → 차선 추종 흉내(TRACKING) → 차선 자동 켜기. 모드 기록을 비운다."""
    import json
    import urllib.request
    _enter_drive(page, base_url)
    req = urllib.request.Request(
        base_url + "/__test__/line-follow",
        data=json.dumps({"state": "TRACKING", "error": 0.1, "confidence": 0.9, "linear": 0.03,
                         "angular": 0.0, "reason": "tracking"}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    urllib.request.urlopen(req).read()
    page.click("[data-drive-auto]")
    page.wait_for_selector("[data-drive-go]", state="visible")
    dev_server.LINE_FOLLOW_MODE_LOG.clear()


def _wait_for_modes(page, *expected):
    for _ in range(50):
        if dev_server.LINE_FOLLOW_MODE_LOG[-len(expected):] == list(expected):
            return
        page.wait_for_timeout(100)
    raise AssertionError(f"line-follow mode log {dev_server.LINE_FOLLOW_MODE_LOG}, expected tail {expected}")


GO_ACTIVE = "document.querySelector('[data-drive-go]').classList.contains('active')"


@pytest.mark.skipif(not browser_tests_enabled(),
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_go_releases_on_cancel_and_leave(tablet_page):
    """D-344: 진행은 누르는 동안만 — 손가락이 버튼을 벗어나거나 시스템이 터치를 취소하면 CORE 에 OFF."""
    base_url, page, errors = tablet_page
    _arm_auto(page, base_url)
    go = page.locator("[data-drive-go]").bounding_box()
    stick = page.locator("[data-drive-stick]").bounding_box()

    # 벗어남(pointerleave)
    page.mouse.move(go["x"] + go["width"] / 2, go["y"] + go["height"] / 2)
    page.mouse.down()
    page.wait_for_function(GO_ACTIVE)
    page.mouse.move(stick["x"] - 40, stick["y"] - 40)
    _wait_for_modes(page, "CAMERA_LINE", "OFF")
    page.mouse.up()
    page.wait_for_function(f"!({GO_ACTIVE})")
    page.wait_for_timeout(300)

    # 취소(pointercancel)
    dev_server.LINE_FOLLOW_MODE_LOG.clear()
    page.mouse.move(go["x"] + go["width"] / 2, go["y"] + go["height"] / 2)
    page.mouse.down()
    page.wait_for_function(GO_ACTIVE)
    page.dispatch_event("[data-drive-go]", "pointercancel")
    _wait_for_modes(page, "CAMERA_LINE", "OFF")
    page.wait_for_function(f"!({GO_ACTIVE})")
    page.mouse.up()
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(),
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_stick_takes_over_auto(tablet_page):
    """자동 진행 중 스틱을 잡으면 자동이 즉시 풀린다(CORE 에 PUT mode OFF) — 손이 우선이다."""
    base_url, page, errors = tablet_page
    _arm_auto(page, base_url)
    page.dispatch_event("[data-drive-go]", "pointerdown")        # 진행을 누른 채(실제 포인터는 스틱에)
    page.wait_for_function(GO_ACTIVE)
    stick = page.locator("[data-drive-stick]").bounding_box()
    page.mouse.move(stick["x"] + stick["width"] / 2, stick["y"] + stick["height"] / 2)
    page.mouse.down()
    _wait_for_modes(page, "CAMERA_LINE", "OFF")
    page.wait_for_function(f"!({GO_ACTIVE})")
    page.mouse.up()
    assert page.inner_text("[data-drive-motion]") == "대기"
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(),
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
@pytest.mark.parametrize("width,height", [(390, 844), (320, 568)])
def test_turn_cue_follows_manual_mode_on_phone(tablet_page, width, height):
    base_url, page, errors = tablet_page
    page.set_viewport_size({"width": width, "height": height})
    _arm_auto(page, base_url)
    robot = page.locator('ui-topbar [data-goto="/console"]').bounding_box()
    stop = page.locator('ui-topbar [data-estop]').bounding_box()
    assert robot and stop and robot["x"] + robot["width"] <= stop["x"]
    if page.locator("ui-topbar ui-brand").is_visible():
        brand = page.locator("ui-topbar ui-brand").bounding_box()
        assert brand["x"] + brand["width"] <= robot["x"]
    assert stop["x"] + stop["width"] <= width
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if width == 320:
        go = page.locator("[data-drive-go]").bounding_box()
        assert go and go["y"] + go["height"] <= height
    assert not page.locator("[data-drive-scroll-cue]").is_visible()
    if output := os.environ.get("ROSY_SHOT_DIR"):
        Path(output).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(output) / f"pilot-turn-cue-auto-{width}x{height}.png"))
    page.click("[data-drive-manual]")
    page.wait_for_selector("[data-drive-pivots]", state="visible")
    assert page.locator("[data-drive-scroll-cue]").is_visible()
    if output:
        page.screenshot(path=str(Path(output) / f"pilot-turn-cue-manual-{width}x{height}.png"))
    page.locator('[data-drive-pivot="left"]').scroll_into_view_if_needed()
    pivot = page.locator('[data-drive-pivot="left"]').bounding_box()
    assert pivot and pivot["y"] >= page.locator("ui-topbar").bounding_box()["height"]
    assert pivot["y"] + pivot["height"] <= height + 1
    pivot_widths = page.evaluate("""() => [...document.querySelectorAll('[data-drive-pivots] ui-button')]
      .map(button => [button.clientWidth, button.scrollWidth])""")
    assert all(scroll <= client + 1 for client, scroll in pivot_widths), pivot_widths
    assert abs(pivot_widths[0][0] - pivot_widths[1][0]) <= 1, pivot_widths
    page.locator('[data-drive-pivot="right"]').scroll_into_view_if_needed()
    right = page.locator('[data-drive-pivot="right"]').bounding_box()
    assert right and right["y"] >= page.locator("ui-topbar").bounding_box()["height"]
    assert right["y"] + right["height"] <= height + 1
    if output:
        page.screenshot(path=str(Path(output) / f"pilot-turn-controls-{width}x{height}.png"))
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(),
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_short_phone_hud_uses_existing_tools_panel(tablet_page):
    base_url, page, errors = tablet_page
    _enter_drive(page, base_url)
    page.set_viewport_size({"width": 320, "height": 568})
    page.wait_for_function("document.querySelectorAll('[data-drive-tools-panel] details.pilot-models').length === 2")
    assert page.locator("[data-drive-hud] details.pilot-models").count() == 0
    assert page.locator("[data-drive-tools-panel] [data-drive-fit]").count() == 1
    assert page.locator("[data-drive-tools-panel] [data-drive-fill]").count() == 1
    hud = page.locator("[data-drive-hud]")
    assert hud.evaluate("node => node.scrollHeight <= node.clientHeight + 1")
    page.locator("[data-drive-tools]").click()
    panel = page.locator("[data-drive-tools-panel]")
    assert panel.is_visible()
    bounds = panel.bounding_box()
    assert bounds["y"] >= 0 and bounds["y"] + bounds["height"] <= 568
    if output := os.environ.get("ROSY_SHOT_DIR"):
        Path(output).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(output) / "pilot-tools-320x568.png"))
    panel.locator("details.pilot-models summary").first.click()
    assert panel.locator("details.pilot-models").first.get_attribute("open") is not None
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_function("document.querySelectorAll('[data-drive-hud] details.pilot-models').length === 2")
    assert panel.is_hidden()
    assert page.locator("[data-drive-tools]").get_attribute("aria-expanded") == "false"
    assert page.locator("[data-drive-hud] [data-drive-fit]").count() == 1
    assert page.locator("[data-drive-hud] [data-drive-fill]").count() == 1
    assert page.locator("[data-drive-hud] details.pilot-models[open]").count() == 0
    page.set_viewport_size({"width": 320, "height": 568})
    page.wait_for_function("document.querySelectorAll('[data-drive-tools-panel] details.pilot-models').length === 2")
    page.locator("[data-drive-tools]").click()
    panel.get_by_text("닫기", exact=True).scroll_into_view_if_needed()
    panel.get_by_text("닫기", exact=True).click()
    assert panel.is_hidden()
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(),
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_reenter_resets_auto_mode(tablet_page):
    """주행 화면은 같은 section 에 다시 마운트된다 — 나갔다 들어오면 수동(페달)으로 시작한다."""
    base_url, page, errors = tablet_page
    _arm_auto(page, base_url)
    assert page.get_attribute("[data-drive-auto]", "aria-pressed") == "true"
    page.click("[data-drive-exit]")
    page.wait_for_selector("[data-drive-enter]")
    page.click("[data-drive-enter]")
    page.wait_for_selector("[data-drive-stick]")
    state = page.evaluate("""(() => {
      const drive = document.querySelector('[data-screen=drive]');
      return {auto: drive.dataset.autoMode, pressed: document.querySelector('[data-drive-auto]').getAttribute('aria-pressed')};
    })()""")
    assert state == {"auto": "off", "pressed": "false"}, state
    assert page.locator("[data-drive-pedal=forward]").is_visible()
    assert not page.locator("[data-drive-go]").is_visible()
    assert errors == [], errors


def _calibrating(owner_id: str) -> dict:
    return {"kind": "CALIBRATING", "session_id": "cal-1", "calibration_kind": "drive",
            "label": "주행 보정", "owner": {"id": owner_id, "role": "operator", "label": "보정 노트북"},
            "started_at": "2026-10-01T09:00:00+00:00", "remaining_s": 27.0}


@pytest.mark.skipif(not browser_tests_enabled(),
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_calibration_banner_locks_drive_for_other_tokens_and_keeps_estop(tablet_page):
    """D-321 부록: 보정 중이면 띠가 뜨고, 남의 보정이면 주행 조작이 사유와 함께 잠긴다."""
    base_url, page, errors = tablet_page
    shots = Path(os.environ.get("ROSY_SHOT_DIR", "X:/DevTemp/calibration-mode"))
    shots.mkdir(parents=True, exist_ok=True)
    log = f"{base_url}/__test__/teleop"
    _enter_drive(page, base_url)
    try:
        page.request.post(f"{base_url}/__test__/activity", data=_calibrating("someone-else"))
        page.wait_for_selector("[data-drive-calibration]:not([hidden])")
        assert page.inner_text("[data-drive-calibration-title]") == "보정 중 — 주행 보정"
        reason = page.inner_text("[data-drive-calibration-reason]")
        assert "보정 노트북" in reason and "비상 정지" in reason
        assert page.locator("[data-drive-fact=activity]").is_visible()
        page.wait_for_selector("[data-drive-controls][data-locked]")
        assert page.evaluate("""[...document.querySelectorAll('[data-drive-controls] ui-button')]
                                .every((b) => b.disabled)""")
        estop = page.locator("ui-topbar ui-button[data-estop]")
        assert estop.is_visible() and not estop.evaluate("(b) => b.disabled")
        page.screenshot(path=str(shots / "pilot-calibration-locked.png"))

        # 잠긴 동안에는 스틱을 밀어도 teleop 을 한 번도 보내지 않는다.
        before = len(page.request.get(log).json())
        box = page.locator("[data-drive-stick]").bounding_box()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.mouse.down()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 5, steps=3)
        page.keyboard.down("ArrowUp")
        page.wait_for_timeout(600)
        page.keyboard.up("ArrowUp")
        page.mouse.up()
        assert len(page.request.get(log).json()) == before, "잠긴 조작부가 명령을 보냈다"

        # 이 기기(whoami id dev-1)가 보정 주인이면 띠는 그대로, 조작은 풀린다.
        page.request.post(f"{base_url}/__test__/activity", data=_calibrating("dev-1"))
        page.wait_for_selector("[data-drive-controls]:not([data-locked])")
        assert page.locator("[data-drive-calibration]").is_visible()
        assert "이 기기" in page.inner_text("[data-drive-calibration-reason]")
        page.screenshot(path=str(shots / "pilot-calibration-owner.png"))

        page.request.post(f"{base_url}/__test__/activity", data="null",
                          headers={"Content-Type": "application/json"})
        page.wait_for_selector("[data-drive-calibration]", state="hidden")
        assert not page.locator("[data-drive-fact=activity]").is_visible()
    finally:
        dev_server.STATE["activity"] = None
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(),
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_leaving_while_locked_never_posts_idle_over_the_owner(tablet_page):
    """D-321 부록: 남의 보정으로 잠긴 화면이 나가도 /mode IDLE 로 주인의 주행을 끊지 않는다."""
    base_url, page, errors = tablet_page
    _enter_drive(page, base_url)
    try:
        page.request.post(f"{base_url}/__test__/activity", data=_calibrating("someone-else"))
        page.wait_for_selector("[data-drive-controls][data-locked]")
        before = len(page.request.get(f"{base_url}/__test__/mode-log").json())
        page.click("[data-drive-exit]")
        page.wait_for_timeout(500)
        assert page.request.get(f"{base_url}/__test__/mode-log").json()[before:] == []
    finally:
        dev_server.STATE["activity"] = None
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(),
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_owner_leaving_still_returns_the_mode_to_idle(tablet_page):
    base_url, page, errors = tablet_page
    _enter_drive(page, base_url)
    try:
        page.request.post(f"{base_url}/__test__/activity", data=_calibrating("dev-1"))
        page.wait_for_selector("[data-drive-calibration]:not([hidden])")
        page.wait_for_selector("[data-drive-controls]:not([data-locked])")
        before = len(page.request.get(f"{base_url}/__test__/mode-log").json())
        page.click("[data-drive-exit]")
        page.wait_for_timeout(500)
        assert page.request.get(f"{base_url}/__test__/mode-log").json()[before:] == ["IDLE"]
    finally:
        dev_server.STATE["activity"] = None
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(),
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_owner_sees_checking_while_whoami_retries_then_gets_control(tablet_page):
    """whoami 가 실패하는 동안 '보정 확인 중'으로 잠그고, 재시도가 성공하면 주인에게 조작을 돌려준다."""
    base_url, page, errors = tablet_page
    page.request.post(f"{base_url}/__test__/activity", data=_calibrating("dev-1"))
    try:
        page.goto(f"{base_url}/pilot")
        page.wait_for_selector("form[data-pilot-token-form] ui-field input")
        page.fill("form[data-pilot-token-form] ui-field input", "devtoken")
        page.click("form[data-pilot-token-form] ui-button")
        page.wait_for_selector("[data-drive-enter]")
        page.request.post(f"{base_url}/__test__/whoami-fail", data={"count": 2})
        page.click("[data-drive-enter]")
        page.wait_for_function(
            "document.querySelector('[data-drive-calibration-reason]')?.textContent.startsWith('보정 확인 중')")
        assert page.locator("[data-drive-controls][data-locked]").count() == 1
        page.wait_for_selector("[data-drive-controls]:not([data-locked])", timeout=30_000)
        assert "이 기기" in page.inner_text("[data-drive-calibration-reason]")
    finally:
        dev_server.STATE["activity"] = None
        dev_server.WHOAMI_FAILURES["remaining"] = 0
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(),
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_exit_after_a_failed_engage_posts_no_idle(tablet_page):
    """modeHeld 고정: MANUAL 을 잡지 못한 화면은 나가면서 IDLE 을 보내지 않는다(잠금이 없어도)."""
    base_url, page, errors = tablet_page
    page.goto(f"{base_url}/pilot")
    page.wait_for_selector("form[data-pilot-token-form] ui-field input")
    page.fill("form[data-pilot-token-form] ui-field input", "devtoken")
    page.click("form[data-pilot-token-form] ui-button")
    page.wait_for_selector("[data-drive-enter]")
    page.request.post(f"{base_url}/__test__/mode-refuse", data={"count": 1})
    try:
        before = len(page.request.get(f"{base_url}/__test__/mode-log").json())
        page.click("[data-drive-enter]")
        page.wait_for_selector("[data-drive-blocked]:not([hidden])")
        page.click("[data-drive-exit]")
        page.wait_for_timeout(500)
        assert page.request.get(f"{base_url}/__test__/mode-log").json()[before:] == []
    finally:
        dev_server.MODE_REFUSALS["remaining"] = 0
    assert errors == [], errors


ROBOT_RECORDING_ID = "20261002T101500Z_rosy_dev"
ROBOT_RECORD_STOP = "document.querySelector('[data-robot-record]').textContent.includes('중지')"


def _recordings(page, base_url, **body):
    if body:
        page.request.post(f"{base_url}/__test__/recordings", data=body)
    return page.request.get(f"{base_url}/__test__/recordings").json()


def _eventually(probe, timeout_s=10.0):
    """Polls probe() until it is truthy; returns its value (no fixed sleeps in the test body)."""
    deadline = time.monotonic() + timeout_s
    while True:
        value = probe()
        if value or time.monotonic() > deadline:
            return value
        time.sleep(0.1)


def _settled_polls(page, base_url):
    """True once GET /recordings/active stops arriving: the recording view was disposed."""
    last = [-1]

    def probe():
        polls = _recordings(page, base_url)["polls"]
        if polls == last[0]:
            return True
        last[0] = polls
        time.sleep(1.3)         # one poll period (1 s) plus slack between the two reads
        return False
    return _eventually(probe, 15.0)


def _open_sheet(page):
    _click_tool(page, "[data-recordings-open]")
    row = page.locator(f"[data-recordings-sheet] [data-recording-id='{ROBOT_RECORDING_ID}']")
    row.wait_for()
    return row


def _enter_recording_drive(page, base_url, **scenario):
    _recordings(page, base_url, reset=True, **scenario)
    _enter_drive(page, base_url)
    page.wait_for_function("!document.querySelector('[data-robot-record]').disabled")


@pytest.mark.skipif(not browser_tests_enabled(),
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_narrow_recordings_sheet_scrolls_many_rows_and_keeps_actions_visible(base_url):
    """22rem 미만: 녹화본이 많으면 목록만 스크롤하고 하단 행동은 스크롤 없이 보인다."""
    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 320, "height": 568})
        page.set_default_timeout(10_000)
        try:
            _enter_recording_drive(page, base_url, many=True)
            _open_sheet(page)
            rows = page.locator("[data-recordings-sheet] [data-recording-id]")
            assert rows.count() == 12
            assert page.evaluate("""(() => { const l = document.querySelector('[data-recordings-list]');
              return l.scrollHeight > l.clientHeight; })()"""), "많은 녹화본은 목록이 스크롤한다"
            for selector in ("[data-recordings-close]", "[data-recordings-refresh]"):
                box = page.locator(selector).bounding_box()
                assert box and box["y"] >= 0 and box["y"] + box["height"] <= 568, selector
            last = rows.last
            last.scroll_into_view_if_needed()
            assert last.evaluate("""row => { const b = row.getBoundingClientRect();
              return document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2)?.closest('[data-recording-id]') === row; }""")
        finally:
            _recordings(page, base_url, reset=True)
            browser.close()


@pytest.mark.skipif(not browser_tests_enabled(),
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
@pytest.mark.parametrize("viewport", [(2000, 1200), (1200, 2000), (390, 844), (320, 568)])
def test_robot_recording_toggle_and_sheet(base_url, viewport):
    """D-411 A: 로봇 녹화 토글(화면 녹화와 따로)과 녹화본 시트 — 받기는 CORE 의 차단 사유를 따른다."""
    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]}, accept_downloads=True)
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.set_default_timeout(10_000)
        try:
            _enter_recording_drive(page, base_url)
            assert page.locator("[data-evidence-record]").inner_text().strip() == "화면 녹화"
            assert page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") <= 0
            _click_tool(page, "[data-robot-record]")
            page.wait_for_function(ROBOT_RECORD_STOP)
            page.wait_for_selector("[data-drive-fact=recording]:not([hidden])")
            assert "녹화 0:01 / 10:00" in page.inner_text("[data-drive-fact=recording]")
            assert _recordings(page, base_url)["log"] == ["start"]
            row = _open_sheet(page)
            stop = page.locator("ui-topbar [data-estop]").bounding_box()
            assert stop and 0 <= stop["y"] and stop["y"] + stop["height"] <= viewport[1], "시트가 열려도 비상 정지는 화면 안"
            if output := os.environ.get("ROSY_SHOT_DIR"):
                shots = Path(output)
                shots.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(shots / f"pilot-recording-sheet-{viewport[0]}x{viewport[1]}.png"))
            assert page.evaluate("!!document.activeElement.closest('[data-recordings-sheet]')"), "열면 시트로 초점"
            box = page.evaluate("""(() => { const s = document.querySelector('[data-recordings-sheet]').getBoundingClientRect();
              const h = document.querySelector('[data-drive-hud]').getBoundingClientRect();
              return {top: s.top, bottom: s.bottom, left: s.left, right: s.right, hud: h.bottom, vh: innerHeight}; })()""")
            assert box["top"] >= box["hud"], f"시트가 HUD 를 덮는다 {box}"
            assert box["left"] >= 0 and box["right"] <= viewport[0] + 1 and box["bottom"] <= box["vh"] + 1, box
            assert page.evaluate("""(() => {
              const sheet = document.querySelector('[data-recordings-sheet]');
              const box = sheet.getBoundingClientRect();
              return document.elementFromPoint(box.left + box.width / 2, box.bottom - 20)
                ?.closest('[data-recordings-sheet]') === sheet;
            })()"""), "시트 하단이 조작부 뒤에 가려지지 않아야 한다"
            close = page.locator("[data-recordings-close]")
            close_box = close.bounding_box()
            assert close_box and close_box["y"] >= 0 and close_box["y"] + close_box["height"] <= viewport[1], "닫기는 스크롤 없이 보여야 한다"
            row_box = row.bounding_box()
            refresh_box = page.locator("[data-recordings-refresh]").bounding_box()
            assert row_box and refresh_box and row_box["y"] + row_box["height"] <= refresh_box["y"] + 1, "녹화본 행이 하단 행동에 가려지지 않아야 한다"
            assert close.evaluate("""button => {
              const box = button.getBoundingClientRect();
              return document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2)
                ?.closest('[data-recordings-sheet]') === button.closest('[data-recordings-sheet]');
            }"""), "시트 닫기가 조작부에 가려지지 않아야 한다"
            refresh_width = refresh_box["width"]
            assert abs(refresh_width - close.bounding_box()["width"]) <= 1, "같은 행의 시트 행동은 같은 너비"
            assert row.locator("[data-recording-fetch]").is_disabled()          # 녹화 중에는 받지 않는다
            assert "녹화 중에는" in page.inner_text("[data-recordings-notice]")
            assert page.get_attribute("[data-recordings-notice]", "aria-live") == "polite"
            _click_tool(page, "[data-robot-record]")
            page.wait_for_function("document.querySelector('[data-robot-record]').textContent.trim() === '로봇 녹화'")
            row = _open_sheet(page)
            _recordings(page, base_url, blocker="ROBOT_MOVING")
            page.click("[data-recordings-refresh]")
            page.wait_for_function("document.querySelector('[data-recordings-notice]').textContent.includes('멈춘 뒤')")
            assert row.locator("[data-recording-fetch]").is_disabled()
            _recordings(page, base_url, blocker=None)
            # no click: the open sheet refreshes itself every few seconds
            page.wait_for_function("!document.querySelector('[data-recording-fetch]').disabled")
            with page.expect_download() as download:
                row.locator("[data-recording-fetch]").click()
            assert download.value.suggested_filename == f"{ROBOT_RECORDING_ID}.tar"
            row.locator("[data-recording-status]").wait_for()
            assert "받음" in row.locator("[data-recording-status]").inner_text()
            assert _eventually(lambda: _recordings(page, base_url)["log"] == ["start", "stop", "archive", "archive_done"])
            page.keyboard.press("Escape")
            assert page.locator("[data-recordings-sheet]").count() == 0
            assert page.evaluate("document.activeElement?.hasAttribute('data-drive-tools')")
        finally:
            browser.close()
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(),
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_robot_recording_shows_starting_until_the_writer_records(tablet_page):
    """'녹화 중'은 로봇이 실제로 기록할 때부터다. 준비 중에는 타이머 없이 멈출 수만 있다."""
    base_url, page, errors = tablet_page
    _enter_recording_drive(page, base_url, starting=True)
    toggle = "[data-robot-record]"
    _click_tool(page, toggle)
    page.wait_for_function(f"document.querySelector('{toggle}').dataset.state === 'starting'")
    assert page.inner_text(toggle).strip() == "녹화 준비 중…"
    assert page.get_attribute(toggle, "aria-pressed") == "true"
    assert page.get_attribute(toggle, "aria-label") == "로봇 녹화 준비 중, 누르면 취소"
    assert not page.locator(toggle).is_disabled()
    # 켜진 버튼을 흐리게(opacity) 하지 않고, 표면이 공용 버튼을 다시 칠하지도 않는다(D-411):
    # 준비 중은 라벨·눌림·HUD 칩이 말한다.
    opacity = page.evaluate(f"getComputedStyle(document.querySelector('{toggle}')).opacity")
    assert opacity == "1", opacity
    assert page.get_attribute(toggle, "kind") is not None
    fact = page.inner_text("[data-drive-fact=recording]")
    assert "아직 기록하지 않습니다" in fact and "0:0" not in fact
    _click_tool(page, toggle)                                     # 준비 중 멈춤은 깨끗한 정지
    page.wait_for_function(f"document.querySelector('{toggle}').textContent.trim() === '로봇 녹화'")
    assert _recordings(page, base_url)["log"] == ["start", "stop"]
    _click_tool(page, toggle)
    page.wait_for_function(f"document.querySelector('{toggle}').dataset.state === 'starting'")
    _recordings(page, base_url, ready=True)                # 기록기가 첫 파일을 열었다
    page.wait_for_function(ROBOT_RECORD_STOP)
    page.wait_for_function("document.querySelector('[data-drive-fact=recording]').textContent.includes('녹화 0:')")
    assert page.get_attribute(toggle, "aria-label") == "로봇 녹화 중지"
    _click_tool(page, toggle)
    page.wait_for_function(f"document.querySelector('{toggle}').dataset.state === 'idle'")
    _click_tool(page, toggle)
    page.wait_for_function(f"document.querySelector('{toggle}').dataset.state === 'starting'")
    page.click("[data-drive-exit]")                        # 준비 중에 나가도 이 기기 녹화는 멈춘다
    assert _eventually(lambda: _recordings(page, base_url)["log"] == ["start", "stop", "start", "stop",
                                                                      "start", "stop"])
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(),
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_leaving_drive_stops_the_robot_recording_this_device_started(tablet_page):
    base_url, page, errors = tablet_page
    _enter_recording_drive(page, base_url)
    _click_tool(page, "[data-robot-record]")
    page.wait_for_function(ROBOT_RECORD_STOP)
    page.click("[data-drive-exit]")
    assert _eventually(lambda: _recordings(page, base_url)["log"] == ["start", "stop"])
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(),
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_robot_recording_continues_past_the_ten_minute_cap_until_stopped(tablet_page):
    """한 파일은 10분 상한을 지키고, 끄지 않은 녹화는 다음 구간으로 잇는다. 끈 뒤에는 잇지 않는다."""
    base_url, page, errors = tablet_page
    _enter_recording_drive(page, base_url)
    toggle = "[data-robot-record]"
    _click_tool(page, toggle)
    page.wait_for_function(ROBOT_RECORD_STOP)
    _recordings(page, base_url, cap=True)
    assert _eventually(lambda: _recordings(page, base_url)["log"] == ["start", "start"])
    page.wait_for_function(ROBOT_RECORD_STOP)
    page.wait_for_function("document.querySelector('[data-drive-fact=recording]').textContent.includes('2번째')")
    page.wait_for_timeout(6000)                            # 안내가 지나간 뒤에도 구간 번호는 남는다
    assert "2번째 구간" in page.inner_text("[data-drive-fact=recording]")
    _click_tool(page, toggle)
    page.wait_for_function(f"document.querySelector('{toggle}').dataset.state === 'idle'")
    _recordings(page, base_url, cap=True)                  # 끈 뒤의 상한 표시는 다시 켜지 않는다
    page.wait_for_timeout(2500)
    assert _recordings(page, base_url)["log"] == ["start", "start", "stop"]
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(),
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_another_devices_recording_is_neither_stopped_nor_stoppable_here(tablet_page):
    base_url, page, errors = tablet_page
    _recordings(page, base_url, reset=True, foreign=True)
    _enter_drive(page, base_url)
    page.wait_for_function(ROBOT_RECORD_STOP)
    _click_tool(page, "[data-robot-record]")
    page.wait_for_function("document.querySelector('[data-drive-fact=recording]').textContent.includes('다른 기기가 시작한')")
    page.click("[data-drive-exit]")
    assert _settled_polls(page, base_url)
    assert _recordings(page, base_url)["log"] == []
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(),
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_a_viewer_is_told_it_needs_an_operator(tablet_page):
    base_url, page, errors = tablet_page
    _enter_recording_drive(page, base_url, role="viewer")
    _click_tool(page, "[data-robot-record]")
    page.wait_for_function("document.querySelector('[data-drive-fact=recording]').textContent.includes('운전자(Operator)')")
    row = _open_sheet(page)
    row.locator("[data-recording-fetch]").click()
    page.wait_for_function("document.querySelector('[data-recording-status]')?.textContent.includes('운전자(Operator)')")
    assert _recordings(page, base_url)["log"] == []
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(),
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
@pytest.mark.parametrize("mode, text", [("short", "끊겼습니다"), ("conflict", "멈춘 뒤에")])
def test_a_cut_or_refused_download_saves_nothing(tablet_page, mode, text):
    base_url, page, errors = tablet_page
    _enter_recording_drive(page, base_url, archive=mode)
    downloads = []
    page.on("download", lambda item: downloads.append(item))
    row = _open_sheet(page)
    row.locator("[data-recording-fetch]").click()
    page.wait_for_function(f"document.querySelector('[data-recording-status]')?.textContent.includes('{text}')")
    assert downloads == []
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(),
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
@pytest.mark.parametrize("how", ["cancel", "exit"])
def test_an_in_flight_download_is_aborted_by_cancel_or_leaving(tablet_page, how):
    """받는 중에 취소하거나 화면을 나가면 요청을 끊는다 — CORE 가 fetched 로 표시하지 않게."""
    base_url, page, errors = tablet_page
    _enter_recording_drive(page, base_url, archive="slow")
    try:
        row = _open_sheet(page)
        row.locator("[data-recording-fetch]").click()
        row.locator("[data-recording-cancel]").wait_for()
        assert _eventually(lambda: "archive" in _recordings(page, base_url)["log"])
        page.click("[data-recording-cancel]" if how == "cancel" else "[data-drive-exit]")
        assert _eventually(lambda: "archive_aborted" in _recordings(page, base_url)["log"]), \
            _recordings(page, base_url)
        if how == "cancel":
            page.wait_for_function("document.querySelector('[data-recording-status]')?.textContent.includes('취소')")
    finally:
        _recordings(page, base_url, release=True)
    assert "archive_done" not in _recordings(page, base_url)["log"]
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(),
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_a_large_recording_points_to_the_pc_tool(tablet_page):
    base_url, page, errors = tablet_page
    _enter_recording_drive(page, base_url, big=True)
    row = _open_sheet(page)
    button = row.locator("[data-recording-fetch]")
    assert button.is_disabled()
    assert "rosy_ml fetch" in button.inner_text()
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(),
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_recordings_sheet_refresh_keeps_keyboard_focus(tablet_page):
    """3 s 새로 읽기가 같은 목록을 가져오면 행을 다시 만들지 않는다 — 초점·live region 그대로."""
    base_url, page, errors = tablet_page
    _enter_recording_drive(page, base_url)
    row = _open_sheet(page)
    page.wait_for_function("!document.querySelector('[data-recording-fetch]').disabled")
    row.locator("[data-recording-fetch]").focus()
    page.evaluate("window.__focused = document.activeElement")
    lists = _recordings(page, base_url)["lists"]
    assert _eventually(lambda: _recordings(page, base_url)["lists"] >= lists + 2)
    assert page.evaluate("document.activeElement === window.__focused && window.__focused.isConnected")
    assert errors == [], errors


# --- D-411 B: rosy.controls/1 — 기기가 알리는 조작부로 화면을 조립한다 ---------------------------

@pytest.mark.skipif(not browser_tests_enabled(), reason="ROSY_RUN_BROWSER_TESTS=1")
def test_unknown_control_kind_is_shown_not_fatal(tablet_page):
    base_url, page, errors = tablet_page
    page.request.post(f"{base_url}/__test__/controls", data={"extra": {"id": "laser", "kind": "laser", "label": "레이저"}})
    _enter_drive(page, base_url)
    assert page.locator("[data-control-unsupported]").inner_text().strip() == "지원하지 않는 조작부 · 레이저"
    assert page.locator("[data-drive-auto]").count() == 1          # base_velocity autonomy ["line"]
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(), reason="ROSY_RUN_BROWSER_TESTS=1")
def test_old_core_without_controls_falls_back_to_the_pinky_profile(tablet_page):
    base_url, page, errors = tablet_page
    page.request.post(f"{base_url}/__test__/controls", data={"omit": True})
    _enter_drive(page, base_url)
    assert page.locator("[data-drive-stage]").count() == 1
    assert page.locator("[data-drive-auto]").count() == 1          # legacy PROFILE autonomy ["line"]
    assert page.locator("[data-control-unsupported]").count() == 0
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(), reason="ROSY_RUN_BROWSER_TESTS=1")
def test_announced_autonomy_decides_the_line_toggle(tablet_page):
    base_url, page, errors = tablet_page
    page.request.post(f"{base_url}/__test__/controls",
                      data={"items": [{**dev_server._BASE_CONTROL, "autonomy": []}]})
    _enter_drive(page, base_url)
    assert page.locator("[data-drive-auto]").count() == 0
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(), reason="ROSY_RUN_BROWSER_TESTS=1")
def test_empty_controls_are_not_an_old_server(tablet_page):
    base_url, page, errors = tablet_page
    page.request.post(f"{base_url}/__test__/controls", data={"items": []})
    page.goto(f"{base_url}/pilot")
    page.fill("form[data-pilot-token-form] ui-field input", "devtoken")
    page.click("form[data-pilot-token-form] ui-button")
    page.click("[data-drive-enter]")
    page.wait_for_selector("text=이 기기는 지금 주행 조작부를 알리지 않습니다")
    assert page.locator("[data-drive-stick]").count() == 0
    page.click("text=접속 화면으로")
    page.wait_for_selector("[data-drive-enter]")
    assert errors == [], errors


# The fake follows the real SIM runtime (pilot_sim_runtime.snapshot/submit, command_owner):
# while a goal runs /state says ready:false, owner_state "active", active_goal; a goal needs a
# state_sequence served by a ready readback; a second goal while one runs is refused.
_ARM_HARNESS = """async (opts) => {
  const {mountArm} = await import('/pilot/assets/screens/arm.js');
  Object.assign(window, {goals: [], grips: [], gripperState: null, cancels: 0, terminal: 'RUNNING', rejections: [], seq: 0, served: new Set(),
    pos: {joint1: 0, joint2: 0, gripper_joint_1: 0}, seatLost: false, forgetGoals: false,
    mismatchOnce: Boolean(opts.mismatchOnce), started: {}, finished: {}});
  const TERMINAL = ['SUCCEEDED', 'REJECTED', 'CANCELED', 'UNKNOWN_HOLD'];
  const goalState = (id) => window.finished[id] ?? (opts.settleMs ? (performance.now() - window.started[id] >= opts.settleMs ? 'SUCCEEDED' : 'RUNNING')
                                          : window.terminal);
  const current = () => window.goals.at(-1)?.request_id;
  const running = () => Boolean(current()) && !TERMINAL.includes(goalState(current()));
  const refuse = (reason) => { window.rejections.push(reason); throw new Error(`409: {"error":{"message":"${reason}"}}`); };
  // opts.gripper: a D-411 C server — the gripper leaves joint_jog and has its own control.
  const gripper = {id: 'gripper', kind: 'gripper', label: '그리퍼', joint: 'gripper_joint_1', closed: 0, open: 1,
    unit: 'rad', presets: {open: 1, half: 0.5, close: 0}, readback: ['position', 'grasp'], max_velocity: 0.5};
  const target = {kind: 'omx_sim', simulation: true, instance_id: 'omx_01', joints: ['joint1', 'joint2'],
    gripper: 'gripper_joint_1', controls: {schema: 'rosy.controls/1', items: [{id: 'arm', kind: 'joint_jog',
    label: '팔', max_step_rad: 0.05, duration_s: 0.4, command: 'bounded_goal',
    joints: [{name: 'joint1', lower: -1, upper: 1}, {name: 'joint2', lower: -1, upper: 1},
             ...(opts.gripper ? [] : [{name: 'gripper_joint_1', lower: -0.01, upper: 0.019}])]},
    ...(opts.gripper ? [gripper] : []), ...(opts.extra || [])]}};
  const gripperBlock = (busy) => ({joint: 'gripper_joint_1', position: window.pos.gripper_joint_1, open: 1, closed: 0,
    state: window.gripperState ?? (busy && window.grips.at(-1)?.request_id === current() ? 'moving'
           : Math.abs(window.pos.gripper_joint_1) <= 0.05 ? 'closed' : 'open')});
  const driver = {request: async (path, options = {}) => {
    if (path === '/pair') return {token: 't'};
    if (path === '/whoami') return {role: 'operator'};
    if (path === '/seat') return {seat_id: 's'};
    if (path.startsWith('/seat/')) { if (window.seatLost && options.method === 'PUT') throw new Error('409: seat expired'); return {seat_id: 's'}; }
    if (path === '/state') {
      if (window.failNextState) { window.failNextState = false; throw new Error('503: {"error":{"message":"busy"}}'); }
      const busy = running(); window.seq += 1;
      if (!busy) window.served.add(window.seq);
      return {ready: !busy, state_sequence: window.seq, owner_state: busy ? 'active' : 'ready', joint_age_ms: 5,
              active_goal: busy ? current() : null, positions: {...window.pos},
              ...(opts.gripper ? {gripper: gripperBlock(busy)} : {})};
    }
    if (path === '/gripper') {
      const body = JSON.parse(options.body);
      if (running()) refuse('goal_active');
      if (!window.served.has(body.state_sequence)) refuse('readback_not_recently_served');
      if (body.position < -0.1 || body.position > 1.1) refuse('gripper_limit');
      window.pos.gripper_joint_1 = body.position; window.grips.push(body); window.goals.push(body);
      window.started[body.request_id] = performance.now();
      return {command_id: body.request_id, state: 'LOCAL_ACCEPTED'};
    }
    if (path === '/goals') {
      const body = JSON.parse(options.body);
      if (running()) refuse('goal_active');
      if (!window.served.has(body.state_sequence)) refuse('readback_not_recently_served');
      if (window.mismatchOnce) { window.mismatchOnce = false; refuse('joint_state_sequence_mismatch'); }
      const range = target.controls.items[0].joints.find((j) => j.name === body.joint);
      const next = window.pos[body.joint] + body.delta_rad;
      if (next < range.lower || next > range.upper) refuse('joint_limit');
      window.pos[body.joint] = next; window.goals.push(body); window.started[body.request_id] = performance.now();
      return {command_id: body.request_id, state: 'LOCAL_ACCEPTED'};
    }
    if (path.endsWith('/cancel')) { window.cancels++; return {state: 'CANCEL_REQUESTED'}; }
    if (path.startsWith('/goals/')) {
      if (window.forgetGoals) throw new Error('404: {"error":{"message":"goal unknown"}}');
      // A receipt settles this goal only; later goals still start RUNNING.
      if (window.settleOnPoll) { window.settleOnPoll = false; window.finished[decodeURIComponent(path.slice(7))] = 'SUCCEEDED'; window.failNextState = true; }
      return {state: goalState(decodeURIComponent(path.slice(7)))};
    }
    return {};
  }};
  const root = document.querySelector('[data-screen="arm"]');
  document.body.dataset.pilotScreen = 'arm';
  document.querySelector('[data-screen="connect"]').hidden = true;
  document.querySelectorAll('[data-estop], [data-goto]').forEach(button => { button.hidden = true; });
  root.hidden = false;
  sessionStorage.setItem(`rosy.pilot.omx-sim.${location.origin}`, 't');
  window.disposeArm = mountArm(root, target, driver);
}"""


def _mount_arm(page, base_url, **opts):
    page.goto(f"{base_url}/pilot")
    page.wait_for_selector("form[data-pilot-token-form]")
    page.evaluate(_ARM_HARNESS, opts)
    page.wait_for_function("document.querySelector('[data-sim-status]').textContent === '조작 가능'")


@pytest.mark.skipif(not browser_tests_enabled(), reason="ROSY_RUN_BROWSER_TESTS=1")
def test_arm_joystick_sends_bounded_goals_one_at_a_time(tablet_page):
    base_url, page, errors = tablet_page
    _mount_arm(page, base_url)
    result = page.evaluate("""async () => {
      const pad = document.querySelector('[data-arm-pad]');
      const box = pad.getBoundingClientRect();
      pad.dispatchEvent(new PointerEvent('pointerdown', {clientX: box.right, clientY: box.top + box.height / 2, pointerId: 1, bubbles: true}));
      await new Promise((r) => setTimeout(r, 300));
      const whileRunning = window.goals.length;
      window.terminal = 'SUCCEEDED';
      await new Promise((r) => setTimeout(r, 1300));
      pad.dispatchEvent(new PointerEvent('pointerup', {pointerId: 1, bubbles: true}));
      const atRelease = window.goals.length;
      await new Promise((r) => setTimeout(r, 1300));
      return {whileRunning, atRelease, after: window.goals.length, cancels: window.cancels, rejections: window.rejections,
              deltas: window.goals.map((g) => g.delta_rad), joints: [...new Set(window.goals.map((g) => g.joint))],
              durations: [...new Set(window.goals.map((g) => g.duration_s))]};
    }""")
    assert result["whileRunning"] == 1
    assert result["atRelease"] >= 2 and result["after"] == result["atRelease"]
    assert all(0 < d <= 0.05 for d in result["deltas"]) and result["joints"] == ["joint1"]
    assert result["durations"] == [0.4]
    assert result["cancels"] == 0 and result["rejections"] == []    # release never cancels (D-411 부록)
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(), reason="ROSY_RUN_BROWSER_TESTS=1")
def test_arm_axes_are_remappable_and_buttons_wait_for_the_goal(tablet_page):
    base_url, page, errors = tablet_page
    _mount_arm(page, base_url, extra=[{"id": "beam", "kind": "beam", "label": "빔"}])
    assert page.locator("[data-control-unsupported]").inner_text().strip() == "지원하지 않는 조작부 · 빔"
    assert page.locator("[data-arm-pad-label=up]").inner_text() == "joint2 +"
    page.select_option("[data-arm-axis=y]", "gripper_joint_1")
    assert page.locator("[data-arm-pad-label=up]").inner_text() == "gripper_joint_1 +"
    page.click("[data-sim-delta='0.02']")
    page.wait_for_function("window.goals.length === 1")
    page.wait_for_function("document.querySelector(\"[data-sim-delta='0.02']\").disabled")
    assert page.locator("[data-sim-cancel]").is_enabled()
    page.evaluate("window.terminal = 'SUCCEEDED'")
    page.wait_for_function("!document.querySelector(\"[data-sim-delta='0.02']\").disabled")
    page.focus("[data-arm-pad]")
    page.keyboard.down("ArrowUp")
    page.wait_for_function("window.goals.length >= 2")
    page.keyboard.up("ArrowUp")
    goal = page.evaluate("window.goals[1]")
    assert goal["joint"] == "gripper_joint_1" and 0 < goal["delta_rad"] <= 0.019
    assert page.evaluate("window.rejections") == []
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(), reason="ROSY_RUN_BROWSER_TESTS=1")
@pytest.mark.parametrize("width,height", [(390, 844), (320, 568)])
def test_arm_screen_fits_phone_width(base_url, width, height):
    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": width, "height": height})
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            _mount_arm(page, base_url)
            overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
            assert overflow <= 0, f"가로 넘침 {overflow}px"
            assert page.locator("[data-arm-pad]").is_visible()
            assert page.locator("[data-sim-status]").inner_text() == "조작 가능"
            assert page.locator("ui-topbar [data-gate-state]").is_hidden()
            assert page.locator("ui-topbar ui-brand small").is_hidden()
            assert errors == [], errors
        finally:
            browser.close()

_HOLD_PAD = """async (ms) => {
  const pad = document.querySelector('[data-arm-pad]');
  const box = pad.getBoundingClientRect();
  pad.dispatchEvent(new PointerEvent('pointerdown', {clientX: box.right, clientY: box.top + box.height / 2, pointerId: 1, bubbles: true}));
  await new Promise((r) => setTimeout(r, ms));
  const held = {status: document.querySelector('[data-arm-pad-status]').textContent,
                button: document.querySelector("[data-sim-delta='0.02']").getAttribute('reason')};
  pad.dispatchEvent(new PointerEvent('pointerup', {pointerId: 1, bubbles: true}));
  return held;
}"""


@pytest.mark.skipif(not browser_tests_enabled(), reason="ROSY_RUN_BROWSER_TESTS=1")
def test_arm_stick_held_keeps_going_across_goals_while_the_owner_is_active(tablet_page):
    """Review C1: the real owner says ready:false/"active" while a goal runs — that is busy, not blocked."""
    base_url, page, errors = tablet_page
    _mount_arm(page, base_url, settleMs=300)
    held = page.evaluate(_HOLD_PAD, 2600)
    page.wait_for_timeout(800)
    count = page.evaluate("window.goals.length")
    assert count >= 3, count
    assert page.evaluate("window.rejections") == []                 # never overlapping, never a stale sequence
    assert held["button"] == "조이스틱 사용 중"                          # ± wait while the stick is held (I2)
    assert page.evaluate("window.goals.length") == count             # release stops new goals
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(), reason="ROSY_RUN_BROWSER_TESTS=1")
def test_arm_sequence_mismatch_is_retried_once_not_a_release(tablet_page):
    """Gazebo run: a new /joint_states between GET /state and POST → 409 joint_state_sequence_mismatch."""
    base_url, page, errors = tablet_page
    _mount_arm(page, base_url, settleMs=300, mismatchOnce=True)
    page.evaluate(_HOLD_PAD, 1500)
    assert page.evaluate("window.rejections") == ["joint_state_sequence_mismatch"]
    assert page.evaluate("window.goals.length") >= 2
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(), reason="ROSY_RUN_BROWSER_TESTS=1")
def test_arm_stick_stops_at_the_joint_limit_without_a_refused_goal(tablet_page):
    base_url, page, errors = tablet_page
    _mount_arm(page, base_url, settleMs=150)
    page.evaluate("window.pos.joint1 = 0.98")
    page.wait_for_timeout(1200)                                     # a readback with the new position
    held = page.evaluate(_HOLD_PAD, 1500)
    assert [g["delta_rad"] for g in page.evaluate("window.goals")] == [0.02]
    assert page.evaluate("window.rejections") == []
    assert held["status"].startswith("관절 한계")
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(), reason="ROSY_RUN_BROWSER_TESTS=1")
def test_arm_seat_loss_drops_the_goal_and_offers_pairing(tablet_page):
    base_url, page, errors = tablet_page
    _mount_arm(page, base_url)
    page.click("[data-sim-delta='0.02']")
    page.wait_for_function("!document.querySelector('[data-sim-cancel]').disabled")
    page.evaluate("window.seatLost = true")
    page.wait_for_selector("[data-sim-pair]", state="visible")
    assert page.locator("[data-sim-cancel]").is_disabled()
    assert page.inner_text("[data-sim-status]").startswith("조작 보류")
    assert page.locator("[data-arm-pad]").get_attribute("aria-disabled") == "true"
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(), reason="ROSY_RUN_BROWSER_TESTS=1")
def test_arm_goal_unknown_to_the_server_is_settled(tablet_page):
    base_url, page, errors = tablet_page
    _mount_arm(page, base_url)
    page.click("[data-sim-delta='0.02']")
    page.wait_for_function("!document.querySelector('[data-sim-cancel]').disabled")
    page.evaluate("window.forgetGoals = true")
    page.wait_for_function("document.querySelector('[data-sim-status]').textContent.includes('goal_unknown')")
    page.wait_for_function("document.querySelector('[data-sim-cancel]').disabled")
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(), reason="ROSY_RUN_BROWSER_TESTS=1")
def test_arm_gripper_presets_slider_and_badge(tablet_page):
    """D-411 C: one absolute goal per preset or slider release; the badge reads the grasp state."""
    base_url, page, errors = tablet_page
    _mount_arm(page, base_url, gripper=True)
    badge = page.locator("[data-gripper-state]")
    assert badge.inner_text() == "닫힘" and badge.get_attribute("aria-live") == "polite"
    assert "gripper_joint_1" not in page.locator("[data-sim-joint] option").all_inner_texts()
    page.click("[data-gripper-preset='half']")
    page.wait_for_function("window.grips.length === 1")
    grip = page.evaluate("window.grips[0]")
    assert grip["position"] == 0.5 and grip["duration_s"] == 1.12         # 0.5 rad at 0.9 x 0.5 rad/s, rounded up
    page.wait_for_function("document.querySelector('[data-gripper-state]').textContent === '이동 중'")
    assert page.locator("[data-gripper-preset='close']").is_disabled()     # one goal at a time
    assert page.locator("[data-gripper-percent]").is_disabled()
    page.evaluate("window.terminal = 'SUCCEEDED'")
    page.wait_for_function("!document.querySelector('[data-gripper-percent]').disabled")
    assert badge.inner_text() == "열림"
    assert page.locator("[data-gripper-percent]").input_value() == "50"
    page.evaluate("""() => { const s = document.querySelector('[data-gripper-percent]');
      s.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true})); s.value = '100';
      s.dispatchEvent(new Event('input', {bubbles: true})); s.dispatchEvent(new Event('change', {bubbles: true})); }""")
    page.wait_for_function("window.grips.length === 2")
    grip = page.evaluate("window.grips[1]")
    assert grip["position"] == 1.0 and grip["duration_s"] == 1.12
    page.evaluate("window.pos.gripper_joint_1 = 0.3; window.gripperState = 'holding'")
    page.wait_for_function("document.querySelector('[data-gripper-state]').textContent === '쥐고 있음'")
    assert page.evaluate("window.rejections") == []
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(), reason="ROSY_RUN_BROWSER_TESTS=1")
@pytest.mark.parametrize("viewport", [(2000, 1200), (1200, 2000), (390, 844), (320, 568)])
def test_arm_gripper_sits_in_the_right_hand_slot(base_url, viewport):
    shots = Path(os.environ.get("ROSY_SHOT_DIR", "X:/DevTemp/d411-c"))
    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            _mount_arm(page, base_url, gripper=True)
            jog = page.locator("[data-control='joint_jog']").bounding_box()
            grip = page.locator("[data-control='gripper']").bounding_box()
            overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
            assert overflow <= 0, f"가로 넘침 {overflow}px"
            if viewport[0] >= 1024:
                assert grip["x"] >= jog["x"] + jog["width"] and abs(grip["y"] - jog["y"]) < 2, (jog, grip)
                assert abs(grip["width"] - jog["width"]) <= 1, (jog, grip)
                assert page.locator(".arm-controls").bounding_box()["width"] > 900
            else:
                assert grip["y"] >= jog["y"] + jog["height"], (jog, grip)
                assert abs(grip["width"] - jog["width"]) <= 1, (jog, grip)
            for name in ("open", "half", "close"):
                box = page.locator(f"[data-gripper-preset='{name}']").bounding_box()
                assert box["height"] >= 40 and box["x"] + box["width"] <= viewport[0], (name, box)
            if shots.drive and Path(shots.drive + "/").exists():
                shots.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(shots / f"pilot-arm-gripper-{viewport[0]}x{viewport[1]}.png"), full_page=True)
            assert errors == [], errors
        finally:
            browser.close()


@pytest.mark.skipif(not browser_tests_enabled(), reason="ROSY_RUN_BROWSER_TESTS=1")
def test_a_widget_that_throws_is_shown_not_fatal(tablet_page):
    base_url, page, errors = tablet_page
    page.goto(f"{base_url}/pilot")
    text = page.evaluate("""async () => {
      const {composeControls} = await import('/pilot/assets/screens/compose.js');
      const root = document.createElement('div'); document.body.append(root);
      composeControls(root, [{id: 'a', kind: 'joint_jog', label: '팔'}, {id: 'b', kind: 'ok', label: '확인'}],
        {joint_jog: () => { throw new Error('bad joints'); }, ok: (slot) => { slot.textContent = 'fine'; }}, {});
      return [...root.children].map((slot) => slot.textContent);
    }""")
    assert text == ["그릴 수 없는 조작부 · 팔", "fine"]
    assert errors == [], errors


def _enter_drive_with(page, base_url, items):
    page.request.post(f"{base_url}/__test__/controls", data={"items": items})
    page.goto(f"{base_url}/pilot")
    page.fill("form[data-pilot-token-form] ui-field input", "devtoken")
    page.click("form[data-pilot-token-form] ui-button")
    page.click("[data-drive-enter]")
    page.wait_for_selector("[data-drive-stick]")


@pytest.mark.skipif(not browser_tests_enabled(), reason="ROSY_RUN_BROWSER_TESTS=1")
def test_zero_announced_limits_show_standstill(tablet_page):
    base_url, page, errors = tablet_page
    _enter_drive_with(page, base_url, [{**dev_server._BASE_CONTROL, "max_linear": 0, "max_angular": 0}])
    page.wait_for_function("document.querySelector('[data-drive-fact=cap]').textContent.includes('정지로 제한됨')")
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(), reason="ROSY_RUN_BROWSER_TESTS=1")
def test_a_base_without_pivot_or_fine_draws_neither_and_ignores_q_e(tablet_page):
    base_url, page, errors = tablet_page
    _enter_drive_with(page, base_url, [{**dev_server._BASE_CONTROL, "pivot": False, "fine": False}])
    assert page.locator("[data-drive-pivot]").count() == 0
    assert page.locator("[data-drive-scroll-cue]").count() == 0
    assert page.locator("[data-drive-fine]").count() == 0
    page.wait_for_function("document.querySelector('[data-drive-fact=cap]')?.textContent.includes('0.10')")
    dev_server.TELEOP_LOG.clear()
    page.keyboard.down("KeyQ")
    page.wait_for_timeout(600)
    page.keyboard.up("KeyQ")
    assert all(entry["angular"] == 0 for entry in dev_server.TELEOP_LOG)
    assert errors == [], errors

# A zone point straight above the ring, as high as the column allows (top edge + 4 px).
_ZONE_TOP = """() => {
  const stick = document.querySelector('[data-drive-stick]').getBoundingClientRect();
  const column = document.querySelector('[data-drive-right]').getBoundingClientRect();
  const cx = stick.left + stick.width / 2, cy = stick.top + stick.height / 2, r = stick.width / 2;
  for (let k = 1.75; k > 1.05; k -= 0.05) {
    const y = Math.max(column.top + 4, cy - k * r);
    if (cy - y > r && document.elementFromPoint(cx, y)?.closest('[data-drive-stick]')) {
      return {x: cx, y, r, clamped: y - r < column.top};
    }
  }
  return null;
}"""
_RING_IN_COLUMN = """() => {
  const el = document.querySelector('[data-drive-stick]');
  const ring = el.getBoundingClientRect();
  const column = document.querySelector('[data-drive-right]').getBoundingClientRect();
  return {inside: ring.top >= column.top - 0.5 && ring.bottom <= column.bottom + 0.5
                  && ring.left >= column.left - 0.5 && ring.right <= column.right + 0.5,
          ring: [ring.left, ring.top, ring.right, ring.bottom], column: [column.left, column.top, column.right, column.bottom]};
}"""


def _zone_point(page):
    """A point 1.5 ring radii from the stick centre, outside the ring but inside its column."""
    return page.evaluate("""() => {
      const stick = document.querySelector('[data-drive-stick]').getBoundingClientRect();
      const column = document.querySelector('[data-drive-right]').getBoundingClientRect();
      const cx = stick.left + stick.width / 2, cy = stick.top + stick.height / 2, r = stick.width / 2;
      for (const [name, dx, dy] of [['up', 0, -1], ['right', 1, 0], ['left', -1, 0], ['down', 0, 1]]) {
        const x = cx + dx * 1.5 * r, y = cy + dy * 1.5 * r;
        if (x > column.left + 2 && x < column.right - 2 && y > column.top + 2 && y < column.bottom - 2
            && document.elementFromPoint(x, y)?.closest('[data-drive-stick]')) return {name, x, y, r};
      }
      return null;
    }""")


@pytest.mark.skipif(not browser_tests_enabled(), reason="ROSY_RUN_BROWSER_TESTS=1")
@pytest.mark.parametrize("viewport", [(2000, 1200), (390, 844)])
def test_stick_grabs_a_touch_outside_the_ring_but_not_a_neighbour_button(base_url, viewport):
    """Tablet field report 2026-10-02: the ring is too small. An invisible zone around it grabs the
    stick; deflection is measured from the ring centre and clamped at the ring edge."""
    log = f"{base_url}/__test__/teleop"
    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            _enter_drive(page, base_url)
            point = _zone_point(page)
            assert point, "no room for the zone around the ring"
            # Floating origin (re-review I-B): a touch outside the ring is zero, not full deflection.
            before = len(page.request.get(log).json())
            page.mouse.move(point["x"], point["y"])
            page.mouse.down()
            page.wait_for_timeout(600)
            assert page.locator("[data-drive-stick].active").count() == 1
            landed = page.request.get(log).json()[before:]
            assert all(c["linear"] == 0 and c["angular"] == 0 for c in landed), landed   # no motion (zeros or nothing)
            cap = float(page.inner_text("[data-drive-fact=cap]").split()[1])
            page.mouse.move(point["x"], point["y"] - point["r"], steps=4)       # up by one ring radius
            page.wait_for_timeout(800)
            page.mouse.up()
            page.wait_for_timeout(400)
            sent = page.request.get(log).json()
            moved = sent[before + len(landed):]
            peak = max(c["linear"] for c in moved)
            # the HUD shows the cap to 2 decimals (0.105 → "0.10"); full deflection reaches it.
            assert abs(peak - cap) <= 0.0051 and all(c["angular"] == 0 for c in moved), (cap, moved)
            assert page.evaluate("getComputedStyle(document.querySelector('[data-drive-stick]')).translate") in ("none", "")
            assert sent[-1]["linear"] == 0 and sent[-1]["angular"] == 0      # release ends the hold
            # D-411 B follow-up (phone): a touch at the top of the zone must not push the drawn ring
            # out of its column (it was clipped); only the drawing is clamped, zero stays under the finger.
            top = page.evaluate(_ZONE_TOP)
            assert top, "no zone point near the top of the column"
            before = len(page.request.get(log).json())
            page.mouse.move(top["x"], top["y"])
            page.mouse.down()
            page.wait_for_timeout(400)
            ring = page.evaluate(_RING_IN_COLUMN)
            assert ring["inside"], ring
            if viewport[0] < 600:
                assert top["clamped"], top           # phone: unclamped, the ring would leave the column
            if viewport[0] < 600:
                shots = Path(os.environ.get("ROSY_SHOT_DIR", "X:/DevTemp/d411-c"))
                if shots.drive and Path(shots.drive + "/").exists():
                    shots.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(shots / f"pilot-drive-zone-top-{viewport[0]}x{viewport[1]}.png"))
            landed = page.request.get(log).json()[before:]
            assert all(c["linear"] == 0 and c["angular"] == 0 for c in landed), landed
            page.mouse.move(top["x"], top["y"] - top["r"], steps=4)          # up one radius from the touch
            page.wait_for_timeout(600)
            page.mouse.up()
            page.wait_for_timeout(300)
            moved = page.request.get(log).json()[before + len(landed):]
            assert abs(max(c["linear"] for c in moved) - cap) <= 0.0051, (cap, moved)
            for selector in ("[data-drive-pedal=forward]", "[data-drive-pivot=right]"):
                box = page.locator(selector).bounding_box()
                page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                page.mouse.down()
                page.wait_for_timeout(150)
                assert page.locator("[data-drive-stick].active").count() == 0, selector
                page.mouse.up()
            view = page.locator("[data-drive-view]").bounding_box()
            hit = page.evaluate("([x, y]) => Boolean(document.elementFromPoint(x, y)?.closest('[data-drive-stick]'))",
                                [view["x"] + view["width"] / 2, view["y"] + view["height"] / 2])
            assert not hit, "the zone must not cover the camera view"
            assert errors == [], errors
        finally:
            browser.close()

@pytest.mark.skipif(not browser_tests_enabled(), reason="ROSY_RUN_BROWSER_TESTS=1")
def test_a_settle_survives_a_failed_readback_right_after_it(tablet_page):
    """Re-review I-A: /state fails once right after SUCCEEDED — the stick must not wait forever."""
    base_url, page, errors = tablet_page
    _mount_arm(page, base_url)
    page.evaluate("""() => {
      const pad = document.querySelector('[data-arm-pad]'); const box = pad.getBoundingClientRect();
      pad.dispatchEvent(new PointerEvent('pointerdown', {clientX: box.right, clientY: box.top + box.height / 2, pointerId: 1, bubbles: true}));
    }""")
    page.wait_for_function("window.goals.length === 1")
    page.evaluate("window.terminal = 'RUNNING'; window.settleOnPoll = true")
    page.wait_for_function("document.querySelector('[data-sim-status]').textContent.startsWith('조작 보류')")
    page.evaluate("document.querySelector('[data-arm-pad]').dispatchEvent(new PointerEvent('pointerup', {pointerId: 1, bubbles: true}))")
    page.wait_for_function("document.querySelector('[data-sim-status]').textContent === '조작 가능'")
    page.evaluate("""() => {
      const pad = document.querySelector('[data-arm-pad]'); const box = pad.getBoundingClientRect();
      pad.dispatchEvent(new PointerEvent('pointerdown', {clientX: box.right, clientY: box.top + box.height / 2, pointerId: 2, bubbles: true}));
    }""")
    page.wait_for_function("window.goals.length === 2", timeout=5000)
    page.evaluate("document.querySelector('[data-arm-pad]').dispatchEvent(new PointerEvent('pointerup', {pointerId: 2, bubbles: true}))")
    assert page.evaluate("window.rejections") == []
    assert errors == [], errors
@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
@pytest.mark.parametrize("width,height", [(2000, 1200), (1200, 2000), (390, 844), (320, 568)])
def test_startup_target_failure_retries_without_pinky_fallback(tablet_page, width, height):
    from playwright.sync_api import expect
    base_url, page, errors = tablet_page
    page.set_viewport_size({"width": width, "height": height})
    state = {"status": 503, "body": {}, "held": []}
    def target(route):
        if state["status"] is None: state["held"].append(route)
        else: route.fulfill(status=state["status"], json=state["body"])
    page.route('**/api/v1/sim/omx/target', target)
    page.goto(base_url + '/pilot')
    retry = page.get_by_role('button', name='대상 다시 확인', exact=True)
    def capture_target_error(state_name):
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        for control in (retry, page.locator('ui-topbar [data-estop]')):
            box = control.bounding_box()
            assert box and box['x'] >= 0 and box['x'] + box['width'] <= width
            assert box['y'] >= 0 and box['y'] + box['height'] <= height
            assert box['height'] >= 44
        if os.environ.get('ROSY_SHOT_DIR'):
            shot_dir = Path(os.environ['ROSY_SHOT_DIR'])
            shot_dir.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(shot_dir / f'pilot-target-{state_name}-{width}x{height}.png'))
    expect(retry).to_be_visible()
    expect(page.locator('[data-screen=connect]')).to_contain_text('조종 대상을 확인하지 못했습니다')
    assert not page.locator('[data-pilot-token-form]').count()
    capture_target_error('unavailable')
    state.update(status=200, body={"kind": "invalid"})
    retry.click()
    expect(page.locator('[data-screen=connect]')).to_contain_text('연결과 대상 정보를 확인한 뒤 다시 시도하세요')
    expect(page.locator('[data-screen=connect]')).not_to_contain_text('invalid simulation target')
    capture_target_error('invalid')
    state['status'] = None
    retry.click()
    page.wait_for_function("document.querySelector('[data-discovery-retry]').disabled")
    retry.dispatch_event('click')
    assert len(state['held']) == 1
    state['held'][0].fulfill(status=404, json={})
    expect(page.locator('[data-pilot-token-form]')).to_be_visible()
    expect(page.locator('#pilot-notice')).to_have_text('')
    state.update(status=503, held=[])
    page.reload()
    expect(retry).to_be_visible()
    state['status'] = None
    retry.click()
    page.wait_for_function("document.querySelector('[data-discovery-retry]').disabled")
    page.locator('#pilot-notice').evaluate("node => node.textContent = '정지 요청을 보냈습니다'")
    page.wait_for_timeout(50)
    assert len(state['held']) == 1
    state['held'][0].fulfill(status=404, json={})
    expect(page.locator('[data-pilot-token-form]')).to_be_visible()
    expect(page.locator('#pilot-notice')).to_have_text('정지 요청을 보냈습니다')
    state.update(status=503, held=[])
    page.reload()
    expect(retry).to_be_visible()
    state['status'] = None
    retry.click()
    page.wait_for_function("document.querySelector('[data-discovery-retry]').disabled")
    page.locator('#pilot-notice').evaluate("node => node.textContent = '정지 요청을 보냈습니다'")
    page.wait_for_timeout(50)
    assert len(state['held']) == 1
    state['held'][0].fulfill(status=503, json={})
    expect(retry).to_be_enabled()
    expect(page.locator('[data-screen=connect]')).to_contain_text('조종 대상을 확인하지 못했습니다')
    expect(page.locator('#pilot-notice')).to_have_text('정지 요청을 보냈습니다')
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    assert errors == []


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
def test_show_code_visible_for_operator_with_upgrade_path_and_working_for_admin(tablet_page):
    """양방향 연동(D-193 §5): 운영자에게도 항목이 보이고 전환 길을 제공, 관리자는 발급·표시."""
    base_url, page, errors = tablet_page
    page.goto(f"{base_url}/pilot")
    page.wait_for_selector("form[data-pilot-token-form] ui-field input")
    page.fill("form[data-pilot-token-form] ui-field input", "devtoken")
    page.click("form[data-pilot-token-form] ui-button")
    page.wait_for_selector("[data-drive-enter]")
    # 운영자: 항목은 보이지만 발급은 CORE 403 — 전환 안내가 떠야 한다.
    page.locator("[data-show-code]").wait_for(state="visible")
    page.click("[data-show-code]")
    page.wait_for_selector("[data-enroll-upgrade]")
    assert "관리자 권한이 필요합니다" in page.inner_text("[data-enroll-status]")
    page.click("[data-enroll-upgrade]")
    page.wait_for_selector("form[data-pilot-token-form] ui-field input")
    page.get_by_text("관리자 코드를 입력하면 연동 코드를 발급할 수 있습니다.").wait_for(state="visible")
    page.evaluate("sessionStorage.clear()")
    page.goto(f"{base_url}/pilot")
    page.wait_for_selector("form[data-pilot-token-form] ui-field input")
    page.fill("form[data-pilot-token-form] ui-field input", "devadmintoken")
    page.click("form[data-pilot-token-form] ui-button")
    page.wait_for_selector("[data-drive-enter]")
    page.locator("[data-show-code]").wait_for(state="visible")
    page.click("[data-show-code]")
    page.wait_for_selector("[data-enroll-code]")
    assert page.inner_text("[data-enroll-code]") == "DEMO-C0DE"
    assert "상대 기기에서 입력하세요" in page.inner_text("[data-enroll-status]")
    assert page.inner_text("[data-enroll-timer]").startswith("유효 05:0")
    page.wait_for_timeout(1500)
    assert page.inner_text("[data-enroll-timer]") != "유효 05:00"
    assert page.locator("[data-show-code]").is_enabled()
    overflow = page.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert overflow <= 0, f"가로 넘침 {overflow}px"
    page.evaluate("sessionStorage.clear()")
    page.goto(f"{base_url}/pilot")  # 재진입: 카운트다운 타이머가 정리된다
    page.wait_for_selector("form[data-pilot-token-form] ui-field input")
    page.wait_for_timeout(1200)
    assert page.locator("[data-enroll-timer]").count() == 0
    assert errors == [], errors
