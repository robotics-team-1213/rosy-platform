"""Optional browser-level safety test for ordered hold-to-drive shutdown."""

from __future__ import annotations

import os
from urllib.parse import urlparse
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "core" / "core_api_web" / "core_api_web" / "web"
#: Production serves `/common/*` from the web_common package (core_api_web
#: mounts it; `test_ui_route.py` pins the 200s). The harness must mirror that
#: mount — app.js imports `/common/core_ui_logic.js` absolutely, and a request
#: with no route escapes to real DNS (rosy.test does not resolve) and kills the
#: boot before the first assertion.
WEB_COMMON = ROOT / "src" / "core" / "web_common"

from browser_harness import DECLINE_CONFIRM, accept_confirm, open_page  # noqa: E402

#: F-09 — 정상 상태의 따뜻한 색 예산 스캔(D-82: 따뜻한 것이 보이면 언제나
#: 무언가 잘못된 것이다). 캔버스 fillStyle 정규화로 토큰·계산색을 같은 형식으로
#: 맞춘다(F-08 동어반복 교훈). 숨은 요소는 제외(F-06 가시성 교훈).
WARM_SCAN = """() => {
    const cs = getComputedStyle(document.documentElement);
    const ctx = document.createElement('canvas').getContext('2d');
    const norm = (v) => { ctx.fillStyle = v.trim(); return ctx.fillStyle; };
    const warm = new Set([norm(cs.getPropertyValue('--status-warn')),
                          norm(cs.getPropertyValue('--status-crit'))]);
    const hits = [];
    for (const el of document.querySelectorAll('*')) {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        const s = getComputedStyle(el);
        if (warm.has(norm(s.color)) || warm.has(norm(s.backgroundColor))) {
            hits.push(`${el.tagName.toLowerCase()}#${el.id || '-'}`
                      + `.${(el.className || '-').toString().slice(0, 40)}`);
        }
    }
    return hits;
}"""

pytestmark = pytest.mark.skipif(
    os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
    reason="set ROSY_RUN_BROWSER_TESTS=1 to run the optional Chromium regression",
)

MAP_STUB = """
export function createFieldMap({canvas, empty, status}) {
  function paint() {
    if (!canvas) return;
    canvas.width = 720;
    canvas.height = 360;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#111b22';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = '#70818b';
    ctx.lineWidth = 12;
    ctx.strokeRect(28, 24, 664, 312);
    ctx.strokeStyle = '#d7e0df';
    ctx.lineWidth = 3;
    ctx.setLineDash([18, 15]);
    ctx.beginPath();
    ctx.moveTo(60, 180);
    ctx.lineTo(660, 180);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = '#f5f3df';
    for (let x = 350; x <= 430; x += 16) ctx.fillRect(x, 88, 9, 184);
    ctx.fillStyle = '#d84a3a';
    ctx.fillRect(330, 78, 7, 204);
    ctx.fillStyle = '#35b879';
    ctx.beginPath();
    ctx.arc(230, 180, 12, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#dbe6e4';
    ctx.font = 'bold 18px sans-serif';
    ctx.fillText('map_260905_update_v2 · HOST-SIM', 48, 55);
    if (empty) empty.hidden = true;
    if (status) status.textContent = 'HOST-SIM MAP · 720×360';
  }
  requestAnimationFrame(paint);
  return { refresh: async () => { paint(); return {}; }, setPose: paint };
}
"""

