"""D-323 — /pilot 브라우저 계약 (dev_server 가짜 CORE).

게이트 플로우 + 주행 화면 마운트 + 카메라 프레임 + 속도 프리셋을 태블릿 뷰포트에서
기계로 판정한다. ROSY_RUN_BROWSER_TESTS=1 옵트인.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

playwright_sync = pytest.importorskip("playwright.sync_api", reason="Playwright 없음")
import uvicorn  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dev_server  # noqa: E402

TABLET_VIEWPORTS = [(2000, 1200), (1200, 2000)]


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1", reason="browser opt-in")
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
    page.fill("[data-sim-task]", "관절 이동 시연")
    page.click("[data-sim-record-start]")
    page.wait_for_function("document.querySelector('[data-sim-record-status]').textContent.includes('기록 시작 실패')")
    page.wait_for_timeout(1200)
    assert "기록 시작 실패" in page.inner_text("[data-sim-record-status]")
    page.click("[data-sim-record-start]")
    page.wait_for_function("document.querySelector('[data-sim-record-status]').textContent.includes('recording')")
    page.select_option("[data-sim-outcome]", "success")
    page.click("[data-sim-record-stop]")
    page.wait_for_function("window.outcome === 'success'")
    page.evaluate("window.cameraFresh = false")
    page.wait_for_function("document.querySelector('[data-sim-camera]').hidden")
    assert page.locator("[data-sim-record-start]").evaluate("b => b.disabled")
    page.evaluate("window.disposeArm()")
    page.wait_for_function("window.released === 1")
    assert errors == [], errors


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1", reason="browser opt-in")
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


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def base_url():
    config = uvicorn.Config(dev_server.app, host="127.0.0.1",
                            port=_free_port(), log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        thread.join(0.05)
    yield f"http://127.0.0.1:{config.port}"
    server.should_exit = True
    thread.join(timeout=5)


def _gate_value(page) -> str:
    return page.locator('dl[data-gate-readout] dd').first.inner_text()


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


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
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


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
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


def _enter_drive(page, base_url):
    page.goto(f"{base_url}/pilot")
    page.wait_for_selector("form[data-pilot-token-form] ui-field input")
    page.fill("form[data-pilot-token-form] ui-field input", "devtoken")
    page.click("form[data-pilot-token-form] ui-button")
    page.wait_for_selector("[data-drive-enter]")
    page.click("[data-drive-enter]")
    page.wait_for_selector("[data-drive-stick]")
    page.wait_for_function("document.querySelector('[data-drive-fact=cap]')?.textContent.includes('0.10')")


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
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


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
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


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
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


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_key_released_while_an_input_has_focus_still_stops(tablet_page):
    """W 를 누른 채 입력 조정 슬라이더를 누르고 W 를 떼도 키가 눌린 채 남지 않는다(리뷰 지적)."""
    base_url, page, errors = tablet_page
    _enter_drive(page, base_url)
    log = f"{base_url}/__test__/teleop"
    page.click("[data-drive-inputs]")
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


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
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


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
@pytest.mark.parametrize("viewport", [(2000, 1200), (1333, 760), (1200, 2000), (390, 844)])
def test_camera_keeps_aspect_and_controls_never_cover_it(base_url, viewport):
    """D-363: 카메라는 원본 비율 그대로 전부 보이고, 조작부·HUD·상단 바가 영상을 덮지 않는다."""
    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})
        try:
            _enter_drive(page, base_url)
            page.wait_for_selector("[data-drive-frame][src]", timeout=10_000)
            page.wait_for_function("document.querySelector('[data-drive-frame]').naturalWidth > 0")
            page.wait_for_timeout(300)
            m = page.evaluate(MEASURE_VIDEO)
        finally:
            browser.close()
    assert m["fit"] == "contain", m
    assert abs(m["shown"] - m["ratio"]) / m["ratio"] < 0.01, m
    assert m["overlaps"] == 0, m
    assert m["videoArea"] > 0.2, f"영상이 너무 작다: {m}"


CONTROL_BOXES = """(() => {
  const box = (s) => { const r = document.querySelector(s).getBoundingClientRect();
    return {x: r.x, y: r.y, w: r.width, h: r.height}; };
  return {stick: box('[data-drive-stick]'), pedal: box('[data-drive-pedal=forward]'),
          vw: innerWidth, vh: innerHeight};
})()"""


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
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
                    page.click("[data-drive-zoom]")
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


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
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


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
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


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
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


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
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


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
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


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
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


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
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


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
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


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
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
    page.click("[data-recordings-open]")
    row = page.locator(f"[data-recordings-sheet] [data-recording-id='{ROBOT_RECORDING_ID}']")
    row.wait_for()
    return row


def _enter_recording_drive(page, base_url, **scenario):
    _recordings(page, base_url, reset=True, **scenario)
    _enter_drive(page, base_url)
    page.wait_for_function("!document.querySelector('[data-robot-record]').disabled")


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
@pytest.mark.parametrize("viewport", [(2000, 1200), (1200, 2000), (390, 844)])
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
            page.click("[data-robot-record]")
            page.wait_for_function(ROBOT_RECORD_STOP)
            page.wait_for_selector("[data-drive-fact=recording]:not([hidden])")
            assert "녹화 0:01 / 10:00" in page.inner_text("[data-drive-fact=recording]")
            assert _recordings(page, base_url)["log"] == ["start"]
            row = _open_sheet(page)
            assert page.evaluate("!!document.activeElement.closest('[data-recordings-sheet]')"), "열면 시트로 초점"
            box = page.evaluate("""(() => { const s = document.querySelector('[data-recordings-sheet]').getBoundingClientRect();
              const h = document.querySelector('[data-drive-hud]').getBoundingClientRect();
              return {top: s.top, bottom: s.bottom, left: s.left, right: s.right, hud: h.bottom, vh: innerHeight}; })()""")
            assert box["top"] >= box["hud"], f"시트가 HUD 를 덮는다 {box}"
            assert box["left"] >= 0 and box["right"] <= viewport[0] + 1 and box["bottom"] <= box["vh"] + 1, box
            assert row.locator("[data-recording-fetch]").is_disabled()          # 녹화 중에는 받지 않는다
            assert "녹화 중에는" in page.inner_text("[data-recordings-notice]")
            assert page.get_attribute("[data-recordings-notice]", "aria-live") == "polite"
            page.click("[data-robot-record]")
            page.wait_for_function("document.querySelector('[data-robot-record]').textContent.trim() === '로봇 녹화'")
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
            assert page.evaluate("document.activeElement?.hasAttribute('data-recordings-open')")
        finally:
            browser.close()
    assert errors == [], errors


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_robot_recording_shows_starting_until_the_writer_records(tablet_page):
    """'녹화 중'은 로봇이 실제로 기록할 때부터다. 준비 중에는 타이머 없이 멈출 수만 있다."""
    base_url, page, errors = tablet_page
    _enter_recording_drive(page, base_url, starting=True)
    toggle = "[data-robot-record]"
    page.click(toggle)
    page.wait_for_function(f"document.querySelector('{toggle}').dataset.state === 'starting'")
    assert page.inner_text(toggle).strip() == "녹화 준비 중…"
    assert page.get_attribute(toggle, "aria-pressed") == "true"
    assert page.get_attribute(toggle, "aria-label") == "로봇 녹화 준비 중, 누르면 취소"
    assert not page.locator(toggle).is_disabled()
    # 켜진 버튼을 흐리게(opacity) 하지 않는다: 조용한 잉크(바탕 대비 4.5:1 이상)와 점선 테두리.
    look = page.evaluate(f"""(() => {{
      const b = getComputedStyle(document.querySelector('{toggle}'));
      const probe = document.createElement('span');
      probe.style.color = 'var(--ink-quiet)';
      document.body.append(probe);
      const quiet = getComputedStyle(probe).color;
      probe.remove();
      return {{opacity: b.opacity, color: b.color, quiet, border: b.borderTopStyle, borderColor: b.borderTopColor}};
    }})()""")
    assert look["opacity"] == "1", look
    assert look["color"] == look["quiet"] == look["borderColor"] and look["border"] == "dashed", look
    fact = page.inner_text("[data-drive-fact=recording]")
    assert "아직 기록하지 않습니다" in fact and "0:0" not in fact
    page.click(toggle)                                     # 준비 중 멈춤은 깨끗한 정지
    page.wait_for_function(f"document.querySelector('{toggle}').textContent.trim() === '로봇 녹화'")
    assert _recordings(page, base_url)["log"] == ["start", "stop"]
    page.click(toggle)
    page.wait_for_function(f"document.querySelector('{toggle}').dataset.state === 'starting'")
    _recordings(page, base_url, ready=True)                # 기록기가 첫 파일을 열었다
    page.wait_for_function(ROBOT_RECORD_STOP)
    page.wait_for_function("document.querySelector('[data-drive-fact=recording]').textContent.includes('녹화 0:')")
    assert page.get_attribute(toggle, "aria-label") == "로봇 녹화 중지"
    page.click(toggle)
    page.wait_for_function(f"document.querySelector('{toggle}').dataset.state === 'idle'")
    page.click(toggle)
    page.wait_for_function(f"document.querySelector('{toggle}').dataset.state === 'starting'")
    page.click("[data-drive-exit]")                        # 준비 중에 나가도 이 기기 녹화는 멈춘다
    assert _eventually(lambda: _recordings(page, base_url)["log"] == ["start", "stop", "start", "stop",
                                                                      "start", "stop"])
    assert errors == [], errors


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_leaving_drive_stops_the_robot_recording_this_device_started(tablet_page):
    base_url, page, errors = tablet_page
    _enter_recording_drive(page, base_url)
    page.click("[data-robot-record]")
    page.wait_for_function(ROBOT_RECORD_STOP)
    page.click("[data-drive-exit]")
    assert _eventually(lambda: _recordings(page, base_url)["log"] == ["start", "stop"])
    assert errors == [], errors


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_another_devices_recording_is_neither_stopped_nor_stoppable_here(tablet_page):
    base_url, page, errors = tablet_page
    _recordings(page, base_url, reset=True, foreign=True)
    _enter_drive(page, base_url)
    page.wait_for_function(ROBOT_RECORD_STOP)
    page.click("[data-robot-record]")
    page.wait_for_function("document.querySelector('[data-drive-fact=recording]').textContent.includes('다른 기기가 시작한')")
    page.click("[data-drive-exit]")
    assert _settled_polls(page, base_url)
    assert _recordings(page, base_url)["log"] == []
    assert errors == [], errors


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_a_viewer_is_told_it_needs_an_operator(tablet_page):
    base_url, page, errors = tablet_page
    _enter_recording_drive(page, base_url, role="viewer")
    page.click("[data-robot-record]")
    page.wait_for_function("document.querySelector('[data-drive-fact=recording]').textContent.includes('운전자(Operator)')")
    row = _open_sheet(page)
    row.locator("[data-recording-fetch]").click()
    page.wait_for_function("document.querySelector('[data-recording-status]')?.textContent.includes('운전자(Operator)')")
    assert _recordings(page, base_url)["log"] == []
    assert errors == [], errors


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
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


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
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


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_a_large_recording_points_to_the_pc_tool(tablet_page):
    base_url, page, errors = tablet_page
    _enter_recording_drive(page, base_url, big=True)
    row = _open_sheet(page)
    button = row.locator("[data-recording-fetch]")
    assert button.is_disabled()
    assert "rosy_ml fetch" in button.inner_text()
    assert errors == [], errors


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
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

@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1", reason="ROSY_RUN_BROWSER_TESTS=1")
def test_unknown_control_kind_is_shown_not_fatal(tablet_page):
    base_url, page, errors = tablet_page
    page.request.post(f"{base_url}/__test__/controls", data={"extra": {"id": "laser", "kind": "laser", "label": "레이저"}})
    _enter_drive(page, base_url)
    assert page.locator("[data-control-unsupported]").inner_text().strip() == "지원하지 않는 조작부 · 레이저"
    assert page.locator("[data-drive-auto]").count() == 1          # base_velocity autonomy ["line"]
    assert errors == [], errors


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1", reason="ROSY_RUN_BROWSER_TESTS=1")
def test_old_core_without_controls_falls_back_to_the_pinky_profile(tablet_page):
    base_url, page, errors = tablet_page
    page.request.post(f"{base_url}/__test__/controls", data={"omit": True})
    _enter_drive(page, base_url)
    assert page.locator("[data-drive-stage]").count() == 1
    assert page.locator("[data-drive-auto]").count() == 1          # legacy PROFILE autonomy ["line"]
    assert page.locator("[data-control-unsupported]").count() == 0
    assert errors == [], errors


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1", reason="ROSY_RUN_BROWSER_TESTS=1")
def test_announced_autonomy_decides_the_line_toggle(tablet_page):
    base_url, page, errors = tablet_page
    page.request.post(f"{base_url}/__test__/controls",
                      data={"items": [{**dev_server._BASE_CONTROL, "autonomy": []}]})
    _enter_drive(page, base_url)
    assert page.locator("[data-drive-auto]").count() == 0
    assert errors == [], errors


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1", reason="ROSY_RUN_BROWSER_TESTS=1")
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
    mismatchOnce: Boolean(opts.mismatchOnce), started: {}});
  const TERMINAL = ['SUCCEEDED', 'REJECTED', 'CANCELED', 'UNKNOWN_HOLD'];
  const goalState = (id) => opts.settleMs ? (performance.now() - window.started[id] >= opts.settleMs ? 'SUCCEEDED' : 'RUNNING')
                                          : window.terminal;
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
      if (window.settleOnPoll) { window.settleOnPoll = false; window.terminal = 'SUCCEEDED'; window.failNextState = true; }
      return {state: goalState(decodeURIComponent(path.slice(7)))};
    }
    return {};
  }};
  const root = document.querySelector('[data-screen="arm"]');
  document.body.dataset.pilotScreen = 'arm';
  document.querySelector('[data-screen="connect"]').hidden = true;
  root.hidden = false;
  sessionStorage.setItem(`rosy.pilot.omx-sim.${location.origin}`, 't');
  window.disposeArm = mountArm(root, target, driver);
}"""


