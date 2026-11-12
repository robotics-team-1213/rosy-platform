"""D-131 1단계 — 군집 제어 오버레이의 브라우저 렌더 계약 (옵트인).

ROSY_RUN_BROWSER_TESTS=1 로 실행한다. 가짜 API 응답(활성 대형 + 중재 대기 +
릴레이 단절 팔로워)으로 콘솔을 띄워, 후단이 주는 상태가 실제로 그려지는지
단언한다. mutation-proven: drawFormationOverlay/drawMediation 호출을 지우면
이 시험은 적색이어야 한다(test/ AGENTS 규정).
"""

from __future__ import annotations

import os
import json
from pathlib import Path
from console_browser_site import ROOT, WEB, WEB_COMMON, console_url  # noqa: F401
from urllib.parse import urlparse

import pytest
from browser_harness import browser_tests_enabled
from fleet.server.static_routes import CONSOLE_ASSETS

pytestmark = pytest.mark.skipif(
    not browser_tests_enabled(),
    reason="set ROSY_RUN_BROWSER_TESTS=1 to run the optional Chromium regression",
)

from browser_harness import (  # noqa: E402
    DECLINE_CONFIRM,
    accept_confirm,
    open_page,
    save_temp_screenshot,
)

MAP_GRID = {
    "map_id": "mock:1", "width": 40, "height": 40, "resolution": 0.05,
    "origin": {"x": 0.0, "y": 0.0, "yaw": 0.0}, "data": [20] * (40 * 40),
}


def _robot(robot_id: str, pose: dict, **extra) -> dict:
    row = {
        "robot_id": robot_id, "online": True, "goal": None, "queued": None,
        "yielding": None, "error": None,
        # A Nav2 robot reports its map; the console draws only map poses (field check 2026-10-10).
        "state": {"robot_id": robot_id, "mode": "NAVIGATION", "navigation": "NAVIGATING", "map_id": "map",
                  "pose": pose, "localization": {"state": "LOCALIZED", "pose_frame": "map"},
                  "battery": {"percent": 90}, "safety": {"estop": False}},
    }
    row.update(extra)
    return row


SNAPSHOT = {
    "fleet": {"name": "site", "online": 3, "total": 3},
    "robots": [
        _robot("rosy_01", {"x": 1.0, "y": 1.0, "yaw": 0.0},
               goal={"x": 1.5, "y": 1.0, "yaw": 0.0}),
        _robot("rosy_02", {"x": 0.45, "y": 1.0, "yaw": 0.0}),
        _robot("rosy_03", {"x": 0.45, "y": 0.4, "yaw": 0.0},
               queued={"x": 1.2, "y": 0.4, "yaw": 0.0, "blocked_by": "rosy_02",
                       "waiting_on": ["rosy_02"], "reason": "ROUTE_CONFLICT"}),
    ],
    "ts": 0.0,
}

FORMATION = {
    "active": True, "state": "RUNNING", "leader": "rosy_01",
    "formation": "COLUMN", "spacing": 0.6,
    "assignment": {"rosy_02": {"distance": 0.6, "lateral": 0.0},
                   "rosy_03": {"distance": 1.2, "lateral": 0.0}},
    "reason": None, "pending_triggers": [],
    "stream_evidence": {
        "rosy_01": {"state": "fresh", "age_s": 0.1, "reason": "sample_within_limit",
                    "stale_after_s": 1.0, "source": "leader_rx"},
        "rosy_02": {"state": "fresh", "age_s": 0.1, "reason": "sample_within_limit",
                    "stale_after_s": 1.0, "source": "follower_tx"},
        "rosy_03": {"state": "disconnected", "age_s": None, "reason": "transport_down",
                    "stale_after_s": 1.0, "source": "follower_tx"},
    },
    "relay": {"paused": False, "leader_rx_hz": 9.8, "leader_age_s": 0.1,
              "leader_last_error": None,
              "follower_tx_hz": {"rosy_02": 4.8, "rosy_03": 0.0},
              "follower_connected": {"rosy_02": True, "rosy_03": False}},
}

API = {
    "/api/fleet/state": SNAPSHOT,
    "/api/fleet/map": MAP_GRID,
    "/api/fleet/formation": FORMATION,
}


def test_console_fixture_serves_registered_assets(console_url):
    from urllib.request import urlopen

    base = console_url.rsplit("/", 1)[0]
    for name, (relative, _) in CONSOLE_ASSETS.items():
        with urlopen(f"{base}/console/assets/{name}", timeout=5) as response:
            assert response.read() == (WEB / relative).read_bytes(), name


def test_the_console_renders_what_swarm_control_says(console_url):
    from playwright.sync_api import sync_playwright

    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        # D-153 G2 선언 뷰포트 = 사이트 PC 1920×1080(회차 11부터 LOCAL에서 증거화).
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.on("pageerror", lambda exc: errors.append(str(exc)))

        def serve_api(route):
            path = urlparse(route.request.url).path
            body = API.get(path)
            # 세션 폴백은 _open_console 과 같은 모양이다 — 이것이 없으면 콘솔이
            # 잠긴 채로 폴링을 시작하지 않아 지도·명단이 영영 로딩에 남는다
            # (2026-10-01 세션 게이트 도입 뒤 이 시험만 인라인 라우트를 썼다).
            if body is None and path == "/api/fleet/session":
                body = {"principal_id": "test-operator", "role": "operator"}
            if body is None:
                route.fulfill(status=404, json={"detail": "no such api"})
                return
            route.fulfill(status=200, json=body)

        page.route("**/api/**", serve_api)
        page.goto(console_url, wait_until="networkidle")
        # 슬롯 고스트: COLUMN 에서 두 팔로워의 자리가 그려진다.
        page.wait_for_function("() => (window.__swarmOverlay?.slots || 0) === 2", timeout=8000)
        # 중재: rosy_03 의 대기 미션은 rosy_02 로의 점선이 된다.
        page.wait_for_function("() => (window.__swarmOverlay?.mediation || 0) >= 1", timeout=8000)

        roster = page.inner_text("#roster")
        assert "끊김" in roster, "연결이 끊긴 팔로워의 증거 태그가 없다"
        assert "지연" not in roster, "정상 스트림(4.8 Hz)에 지연 태그가 붙었다 — 정상은 무색이어야 한다"
        page.locator('[data-context-tab="tools"]').click()
        assert "0.60 m" in page.inner_text("#formation-detail"), "슬롯 요약이 사라졌다"
        page.locator('[data-context-tab="status"]').click()
        # D-651: exceptions lead the summary; actions await explicit selection.
        assert page.locator('#roster article').first.get_attribute('data-robot-id') == 'rosy_03'
        assert page.locator('#roster article').count() == 3
        assert page.locator('#robot-workspace article').count() == 0
        assert page.locator('#robot-workspace-empty').is_visible()
        save_temp_screenshot(page, "fleet_console_exception_first.png")
        _open_cards(page)
        # D-82/§7.3 색 예산 — 색칠은 문제 있는 한 대(rosy_03: 끊김 crit + 대기
        # warn)에만 몰리고 정상 로봇은 무색이다("one coloured row").
        per_robot = {}
        for robot_id in ('rosy_01', 'rosy_02', 'rosy_03'):
            _open_cards(page, robot_id)
            per_robot[robot_id] = page.locator(
                '#robot-workspace ui-tag[status=crit], #robot-workspace ui-tag[status=warn]').count()
        assert per_robot == {"rosy_01": 0, "rosy_02": 0, "rosy_03": 2}

        assert not errors, f"페이지 오류: {errors}"
        save_temp_screenshot(page, "fleet_console_overlay.png")
        browser.close()


def test_normal_robot_is_reachable_from_the_exception_first_roster(console_url):
    from playwright.sync_api import sync_playwright

    robot = _robot("rosy_01", {"x": 1.0, "y": 1.0, "yaw": 0.0})
    api = {
        "/api/fleet/state": {"fleet": {"name": "site", "online": 1, "total": 1},
                             "robots": [robot], "ts": 0.0},
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": {"active": False, "state": "IDLE"},
    }
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, api)
        page.goto(console_url, wait_until="networkidle")
        summary = page.locator('#roster article[data-robot-id="rosy_01"]')
        assert 'rosy_01' in summary.inner_text()
        assert summary.locator('[data-fact="battery"]').count() == 1
        choose = summary.locator('[data-select-robot-id="rosy_01"]')
        choose.focus()
        page.keyboard.press('Enter')
        card = page.locator('#robot-workspace article[data-robot-id="rosy_01"]')
        assert card.locator('[data-goal-robot-id="rosy_01"]').is_visible()
        assert card.locator('[data-map-recording]').is_visible()
        assert page.locator('#robot-choice').input_value() == 'rosy_01'
        page.wait_for_timeout(1500)
        assert card.is_visible()
        page.locator('#robot-choice').select_option('')
        assert page.locator('#robot-workspace article').count() == 0
        assert page.locator('#robot-workspace-empty').is_visible()
        assert not errors
        browser.close()


