"""D-323 — /pilot 브라우저 계약 (dev_server 가짜 CORE).

게이트 플로우 + 주행 화면 마운트 + 카메라 프레임 + 속도 프리셋을 태블릿 뷰포트에서
기계로 판정한다. ROSY_RUN_BROWSER_TESTS=1 옵트인.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
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
        page.request.post(f"{base_url}/__test__/recordings", data={"blocker": None, "reset": True})
        try:
            _enter_drive(page, base_url)
            assert page.locator("[data-evidence-record]").inner_text().strip() == "화면 녹화"
            page.wait_for_function("!document.querySelector('[data-robot-record]').disabled")
            assert page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") <= 0
            page.click("[data-robot-record]")
            page.wait_for_function("document.querySelector('[data-robot-record]').textContent.includes('중지')")
            page.wait_for_selector("[data-drive-fact=recording]:not([hidden])")
            assert "녹화 0:01 / 10:00" in page.inner_text("[data-drive-fact=recording]")
            assert page.request.get(f"{base_url}/__test__/recordings").json()["log"] == ["start"]
            page.click("[data-recordings-open]")
            row = page.locator(f"[data-recordings-sheet] [data-recording-id='{ROBOT_RECORDING_ID}']")
            row.wait_for()
            assert row.locator("[data-recording-fetch]").is_disabled()          # 녹화 중에는 받지 않는다
            assert "녹화 중에는" in page.inner_text("[data-recordings-notice]")
            page.click("[data-robot-record]")
            page.wait_for_function("document.querySelector('[data-robot-record]').textContent.trim() === '로봇 녹화'")
            page.request.post(f"{base_url}/__test__/recordings", data={"blocker": "ROBOT_MOVING"})
            page.click("[data-recordings-refresh]")
            page.wait_for_function("document.querySelector('[data-recordings-notice]').textContent.includes('멈춘 뒤')")
            assert row.locator("[data-recording-fetch]").is_disabled()
            page.request.post(f"{base_url}/__test__/recordings", data={"blocker": None})
            page.click("[data-recordings-refresh]")
            page.wait_for_function("!document.querySelector('[data-recording-fetch]').disabled")
            sheet = page.locator("[data-recordings-sheet]").bounding_box()
            assert sheet["x"] >= 0 and sheet["x"] + sheet["width"] <= viewport[0] + 1, sheet
            with page.expect_download() as download:
                row.locator("[data-recording-fetch]").click()
            assert download.value.suggested_filename == f"{ROBOT_RECORDING_ID}.tar"
            row.locator("[data-recording-status]").wait_for()
            assert "받음" in row.locator("[data-recording-status]").inner_text()
            log = page.request.get(f"{base_url}/__test__/recordings").json()["log"]
            assert log == ["start", "stop", "archive"], log
            page.click("[data-recordings-close]")
            assert page.locator("[data-recordings-sheet]").count() == 0
        finally:
            browser.close()
    assert errors == [], errors


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_leaving_drive_stops_the_robot_recording_this_device_started(tablet_page):
    base_url, page, errors = tablet_page
    page.request.post(f"{base_url}/__test__/recordings", data={"blocker": None, "reset": True})
    _enter_drive(page, base_url)
    page.wait_for_function("!document.querySelector('[data-robot-record]').disabled")
    page.click("[data-robot-record]")
    page.wait_for_function("document.querySelector('[data-robot-record]').textContent.includes('중지')")
    page.click("[data-drive-exit]")
    page.wait_for_timeout(500)
    assert page.request.get(f"{base_url}/__test__/recordings").json()["log"] == ["start", "stop"]
    assert errors == [], errors