"""D-131 1단계 — 군집 제어 오버레이의 브라우저 렌더 계약 (옵트인).

ROSY_RUN_BROWSER_TESTS=1 로 실행한다. 가짜 API 응답(활성 대형 + 중재 대기 +
릴레이 단절 팔로워)으로 콘솔을 띄워, 후단이 주는 상태가 실제로 그려지는지
단언한다. mutation-proven: drawFormationOverlay/drawMediation 호출을 지우면
이 시험은 적색이어야 한다(test/ AGENTS 규정).
"""

from __future__ import annotations

import os
import json
import socket
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
    reason="set ROSY_RUN_BROWSER_TESTS=1 to run the optional Chromium regression",
)

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "operations" / "fleet" / "fleet" / "server" / "web"
#: D-129·D-157 — 공용 자산의 단일 파일. Fleet 사본은 없다.
WEB_COMMON = ROOT / "shared" / "web"

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
        "state": {"robot_id": robot_id, "mode": "NAVIGATION", "navigation": "NAVIGATING",
                  "pose": pose, "battery": {"percent": 90}, "safety": {"estop": False}},
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


@pytest.fixture()
def console_url():
    # index.html 의 절대 경로(/common/tokens.css, /console/assets/*)를 풀어 준다.
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(WEB), **kwargs)

        def translate_path(self, path: str) -> str:
            if path.startswith("/common/"):
                name = path.removeprefix("/common/")
                if name in json.loads((WEB_COMMON / "shared-assets.json").read_text(encoding="utf-8"))["shared_assets"]:
                    return str(WEB_COMMON / name)
            if path.startswith("/console/assets/"):
                path = "/" + path[len("/console/assets/"):]
            return super().translate_path(path)

        def log_message(self, *args):  # 시험 출력을 조용히
            pass

    class ConsoleServer(ThreadingHTTPServer):
        # Windows SO_REUSEADDR permits concurrent servers on the same endpoint.
        # Each browser must receive this fixture's files, including mutations.
        allow_reuse_address = os.name != "nt"

        def server_bind(self):
            if os.name == "nt":
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            super().server_bind()

    # Windows may assign Chromium-blocked ports (for example 10080) for port 0.
    for port in range(40000, 41000):
        try:
            server = ConsoleServer(("127.0.0.1", port), Handler)
        except OSError:
            continue
        else:
            break
    else:
        raise RuntimeError("could not allocate a browser-safe local port")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/index.html"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


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
        assert "0.60m" in page.inner_text("#formation-detail"), "슬롯 요약이 사라졌다"
        assert [card.get_attribute("data-robot-id") for card in page.locator("#roster article").all()] == ["rosy_03"]
        save_temp_screenshot(page, "fleet_console_exception_first.png")
        page.locator("#roster-toggle").click()
        assert page.locator("#roster-toggle").get_attribute("aria-expanded") == "true"
        # D-82/§7.3 색 예산 — 색칠은 문제 있는 한 대(rosy_03: 끊김 crit + 대기
        # warn)에만 몰리고 정상 로봇은 무색이다("one coloured row").
        per_robot = page.evaluate(
            "() => Object.fromEntries([...document.querySelectorAll('#roster article')]"
            ".map((el) => [el.querySelector('b')?.textContent,"
            " el.querySelectorAll('ui-tag[status=crit], ui-tag[status=warn]').length]))"
        )
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
        assert "개입할 로봇 없음" in page.inner_text("#roster")
        assert page.locator("#roster article").count() == 0
        toggle = page.locator("#roster-toggle")
        assert toggle.get_attribute("aria-expanded") == "false"
        toggle.focus()
        page.keyboard.press("Enter")
        assert toggle.get_attribute("aria-expanded") == "true"
        assert page.locator("#roster article").count() == 1
        assert page.locator("#roster article").get_attribute("data-robot-id") == "rosy_01"
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
        page.locator("#roster-toggle").click()
        goals = page.locator("#roster ui-button[data-goal-robot-id]")
        assert goals.count() == 2
        for goal in goals.all():
            assert goal.get_attribute("disabled") == (None if supported else "")
            if not supported:
                assert goal.get_attribute("reason") == "수동 주행만 지원"
        arm = page.locator("#formation-start")
        assert arm.get_attribute("disabled") == (None if supported else "")
        if not supported:
            assert "수동 주행만 지원" in page.inner_text("#formation-detail")
        assert not errors
        browser.close()


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
            "() => document.getElementById('online-pill')?.textContent === '0/0 연결'"
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
            " === 'Fleet 서버 없음'"
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
        assert page.locator("#roster-toggle").is_hidden()
        for state in ("loading", "recovered"):
            if state == "recovered":
                page.evaluate("snapshot => window.__releaseState(snapshot)", SNAPSHOT)
                page.wait_for_function("() => document.querySelector('#online-pill')?.textContent === '3/3 연결'")
                assert "rosy_03" in page.inner_text("#roster")
            stop = page.locator("#estop").bounding_box()
            assert stop and stop["width"] > 0 and stop["y"] + stop["height"] <= height
            map_panel = page.locator('section[aria-labelledby="map-heading"]').bounding_box()
            roster_panel = page.locator('section[aria-labelledby="roster-heading"]').bounding_box()
            assert abs(map_panel["width"] - roster_panel["width"]) <= 1
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
        page.locator("#roster-toggle").click()
        page.wait_for_function("() => document.querySelector('#roster article')?.textContent.includes('1.00')")
        api["/api/fleet/state"] = (500, {"detail": "gather failed"})
        page.wait_for_function("() => document.querySelector('#online-pill')?.textContent === 'Fleet 서버 없음'"
                               " && document.querySelector('#roster article')?.textContent.includes('상태 확인 불가')")
        assert not errors
        assert "1.00" not in page.inner_text("#roster")
        assert "상태 확인 불가" in page.inner_text("#roster")
        assert page.locator("#roster-toggle").is_hidden()
        assert "로봇 위치 확인 불가" in page.inner_text("#map-tag")
        assert "로봇 위치 확인 불가" in page.locator("#map-canvas").get_attribute("aria-label")
        assert page.locator("#roster article ui-button").first.is_disabled()
        assert page.locator("#online-pill").evaluate("node => node.scrollWidth <= node.clientWidth")
        for state in ("lost", "recovered"):
            if state == "recovered":
                api["/api/fleet/state"] = {"fleet": {"name": "site", "online": 1, "total": 1},
                                           "robots": [robot]}
                page.wait_for_function("() => document.querySelector('#roster article')?.textContent.includes('1.00')")
                assert "로봇 위치 확인 불가" not in page.inner_text("#map-tag")
            stop = page.locator("#estop").bounding_box()
            assert stop and stop["width"] > 0 and stop["y"] + stop["height"] <= height
            map_panel = page.locator('section[aria-labelledby="map-heading"]').bounding_box()
            roster_panel = page.locator('section[aria-labelledby="roster-heading"]').bounding_box()
            assert abs(map_panel["width"] - roster_panel["width"]) <= 1
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
            workflow = page.locator("#console-workflow").bounding_box()
            assert workflow and abs(workflow["x"] - edges[0]) < 1
            assert abs(workflow["x"] + workflow["width"] - edges[1]) < 1
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
        page.locator('#roster-toggle').click()
        page.wait_for_function('() => !document.querySelector("ui-button[data-goal-robot-id=rosy_01]").disabled')
        page.locator('ui-button[data-goal-robot-id="rosy_01"]').click()
        page.locator('#map-canvas').press('Enter')
        dialog.wait_for()
        robot['state']['safety']['estop'] = True
        page.wait_for_function('() => !document.querySelector("#roster article.selected")')
        dialog.locator('ui-button[kind=irreversible]').click()
        page.wait_for_timeout(100)
        assert ('POST', '/api/fleet/robots/rosy_01/goal') not in calls
        robot['state']['safety']['estop'] = False
        robot['state']['line_follow']['mode'] = 'CAMERA_LINE'
        fallback = page.get_by_role('button', name='IR 추적 선택', exact=True)
        fallback.wait_for()
        fallback.click()
        robot['state']['line_follow']['mode'] = 'OFF'
        page.wait_for_function('() => ![...document.querySelectorAll("#roster ui-button")].some(node=>node.textContent==="IR 추적 선택")')
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
        assert ('POST', '/api/fleet/cancel-all') not in calls
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
def test_fleet_cancel_all_requires_confirm_and_logs_each_robot_honestly(console_url, width, height):
    """D-421 — 전체 주행 취소는 confirm을 지나고, 로봇별 결과와 물리 정지 미확인을 쓴다."""
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
        page.locator("#cancel-all").click()
        dialog = page.locator('dialog.ui-confirm')
        dialog.wait_for()
        confirms = [dialog.inner_text()]
        stop = page.locator("#estop").bounding_box()
        assert stop and stop["width"] > 0 and stop["y"] >= 0 and stop["y"] + stop["height"] <= height
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        save_temp_screenshot(page, "fleet_cancel_all_confirm.png" if width == 1920 else f"fleet_cancel_all_confirm_{width}.png")
        dialog.locator('ui-button[kind=quiet]').click()
        declined = [post for post in posts if post[1] == "/api/fleet/cancel-all"]
        assert page.locator("#cancel-all-result").is_hidden()
        page.locator("#cancel-all").click()
        dialog.locator('ui-button[kind=irreversible]').click()
        page.locator("#log").get_by_text("주행 취소 요청 응답: 1/3 · 물리 정지 미확인").wait_for()
        summary = page.locator("#cancel-all-result")
        assert "1/3 · 물리 정지 미확인" in summary.inner_text()
        result_box = summary.bounding_box()
        assert result_box and result_box["y"] >= 0 and result_box["y"] + result_box["height"] <= height
        page.get_by_text("rosy_02 주행 취소 응답 없음 — 대형 추종 ConnectError · 내비게이션 ConnectError · 차선 추종 ConnectError").wait_for()
        page.get_by_text("rosy_03 주행 취소 실패 — 주소 미확인 — 차선 추종 끄기 미전송").wait_for()
        page.get_by_text("대기 작업 2개 취소 · 로봇 취소 확인 대기 작업 1개").wait_for()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        save_temp_screenshot(page, "fleet_cancel_all_result.png" if width == 1920 else f"fleet_cancel_all_result_{width}.png")
        details = page.locator("#cancel-all-details")
        assert details.is_visible() and details.get_attribute("href") == "#log"
        details.click()
        assert page.evaluate("location.hash") == "#log"
        assert page.locator("#log").is_visible()
        page.locator("#log-clear").click()
        assert details.is_hidden()
        assert not errors, f"페이지 오류: {errors}"
        browser.close()

    assert "비상 정지 래치는 걸지 않습니다" in confirms[0]
    assert declined == []
    assert ("POST", "/api/fleet/cancel-all") in posts
    assert ("POST", "/api/fleet/estop") not in posts