FETCH_INIT = """
sessionStorage.setItem('rosy.dashboard.token', 'operator-test-token');
window.__teleopCommands = [];
window.__apiCalls = [];
window.__cameraSequence = 7;
window.__cameraFrameStatus = 200;
window.__nativeFetch = window.fetch.bind(window);
window.__trafficReadback = {
  status: {
    mode: 'MONITOR_ONLY', state: 'FOLLOW', reason: 'clear_road',
    signal_colour: 'GREEN', stop_line_distance_m: null,
    scene_revision: 'road-scene-v1', policy_revision: 'traffic-policy-v1',
  },
  active: {
    mode: 'MONITOR_ONLY', map_id: 'map_260905_update_v2',
    scene_revision: 'road-scene-v1', policy_revision: 'traffic-policy-v1',
    approach_distance_m: 0.35, stop_distance_m: 0.12,
    stop_dwell_s: 0.5, stale_after_s: 0.4,
    min_confidence: 0.5, proceed_speed_scale: 0.5,
  },
  staged: null,
  simulation_signal: {available: true, colour: 'GREEN'},
};
window.WebSocket = class extends EventTarget {
  constructor() { super(); setTimeout(() => this.dispatchEvent(new Event('open')), 0); }
  close() {}
};
window.fetch = async (input, options = {}) => {
  const url = new URL(typeof input === 'string' ? input : input.url, location.href);
  const path = url.pathname;
  const method = (options.method || 'GET').toUpperCase();
  let parsed = null;
  if (options.body) {
    try { parsed = JSON.parse(options.body); } catch (_error) { parsed = options.body; }
  }
  window.__apiCalls.push({ method, path, search: url.search, body: parsed });
  const authorization = new Headers(options.headers || {}).get('Authorization') || '';
  if (authorization.includes('bad-token')) {
    return new Response(JSON.stringify({error: {code: 'UNAUTHORIZED', message: 'invalid token'}}), {
      status: 401, headers: {'Content-Type': 'application/json'},
    });
  }
  const bodies = {
    '/api/v1/robot/state': {
      robot_id: 'rosy_01', online: true, mode: 'MANUAL', navigation: 'IDLE',
      pose: {x: 1.25, y: -0.5, yaw: 0.3}, velocity: {linear: 0, angular: 0},
      battery: {percent: 90, voltage: 7.5}, safety: {estop: false}, seq: 1,
      evidence: {
        pose: {evidence: 'fresh', stale_after_s: 2.0},
        velocity: {evidence: 'fresh', stale_after_s: 0.5},
      },
      traffic_policy: {
        mode: 'MONITOR_ONLY', state: 'FOLLOW', reason: 'clear_road',
        signal_colour: 'GREEN', stop_line_distance_m: null,
        scene_revision: 'road-scene-v1', policy_revision: 'traffic-policy-v1',
      },
    },
    '/api/v1/system/runtime': {
      os: {}, cpu: {}, memory: {}, storage: {},
      network: {throughput: {rx_bytes_per_second: null, tx_bytes_per_second: null}},
      ros: null,
    },
    '/api/v1/system/info': {name: 'Rosy', robot_id: 'rosy_01', hardware_model: 'test'},
    '/api/v1/system/capabilities': {
      teleop: true, slam: true, docking: {supported: false},
      navigation: {goal_navigation: true},
    },
    '/api/v1/system/inventory': {
      descriptors: [
        {id: 'mobility.move', available: true, state: 'available', reason: null},
      ],
    },
    '/api/v1/safety/state': {
      estop: false, source: null, fleet_loss_policy: 'STOP',
      limits: {max_linear: 0.2, max_angular: 0.8, manual_linear: 0.15, manual_angular: 0.6},
      battery: {warning_percent: 20, critical_percent: 10, deep_percent: 5, critical_policy: 'RETURN_HOME'},
    },
    '/api/v1/events': {events: []},
    '/api/v1/traffic': window.__trafficReadback,
    '/api/v1/vision/front/status': {
      available: true, stale: false, source: 'HOST-SIM',
      frame_id: 'front_camera_link', captured_at: 42.25,
      age_ms: 80, width: 640, height: 360,
      overlay: 'semantic-road-v1', sequence: window.__cameraSequence,
    },
    '/api/v1/waypoints': {waypoints: []},
    '/api/v1/docking/status': {state: 'UNDOCKED', dock_id: null, supported: false},
    '/api/v1/docking/docks': {docks: []},
    '/api/v1/host/network': {available: false, detail: 'no agent'},
    '/api/v1/host/release': {available: false, detail: 'no agent'},
    '/api/v1/host/commissioning': {runtime_mode: 'core', fleet_hold: true, detail: 'core'},
  };
  if (window.__rosyStateOverrides?.robot_state) {
    Object.assign(bodies['/api/v1/robot/state'], window.__rosyStateOverrides.robot_state);
  }
  if (window.__rosyVisionOverride) {
    Object.assign(bodies['/api/v1/vision/front/status'], window.__rosyVisionOverride);
  }
  if (window.__rosyRuntimeOverride) {
    Object.assign(bodies['/api/v1/system/runtime'], window.__rosyRuntimeOverride);
  }
  if (window.__rosyHostNetworkOverride) {
    Object.assign(bodies['/api/v1/host/network'], window.__rosyHostNetworkOverride);
  }
  if (path === '/api/v1/teleop') {
    const command = JSON.parse(options.body);
    if (command.linear !== 0 || command.angular !== 0) {
      await new Promise((resolve) => setTimeout(resolve, 650));
    }
    window.__teleopCommands.push(command);
    return new Response(JSON.stringify({accepted: true}), {
      status: 200, headers: {'Content-Type': 'application/json'},
    });
  }
  if (path === '/api/v1/vision/front/frame') {
    if (window.__cameraFrameStatus !== 200) {
      return new Response(JSON.stringify({error: {code: 'CAMERA_RATE_LIMITED'}}), {
        status: window.__cameraFrameStatus,
        headers: {'Content-Type': 'application/json'},
      });
    }
    const mock = await window.__nativeFetch('/mock-camera.jpg');
    return new Response(await mock.blob(), {
      status: 200,
      headers: {
        'Content-Type': 'image/jpeg',
        'X-Rosy-Camera-Sequence': String(window.__cameraSequence),
        'X-Rosy-Camera-Captured-At': '42.25',
      },
    });
  }
  if (method === 'POST' && path === '/api/v1/waypoints') {
    return new Response(JSON.stringify(parsed), {
      status: 201, headers: {'Content-Type': 'application/json'},
    });
  }
  if (method === 'POST' && path === '/api/v1/traffic/policy/stage') {
    const current = bodies['/api/v1/traffic'];
    current.staged = {...current.active, ...parsed};
    return new Response(JSON.stringify(current), {
      status: 200, headers: {'Content-Type': 'application/json'},
    });
  }
  if (method === 'POST' && path === '/api/v1/traffic/policy/apply') {
    const current = bodies['/api/v1/traffic'];
    current.active = current.staged;
    current.staged = null;
    current.status = {...current.status, mode: current.active.mode,
      policy_revision: current.active.policy_revision};
    return new Response(JSON.stringify(current), {
      status: 200, headers: {'Content-Type': 'application/json'},
    });
  }
  if (method === 'PUT' && path === '/api/v1/traffic/simulation/signal') {
    bodies['/api/v1/traffic'].simulation_signal.colour = parsed.colour;
    return new Response(JSON.stringify(
      bodies['/api/v1/traffic'].simulation_signal
    ), {status: 200, headers: {'Content-Type': 'application/json'}});
  }
  if (method === 'PUT' && path === '/api/v1/safety/limits') {
    return new Response(JSON.stringify({
      estop: false, fleet_loss_policy: 'STOP',
      limits: {
        max_linear: 0.2, max_angular: 0.8,
        manual_linear: parsed.manual_linear, manual_angular: parsed.manual_angular,
      },
    }), { status: 200, headers: {'Content-Type': 'application/json'} });
  }
  if (method === 'POST' && path === '/api/v1/docking/types') {
    return new Response(JSON.stringify(parsed), {
      status: 200, headers: {'Content-Type': 'application/json'},
    });
  }
  if (method === 'POST' && path === '/api/v1/docking/docks') {
    return new Response(JSON.stringify(parsed), {
      status: 200, headers: {'Content-Type': 'application/json'},
    });
  }
  if (path === '/api/v1/logs/audit') {
    return new Response(JSON.stringify({events: []}), {
      status: 200, headers: {'Content-Type': 'application/json'},
    });
  }
  return new Response(JSON.stringify(bodies[path] ?? {}), {
    status: 200, headers: {'Content-Type': 'application/json'},
  });
};
"""