@pytest.mark.parametrize("supported", [False, True])
def test_motion_buttons_follow_live_robot_capabilities(console_url, supported):
    from playwright.sync_api import sync_playwright

    caps = {"navigation": {"goal_navigation": supported},
            "swarm": {"lead": supported, "follow": supported},
            "runtime": {"mode": "hardware" if supported else "motor"}}
    robots = [_robot(name, {"x": x, "y": 1.0, "yaw": 0.0}, capabilities=caps)
              for name, x in [("robot-a", 1.0), ("robot-b", 0.5)]]
    api = {"/api/fleet/state": {"fleet": {"name": "site", "online": 2, "total": 2},
                                "robots": robots, "ts": 0.0},
           "/api/fleet/map": MAP_GRID,
           "/api/fleet/formation": {"active": False, "state": "IDLE"}}
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, api)
        page.goto(console_url, wait_until="networkidle")
        for robot_id in ("robot-a", "robot-b"):
            _open_cards(page, robot_id)
            goal = page.locator("#robot-workspace ui-button[data-goal-robot-id]")
            assert goal.count() == 1
            assert goal.get_attribute("disabled") == (None if supported else "")
            if not supported:
                assert goal.get_attribute("reason") == "수동 주행만 지원"
        page.locator('[data-context-tab="tools"]').click()
        page.locator(".formation-form-wrap > summary").click()
        page.locator("#formation-leader").select_option("robot-a")
        page.locator('#formation-members input[value="robot-b"]').check()
        arm = page.locator("#formation-start")
        assert arm.get_attribute("disabled") == (None if supported else "")
        if not supported:
            assert "수동 주행만 지원" in page.inner_text("#formation-why")
        assert not errors
        browser.close()


def _open_cards(page, robot_id=None):
    """Select the robot whose task and evidence are inspected in the workspace."""
    page.wait_for_function("() => document.querySelectorAll('#roster article').length > 0")
    if robot_id is None:
        robot_id = page.locator('#robot-choice option[value]:not([value=""])').evaluate_all(
            "options => options.some(option => option.value === 'rosy_01') ? 'rosy_01' : options[0].value")
    page.locator('#robot-choice').select_option(robot_id)
    page.locator('#robot-workspace article').wait_for(state='visible')
    page.evaluate("() => document.activeElement?.blur()")


def _open_token_access(page):
    """Open the operator connection fold before using its token controls."""
    if page.locator("#topbar-extra").is_hidden():
        page.locator("#topbar-more").click()
    if not page.locator("#token-access").evaluate("node => node.open"):
        page.locator("#token-access > summary").click()
    page.locator("#console-token").wait_for(state="visible")


def _open_console(playwright, api, posts=None, init_script=""):
    """D-153 회차4 — 상태별 Fleet G2 셀. api 값은 (status, body) 또는 body."""
    browser, page, errors = open_page(playwright, 1920, 1080)

    def serve_api(route):
        path = urlparse(route.request.url).path
        if posts is not None:
            posts.append((route.request.method, path))
        entry = api.get(path)
        if entry is None and path == "/api/fleet/session" and path not in api:
            entry = {"principal_id": "test-operator", "role": "operator"}
        if entry is None:
            route.fulfill(status=404, json={"detail": "no such api"})
            return
        status, body = entry if isinstance(entry, tuple) else (200, entry)
        route.fulfill(status=status, json=body)

    page.route("**/api/**", serve_api)
    if init_script:
        page.add_init_script(init_script)
    return browser, page, errors


def test_fleet_labels_are_rendered_as_text(console_url):
    """Identifiers and device-reported faults must never create markup in the roster."""
    from playwright.sync_api import sync_playwright

    marker = "<img src=x onerror=alert(1)>"
    robot = _robot(marker, {"x": 1.0, "y": 1.0, "yaw": 0.0})
    robot["state"]["capabilities_degraded"] = [marker]
    snapshot = {
        "fleet": {"name": "site", "online": 1, "total": 1},
        "robots": [robot],
        "signals": {marker: {"signal_id": marker, "mode": "manual", "online": True, "lamps": {}}},
        "ts": 0.0,
    }
    api = {"/api/fleet/state": snapshot, "/api/fleet/map": MAP_GRID,
           "/api/fleet/formation": {"active": False, "state": "IDLE"}}
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, api)
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function("() => document.querySelectorAll('#roster article').length === 1")
        assert page.locator("#roster b").first.text_content() == marker
        assert page.locator("#warning-list b").first.text_content() == marker
        page.locator('[data-context-tab="tools"]').click()
        assert page.locator("#signal-cards b").first.text_content() == marker
        assert page.locator("#roster img, #warning-list img, #signal-cards img").count() == 0
        assert not errors
        browser.close()


def test_fleet_keyboard_can_skip_to_named_main_content(console_url):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, API)
        page.goto(console_url, wait_until="networkidle")
        page.keyboard.press("Tab")
        assert page.locator(":focus").get_attribute("href") == "#fleet-main"
        page.keyboard.press("Enter")
        assert page.locator(":focus").get_attribute("id") == "fleet-main"
        assert page.get_by_role("heading", level=1).count() == 1
        assert not errors
        browser.close()


EMPTY_SNAPSHOT = {
    "fleet": {"name": "site", "online": 0, "total": 0},
    "robots": [],
    "ts": 0.0,
}


def test_empty_fleet_renders_zero_online_and_no_ghosts(console_url):
    from playwright.sync_api import sync_playwright

    api = {
        "/api/fleet/state": EMPTY_SNAPSHOT,
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": {"active": False, "state": "IDLE"},
    }
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, api)
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function(
            "() => document.getElementById('online-pill')?.textContent === '0/0'"
        )
        assert "rosy" not in page.inner_text("#roster")
        assert "등록된 로봇이 없습니다" in page.inner_text("#roster")
        assert (page.evaluate("window.__swarmOverlay?.slots || 0") == 0), (
            "비활성 대형에 오버레이가 남아 있다 — 장식이 아니라 현재 작업 대상만 보인다(D-131)"
        )
        assert not errors
        save_temp_screenshot(page, "fleet_console_empty.png")
        browser.close()


def test_gather_failure_names_itself_on_the_pill(console_url):
    from playwright.sync_api import sync_playwright

    api = {
        "/api/fleet/state": (500, {"detail": "gather failed"}),
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": {"active": False, "state": "IDLE"},
    }
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, api)
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function(
            "() => document.getElementById('online-pill')?.textContent"
            " === 'Fleet 연결 끊김'"
        )
        assert page.locator("#online-pill").get_attribute("status") == "crit"
        assert "Fleet 상태를 확인할 수 없습니다" in page.inner_text("#roster")
        assert not errors
        save_temp_screenshot(page, "fleet_console_gather-error.png")
        browser.close()


@pytest.mark.parametrize("width", [320, 390])
@pytest.mark.parametrize("scenario", ["empty", "gather-error"])
def test_mobile_fleet_empty_and_failure_keep_next_step_visible(console_url, width, scenario):
    from playwright.sync_api import sync_playwright

    api = {
        "/api/fleet/state": EMPTY_SNAPSHOT if scenario == "empty" else (500, {"detail": "gather failed"}),
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": {"active": False, "state": "IDLE"},
    }
    expected = "등록된 로봇이 없습니다" if scenario == "empty" else "Fleet 상태를 확인할 수 없습니다"
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, api)
        page.set_viewport_size({"width": width, "height": 844})
        page.goto(console_url, wait_until="networkidle")
        page.get_by_text(expected).first.wait_for()
        stop = page.locator("#estop").bounding_box()
        assert stop and stop["width"] > 0 and stop["x"] + stop["width"] <= width
        assert stop["y"] + stop["height"] <= 844
        assert page.evaluate("document.documentElement.scrollWidth - innerWidth") == 0
        assert errors == []
        save_temp_screenshot(page, f"fleet_console_{scenario}_{width}.png")
        browser.close()