def test_fleet_cancel_all_failure_is_visible_beside_action_on_phone(console_url):
    from playwright.sync_api import sync_playwright, expect

    api = {**API, "/api/fleet/cancel-all": (503, {"detail": {"code": "SERVER_UNAVAILABLE"}})}
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, api)
        page.set_viewport_size({"width": 320, "height": 568})
        page.goto(console_url, wait_until="networkidle")
        page.locator("#cancel-all").click()
        page.locator('dialog.ui-confirm ui-button[kind=irreversible]').click()
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
            "() => document.getElementById('online-pill')?.textContent === '2/3 연결'"
        )
        roster = page.inner_text("#roster")
        assert "닿지 않음: CONNECT_ERROR" in roster
        assert "오프라인" in roster
        assert "OFFLINE" not in roster
        offline = page.locator("#roster .robot.offline")
        assert "rosy_03" in page.locator("#roster article").first.inner_text()
        assert "NAVIGATING" not in offline.inner_text()
        assert "0.45" not in offline.inner_text()
        assert page.locator("#roster .robot.offline ui-tag[status=crit]", has_text="오프라인").first.get_attribute("title") == "OFFLINE"
        offline.scroll_into_view_if_needed()
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
        card = page.locator("#roster article").filter(has_text="rosy_01")
        card.wait_for()
        safety_row = card.locator('[data-fact="safety"]')
        # Stable fact identity survives translated/icon labels; stop remains a
        # visible value and goal dispatch remains disabled.
        assert expected in safety_row.inner_text()
        assert reason in card.inner_text()
        assert "목표 남음" in card.inner_text()
        assert "NAVIGATING" not in card.inner_text()
        assert card.locator("ui-button[data-goal-robot-id]").evaluate("node => node.disabled")
        assert not card.locator("ui-button").nth(1).evaluate("node => node.disabled")
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
        page.locator("#roster-toggle").click()
        page.locator("ui-button[data-goal-robot-id='rosy_01']").click()
        assert page.locator(".robot.selected").count() == 1
        robot["state"]["safety"] = None
        page.wait_for_function("() => document.querySelector('#roster article')"
                               "?.textContent.includes('안전 상태를 확인할 수 없어')")
        assert page.locator(".robot.selected").count() == 0
        assert page.locator("#map-canvas").get_attribute("tabindex") == "-1"
        assert "목표 지정 취소" in page.inner_text("#log")
        page.keyboard.press("Enter")
        assert not any(method == "POST" and path.endswith("/goal") for method, path in posts)
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
        page.wait_for_function(
            "() => document.getElementById('formation-state')?.textContent"
            " === '유지 중'"
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
        page.wait_for_function("() => document.querySelector('#formation-state')?.textContent === '유지 중'")
        assert page.locator("#formation-resume").is_disabled()
        assert "비상 정지" in page.inner_text("#formation-detail")
        assert "safety.estop" not in page.inner_text("#formation-detail")
        assert "주행 정체" in page.inner_text("#formation-detail")
        assert "nav.stuck" not in page.inner_text("#formation-detail")
        for state in ("blocked", "ready"):
            if state == "ready":
                api["/api/fleet/formation"] = HOLDING_FORMATION
                page.reload(wait_until="networkidle")  # Separate HOLD with no pending trigger.
                page.wait_for_function("() => !document.querySelector('#formation-resume')?.disabled", timeout=7000)
                assert "재개 차단" not in page.inner_text("#formation-detail")
            stop = page.locator("#estop").bounding_box()
            assert stop and stop["width"] > 0 and stop["y"] + stop["height"] <= height
            if width < 480:
                panels = [page.locator(selector).bounding_box() for selector in (
                    'section[aria-labelledby="map-heading"]',
                    'section[aria-labelledby="roster-heading"]',
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
                roster_panel = page.locator('section[aria-labelledby="roster-heading"]').bounding_box()
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
        page.wait_for_function("() => document.querySelector('#map-tag')?.textContent.includes('paint-test')")
        # D-487: the calibrated canvas carries the frame; no second copy under the map.
        assert page.locator("#map-camera").count() == 0
        assert page.evaluate("() => { const c = document.querySelector('#map-canvas'); "
                             "const p = c.getContext('2d').getImageData(10, 10, 1, 1).data; "
                             "return p[0] > 150 && p[1] < 100 && p[2] < 100; }")
        frame_age["ms"] = "4000"
        page.wait_for_function("() => !document.querySelector('#map-tag')?.textContent.includes('paint-test')",
                               timeout=7000)
        assert not errors
        browser.close()


# --- D-224: 예외 문법의 키보드 어휘 — ↑/↓ 순회 · Enter 목표 · Escape 해소 ----

def test_keyboard_traverses_the_roster_and_arms_a_goal(console_url):
    from playwright.sync_api import sync_playwright

    api = {
        "/api/fleet/state": SNAPSHOT,
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": FORMATION,
    }
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, api)
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function(
            "() => (window.__swarmOverlay?.slots || 0) === 2", timeout=8000
        )
        page.locator("#roster-toggle").click()
        page.locator("#roster-toggle").evaluate("node => node.blur()")
        page.keyboard.press("ArrowDown")
        page.wait_for_function(
            "() => document.activeElement"
            " && document.activeElement.matches('#roster article')"
            " && document.activeElement.querySelector('b')?.textContent === 'rosy_01'"
        )
        page.evaluate("() => { window.__focusedCard = document.activeElement; }")
        page.wait_for_function("() => !window.__focusedCard.isConnected", timeout=3000)
        assert page.evaluate(
            "() => document.activeElement.matches('#roster article')"
            " && document.activeElement.querySelector('b')?.textContent === 'rosy_01'"
        )
        page.keyboard.press("ArrowDown")
        page.wait_for_function(
            "() => document.activeElement.querySelector('b')?.textContent === 'rosy_02'"
        )
        page.keyboard.press("Enter")
        page.wait_for_function(
            "() => document.querySelectorAll('.robot.selected').length === 1"
            " && document.querySelector('.robot.selected b')?.textContent === 'rosy_02'"
        )
        page.keyboard.press("Escape")
        page.wait_for_function(
            "() => document.querySelectorAll('.robot.selected').length === 0"
        )
        assert not errors, f"페이지 오류: {errors}"
        browser.close()


def test_fleet_map_keyboard_goal_requires_confirmation_and_can_cancel(console_url):
    from playwright.sync_api import sync_playwright

    posts: list[tuple[str, str]] = []
    goal_path = "/api/fleet/robots/rosy_02/goal"
    api = {
        "/api/fleet/state": SNAPSHOT,
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": FORMATION,
        goal_path: {"accepted": True, "task": {"task_id": "keyboard-goal", "status": "ACCEPTED"}},
    }
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, api, posts=posts,
                                               init_script=DECLINE_CONFIRM)
        page.goto(console_url, wait_until="networkidle")
        assert page.locator("#log ui-empty").inner_text() == "최근 이벤트가 없습니다 — 관제 요청과 연결 상태 변화가 여기에 표시됩니다."
        page.locator("#roster-toggle").click()
        page.wait_for_function("() => !document.querySelector('#roster article ui-button')?.disabled")
        aim = page.locator("#roster article").filter(has_text="rosy_02").locator("ui-button").first
        aim.click()
        canvas = page.locator("#map-canvas")
        assert canvas.get_attribute("tabindex") == "0"
        assert page.evaluate("document.activeElement?.id") == "map-canvas"
        page.keyboard.press("ArrowRight")
        assert "rosy_02" in page.inner_text("#hint")
        assert "Enter" in page.inner_text("#hint")
        save_temp_screenshot(page, "fleet_goal_preconfirm.png")
        page.keyboard.press("Enter")
        dialog = page.locator('dialog.ui-confirm')
        dialog.wait_for()
        assert "rosy_02" in dialog.inner_text()
        save_temp_screenshot(page, "fleet_goal_confirm_open.png")
        dialog.locator('ui-button[kind=quiet]').click()
        assert not any(method == "POST" and path == goal_path for method, path in posts)
        page.keyboard.press("Escape")
        assert page.locator(".robot.selected").count() == 0
        assert page.evaluate("document.activeElement?.dataset.goalRobotId") == "rosy_02"

        aim.click()
        page.keyboard.press("Enter")
        dialog.locator('ui-button[kind=irreversible]').click()
        page.wait_for_function("() => document.querySelector('#log')?.textContent.includes('미션 하달')")
        assert sum(method == "POST" and path == goal_path for method, path in posts) == 1
        assert page.locator("#log ui-empty").count() == 0
        assert page.locator(".robot.selected").count() == 0
        assert page.evaluate("document.activeElement?.dataset.goalRobotId") == "rosy_02"
        assert not errors
        browser.close()


def test_queued_navigation_is_successful_and_cancel_targets_task(console_url):
    from playwright.sync_api import sync_playwright

    posts: list[tuple[str, str]] = []
    task = {"task_id": "task-queued-123", "status": "QUEUED", "attempt_seq": 0,
            "reason": "ROUTE_CONFLICT", "waiting_on": ["rosy_02"], "queue_position": 1}
    api = {
        "/api/fleet/state": SNAPSHOT,
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": FORMATION,
        "/api/fleet/robots/rosy_01/goal": {"accepted": False, "queued": True, "task": task},
        "/api/fleet/tasks/task-queued-123": {"task": task},
        "/api/fleet/tasks/task-queued-123/cancel": {"task": {**task, "status": "CANCELED"}},
    }
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, api, posts=posts,
                                              init_script="window.confirm = () => true")
        page.goto(console_url, wait_until="networkidle")
        page.locator("#roster-toggle").click()
        page.wait_for_function("() => document.querySelectorAll('#roster article').length > 0")
        page.wait_for_function("() => !document.querySelector('#roster article ui-button')?.disabled")
        page.locator("#roster article").filter(has_text="rosy_01").locator("ui-button").first.click()
        canvas_box = page.locator("#map-canvas").bounding_box()
        assert canvas_box
        page.mouse.click(canvas_box["x"] + canvas_box["width"] / 2,
                         canvas_box["y"] + canvas_box["height"] / 2)
        page.locator('dialog.ui-confirm ui-button[kind=irreversible]').click()
        page.wait_for_function("() => document.querySelector('#log')?.textContent.includes('task-queued-123')")
        assert "QUEUED" in page.inner_text("#log")
        assert "#1" in page.inner_text("#log")
        page.locator("#roster article").filter(has_text="rosy_01").locator("ui-button").nth(1).click()
        page.wait_for_timeout(200)
        assert not errors
        browser.close()

    assert ("POST", "/api/fleet/tasks/task-queued-123/cancel") in posts


# --- D-219: 큐의 렌더 계약 — HITL 과 성능 저하가 보이고, 비면 사라진다 ---------

def _with_state(robot: dict, **state_extra) -> dict:
    row = {**robot, "state": {**robot["state"], **state_extra}}
    return row


def test_queues_render_hitl_and_degraded_then_hide_when_empty(console_url):
    from playwright.sync_api import sync_playwright

    degraded = {
        "fleet": {"name": "site", "online": 3, "total": 3},
        "robots": [
            _robot("rosy_01", {"x": 1.0, "y": 1.0, "yaw": 0.0}),
            _with_state(_robot("rosy_02", {"x": 0.45, "y": 1.0, "yaw": 0.0}),
                        hitl_requested=True),
            _with_state(_robot("rosy_03", {"x": 0.45, "y": 0.4, "yaw": 0.0}),
                        capabilities_degraded=["lidar", "docking"]),
        ],
        "ts": 0.0,
    }
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, {
            "/api/fleet/state": degraded,
            "/api/fleet/map": MAP_GRID,
            "/api/fleet/formation": {"active": False, "state": "IDLE"},
        })
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function(
            "() => document.querySelectorAll('#critical-list li').length === 1"
            " && document.querySelectorAll('#warning-list li').length === 1"
        )
        crit = page.inner_text("#critical-list")
        warn = page.inner_text("#warning-list")
        assert "rosy_02" in crit and "개입 필요" in crit
        assert "로봇 화면에서 확인" in crit  # 정직한 경로(D-218, F-20)
        assert "rosy_03" in warn and "lidar" in warn
        assert page.locator(".queues-panel").is_visible()
        assert not errors, f"페이지 오류: {errors}"
        save_temp_screenshot(page, "fleet_console_queues.png")
        browser.close()

    with sync_playwright() as p:
        browser, page, _errors = _open_console(p, {
            "/api/fleet/state": SNAPSHOT,
            "/api/fleet/map": MAP_GRID,
            "/api/fleet/formation": FORMATION,
        })
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function(
            "() => (window.__swarmOverlay?.slots || 0) === 2", timeout=8000
        )
        # 정상 로스터에는 큐 패널이 아예 없다 — '이상 없음'을 칠하지 않는다.
        assert page.locator(".queues-panel").is_hidden()
        browser.close()


# --- D-201: 예외 문법의 적합 계약 — 선언 뷰포트(사이트 PC 1920×1080)에서
#     문서가 스크롤되지 않고 신호등·대형이 뷰포트 안에 있다. -------------------

FLEET_FIT_PROBE = """() => {
  const inside = (sel) => {
    const n = document.querySelector(sel);
    if (!n) return null;
    const b = n.getBoundingClientRect();
    return { top: Math.round(b.top), bottom: Math.round(b.bottom), height: Math.round(b.height), width: Math.round(b.width) };
  };
  return {
    docOverflow: document.documentElement.scrollHeight - window.innerHeight,
    primary: inside('.console-primary'),
    secondary: inside('.console-secondary'),
    mapPanel: inside('.panel[aria-labelledby="map-heading"]'),
    mapCanvas: inside('#map-canvas'),
    visionFrame: inside('#vision-frame'),
    visionPreview: inside('.vision-preview'),
    signals: inside('.signals'),
    formation: inside('.formation'),
    rosterPanel: inside('.panel[aria-labelledby="roster-heading"]'),
    stop: inside('#estop'),
    roster: inside('#roster'),
    rosterHeading: inside('#roster-heading'),
    vh: window.innerHeight,
  };
}"""


def test_console_fits_the_declared_viewport(console_url):
    from playwright.sync_api import sync_playwright

    api = {
        "/api/fleet/state": SNAPSHOT,
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": FORMATION,
    }
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, api)
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function(
            "() => (window.__swarmOverlay?.slots || 0) === 2", timeout=8000
        )
        fit = page.evaluate(FLEET_FIT_PROBE)
        assert not errors
        save_temp_screenshot(page, "fleet_console_fit.png")
        browser.close()

    assert fit["docOverflow"] <= 0, (
        f"문서가 {fit['docOverflow']}px 스크롤된다 — 예외 문법은 한눈에 다"
        " 보인다(D-201): " + str(fit)
    )
    assert abs(fit["primary"]["width"] - fit["secondary"]["width"]) <= 1, fit
    for name in ("signals", "formation", "rosterPanel"):
        box = fit[name]
        assert box is not None and box["bottom"] <= fit["vh"] and box["top"] >= 0, (
            f"{name} 이(가) 뷰포트 밖이다(D-201): {box}"
        )
    for name in ("mapCanvas", "visionPreview", "signals", "formation", "roster", "rosterPanel", "stop"):
        assert fit[name]["width"] > 0 and fit[name]["height"] > 0, fit
    assert fit["visionFrame"]["height"] == 0, fit  # No camera source in this fixture.
    assert fit["stop"]["width"] >= 58 and fit["stop"]["height"] >= 58, fit
    assert fit["stop"]["top"] >= 0 and fit["stop"]["bottom"] <= fit["vh"], fit
    assert fit["roster"]["top"] - fit["rosterHeading"]["bottom"] <= 24, fit
    assert fit["rosterPanel"]["height"] <= 0.75 * fit["vh"], fit