def _mount_arm(page, base_url, **opts):
    page.goto(f"{base_url}/pilot")
    page.wait_for_selector("form[data-pilot-token-form]")
    page.evaluate(_ARM_HARNESS, opts)
    page.wait_for_function("document.querySelector('[data-sim-status]').textContent === '조작 가능'")


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1", reason="ROSY_RUN_BROWSER_TESTS=1")
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


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1", reason="ROSY_RUN_BROWSER_TESTS=1")
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


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1", reason="ROSY_RUN_BROWSER_TESTS=1")
def test_arm_screen_fits_phone_width(base_url):
    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 390, "height": 844})
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            _mount_arm(page, base_url)
            overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
            assert overflow <= 0, f"가로 넘침 {overflow}px"
            assert page.locator("[data-arm-pad]").is_visible()
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


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1", reason="ROSY_RUN_BROWSER_TESTS=1")
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


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1", reason="ROSY_RUN_BROWSER_TESTS=1")
def test_arm_sequence_mismatch_is_retried_once_not_a_release(tablet_page):
    """Gazebo run: a new /joint_states between GET /state and POST → 409 joint_state_sequence_mismatch."""
    base_url, page, errors = tablet_page
    _mount_arm(page, base_url, settleMs=300, mismatchOnce=True)
    page.evaluate(_HOLD_PAD, 1500)
    assert page.evaluate("window.rejections") == ["joint_state_sequence_mismatch"]
    assert page.evaluate("window.goals.length") >= 2
    assert errors == [], errors


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1", reason="ROSY_RUN_BROWSER_TESTS=1")
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


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1", reason="ROSY_RUN_BROWSER_TESTS=1")
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


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1", reason="ROSY_RUN_BROWSER_TESTS=1")
def test_arm_goal_unknown_to_the_server_is_settled(tablet_page):
    base_url, page, errors = tablet_page
    _mount_arm(page, base_url)
    page.click("[data-sim-delta='0.02']")
    page.wait_for_function("!document.querySelector('[data-sim-cancel]').disabled")
    page.evaluate("window.forgetGoals = true")
    page.wait_for_function("document.querySelector('[data-sim-status]').textContent.includes('goal_unknown')")
    page.wait_for_function("document.querySelector('[data-sim-cancel]').disabled")
    assert errors == [], errors


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1", reason="ROSY_RUN_BROWSER_TESTS=1")
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


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1", reason="ROSY_RUN_BROWSER_TESTS=1")
@pytest.mark.parametrize("viewport", [(2000, 1200), (390, 844)])
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
                assert grip["width"] < jog["width"]
            else:
                assert grip["y"] >= jog["y"] + jog["height"], (jog, grip)
            for name in ("open", "half", "close"):
                box = page.locator(f"[data-gripper-preset='{name}']").bounding_box()
                assert box["height"] >= 40 and box["x"] + box["width"] <= viewport[0], (name, box)
            if shots.drive and Path(shots.drive + "/").exists():
                shots.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(shots / f"pilot-arm-gripper-{viewport[0]}x{viewport[1]}.png"), full_page=True)
            assert errors == [], errors
        finally:
            browser.close()


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1", reason="ROSY_RUN_BROWSER_TESTS=1")
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


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1", reason="ROSY_RUN_BROWSER_TESTS=1")
def test_zero_announced_limits_show_standstill(tablet_page):
    base_url, page, errors = tablet_page
    _enter_drive_with(page, base_url, [{**dev_server._BASE_CONTROL, "max_linear": 0, "max_angular": 0}])
    page.wait_for_function("document.querySelector('[data-drive-fact=cap]').textContent.includes('정지로 제한됨')")
    assert errors == [], errors


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1", reason="ROSY_RUN_BROWSER_TESTS=1")
def test_a_base_without_pivot_or_fine_draws_neither_and_ignores_q_e(tablet_page):
    base_url, page, errors = tablet_page
    _enter_drive_with(page, base_url, [{**dev_server._BASE_CONTROL, "pivot": False, "fine": False}])
    assert page.locator("[data-drive-pivot]").count() == 0
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


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1", reason="ROSY_RUN_BROWSER_TESTS=1")
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

@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1", reason="ROSY_RUN_BROWSER_TESTS=1")
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