@pytest.mark.parametrize("width,height", [(1920, 1080), (390, 844), (320, 568)])
def test_slow_initial_gather_does_not_spawn_overlapping_polls(console_url, width, height):
    """The loading state keeps one state request in flight until it resolves."""
    from playwright.sync_api import sync_playwright

    delayed_state = """(() => {
      const originalFetch = window.fetch.bind(window);
      window.__stateCalls = 0;
      window.fetch = (input, options) => {
        if (new URL(String(input), location.origin).pathname === '/api/fleet/state') {
          window.__stateCalls += 1;
          if (window.__stateCalls === 1) {
            return new Promise(resolve => {
              window.__releaseState = snapshot => resolve(new Response(JSON.stringify(snapshot), {
                status: 200, headers: {'Content-Type': 'application/json'}
              }));
            });
          }
        }
        return originalFetch(input, options);
      };
    })();"""
    api = {
        "/api/fleet/state": SNAPSHOT,
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": {"active": False, "state": "IDLE"},
    }
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, api, init_script=delayed_state)
        page.set_viewport_size({"width": width, "height": height})
        page.goto(console_url, wait_until="domcontentloaded")
        page.wait_for_function("() => window.__stateCalls === 1")
        assert "로봇 목록 불러오는 중" in page.inner_text("#roster")
        page.wait_for_timeout(1400)
        assert page.evaluate("window.__stateCalls") == 1
        assert "로봇 목록 불러오는 중" in page.inner_text("#roster")
        assert page.locator(".queues-panel").is_hidden()
        for state in ("loading", "recovered"):
            if state == "recovered":
                page.evaluate("snapshot => window.__releaseState(snapshot)", SNAPSHOT)
                page.wait_for_function("() => document.querySelector('#online-pill')?.textContent === '3/3'")
                assert "rosy_03" in page.inner_text("#roster")
            stop = page.locator("#estop").bounding_box()
            assert stop and stop["width"] > 0 and stop["y"] + stop["height"] <= height
            map_panel = page.locator('section[aria-labelledby="map-heading"]').bounding_box()
            roster_panel = page.locator('section[aria-labelledby="roster-heading"]').bounding_box()
            assert abs(map_panel["width"] / roster_panel["width"] - (2 if width >= 1024 else 1)) <= 0.03  # D-629: map 2 : rail 1 from 64rem
            if width < 480:
                assert abs(map_panel["x"] - roster_panel["x"]) <= 1
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            save_temp_screenshot(page, f"fleet_console_slow_{state}_{width}.png")
        assert not errors
        browser.close()


@pytest.mark.parametrize("width,height", [(1920, 1080), (390, 844), (320, 568)])
def test_gather_loss_removes_last_known_robot_position(console_url, width, height):
    """A failed refresh must not present the last snapshot as a live position."""
    from playwright.sync_api import sync_playwright

    robot = _robot("rosy_01", {"x": 1.0, "y": 1.0, "yaw": 0.0})
    api = {
        "/api/fleet/state": {"fleet": {"name": "site", "online": 1, "total": 1},
                             "robots": [robot]},
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": {"active": False, "state": "IDLE"},
    }
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, api)
        page.set_viewport_size({"width": width, "height": height})
        page.goto(console_url, wait_until="networkidle")
        _open_cards(page)
        page.wait_for_function("() => document.querySelector('#robot-workspace article')?.textContent.includes('1.00')")
        api["/api/fleet/state"] = (500, {"detail": "gather failed"})
        page.wait_for_function("() => document.querySelector('#online-pill')?.textContent === 'Fleet 연결 끊김'"
                               " && document.querySelector('#robot-workspace article')?.textContent.includes('상태 확인 불가')")
        assert not errors
        assert "1.00" not in page.inner_text("#robot-workspace")
        assert "상태 확인 불가" in page.inner_text("#robot-workspace")
        assert "로봇 위치 확인 불가" in page.locator("#map-tag").text_content()
        assert page.locator('#roster [data-localization]').inner_text() == "위치 미확인"
        assert "로봇 위치 확인 불가" in page.locator("#map-canvas").get_attribute("aria-label")
        assert page.locator("#robot-workspace article [data-goal-robot-id]").is_disabled()
        assert page.locator("#online-pill").evaluate("node => node.scrollWidth <= node.clientWidth")
        for state in ("lost", "recovered"):
            if state == "recovered":
                api["/api/fleet/state"] = {"fleet": {"name": "site", "online": 1, "total": 1},
                                           "robots": [robot]}
                page.wait_for_function("() => document.querySelector('#robot-workspace article')?.textContent.includes('1.00')")
                assert "로봇 위치 확인 불가" not in page.locator("#map-tag").text_content()
            stop = page.locator("#estop").bounding_box()
            assert stop and stop["width"] > 0 and stop["y"] + stop["height"] <= height
            map_panel = page.locator('section[aria-labelledby="map-heading"]').bounding_box()
            roster_panel = page.locator('section[aria-labelledby="roster-heading"]').bounding_box()
            assert abs(map_panel["width"] / roster_panel["width"] - (2 if width >= 1024 else 1)) <= 0.03  # D-629: map 2 : rail 1 from 64rem
            if width < 480:
                assert abs(map_panel["x"] - roster_panel["x"]) <= 1
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            save_temp_screenshot(page, f"fleet_console_gather_{state}_{width}.png")
        assert not errors
        browser.close()


DECLINE_ESTOP_CONFIRM = DECLINE_CONFIRM


@pytest.mark.parametrize("page_file,width,height", [
    ("index.html", 1920, 1080), ("index.html", 390, 844), ("index.html", 320, 568),
    ("install.html", 1920, 1080), ("install.html", 390, 844), ("install.html", 320, 568),
])
def test_fleet_estop_fires_on_one_click_without_any_dialog(console_url, page_file, width, height):
    """D-414 — 전체 정지는 확인 없이 한 번의 누름으로 즉시 나간다(D-92a 좁힘).

    비상 정지는 비상 출구다: 확인 대화상자는 마찰이고, 거절 경로는 사고다.
    대화상자가 열리지 않는 것까지 확인한다(window.confirm 스텁이 한 번도
    불리지 않으면 통과).
    """
    from playwright.sync_api import sync_playwright, expect

    posts: list[str] = []
    api = dict(API)
    api["/api/fleet/estop"] = {"stopped": 3, "total": 3, "robots": []}
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, api, posts=posts, init_script=DECLINE_CONFIRM +
            "sessionStorage.setItem('rosy-console-token','operator-token');")
        page.set_viewport_size({"width": width, "height": height})
        page.goto(console_url.replace("index.html", page_file), wait_until="networkidle")
        page.wait_for_function(
            "() => document.querySelector('#user-role')?.textContent.includes('운영자')", timeout=3000)
        page.locator("#estop").click()
        feedback = page.locator("#estop-feedback")
        expect(feedback).to_contain_text("정지 요청 응답: 3/3 · 물리 정지 미확인")
        box = feedback.bounding_box()
        assert box and box["y"] >= 0 and box["y"] + box["height"] <= height
        edges = page.locator("main").evaluate("""main => {
            const box = main.getBoundingClientRect(), style = getComputedStyle(main);
            return [box.left + parseFloat(style.paddingLeft), box.right - parseFloat(style.paddingRight)];
        }""")
        assert abs(box["x"] - edges[0]) < 1
        assert abs(box["x"] + box["width"] - edges[1]) < 1
        if page_file == "index.html":
            assert page.locator("#console-workflow").count() == 0  # D-488
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        save_temp_screenshot(page, f"fleet_estop_result_{page_file[:-5]}_{width}.png")
        assert any(path == "/api/fleet/estop" for _method, path in posts), posts
        assert page.evaluate("() => window.__confirms.length") == 0
        assert not errors
        browser.close()


@pytest.mark.parametrize("page_file", ["index.html", "install.html"])
@pytest.mark.parametrize("response,expected", [
    ({"stopped": 1, "total": 3, "robots": [
        {"robot_id": "rosy_02", "stopped": False, "error": {"code": "CONNECT_ERROR"}}]},
     "정지 요청 응답: 1/3 · 물리 정지 미확인"),
    ((503, {"detail": {"code": "SERVER_UNAVAILABLE"}}), "비상 정지 결과 확인 불가"),
])
def test_fleet_estop_partial_and_unknown_are_visible_on_phone(console_url, page_file, response, expected):
    from playwright.sync_api import sync_playwright, expect

    api = {**API, "/api/fleet/estop": response}
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, api, init_script=DECLINE_CONFIRM +
            "sessionStorage.setItem('rosy-console-token','operator-token');")
        page.set_viewport_size({"width": 320, "height": 568})
        page.goto(console_url.replace("index.html", page_file), wait_until="networkidle")
        page.locator("#estop").click()
        feedback = page.locator("#estop-feedback")
        expect(feedback).to_contain_text(expected)
        assert feedback.get_attribute("state") == "error"
        assert "SERVER_UNAVAILABLE" not in feedback.inner_text()
        box = feedback.bounding_box()
        assert box and box["y"] >= 0 and box["y"] + box["height"] <= 568
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        save_temp_screenshot(page, f"fleet_estop_{'partial' if isinstance(response, dict) else 'unknown'}_{page_file[:-5]}_320.png")
        if isinstance(response, dict):
            if page_file == "index.html":
                page.locator('[data-context-tab="inbox"]').click()
            assert "rosy_02" in page.locator("#log").inner_text()
        assert page.evaluate("() => window.__confirms.length") == 0
        assert not errors
        browser.close()