def _launch_page(playwright, extra_init=""):
    browser, page, _errors = open_page(playwright, 390, 844)
    html = (WEB / "index.html").read_text(encoding="utf-8")
    page.route(
        "http://rosy.test/dashboard",
        lambda route: route.fulfill(status=200, content_type="text/html", body=html),
    )

    def _serve_style(route):
        name = Path(urlparse(route.request.url).path).name
        source = WEB / name
        if not source.is_file():
            route.fulfill(status=404, body="")
            return
        route.fulfill(
            status=200,
            content_type="text/css",
            body=source.read_text(encoding="utf-8"),
        )

    page.route("http://rosy.test/dashboard/assets/*.css", _serve_style)

    def _serve_module(route):
        """Serve every real ES module from the tree; only map.js is stubbed.

        Listing files here meant a new module 404'd silently and the page died
        before the first assertion, with the failure pointing at the assertion
        rather than the missing import.
        """
        name = Path(urlparse(route.request.url).path).name
        if name == "map.js":
            body = MAP_STUB
        else:
            source = WEB / name
            if not source.is_file():
                route.fulfill(status=404, body="")
                return
            body = source.read_text(encoding="utf-8")
        route.fulfill(status=200, content_type="application/javascript", body=body)

    page.route("http://rosy.test/dashboard/assets/*.js", _serve_module)
    camera = (
        ROOT / "docs" / "validation" / "semantic-road-2026-09-21"
        / "camera_preview_demo.jpg"
    )
    page.route(
        "http://rosy.test/mock-camera.jpg",
        lambda route: route.fulfill(
            status=200, content_type="image/jpeg", body=camera.read_bytes()),
    )

    def _serve_common(route):
        name = Path(urlparse(route.request.url).path).name
        source = WEB_COMMON / name
        if not source.is_file():
            route.fulfill(status=404, body="")
            return
        route.fulfill(
            status=200,
            content_type=(
                "text/css" if name.endswith(".css") else "application/javascript"
            ),
            body=source.read_text(encoding="utf-8"),
        )

    page.route("http://rosy.test/common/*", _serve_common)
    page.add_init_script(script=FETCH_INIT)
    if extra_init:
        # D-153 G2 상태 매트릭스 — FETCH_INIT 뒤에 붙어 오버라이드/토큰을 덮어쓴다.
        page.add_init_script(script=extra_init)
    page.on("dialog", lambda dialog: dialog.accept())
    return browser, page


