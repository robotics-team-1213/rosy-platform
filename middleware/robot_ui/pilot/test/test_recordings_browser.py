"""Robot recording browser workflows over the shared Pilot fake CORE."""
from pathlib import Path
import os

import pytest
from browser_harness import browser_tests_enabled
from test_pilot_browser import (
    ROBOT_RECORDING_ID, ROBOT_RECORD_STOP, _click_tool, _default_controls,
    _enter_drive, _enter_recording_drive, _eventually, _open_sheet, _recordings,
    _settled_polls, playwright_sync,
)


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