def test_fleet_confirmation_keeps_stop_live_and_rechecks_dispatch_generation(console_url):
    from playwright.sync_api import sync_playwright, expect

    api = {**API, '/api/fleet/dispatch-control': {'generation': 7, 'dispatch_enabled': False,
           'rearm_available': True, 'queued_tasks': 2, 'unresolved_actions': 0},
           '/api/fleet/estop': {'stopped': 3, 'total': 3},
           '/api/fleet/dispatch/rearm': {'generation': 7, 'dispatch_enabled': True}}
    calls = []
    api['/api/fleet/state'] = json.loads(json.dumps(SNAPSHOT))
    robot = api['/api/fleet/state']['robots'][0]
    robot['state']['line_follow'] = {'mode': 'CAMERA_LINE', 'state': 'LOST', 'reason': 'camera_reselection_required'}
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, api, calls,
            init_script="sessionStorage.setItem('rosy-console-token','fixture-token');")
        page.goto(console_url, wait_until='networkidle')
        page.locator('#dispatch-rearm').click()
        dialog = page.locator('dialog.ui-confirm')
        expect(dialog).to_have_count(1, timeout=3000)
        page.locator('#estop').click()
        assert ('POST', '/api/fleet/estop') in calls
        expect(dialog).to_have_count(0)
        page.locator('#dispatch-rearm').click()
        api['/api/fleet/dispatch-control']['generation'] = 8
        page.wait_for_function('() => document.querySelector("#dispatch-control-detail").textContent.includes("8")')
        dialog.locator('ui-button[kind=irreversible]').click()
        page.wait_for_timeout(100)
        assert ('POST', '/api/fleet/dispatch/rearm') not in calls
        robot['state']['line_follow']['mode'] = 'OFF'
        _open_cards(page)
        page.wait_for_function('() => !document.querySelector("ui-button[data-goal-robot-id=rosy_01]").disabled')
        page.locator('ui-button[data-goal-robot-id="rosy_01"]').click()
        page.locator('#map-canvas').press('Enter')
        dialog.wait_for()
        robot['state']['safety']['estop'] = True
        page.wait_for_function('() => !document.querySelector("#robot-workspace article.selected")')
        dialog.locator('ui-button[kind=irreversible]').click()
        page.wait_for_timeout(100)
        assert ('POST', '/api/fleet/robots/rosy_01/goal') not in calls
        robot['state']['safety']['estop'] = False
        robot['state']['line_follow']['mode'] = 'CAMERA_LINE'
        fallback = page.get_by_role('button', name='IR 차선 추종으로 전환…', exact=True)
        fallback.wait_for()
        fallback.click()
        robot['state']['line_follow']['mode'] = 'OFF'
        page.wait_for_function('() => ![...document.querySelectorAll("#robot-workspace ui-button")].some(node=>node.textContent==="IR 차선 추종으로 전환…")')
        dialog.locator('ui-button[kind=irreversible]').click()
        page.wait_for_timeout(100)
        assert ('POST', '/api/fleet/robots/rosy_01/line-follow') not in calls
        held = []
        page.evaluate("""() => {const previous=fetch;window.fetch=(url,options={})=>{if(String(url).endsWith('/api/fleet/dispatch/rearm')){options={...options};delete options.signal;}return previous(url,options);};}""")
        page.route('**/api/fleet/dispatch/rearm', lambda route: held.append(route))
        page.locator('#dispatch-rearm').click()
        dialog.locator('ui-button[kind=irreversible]').click()
        page.wait_for_timeout(100)
        assert len(held) == 1
        page.locator('#cancel-all').click()
        expect(dialog).to_have_count(0)
        assert calls.count(('POST', '/api/fleet/cancel-all')) == 1
        _open_token_access(page)
        page.locator('#console-token').fill('replacement-fixture-token')
        page.locator('#token-save').click()
        page.wait_for_function('() => !document.querySelector("#dispatch-rearm").disabled')
        page.locator('#dispatch-rearm').click()
        dialog.locator('ui-button[kind=irreversible]').click()
        page.wait_for_timeout(100)
        assert len(held) == 2
        held[0].fulfill(status=200, json={'generation': 8, 'dispatch_enabled': True})
        page.wait_for_timeout(100)
        page.locator('#cancel-all').click()
        expect(dialog).to_have_count(0)
        assert calls.count(('POST', '/api/fleet/cancel-all')) == 2
        page.evaluate('() => dispatchEvent(new PageTransitionEvent("pagehide"))')
        snapshot = page.locator('#log').inner_html()
        held[1].fulfill(status=200, json={'generation': 8, 'dispatch_enabled': True})
        page.wait_for_timeout(100)
        expect(dialog).to_have_count(0)
        assert page.locator('#log').inner_html() == snapshot
        assert ('POST', '/api/fleet/dispatch/rearm') not in calls
        assert not errors
        browser.close()


@pytest.mark.parametrize("width,height", [(1920, 1080), (390, 844), (320, 568)])
def test_fleet_cancel_all_runs_at_once_and_logs_each_robot_honestly(console_url, width, height):
    """D-421 / D-540 6 (user decision 2026-10-10) — 전체 주행 취소는 확인 없이 바로 나가고(멈춤), 보낸 대수와
    로봇별 결과, 물리 정지 미확인을 쓴다. 래치(비상 정지)는 걸지 않는다."""
    from playwright.sync_api import sync_playwright

    step_ok = {"ok": True}
    api = {
        "/api/fleet/state": SNAPSHOT,
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": FORMATION,
        "/api/fleet/cancel-all": {
            "cancelled": 1, "total": 3, "evidence": "CORE_REPLY_ONLY",
            "robots": [
                {"robot_id": "rosy_01", "result": "cancelled",
                 "steps": {"swarm": step_ok, "navigation": step_ok, "line_follow": step_ok},
                 "tasks": {"awaiting_core_result": ["t-1"]}},
                {"robot_id": "rosy_02", "result": "unreachable",
                 "steps": {"swarm": {"ok": False, "error": {"reachable": False,
                                                             "code": "ConnectError",
                                                             "message": "gone"}},
                           "navigation": {"ok": False, "error": {"reachable": False,
                                                                  "code": "ConnectError",
                                                                  "message": "gone"}},
                           "line_follow": {"ok": False, "error": {"reachable": False,
                                                                   "code": "ConnectError",
                                                                   "message": "gone"}}},
                 "tasks": {"awaiting_core_result": []}},
                {"robot_id": "rosy_03", "result": "failed",
                 "steps": {"swarm": step_ok, "navigation": step_ok,
                           "line_follow": {"ok": False, "error": {
                               "reachable": False, "sent": False,
                               "code": "ADDRESS_UNVERIFIED", "message": "stop only"}}},
                 "tasks": {"awaiting_core_result": []}},
            ],
            "formation": {"stopped": True, "state": "STOPPED"},
            "tasks": {"canceled": ["q-1", "q-2"], "error": None},
        },
    }
    posts: list[tuple[str, str]] = []
    with sync_playwright() as p:
        browser, page, errors = _open_console(
            p, api, posts=posts, init_script=DECLINE_CONFIRM)
        page.set_viewport_size({"width": width, "height": height})
        page.goto(console_url, wait_until="networkidle")
        assert page.locator("#cancel-all").get_attribute("kind") == "quiet"
        assert page.locator("#cancel-all-result").is_hidden()
        page.locator("#cancel-all").click()
        assert page.locator('dialog.ui-confirm').count() == 0  # a stop never waits behind a dialog
        stop = page.locator("#estop").bounding_box()
        assert stop and stop["width"] > 0 and stop["y"] >= 0 and stop["y"] + stop["height"] <= height
        page.wait_for_function("() => !document.querySelector('#cancel-all-result').hidden")
        page.locator("#log").get_by_text("주행 취소 요청 응답: 1/3 · 물리 정지 미확인").wait_for(state="attached")
        summary = page.locator("#cancel-all-result")
        assert summary.inner_text().startswith("전체 주행 취소를 보냈습니다 · 3대")
        assert "1/3 · 물리 정지 미확인" in summary.inner_text()
        result_box = summary.bounding_box()
        assert result_box and result_box["y"] >= 0 and result_box["y"] + result_box["height"] <= height
        page.locator("#log").get_by_text("rosy_02 주행 취소 응답 없음 — 대형 추종 ConnectError · 내비게이션 ConnectError · 차선 추종 ConnectError").wait_for(state="attached")
        page.locator("#log").get_by_text("rosy_03 주행 취소 실패 — 주소 미확인 — 차선 추종 끄기 미전송").wait_for(state="attached")
        page.locator("#log").get_by_text("대기 작업 2개 취소 · 로봇 취소 확인 대기 작업 1개").wait_for(state="attached")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        save_temp_screenshot(page, "fleet_cancel_all_result.png" if width == 1920 else f"fleet_cancel_all_result_{width}.png")
        details = page.locator("#cancel-all-details")
        assert details.is_visible() and details.get_attribute("href") == "#log"
        details.click()
        assert page.locator("#context-inbox").is_visible()
        assert page.evaluate("location.hash") == "#log"
        assert page.locator("#log").is_visible()
        page.locator("#log").get_by_text("주행 취소 요청 응답: 1/3 · 물리 정지 미확인").wait_for(state="visible")
        page.locator("#log").get_by_text("rosy_02 주행 취소 응답 없음 — 대형 추종 ConnectError · 내비게이션 ConnectError · 차선 추종 ConnectError").wait_for(state="visible")
        page.locator("#log").get_by_text("rosy_03 주행 취소 실패 — 주소 미확인 — 차선 추종 끄기 미전송").wait_for(state="visible")
        page.locator("#log").get_by_text("대기 작업 2개 취소 · 로봇 취소 확인 대기 작업 1개").wait_for(state="visible")
        page.locator("#log-clear").click()
        assert details.is_hidden()
        assert not errors, f"페이지 오류: {errors}"
        browser.close()

    assert [post for post in posts if post[1] == "/api/fleet/cancel-all"] == [("POST", "/api/fleet/cancel-all")]
    assert ("POST", "/api/fleet/estop") not in posts


