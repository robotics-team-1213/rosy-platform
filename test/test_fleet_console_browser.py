"""D-131 1단계 — 군집 제어 오버레이의 브라우저 렌더 계약 (옵트인).

ROSY_RUN_BROWSER_TESTS=1 로 실행한다. 가짜 API 응답(활성 대형 + 중재 대기 +
릴레이 단절 팔로워)으로 콘솔을 띄워, 후단이 주는 상태가 실제로 그려지는지
단언한다. mutation-proven: drawFormationOverlay/drawMediation 호출을 지우면
이 시험은 적색이어야 한다(test/ AGENTS 규정).
"""

from __future__ import annotations

import os
import json
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
WEB = ROOT / "src" / "site" / "fleet" / "fleet" / "server" / "web"
#: D-129·D-157 — 공용 자산의 단일 파일. Fleet 사본은 없다.
WEB_COMMON = ROOT / "src" / "hmi" / "web_common"

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
                if name in {"tokens.css", "theme.js", "components.css", "ui.js", "core_ui_logic.js"}:
                    return str(WEB_COMMON / name)
            if path.startswith("/console/assets/"):
                path = "/" + path[len("/console/assets/"):]
            return super().translate_path(path)

        def log_message(self, *args):  # 시험 출력을 조용히
            pass

    # Windows may assign Chromium-blocked ports (for example 10080) for port 0.
    for port in range(40000, 40100):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        except OSError:
            continue
        else:
            break
    else:
        raise RuntimeError("could not allocate a browser-safe local port")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/index.html"
    server.shutdown()


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
            " el.querySelectorAll('.tag.crit, .tag.warn').length]))"
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