def test_fleet_control_groups_are_semantic_subheadings(console_url):
    from playwright.sync_api import sync_playwright

    api = {
        "/api/fleet/state": SNAPSHOT,
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": FORMATION,
    }
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, api)
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function(
            "() => (window.__swarmOverlay?.slots || 0) === 2", timeout=8000
        )
        headings = [
            "기기 연결",
            "대형",
            "신호등",
        ]
        for name in headings:
            assert page.get_by_role("heading", name=name, exact=True).count() == 1
        assert page.locator('.device-link a[href="/console/install"]').count() == 1
        page.goto(console_url.rsplit("/", 1)[0] + "/install.html", wait_until="networkidle")
        page.get_by_role("tab", name="로봇 등록", exact=True).click()
        assert page.get_by_role("heading", name="로봇 등록", exact=True).count() == 1
        assert not errors
        browser.close()


def test_robot_enrollment_panel_enrolls_by_screen_code(console_url):
    """D-361 S3: a named operator enrolls a discovered robot; the code goes only to Fleet."""
    import os
    from playwright.sync_api import sync_playwright

    listing = {"available": True, "unavailable_reason": None, "static_robot_ids": ["rosy_01"],
               "robots": [], "alarms": []}
    enrolled = {"robot_id": "rosy_09", "hostname": "rosy-pinky-8kcn", "address": "192.168.1.202:8080",
                "state": "active", "legacy_lifetime": True, "origin": "enrolled", "hold": None,
                "expires_at": "2026-10-07T00:00:00+00:00"}
    api = {
        "/api/fleet/state": SNAPSHOT, "/api/fleet/map": MAP_GRID, "/api/fleet/formation": FORMATION,
        "/api/fleet/session": {"principal_id": "alice", "role": "operator"},
        "/api/fleet/discovery": {"scanner_online": True, "devices": [{
            "name": "rosy-pinky-8kcn", "hostname": "rosy-pinky-8kcn.local",
            "address": "192.168.1.202", "port": 8080, "stage": "CORE_READY", "release": "",
            "robot_id": None, "status": "registration_pending", "enrollable": True}]},
        "/api/fleet/enrollment/robots": listing,
    }
    bodies = []
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, api)

        def enroll(route):
            if route.request.method != "POST":
                route.fallback()
                return
            bodies.append(route.request.post_data_json)
            listing["robots"] = [enrolled]
            route.fulfill(status=201, json=enrolled)

        page.route("**/api/fleet/enrollment/robots", enroll)
        page.goto(console_url.rsplit("/", 1)[0] + "/install.html", wait_until="networkidle")
        page.get_by_role("tab", name="로봇 등록", exact=True).click()
        page.get_by_role("heading", name="로봇 등록", exact=True).wait_for()
        page.locator("#discovery-list ui-button", has_text="등록").first.click()
        assert not page.locator("#enroll-move-check").is_visible()
        page.locator("#enroll-code").fill("7kxm" + "p3qa")
        page.locator("#enroll-submit").click()
        page.wait_for_function(
            "() => document.querySelector('#enrolled-list')?.textContent.includes('rosy_09')")
        assert bodies == [{"discovery_name": "rosy-pinky-8kcn", "code": "7KXM-" + "P3QA"}]
        text = page.locator("#enrolled-list").text_content()
        assert "출처 등록" in text and "7일 뒤 새 코드" in text and "출처 파일" in text
        shot = os.environ.get("ROSY_ENROLL_SCREENSHOT")
        if shot:
            page.screenshot(path=shot, full_page=True)
        assert not errors
        browser.close()


def _enrollment_api(listing):
    return {
        "/api/fleet/state": SNAPSHOT, "/api/fleet/map": MAP_GRID, "/api/fleet/formation": FORMATION,
        "/api/fleet/session": {"principal_id": "alice", "role": "operator"},
        "/api/fleet/discovery": {"scanner_online": True, "devices": [{
            "name": "rosy-pinky-8kcn", "hostname": "rosy-pinky-8kcn.local",
            "address": "192.168.1.202", "port": 8080, "stage": "CORE_READY", "release": "",
            "robot_id": None, "status": "registration_pending", "enrollable": True}]},
        "/api/fleet/enrollment/robots": listing,
        "/api/fleet/estop": {"stopped": 3, "total": 3, "robots": []},
    }


def test_enrollment_dialog_leaves_the_fleet_stop_live(console_url):
    """D-280 원칙 2 (P1-2 review): the enrollment dialog is non-modal — #estop stays live."""
    from playwright.sync_api import sync_playwright

    listing = {"available": True, "unavailable_reason": None, "static_robot_ids": [], "robots": [], "alarms": []}
    posts = []
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, _enrollment_api(listing), posts)
        page.on("dialog", lambda dialog: dialog.accept())  # 전체 정지의 window.confirm
        page.goto(console_url.rsplit("/", 1)[0] + "/install.html", wait_until="networkidle")
        page.get_by_role("tab", name="로봇 등록", exact=True).click()
        page.get_by_role("heading", name="로봇 등록", exact=True).wait_for()
        opener = page.locator("#discovery-list ui-button", has_text="등록").first
        opener.click()
        page.wait_for_function("document.getElementById('enroll-dialog').open")
        assert page.evaluate("document.activeElement?.id") == "enroll-code"
        state = page.evaluate("""() => {
          const stop = document.getElementById('estop');
          const box = stop.getBoundingClientRect();
          const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
          const inertAncestor = (node) => { for (; node; node = node.parentElement) if (node.inert) return true; return false; };
          return {stopInert: inertAncestor(stop), hitsStop: Boolean(hit && stop.contains(hit)),
                  dialogInert: inertAncestor(document.getElementById('enroll-dialog')),
                  panelInert: inertAncestor(document.getElementById('enrolled-list'))};
        }""")
        assert state == {"stopInert": False, "hitsStop": True, "dialogInert": False, "panelInert": True}
        page.locator("#estop").click()
        page.wait_for_function("!document.getElementById('enroll-dialog').open")
        for _ in range(50):
            if ("POST", "/api/fleet/estop") in posts:
                break
            page.wait_for_timeout(100)
        assert ("POST", "/api/fleet/estop") in posts
        assert page.evaluate("[...document.querySelectorAll('[inert]')].length") == 0
        # the dialog went back to its panel (it sat at the end of body only while open)
        assert page.evaluate("document.getElementById('enroll-dialog').parentElement !== document.body")
        assert not errors
        browser.close()


def test_unenroll_is_a_quiet_row_action_confirmed_by_name(console_url):
    """D-371 (P2-3 review): 등록 해제 revokes the site token, so it is `등록 해제…` + confirmIrreversible."""
    from playwright.sync_api import sync_playwright

    enrolled = {"robot_id": "rosy_09", "hostname": "rosy-pinky-8kcn", "address": "192.168.1.202:8080",
                "state": "active", "legacy_lifetime": True, "origin": "enrolled", "hold": None,
                "expires_at": "2026-10-07T00:00:00+00:00"}
    listing = {"available": True, "unavailable_reason": None, "static_robot_ids": [], "robots": [enrolled],
               "alarms": []}
    deletes = []
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, _enrollment_api(listing))

        def remove(route):
            if route.request.method != "DELETE":
                route.fallback()
                return
            deletes.append(route.request.url)
            route.fulfill(status=200, json={"state": "removed"})

        page.route("**/api/fleet/enrollment/robots/rosy_09", remove)
        page.goto(console_url.rsplit("/", 1)[0] + "/install.html", wait_until="networkidle")
        page.get_by_role("tab", name="로봇 등록", exact=True).click()
        row_button = page.locator('#enrolled-list li[data-robot-id="rosy_09"] ui-button[data-action="unenroll"]')
        row_button.wait_for()
        assert row_button.inner_text() == "등록 해제…"
        assert row_button.get_attribute("kind") == "quiet"
        row_button.click()
        dialog = page.locator("dialog.ui-confirm")
        dialog.wait_for()
        assert '"rosy_09"' in dialog.locator("p").inner_text()
        run = dialog.locator('ui-button[kind="irreversible"]')
        assert run.inner_text() == "등록 해제"
        page.keyboard.press("Escape")
        page.wait_for_function("!document.querySelector('dialog.ui-confirm')")
        assert deletes == []
        assert page.evaluate("document.activeElement?.dataset.action") == "unenroll"
        row_button.click()
        page.locator('dialog.ui-confirm ui-button[kind="irreversible"]').click()
        page.wait_for_function("!document.querySelector('dialog.ui-confirm')")
        for _ in range(50):
            if deletes:
                break
            page.wait_for_timeout(100)
        assert len(deletes) == 1
        assert not errors
        browser.close()


def test_camera_rectification_controls_are_accessible_source_scoped_and_reset(console_url):
    from playwright.sync_api import sync_playwright

    api = {
        **API,
        "/api/fleet/vision/sources": {"sources": ["ceiling-north"]},
        "/api/fleet/vision/lease": {
            "source_id": "ceiling-north", "lease": "preview-lease",
            "frame_path": "/api/vision/sources/ceiling-north/frame", "expires_in_s": 60,
        },
    }
    lease_payloads = []
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(
            playwright, api,
            init_script="sessionStorage.setItem('rosy-console-token', 'test-token')",
        )
        page.on("request", lambda request: lease_payloads.append(json.loads(request.post_data))
                if request.url.endswith("/api/fleet/vision/lease") and request.post_data else None)
        page.goto(console_url.rsplit("/", 1)[0] + "/install.html", wait_until="networkidle")
        page.get_by_role("tab", name="카메라 설치·보정", exact=True).click()
        page.get_by_text("왜곡 및 사각 보정", exact=True).click()
        page.get_by_label("왼쪽 위 X (%)").fill("10")
        page.get_by_label("출력 비율").select_option("1")
        page.wait_for_function(
            "() => { const p = JSON.parse(localStorage.getItem('rosy-camera-rectification:ceiling-north') || '{}'); return p.output_aspect === 1 && p.corners?.[0]?.[0] === 0.1; }"
        )
        page.wait_for_timeout(600)
        assert page.get_by_label("왼쪽 위 X (%)").input_value() == "10"
        assert any(payload["rectification"]["output_aspect"] == 1
                   and payload["rectification"]["corners"][0][0] == 0.1
                   for payload in lease_payloads)
        page.get_by_role("button", name="조정 초기화").click()
        page.wait_for_function(
            "() => localStorage.getItem('rosy-camera-rectification:ceiling-north') === null"
        )
        assert page.get_by_label("왼쪽 위 X (%)").input_value() == "0"
        assert page.get_by_label("출력 비율").input_value() == "0"
        assert page.get_by_text("기본 조정값으로 초기화했습니다.").count() == 1
        assert not errors
        browser.close()


def test_camera_rectification_direct_manipulation(console_url):
    from playwright.sync_api import sync_playwright

    api = {
        **API,
        "/api/fleet/vision/sources": {"sources": ["ceiling-north"]},
        "/api/fleet/vision/lease": {
            "source_id": "ceiling-north", "lease": "preview-lease",
            "frame_path": "/api/vision/sources/ceiling-north/frame", "expires_in_s": 60,
        },
    }
    lease_payloads = []
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(
            playwright, api,
            init_script=(
                "sessionStorage.setItem('rosy-console-token', 'test-token');"
                "if (!localStorage.getItem('rosy-camera-rectification:ceiling-north')) "
                "localStorage.setItem('rosy-camera-rectification:ceiling-north', JSON.stringify({"
                "corners:[[0.2,0.2],[0.8,0.2],[0.8,0.8],[0.2,0.8]]}))"
            ),
        )
        page.on("request", lambda request: lease_payloads.append(json.loads(request.post_data))
                if request.url.endswith("/api/fleet/vision/lease") and request.post_data else None)
        def serve_frame(route):
            corners = lease_payloads[-1]["rectification"]["corners"] if lease_payloads else []
            identity = corners == [[0, 0], [1, 0], [1, 1], [0, 1]]
            route.fulfill(
                status=200, content_type="image/svg+xml",
                body=b'<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480"><rect width="640" height="480" fill="#111"/></svg>',
                headers={"X-Frame-Rectified": str(not identity).lower(),
                         "X-Frame-Seq": "42", "X-Frame-Age-Ms": "20"},
            )

        page.route("**/api/vision/**", serve_frame)
        page.goto(console_url.rsplit("/", 1)[0] + "/install.html", wait_until="networkidle")
        page.get_by_role("tab", name="카메라 설치·보정", exact=True).click()
        page.get_by_text("왜곡 및 사각 보정", exact=True).click()
        page.get_by_role("button", name="원본에서 영역 조정").click()
        page.wait_for_timeout(500)
        assert not errors, (errors, lease_payloads, page.locator("#vision-state").inner_text(),
                            page.locator("#vision-message").inner_text())
        assert page.locator("#vision-image-stage").get_attribute("hidden") is None, (
            lease_payloads, page.locator("#vision-state").inner_text(),
            page.locator("#vision-message").inner_text(),
        )
        assert page.locator("#vision-corner-overlay").get_attribute("hidden") is None, (
            page.locator("#vision-frame").get_attribute("data-editing"),
            page.locator("#vision-edit-corners").get_attribute("aria-pressed"),
            lease_payloads,
        )
        page.locator("[data-corner-handle='0']").wait_for(state="visible")

        handle = page.locator("[data-corner-handle='0']")
        handle.scroll_into_view_if_needed()
        box = handle.bounding_box()
        assert box is not None
        hit_test = page.evaluate("([x, y]) => document.elementFromPoint(x, y)?.outerHTML", [
            box["x"] + box["width"] / 2, box["y"] + box["height"] / 2,
        ])
        assert "data-corner-handle" in (hit_test or ""), (box, hit_test)
        page.evaluate("""() => {
          window.__pointerLog = [];
          for (const type of ['pointerdown', 'pointermove', 'pointerup'])
            document.querySelector('#vision-corner-overlay').addEventListener(type,
              (event) => window.__pointerLog.push({type, primary: event.isPrimary,
                x: event.clientX, y: event.clientY, target: event.target.dataset.cornerHandle}), true);
        }""")
        start_x, start_y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        page.mouse.move(start_x, start_y)
        page.mouse.down()
        page.mouse.move(start_x + 0.1 * box["width"], start_y + 0.1 * box["height"])
        page.mouse.up()
        page.wait_for_timeout(250)
        assert page.evaluate("window.__pointerLog"), page.evaluate("window.__pointerLog")
        page.wait_for_function(
            "() => JSON.parse(localStorage.getItem('rosy-camera-rectification:ceiling-north') || '{}')"
            ".corners?.[0]?.[0] > 0.2 && JSON.parse(localStorage.getItem('rosy-camera-rectification:ceiling-north') || '{}')"
            ".corners?.[0]?.[1] > 0.2",
            timeout=1000,
        )
        moved_x = page.get_by_label("왼쪽 위 X (%)").input_value()
        assert float(moved_x) > 20
        assert lease_payloads and lease_payloads[-1]["rectification"]["corners"][0] == [0, 0]

        page.locator("[data-corner-handle='1']").focus()
        page.keyboard.press("ArrowLeft")
        page.keyboard.press("ArrowDown")
        assert page.evaluate("document.activeElement.dataset.cornerHandle") == "1"
        coarse_x = float(page.get_by_label("오른쪽 위 X (%)").input_value())
        page.keyboard.press("Shift+ArrowRight")
        preserved_x = page.get_by_label("오른쪽 위 X (%)").input_value()
        assert float(preserved_x) == pytest.approx(coarse_x + 0.1)
        save_temp_screenshot(page, "fleet_camera_direct_adjustment_desktop.png")
        page.set_viewport_size({"width": 390, "height": 844})
        page.locator("[data-corner-handle='1']").scroll_into_view_if_needed()
        save_temp_screenshot(page, "fleet_camera_direct_adjustment_mobile.png")
        assert page.evaluate("document.documentElement.scrollWidth - window.innerWidth") == 0
        page.get_by_role("button", name="보정 결과 미리보기").click()
        page.wait_for_function(
            "() => document.querySelector('#vision-state').textContent.includes('보정')"
        )
        assert lease_payloads[-1]["rectification"]["corners"][0][0] > 0.2
        assert lease_payloads[-1]["rectification"]["corners"][1][0] < 0.8
        assert lease_payloads[-1]["rectification"]["corners"][1][1] > 0.2
        assert not errors
        page.reload(wait_until="networkidle")
        page.get_by_role("combobox", name="작업 선택").select_option('calibration')
        page.get_by_text("왜곡 및 사각 보정", exact=True).click()
        assert page.get_by_label("오른쪽 위 X (%)").input_value() == preserved_x
        browser.close()


