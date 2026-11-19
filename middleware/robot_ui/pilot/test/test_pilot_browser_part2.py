from __future__ import annotations

from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from test_pilot_browser import (
    os, json, Path, pytest, browser_tests_enabled, playwright_sync, dev_server,
    _click_tool, _enter_drive,
)


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
        assert len(buttons) == 2, action_boxes
        assert max(button["width"] for button in buttons) - min(button["width"] for button in buttons) <= 1, action_boxes
        assert all(button["height"] >= 44 for button in buttons), action_boxes
        assert abs(buttons[0]["left"] - action_boxes["track"]["left"]) <= 1, action_boxes
        assert abs(buttons[-1]["right"] - action_boxes["track"]["right"]) <= 1, action_boxes
        assert abs(buttons[0]["top"] - buttons[1]["top"]) <= 1, action_boxes
        assert all(box["bottom"] <= controls["viewport"] for box in controls["boxes"]
                   if "pedal" in box["selector"] or "stick" in box["selector"]), controls
        if viewport[0] == 390:
            assert cue is None
            assert all(box["bottom"] <= controls["viewport"] + 1 for box in controls["boxes"]), controls
            assert scrolled["page"] == 0, scrolled
        else:
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
    page.wait_for_function("document.querySelector('[data-intent-steer]').textContent.includes('오른쪽')")
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
    page.screenshot(path=str(Path(os.environ.get("ROSY_SHOT_DIR") or Path(os.environ.get("ROSY_SCRATCH") or os.environ.get("TEMP") or "/tmp")) / "pilot-intent-tracking.png"))
    assert got["steer"] == "오른쪽 18°/s" and got["state"] == "tracking"
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
    # 진행은 이 화면이 수동 모드를 잡은 뒤에만 받는다(drive.js `!engaged`). 그 전의 누름은 버려지고 다시 오지 않는다.
    # 조작 응답 표시는 잡은 뒤의 hold 루프만 쓰므로, 그 글이 뜬 것이 잡았다는 화면 증거다.
    page.wait_for_function(ENGAGED)
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
ENGAGED = "document.querySelector('[data-drive-fact=latency]').textContent.startsWith('조작 응답 ')"


@pytest.mark.skipif(not browser_tests_enabled(),
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_go_pressed_before_manual_mode_is_held_starts_nothing(tablet_page):
    """수동 모드를 잡기 전의 진행 누름은 CORE 에 닿지 않는다. 잡은 뒤의 누름만 차선 추종을 켠다."""
    base_url, page, errors = tablet_page
    held = []

    def mode(route):
        if route.request.method == "POST" and not held:
            held.append(route)
        else:
            route.continue_()
    page.route("**/api/v1/mode", mode)
    _enter_drive(page, base_url)
    page.click("[data-drive-auto]")
    page.wait_for_selector("[data-drive-go]", state="visible")
    dev_server.LINE_FOLLOW_MODE_LOG.clear()
    page.dispatch_event("[data-drive-go]", "pointerdown")
    assert not page.evaluate(GO_ACTIVE)
    page.dispatch_event("[data-drive-go]", "pointerup")
    assert len(held) == 1 and not page.evaluate(ENGAGED)
    held[0].continue_()
    page.wait_for_function(ENGAGED)
    assert dev_server.LINE_FOLLOW_MODE_LOG == []
    page.dispatch_event("[data-drive-go]", "pointerdown")
    page.wait_for_function(GO_ACTIVE)
    page.dispatch_event("[data-drive-go]", "pointerup")
    _wait_for_modes(page, "CAMERA_LINE", "OFF")
    playwright_sync.expect(page.locator("[data-drive-motion]")).to_have_text("대기")  # back at idle: nothing in flight
    # Exactly the one held press. An early press that leaked to CORE late would add a second pair.
    assert dev_server.LINE_FOLLOW_MODE_LOG == ["CAMERA_LINE", "OFF"], dev_server.LINE_FOLLOW_MODE_LOG
    assert errors == [], errors


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
    # 진행 표시는 멈추는 중에 이미 꺼진다. 동작 표시는 CORE 가 수동을 돌려준 뒤(idle)에 대기로 돌아온다.
    playwright_sync.expect(page.locator("[data-drive-motion]")).to_have_text("대기")
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
    assert page.locator("[data-drive-scroll-cue]").is_visible() == (width == 320)
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
    page.wait_for_function("document.querySelectorAll('[data-drive-tools-panel] details.pilot-models').length === 2")
    assert panel.is_visible()
    assert page.locator("[data-drive-tools]").get_attribute("aria-expanded") == "true"
    assert page.locator("[data-drive-tools-panel] [data-drive-fit]").count() == 1
    assert page.locator("[data-drive-tools-panel] [data-drive-fill]").count() == 1
    assert page.locator("[data-drive-tools-panel] details.pilot-models[open]").count() == 1
    bounds = panel.bounding_box()
    assert bounds["y"] >= 0 and bounds["y"] + bounds["height"] <= 844
    if output:
        page.screenshot(path=str(Path(output) / "pilot-tools-390x844.png"))
    scroll = panel.evaluate("node => { node.scrollTop = node.scrollHeight; return {top: node.scrollTop, height: node.scrollHeight, visible: node.clientHeight}; }")
    assert scroll["height"] > scroll["visible"] and scroll["top"] > 0, scroll
    if output:
        page.screenshot(path=str(Path(output) / "pilot-tools-scroll-390x844.png"))
    page.set_viewport_size({"width": 500, "height": 844})
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
    shots = Path(os.environ.get("ROSY_SHOT_DIR") or Path(os.environ.get("ROSY_SCRATCH") or os.environ.get("TEMP") or "/tmp") / "calibration-mode")
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
                                .every((b) => b.disabled && b.getAttribute("reason") === "위 사유")""")
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


# The fake follows the real SIM runtime (pilot_sim.runtime.snapshot/submit, command_owner):
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
    shots = Path(os.environ.get("ROSY_SHOT_DIR") or Path(os.environ.get("ROSY_SCRATCH") or os.environ.get("TEMP") or "/tmp") / "d411-c")
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
                shots = Path(os.environ.get("ROSY_SHOT_DIR") or Path(os.environ.get("ROSY_SCRATCH") or os.environ.get("TEMP") or "/tmp") / "d411-c")
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
    # The first failure already shows this text, so it cannot mark the end of this attempt. The attempt ends when
    # start() swaps in a fresh screen: measuring before that reads the old button while it is being detached.
    shown = retry.element_handle()
    retry.click()
    page.wait_for_function("shown => !shown.isConnected", arg=shown)
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