def test_fleet_cancel_all_failure_is_visible_beside_action_on_phone(console_url):
    from playwright.sync_api import sync_playwright, expect

    api = {**API, "/api/fleet/cancel-all": (503, {"detail": {"code": "SERVER_UNAVAILABLE"}})}
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, api)
        page.set_viewport_size({"width": 320, "height": 568})
        page.goto(console_url, wait_until="networkidle")
        page.locator("#cancel-all").click()  # no confirm: a stop goes at once (D-540 6)
        result = page.locator("#cancel-all-result")
        expect(result).to_contain_text("주행 취소 결과 확인 불가")
        expect(result).to_contain_text("로봇 상태를 다시 확인하세요")
        assert "SERVER_UNAVAILABLE" not in result.inner_text()
        box = result.bounding_box()
        assert box and box["y"] >= 0 and box["y"] + box["height"] <= 568
        assert page.locator("#cancel-all-details").is_hidden()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        save_temp_screenshot(page, "fleet_cancel_all_failure_320.png")
        assert not errors
        browser.close()


DELAYED_FORMATION = {
    **FORMATION,
    "stream_evidence": {
        **FORMATION["stream_evidence"],
        "rosy_02": {"state": "delayed", "age_s": 2.1, "reason": "sample_too_old",
                    "stale_after_s": 1.0, "source": "follower_tx"},
    },
    "relay": {
        **FORMATION["relay"],
        "follower_tx_hz": {"rosy_02": 1.2, "rosy_03": 0.0},
        "follower_connected": {"rosy_02": True, "rosy_03": False},
    },
}

HOLDING_FORMATION = {
    **FORMATION,
    "state": "HOLDING",
    "reason": ["nav.stuck", "rosy_03"],
    "pending_triggers": [],
}

UNREACHABLE_SNAPSHOT = {
    **SNAPSHOT,
    "fleet": {"name": "site", "online": 2, "total": 3},
    "robots": [
        SNAPSHOT["robots"][0],
        SNAPSHOT["robots"][1],
        _robot(
            "rosy_03", {"x": 0.45, "y": 0.4, "yaw": 0.0},
            online=False, state=None,
            error={"reachable": False, "code": "CONNECT_ERROR"},
        ),
    ],
}


@pytest.mark.parametrize("width,height", [(1920, 1080), (390, 844), (320, 568)])
def test_delayed_follower_stream_is_named_in_the_roster(console_url, width, height):
    """FOR-003 — 바닥 Hz 아래 팔로워는 '지연'으로, 단절 팔로워는 '끊김'으로 갈린다."""
    from playwright.sync_api import sync_playwright

    api = {
        "/api/fleet/state": SNAPSHOT,
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": DELAYED_FORMATION,
    }
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, api)
        page.set_viewport_size({"width": width, "height": height})
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function(
            "() => (window.__swarmOverlay?.slots || 0) === 2", timeout=8000
        )
        roster = page.inner_text("#roster")
        assert "지연" in roster, "1.2 Hz 팔로워에 지연 태그가 없다"
        assert "끊김" in roster
        assert "rosy_02" in page.locator("#roster article").first.inner_text()
        stop = page.locator("#estop").bounding_box()
        assert stop and stop["width"] > 0 and stop["y"] >= 0 and stop["y"] + stop["height"] <= height
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert not errors
        save_temp_screenshot(page, "fleet_console_delayed.png" if width == 1920 else f"fleet_console_delayed_{width}.png")
        browser.close()


@pytest.mark.parametrize("width,height", [(1920, 1080), (390, 844), (320, 568)])
def test_unreachable_robot_is_never_drawn_healthy(console_url, width, height):
    """concept 16 §5 — 연락 두절은 자기 상태다. '닿지 않음'과 이유가 보여야 한다."""
    from playwright.sync_api import sync_playwright

    api = {
        "/api/fleet/state": UNREACHABLE_SNAPSHOT,
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": {"active": False, "state": "IDLE"},
    }
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, api)
        page.set_viewport_size({"width": width, "height": height})
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function(
            "() => document.getElementById('online-pill')?.textContent === '2/3'"
        )
        roster = page.inner_text("#roster")
        assert "닿지 않음: CONNECT_ERROR" in roster
        assert "오프라인" in roster
        assert "OFFLINE" not in roster
        _open_cards(page, "rosy_03")
        offline = page.locator("#robot-workspace .robot.offline")
        assert "rosy_03" in page.locator("#roster article").first.inner_text()
        assert "NAVIGATING" not in offline.inner_text()
        assert "0.45" not in offline.inner_text()
        assert page.locator("#robot-workspace .robot.offline ui-tag[status=crit]", has_text="오프라인").first.get_attribute("title") == "OFFLINE"
        # The roster replaces its cards on every poll; scroll in one step so a re-render cannot detach the node mid-wait.
        offline.evaluate("node => node.scrollIntoView({block: 'nearest'})")
        stop = page.locator("#estop").bounding_box()
        assert stop and stop["width"] > 0 and stop["y"] >= 0 and stop["y"] + stop["height"] <= height
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert not errors
        save_temp_screenshot(page, "fleet_console_unreachable.png" if width == 1920 else f"fleet_console_unreachable_{width}.png")
        browser.close()


@pytest.mark.parametrize("safety, expected, reason", [
    (None, "정보 없음", "안전 상태를 확인할 수 없어"),
    ({"estop": True}, "비상 정지", "비상정지가 활성화되어"),
])
def test_goal_is_unavailable_when_safety_is_unknown_or_stopped(console_url, safety, expected, reason):
    from playwright.sync_api import sync_playwright

    robot = _robot("rosy_01", {"x": 1.0, "y": 1.0, "yaw": 0.0})
    robot["state"]["safety"] = safety
    api = {
        "/api/fleet/state": {"fleet": {"name": "site", "online": 1, "total": 1},
                             "robots": [robot], "ts": 0.0},
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": {"active": False, "state": "IDLE"},
    }
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, api)
        page.goto(console_url, wait_until="networkidle")
        _open_cards(page)
        card = page.locator("#robot-workspace article").filter(has_text="rosy_01")
        card.wait_for()
        safety_row = card.locator('[data-fact="safety"]')
        # Stable fact identity survives translated/icon labels; stop remains a
        # visible value and goal dispatch remains disabled.
        assert expected in safety_row.inner_text()
        assert reason in card.inner_text()
        assert "목표 남음" in card.inner_text()
        assert "NAVIGATING" not in card.inner_text()
        assert card.locator("ui-button[data-goal-robot-id]").evaluate("node => node.disabled")
        assert not card.locator("ui-button[data-cancel-scope]").evaluate("node => node.disabled")  # 운행 취소 (D-540 (d))
        assert not errors
        save_temp_screenshot(page, "fleet_safety_stopped.png" if safety else "fleet_safety_unknown.png")
        browser.close()