def test_camera_fault_ir_fallback_decline_sends_no_request(console_url):
    from playwright.sync_api import sync_playwright

    robot = _robot("rosy_01", {"x": 1.0, "y": 1.0, "yaw": 0.0})
    robot["state"]["line_follow"] = {
        "mode": "CAMERA_LINE",
        "state": "LOST",
        "reason": "camera_reselection_required",
    }
    snapshot = {"fleet": {"name": "site", "online": 1, "total": 1}, "robots": [robot], "ts": 0.0}
    api = {
        "/api/fleet/state": snapshot,
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": {"active": False, "state": "IDLE"},
    }
    posts = []
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(
            playwright, api, posts=posts, init_script=DECLINE_CONFIRM
        )
        page.goto(console_url, wait_until="networkidle")
        page.locator("#roster-toggle").click()
        fallback = page.get_by_role("button", name="IR 추적 선택", exact=True)
        fallback.wait_for(state="visible")
        fallback.click()
        dialog = page.locator('dialog.ui-confirm')
        dialog.wait_for()
        confirm = dialog.inner_text()
        dialog.locator('ui-button[kind=quiet]').click()
        browser.close()

    assert "rosy_01" in confirm and "IR 추적" in confirm and "요청할까요?" in confirm
    assert not [method_path for method_path in posts if method_path[0] == "POST"]
    assert errors == []


@pytest.mark.parametrize("width", [320, 390])
def test_mobile_console_has_no_horizontal_overflow(console_url, width):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, API)
        page.set_viewport_size({"width": width, "height": 844})
        page.goto(console_url, wait_until="networkidle")
        assert page.locator("#roster article").count() == 1
        assert "rosy_03" in page.locator("#roster article").inner_text()
        save_temp_screenshot(page, f"fleet_console_mobile_default_{width}.png")
        actions = page.locator("#roster article .robot-actions")
        action_widths, actions_width = actions.locator("ui-button").evaluate_all(
            "buttons => [buttons.map(button => button.getBoundingClientRect().width), "
            "buttons[0].parentElement.getBoundingClientRect().width]")
        assert len(action_widths) == 3 and abs(action_widths[0] - action_widths[1]) <= 1, action_widths
        if width == 320:
            assert abs(action_widths[2] - actions_width) <= 1, action_widths
        else:
            assert abs(action_widths[2] - action_widths[0]) <= 1, action_widths
        page.locator("#roster-toggle").click()
        page.wait_for_function("() => document.querySelectorAll('#roster article').length > 0")
        save_temp_screenshot(page, f"fleet_console_mobile_{width}.png")
        layout = page.evaluate("""() => ({
          overflow: document.documentElement.scrollWidth - innerWidth,
          outside: [...document.querySelectorAll('*')].filter(node => node.getBoundingClientRect().right > innerWidth + 1)
            .slice(0, 8).map(node => ({tag:node.tagName, className:String(node.className),
              right:node.getBoundingClientRect().right})),
          headerRows: getComputedStyle(document.querySelector('ui-topbar')).gridTemplateRows
            .trim().split(' ').length,
          headerOverlaps: (() => {
            const boxes = ['ui-brand', '#online-pill', '#estop', '#console-token',
              '#token-save', '#user-role', '#clock'].map(selector => {
                const rect = document.querySelector(selector).getBoundingClientRect();
                return {selector, left:rect.left, right:rect.right, top:rect.top, bottom:rect.bottom};
              });
            return boxes.flatMap((a, index) => boxes.slice(index + 1).filter(b =>
              Math.min(a.right, b.right) - Math.max(a.left, b.left) > 1 &&
              Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 1
            ).map(b => [a.selector, b.selector]));
          })(),
          brand: document.querySelector('ui-brand').getBoundingClientRect().toJSON(),
          brandSize: parseFloat(getComputedStyle(document.querySelector('ui-brand b')).fontSize),
          stop: document.querySelector('#estop').getBoundingClientRect().toJSON(),
          status: document.querySelector('#online-pill').getBoundingClientRect().toJSON(),
          operator: document.querySelector('#user-role').getBoundingClientRect().toJSON(),
          clock: document.querySelector('#clock').getBoundingClientRect().toJSON(),
          stopScopeHidden: (() => {
            const small = document.querySelector('#estop small');
            return !!small && getComputedStyle(small).display === 'none';
          })(),
          stopVerb: [...document.querySelectorAll('#estop span')].filter(node => !node.classList.contains('sr-only')).map(node => node.textContent).join(''),
          stopAccessibleName: document.querySelector('#estop').getAttribute('aria-label'),
        })""")
        if width <= 320:
            page.locator("#topbar-more").click()
            assert page.locator('#topbar-extra a[href="/console/cell"]').is_visible()
        browser.close()
    assert errors == []
    assert layout["overflow"] == 0, layout["outside"]
    assert layout["stop"]["right"] <= width, layout
    assert layout["status"]["right"] <= width, layout
    assert layout["brand"]["left"] >= 0 and layout["brandSize"] >= 12, layout
    assert layout["brand"]["right"] <= layout["status"]["left"] or layout["brand"]["bottom"] <= layout["status"]["top"], layout
    assert layout["headerRows"] <= 4, layout
    assert layout["headerOverlaps"] == [], layout
    if width <= 384:
        # D-359 §6.4 — compact 머리는 두 줄이다(이름·설정 / 연결·시계, 정지는 두 줄에 걸친다).
        # 연결 표지와 시계는 여전히 한 줄을 나눠 쓴다 — 격자 이름 대신 상자로 비교한다.
        status, clock = layout["status"], layout["clock"]
        assert min(status["bottom"], clock["bottom"]) - max(status["top"], clock["top"]) > 1, layout
        assert layout["stopScopeHidden"], layout
        # 보이는 동사는 비상 정지. 래치 부제는 이 폭에서 숨고, 접근 이름은 보이는 글이다.
        assert layout["stopVerb"] == "비상 정지", layout
        assert layout["stopAccessibleName"] is None, layout


@pytest.mark.parametrize("width", [320, 390, 1366])
def test_formation_buttons_keep_their_reasons_readable(console_url, width):
    """D-359 US-007 캡처: 네 버튼을 한 줄에 같은 폭으로 눌러 담아 390px에서 '무장 / 이미 대형 중'이
    어절마다 한 줄씩 네 줄이 됐다. 버튼 줄은 접히고, 이름·사유는 각각 두 줄을 넘지 않는다."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, API)
        page.set_viewport_size({"width": width, "height": 844})
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function("() => document.querySelector('#formation-start small[data-reason]')")
        tall = page.evaluate("""() => [...document.querySelector('#formation-start').parentElement.querySelectorAll('ui-button')].flatMap(button => {
          const note = button.querySelector('small[data-reason]');
          const lines = (node) => node ? Math.round(node.getBoundingClientRect().height
            / parseFloat(getComputedStyle(node).lineHeight)) : 0;
          const label = [...button.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent.trim()).join('');
          const range = document.createRange();
          const text = [...button.childNodes].find(n => n.nodeType === 3 && n.textContent.trim());
          let labelLines = 0;
          if (text) { range.selectNodeContents(text); labelLines = range.getClientRects().length; }
          return (lines(note) > 2 || labelLines > 2) ? [`${button.id} ${label}: label ${labelLines}, reason ${lines(note)}`] : [];
        })""")
        browser.close()
    assert errors == []
    assert tall == []


# --- D-359 §6.4: 세로 예산 — 붙박이 머리 ≤ 창 높이 20%, 비상 정지는 첫 화면에 ---------

@pytest.mark.parametrize("width,height", [(390, 844), (320, 568)])
def test_compact_header_budget_keeps_the_stop_in_view(console_url, width, height):
    """접속·역할·테마는 '설정' 뒤에 접히고, 펼치면 보인다. 머리는 창 높이의 20% 이하다.

    변이 증명: components.css `ui-topbar`에 `min-height: 300px`을 넣으면 빨갛다."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, API)
        page.set_viewport_size({"width": width, "height": height})
        page.goto(console_url, wait_until="networkidle")
        probe = """() => {
          const box = (s) => document.querySelector(s).getBoundingClientRect().toJSON();
          const shown = (s) => { const n = document.querySelector(s); return !!n && n.getClientRects().length > 0; };
          return {overflow: document.documentElement.scrollWidth - innerWidth,
            topbar: box('ui-topbar'), sticky: getComputedStyle(document.querySelector('ui-topbar')).position,
            stop: box('#estop'), more: box('#topbar-more'),
            expanded: document.querySelector('#topbar-more').getAttribute('aria-expanded'),
            token: shown('#console-token'), theme: shown('#theme-choice'), role: shown('#user-role'),
            status: shown('#online-pill'), clock: shown('#clock')};
        }"""
        folded = page.evaluate(probe)
        page.get_by_role("button", name="설정", exact=True).click()
        opened = page.evaluate(probe)
        page.get_by_role("button", name="설정", exact=True).click()
        page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
        scrolled = page.evaluate(probe)
        save_temp_screenshot(page, f"fleet_header_budget_{width}.png")
        browser.close()

    assert errors == []
    assert folded["overflow"] <= 0, folded
    assert folded["topbar"]["height"] <= 0.2 * height, folded
    assert folded["sticky"] == "sticky", folded
    stop = folded["stop"]
    assert stop["top"] >= 0 and stop["left"] >= 0 and stop["bottom"] <= height and stop["right"] <= width, folded
    assert folded["expanded"] == "false" and not folded["token"] and not folded["theme"] and not folded["role"], folded
    assert folded["status"] and folded["clock"], folded
    assert opened["expanded"] == "true" and opened["token"] and opened["theme"] and opened["role"], opened
    assert opened["overflow"] <= 0, opened
    assert scrolled["expanded"] == "false", scrolled
    assert 0 <= scrolled["stop"]["top"] and scrolled["stop"]["bottom"] <= height, scrolled