def test_delayed_positive_request_cannot_arrive_after_release_zero():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page = _launch_page(playwright)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.goto("http://rosy.test/dashboard", wait_until="domcontentloaded", timeout=5_000)
        page.wait_for_function(
            "document.getElementById('robot-mode')?.textContent === 'MANUAL'"
        )
        # F-09 — 정상(MANUAL, fresh) 상태에서 보이는 따뜻한 색은 E-Stop 채움
        # 하나뿐이다(Law 3/D-82 "위험은 채움이다"). 실투 스캔 실측(회차 9).
        page.wait_for_timeout(300)
        warm = page.evaluate(WARM_SCAN)
        assert set(warm) <= {"button#emergency-stop.stop-button"}, (
            f"정상 상태의 경보 예산 밖 따뜻한 색: {warm}"
        )
        assert page.locator("#network-rx-rate").inner_text() == "—"
        assert page.locator("#network-tx-rate").inner_text() == "—"
        assert "그래프 수집 불가" in page.locator("#ros-risk-list").inner_text()
        assert page.locator("#ros-risk-list .risk-clear").count() == 0
        page.locator("#bench-safety-confirmed").check()
        forward = page.locator('[data-teleop="forward"]')
        page.wait_for_function(
            "!document.querySelector('[data-teleop=\"forward\"]')?.disabled"
        )
        assert forward.is_enabled()

        forward.dispatch_event("pointerdown", {"pointerId": 1, "button": 0})
        page.wait_for_timeout(80)
        forward.dispatch_event("pointerup", {"pointerId": 1, "button": 0})
        page.wait_for_function("window.__teleopCommands.length >= 2")
        if screenshot := os.environ.get("ROSY_DASHBOARD_FULL_SCREENSHOT"):
            output = Path(screenshot)
            output.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(output), full_page=True)
        commands = page.evaluate("window.__teleopCommands")
        browser.close()

    assert commands[0] == {"linear": 0.05, "angular": 0}
    assert commands[-1] == {"linear": 0, "angular": 0}
    assert not any(command != {"linear": 0, "angular": 0} for command in commands[1:])


