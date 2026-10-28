"""Pilot connection lobby: discovery, recent names, retry and observation evidence."""

import json
import os
from pathlib import Path

import pytest
from browser_harness import browser_tests_enabled

playwright_sync = pytest.importorskip("playwright.sync_api", reason="Playwright 없음")


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


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
@pytest.mark.parametrize("width,height", [(2000, 1200), (390, 844), (320, 568)])
def test_lobby_long_robot_names_keep_text_and_actions_inside_panel(tablet_page, width, height):
    base_url, page, errors = tablet_page
    page.set_viewport_size({"width": width, "height": height})
    hostname = "r" * 63  # A valid maximum-length DNS label.
    label = "robot-" + "x" * 90
    page.add_init_script("localStorage.setItem('rosy.pilot.recent', JSON.stringify("
                         f"[{{host: location.host, label: {json.dumps(label)}}}]));")
    page.route("**/api/v1/site/rooms", lambda route: route.fulfill(json={"rooms": [
        {"hostname": hostname, "port": 8080, "kind": "robot",
         "url": f"http://{hostname}.local:8080/pilot/#join"}]}))
    page.goto(f"{base_url}/pilot")
    recent = page.locator("[data-recent-connect]")
    room = page.locator("[data-lobby-room]")
    playwright_sync.expect(recent).to_have_text(label)
    playwright_sync.expect(room).to_have_text(hostname)
    if output := os.environ.get("ROSY_SHOT_DIR"):
        Path(output).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(output) / f"pilot_long_names_{width}x{height}.png"), full_page=True)
    panel = page.locator("[data-screen=connect]").bounding_box()
    for control in (recent, page.locator("[data-recent-remove]"), room):
        box = control.bounding_box()
        assert box and panel["x"] - 1 <= box["x"], (width, box, panel)
        assert box["x"] + box["width"] <= panel["x"] + panel["width"] + 1, (width, box, panel)
        assert control.evaluate("el => el.scrollWidth <= el.clientWidth + 1"), (width, control.text_content())
    remove = page.locator("[data-recent-remove]")
    remove.focus()
    page.keyboard.press("Enter")
    playwright_sync.expect(recent).to_have_count(0)
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
                # refreshLobby appends retry after the independent self-state read settles.
                page.locator("[data-lobby-retry]").wait_for(state="visible")
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
                if state == "empty":
                    status_box = page.locator("[data-lobby-self]").bounding_box()
                    summary_box = page.get_by_text("같은 LAN에서 발견한 다른 로봇이 없습니다").bounding_box()
                    assert status_box["y"] + status_box["height"] <= summary_box["y"]
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


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
def test_lobby_shows_self_driving_tag_when_manual_and_moving(tablet_page):
    """Manual movement is explicitly attributed to this robot."""
    base_url, page, errors = tablet_page
    page.route("**/api/v1/site/rooms",
               lambda route: route.fulfill(json={"rooms": []}))
    page.route("**/api/v1/robot/state",
               lambda route: route.fulfill(json={
                   "mode": "MANUAL",
                   "evidence": {"velocity": {"evidence": "fresh"}},
                   "velocity": {"linear": 0.08, "angular": 0.0}}))
    page.goto(f"{base_url}/pilot")
    page.wait_for_selector("form[data-pilot-token-form] ui-field input")
    tag = page.locator("[data-lobby-self]")
    tag.wait_for(state="visible")
    assert tag.inner_text() == "이 로봇 · 운전 중"
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
def test_lobby_self_tag_shows_idle_when_not_driving(tablet_page):
    base_url, page, errors = tablet_page
    page.route("**/api/v1/site/rooms",
               lambda route: route.fulfill(json={"rooms": []}))
    page.route("**/api/v1/robot/state",
               lambda route: route.fulfill(json={
                   "mode": "IDLE", "velocity": {"linear": 0.0, "angular": 0.0},
                   "evidence": {"velocity": {"evidence": "fresh"}}}))
    page.goto(f"{base_url}/pilot")
    page.wait_for_selector("form[data-pilot-token-form] ui-field input")
    tag = page.locator("[data-lobby-self]")
    tag.wait_for(state="visible")
    assert tag.inner_text() == "이 로봇 · 정지 상태"
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
@pytest.mark.parametrize("status,state,word", [
    (503, {}, "속도 연결 끊김"),
    (200, {"mode": "MANUAL", "velocity": {"linear": 0}}, "속도 정보 없음"),
    (200, {"mode": "SAFE_STOP", "safety": {"estop": True},
           "evidence": {"safety": {"evidence": "fresh"}}}, "안전 정지"),
    (200, {"mode": "SAFE_STOP", "safety": {"estop": True}}, "안전 정지 보고 · 안전 상태 확인 불가"),
    (200, {"mode": "NAVIGATION", "velocity": {"linear": 0, "angular": 0.1},
           "evidence": {"velocity": {"evidence": "fresh"}}}, "이동 중"),
    (200, {"mode": "IDLE", "velocity": {"linear": 0, "angular": 0},
           "evidence": {"velocity": {"evidence": "delayed"}}}, "속도 지연"),
    (200, {"mode": "IDLE", "velocity": {"linear": 0, "angular": 0},
           "evidence": {"velocity": {"evidence": "disconnected"}}}, "속도 연결 끊김"),
    (200, {"mode": "IDLE", "velocity": {"linear": 0, "angular": 0},
           "evidence": {"velocity": {"evidence": "unavailable"}}}, "속도 정보 없음"),
    (200, {"mode": "IDLE", "velocity": {"linear": 0, "angular": 0}}, "속도 연결 끊김"),
])
def test_lobby_self_state_never_turns_missing_or_moving_evidence_into_idle(tablet_page, status, state, word):
    base_url, page, errors = tablet_page
    page.route("**/api/v1/site/rooms", lambda route: route.fulfill(json={"rooms": []}))
    page.route("**/api/v1/robot/state", lambda route: route.fulfill(status=status, json=state))
    page.goto(f"{base_url}/pilot")
    tag = page.locator("[data-lobby-self]")
    tag.wait_for(state="visible")
    assert tag.inner_text() == f"이 로봇 · {word}"
    assert page.locator("[data-lobby-retry]").is_visible()
    assert errors == [], errors


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
@pytest.mark.parametrize("stored", ["null", "{}", "[null, 1]", '[{"host":"other.test","label":"다른 로봇"}]',
                                   '[{"host":"other.test","label":null,"token":"legacy-secret"}]'])
def test_recent_metadata_cannot_break_gate_or_offer_another_robot_as_this_origin(tablet_page, stored):
    base_url, page, errors = tablet_page
    page.add_init_script(f"localStorage.setItem('rosy.pilot.recent', {json.dumps(stored)})")
    page.goto(f"{base_url}/pilot")
    page.locator("form[data-pilot-token-form] ui-field input").wait_for(state="visible")
    assert page.locator("[data-recent-connect]").count() == 0
    assert "legacy-secret" not in page.evaluate("localStorage.getItem('rosy.pilot.recent') || ''")
    assert errors == [], errors