def test_slow_initial_gather_does_not_spawn_overlapping_polls(console_url):
    """The loading state keeps one state request in flight until it resolves."""
    from playwright.sync_api import sync_playwright

    delayed_state = """(() => {
      const originalFetch = window.fetch.bind(window);
      window.__stateCalls = 0;
      window.fetch = (input, options) => {
        if (String(input) === '/api/fleet/state') {
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
        page.goto(console_url, wait_until="domcontentloaded")
        page.wait_for_function("() => window.__stateCalls === 1")
        assert "로봇 목록 불러오는 중" in page.inner_text("#roster")
        page.wait_for_timeout(1400)
        assert page.evaluate("window.__stateCalls") == 1
        assert "로봇 목록 불러오는 중" in page.inner_text("#roster")
        assert page.locator(".queues-panel").is_hidden()
        assert page.locator("#roster-toggle").is_hidden()
        save_temp_screenshot(page, "fleet_console_slow_loading.png")
        page.evaluate("snapshot => window.__releaseState(snapshot)", SNAPSHOT)
        page.wait_for_function("() => document.querySelector('#online-pill')?.textContent === '3/3 연결'")
        assert "rosy_03" in page.inner_text("#roster")
        save_temp_screenshot(page, "fleet_console_slow_recovered.png")
        assert not errors
        browser.close()


def test_gather_loss_removes_last_known_robot_position(console_url):
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
        save_temp_screenshot(page, "fleet_console_gather-lost-after-live.png")
        api["/api/fleet/state"] = {"fleet": {"name": "site", "online": 1, "total": 1},
                                   "robots": [robot]}
        page.wait_for_function("() => document.querySelector('#roster article')?.textContent.includes('1.00')")
        assert "로봇 위치 확인 불가" not in page.inner_text("#map-tag")
        assert not errors
        browser.close()


DECLINE_ESTOP_CONFIRM = DECLINE_CONFIRM


def test_fleet_estop_requires_confirm_and_decline_blocks_it(console_url):
    """D-92(a) — 전체 정지는 confirm을 지나며 거부하면 나가지 않는다."""
    from playwright.sync_api import sync_playwright

    api = {
        "/api/fleet/state": SNAPSHOT,
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": FORMATION,
        "/api/fleet/estop": {"stopped": 3, "total": 3, "robots": []},
    }
    posts: list[tuple[str, str]] = []
    with sync_playwright() as p:
        browser, page, errors = _open_console(
            p, api, posts=posts, init_script=DECLINE_ESTOP_CONFIRM)
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function(
            "() => (window.__swarmOverlay?.slots || 0) === 2", timeout=8000
        )
        save_temp_screenshot(page, "fleet_estop_preconfirm.png")
        page.locator("#estop").click()
        page.wait_for_function("() => window.__confirms.length === 1")
        declined = [post for post in posts if post[1] == "/api/fleet/estop"]
        accept_confirm(page)
        page.locator("#estop").click()
        for _ in range(40):
            if any(post == ("POST", "/api/fleet/estop") for post in posts):
                break
            page.wait_for_timeout(100)
        confirms = page.evaluate("window.__confirms")
        page.get_by_text("정지 요청 응답: 3/3 · 물리 정지 미확인").wait_for()
        assert not errors, f"페이지 오류: {errors}"
        browser.close()

    assert "등록된 모든 로봇을 정지시킵니다" in confirms[0]
    assert declined == []
    assert any(post == ("POST", "/api/fleet/estop") for post in posts)


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
    "reason": ["STREAM_LOST"],
    "pending_triggers": [["stream", "rosy_03"]],
}

UNREACHABLE_SNAPSHOT = {
    **SNAPSHOT,
    "fleet": {"name": "site", "online": 2, "total": 3},
    "robots": [
        SNAPSHOT["robots"][0],
        SNAPSHOT["robots"][1],
        _robot(
            "rosy_03", {"x": 0.45, "y": 0.4, "yaw": 0.0},
            online=False,
            error={"reachable": False, "code": "CONNECT_ERROR"},
        ),
    ],
}


def test_delayed_follower_stream_is_named_in_the_roster(console_url):
    """FOR-003 — 바닥 Hz 아래 팔로워는 '지연'으로, 단절 팔로워는 '끊김'으로 갈린다."""
    from playwright.sync_api import sync_playwright

    api = {
        "/api/fleet/state": SNAPSHOT,
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": DELAYED_FORMATION,
    }
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, api)
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function(
            "() => (window.__swarmOverlay?.slots || 0) === 2", timeout=8000
        )
        roster = page.inner_text("#roster")
        assert "지연" in roster, "1.2 Hz 팔로워에 지연 태그가 없다"
        assert "끊김" in roster
        assert not errors
        save_temp_screenshot(page, "fleet_console_delayed.png")
        browser.close()


def test_unreachable_robot_is_never_drawn_healthy(console_url):
    """concept 16 §5 — 연락 두절은 자기 상태다. '닿지 않음'과 이유가 보여야 한다."""
    from playwright.sync_api import sync_playwright

    api = {
        "/api/fleet/state": UNREACHABLE_SNAPSHOT,
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": {"active": False, "state": "IDLE"},
    }
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, api)
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function(
            "() => document.getElementById('online-pill')?.textContent === '2/3 연결'"
        )
        roster = page.inner_text("#roster")
        assert "닿지 않음: CONNECT_ERROR" in roster
        assert "OFFLINE" in roster
        assert not errors
        save_temp_screenshot(page, "fleet_console_unreachable.png")
        browser.close()


@pytest.mark.parametrize("safety, expected, reason", [
    (None, "정보 없음", "안전 상태를 확인할 수 없어"),
    ({"estop": True}, "E-STOP", "비상정지가 활성화되어"),
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
        safety_row = card.locator(".facts div").filter(has_text="SAFETY")
        # E-STOP은 값이 아니라 crit 태그로 렌더된다(D-202) — 요소 타입이 아니라
        # 행의 값으로 단정한다.
        assert expected in safety_row.inner_text()
        assert reason in card.inner_text()
        assert card.locator("ui-button[data-goal-robot-id]").evaluate("node => node.disabled")
        assert not card.locator("ui-button").nth(1).evaluate("node => node.disabled")
        assert not errors
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
            " === 'HOLDING'"
        )
        assert "warn" in page.locator("#formation-state").get_attribute("class")
        assert page.locator("#formation-resume").is_enabled()
        assert not errors
        save_temp_screenshot(page, "fleet_console_holding.png")
        browser.close()


def test_formation_read_loss_hides_last_running_evidence_and_recovers(console_url):
    """A failed poll must not present an old leader or relay rate as current."""
    from playwright.sync_api import sync_playwright

    api = {
        "/api/fleet/state": SNAPSHOT,
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": FORMATION,
    }
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, api)
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function("() => document.querySelector('#formation-state')?.textContent === 'RUNNING'")
        assert "9.8 Hz" in page.inner_text("#formation-detail")
        assert page.evaluate("window.__swarmOverlay?.slots") == 2

        api["/api/fleet/formation"] = (503, {"detail": {"code": "FORMATION_UNAVAILABLE"}})
        page.wait_for_function("() => document.querySelector('#formation-state')?.textContent === '확인 불가'",
                               timeout=7000)
        assert "9.8 Hz" not in page.inner_text("#formation-detail")
        assert "리더 rosy_01" not in page.inner_text("#formation-detail")
        assert page.evaluate("window.__swarmOverlay?.slots") == 0
        for control in ("formation-start", "formation-reform", "formation-resume"):
            assert page.locator(f"#{control}").is_disabled()
        save_temp_screenshot(page, "fleet_formation_read_lost.png")

        api["/api/fleet/formation"] = FORMATION
        page.wait_for_function("() => document.querySelector('#formation-state')?.textContent === 'RUNNING'",
                               timeout=7000)
        assert "9.8 Hz" in page.inner_text("#formation-detail")
        assert page.evaluate("window.__swarmOverlay?.slots") == 2
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
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function("() => document.querySelector('#discovery-list')?.textContent.includes('192.0.2.10')")

        api["/api/fleet/discovery"] = (503, {"detail": {"code": "SCANNER_UNAVAILABLE"}})
        page.wait_for_function("() => document.querySelector('#discovery-status')?.textContent === '발견 상태 확인 불가'",
                               timeout=7000)
        assert "192.0.2.10" not in page.inner_text("#discovery-list")
        assert "발견 목록을 확인할 수 없습니다" in page.inner_text("#discovery-list")

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
        assert page.locator("#log .log-empty strong").inner_text() == "최근 이벤트가 없습니다"
        assert "관제 요청과 연결 상태 변화" in page.locator("#log .log-empty span").inner_text()
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
        assert page.evaluate("window.__confirms.length") == 1
        assert "rosy_02" in page.evaluate("window.__confirms[0]")
        assert not any(method == "POST" and path == goal_path for method, path in posts)
        page.keyboard.press("Escape")
        assert page.locator(".robot.selected").count() == 0
        assert page.evaluate("document.activeElement?.dataset.goalRobotId") == "rosy_02"

        aim.click()
        accept_confirm(page)
        page.keyboard.press("Enter")
        page.wait_for_function("() => document.querySelector('#log')?.textContent.includes('미션 하달')")
        assert sum(method == "POST" and path == goal_path for method, path in posts) == 1
        assert page.locator("#log .log-empty").count() == 0
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
        page.wait_for_function("() => document.querySelectorAll('#roster article').length === 3")
        page.wait_for_function("() => !document.querySelector('#roster article ui-button')?.disabled")
        page.locator("#roster article").filter(has_text="rosy_01").locator("ui-button").first.click()
        canvas_box = page.locator("#map-canvas").bounding_box()
        assert canvas_box
        page.mouse.click(canvas_box["x"] + canvas_box["width"] / 2,
                         canvas_box["y"] + canvas_box["height"] / 2)
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
    return { top: Math.round(b.top), bottom: Math.round(b.bottom), height: Math.round(b.height) };
  };
  return {
    docOverflow: document.documentElement.scrollHeight - window.innerHeight,
    mapPanel: inside('main > .panel[aria-labelledby="map-heading"]'),
    mapCanvas: inside('#map-canvas'),
    visionFrame: inside('#vision-frame'),
    visionPreview: inside('.vision-preview'),
    signals: inside('.signals'),
    formation: inside('.formation'),
    rosterPanel: inside('main > .panel[aria-labelledby="roster-heading"]'),
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
    for name in ("signals", "formation", "rosterPanel"):
        box = fit[name]
        assert box is not None and box["bottom"] <= fit["vh"] and box["top"] >= 0, (
            f"{name} 이(가) 뷰포트 밖이다(D-201): {box}"
        )
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
            "같은 네트워크에서 발견",
            "대형",
            "신호등",
        ]
        for name in headings:
            assert page.get_by_role("heading", name=name, exact=True).count() == 1
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
        page.goto(console_url, wait_until="networkidle")
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
        page.goto(console_url, wait_until="networkidle")
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
        page.wait_for_function("() => window.__confirms?.length === 1")
        confirm = page.evaluate("window.__confirms[0]")
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
        page.locator("#roster-toggle").click()
        page.wait_for_function("() => document.querySelectorAll('#roster article').length === 3")
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
          stop: document.querySelector('#estop').getBoundingClientRect().toJSON(),
          status: document.querySelector('#online-pill').getBoundingClientRect().toJSON(),
          operator: document.querySelector('#user-role').getBoundingClientRect().toJSON(),
          clock: document.querySelector('#clock').getBoundingClientRect().toJSON(),
          statusRow: getComputedStyle(document.querySelector('#online-pill')).gridRowStart,
          clockRow: getComputedStyle(document.querySelector('#clock')).gridRowStart,
          stopScopeHidden: getComputedStyle(document.querySelector('#estop small')).display === 'none',
          stopAccessibleName: document.querySelector('#estop').getAttribute('aria-label'),
        })""")
        browser.close()
    assert errors == []
    assert layout["overflow"] == 0, layout["outside"]
    assert layout["stop"]["right"] <= width, layout
    assert layout["status"]["right"] <= width, layout
    assert layout["brand"]["right"] <= layout["status"]["left"] or layout["brand"]["bottom"] <= layout["status"]["top"], layout
    assert layout["headerRows"] <= 4, layout
    assert layout["headerOverlaps"] == [], layout
    if width <= 384:
        assert layout["statusRow"] == layout["clockRow"] == "1", layout
        assert layout["stopScopeHidden"], layout
        assert layout["stopAccessibleName"] == "전체 로봇 정지", layout


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