def test_field_settings_save_limits_waypoint_and_dock_without_navigation():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page = _launch_page(playwright)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.goto("http://rosy.test/dashboard", wait_until="domcontentloaded", timeout=5_000)
        page.wait_for_function(
            "document.getElementById('robot-mode')?.textContent === 'MANUAL'"
        )
        page.locator("#view-inspect").click()
        page.locator("#field-settings-panel").scroll_into_view_if_needed()

        page.wait_for_function(
            "document.querySelector('#waypoint-list ui-empty')?.textContent?.includes('없습니다')"
        )
        page.wait_for_function(
            "document.getElementById('limits-save')"
            " && !document.getElementById('limits-save').disabled"
        )
        assert page.locator("#field-settings-panel").get_by_text("FLEET_HOLD", exact=True).count() == 1
        assert page.locator("#dock-capability").inner_text() == "HOLD"
        if screenshot := os.environ.get("ROSY_FIELD_SETTINGS_SCREENSHOT"):
            output = Path(screenshot)
            output.parent.mkdir(parents=True, exist_ok=True)
            page.locator("#field-settings-panel").screenshot(path=str(output))

        page.locator("#waypoint-name").fill("zone_a")
        page.locator("#waypoint-save").click()
        page.wait_for_function(
            "document.getElementById('waypoint-message')?.textContent?.includes('zone_a')"
        )

        page.locator("#limit-manual-linear").fill("0.11")
        page.locator("#limit-manual-angular").fill("0.41")
        page.locator("#limits-save").click()
        page.wait_for_function(
            "document.getElementById('limits-message')?.textContent?.includes('rosy.yaml')"
        )

        page.locator("#dock-id").fill("dock_1")
        page.locator("#dock-register").click()
        page.wait_for_function(
            "document.getElementById('dock-message')?.textContent?.includes('등록')"
        )
        assert page.url.startswith("http://rosy.test/dashboard")

        calls = page.evaluate("window.__apiCalls")
        browser.close()

    posts = {(call["method"], call["path"]) for call in calls}
    assert ("POST", "/api/v1/waypoints") in posts
    assert ("PUT", "/api/v1/safety/limits") in posts
    assert ("POST", "/api/v1/docking/types") in posts
    assert ("POST", "/api/v1/docking/docks") in posts
    waypoint = next(call for call in calls if call["path"] == "/api/v1/waypoints" and call["method"] == "POST")
    assert waypoint["body"]["name"] == "zone_a"
    assert waypoint["body"]["x"] == 1.25
    limits = next(call for call in calls if call["path"] == "/api/v1/safety/limits")
    assert limits["body"]["manual_linear"] == 0.11
    dock = next(call for call in calls if call["path"] == "/api/v1/docking/docks" and call["method"] == "POST")
    assert dock["body"]["id"] == "dock_1"
    assert dock["body"]["type"] == "rosy_v1"


def test_traffic_policy_is_staged_before_stopped_only_apply():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page = _launch_page(playwright)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.goto(
            "http://rosy.test/dashboard",
            wait_until="domcontentloaded",
            timeout=5_000,
        )
        page.locator("#traffic-policy-revision-input").fill(
            "traffic-policy-v2")
        page.locator("#traffic-policy-mode").select_option("ENFORCED")
        page.locator("#traffic-policy-stage").click()
        page.wait_for_function(
            "document.getElementById('traffic-policy-apply')"
            " && !document.getElementById('traffic-policy-apply').disabled"
        )
        page.locator("#traffic-policy-apply").click()
        page.wait_for_function(
            "document.getElementById('traffic-policy-message')"
            "?.textContent === '정지 상태에서 정책을 적용했습니다.'"
        )
        if screenshot := os.environ.get("ROSY_DASHBOARD_SCREENSHOT"):
            output = Path(screenshot)
            output.parent.mkdir(parents=True, exist_ok=True)
            page.locator(".traffic-policy-control").screenshot(
                path=str(output))
        calls = page.evaluate("window.__apiCalls")
        browser.close()

    mutations = [
        (call["method"], call["path"])
        for call in calls
        if call["path"].startswith("/api/v1/traffic/policy/")
    ]
    assert mutations == [
        ("POST", "/api/v1/traffic/policy/stage"),
        ("POST", "/api/v1/traffic/policy/apply"),
    ]


def test_live_camera_preview_is_visible_beside_the_map():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page = _launch_page(playwright)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.goto(
            "http://rosy.test/dashboard",
            wait_until="domcontentloaded",
            timeout=5_000,
        )
        page.wait_for_function(
            "document.getElementById('vision-stage')?.dataset.state === 'live'"
        )
        assert page.locator("#vision-frame").is_visible()
        assert page.locator("#vision-source").inner_text() == "HOST-SIM"
        assert page.locator("#vision-resolution").inner_text() == "640×360"
        assert page.locator("#vision-captured").inner_text() == "42.250 s"
        assert page.locator("#vision-status").inner_text() == "LIVE"
        if screenshot := os.environ.get("ROSY_CAMERA_DASHBOARD_SCREENSHOT"):
            output = Path(screenshot)
            output.parent.mkdir(parents=True, exist_ok=True)
            page.locator(".region-observe").screenshot(path=str(output))
        calls = page.evaluate("window.__apiCalls")
        browser.close()

    paths = [call["path"] for call in calls]
    assert "/api/v1/vision/front/status" in paths
    assert "/api/v1/vision/front/frame" in paths
    frame_call = next(
        call for call in calls
        if call["path"] == "/api/v1/vision/front/frame"
    )
    assert frame_call["search"] == "?sequence=7"


