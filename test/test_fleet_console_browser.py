"""D-131 1단계 — 군집 제어 오버레이의 브라우저 렌더 계약 (옵트인).

ROSY_RUN_BROWSER_TESTS=1 로 실행한다. 가짜 API 응답(활성 대형 + 중재 대기 +
릴레이 단절 팔로워)으로 콘솔을 띄워, 후단이 주는 상태가 실제로 그려지는지
단언한다. mutation-proven: drawFormationOverlay/drawMediation 호출을 지우면
이 시험은 적색이어야 한다(test/ AGENTS 규정).
"""

from __future__ import annotations

import os
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
#: D-129·D-1005 — 공용 L1 자산의 단일 파일. fleet 사본은 없다.
CANONICAL_TOKENS = ROOT / "src" / "hmi" / "web_common" / "tokens.css"

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
            if path == "/common/tokens.css":
                return str(CANONICAL_TOKENS)
            if path.startswith("/console/assets/"):
                path = "/" + path[len("/console/assets/"):]
            return super().translate_path(path)

        def log_message(self, *args):  # 시험 출력을 조용히
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
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


def _open_console(playwright, api, posts=None, init_script=""):
    """D-153 회차4 — 상태별 Fleet G2 셀. api 값은 (status, body) 또는 body."""
    browser, page, errors = open_page(playwright, 1920, 1080)

    def serve_api(route):
        path = urlparse(route.request.url).path
        if posts is not None:
            posts.append((route.request.method, path))
        entry = api.get(path)
        if entry is None:
            route.fulfill(status=404, json={"detail": "no such api"})
            return
        status, body = entry if isinstance(entry, tuple) else (200, entry)
        route.fulfill(status=status, json=body)

    page.route("**/api/**", serve_api)
    if init_script:
        page.add_init_script(init_script)
    return browser, page, errors


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
        assert not errors
        save_temp_screenshot(page, "fleet_console_gather-error.png")
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
        assert not errors, f"페이지 오류: {errors}"
        browser.close()

    assert "등록된 모든 로봇을 정지시킵니다" in confirms[0]
    assert declined == []
    assert any(post == ("POST", "/api/fleet/estop") for post in posts)


DELAYED_FORMATION = {
    **FORMATION,
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
    "pending_triggers": ["stream"],
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
        page.keyboard.press("ArrowDown")
        page.wait_for_function(
            "() => document.activeElement"
            " && document.activeElement.matches('#roster article')"
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
    return { top: Math.round(b.top), bottom: Math.round(b.bottom) };
  };
  return {
    docOverflow: document.documentElement.scrollHeight - window.innerHeight,
    signals: inside('.signals'),
    formation: inside('.formation'),
    rosterPanel: inside('main > .panel[aria-labelledby="roster-heading"]'),
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
