"""Optional browser-level safety test for ordered hold-to-drive shutdown."""

from __future__ import annotations

import json
import os
from urllib.parse import urlparse
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "runtime" / "core_api_web" / "core_api_web" / "web"
#: Production serves `/common/*` from the web_common package (core_api_web
#: mounts it; `test_ui_route.py` pins the 200s). The harness must mirror that
#: mount — app.js imports `/common/core_ui_logic.js` absolutely, and a request
#: with no route escapes to real DNS (rosy.test does not resolve) and kills the
#: boot before the first assertion.
WEB_COMMON = ROOT / "src" / "hmi" / "web_common"

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
window.__sockets = [];
window.WebSocket = class extends EventTarget {
  constructor(url) {
    super();
    this.url = url;
    this.sent = [];
    window.__sockets.push(this);
    setTimeout(() => this.dispatchEvent(new Event('open')), 0);
  }
  send(data) { this.sent.push(String(data)); }
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
  if (authorization.includes('bad-token')
      || (window.__revoked && authorization.includes(window.__revoked))) {
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
        battery: {evidence: 'fresh', stale_after_s: 5.0},
        safety: {evidence: 'fresh', stale_after_s: 0.2},
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
    '/api/v1/system/info': {
      name: 'Rosy', robot_id: 'rosy_01', hardware_model: 'test',
      runtime_mode: 'hardware', caller_role: window.__callerRole || 'administrator',
    },
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
  if (window.__rosyInfoOverride) {
    Object.assign(bodies['/api/v1/system/info'], window.__rosyInfoOverride);
  }
  if (window.__rosyCapabilitiesOverride) {
    bodies['/api/v1/system/capabilities'] = window.__rosyCapabilitiesOverride;
  }
  if (window.__rosyInventoryOverride) {
    bodies['/api/v1/system/inventory'] = window.__rosyInventoryOverride;
  }
  if (window.__rosyHostNetworkOverride) {
    Object.assign(bodies['/api/v1/host/network'], window.__rosyHostNetworkOverride);
  }
  if (path === '/api/v1/auth/whoami') {
    const paired = authorization.includes('paired-test-token');
    return new Response(JSON.stringify(paired ? {
      id: 'b1c2d3e4f5a6', role: 'operator', label: 'bay 7 tablet', source: 'pair-physical',
      created_at: '2026-09-24T00:00:00+00:00', expires_at: '2099-10-01T00:00:00+00:00',
    } : {
      id: '0a1b2c3d4e5f', role: bodies['/api/v1/system/info'].caller_role, label: 'bench',
      source: 'card', created_at: '2026-09-24T00:00:00+00:00', expires_at: null,
    }), {status: 200, headers: {'Content-Type': 'application/json'}});
  }
  if (method === 'POST' && path === '/api/v1/auth/pair') {
    const reply = window.__pairReply || {status: 201, body: {
      id: 'b1c2d3e4f5a6', token: 'paired-test-token', role: 'operator', label: 'bay 7 tablet',
      source: 'pair-physical',
      expires_at: new Date(Date.now() + 7 * 24 * 3600 * 1000 - 60 * 1000).toISOString(),
    }};
    return new Response(JSON.stringify(reply.body), {
      status: reply.status,
      headers: {'Content-Type': 'application/json', 'Cache-Control': 'no-store', ...(reply.headers || {})},
    });
  }
  if (method === 'POST' && path === '/api/v1/auth/logout') {
    if (authorization.includes('paired-test-token')) return new Response(null, {status: 204});
    return new Response(JSON.stringify({error: {code: 'VALIDATION_ERROR',
      message: 'only a paired browser token can log out'}}), {
      status: 409, headers: {'Content-Type': 'application/json'},
    });
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
    const admin = bodies['/api/v1/system/info'].caller_role === 'administrator';
    return new Response(JSON.stringify(admin ? {events: []} : {error: {code: 'FORBIDDEN'}}), {
      status: admin ? 200 : 403, headers: {'Content-Type': 'application/json'},
    });
  }
  return new Response(JSON.stringify(bodies[path] ?? {}), {
    status: 200, headers: {'Content-Type': 'application/json'},
  });
};
"""


def _launch_page(playwright, extra_init="", width=390, height=844):
    browser, page, _errors = open_page(playwright, width, height)
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
        assert set(warm) <= {"ui-button#emergency-stop.stop-button"}, (
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
        # D-201 — 정책 편집은 점검 뷰(절차 문법)의 현장 설정 카드에 산다.
        page.locator("#view-inspect").click()
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
            page.locator(".settings-card[aria-labelledby='traffic-policy-heading']").screenshot(
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
        page.locator("#auth-tab-token").click()
        page.locator("#token-input").fill("bad-token")
        page.locator("#auth-form [type=submit]").click()
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


# US-010 — rosy-pinky-e4us, release 005, CORE-only, viewer token. The page
# showed BATTERY 0% / 0.00 V, "Rosy 01", 5/5 motion capabilities, and a red
# "안전 회로 수신 끊김" banner beside "READY 주행 회로 정상", and it probed
# /logs/audit for a 403. The payloads below are what CORE now answers there.
CORE_ONLY_VIEWER_INIT = """
    sessionStorage.setItem('rosy.dashboard.token', 'viewer-test-token');
    window.__callerRole = 'viewer';
    window.__rosyInfoOverride = {
      robot_name: 'rosy-pinky-e4us', robot_id: 'rosy_18', runtime_mode: 'core',
    };
    const unavailable = (stale) => ({received_at: null, evidence: 'unavailable', stale_after_s: stale});
    window.__rosyStateOverrides = {robot_state: {
      robot_id: 'rosy_18', mode: 'IDLE',
      pose: {x: 0, y: 0, yaw: 0}, velocity: {linear: 0, angular: 0},
      battery: {percent: null, voltage: null},
      evidence: {
        pose: unavailable(2.0), velocity: unavailable(0.5), battery: unavailable(5.0),
        navigation: unavailable(2.0), safety: unavailable(0.2),
        docking: {received_at: '2026-09-24T00:00:00.000Z', evidence: 'fresh', stale_after_s: 2.0},
      },
    }};
    window.__rosyCapabilitiesOverride = {
      teleop: false, slam: false, docking: {supported: false},
      navigation: {goal_navigation: false, return_home: false},
      swarm: {follow: false, lead: false},
      withheld: {flags: ['teleop', 'navigation.goal_navigation', 'swarm.follow',
                         'swarm.lead', 'slam', 'navigation.return_home'],
                 reason: 'runtime_mode:core'},
    };
    const blocked = (id) => ({id, available: false, state: 'blocked', reason: 'runtime_mode:core'});
    window.__rosyInventoryOverride = {
      device_state: 'READY',
      descriptors: ['mobility.move', 'mobility.navigate', 'mobility.follow',
                    'mobility.lead', 'perception.localize'].map(blocked),
    };
"""


def test_core_only_viewer_sees_the_truth_and_probes_nothing_forbidden():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page = _launch_page(playwright, extra_init=CORE_ONLY_VIEWER_INIT)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.goto("http://rosy.test/dashboard", wait_until="domcontentloaded", timeout=5_000)
        page.wait_for_function(
            "document.getElementById('safety-label')?.textContent === 'HW OFF'"
        )
        page.wait_for_function(
            "document.getElementById('capability-count')?.textContent === '0 / 5'"
        )
        page.wait_for_timeout(300)

        # 1. no battery reading is not 0% / 0.00 V
        assert page.locator("#battery-value").inner_text() == "—"
        assert page.locator("#battery-voltage").inner_text() == "voltage —"
        assert page.locator("#battery-value").get_attribute("data-evidence") == "unavailable"
        # 2. the provisioned name, not the placeholder
        assert page.locator("#robot-name").inner_text() == "rosy-pinky-e4us"
        # 3. motion is withheld and says why, without alarm colour
        capabilities = page.locator("#capability-list").inner_text()
        assert "하드웨어 런타임 꺼짐 (CORE-only)" in capabilities
        assert page.locator('#capability-list [data-cause="runtime"]').count() == 5
        assert page.locator('[data-teleop="forward"]').is_disabled()
        # 4. hero and banner agree: no source, and the reason is CORE-only
        assert "CORE-only" in page.locator("#safety-source").inner_text()
        triage_text = page.locator("#triage").inner_text()
        assert "수신 끊김" not in triage_text
        assert "출처는 있는데" not in triage_text
        assert page.locator("#triage-title").inner_text() == "하드웨어 런타임 꺼짐 (CORE-only)"
        assert page.locator("#triage").get_attribute("data-category") == "observation"
        warm = page.evaluate(WARM_SCAN)
        assert set(warm) <= {"ui-button#emergency-stop.stop-button"}, (
            f"CORE-only는 고장이 아니다 — 경보 예산 밖 따뜻한 색: {warm}"
        )
        # 5. a viewer never asks for what it cannot read
        paths = [call["path"] for call in page.evaluate("window.__apiCalls")]
        assert "/api/v1/system/info" in paths
        assert "/api/v1/logs/audit" not in paths
        assert "/api/v1/system/tokens" not in paths
        assert page.locator("#limits-save").is_disabled()
        browser.close()


def test_hardware_runtime_with_a_silent_safety_source_never_claims_ready():
    """Same evidence, other cause: the hero must match the banner, not contradict it."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    init = """
        window.__rosyStateOverrides = {robot_state: {evidence: {
          pose: {evidence: 'fresh', stale_after_s: 2.0},
          velocity: {evidence: 'fresh', stale_after_s: 0.5},
          safety: {received_at: null, evidence: 'disconnected', stale_after_s: 0.2},
        }}};
    """
    with sync_playwright() as playwright:
        try:
            browser, page = _launch_page(playwright, extra_init=init)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.goto("http://rosy.test/dashboard", wait_until="domcontentloaded", timeout=5_000)
        page.wait_for_function(
            "document.getElementById('triage-title')?.textContent === '안전 회로 수신 끊김'"
        )
        assert page.locator("#safety-label").inner_text() == "UNVERIFIED"
        assert page.locator("#safety-source").inner_text() == "안전 회로 수신 끊김"
        browser.close()


# --- D-193 S3: login code, whoami badge, logout, first-message WebSocket auth ---

NO_TOKEN_INIT = "sessionStorage.removeItem('rosy.dashboard.token');"


# --- D-201: 적합 계약 — 고정 문법 표면은 선언 뷰포트에서 스크롤도 분쇄도 없다 ---

FIT_PROBE = """() => {
  const act = document.querySelector('.region-act');
  const mode = document.querySelector('.mode-control');
  const estop = document.getElementById('emergency-stop').getBoundingClientRect();
  return {
    docOverflow: document.documentElement.scrollHeight - window.innerHeight,
    actOverflow: act.scrollHeight - act.clientHeight,
    modeHeight: Math.round(mode.getBoundingClientRect().height),
    estopInside: estop.top >= 0 && estop.bottom <= window.innerHeight,
  };
}"""

#: 공간 문법의 선언 최소 뷰포트. 1366×768 이 상용 노트북 바닥이고
#: 1536×864 는 회차 1이 전화만 찍고 비운 자리다(D-201).
FIT_VIEWPORTS = [(1536, 864), (1366, 768)]


@pytest.mark.parametrize(
    "state", ["", CONSOLE_STATE_INIT["safe-stop"]]
)
@pytest.mark.parametrize("viewport", FIT_VIEWPORTS)
def test_operate_view_fits_and_does_not_crush(viewport, state):
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page = _launch_page(
                playwright, extra_init=state,
                width=viewport[0], height=viewport[1])
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.goto(
            "http://rosy.test/dashboard",
            wait_until="domcontentloaded",
            timeout=5_000,
        )
        page.wait_for_function(
            "document.getElementById('robot-mode')?.textContent !== undefined"
        )
        page.wait_for_timeout(700)
        fit = page.evaluate(FIT_PROBE)
        browser.close()

    assert fit["docOverflow"] <= 0, (
        f"{viewport}: 운용 뷰 문서가 스크롤된다 — 공간 문법 위반(D-201): {fit}"
    )
    assert fit["actOverflow"] <= 1, (
        f"{viewport}: 조작 열이 프레임을 넘는다 — 관측·조작은 고정(D-201): {fit}"
    )
    assert fit["modeHeight"] >= 40, (
        f"{viewport}: 모드 분절 제어가 분쇄됐다 — min-height 44의 조작 요소가"
        f" {fit['modeHeight']}px로 눌렸다(D-201): {fit}"
    )
    assert fit["estopInside"], f"{viewport}: 즉시 정지가 뷰포트 밖이다: {fit}"


# --- D-203: 계산 척급 폐쇄 — 보이는 계산 크기는 토큰 단계뿐이다 ---------------

TYPE_STEPS = "new Set(['12px', '14px', '16px', '18px', '20px', '32px'])"

OFF_SCALE_CENSUS = """() => {
  const steps = STEPS;
  const off = [];
  for (const el of document.querySelectorAll('*')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    if (!(el.textContent.trim() && el.children.length === 0)) continue;
    const size = getComputedStyle(el).fontSize;
    if (!steps.has(size)) {
      off.push(`${size} <${el.tagName.toLowerCase()}#${el.id || '-'}>`
               + `.${(el.className || '').toString().split(' ')[0] || '-'}`);
    }
  }
  return off;
}"""


@pytest.mark.parametrize("state_init", ["", CONSOLE_STATE_INIT["delayed"]])
def test_visible_type_scale_is_closed(state_init):
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page = _launch_page(playwright, extra_init=state_init)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.goto(
            "http://rosy.test/dashboard",
            wait_until="domcontentloaded",
            timeout=5_000,
        )
        page.evaluate(f"window.STEPS = {TYPE_STEPS}")
        off = page.evaluate(OFF_SCALE_CENSUS)
        # 점검 뷰(절차 문법)도 같은 계단을 쓴다 — 편집 UI가 살고 있는 곳이다.
        page.locator("#view-inspect").click()
        page.wait_for_timeout(300)
        off += page.evaluate(OFF_SCALE_CENSUS)
        browser.close()

    assert off == [], (
        "계단 밖 계산 크기가 화면에 있다 — 닫힌 여섯 단계 밖이다(D-203): "
        + "; ".join(off[:6])
    )


# --- D-214: 텍스트 대비의 바닥 — 보이는 모든 글자가 읽혀야 한다 ---------------

TEXT_FLOOR_CENSUS = """() => {
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
    const floor = parseFloat(s.fontSize) >= 24 ? 3.0 : 4.5;
    if (ratio < floor) {
      offenders.push(`${el.tagName.toLowerCase()}#${el.id || '-'}`
        + ` ${ratio.toFixed(2)}:1 "${el.textContent.trim().slice(0, 14)}"`);
    }
  }
  return offenders;
}"""


@pytest.mark.parametrize("state_init", ["", CONSOLE_STATE_INIT["safe-stop"]])
def test_visible_text_meets_the_contrast_floor(state_init):
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page = _launch_page(playwright, extra_init=state_init)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.goto(
            "http://rosy.test/dashboard",
            wait_until="domcontentloaded",
            timeout=5_000,
        )
        page.wait_for_timeout(700)
        offenders = page.evaluate(TEXT_FLOOR_CENSUS)
        page.locator("#view-inspect").click()
        page.wait_for_timeout(300)
        offenders += page.evaluate(TEXT_FLOOR_CENSUS)
        browser.close()

    assert offenders == [], (
        "바닥(4.5:1, 큰 값 3.0:1) 아래 텍스트가 있다(D-214): "
        + "; ".join(offenders[:6])
    )


# --- D-220: 정지 계약 — 움직임 예산은 0이다 -----------------------------------

MOTION_CENSUS = """() => {
  const moving = [];
  for (const el of document.querySelectorAll('*')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    const s = getComputedStyle(el);
    if ((s.transitionDuration !== '0s' && s.transitionProperty !== 'none')
        || s.animationName !== 'none') {
      moving.push(`${el.tagName.toLowerCase()}#${el.id || '-'}`
        + `.${(el.className || '').toString().split(' ')[0] || '-'}`
        + ` t=${s.transitionDuration}/${s.transitionProperty}`
        + ` a=${s.animationName}`);
    }
  }
  return moving;
}"""


def test_no_visible_element_moves():
    """D-220 — 상태 변화는 점프 컷이다. 보간은 없는 값을 있는 것처럼 보이게 한다."""
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
        page.wait_for_timeout(700)
        moving = page.evaluate(MOTION_CENSUS)
        page.locator("#view-inspect").click()
        page.wait_for_timeout(300)
        moving += page.evaluate(MOTION_CENSUS)
        browser.close()

    assert moving == [], (
        "움직이는 요소가 있다 — 예산은 0이다, 예외는 ADR 로만(D-220): "
        + "; ".join(moving[:6])
    )


def _open_dashboard(playwright, extra_init=""):
    browser, page = _launch_page(playwright, extra_init=extra_init)
    page.goto("http://rosy.test/dashboard", wait_until="domcontentloaded", timeout=5_000)
    return browser, page


def _storage(page):
    return page.evaluate(
        "({session: sessionStorage.getItem('rosy.dashboard.token'),"
        " local: localStorage.getItem('rosy.dashboard.paired')})"
    )


def test_login_code_pairs_this_tab_and_shows_who_is_logged_in():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page = _open_dashboard(playwright, NO_TOKEN_INIT)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        # The code tab is the default and the token form is hidden.
        assert "open" in page.locator("#auth-drawer").get_attribute("class")
        assert page.locator("#auth-tab-code").get_attribute("aria-selected") == "true"
        assert page.locator("#auth-form").is_hidden()
        assert page.locator("#whoami-badge").is_hidden()

        page.locator("#code-input").fill(" abcd efgh ")
        page.locator("#code-label").fill("bay 7 tablet")
        page.locator("#code-submit").click()
        page.wait_for_function(
            "document.getElementById('whoami-role')?.textContent === 'operator'")

        pair = next(call for call in page.evaluate("window.__apiCalls")
                    if call["path"] == "/api/v1/auth/pair")
        assert pair["body"] == {"code": "ABCDEFGH", "label": "bay 7 tablet"}
        detail = page.locator("#whoami-detail").inner_text()
        assert "bay 7 tablet" in detail and "로봇 화면 코드" in detail and "만료" in detail
        assert page.locator("#logout").inner_text() == "로그아웃"
        # Not ticked: this tab only.
        assert _storage(page) == {"session": "paired-test-token", "local": None}
        # The socket URL carries no token; the first message does.
        page.wait_for_function(
            "window.__sockets.length > 0 && window.__sockets.at(-1).sent.length > 0")
        socket = page.evaluate(
            "({url: window.__sockets.at(-1).url, sent: window.__sockets.at(-1).sent})")
        assert socket["url"].endswith("/ws/state") and "token" not in socket["url"]
        assert socket["sent"] == ['{"type":"auth","token":"paired-test-token"}']
        for call in page.evaluate("window.__apiCalls"):
            assert "token" not in call["search"]
        browser.close()


def test_keep_me_logged_in_puts_only_the_expiring_paired_token_in_local_storage():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page = _open_dashboard(playwright, NO_TOKEN_INIT)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.locator("#code-input").fill("ABCD-EFGH")
        page.locator("#code-remember").check()
        page.locator("#code-submit").click()
        page.wait_for_function(
            "document.getElementById('whoami-role')?.textContent === 'operator'")
        stored = _storage(page)
        assert stored["session"] is None
        remembered = json.loads(stored["local"])
        assert remembered["token"] == "paired-test-token"
        assert set(remembered) == {"token", "expires_at"}

        # A pasted (non-expiring) token replaces it and lives in this tab only.
        page.locator("#open-auth").click()
        page.locator("#auth-tab-token").click()
        page.locator("#token-input").fill("operator-test-token")
        page.locator("#auth-form [type=submit]").click()
        page.wait_for_function(
            "document.getElementById('whoami-detail')?.textContent.includes('만료 없음')")
        assert _storage(page) == {"session": "operator-test-token", "local": None}
        assert page.locator("#token-input").input_value() == ""
        assert page.locator("#logout").inner_text() == "이 브라우저에서 잊기"
        browser.close()


def test_an_expired_remembered_token_is_dropped_on_load():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    init = NO_TOKEN_INIT + (
        "localStorage.setItem('rosy.dashboard.paired', JSON.stringify("
        "{token: 'paired-test-token', expires_at: '2000-01-01T00:00:00+00:00'}));")
    with sync_playwright() as playwright:
        try:
            browser, page = _open_dashboard(playwright, init)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.wait_for_timeout(300)
        assert _storage(page) == {"session": None, "local": None}
        assert "open" in page.locator("#auth-drawer").get_attribute("class")
        assert not page.evaluate("window.__apiCalls")
        browser.close()


@pytest.mark.parametrize("reply, expected", [
    ({"status": 401, "body": {"error": {"code": "UNAUTHORIZED",
                                        "message": "invalid or expired login code", "detail": None}}},
     "발급된 코드가 없습니다"),
    ({"status": 401, "body": {"error": {"code": "UNAUTHORIZED",
                                        "message": "invalid or expired login code",
                                        "detail": {"burned": True}}}},
     "관리자에게 새 코드를 요청"),
    ({"status": 429, "body": {"error": {"code": "RATE_LIMITED", "message": "too many pairing attempts"}},
      "headers": {"Retry-After": "37"}},
     "37초 뒤에"),
    ({"status": 403, "body": {"error": {"code": "FORBIDDEN", "message": "robot LAN"}}},
     "로봇 LAN"),
], ids=["wrong-used-expired-or-none", "burned", "rate-limited", "outside-lan"])
def test_login_code_failures_say_what_the_robot_said(reply, expected):
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    init = NO_TOKEN_INIT + f"window.__pairReply = {json.dumps(reply)};"
    with sync_playwright() as playwright:
        try:
            browser, page = _open_dashboard(playwright, init)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.locator("#code-input").fill("ABCD-EFGH")
        page.locator("#code-submit").click()
        page.wait_for_function(
            "(text) => document.getElementById('code-message')?.textContent.includes(text)",
            arg=expected,
        )
        assert _storage(page) == {"session": None, "local": None}
        assert page.locator("#whoami-badge").is_hidden()
        if reply["status"] == 429:
            page.wait_for_timeout(300)
            assert page.locator("#code-submit").is_disabled()
        else:
            page.wait_for_function("!document.getElementById('code-submit').disabled")
        browser.close()


@pytest.mark.parametrize("typed, expected", [
    ("ABCD-EFG", "8자입니다"),
    ("ABCD-EFG0", "0"),
    ("", "8자 코드를 입력"),
])
def test_a_malformed_code_is_caught_before_it_spends_an_attempt(typed, expected):
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page = _open_dashboard(playwright, NO_TOKEN_INIT)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.evaluate("document.getElementById('code-input').required = false; null")
        page.locator("#code-input").fill(typed)
        page.locator("#code-submit").click()
        page.wait_for_function(
            "(text) => document.getElementById('code-message')?.textContent.includes(text)",
            arg=expected,
        )
        assert not [call for call in page.evaluate("window.__apiCalls")
                    if call["path"] == "/api/v1/auth/pair"]
        browser.close()


def test_logout_deletes_the_paired_token_and_forgets_it():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    init = "sessionStorage.setItem('rosy.dashboard.token', 'paired-test-token');"
    with sync_playwright() as playwright:
        try:
            browser, page = _open_dashboard(playwright, init)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.wait_for_function("document.getElementById('logout')?.textContent === '로그아웃'")
        page.locator("#logout").click()
        page.wait_for_function("document.getElementById('auth-drawer').classList.contains('open')")
        calls = page.evaluate("window.__apiCalls")
        assert any(call["method"] == "POST" and call["path"] == "/api/v1/auth/logout"
                   for call in calls)
        assert _storage(page) == {"session": None, "local": None}
        assert page.locator("#whoami-badge").is_hidden()
        assert "로봇에서 지워졌습니다" in page.locator("#auth-notice").inner_text()
        before = len(page.evaluate("window.__apiCalls"))
        page.wait_for_timeout(2_500)  # no polling with a forgotten token
        assert len(page.evaluate("window.__apiCalls")) == before
        browser.close()


def test_logging_out_a_card_token_is_refused_by_core_and_only_forgotten_here():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page = _open_dashboard(playwright)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.wait_for_function(
            "document.getElementById('logout')?.textContent === '이 브라우저에서 잊기'")
        page.locator("#logout").click()
        page.wait_for_function("document.getElementById('auth-drawer').classList.contains('open')")
        paths = [call["path"] for call in page.evaluate("window.__apiCalls")]
        assert "/api/v1/auth/logout" in paths  # CORE decides; it answers 409
        assert _storage(page) == {"session": None, "local": None}
        assert "로봇에 남아 있습니다" in page.locator("#auth-notice").inner_text()
        browser.close()


def test_a_4401_close_with_a_revoked_token_signs_out_without_reconnecting():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page = _open_dashboard(playwright)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.wait_for_function(
            "window.__sockets.length === 1 && window.__sockets[0].sent.length === 1")
        page.evaluate(
            "window.__revoked = 'operator-test-token';"
            " window.__sockets[0].dispatchEvent(new CloseEvent('close', {code: 4401})); null"
        )
        page.wait_for_function(
            "document.getElementById('auth-notice')?.textContent.includes('만료되었거나 회수')")
        assert _storage(page) == {"session": None, "local": None}
        page.wait_for_timeout(1_500)
        assert page.evaluate("window.__sockets.length") == 1
        browser.close()


REFUSE_EVERY_SOCKET = (
    "window.__refuse = setInterval(() => {"
    "  for (const socket of window.__sockets) {"
    "    if (!socket.refused) {"
    "      socket.refused = true;"
    "      socket.dispatchEvent(new CloseEvent('close', {code: 1006}));"
    "    }"
    "  }"
    "}, 10); null"
)


def test_refused_sockets_reconnect_with_growing_backoff_not_a_hot_loop():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page = _open_dashboard(playwright)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.wait_for_function("window.__sockets.length === 1")
        # Every socket is refused at once (1013 arrives as 1006 before accept).
        page.evaluate(REFUSE_EVERY_SOCKET)
        page.wait_for_timeout(4_000)
        count = page.evaluate("window.__sockets.length")
        # Retries after 1 s and 2 s (+ up to 20 % jitter): at most three sockets in 4 s.
        assert 2 <= count <= 3, count
        # REST polling keeps the state fresh meanwhile.
        polls = [call for call in page.evaluate("window.__apiCalls")
                 if call["path"] == "/api/v1/robot/state"]
        assert len(polls) >= 2
        browser.close()


def test_a_paired_token_expiring_beyond_seven_days_is_not_remembered():
    # M1: "로그인 유지(최대 7일)" must not keep a longer-lived token in localStorage.
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    reply = {"status": 201, "body": {
        "id": "b1c2d3e4f5a6", "token": "paired-test-token", "role": "operator", "label": "",
        "source": "pair-physical", "expires_at": "2099-10-01T00:00:00+00:00"}}
    init = NO_TOKEN_INIT + f"window.__pairReply = {json.dumps(reply)};"
    with sync_playwright() as playwright:
        try:
            browser, page = _open_dashboard(playwright, init)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.locator("#code-input").fill("ABCD-EFGH")
        page.locator("#code-remember").check()
        page.locator("#code-submit").click()
        page.wait_for_function(
            "document.getElementById('whoami-role')?.textContent === 'operator'")
        assert _storage(page) == {"session": "paired-test-token", "local": None}
        browser.close()


def test_a_socket_that_sends_one_frame_then_closes_still_backs_off():
    # L3: one delivered frame is not "stable"; the backoff keeps growing.
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page = _open_dashboard(playwright)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.wait_for_function("window.__sockets.length === 1")
        page.evaluate(
            "window.__flap = setInterval(() => {"
            "  for (const socket of window.__sockets) {"
            "    if (!socket.flapped && socket.sent.length) {"
            "      socket.flapped = true;"
            "      socket.dispatchEvent(new MessageEvent('message', {data: '{}'}));"
            "      socket.dispatchEvent(new CloseEvent('close', {code: 1011}));"
            "    }"
            "  }"
            "}, 10); null"
        )
        page.wait_for_timeout(4_000)
        count = page.evaluate("window.__sockets.length")
        assert 2 <= count <= 3, count
        browser.close()