def test_camera_preview_is_cleared_when_reauthentication_fails():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page = _launch_page(playwright)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.goto(
            "http://rosy.test/dashboard",
            wait_until="domcontentloaded",
            timeout=5_000,
        )
        page.wait_for_function(
            "document.getElementById('vision-stage')?.dataset.state === 'live'"
        )
        page.locator("#open-auth").click()
        page.locator("#token-input").fill("bad-token")
        page.locator("#auth-form button[type=submit]").click()
        page.wait_for_function(
            "document.getElementById('vision-empty')?.textContent.includes('인증 실패')"
        )
        assert page.locator("#vision-frame").is_hidden()
        assert page.locator("#vision-status").inner_text() == "WAITING"
        before = page.evaluate(
            "window.__apiCalls.filter((call) => call.path === '/api/v1/vision/front/status').length"
        )
        page.wait_for_timeout(700)
        after = page.evaluate(
            "window.__apiCalls.filter((call) => call.path === '/api/v1/vision/front/status').length"
        )
        browser.close()

    assert after == before


def test_rate_limited_camera_never_leaves_an_old_frame_live():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page = _launch_page(playwright)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.goto(
            "http://rosy.test/dashboard",
            wait_until="domcontentloaded",
            timeout=5_000,
        )
        page.wait_for_function(
            "document.getElementById('vision-stage')?.dataset.state === 'live'"
        )
        page.evaluate("window.__cameraSequence = 8; window.__cameraFrameStatus = 429")
        page.wait_for_function(
            "document.getElementById('vision-empty')?.textContent.includes('속도 제한')"
        )
        assert page.locator("#vision-frame").is_hidden()
        assert page.locator("#vision-status").inner_text() == "WAITING"
        browser.close()


CONSOLE_STATE_INIT = {
    # D-153 G2 상태 매트릭스 — 서버가 내린 증거 어휘·모드·401을 값별로 렌더하는지.
    "delayed": """
        window.__rosyStateOverrides = {robot_state: {evidence: {
          pose: {evidence: 'delayed', stale_after_s: 2.0},
          velocity: {evidence: 'delayed', stale_after_s: 0.5},
        }}};
    """,
    "disconnected": """
        window.__rosyStateOverrides = {robot_state: {evidence: {
          pose: {evidence: 'disconnected'},
          velocity: {evidence: 'disconnected'},
        }}};
    """,
    "safe-stop": """
        window.__rosyStateOverrides = {robot_state: {
          mode: 'SAFE_STOP', safety: {estop: true},
        }};
    """,
    "unauthorized": "sessionStorage.setItem('rosy.dashboard.token', 'bad-token');",
    "vision-unavailable": """
        window.__rosyVisionOverride = {available: false, stale: false};
    """,
    "first-boot": """
        window.fetch = () => new Promise(() => {});
    """,
    "runtime-normal": """
        window.__rosyRuntimeOverride = {
          ros: {
            status: 'OK', domain_id: 41, namespace: 'rosy_01',
            isolation: {mode: 'localhost_only', interface: 'lo'},
            rmw: 'rmw_cyclonedds_cpp', node_count: 2, topic_count: 2,
            nodes: [{name: '/rosy_01/core'}, {name: '/rosy_01/emotion'}],
            topics: [{name: '/rosy_01/cmd_vel'}, {name: '/rosy_01/power/mode'}],
            edges: [
              {source: '/rosy_01/core', target: '/rosy_01/cmd_vel', kind: 'pub'},
              {source: '/rosy_01/emotion', target: '/rosy_01/power/mode', kind: 'sub'},
            ],
          },
          network: {throughput: {rx_bytes_per_second: 1523000, tx_bytes_per_second: 480000}},
        };
        window.__rosyHostNetworkOverride = {
          available: true,
          data: {mode: 'SITE_STA', ssid: 'site-wlan', ap_active: false,
                 ipv4: '192.168.0.7', default_route: '192.168.0.1',
                 dns: ['1.1.1.1'], internet: true, peer_reachable: true},
        };
    """,
    "rmw-mismatch": """
        window.__rosyRuntimeOverride = {
          ros: {
            status: 'DEGRADED', domain_id: 41, namespace: 'rosy_01',
            isolation: {mode: 'localhost_only', interface: 'lo'},
            rmw: 'rmw_fastrtps_cpp', node_count: 1, topic_count: 1,
            nodes: [{name: '/rosy_01/core'}],
            topics: [{name: '/rosy_01/cmd_vel'}],
            edges: [
              {source: '/rosy_01/core', target: '/rosy_01/cmd_vel', kind: 'pub'},
            ],
            risks: [{code: 'RMW_MISMATCH',
                     message: '다음 CORE 기동에서 CycloneDDS로 정정됩니다'}],
          },
        };
    """,
    "network-relay": """
        window.__rosyHostNetworkOverride = {
          available: true,
          data: {mode: 'RELAY_AP_STA', ssid: 'site-wlan', ap_active: true,
                 ipv4: '192.168.23.1', default_route: null,
                 dns: [], internet: false, peer_reachable: true},
        };
    """,
    "network-provisioning": """
        window.__rosyHostNetworkOverride = {
          available: true,
          data: {mode: 'PROVISIONING_AP', ssid: 'rosy-setup', ap_active: true,
                 ipv4: '10.0.0.1', default_route: null,
                 dns: [], internet: false, peer_reachable: false},
        };
    """,
    # 기본 스텁(runtime.ros=null)이 곧 unavailable 상태다 — 뷰만 전환한다.
    "runtime-unavailable": "",
}