def test_wide_header_keeps_every_item_on_one_line(console_url):
    """1920px은 모든 항목을 편 한 줄, 1366·1280px(90rem 미만)은 '설정'으로 접힌 한 줄이다.
    어느 쪽이든 머리는 한 줄이고 비상 정지는 오른쪽 위이며 테마 이름표는 두 줄로 접히지 않는다."""
    from playwright.sync_api import sync_playwright

    results = {}
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, API)
        for width, height in ((1920, 1080), (1366, 768), (1280, 800)):
            page.set_viewport_size({"width": width, "height": height})
            page.goto(console_url, wait_until="networkidle")
            if page.locator('#topbar-more').is_visible():
                page.locator('#topbar-more').click()
                assert page.get_by_role('group', name='화면 테마', exact=True).count() == 1
                page.locator('#topbar-more').click()
            else:
                assert page.get_by_role('group', name='화면 테마', exact=True).count() == 1
            results[width] = page.evaluate("""() => {
              const label = document.querySelector('#theme-choice-label');
              const line = parseFloat(getComputedStyle(label).lineHeight) || 20;
              const more = document.querySelector('#topbar-more');
              return {labelLines: label.getClientRects().length ? Math.round(label.getBoundingClientRect().height / line) : 0,
                moreShown: more.getClientRects().length > 0,
                topbar: document.querySelector('ui-topbar').getBoundingClientRect().height,
                stop: document.querySelector('#estop').getBoundingClientRect().toJSON()};
            }""")
        browser.close()

    assert errors == []
    assert results[1920]["labelLines"] == 0 and not results[1920]["moreShown"], results
    for width in (1366, 1280):
        assert results[width]["moreShown"] and results[width]["labelLines"] == 0, results
    for width, result in results.items():
        assert result["topbar"] <= 100, results
        assert result["stop"]["top"] <= 30 and width - result["stop"]["right"] <= 32, results


# --- D-202: 위험은 채움이다 — 따뜻한 글자는 4.5:1 이상이어야 읽힌다 ----------

WARM_TEXT_CONTRAST = """() => {
  const cs = getComputedStyle(document.documentElement);
  const ctx = document.createElement('canvas').getContext('2d');
  const norm = (v) => { ctx.fillStyle = v.trim(); return ctx.fillStyle; };
  const warm = new Set([norm(cs.getPropertyValue('--status-warn')),
                        norm(cs.getPropertyValue('--status-crit'))]);
  const effBg = (el) => {
    let node = el;
    while (node && node !== document.documentElement) {
      const s = getComputedStyle(node);
      const m = s.backgroundColor.match(/rgba?\\(([^)]+)\\)/);
      if (m && (m[1].split(',').length < 4 || Number(m[1].split(',')[3]) === 1)) {
        return norm(s.backgroundColor);
      }
      node = node.parentElement;
    }
    return norm(cs.getPropertyValue('--ground'));
  };
  const lum = (c) => {
    let r, g, b;
    if (c[0] === '#') {
      const h = c.length === 4 ? c.replace(/[^#]/g, (x) => x + x) : c;
      r = parseInt(h.slice(1, 3), 16); g = parseInt(h.slice(3, 5), 16);
      b = parseInt(h.slice(5, 7), 16);
    } else {
      const m = c.match(/rgba?\\(([^)]+)\\)/);
      if (!m) return null;
      [r, g, b] = m[1].split(',').map(Number);
    }
    const f = (v) => { v /= 255;
      return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const offenders = [];
  for (const el of document.querySelectorAll('*')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    if (!(el.textContent.trim() && el.children.length === 0)) continue;
    const s = getComputedStyle(el);
    const color = norm(s.color);
    if (!warm.has(color)) continue;
    const la = lum(color), lb = lum(effBg(el));
    if (la === null || lb === null) continue;
    const ratio = (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
    if (ratio < 4.5) {
      offenders.push(`${el.tagName.toLowerCase()}.${(el.className || '').toString()}"
        ${ratio.toFixed(2)}:1 "${el.textContent.trim().slice(0, 16)}"`);
    }
  }
  return offenders;
}"""


def test_warm_coloured_text_stays_readable(console_url):
    """D-202 — crit 글자(2.24:1) 같은 읽히지 않는 경보를 금지한다."""
    from playwright.sync_api import sync_playwright

    api = {
        "/api/fleet/state": SNAPSHOT,
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": FORMATION,
    }
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, api)
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function(
            "() => (window.__swarmOverlay?.slots || 0) === 2", timeout=8000
        )
        offenders = page.evaluate(WARM_TEXT_CONTRAST)
        assert not errors
        browser.close()

    assert offenders == [], (
        "따뜻한 색 글자가 4.5:1 미만이다 — 위험은 채움이다(D-202): "
        + "; ".join(offenders[:6])
    )


# --- D-214: 텍스트 대비의 바닥 — 색이 아니라 청중의 계약 ---------------------

TEXT_CONTRAST_FLOOR = """() => {
  const ctx = document.createElement('canvas').getContext('2d');
  const effBg = (el) => {
    let node = el;
    while (node && node !== document.documentElement) {
      const s = getComputedStyle(node);
      const m = s.backgroundColor.match(/rgba?\\(([^)]+)\\)/);
      if (m && (m[1].split(',').length < 4 || Number(m[1].split(',')[3]) === 1)) {
        return s.backgroundColor;
      }
      node = node.parentElement;
    }
    return getComputedStyle(document.documentElement).getPropertyValue('--ground');
  };
  const lum = (c) => {
    let r, g, b;
    if (c[0] === '#') {
      const h = c.length === 4 ? c.replace(/[^#]/g, (x) => x + x) : c;
      r = parseInt(h.slice(1, 3), 16); g = parseInt(h.slice(3, 5), 16);
      b = parseInt(h.slice(5, 7), 16);
    } else {
      const m = c.match(/rgba?\\(([^)]+)\\)/);
      if (!m) return null;
      [r, g, b] = m[1].split(',').map(Number);
    }
    const f = (v) => { v /= 255;
      return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const offenders = [];
  for (const el of document.querySelectorAll('*')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    if (!(el.textContent.trim() && el.children.length === 0)) continue;
    const s = getComputedStyle(el);
    const la = lum(s.color), lb = lum(effBg(el));
    if (la === null || lb === null) continue;
    const ratio = (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
    // 24px 이상의 디스플레이 값은 크기가 대비를 보상한다(D-214).
    const floor = parseFloat(s.fontSize) >= 24 ? 3.0 : 4.5;
    if (ratio < floor) {
      offenders.push(`${el.tagName.toLowerCase()}.${(el.className || '').toString()}`
        + ` ${ratio.toFixed(2)}:1 <${floor} "${el.textContent.trim().slice(0, 14)}"`);
    }
  }
  return offenders;
}"""


def test_visible_text_meets_the_contrast_floor(console_url):
    """D-214 — 보이는 모든 글자는 4.5:1(큰 값 3.0:1) 바닥 위에 있다.

    선택된 로봇 카드의 muted 라벨(4.11:1)이 이 게이트의 첫 적발이다.
    """
    from playwright.sync_api import sync_playwright

    api = {
        "/api/fleet/state": SNAPSHOT,
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": FORMATION,
    }
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, api)
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function(
            "() => (window.__swarmOverlay?.slots || 0) === 2", timeout=8000
        )
        # 로스터의 선택 상태를 만든다 — 바닥 붕괴는 선택 카드에서 났다.
        # 선택은 카드가 아니라 '목표 지정' 버튼으로 일어난다(console.js).
        page.locator("#roster article ui-button", has_text="목표 지정").first.click()
        # 경합 하에서 기본 5초를 넘기는 것은 대기의 문제지 대비의 문제가 아니다
        # — 계약은 센서스가 지킨다(2026-09-25 재검증 노트의 플레이크와 같은 계열).
        page.wait_for_function(
            "() => document.querySelectorAll('.robot.selected').length === 1",
            timeout=20_000,
        )
        offenders = page.evaluate(TEXT_CONTRAST_FLOOR)
        assert not errors
        browser.close()

    assert offenders == [], (
        "바닥 아래 텍스트가 있다 — 선택도 읽기를 희생하지 않는다(D-214): "
        + "; ".join(offenders[:6])
    )


@pytest.mark.parametrize("width,height", [(1366, 768), (390, 844), (320, 568)])
def test_map_label_chips_never_cover_each_other(console_url, width, height):
    """D-359 US-008 capture: near rosy_03 the tracking-error chip ("0.88m") and the mediation
    chip ("경로 충돌") were drawn on the same spot and neither read. Chips step aside."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser, page, errors = _open_console(p, dict(API))
        page.set_viewport_size({"width": width, "height": height})
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function("() => (window.__swarmOverlay?.mediation || 0) >= 1"
                               " && (window.__mapChips || []).length >= 3", timeout=8000)
        chips = page.evaluate("() => window.__mapChips.map((r) => ({...r}))")
        assert not errors
        browser.close()

    texts = [chip["text"] for chip in chips]
    assert "경로 충돌" in texts and "0.88m" in texts, texts
    hits = [
        (a["text"], b["text"])
        for i, a in enumerate(chips) for b in chips[i + 1:]
        if a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"]
        and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"]
    ]
    assert hits == [], hits


@pytest.mark.parametrize("width,height", [(320, 568), (390, 844), (1366, 768)])
def test_wordmark_stays_on_one_line(console_url, width, height):
    """D-359 US-008 capture: at 320px "ROSY FLEET" broke into two lines (brand column 83px,
    text 119px). The wordmark is one line, not clipped, and does not run under the next item."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser, page, errors = _open_console(p, API)
        page.set_viewport_size({"width": width, "height": height})
        page.goto(console_url, wait_until="networkidle")
        mark = page.evaluate("""() => {
          const b = document.querySelector('ui-brand b');
          const range = document.createRange(); range.selectNodeContents(b);
          const lines = new Set([...range.getClientRects()].map((r) => Math.round(r.top))).size;
          const text = range.getBoundingClientRect();
          const more = document.getElementById('topbar-more');
          const next = more.getClientRects().length ? more.getBoundingClientRect() : null;
          return {lines, textRight: text.right, boxRight: b.getBoundingClientRect().right,
                  nextLeft: next && Math.abs(next.top - text.top) < text.height ? next.left : null};
        }""")
        browser.close()

    assert errors == []
    assert mark["lines"] == 1, mark
    assert mark["textRight"] <= mark["boxRight"] + 0.5, mark
    if mark["nextLeft"] is not None:
        assert mark["textRight"] <= mark["nextLeft"], mark


@pytest.mark.parametrize("width,height", [(1920, 1080), (1366, 768), (390, 844)])
def test_member_label_sits_beside_the_first_checkbox_row(console_url, width, height):
    """D-359 US-008 capture: "포함 로봇" sat below the checkbox row (centred on a wrapped list at
    1366/390; at wide widths it could flow into the previous row). The label shares the first
    row of the member list and stands to its left."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser, page, errors = _open_console(p, API)
        page.set_viewport_size({"width": width, "height": height})
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function("() => document.querySelectorAll('#formation-members label').length === 3")
        boxes = page.evaluate("""() => {
          const r = (n) => n.getBoundingClientRect().toJSON();
          return {label: r(document.querySelector('.member-label')),
                  first: r(document.querySelector('#formation-members label')),
                  list: r(document.getElementById('formation-members')),
                  named: document.getElementById('formation-members').getAttribute('aria-labelledby')};
        }""")
        browser.close()

    assert errors == []
    label, first, members = boxes["label"], boxes["first"], boxes["list"]
    centre = lambda box: box["y"] + box["height"] / 2  # noqa: E731
    assert abs(centre(label) - centre(first)) <= 2, boxes
    assert label["right"] <= members["x"], boxes
    assert boxes["named"] == "formation-members-label", boxes


def test_roster_mode_tag_speaks_korean_and_keeps_the_enum_in_title(console_url):
    """D-359 US-009 — the card's mode tag reads the shared MODE_LABEL."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, API)
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function("() => document.querySelectorAll('#roster article').length > 0")
        first_tag = page.locator("#roster article").first.locator(".robot-head ui-tag").first
        assert first_tag.inner_text() == "내비게이션"
        assert first_tag.get_attribute("title") == "NAVIGATION"
        assert "NAVIGATION" not in page.inner_text("#roster")
        assert not errors
        browser.close()


