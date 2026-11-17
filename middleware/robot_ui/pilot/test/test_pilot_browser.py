"""D-323 — /pilot 브라우저 계약 (dev_server 가짜 CORE).

게이트 플로우 + 주행 화면 마운트 + 카메라 프레임 + 속도 프리셋을 태블릿 뷰포트에서
기계로 판정한다. ROSY_RUN_BROWSER_TESTS=1 옵트인.
"""

from __future__ import annotations

import os
import json
import sys
import time
from pathlib import Path

import pytest
from browser_harness import browser_tests_enabled

playwright_sync = pytest.importorskip("playwright.sync_api", reason="Playwright 없음")

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
    page.click("[data-sim-record-stop='success']")
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
    # D-741 3: the app bar brand is the R mark, the app name, then this robot's name.
    assert page.locator("ui-topbar ui-brand b").text_content() == "Pilot"
    robot_name = page.locator("ui-topbar ui-brand [data-pilot-robot]")
    assert robot_name.text_content() == "rosy_26" and robot_name.is_visible()
    controls = page.locator("ui-topbar ui-button")
    assert controls.last.get_attribute("data-estop") is not None, "the stop is the last control in the bar"
    assert "로봇 화면에 뜬 로그인 코드" in offer.inner_text()
    assert page.locator("[data-dev-connect]").count() == 0
    text = page.locator("[data-screen=connect]").inner_text()
    assert text.index("rosy_26") < text.index("rosy-pinky-8kcn.local")
    assert errors == [], errors


CONNECT_BAR = """() => {
  const box = (selector) => { const r = document.querySelector(selector).getBoundingClientRect();
    return {x: r.x, y: r.y, right: r.right, bottom: r.bottom, width: r.width, height: r.height}; };
  const name = document.querySelector('[data-pilot-robot]');
  const shown = {bar: box('ui-topbar'), stop: box('[data-estop]'), brand: box('ui-brand'), mark: box('ui-brand b'),
    name: box('[data-pilot-robot]'), cut: name.scrollWidth > name.clientWidth,
    em: parseFloat(getComputedStyle(document.querySelector('ui-brand b')).fontSize),
    overflow: document.documentElement.scrollWidth - innerWidth};
  const hit = document.elementFromPoint(shown.stop.x + shown.stop.width / 2, shown.stop.y + shown.stop.height / 2);
  name.hidden = true;
  const bare = {bar: box('ui-topbar'), stop: box('[data-estop]')};
  name.hidden = false;
  return {shown, bare, stopOnTop: Boolean(hit?.closest('[data-estop]'))};
}"""


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
@pytest.mark.parametrize("width,height", [(390, 844), (320, 568)])
@pytest.mark.parametrize("robot_id", ["rosy_26", "rosy-pinky-with-a-very-long-robot-name-0026"])
def test_connect_app_bar_names_this_robot_at_phone_width(tablet_page, width, height, robot_id):
    """D-741 3: the connect screen's app bar says which robot this is at phone width too. Below 30rem the wordmark
    folds to the R mark and the name stands beside it in the same row. A long name is cut with an ellipsis.
    The name neither moves nor covers the stop and the bar does not grow."""
    base_url, page, errors = tablet_page
    page.set_viewport_size({"width": width, "height": height})
    page.route("**/api/v1/auth/connection", lambda route: route.fulfill(
        json={"mode": "paired", "robot_id": robot_id, "transport": "https"}))
    page.goto(f"{base_url}/pilot")
    page.locator("[data-connection-title]").wait_for()
    name = page.locator("ui-topbar ui-brand [data-pilot-robot]")
    playwright_sync.expect(name).to_have_text(robot_id)
    got = page.evaluate(CONNECT_BAR)
    print(json.dumps({"width": width, "robot_id": robot_id, **got}))
    shown, bare = got["shown"], got["bare"]
    assert name.is_visible() and shown["name"]["width"] > 0, got
    assert shown["mark"]["width"] <= shown["em"] + 1, got  # the R mark alone
    assert shown["mark"]["right"] <= shown["name"]["x"] + 1 and shown["name"]["right"] <= shown["stop"]["x"], got
    assert shown["brand"]["y"] - 1 <= shown["name"]["y"] and shown["name"]["bottom"] <= shown["brand"]["bottom"] + 1, got
    assert shown["brand"]["height"] <= 64, got
    assert shown["cut"] == (len(robot_id) > 20), got
    assert shown["bar"]["height"] == bare["bar"]["height"], got
    assert all(abs(shown["stop"][key] - bare["stop"][key]) <= 0.5 for key in ("x", "y", "width", "height")), got
    assert got["stopOnTop"] and shown["stop"]["right"] <= width and shown["stop"]["height"] >= 44, got
    assert shown["overflow"] <= 0, got
    assert page.locator("ui-topbar ui-brand a").get_attribute("aria-label") == "Rosy Pilot 접속 홈"
    assert errors == [], errors