@pytest.mark.parametrize("state", list(CONSOLE_STATE_INIT))
def test_console_state_matrix_renders_each_state(state):
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page = _launch_page(playwright, extra_init=CONSOLE_STATE_INIT[state])
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.goto(
            "http://rosy.test/dashboard",
            wait_until="domcontentloaded",
            timeout=5_000,
        )
        # F-06 — 장비 런타임 카드는 inspect 뷰 패널 안에 있다. operate 뷰에서
        # 찍으면 DOM 단얜(innerText 폴백)만 통과하고 화면은 비어 있다.
        if state in (
            "runtime-normal",
            "rmw-mismatch",
            "network-relay",
            "network-provisioning",
            "runtime-unavailable",
        ):
            page.locator("#view-inspect").click()
        if state == "unauthorized":
            page.wait_for_function(
                "document.getElementById('auth-drawer')?.classList.contains('open')"
            )
        elif state == "safe-stop":
            page.wait_for_function(
                "document.getElementById('robot-mode')?.textContent === 'SAFE_STOP'"
            )
        elif state == "vision-unavailable":
            page.wait_for_function(
                "document.getElementById('vision-status')?.textContent === 'WAITING'"
            )
            assert "수신 대기" in page.locator("#vision-empty").inner_text()
            assert (
                page.locator("#vision-stage").get_attribute("data-state") == "waiting"
            )
        elif state == "first-boot":
            page.wait_for_timeout(600)
            assert page.locator("#robot-mode").inner_text() == ""
            assert page.evaluate("window.__apiCalls.length") == 0
        elif state == "runtime-normal":
            page.wait_for_function(
                "document.getElementById('dds-rmw')?.textContent"
                " === 'rmw_cyclonedds_cpp'"
            )
            assert page.locator("#network-mode").inner_text() == "SITE_STA"
            assert page.locator("#dds-isolation").inner_text() == "LOOPBACK ONLY"
            assert page.locator("#ros-graph-status").inner_text() == "OK"
            assert page.locator("#network-rx-rate").inner_text() != "—"
            assert page.locator("#dds-rmw").is_visible()
            assert page.locator("#network-mode").is_visible()
            # F-08 — 정상 그래프의 토픽 마커는 경보 색을 쓰지 않는다(D-82:
            # 따뜻한 것이 보이면 언제나 무언가 잘못된 것이다). 양쪽 색을 같은
            # 정규화(캔버스 fillStyle)로 바꿔 비교한다 — 문자열 형식이 달라
            # 항상 통과하는 동어반복 단얜은 F-08 첫 게임이었다.
            fills = page.evaluate(
                "() => {"
                " const topic = document.querySelector('.graph-topic');"
                " if (!topic) return null;"
                " const ctx = document.createElement('canvas').getContext('2d');"
                " ctx.fillStyle = getComputedStyle(topic).fill;"
                " const used = ctx.fillStyle;"
                " ctx.fillStyle = getComputedStyle(document.documentElement)"
                "   .getPropertyValue('--status-warn').trim();"
                " return [used, ctx.fillStyle];"
                "}"
            )
            assert fills, "그래프 토픽 요소가 없다"
            assert fills[0] != fills[1], (
                "그래프 토픽이 --status-warn을 쓴다 — 정상 상태의 경보 예산 소비"
            )
        elif state == "rmw-mismatch":
            page.wait_for_function(
                "document.getElementById('dds-rmw')?.textContent"
                " === 'rmw_fastrtps_cpp'"
            )
            assert "RMW_MISMATCH" in page.locator("#ros-risk-list").inner_text()
            assert page.locator("#dds-rmw").is_visible()
            assert page.locator("#ros-risk-list").is_visible()
        elif state == "runtime-unavailable":
            page.wait_for_function(
                "() => document.getElementById('ros-risk-list')"
                "?.textContent.includes('그래프 수집 불가')"
            )
            assert page.locator("#ros-risk-list").is_visible()
        elif state in ("network-relay", "network-provisioning"):
            expected = {
                "network-relay": "RELAY_AP_STA",
                "network-provisioning": "PROVISIONING_AP",
            }[state]
            page.wait_for_function(
                f"document.getElementById('network-mode')?.textContent"
                f" === '{expected}'"
            )
            assert page.locator("#network-mode").is_visible()
        else:
            page.wait_for_function(
                f"document.getElementById('pose-x')?.dataset.evidence === '{state}'"
            )
            assert (
                page.locator("#velocity-linear").get_attribute("data-evidence") == state
            )
            assert page.locator("#pose-x").is_visible()
        if shot_dir := os.environ.get("ROSY_DASHBOARD_STATE_SHOT_DIR"):
            output = Path(shot_dir) / f"console_{state}_390x844_local.png"
            output.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(output), full_page=True)
        browser.close()