@pytest.mark.parametrize("width,height", [(390, 844), (320, 568)])
def test_single_column_tier_puts_exceptions_before_the_map_and_formation_last(console_url, width, height):
    """D-359 US-009 — below 64rem: 주의·로봇 → 지도 → 관제 카메라 → 대형 → 기기 연결(설정 일은 끝).
    Wide keeps its columns (main 486e3683: 대형 sits under the roster list, 기기 연결 beside it)."""
    from playwright.sync_api import sync_playwright

    probe = """() => Object.fromEntries(['.queues-panel', '#roster', '#map-stage', '.vision-preview', '.formation',
        '#log', '.device-link']
      .map((sel) => [sel, Math.round(document.querySelector(sel).getBoundingClientRect().top + window.scrollY)]))"""
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, API)
        page.set_viewport_size({"width": width, "height": height})
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function("() => document.querySelectorAll('#roster article').length > 0")
        top = page.evaluate(probe)
        assert (top["#roster"] < top["#map-stage"] < top[".vision-preview"] < top[".formation"]
                < top["#log"] < top[".device-link"]), top
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.evaluate("""() => {
          window.retainedPanels = ['.queues-panel', '[aria-labelledby=roster-heading]',
            '[aria-labelledby=map-heading]', '.ops-block'].map(sel => document.querySelector(sel));
          document.querySelector('.formation-form-wrap').open = true;
          const input = document.querySelector('#formation-spacing');
          input.value = '1.7'; input.focus();
        }""")
        page.set_viewport_size({"width": 1366, "height": 768})
        page.wait_for_function("() => document.querySelector('.console-primary').contains(document.querySelector('#map-stage'))")
        assert page.evaluate("() => ['.queues-panel', '[aria-labelledby=roster-heading]', '[aria-labelledby=map-heading]', '.ops-block'].every((sel, i) => document.querySelector(sel) === window.retainedPanels[i])")
        wide = page.evaluate(probe)
        # D-439: primary map/roster remain side by side; secondary tasks follow both in DOM and layout.
        left = page.evaluate("""() => Object.fromEntries(['#map-stage', '#roster', '.formation', '.device-link']
          .map((sel) => [sel, document.querySelector(sel).getBoundingClientRect().left]))""")
        assert left["#map-stage"] < left["#roster"], left
        assert wide[".formation"] > max(wide["#roster"], wide["#map-stage"]), wide
        assert wide["#log"] < wide[".device-link"], wide
        assert page.evaluate("document.querySelector('[aria-labelledby=map-heading]').compareDocumentPosition(document.querySelector('.ops-block')) & Node.DOCUMENT_POSITION_FOLLOWING")
        assert wide["#roster"] < wide["#map-stage"] + 200, wide
        page.set_viewport_size({"width": width, "height": height})
        page.wait_for_function("() => document.querySelector('[aria-labelledby=roster-heading]').parentElement.id === 'fleet-main'")
        assert page.evaluate("""() => {
          const panels = ['.queues-panel', '[aria-labelledby=roster-heading]',
            '[aria-labelledby=map-heading]', '.ops-block'].map(sel => document.querySelector(sel));
          return panels.every((node, i) => node === window.retainedPanels[i])
            && panels[1].compareDocumentPosition(panels[2]) & Node.DOCUMENT_POSITION_FOLLOWING;
        }""")
        assert page.locator('#formation-spacing').input_value() == '1.7'
        assert page.locator('#formation-spacing').evaluate('(node) => node === document.activeElement')
        assert not errors
        browser.close()


PAINT_LOG = """
(() => {
  const log = [];
  window.__paintLog = log;
  const proto = CanvasRenderingContext2D.prototype;
  for (const name of ["drawImage", "stroke", "fillText"]) {
    const original = proto[name];
    proto[name] = function (...args) {
      if (this.canvas.id === "map-canvas") log.push(name === "fillText" ? `text:${args[0]}` : name);
      return original.apply(this, args);
    };
  }
})();
"""


def test_map_chips_paint_after_lines_and_clear_robot_markers(console_url):
    """D-359 US-008 leftovers — chips are painted after formation/mediation lines, so no line
    crosses chip text, and chips are placed off the robot marker boxes."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser, page, errors = _open_console(p, API, init_script=PAINT_LOG)
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function("() => (window.__swarmOverlay?.slots || 0) === 2", timeout=8000)
        page.wait_for_function("() => (window.__swarmOverlay?.mediation || 0) > 0")
        log = page.evaluate("window.__paintLog")
        last = log[max(i for i, op in enumerate(log) if op == "drawImage"):]  # the latest full draw
        texts = [i for i, op in enumerate(last) if op.startswith("text:")]
        strokes = [i for i, op in enumerate(last) if op == "stroke"]
        assert texts and strokes, last
        assert max(strokes) < min(texts), last
        chips = page.evaluate("window.__mapChips")
        markers = page.evaluate("window.__mapMarkers")
        assert len(markers) == 3
        overlap = [(c["text"], m["robot"]) for c in chips for m in markers
                   if c["x"] < m["x"] + m["w"] and m["x"] < c["x"] + c["w"]
                   and c["y"] < m["y"] + m["h"] and m["y"] < c["y"] + c["h"]]
        assert overlap == [], (overlap, chips, markers)
        assert not errors
        browser.close()


# --- D-341 카메라 연결 승인 (기기 연결 패널) ---------------------------------------

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


def test_camera_approval_takes_the_phone_code_and_shows_the_mutual_check(console_url):
    """D-341 3–4: approve = free paired source + the phone's six digits; the console never shows a code."""
    import re

    from playwright.sync_api import sync_playwright

    bodies = []
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, _camera_api())

        def approve(route):
            bodies.append(route.request.post_data_json)
            if len(bodies) == 1:
                route.fulfill(status=409, json={"detail": {
                    "code": "CODE_MISMATCH", "message": "code does not match the phone", "attempts_left": 2}})
                return
            route.fulfill(status=200, json={
                "request_id": "req-7f3a", "credential_id": "cred-9d0c11aa22bb", "source_id": "ceiling_south",
                "site_ca_fingerprint": CAMERA_FINGERPRINT, "expires_at": "2027-03-30T09:00:00+00:00",
                "confirm_within_s": 120})

        page.route("**/api/fleet/pairing/v1/requests/req-7f3a/approve", approve)
        page.goto(console_url.rsplit("/", 1)[0] + "/install.html", wait_until="networkidle")
        page.get_by_role("tab", name="카메라 연결 승인", exact=True).click()
        page.get_by_role("heading", name="카메라 연결 승인", exact=True).wait_for()
        ready = page.locator('#camera-requests li[data-request-id="req-7f3a"] ui-button[data-action="approve"]')
        ready.wait_for()
        assert ready.inner_text() == "승인…"
        waiting = page.locator('#camera-requests li[data-request-id="req-81bc"] ui-button[data-action="approve"]')
        assert waiting.get_attribute("reason") == "폰에 아직 코드가 없습니다"
        assert page.evaluate("document.getElementById('camera-requests').textContent").count("남은 시간") == 2
        assert "한도로 거절된 요청 2건" in page.locator("#camera-queue-health").inner_text()
        assert page.locator("#camera-site-fingerprint").inner_text() == CAMERA_FINGERPRINT
        _camera_shot(page, "01-pending-operator-1920.png")

        ready.click()
        page.wait_for_function("document.getElementById('camera-approve-dialog').open")
        assert page.evaluate("document.activeElement?.id") == "camera-approve-code"
        assert page.evaluate(
            "[...document.querySelectorAll('#camera-approve-source option')].map(o => o.value)") == ["ceiling_south"]
        assert page.evaluate("""() => { const s = document.getElementById('estop');
          for (let n = s; n; n = n.parentElement) if (n.inert) return false; return true; }""")
        page.locator("#camera-approve-code").fill("12345")
        page.locator("#camera-approve-submit").click()
        assert "숫자 6자리" in page.locator("#camera-approve-error").inner_text()
        assert bodies == []
        page.locator("#camera-approve-code").fill("123 456")
        page.locator("#camera-approve-submit").click()
        page.wait_for_function(
            "document.getElementById('camera-approve-error').textContent.includes('남은 입력 2회')")
        assert bodies == [{"code": "123456", "source_id": "ceiling_south"}]
        assert page.evaluate("document.getElementById('camera-approve-dialog').open")
        _camera_shot(page, "02-approve-dialog-mismatch-1920.png", "#camera-approve-dialog")
        page.locator("#camera-approve-code").fill("654321")
        page.locator("#camera-approve-submit").click()
        page.wait_for_function("!document.getElementById('camera-confirm').hidden")
        confirm = page.locator("#camera-confirm").inner_text()
        assert "폰 화면과 이 지문·자격 ID가 같은지 확인하세요" in confirm
        assert page.locator("#camera-confirm-fingerprint").inner_text() == CAMERA_FINGERPRINT
        assert page.locator("#camera-confirm-credential").inner_text() == "cred-9d0c11aa22bb"
        assert re.search(r"남은 시간 (2:00|1:5\d)", page.locator("#camera-confirm-clock").inner_text())
        mono = page.evaluate(
            "getComputedStyle(document.getElementById('camera-confirm-fingerprint')).fontFamily")
        assert "mono" in mono.lower() or "consolas" in mono.lower(), mono
        body = page.inner_text("body")
        assert "654321" not in body and "123456" not in body
        _camera_shot(page, "03-mutual-check-1920.png")
        page.set_viewport_size({"width": 1366, "height": 768})
        _camera_shot(page, "04-mutual-check-1366.png")
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        _camera_shot(page, "05-mutual-check-390.png")
        page.set_viewport_size({"width": 320, "height": 568})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        _camera_shot(page, "06-mutual-check-320.png")
        assert not errors
        browser.close()


def test_camera_reject_and_revoke_are_quiet_row_actions_confirmed_by_name(console_url):
    """D-371: 거절…/폐기… open confirmIrreversible naming the target; danger fill only there."""
    from playwright.sync_api import sync_playwright

    posts = []

    def answer(body):
        def handle(route):
            posts.append((route.request.method, urlparse(route.request.url).path))
            route.fulfill(status=200, json=body)
        return handle

    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, _camera_api())
        page.route("**/api/fleet/pairing/v1/requests/req-81bc/reject",
                   answer({"request_id": "req-81bc", "state": "rejected"}))
        page.route("**/api/fleet/pairing/v1/credentials/cred-4be1a09c3d2f/revoke",
                   answer({"credential_id": "cred-4be1a09c3d2f", "state": "revoked"}))
        page.goto(console_url.rsplit("/", 1)[0] + "/install.html", wait_until="networkidle")
        page.get_by_role("tab", name="카메라 연결 승인", exact=True).click()
        revoke = page.locator('#camera-credentials li[data-credential-id="cred-4be1a09c3d2f"] '
                              'ui-button[data-action="revoke"]')
        revoke.wait_for()
        assert revoke.inner_text() == "폐기…" and revoke.get_attribute("kind") == "quiet"
        text = page.locator("#camera-credentials").inner_text()
        assert "사용 중" in text and "alice" in text and "2027-03-30" in text
        revoke.click()
        dialog = page.locator("dialog.ui-confirm")
        dialog.wait_for()
        assert '"cred-4be1a09c3d2f"' in dialog.locator("p").inner_text()
        assert dialog.locator('ui-button[kind="irreversible"]').inner_text() == "폐기"
        _camera_shot(page, "07-revoke-confirm-1920.png", "dialog.ui-confirm")
        page.keyboard.press("Escape")
        page.wait_for_function("!document.querySelector('dialog.ui-confirm')")
        assert page.evaluate("document.activeElement?.dataset.action") == "revoke"
        revoke_path = "/api/fleet/pairing/v1/credentials/cred-4be1a09c3d2f/revoke"
        assert ("POST", revoke_path) not in posts
        revoke.click()
        page.locator('dialog.ui-confirm ui-button[kind="irreversible"]').click()
        page.wait_for_function("document.getElementById('camera-result').textContent.includes('폐기했습니다')")

        reject = page.locator('#camera-requests li[data-request-id="req-81bc"] ui-button[data-action="reject"]')
        assert reject.inner_text() == "거절…"
        reject.click()
        page.locator("dialog.ui-confirm").wait_for()
        assert '"Pixel 7"' in page.locator("dialog.ui-confirm p").inner_text()
        page.locator('dialog.ui-confirm ui-button[kind="irreversible"]').click()
        page.wait_for_function("document.getElementById('camera-result').textContent.includes('거절했습니다')")
        assert ("POST", revoke_path) in posts
        assert ("POST", "/api/fleet/pairing/v1/requests/req-81bc/reject") in posts
        assert not errors
        browser.close()