ONE_ROW_BAR = """() => {
  const seats = {bar: 'ui-topbar', brand: 'ui-brand', mark: 'ui-brand b', name: '[data-pilot-robot]',
    tag: '[data-gate-state]', map: '[data-goto]', stop: '[data-estop]', notice: '#pilot-notice'};
  const read = () => Object.fromEntries(Object.entries(seats).map(([key, selector]) => {
    const r = document.querySelector(selector).getBoundingClientRect();
    return [key, {x: r.x, y: r.y, right: r.right, bottom: r.bottom, width: r.width, height: r.height}]; }));
  const notice = document.querySelector('#pilot-notice');
  const before = notice.textContent;
  notice.textContent = '';
  const quiet = read();
  const hit = document.elementFromPoint(quiet.stop.x + quiet.stop.width / 2, quiet.stop.y + quiet.stop.height / 2);
  notice.textContent = '로봇에 연결됐습니다 · 비상 정지 중';
  const told = read();
  notice.textContent = before;
  return {quiet, told, stopOnTop: Boolean(hit?.closest('[data-estop]')),
    token: parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--appbar-height')),
    overflow: document.documentElement.scrollWidth - innerWidth};
}"""


def _near(box, x, y, width, height):
    return all(abs(box[key] - want) <= 1 for key, want in zip(("x", "y", "width", "height"), (x, y, width, height)))


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
@pytest.mark.parametrize("width,height", [(320, 568), (390, 844), (768, 1024), (1024, 768), (1366, 768)])
def test_connect_app_bar_is_one_row_from_64rem_and_keeps_the_two_row_stop_below(tablet_page, width, height):
    """D-741 3·5 and its 2026-10-14 addendum. From 64rem the connect screen's app bar is one row of --appbar-height:
    brand, robot name, notice, gate state, 운용 지도, then the stop last, and the stop is no smaller than 82x48.
    Below 64rem nothing moved: the numbers are the ones measured before this change (sha d434979c9), where the
    stop spans both rows at 82x74 and a notice takes its own row under them."""
    base_url, page, errors = tablet_page
    page.set_viewport_size({"width": width, "height": height})
    page.route("**/api/v1/auth/connection", lambda route: route.fulfill(
        json={"mode": "paired", "robot_id": "rosy_26", "transport": "https"}))
    page.goto(f"{base_url}/pilot")
    page.locator("[data-connection-title]").wait_for()
    playwright_sync.expect(page.locator("ui-topbar ui-brand [data-pilot-robot]")).to_have_text("rosy_26")
    got = page.evaluate(ONE_ROW_BAR)
    print(json.dumps({"width": width, **got}))
    quiet, told, token = got["quiet"], got["told"], got["token"]
    assert token == 64 and got["stopOnTop"] and got["overflow"] <= 0, got
    assert all(abs(told[seat][key] - quiet[seat][key]) <= 0.5 for seat in ("stop", "map", "tag", "name", "mark")
               for key in ("x", "y", "width", "height")), got  # a notice moves and squeezes nothing
    assert told["notice"]["width"] > 0, got
    if width < 1024:
        mark, name_x = (20, 56) if width < 480 else (79, 115)
        assert quiet["bar"]["height"] == 103 and abs(told["bar"]["height"] - 120) <= 1, got
        assert _near(quiet["stop"], width - 106, 16, 82, 74), got
        assert _near(quiet["map"], 76, 42, 82, 48) and _near(quiet["tag"], 24, 58, 44, 32), got
        assert _near(quiet["name"], name_x, 20, 61, 14) and abs(quiet["mark"]["width"] - mark) <= 1, got
        assert _near(told["notice"], 24, 94, width - 48, 17), got
    else:
        assert quiet["bar"]["height"] == token and told["bar"]["height"] == token, got
        row = [told[key] for key in ("mark", "name", "notice", "tag", "map", "stop")]
        assert all(0 <= box["y"] and box["bottom"] <= token for box in row), got
        assert all(left["right"] <= right["x"] + 1 for left, right in zip(row, row[1:])), got
        assert abs(quiet["stop"]["x"] - (width - 106)) <= 1 and quiet["stop"]["right"] <= width, got
        assert quiet["stop"]["width"] >= 81.89 and quiet["stop"]["height"] >= 48, got  # 81.890625x48 before
        assert quiet["map"]["width"] >= 81.89 and quiet["map"]["height"] >= 48 and _near(quiet["tag"], width - 256, 16, 44, 32), got
    assert errors == [], errors