def test_armed_goal_is_withdrawn_when_safety_becomes_unknown(console_url):
    from playwright.sync_api import sync_playwright

    posts: list[tuple[str, str]] = []
    robot = _robot("rosy_01", {"x": 1.0, "y": 1.0, "yaw": 0.0})
    api = {
        "/api/fleet/state": {"fleet": {"name": "site", "online": 1, "total": 1},
                             "robots": [robot], "ts": 0.0},
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": {"active": False, "state": "IDLE"},
        "/api/fleet/robots/rosy_01/goal": {"accepted": True},
    }
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, api, posts=posts,
                                               init_script=DECLINE_CONFIRM)
        page.goto(console_url, wait_until="networkidle")
        _open_cards(page)
        page.locator("ui-button[data-goal-robot-id='rosy_01']").click()
        assert page.locator(".robot.selected").count() == 1
        robot["state"]["safety"] = None
        page.wait_for_function("() => document.querySelector('#robot-workspace article')"
                               "?.textContent.includes('안전 상태를 확인할 수 없어')")
        assert page.locator(".robot.selected").count() == 0
        assert page.locator("#map-canvas").get_attribute("tabindex") == "-1"
        page.keyboard.press("Enter")
        assert not any(method == "POST" and path.endswith("/goal") for method, path in posts)
        page.locator('[data-context-tab="inbox"]').click()
        assert "목표 지정 취소" in page.inner_text("#log")
        assert not errors
        browser.close()


def test_holding_formation_enables_resume_and_warns(console_url):
    """FOR-004 — HOLDING은 warn 태그·재개 버튼으로 말하고 이유는 맵 칩에 그린다."""
    from playwright.sync_api import sync_playwright

    api = {
        "/api/fleet/state": SNAPSHOT,
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": HOLDING_FORMATION,
    }
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, api)
        page.goto(console_url, wait_until="networkidle")
        page.locator('[data-context-tab="tools"]').click()
        page.wait_for_function(
            "() => document.getElementById('formation-state')?.textContent"
            " === '멈춤 · 재개 대기'"
        )
        assert page.locator("#formation-state").get_attribute("status") == "warn"
        assert page.locator("#formation-state").get_attribute("title") == "HOLDING"
        assert page.locator("#formation-resume").get_attribute("reason") is None
        assert "signals.yaml" not in page.inner_text("#signals-hint")
        assert "HOLDING" not in page.inner_text("main")
        assert page.locator("#formation-resume").is_enabled()
        assert not errors
        save_temp_screenshot(page, "fleet_console_holding.png")
        browser.close()


@pytest.mark.parametrize("width,height", [(1920, 1080), (390, 844), (320, 568)])
def test_holding_formation_pending_trigger_blocks_resume_at_declared_widths(console_url, width, height):
    """A pending safety trigger must not offer a resume action that the server rejects."""
    from playwright.sync_api import sync_playwright

    api = {
        "/api/fleet/state": SNAPSHOT,
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": {
            **HOLDING_FORMATION,
            "pending_triggers": [["safety.estop", "rosy_02"]],
        },
    }
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, api)
        page.set_viewport_size({"width": width, "height": height})
        page.goto(console_url, wait_until="networkidle")
        page.locator('[data-context-tab="tools"]').click()
        page.wait_for_function("() => document.querySelector('#formation-state')?.textContent === '멈춤 · 재개 대기'")
        assert page.locator("#formation-resume").is_disabled()
        assert "비상 정지" in page.inner_text("#formation-detail")
        assert "safety.estop" not in page.inner_text("#formation-detail")
        assert "주행 정체" in page.inner_text("#formation-detail")
        assert "nav.stuck" not in page.inner_text("#formation-detail")
        for state in ("blocked", "ready"):
            if state == "ready":
                api["/api/fleet/formation"] = HOLDING_FORMATION
                page.reload(wait_until="networkidle")  # Separate HOLD with no pending trigger.
                page.locator('[data-context-tab="tools"]').click()
                page.wait_for_function("() => !document.querySelector('#formation-resume')?.disabled", timeout=7000)
                assert "재개 차단" not in page.inner_text("#formation-detail")
            stop = page.locator("#estop").bounding_box()
            assert stop and stop["width"] > 0 and stop["y"] + stop["height"] <= height
            if width < 480:
                panels = [page.locator(selector).bounding_box() for selector in (
                    'section[aria-labelledby="map-heading"]',
                    '.console-context',
                    ".ops-block",
                )]
                assert max(panel["width"] for panel in panels) - min(panel["width"] for panel in panels) <= 1
                assert max(panel["x"] for panel in panels) - min(panel["x"] for panel in panels) <= 1
                actions = [page.locator(f"#formation-{name}").bounding_box() for name in (
                    "start", "reform", "resume", "stop",
                )]
                assert max(action["width"] for action in actions) - min(action["width"] for action in actions) <= 1
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.locator("#formation-state").scroll_into_view_if_needed()
            save_temp_screenshot(page, f"fleet_formation_hold_{state}_{width}.png")
        assert errors == []
        browser.close()


@pytest.mark.parametrize("width,height", [(1920, 1080), (390, 844), (320, 568)])
def test_formation_read_loss_hides_last_running_evidence_and_recovers(console_url, width, height):
    """A failed poll must not present an old leader or relay rate as current."""
    from playwright.sync_api import sync_playwright

    api = {
        "/api/fleet/state": SNAPSHOT,
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": FORMATION,
    }
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, api)
        page.set_viewport_size({"width": width, "height": height})
        page.goto(console_url, wait_until="networkidle")
        page.locator('[data-context-tab="tools"]').click()
        page.wait_for_function("() => document.querySelector('#formation-state')?.textContent === '진행 중'")
        assert "9.8 Hz" in page.inner_text("#formation-detail")
        assert page.evaluate("window.__swarmOverlay?.slots") == 2

        api["/api/fleet/formation"] = (503, {"detail": {"code": "FORMATION_UNAVAILABLE"}})
        page.wait_for_function("() => document.querySelector('#formation-state')?.textContent === '확인 불가'",
                               timeout=7000)
        assert "9.8 Hz" not in page.inner_text("#formation-detail")
        assert "리더 rosy_01" not in page.inner_text("#formation-detail")
        assert "FORMATION_UNAVAILABLE" not in page.inner_text("#formation-detail")
        assert page.evaluate("window.__swarmOverlay?.slots") == 0
        for control in ("formation-start", "formation-reform", "formation-resume"):
            assert page.locator(f"#{control}").is_disabled()
        for state in ("lost", "recovered"):
            if state == "recovered":
                api["/api/fleet/formation"] = FORMATION
                page.wait_for_function("() => document.querySelector('#formation-state')?.textContent === '진행 중'",
                                       timeout=7000)
                assert "9.8 Hz" in page.inner_text("#formation-detail")
                assert page.evaluate("window.__swarmOverlay?.slots") == 2
            stop = page.locator("#estop").bounding_box()
            assert stop and stop["width"] > 0 and stop["y"] + stop["height"] <= height
            if width < 480:
                map_panel = page.locator('section[aria-labelledby="map-heading"]').bounding_box()
                roster_panel = page.locator('.console-context').bounding_box()
                ops_panel = page.locator(".ops-block").bounding_box()
                assert max(map_panel["width"], roster_panel["width"], ops_panel["width"]) - min(
                    map_panel["width"], roster_panel["width"], ops_panel["width"]) <= 1
                assert max(map_panel["x"], roster_panel["x"], ops_panel["x"]) - min(
                    map_panel["x"], roster_panel["x"], ops_panel["x"]) <= 1
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.locator("#formation-state").scroll_into_view_if_needed()
            save_temp_screenshot(page, f"fleet_formation_read_{state}_{width}.png")
        assert errors == []
        browser.close()