@pytest.mark.parametrize("principal,role", [("vic", "viewer"), ("site-console", "operator")])
def test_camera_lists_without_actions_for_viewers_and_the_shared_token(console_url, principal, role):
    """D-341 5: viewers and a single console-token site see the lists, never an action button."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, _camera_api(principal, role))
        page.goto(console_url.rsplit("/", 1)[0] + "/install.html", wait_until="networkidle")
        page.get_by_role("tab", name="카메라 연결 승인", exact=True).click()
        page.locator('#camera-requests li[data-request-id="req-7f3a"]').wait_for()
        page.locator('#camera-credentials li[data-credential-id="cred-4be1a09c3d2f"]').wait_for()
        assert page.locator("#camera-requests ui-button, #camera-credentials ui-button").count() == 0
        if role == "viewer":
            assert page.locator("#camera-role-lock").is_visible()
            assert page.locator("#camera-role-lock").inner_text() == "운용자 권한이 필요합니다"
            assert page.locator("#camera-identity-note").is_hidden()
        else:
            note = page.locator("#camera-identity-note")
            assert note.is_visible() and "site-users.yaml" in note.inner_text()
        _camera_shot(page, f"08-lists-{role}-{principal}-1920.png")
        assert not errors
        browser.close()


def test_camera_section_is_calm_when_fleet_has_no_pairing(console_url):
    """Routes absent (plain 404): one calm sentence, and the panel stops asking."""
    from playwright.sync_api import sync_playwright

    api = {key: value for key, value in _camera_api().items() if "/pairing/" not in key}
    posts = []
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, api, posts)
        page.goto(console_url.rsplit("/", 1)[0] + "/install.html", wait_until="networkidle")
        page.get_by_role("tab", name="카메라 연결 승인", exact=True).click()
        calm = page.locator("#camera-link-unavailable")
        calm.wait_for()
        assert calm.inner_text() == "이 Fleet에는 카메라 연결 승인이 설정되지 않았습니다."
        assert page.locator("#camera-link-controls").is_hidden()
        page.wait_for_timeout(6000)
        asked = [p for p in posts if p[1] == "/api/fleet/pairing/v1/pending"]
        assert len(asked) == 1, asked
        _camera_shot(page, "09-no-pairing-1920.png")
        assert not errors
        browser.close()


ADDRESS_SHOTS = os.environ.get("ROSY_ADDRESS_SCREENSHOT_DIR")


def _address_api():
    offline = {"code": "CONNECT_ERROR", "reachable": False}
    snapshot = {"fleet": {"name": "site", "online": 0, "total": 3}, "ts": 0.0, "robots": [
        _robot(rid, {"x": 0.5 + i, "y": 1.0, "yaw": 0.0}, online=False, error=offline)
        for i, rid in enumerate(("rosy_01", "rosy_09", "rosy_10"))]}

    def entry(rid, origin, pinned, status, seen=(), movable=False, is_name=False):
        return {"robot_id": rid, "origin": origin, "pinned": pinned, "pinned_is_name": is_name,
                "status": status, "in_subnet": None if is_name else False,
                "seen_addresses": list(seen), "movable": movable}

    addresses = {"scanner_state": "online", "all_outside": True, "robots": [
        entry("rosy_01", "static", "192.0.2.10:8443", "outside_scanned_subnets"),
        entry("rosy_09", "enrolled", "192.0.2.20:8080", "seen_at_other_address",
              ["10.16.36.20:8080"], True),
        entry("rosy_10", "enrolled", "192.0.2.21:8080", "seen_at_other_address",
              ["10.16.36.21:8080"], True),
    ]}
    rows = [{"robot_id": rid, "hostname": rid, "address": pinned, "state": "address_changed",
             "legacy_lifetime": False, "origin": "enrolled", "hold": "address_changed",
             "expires_at": "2026-12-01T00:00:00+00:00"}
            for rid, pinned in (("rosy_09", "192.0.2.20:8080"), ("rosy_10", "192.0.2.21:8080"))]
    listing = {"available": True, "unavailable_reason": None, "static_robot_ids": ["rosy_01"],
               "robots": rows, "alarms": []}
    api = {**_enrollment_api(listing), "/api/fleet/state": snapshot,
           "/api/fleet/discovery/addresses": addresses,
           "/api/fleet/discovery": {"scanner_online": True, "scanner_state": "online",
                                    "scanner_age_s": 3, "devices": []}}
    return api


def _shot(page, name):
    if ADDRESS_SHOTS:
        Path(ADDRESS_SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(ADDRESS_SHOTS) / name), full_page=True)


def test_offline_robots_say_why_and_each_move_asks_for_the_screen_code(console_url):
    """점검 2026-10-01 #2/#3/#5 + 리뷰: 경보는 옮길 로봇을 나열하고, 옮기기는 로봇마다 화면 코드."""
    from playwright.sync_api import sync_playwright

    moves = []
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, _address_api())

        def move(route):
            moves.append((urlparse(route.request.url).path, route.request.post_data_json))
            route.fulfill(status=200, json={"robot_id": "rosy_09", "address": "10.16.36.20:8080",
                                            "state": "active", "old_token_revoked": False})

        page.route("**/api/fleet/enrollment/robots/*/move-address", move)
        page.goto(console_url, wait_until="networkidle")
        banner = page.locator("#address-banner")
        banner.wait_for()
        assert banner.inner_text().startswith("사이트 망 주소가 바뀌었을 수 있습니다")
        page.wait_for_function(
            "() => document.querySelectorAll('#roster p[data-address-reason]').length === 3")
        listed = page.locator("#address-movable li")
        assert listed.count() == 2
        assert "rosy_09 → 10.16.36.20:8080" in listed.nth(0).inner_text()
        card = page.locator('#roster article[data-robot-id="rosy_09"]')
        assert "같은 로봇이 10.16.36.20:8080에 보입니다 — 새 주소로 옮기기…" in card.inner_text()
        static = page.locator('#roster article[data-robot-id="rosy_01"]').inner_text()
        assert "고정 주소 192.0.2.10:8443이(가) 지금 망에 없을 수 있습니다" in static
        # Cards retain readable reasons; address actions belong to the install owner.
        assert page.evaluate("""() => [...document.querySelectorAll('#roster article')]
            .every((card) => card.scrollHeight <= card.clientHeight + 1)""")
        assert page.evaluate("""() => {
            const reason = document.querySelector('#roster article[data-robot-id="rosy_10"] [data-address-reason]');
            reason.scrollIntoView({block: 'nearest'});
            const r = reason.getBoundingClientRect();
            const box = document.querySelector('#roster').getBoundingClientRect();
            return r.top >= box.top - 1 && r.bottom <= box.bottom + 1; }""")
        assert page.locator('#roster ui-button[data-move-robot-id]').count() == 0
        assert page.locator('.device-link a[href="/console/install"]').is_visible()
        page.evaluate("document.querySelector('#roster').scrollTop = 0")
        _shot(page, "roster-renumbered-1920.png")
        assert not page.locator("text=(전체)").count()

        page.goto(console_url.rsplit("/", 1)[0] + "/install.html", wait_until="networkidle")
        page.get_by_role("tab", name="로봇 등록", exact=True).click()
        page.wait_for_function("() => document.querySelectorAll('#enrolled-list ui-button[data-action=move]').length === 2")
        page.locator('#enrolled-list li[data-robot-id="rosy_09"] ui-button[data-action="move"]').click()
        dialog = page.locator("#enroll-dialog")
        dialog.wait_for()
        assert "rosy_09 → 10.16.36.20:8080" in page.locator("#enroll-target").inner_text()
        assert page.locator("#enroll-submit").inner_text() == "옮기기"
        check = page.locator("#enroll-move-check")
        assert check.is_visible()
        assert page.locator("#enroll-move-address").inner_text() == "10.16.36.20:8080"
        assert "로봇 화면에 보이는 IP와 같은지 확인하세요" in check.inner_text()
        assert page.locator("#estop").is_enabled()
        page.locator("#enroll-code").fill("7kxm" + "p3q")
        page.locator("#enroll-submit").click()
        assert moves == []  # format refused before anything is sent
        page.locator("#enroll-code").fill("7kxm" + "p3qa")
        _shot(page, "move-code-dialog-1920.png")
        page.locator("#enroll-submit").click()
        page.wait_for_function("() => document.querySelector('#enroll-result')?.textContent.includes('옮김')")
        assert moves == [("/api/fleet/enrollment/robots/rosy_09/move-address", {"code": "7KXM-" + "P3QA"})]
        result = page.locator("#enroll-result").inner_text()
        assert "로봇 대시보드에서 회수하거나 만료되게 두세요" in result

        # The enrolled-list action opens the same code dialog (no window.confirm).
        row_move = page.locator('#enrolled-list li[data-robot-id="rosy_10"] ui-button[data-action="move"]')
        assert row_move.inner_text() == "새 주소로 옮기기…"
        row_move.click()
        page.locator("#enroll-dialog").wait_for()
        assert "rosy_10" in page.locator("#enroll-target").inner_text()
        page.locator("#enroll-cancel").click()
        assert len(moves) == 1
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(300)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        _shot(page, "roster-renumbered-390.png")
        assert not errors
        browser.close()


def test_move_candidate_timeout_and_pagehide_keep_server_code_flow_owned(console_url):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        api = _address_api()
        api['/api/fleet/discovery/addresses']['robots'][1]['seen_addresses'].append('10.16.36.99:8080')
        browser, page, errors = _open_console(playwright, api)
        held = []
        page.goto(console_url.rsplit('/', 1)[0] + '/install.html', wait_until='networkidle')
        page.get_by_role("tab", name="로봇 등록", exact=True).click()
        move = page.locator('#enrolled-list li[data-robot-id="rosy_09"] ui-button[data-action="move"]')
        move.wait_for()
        move.click()
        page.locator('#enroll-dialog').wait_for()
        assert page.locator('#enroll-move-address').inner_text() == '새 주소 미확인'
        page.locator('#enroll-cancel').click()
        page.route('**/api/fleet/discovery/addresses', lambda route: held.append(route))
        move.click()
        page.wait_for_function('() => document.querySelector("#enroll-result").textContent.includes("확인")')
        move.click()
        assert len(held) == 1
        assert page.locator('#estop').is_enabled()
        page.locator('#enroll-dialog').wait_for(timeout=15000)
        assert page.locator('#enroll-move-address').inner_text() == '새 주소 미확인'
        assert page.locator('#enroll-submit').is_enabled()
        page.locator('#enroll-cancel').click()
        move.click()
        page.wait_for_timeout(100)
        assert len(held) == 2
        page.locator('#enroll-address').fill('10.16.36.88:8080')
        page.locator('#enroll-address-add').click()
        page.locator('#enroll-code').fill('7KXM-' + 'P3QA')
        held[-1].fulfill(status=200, json=_address_api()['/api/fleet/discovery/addresses'])
        page.wait_for_timeout(100)
        assert page.locator('#enroll-target').inner_text() == '10.16.36.88:8080'
        assert page.locator('#enroll-code').input_value() == '7KXM-' + 'P3QA'
        page.locator('#enroll-cancel').click()
        move.click()
        page.wait_for_timeout(100)
        assert len(held) == 3
        page.locator('#enroll-address-add').click()
        page.locator('#enroll-cancel').click()
        move.click()
        page.wait_for_timeout(100)
        assert len(held) == 4
        held[-2].fulfill(status=200, json=_address_api()['/api/fleet/discovery/addresses'])
        page.wait_for_timeout(100)
        move.click()
        assert len(held) == 4  # An old finally cannot release the newer lookup.
        page.locator('#console-token').fill('replacement-fixture-token')
        page.locator('#token-save').click()
        page.wait_for_function('() => !document.querySelector("#enroll-address-add").disabled')
        held[-1].fulfill(status=200, json=_address_api()['/api/fleet/discovery/addresses'])
        page.wait_for_timeout(100)
        assert page.locator('#enroll-dialog').is_hidden()
        move.click()
        page.wait_for_timeout(100)
        assert len(held) == 5
        page.evaluate('() => dispatchEvent(new PageTransitionEvent("pagehide"))')
        held[-1].fulfill(status=200, json=_address_api()['/api/fleet/discovery/addresses'])
        page.wait_for_timeout(100)
        assert page.locator('#enroll-dialog').is_hidden()
        assert not errors
        browser.close()


def test_viewer_sees_reasons_but_no_live_move_buttons(console_url):
    from playwright.sync_api import sync_playwright

    api = {**_address_api(), "/api/fleet/session": {"principal_id": "vic", "role": "viewer"}}
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, api)
        page.goto(console_url, wait_until="networkidle")
        page.locator("#address-banner").wait_for()
        page.wait_for_function(
            "() => document.querySelectorAll('#roster p[data-address-reason]').length === 3")
        assert page.locator('#roster ui-button[data-move-robot-id]').count() == 0
        page.goto(console_url.rsplit("/", 1)[0] + "/install.html", wait_until="networkidle")
        page.wait_for_function("() => document.querySelectorAll('#enrolled-list li[data-robot-id]').length > 0")
        assert page.locator('#enrolled-list ui-button[data-action="move"]').count() == 0
        button = page.locator('#enroll-address-add')
        assert button.is_disabled()
        assert button.get_attribute("reason") == "운용자 권한이 필요합니다"
        assert not errors
        browser.close()