DECLINE_MODE_CONFIRM = DECLINE_CONFIRM


def test_irreversible_mode_change_needs_confirm_and_decline_blocks_it():
    """D-92(a)/D-153 G3-5 — 불가역 모드 변경은 confirm을 지나며 거부하면 안 나간다."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page = _launch_page(playwright, extra_init=DECLINE_MODE_CONFIRM)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.goto(
            "http://rosy.test/dashboard",
            wait_until="domcontentloaded",
            timeout=5_000,
        )
        page.wait_for_function(
            "document.getElementById('robot-mode')?.textContent === 'MANUAL'"
        )
        page.locator('[data-mode="IDLE"]').click()
        page.wait_for_function("window.__confirms.length === 1")
        declined_calls = page.evaluate(
            "window.__apiCalls.filter((call) => call.path === '/api/v1/mode')"
        )
        accept_confirm(page)
        page.locator('[data-mode="IDLE"]').click()
        page.wait_for_function(
            "window.__apiCalls.some((call) => call.path === '/api/v1/mode')"
        )
        confirms = page.evaluate("window.__confirms")
        browser.close()

    assert "IDLE 모드로 변경할까요" in confirms[0]
    assert declined_calls == []
    assert len(confirms) == 2


def test_irreversible_cyclone_apply_needs_confirm_and_decline_blocks_it():
    """D-123/D-92(a) — Cyclone 적용(저장+재부팅)도 confirm을 지나며 거부하면 안 나간다."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page = _launch_page(playwright, extra_init=DECLINE_CONFIRM)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.goto(
            "http://rosy.test/dashboard",
            wait_until="domcontentloaded",
            timeout=5_000,
        )
        page.wait_for_function(
            "document.getElementById('robot-mode')?.textContent === 'MANUAL'"
        )
        page.locator("#view-inspect").click()
        page.locator("#dds-cyclone-apply").click()
        page.wait_for_function("window.__confirms.length === 1")
        declined = page.evaluate(
            "window.__apiCalls.filter((call) =>"
            " call.path === '/api/v1/system/dds/cyclone')"
        )
        accept_confirm(page)
        page.locator("#dds-cyclone-apply").click()
        page.wait_for_function(
            "window.__apiCalls.some((call) =>"
            " call.path === '/api/v1/system/dds/cyclone')"
        )
        confirms = page.evaluate("window.__confirms")
        browser.close()

    assert "CycloneDDS를 저장하고 로봇을 재부팅할까요" in confirms[0]
    assert declined == []
    assert len(confirms) == 2