def test_discovery_read_loss_removes_old_device_addresses_and_recovers(console_url):
    """A scanner read failure cannot leave the last discovered address looking current."""
    from playwright.sync_api import sync_playwright

    devices = {"scanner_online": True, "devices": [{
        "name": "rosy-old", "address": "192.0.2.10", "port": 8000,
        "stage": "ready", "status": "pairing_pending",
    }]}
    api = {
        "/api/fleet/state": SNAPSHOT,
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": FORMATION,
        "/api/fleet/discovery": devices,
    }
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, api)
        page.goto(console_url.rsplit("/", 1)[0] + "/install.html", wait_until="networkidle")
        page.wait_for_function("() => document.querySelector('#discovery-list')?.textContent.includes('192.0.2.10')")

        api["/api/fleet/discovery"] = (503, {"detail": {"code": "SCANNER_UNAVAILABLE"}})
        page.wait_for_function("() => document.querySelector('#discovery-status')?.textContent === '발견 상태 확인 불가'",
                               timeout=12000)
        assert "192.0.2.10" not in page.inner_text("#discovery-list")
        assert page.locator("#discovery-list").is_hidden()
        assert "발견 목록을 확인할 수 없습니다" in page.inner_text("#discovery-empty")

        api["/api/fleet/discovery"] = {"scanner_online": True, "devices": [{
            "name": "rosy-new", "address": "192.0.2.11", "port": 8000,
            "stage": "ready", "status": "pairing_pending",
        }]}
        page.wait_for_function("() => document.querySelector('#discovery-list')?.textContent.includes('192.0.2.11')",
                               timeout=7000)
        assert "192.0.2.10" not in page.inner_text("#discovery-list")

        api["/api/fleet/discovery"] = (401, {"detail": {"code": "TOKEN_REQUIRED"}})
        page.wait_for_function("() => document.querySelector('#discovery-status')?.textContent === '인증 필요'",
                               timeout=7000)
        assert "192.0.2.11" not in page.inner_text("#discovery-list")
        api["/api/fleet/discovery"] = devices
        _open_token_access(page)
        page.locator("#token-save").click()
        page.wait_for_function("() => document.querySelector('#discovery-list')?.textContent.includes('192.0.2.10')",
                               timeout=7000)
        assert errors == []
        browser.close()


def test_expired_scanner_lease_raises_an_alarm_and_clears_on_return(console_url):
    """2026-10-01 audit #4: a lost scanner stops move-address; the panel must say so loudly."""
    from playwright.sync_api import sync_playwright

    online = {"scanner_online": True, "scanner_state": "online", "scanner_age_s": 3, "devices": [{
        "name": "rosy-a", "address": "192.0.2.10", "port": 8000,
        "stage": "ready", "status": "pairing_pending",
    }]}
    api = {
        "/api/fleet/state": SNAPSHOT,
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": FORMATION,
        "/api/fleet/discovery": {"scanner_online": False, "scanner_state": "never_seen",
                                 "scanner_age_s": None, "devices": []},
    }
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, api)
        page.goto(console_url.rsplit("/", 1)[0] + "/install.html", wait_until="networkidle")
        page.wait_for_function("() => document.querySelector('#discovery-status')?.textContent === '검색기 연결 대기'")
        assert page.get_attribute("#discovery-status", "status") == "warn"

        api["/api/fleet/discovery"] = {"scanner_online": False, "scanner_state": "expired",
                                       "scanner_age_s": 61, "devices": []}
        page.wait_for_function("() => document.querySelector('#discovery-status')?.textContent === '검색기 끊김'",
                               timeout=7000)
        assert page.get_attribute("#discovery-status", "status") == "crit"
        assert page.locator("#discovery-list").is_hidden()
        assert "마지막 스캔 61초 전" in page.inner_text("#discovery-empty")
        assert "새 주소로 옮기기" in page.inner_text("#discovery-empty")
        assert page.inner_text("#log").count("발견 검색기 끊김") == 1

        api["/api/fleet/discovery"] = online
        page.wait_for_function("() => document.querySelector('#discovery-list')?.textContent.includes('192.0.2.10')",
                               timeout=7000)
        assert page.get_attribute("#discovery-status", "status") == "neutral"
        assert "발견 검색기 다시 연결됨" in page.inner_text("#log")
        assert errors == []
        browser.close()


def test_map_surface_explains_missing_map_and_recovers_without_stale_canvas(console_url):
    """The map area must explain why it cannot be used instead of showing a blank slab."""
    from playwright.sync_api import sync_playwright

    api = {
        "/api/fleet/state": SNAPSHOT,
        "/api/fleet/map": (503, {"detail": {"code": "MAP_UNAVAILABLE"}}),
        "/api/fleet/formation": FORMATION,
    }
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, api)
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function("() => document.querySelector('#map-tag')?.textContent === '맵 없음'")
        assert page.locator("#map-empty").is_visible()
        assert "지도를 확인할 수 없습니다" in page.inner_text("#map-empty")
        assert page.locator("#map-canvas").get_attribute("aria-hidden") == "true"
        assert page.locator(".legend").is_hidden()
        assert "지도가 수신되면" in page.inner_text("#hint")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        save_temp_screenshot(page, "fleet_map_unavailable_1920.png")
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.locator("#map-empty").is_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        save_temp_screenshot(page, "fleet_map_unavailable_390.png")
        page.set_viewport_size({"width": 1920, "height": 1080})

        api["/api/fleet/map"] = MAP_GRID
        page.wait_for_function("() => document.querySelector('#map-empty')?.hidden === true", timeout=7000)
        assert page.locator(".legend").is_visible()
        assert page.locator("#map-canvas").get_attribute("aria-hidden") is None
        assert "지도를 찍으면" in page.inner_text("#hint")

        api["/api/fleet/map"] = (503, {"detail": {"code": "MAP_UNAVAILABLE"}})
        page.wait_for_function("() => document.querySelector('#map-empty')?.hidden === false", timeout=7000)
        assert page.locator(".legend").is_hidden()
        assert page.locator("#map-canvas").get_attribute("aria-hidden") == "true"
        assert page.evaluate("document.querySelector('#map-canvas').getContext('2d').getImageData(0, 0, 1, 1).data[3]") == 0
        assert "지도가 수신되면" in page.inner_text("#hint")
        assert errors == []
        browser.close()


def test_fresh_rosy_cam_frame_becomes_site_map_background_then_expires(console_url):
    from playwright.sync_api import sync_playwright

    api = {
        "/api/fleet/state": EMPTY_SNAPSHOT,
        "/api/fleet/map": (503, {"detail": {"code": "MAP_UNAVAILABLE"}}),
        "/api/fleet/site-map": {"maps": [{"map_id": "map_v2_fleet",
                                      "polygon_m": [[0, 0], [1, 0], [1, 1], [0, 1]],
                                      "bounds_m": {"min_x": 0, "min_y": 0,
                                                   "max_x": 1, "max_y": 1}}]},
        "/api/fleet/calibrations": {"calibrations": [{
            "source_id": "ceiling_north", "map_id": "map_v2_fleet",
            "calibration_revision": "paint-test", "image": {"width": 1280, "height": 720},
            "lens": {"kind": "wide", "focal_mm": 2.2, "hfov_deg": 104.1},
            "map_to_image": [1000, 0, 100, 0, 600, 50, 0, 0, 1]}]},
        "/api/fleet/vision/sources": {"sources": ["ceiling_north"]},
        "/api/fleet/vision/lease": {"source_id": "ceiling_north", "lease": "test-lease",
                                     "frame_path": "/api/vision/sources/ceiling_north/frame", "expires_in_s": 60},
    }
    frame_age = {"ms": "20"}
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(
            playwright, api,
            init_script="sessionStorage.setItem('rosy-console-token', 'test-token')")

        def serve_frame(route):
            route.fulfill(status=200, content_type="image/svg+xml",
                          body='<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720">'
                               '<rect width="1280" height="720" fill="#bf2030"/></svg>',
                          headers={"X-Frame-Rectified": "false", "X-Frame-Seq": "42",
                                   "X-Frame-Age-Ms": frame_age["ms"],
                                   "X-Source-Lens": "kind=wide;focal_mm=2.2;hfov_deg=104.1"})

        page.route("**/api/vision/sources/ceiling_north/frame", serve_frame)
        page.goto(console_url, wait_until="networkidle")
        page.select_option("#map-display-mode", "overlay")
        page.locator("#map-options > summary").click()
        page.wait_for_function("() => document.querySelector('#map-tag')?.textContent.includes('paint-test')")
        # D-560: this Vision answers the map-plane lease with a raw frame (no D-560), so the D-515
        # browser warp is the fallback and the tag says so.
        assert "브라우저 보정(대체)" in page.inner_text("#map-tag")
        page.select_option("#map-display-mode", "overlay")
        # D-487: the calibrated canvas carries the frame; no second copy under the map.
        assert page.locator("#map-camera").count() == 0
        # D-515: the frame is laid top-down on the metre view. The site centre (canvas centre for
        # these symmetric bounds) shows the red frame; the fit pad around the site stays ground.
        red = page.evaluate("() => { const c = document.querySelector('#map-canvas'); "
                            "const g = c.getContext('2d'); "
                            "const at = (x, y) => [...g.getImageData(x, y, 1, 1).data]; "
                            "return [at(Math.floor(c.width / 2), Math.floor(c.height / 2)), at(2, 2)]; }")
        centre, pad = red
        assert centre[0] > 150 and centre[1] < 100 and centre[2] < 100, red
        assert not (pad[0] > 150 and pad[1] < 100 and pad[2] < 100), red
        frame_age["ms"] = "4000"
        page.wait_for_function("() => !document.querySelector('#map-tag')?.textContent.includes('paint-test')",
                               timeout=7000)
        assert not errors
        browser.close()