LONG_NOTICE = ("로그아웃 요청을 보내지 못했습니다. 계정 서버가 응답하지 않습니다. 이 기기의 로그인은 그대로 남아 있으니 "
               "네트워크를 확인한 뒤 다시 로그아웃하세요. (ACCOUNT_UNAVAILABLE)")  # no real connect string reaches 90 chars; error.message can


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
@pytest.mark.parametrize("width,height", [(1024, 768), (1366, 768)])
def test_one_row_bar_holds_a_long_notice_name_and_tag(tablet_page, width, height):
    """From 64rem a long notice, a long robot name and a long gate tag together neither grow the bar nor shrink,
    move or cover the stop. The notice stays whole for assistive tech (role=status textContent)."""
    assert len(LONG_NOTICE) >= 90
    base_url, page, errors = tablet_page
    page.set_viewport_size({"width": width, "height": height})
    robot_id = "rosy-pinky-with-a-very-long-robot-name-0026"
    page.route("**/api/v1/auth/connection", lambda route: route.fulfill(
        json={"mode": "paired", "robot_id": robot_id, "transport": "https"}))
    page.goto(f"{base_url}/pilot")
    page.locator("[data-connection-title]").wait_for()
    playwright_sync.expect(page.locator("ui-topbar ui-brand [data-pilot-robot]")).to_have_text(robot_id)
    got = page.evaluate("""(text) => {
      document.querySelector('#pilot-notice').textContent = text;
      document.querySelector('[data-gate-state]').textContent = '비상 정지 중 · 안전 상태 확인 불가';
      const box = (s) => { const r = document.querySelector(s).getBoundingClientRect();
        return {x: r.x, y: r.y, right: r.right, bottom: r.bottom, width: r.width, height: r.height}; };
      const stop = box('[data-estop]');
      const hit = document.elementFromPoint(stop.x + stop.width / 2, stop.y + stop.height / 2);
      return {bar: box('ui-topbar'), stop, notice: box('#pilot-notice'), tag: box('[data-gate-state]'),
        map: box('[data-goto]'), name: box('[data-pilot-robot]'), stopOnTop: Boolean(hit?.closest('[data-estop]')),
        said: document.querySelector('#pilot-notice').textContent,
        token: parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--appbar-height')),
        overflow: document.documentElement.scrollWidth - innerWidth};
    }""", LONG_NOTICE)
    print(json.dumps({"width": width, **got}))
    stop = got["stop"]
    assert got["bar"]["height"] == got["token"] == 64, got
    assert stop["width"] >= 81.89 and stop["height"] >= 48 and got["stopOnTop"], got
    assert abs(stop["x"] - (width - 106)) <= 1 and stop["bottom"] <= 64 and got["overflow"] <= 0, got
    assert got["map"]["width"] >= 81.89 and got["map"]["height"] >= 48, got
    assert got["notice"]["right"] <= got["tag"]["x"] + 1 and got["tag"]["right"] <= got["map"]["x"] + 1, got
    assert got["said"] == LONG_NOTICE, got
    assert got["notice"]["width"] > 0 and all(got[k]["y"] >= 0 and got[k]["bottom"] <= 64 for k in ("notice", "name", "tag")), got
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
def test_android_shell_bar_does_not_take_the_one_row_rule(tablet_page):
    """The Pilot app's WebView keeps its bar: --topbar-height at 64rem and above, with the stop at 82x48."""
    base_url, page, errors = tablet_page
    page.set_viewport_size({"width": 1366, "height": 768})
    _refuse_second_session(page)
    _open_in_pilot_app(page, base_url, "devtoken")
    _assert_visible(page, "[data-drive-enter]", errors)
    assert page.evaluate("document.body.dataset.pilotScreen") == "connect"
    bar = page.locator("ui-topbar").bounding_box()
    stop = page.locator("ui-topbar [data-estop]").bounding_box()
    print(json.dumps({"bar": bar, "stop": stop}))
    assert bar["height"] == 88 and _near(stop, 1260, 31, 82, 48), (bar, stop)
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
    for package in ("middleware/core/api", "middleware/core/gateway", "middleware/core/events",
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
            assert page.locator("[data-drive-fact=turn]").inner_text() != "0°/s"
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