def test_login_unlocks_operator_controls_before_a_slow_state_gather(console_url):
    """A robot that times out makes /api/fleet/state slow; login must not wait for it.

    Found in the 2026-10-01 live pairing run: with one unreachable robot the state gather
    took 5.1 s and the console kept "토큰 필요" and locked operator buttons until it returned.
    """
    from playwright.sync_api import sync_playwright

    held_state = """(() => {
      const originalFetch = window.fetch.bind(window);
      window.__holdState = true;
      window.fetch = (input, options) => {
        const url = new URL(String(input), location.origin).pathname;
        const auth = new Headers(options?.headers).get('Authorization');
        if (url === '/api/fleet/session' && !auth) {
          return Promise.resolve(new Response(JSON.stringify({detail: {code: 'TOKEN_REQUIRED'}}),
            {status: 401, headers: {'Content-Type': 'application/json'}}));
        }
        if (url === '/api/fleet/state' && window.__holdState) {
          return new Promise(() => {});   // a gather stuck on an unreachable robot
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
        browser, page, errors = _open_console(p, api, init_script=held_state)
        page.goto(console_url, wait_until="domcontentloaded")
        page.fill("#console-token", "operator-token")
        page.locator("#token-save").click()
        page.wait_for_function(
            "() => document.querySelector('#user-role')?.textContent.includes('운영자')", timeout=3000)
        page.wait_for_timeout(500)
        assert "접속 전" not in page.inner_text("#online-pill")
        assert page.locator("#token-save").is_enabled()
        assert not errors
        browser.close()


def test_the_install_document_owns_enrollment_and_calibration(console_url):
    """D-410 — 설치·보정 문서 렌더 계약.

    /console/install 은 기기 등록·카메라 연결 승인·경기장/맵 보정을 소유하고
    운용 표면(로스터·지도·대형·신호등)을 갖지 않는다. 전체 정지는 설치 문서의
    첫 화면에도 산다(D-280). mutation-proven: install.js의 enrollment 배선이나
    install.html의 아이디를 지우면 이 시험은 적색이어야 한다.
    """
    from playwright.sync_api import sync_playwright

    install_url = console_url.rsplit("/", 1)[0] + "/install.html"
    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("pageerror", lambda exc: errors.append(str(exc)))

        def serve_api(route):
            path = urlparse(route.request.url).path
            body = {
                "/api/fleet/session": {"principal_id": "test-operator", "role": "operator"},
                "/api/fleet/discovery": {"scanner_online": True, "scanner_state": "ok",
                                         "devices": [{"name": "rosy_04", "address": "192.168.0.4",
                                                      "port": 8080, "status": "seen"}]},
                "/api/fleet/enrollment/robots": {
                    "available": True, "static_robot_ids": ["rosy_01"],
                    "robots": [{"robot_id": "rosy_02", "address": "192.168.0.2",
                                "online": False}],
                    "alarms": [],
                },
            }.get(path)
            if body is None:
                route.fulfill(status=404, json={"detail": "no such api"})
                return
            route.fulfill(status=200, json=body)

        page.route("**/api/**", serve_api)
        page.goto(install_url, wait_until="networkidle")
        # 세션 모형을 받으면 설치 문서도 운영자로 풀린다(토큰 게이트).
        page.wait_for_function(
            "() => document.getElementById('user-role').textContent.includes('운영자')", timeout=8000)
        # 등록 패널이 목록 모형을 그린다.
        page.wait_for_function(
            "() => document.getElementById('enrolled-list')?.innerText.includes('rosy_02')", timeout=8000)

        shell = page.locator("ui-shell")
        assert shell.get_attribute("grammar") == "procedure"
        assert "설치·보정" in page.title()
        # 설치 문서의 소유물.
        for needle in ("#robot-enrollment", "#camera-link", "#vision-adjustments", "#field-detect"):
            assert page.locator(needle).count() == 1, needle
        # 운용 표면은 없다 — 그 문서는 /console 이다.
        for absent in ("#roster", "#map-canvas", "#formation-heading", "#signals-heading"):
            assert page.locator(absent).count() == 0, absent
        # 전체 정지는 두 문서 모두 첫 화면에 있다(D-280).
        assert page.locator("#estop").is_visible()
        assert page.locator('a[href="/console"]').count() >= 1
        assert not errors
        save_temp_screenshot(page, "fleet_install_procedure.png")
        browser.close()


def _stuck_robot(**stuck_extra) -> dict:
    robot = _robot("rosy_01", {"x": 1.0, "y": 1.0, "yaw": 0.0})
    robot["line_stuck"] = {
        "robot_id": "rosy_01", "stuck_id": "stuck-abc", "cause": "obstacle_ahead",
        "phase": "ASKING", "held_s": 4.0, "attempts": 0, "max_attempts": 2,
        "local_enabled": False, "ask_remaining_s": 11.0, "last_answer": None,
        "decisions": ["WAIT", "RESUME", "BACK_AND_RETRY", "MANUAL", "ABORT"],
        "front_clearance_m": 0.12, "rear_clearance_m": 0.31, "turn_clearance_m": 0.09,
        "rear_blind_m": 0.05, "preview_seq": 812, "opened_event": True,
        "robot_online": True, "observed_age_s": 0.0, "fleet_answer": None, **stuck_extra,
    }
    return robot


def test_line_stuck_panel_confirms_resume_and_shows_cores_refusal_verbatim(console_url):
    """D-407: the panel lists the stuck, RESUME needs a confirm step, BACK_AND_RETRY is off
    while local recovery is disabled, and CORE's 409 reaches the operator unchanged."""
    from playwright.sync_api import sync_playwright

    snapshot = {"fleet": {"name": "site", "online": 1, "total": 1},
                "robots": [_stuck_robot()], "ts": 0.0}
    api = {"/api/fleet/state": snapshot, "/api/fleet/map": MAP_GRID,
           "/api/fleet/formation": {"active": False, "state": "IDLE"}}
    bodies = []
    order = []
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, api)

        def claim(route):
            order.append("claim")
            route.fulfill(status=200, json={"ok": True})

        def decision(route):
            order.append("decision")
            bodies.append(json.loads(route.request.post_data or "{}"))
            route.fulfill(status=409, json={"detail": {
                "code": "STUCK_DECISION_REFUSED", "robot_id": "rosy_01", "robot_status": 409,
                "message": "RESUME refused: object_within_stop_distance"}})

        page.route("**/api/fleet/robots/rosy_01/line-stuck/claim", claim)
        page.route("**/api/fleet/robots/rosy_01/line-stuck/decision", decision)
        page.goto(console_url, wait_until="networkidle")
        panel = page.locator("#stuck-panel")
        panel.wait_for(state="visible")
        item = panel.locator('.stuck-item[data-robot-id="rosy_01"]')
        assert "앞 물체로 멈춤" in item.text_content()
        assert "0.12 m" in item.text_content() and "#812" in item.text_content()
        assert "판단 요청" in page.locator("#critical-list").text_content()
        back = item.locator('ui-button[data-decision="BACK_AND_RETRY"]')
        assert back.get_attribute("aria-disabled") == "true"
        assert "로컬 복구가 꺼져" in back.get_attribute("reason")

        # Escape cancels the confirm step without a request.
        item.locator('ui-button[data-decision="RESUME"]').click()
        confirm = item.locator(".stuck-confirm")
        confirm.wait_for(state="visible")
        page.keyboard.press("Escape")
        confirm.wait_for(state="detached")
        assert bodies == []
        assert order == ["claim"]   # D-438: the click claims; cancelling sends no decision

        # Keyboard: open the confirm step, survive a poll, then send.
        item.locator('ui-button[data-decision="RESUME"]').focus()
        page.keyboard.press("Enter")
        yes = item.locator('ui-button[data-focus-key="confirm-yes"]')
        yes.wait_for(state="visible")
        page.wait_for_function(
            "() => document.activeElement?.dataset?.focusKey === 'confirm-yes'")
        page.wait_for_timeout(1300)   # one state poll re-renders the panel
        assert yes.is_visible()
        page.keyboard.press("Enter")
        result = item.locator(".stuck-result")
        result.wait_for(state="visible")
        text = result.text_content()
        assert bodies == [{"stuck_id": "stuck-abc", "decision": "RESUME"}]
        assert order == ["claim", "claim", "decision"]   # claim always precedes the decision
        assert "정지 거리 안에 아직 물체가 있습니다" in text
        assert "STUCK_DECISION_REFUSED: RESUME refused: object_within_stop_distance" in text
        assert result.get_attribute("data-kind") == "bad"
        assert page.locator("#stuck-panel [style]").count() == 0
        assert not errors
        save_temp_screenshot(page, "fleet_line_stuck_panel.png")
        browser.close()


def _stuck_api(**stuck_extra) -> dict:
    return {"/api/fleet/state": {"fleet": {"name": "site", "online": 1, "total": 1},
                                 "robots": [_stuck_robot(**stuck_extra)], "ts": 0.0},
            "/api/fleet/map": MAP_GRID, "/api/fleet/formation": {"active": False, "state": "IDLE"}}


def test_line_stuck_answer_in_flight_blocks_a_second_submit_then_shows_success(console_url):
    """D-407 review L6: one answer per robot in flight; the accepted outcome is shown."""
    from playwright.sync_api import sync_playwright

    bodies, held = [], []
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, _stuck_api())

        def decision(route):
            bodies.append(json.loads(route.request.post_data or "{}"))
            held.append(route)   # answered below, after the in-flight checks

        page.route("**/api/fleet/robots/rosy_01/line-stuck/decision", decision)
        page.goto(console_url, wait_until="networkidle")
        item = page.locator('#stuck-panel .stuck-item[data-robot-id="rosy_01"]')
        wait = item.locator('ui-button[data-decision="WAIT"]')
        wait.click()
        page.wait_for_function("() => document.querySelector("
                               "'#stuck-panel ui-button[data-decision=\"WAIT\"]')"
                               "?.getAttribute('aria-disabled') === 'true'")
        assert "답을 보내는 중" in wait.get_attribute("reason")
        wait.click(force=True)
        item.locator('ui-button[data-decision="ABORT"]').click(force=True)
        page.wait_for_timeout(300)
        assert len(bodies) == 1 and len(held) == 1
        held[0].fulfill(status=200, json={"robot_id": "rosy_01", "actor_id": "op",
                                          "answer": {}, "result": {"outcome": "hold"}})
        result = item.locator(".stuck-result")
        result.wait_for(state="visible")
        assert result.get_attribute("data-kind") == "good"
        assert "rosy_01 대기: 대기로 답했습니다" in result.text_content()
        assert bodies == [{"stuck_id": "stuck-abc", "decision": "WAIT"}]
        assert wait.get_attribute("aria-disabled") == "false"
        assert not errors
        browser.close()


def test_line_stuck_confirm_follows_the_live_stuck_and_an_offline_robot(console_url):
    """D-407 review L2/L3/L6: a replaced stuck drops the confirm step; an unreachable robot
    disables every answer and the pending confirm's send button with the same reason."""
    from playwright.sync_api import sync_playwright

    api = _stuck_api(local_enabled=True)
    posts = []
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, api, posts=posts)
        page.goto(console_url, wait_until="networkidle")
        item = page.locator('#stuck-panel .stuck-item[data-robot-id="rosy_01"]')
        resume = item.locator('ui-button[data-decision="RESUME"]')
        resume.click()
        item.locator(".stuck-confirm").wait_for(state="visible")
        assert resume.get_attribute("aria-expanded") == "true"

        # CORE closed that stuck and opened another: the confirm step must not carry over.
        api["/api/fleet/state"] = _stuck_api(local_enabled=True, stuck_id="stuck-new")[
            "/api/fleet/state"]
        page.locator('.stuck-item[data-stuck-id="stuck-new"]').wait_for(state="attached")
        assert page.locator("#stuck-panel .stuck-confirm").count() == 0
        assert page.locator('#stuck-panel ui-button[data-decision="RESUME"]').get_attribute(
            "aria-expanded") == "false"

        # Open the confirm step again, then the robot drops off: send is blocked too.
        page.locator('#stuck-panel ui-button[data-decision="BACK_AND_RETRY"]').click()
        yes = page.locator('#stuck-panel ui-button[data-focus-key="confirm-yes"]')
        yes.wait_for(state="visible")
        assert yes.get_attribute("aria-disabled") == "false"
        api["/api/fleet/state"] = _stuck_api(local_enabled=True, stuck_id="stuck-new",
                                             robot_online=False)["/api/fleet/state"]
        page.locator("#stuck-panel .stuck-item.offline").wait_for(state="attached")
        buttons = page.locator("#stuck-panel .stuck-actions ui-button")
        assert buttons.count() == 5
        for index in range(5):
            assert buttons.nth(index).get_attribute("aria-disabled") == "true"
            assert "로봇 연결이 끊겼습니다" in buttons.nth(index).get_attribute("reason")
        assert yes.get_attribute("aria-disabled") == "true"
        assert "로봇 연결이 끊겼습니다" in yes.get_attribute("reason")
        yes.click(force=True)
        page.wait_for_timeout(300)
        assert not [p for p in posts if p[0] == "POST" and p[1].endswith("/line-stuck/decision")]
        assert not errors
        browser.close()


def test_development_mode_console_gets_a_session_and_shows_the_badge(console_url):
    # D-473 4: no stored token -> 401 -> connection says development -> one session, badge stays up.
    from playwright.sync_api import sync_playwright

    issued: list[str] = []

    def serve_api(route):
        path = urlparse(route.request.url).path
        authorization = route.request.headers.get("authorization", "")
        if path == "/api/fleet/auth/connection":
            route.fulfill(status=200, json={"mode": "development"})
        elif path == "/api/fleet/auth/development-session" and route.request.method == "POST":
            issued.append(f"dev-token-{len(issued) + 1}")
            route.fulfill(status=201, json={"token": issued[-1], "principal_id": "development-0a1b2c3d",
                                            "role": "operator", "expires_at": "2026-10-06T12:00:00+00:00"})
        elif not authorization.startswith("Bearer dev-token-"):
            route.fulfill(status=401, json={"detail": {"code": "UNAUTHORIZED"}})
        elif path == "/api/fleet/session":
            route.fulfill(status=200, json={"principal_id": "development-0a1b2c3d", "role": "operator"})
        elif path in API:
            route.fulfill(status=200, json=API[path])
        else:
            route.fulfill(status=404, json={"detail": "no such api"})

    with sync_playwright() as p:
        browser, page, errors = open_page(p, 1920, 1080)
        page.route("**/api/**", serve_api)
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function(
            "() => document.getElementById('user-role').textContent.includes('development-0a1b2c3d')",
            timeout=8000)

        assert page.is_visible("#development-badge")
        assert page.inner_text("#development-badge").strip() == "개발 연결 모드"
        assert page.evaluate("() => sessionStorage.getItem('rosy-console-token')") == "dev-token-1"
        assert issued == ["dev-token-1"], "one 401 must ask for one session, not loop"
        assert not errors, f"페이지 오류: {errors}"
        save_temp_screenshot(page, "fleet_console_development_mode.png")
        browser.close()


def test_paired_console_keeps_the_token_field_and_never_asks_for_a_session(console_url):
    from playwright.sync_api import sync_playwright

    posts: list[str] = []

    def serve_api(route):
        path = urlparse(route.request.url).path
        if route.request.method == "POST":
            posts.append(path)
        if path == "/api/fleet/auth/connection":
            route.fulfill(status=200, json={"mode": "paired"})
        else:
            route.fulfill(status=401, json={"detail": {"code": "UNAUTHORIZED"}})

    with sync_playwright() as p:
        browser, page, errors = open_page(p, 1920, 1080)
        page.route("**/api/**", serve_api)
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function("() => document.getElementById('online-pill').textContent === '접속 전'",
                               timeout=8000)

        assert page.is_hidden("#development-badge")
        assert page.is_visible("#console-token")
        assert posts == []
        assert not errors, f"페이지 오류: {errors}"
        browser.close()