def test_rosy_cam_map_plane_is_drawn_into_its_rectangle_then_falls_back_on_409(console_url):
    """D-560 S2: the console asks Vision for the map plane and lays it on toPx without a warp."""
    from playwright.sync_api import sync_playwright

    api = {
        "/api/fleet/state": EMPTY_SNAPSHOT,
        "/api/fleet/map": (503, {"detail": {"code": "MAP_UNAVAILABLE"}}),
        "/api/fleet/site-map": {"maps": [{"map_id": "map_v2_fleet",
                                      "polygon_m": [[0, 0], [1, 0], [1, 1], [0, 1]],
                                      "bounds_m": {"min_x": 0, "min_y": 0,
                                                   "max_x": 1, "max_y": 1}}]},
        "/api/fleet/calibrations": {"calibrations": [{
            "source_id": "ceiling_north", "map_id": "map_v2_fleet",
            "calibration_revision": "paint-test", "image": {"width": 1280, "height": 720},
            "lens": {"kind": "wide", "focal_mm": 2.2, "hfov_deg": 104.1},
            "map_to_image": [1000, 0, 100, 0, 600, 50, 0, 0, 1]}]},
        "/api/fleet/vision/sources": {"sources": ["ceiling_north"]},
    }
    # Plane 1.3 x 1.3 m at 100 px/m from (-0.15, -0.15): blue, with a red map square
    # x 0..0.5, y 0.5..1 (pixels u 15..65, v 15..65).
    plane_svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="130" height="130">'
                 '<rect width="130" height="130" fill="#2040bf"/>'
                 '<rect x="15" y="15" width="50" height="50" fill="#bf2030"/></svg>')
    raw_svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720">'
               '<rect width="1280" height="720" fill="#20bf40"/></svg>')
    leases = []
    plane = {"status": 200}
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(
            playwright, api,
            init_script="sessionStorage.setItem('rosy-console-token', 'test-token')")

        def serve_lease(route):
            body = route.request.post_data_json
            leases.append(body)
            token = "plane-lease" if (body.get("rectification") or {}).get("mode") == "map" else "raw-lease"
            route.fulfill(status=200, json={"source_id": "ceiling_north", "lease": token,
                                            "frame_path": "/api/vision/sources/ceiling_north/frame",
                                            "expires_in_s": 60})

        def serve_frame(route):
            base = {"X-Frame-Seq": "42", "X-Frame-Age-Ms": "20",
                    "X-Source-Lens": "kind=wide;focal_mm=2.2;hfov_deg=104.1"}
            if route.request.headers.get("authorization") != "Bearer plane-lease":
                route.fulfill(status=200, content_type="image/svg+xml", body=raw_svg,
                              headers={**base, "X-Frame-Rectified": "false"})
            elif plane["status"] == 409:
                route.fulfill(status=409, json={"detail": "plane unavailable"},
                              headers={"X-Frame-State": "plane-unavailable"})
            else:
                route.fulfill(status=200, content_type="image/svg+xml", body=plane_svg,
                              headers={**base, "X-Frame-Rectified": "map",
                                       "X-Frame-Plane": "-0.15,-0.15,1.15,1.15,100",
                                       "X-Frame-Calibration": "paint-test"})

        page.route("**/api/fleet/vision/lease", serve_lease)
        page.route("**/api/vision/sources/ceiling_north/frame", serve_frame)
        page.goto(console_url, wait_until="networkidle")
        page.select_option("#map-display-mode", "overlay")
        page.locator("#map-options > summary").click()
        page.wait_for_function(
            "() => document.querySelector('#map-tag')?.textContent.includes('Rosy Cam 평면 영상 · paint-test')",
            timeout=10000)
        assert {"mode": "map"} in [body.get("rectification") for body in leases]
        page.select_option("#map-display-mode", "overlay")
        # Known map points land on the canvas pixel the map's own toPx gives (siteBounds 0.25 margin,
        # fitTransform pad 32, no view turn): red inside the square, blue outside, ground beyond the plane.
        # Points stay off the 0.5 m grid lines.
        sample = """async (points) => {
          const { fitTransform, project } = await import('/console/assets/site-layer.js');
          const c = document.querySelector('#map-canvas'), g = c.getContext('2d');
          const r = c.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
          const t = fitTransform({ min_x: -0.25, min_y: -0.25, max_x: 1.25, max_y: 1.25 }, r.width, r.height, 32);
          return Object.fromEntries(Object.entries(points).map(([name, [x, y]]) => { const p = project(t, x, y);
            return [name, [...g.getImageData(Math.round(p.px * dpr), Math.round(p.py * dpr), 1, 1).data]]; }));
        }"""
        colours = page.evaluate(sample, {"red": [0.25, 0.75], "blue": [0.75, 0.25],
                                         "edge": [-0.1, 0.3], "out": [-0.22, 0.3]})
        red, blue, edge, out = colours["red"], colours["blue"], colours["edge"], colours["out"]
        assert red[0] > 150 and red[2] < 100, colours
        assert blue[2] > 150 and blue[0] < 100, colours
        assert edge[2] > 150 and edge[0] < 100, colours  # the plane margin is part of the picture
        assert not (out[2] > 150 and out[0] < 100), colours  # beyond the plane stays ground
        save_temp_screenshot(page, "fleet_map_plane_1920.png")
        if out := os.environ.get("ROSY_SHOT_DIR"):
            page.locator("#map-options > summary").click()
            for width, height in [(1440, 1000), (390, 844)]:
                page.set_viewport_size({"width": width, "height": height})
                page.wait_for_timeout(300)
                page.screenshot(path=str(Path(out) / f"console-map-plane-overlay-{width}.png"), full_page=True)
            page.locator("#map-options > summary").click()

        plane["status"] = 409
        page.wait_for_function(
            "() => document.querySelector('#map-tag')?.textContent.includes('브라우저 보정(대체) · paint-test')",
            timeout=10000)
        # The fallback warps the raw (green) frame; the red plane square is gone.
        inside = page.evaluate(sample, {"site": [0.25, 0.75]})["site"]
        assert inside[1] > 150 and inside[0] < 100, inside
        assert not errors
        browser.close()


CAMERA_FINGERPRINT = "3F2A-9C1D-77E0-B4C5"
CAMERA_PENDING = {
    "requests": [
        {"request_id": "req-7f3a", "device_label": "Galaxy S21 천장", "app_version": "0.4.0",
         "state": "revealed", "requested_at": "2026-10-01T09:00:00+00:00", "expires_in_s": 250,
         "attempts_left": 3},
        {"request_id": "req-81bc", "device_label": "Pixel 7", "app_version": "0.4.0",
         "state": "pending", "requested_at": "2026-10-01T09:00:30+00:00", "expires_in_s": 290,
         "attempts_left": 3},
    ],
    "paired_sources": [{"source_id": "ceiling_north", "has_credential": True},
                       {"source_id": "ceiling_south", "has_credential": False}],
    "site_ca_fingerprint": CAMERA_FINGERPRINT,
    "unauthenticated_requests": 5, "refused_requests": 2, "commit_mismatches": 1,
}
CAMERA_CREDENTIALS = {"credentials": [{
    "credential_id": "cred-4be1a09c3d2f", "source_id": "ceiling_north", "state": "active",
    "device_label": "Galaxy A54", "approved_by": "alice", "approved_at": "2026-10-01T08:00:00+00:00",
    "confirmed_at": "2026-10-01T08:01:10+00:00", "expires_at": "2027-03-30T08:00:00+00:00",
    "expired": False}], "site_ca_fingerprint": CAMERA_FINGERPRINT}
CAMERA_SHOTS = os.environ.get("ROSY_CAMERA_SCREENSHOT_DIR")


def _camera_api(principal="alice", role="operator"):
    return {
        "/api/fleet/state": SNAPSHOT, "/api/fleet/map": MAP_GRID, "/api/fleet/formation": FORMATION,
        "/api/fleet/session": {"principal_id": principal, "role": role},
        "/api/fleet/pairing/v1/pending": CAMERA_PENDING,
        "/api/fleet/pairing/v1/credentials/summary": CAMERA_CREDENTIALS,
        "/api/fleet/estop": {"stopped": 3, "total": 3, "robots": []},
    }


def _camera_shot(page, name, selector="#camera-link"):
    if not CAMERA_SHOTS:
        return
    Path(CAMERA_SHOTS).mkdir(parents=True, exist_ok=True)
    page.locator(selector).scroll_into_view_if_needed()
    page.locator(selector).screenshot(path=str(Path(CAMERA_SHOTS) / name))
