"""Optional browser-level safety test for ordered hold-to-drive shutdown."""

from __future__ import annotations

import json
import os
from urllib.parse import urlparse
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'middleware' / 'robot_ui' / "robot"
#: Production serves `/common/*` from the web_common package (core_api_web
#: mounts it; `test_ui_route.py` pins the 200s). The harness must mirror that
#: mount — app.js imports `/common/core_ui_logic.js` absolutely, and a request
#: with no route escapes to real DNS (rosy.test does not resolve) and kills the
#: boot before the first assertion.
WEB_COMMON = ROOT / "shared" / "web"

from browser_harness import browser_tests_enabled, open_page  # noqa: E402

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
    not browser_tests_enabled(),
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
      robot_number: 1, ros_domain_id: 41, ros_namespace: 'rosy_01',
      runtime_mode: 'hardware', caller_role: window.__callerRole || 'administrator',
    },
    '/api/v1/system/capabilities': {
      teleop: true, slam: true, docking: {supported: false},
      navigation: {goal_navigation: true},
      runtime: {drive: 'ready'},
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
      raw_available: true, raw_sequence: window.__cameraSequence,
    },
    '/api/v1/waypoints': {waypoints: []},
    '/api/v1/docking/status': {state: 'UNDOCKED', dock_id: null, supported: false},
    '/api/v1/docking/docks': {docks: []},
    '/api/v1/host/network': {available: false, detail: 'no agent'},
    '/api/v1/host/release': {available: false, detail: 'no agent'},
    '/api/v1/host/commissioning': {runtime_mode: 'core', fleet_hold: true, detail: 'core'},
    '/api/v1/host/hardware': window.__rosyHardware
      || {available: false, detail: '장치 점검 결과가 아직 없습니다', devices: []},
    // D-260 5: the summary line; {} (no state) unless a test sets one.
    '/api/v1/host/status-summary': window.__rosyStatusSummary || {},
  };
  if (window.__rosyCommissioningOverride) {
    Object.assign(bodies['/api/v1/host/commissioning'], window.__rosyCommissioningOverride);
  }
  if (method === 'POST' && path === '/api/v1/host/hardware/refresh') {
    return new Response(JSON.stringify({accepted: true, detail: '장치 점검을 요청했습니다.'}), {
      status: 200, headers: {'Content-Type': 'application/json'},
    });
  }
  // D-247 6: rosy-hw-test ran at once and CORE recorded the answer.
  if (method === 'POST' && path === '/api/v1/host/hardware/test') {
    const device = parsed && parsed.device;
    if (window.__rosyHardware) {
      window.__rosyHardware.test = {
        request_id: '00112233445566778899aabb', action: device, state: 'done',
        detail: device === 'buzzer' ? 'BCM 4 · 2 kHz · duty 10 % · 3×150 ms' : '빨강→초록→파랑 1 s씩 · 8 LED · GPIO19 · 꺼짐',
        finished_at: new Date().toISOString(),
      };
    }
    return new Response(JSON.stringify({accepted: true, request_id: '00112233445566778899aabb', device,
                                        detail: '부저를 울립니다. 들렸는지·보였는지 확인해 주세요.'}), {
      status: 200, headers: {'Content-Type': 'application/json'},
    });
  }
  if (method === 'POST' && path === '/api/v1/host/hardware/confirm') {
    const row = window.__rosyHardware?.devices.find((device) => device.id === parsed.device);
    if (row) {
      Object.assign(row, parsed.observed
        ? {state: 'ok', evidence: '사람 확인: 관리자 2026-09-26 05:00 UTC', source: 'human'}
        : {state: 'no_response', evidence: '사람 확인: 들리지 않음 · 관리자 2026-09-26 05:00 UTC', source: 'human'});
    }
    return new Response(JSON.stringify({recorded: true, device: parsed.device, observed: parsed.observed}), {
      status: 200, headers: {'Content-Type': 'application/json'},
    });
  }
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
  if (window.__rosySafetyOverride) {
    Object.assign(bodies['/api/v1/safety/state'], window.__rosySafetyOverride);
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
        'X-Rosy-Camera-Sequence': url.searchParams.get('sequence') || String(window.__cameraSequence),
        'X-Rosy-Camera-Captured-At': '42.25',
        'X-Rosy-Camera-Frame-Id': 'front_camera_link',
        'X-Rosy-Camera-Variant': url.searchParams.get('overlay') === 'true' ? 'annotated' : 'raw',
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
  if (path === '/api/v1/map' && window.__rosyMapSnapshot) {
    return new Response(JSON.stringify(window.__rosyMapSnapshot), {
      status: 200, headers: {'Content-Type': 'application/json'},
    });
  }
  if (path === '/api/v1/navigation/path' && window.__rosyPathSnapshot) {
    return new Response(JSON.stringify(window.__rosyPathSnapshot), {
      status: 200, headers: {'Content-Type': 'application/json'},
    });
  }
  return new Response(JSON.stringify(bodies[path] ?? {}), {
    status: 200, headers: {'Content-Type': 'application/json'},
  });
};
"""

def _launch_page(playwright, extra_init="", width=390, height=844, real_map=False):
    browser, page, _errors = open_page(playwright, width, height)
    html = (WEB / "index.html").read_text(encoding="utf-8")
    page.route(
        "http://rosy.test/dashboard",
        lambda route: route.fulfill(status=200, content_type="text/html", body=html),
    )
    page.route(
        "http://rosy.test/dashboard?*",
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
        if name == "map.js" and not real_map:
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

DEV_ENTRY_INIT = """
sessionStorage.removeItem('rosy.dashboard.token');
window.__devSessions = 0;
window.__devGate = new Promise(resolve => { window.__finishDevSession = resolve; });
const stubbed = window.fetch;
window.fetch = async (input, options = {}) => {
  const url = new URL(typeof input === 'string' ? input : input.url, location.href);
  if (url.pathname === '/api/v1/auth/connection') {
    window.__apiCalls.push({method: 'GET', path: url.pathname, search: '', body: null});
    return new Response(JSON.stringify({mode: 'development', robot_id: 'rosy_01', transport: 'http'}),
      {status: 200, headers: {'Content-Type': 'application/json'}});
  }
  if (url.pathname === '/api/v1/auth/development-session') {
    window.__devSessions += 1;
    window.__apiCalls.push({method: 'POST', path: url.pathname, search: '', body: null});
    await window.__devGate;
    return new Response(JSON.stringify({id: 'dev-1', token: 'dev-session-token', role: 'operator',
      label: 'Pilot development session', source: 'pair-development',
      expires_at: new Date(Date.now() + 3600000).toISOString()}),
      {status: 201, headers: {'Content-Type': 'application/json'}});
  }
  if (url.pathname === '/api/v1/ui/surfaces/console') {
    window.__apiCalls.push({method: 'GET', path: url.pathname, search: '', body: null});
    return new Response(JSON.stringify({surfaces: []}),
      {status: 200, headers: {'Content-Type': 'application/json'}});
  }
  return stubbed(input, options);
};
"""

def test_development_entry_logs_in_without_a_code():
    """D-432/D-471: 개발 모드 로봇은 로그인 서랍에 코드 없는 입장이 열리고, 누르면 세션이 든다."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        try:
            browser, page = _launch_page(playwright, extra_init=DEV_ENTRY_INIT)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.goto("http://rosy.test/dashboard", wait_until="domcontentloaded", timeout=5_000)
        # 토큰 없이 부팅 → 서랍 열림 + 개발 연결 모드 조사 후 버튼 등장.
        page.wait_for_function("!document.getElementById('dev-connect-row').hidden")
        page.wait_for_function(
            "window.__apiCalls.some((call) => call.path === '/api/v1/auth/connection')")
        # 코드 폼은 그대로 있고, 개발 입장은 세션을 받아 화면에 들어간다.
        assert page.locator("#code-form").is_visible()
        page.click("#dev-connect")
        page.wait_for_function(
            "window.__apiCalls.some((call) => call.path === '/api/v1/auth/development-session')")
        page.wait_for_function("window.__devSessions === 1")
        page.evaluate("window.__finishDevSession()")
        # 엔트리 경로(/dashboard)에서는 로봇 상태 패널이 없으므로 목적지 영역으로 확인한다.
        page.wait_for_function("!document.getElementById('entry-destinations').hidden")
        assert sessionStorage_token(page) == "dev-session-token"
        page.wait_for_function(
            "document.querySelector('.entry-heading h1')?.textContent === '작업을 선택하세요'")
        browser.close()

def test_paired_connection_never_offers_development_entry():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser, page = _launch_page(
            playwright, extra_init=DEV_ENTRY_INIT.replace("mode: 'development'", "mode: 'paired'"))
        page.goto("http://rosy.test/dashboard", wait_until="domcontentloaded", timeout=5_000)
        page.wait_for_function(
            "window.__apiCalls.some((call) => call.path === '/api/v1/auth/connection')")
        assert page.locator("#dev-connect-row").is_hidden()
        browser.close()

def test_compatibility_development_entry_names_pending_reason():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser, page = _launch_page(playwright, extra_init=DEV_ENTRY_INIT)
        page.goto("http://rosy.test/dashboard?view=compatibility", wait_until="domcontentloaded")
        page.wait_for_function("!document.getElementById('dev-connect-row').hidden")
        page.click("#dev-connect")
        page.wait_for_function("window.__devSessions === 1")
        assert page.locator("#dev-connect").is_disabled()
        assert page.locator("#dev-connect").get_attribute("reason") == "개발 연결 확인 중"
        page.evaluate("window.__finishDevSession()")
        page.wait_for_function("document.getElementById('dev-connect').getAttribute('reason') === null")
        browser.close()

def sessionStorage_token(page):
    return page.evaluate("sessionStorage.getItem('rosy.dashboard.token')")

def test_delayed_positive_request_cannot_arrive_after_release_zero():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        try:
            browser, page = _launch_page(playwright)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.goto("http://rosy.test/dashboard#compatibility", wait_until="domcontentloaded", timeout=5_000)
        page.wait_for_function(
            "document.getElementById('robot-mode')?.textContent === '수동'"
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
        assert page.locator("#bench-safety-confirmed").count() == 0
        assert page.locator('[data-teleop="left"]').get_attribute("data-angular") == "0.1"
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
    assert commands[0] == {"linear": 0.03, "angular": 0}
    assert commands[-1] == {"linear": 0, "angular": 0}
    # 부하에서 100ms 틱이 pointerup 전에 두 번째 drive를 쏠 수 있다. 계약은
    # 순서다 — 해제 zero 뒤에 양수가 오면 안 된다. zero 뒤는 전부 zero다.
    first_zero = next(
        i for i, command in enumerate(commands)
        if command == {"linear": 0, "angular": 0}
    )
    assert all(
        command == {"linear": 0, "angular": 0} for command in commands[first_zero:]
    )

def test_field_settings_save_limits_waypoint_and_dock_without_navigation():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        try:
            browser, page = _launch_page(playwright)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.goto("http://rosy.test/dashboard#compatibility", wait_until="domcontentloaded", timeout=5_000)
        page.wait_for_function(
            "document.getElementById('robot-mode')?.textContent === '수동'"
        )
        page.locator("#view-inspect").click()
        page.locator("#field-settings-panel").scroll_into_view_if_needed()
        assert page.locator("#robot-number-input").input_value() == "1"
        assert page.locator("#ros-domain-input").input_value() == "41"
        assert page.locator("#ros-namespace-input").input_value() == "rosy_01"
        assert page.locator("#ros-domain-input").get_attribute("readonly") is not None
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

WAYPOINT_ROW_INIT = """
const listed = window.fetch;
window.fetch = async (input, options = {}) => {
  const url = new URL(typeof input === 'string' ? input : input.url, location.href);
  if ((options.method || 'GET').toUpperCase() === 'GET' && url.pathname === '/api/v1/waypoints') {
    window.__apiCalls.push({method: 'GET', path: url.pathname, search: '', body: null});
    return new Response(JSON.stringify({waypoints: [{name: 'zone_a', x: 1.25, y: 0.5, yaw: 0}]}),
      {status: 200, headers: {'Content-Type': 'application/json'}});
  }
  return listed(input, options);
};
"""

def test_waypoint_delete_dialog_keeps_the_estop_out_of_the_inert_region():
    """D-371 non-modal confirm on the legacy /dashboard settings list.

    The E-stop lives on the operate view, which is hidden while the inspect view
    shows the settings list, so here the check is that the dialog never inerts it
    (it is reachable again the moment the operator switches back), that the rest
    of the page is inert while open, and that Esc and cancel send no DELETE.
    """
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        try:
            browser, page = _launch_page(playwright, extra_init=WAYPOINT_ROW_INIT, width=1366, height=768)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.goto("http://rosy.test/dashboard#compatibility", wait_until="domcontentloaded", timeout=5_000)
        page.wait_for_function("document.getElementById('robot-mode')?.textContent === '수동'")
        page.locator("#view-inspect").click()
        delete = page.locator('li[data-name="zone_a"] [data-waypoint-action="delete"]')
        delete.wait_for()
        assert page.locator("#emergency-stop").get_attribute("data-always-live") is not None
        delete.click()
        dialog = page.locator("dialog.ui-confirm")
        assert dialog.is_visible()
        assert page.evaluate("document.getElementById('emergency-stop').closest('[inert]')") is None
        assert page.evaluate("document.getElementById('waypoint-save').closest('[inert]') !== null")
        assert page.evaluate("document.getElementById('view-operate').closest('[inert]') !== null")
        page.keyboard.press("Escape")
        page.wait_for_function("!document.querySelector('dialog.ui-confirm')")
        delete.click()
        dialog.locator("ui-button[kind=quiet]").click()
        page.wait_for_function("!document.querySelector('dialog.ui-confirm')")
        assert page.evaluate("document.querySelectorAll('[inert]').length") == 0
        calls = page.evaluate("window.__apiCalls")
        browser.close()
    assert not any(call["method"] == "DELETE" for call in calls)

def test_traffic_policy_is_staged_before_stopped_only_apply():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        try:
            browser, page = _launch_page(playwright)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.goto(
            "http://rosy.test/dashboard#compatibility",
            wait_until="domcontentloaded",
            timeout=5_000,
        )
        # D-201 — 정책 편집은 점검 뷰(절차 문법)의 현장 설정 카드에 산다.
        page.wait_for_selector('#compatibility-shell[data-ready="true"]')
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
        page.locator('dialog.ui-confirm ui-button[kind=irreversible]').click()
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
            "http://rosy.test/dashboard#compatibility",
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
        assert page.locator("#vision-status").inner_text() == "실시간"
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
    assert frame_call["search"] == "?sequence=7&overlay=false"

def test_unavailable_camera_keeps_missing_timestamps_missing():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        try:
            browser, page = _launch_page(
                playwright,
                extra_init="window.__rosyVisionOverride = {available: false, stale: false, "
                "source: null, width: null, height: null, age_ms: null, captured_at: null};",
            )
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.goto("http://rosy.test/dashboard#compatibility", wait_until="domcontentloaded", timeout=5_000)
        page.wait_for_function(
            "window.__apiCalls?.some((call) => call.path === '/api/v1/vision/front/status')"
        )
        page.wait_for_timeout(100)
        assert page.locator("#vision-age").inner_text() == "\u2014"
        assert page.locator("#vision-captured").inner_text() == "\u2014"
        browser.close()

def test_camera_preview_is_cleared_when_reauthentication_fails():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        try:
            browser, page = _launch_page(playwright)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.goto(
            "http://rosy.test/dashboard#compatibility",
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
        assert page.locator("#vision-status").inner_text() == "수신 대기"
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
            "http://rosy.test/dashboard#compatibility",
            wait_until="domcontentloaded",
            timeout=5_000,
        )
        page.wait_for_function(
            "document.getElementById('vision-stage')?.dataset.state === 'live'"
        )
        page.evaluate("window.__cameraSequence = 8; window.__cameraFrameStatus = 429")
        page.wait_for_function(
            "document.getElementById('vision-empty')?.textContent.includes('camera raw 429')"
        )
        assert page.locator("#vision-frame").is_hidden()
        assert page.locator("#vision-status").inner_text() == "수신 대기"
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

def test_compatibility_controls_wait_for_their_handlers():
    """A delayed module must not expose a clickable control that loses its click."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright
    with sync_playwright() as playwright:
        browser, page = _launch_page(playwright, extra_init=CONSOLE_STATE_INIT["rmw-mismatch"])
        held = []
        page.route("**/app.js", lambda route: held.append(route))
        try:
            page.goto("http://rosy.test/dashboard#compatibility", wait_until="commit")
            inspect = page.locator("#view-inspect")
            inspect.wait_for(state="visible")
            page.wait_for_function("!document.getElementById('compatibility-shell').hidden")
            assert len(held) == 1, "The actual module request must remain pending"
            with pytest.raises(PlaywrightTimeoutError):
                inspect.click(timeout=250)
            held.pop().fallback()
            inspect.click()
            page.wait_for_function("!document.getElementById('view-inspect-panel').hidden")
            assert page.locator("#dds-rmw").is_visible()
            assert page.locator("#ros-risk-list").is_visible()
        finally:
            for route in held:
                route.fallback()
            browser.close()

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
            "http://rosy.test/dashboard#compatibility",
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
                "document.getElementById('robot-mode')?.textContent === '안전 정지'"
            )
        elif state == "vision-unavailable":
            page.wait_for_function(
                "document.getElementById('vision-status')?.textContent === '수신 대기'"
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

def test_compatibility_settings_confirmation_preserves_stop_and_rechecks_named_targets():
    from playwright.sync_api import sync_playwright, expect
    with sync_playwright() as playwright:
        browser, page = _launch_page(playwright, extra_init=WAYPOINT_ROW_INIT)
        page.goto('http://rosy.test/dashboard#compatibility')
        page.wait_for_selector('#compatibility-shell[data-ready="true"]')
        page.locator('#view-inspect').click()
        page.locator('li[data-name="zone_a"]').wait_for()
        page.evaluate("async()=>{const {session}=await import('/dashboard/assets/client.js');clearInterval(session.refreshTimer);session.refreshTimer=null;}")
        page.locator('#waypoint-name').fill('zone_a')
        page.locator('#waypoint-save').click()
        dialog = page.locator('dialog.ui-confirm')
        expect(dialog).to_have_count(1, timeout=3000)
        assert '"zone_a"' in dialog.inner_text()
        page.locator('#emergency-stop').click()
        assert page.evaluate("__apiCalls.some(c=>c.path==='/api/v1/safety/stop')")
        if dialog.count():
            dialog.locator('ui-button[kind=quiet]').click()
        page.locator('#view-inspect').click()
        page.locator('#waypoint-save').click()
        page.evaluate("async()=>{const {session}=await import('/dashboard/assets/client.js');session.robotState.pose.x=9;session.robotState.map_id='changed-map';}")
        dialog.locator('ui-button[kind=irreversible]').click()
        assert page.evaluate("__apiCalls.filter(c=>c.method==='PUT'&&c.path.includes('/waypoints/')).length") == 0
        page.locator('li[data-name="zone_a"] [data-waypoint-action=go]').click()
        page.evaluate("async()=>{const {session}=await import('/dashboard/assets/client.js');session.waypoints=[];}")
        dialog.locator('ui-button[kind=irreversible]').click()
        assert page.evaluate("__apiCalls.filter(c=>c.path==='/api/v1/navigation/goal').length") == 0
        browser.close()

@pytest.mark.parametrize("width,height", [(390, 844), (1366, 768)])
def test_compatibility_slam_start_reports_session_acceptance(width, height):
    from playwright.sync_api import sync_playwright, expect
    with sync_playwright() as playwright:
        browser, page = _launch_page(playwright, width=width, height=height)
        page.goto('http://rosy.test/dashboard#compatibility')
        page.wait_for_selector('#compatibility-shell[data-ready="true"]')
        page.locator('#view-inspect').click()
        page.locator('#slam-start').click()
        page.locator('dialog.ui-confirm ui-button[kind=irreversible]').click()
        expect(page.locator('#slam-message')).to_have_text('맵핑 세션을 수락했습니다. 지도 갱신은 확인되지 않았습니다.')
        assert page.evaluate("__apiCalls.some(c=>c.path==='/api/v1/slam/start')")
        assert page.locator('.settings-card[aria-labelledby="slam-heading"]').evaluate('(card) => card.getBoundingClientRect().height') < 500
        if shot_dir := os.environ.get('ROSY_DASHBOARD_STATE_SHOT_DIR'):
            output = Path(shot_dir) / f"compatibility_slam_session_{width}x{height}_local.png"
            output.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(output), full_page=True)
            card = page.locator('.settings-card[aria-labelledby="slam-heading"]')
            card.evaluate('(element) => element.scrollIntoView({block: "center"})')
            card.screenshot(path=str(output.with_name(f"compatibility_slam_card_{width}x{height}_local.png")))
        browser.close()

def test_compatibility_traffic_confirmation_abort_releases_new_owner_without_old_readback():
    from playwright.sync_api import sync_playwright, expect
    with sync_playwright() as playwright:
        browser, page = _launch_page(playwright)
        page.goto('http://rosy.test/dashboard#compatibility')
        page.wait_for_selector('#compatibility-shell[data-ready="true"]')
        page.locator('#view-inspect').click()
        page.locator('#traffic-policy-revision-input').fill('guarded-policy-a')
        page.locator('#traffic-policy-stage').click()
        page.wait_for_function('() => !document.querySelector("#traffic-policy-apply").disabled')
        page.evaluate("""() => {const previous=fetch;window.fetch=(url,options={})=>String(url).endsWith('/api/v1/traffic/policy/apply')?new Promise(resolve=>window.finishOldPolicy=()=>resolve(new Response(JSON.stringify(__trafficReadback)))):previous(url,options);}""")
        page.locator('#traffic-policy-apply').click()
        dialog = page.locator('dialog.ui-confirm')
        expect(dialog).to_have_count(1, timeout=3000)
        dialog.locator('ui-button[kind=irreversible]').click()
        page.wait_for_function('() => typeof finishOldPolicy === "function"')
        page.evaluate('() => dispatchEvent(new PageTransitionEvent("pagehide"))')
        page.evaluate('() => dispatchEvent(new PageTransitionEvent("pageshow", {persisted:true}))')
        page.wait_for_function('() => !document.querySelector("#traffic-policy-stage").disabled', timeout=3000)
        page.locator('#traffic-policy-revision-input').fill('guarded-policy-b')
        page.locator('#traffic-policy-stage').click()
        page.wait_for_function('() => document.querySelector("#traffic-policy-message").textContent.includes("guarded-policy-b")')
        message = page.locator('#traffic-policy-message').inner_text()
        page.evaluate('() => finishOldPolicy()')
        page.wait_for_timeout(100)
        assert page.locator('#traffic-policy-message').inner_text() == message
        browser.close()

def test_compatibility_confirmation_keeps_stop_live_and_owns_command_completion():
    from playwright.sync_api import sync_playwright, expect
    with sync_playwright() as playwright:
        browser, page = _launch_page(playwright)
        page.goto('http://rosy.test/dashboard#compatibility')
        page.wait_for_function("document.querySelector('#robot-mode').textContent==='수동'")
        page.locator('[data-mode=IDLE]').click()
        dialog = page.locator('dialog.ui-confirm')
        expect(dialog).to_have_count(1)
        expect(dialog.get_by_role('button', name='요청 전송', exact=True)).to_be_visible()
        page.locator('[data-mode=IDLE]').dispatch_event('click')
        expect(dialog).to_have_count(1)
        page.locator('#emergency-stop').click()
        expect(dialog).to_have_count(0)
        assert page.evaluate("__apiCalls.filter(c=>c.path==='/api/v1/mode').length") == 0
        assert page.evaluate("__apiCalls.filter(c=>c.path==='/api/v1/safety/stop').length") == 1
        page.evaluate("""() => { const prior=fetch;window.fetch=(url,options={})=>String(url).endsWith('/api/v1/mode')?new Promise(resolve=>{window.finishMode=()=>resolve(new Response('{}'));window.modeBody=JSON.parse(options.body);}):prior(url,options); }""")
        page.locator('[data-mode=IDLE]').click()
        dialog.locator('ui-button[kind=irreversible]').click()
        page.wait_for_function("typeof finishMode==='function'")
        page.locator('#dds-cyclone-apply').dispatch_event('click')
        expect(dialog).to_have_count(0)
        assert page.evaluate('window.modeBody') == {'mode': 'IDLE'}
        page.evaluate('finishMode()')
        page.wait_for_function("document.querySelector('[data-mode=IDLE]').disabled===false")
        page.locator('[data-line-mode=IR_LINE]').click()
        page.locator('[data-line-mode=OFF]').evaluate("button=>button.scrollIntoView({block:'end'})")
        page.locator('#emergency-stop').click(timeout=3_000)
        expect(dialog).to_have_count(0)
        page.wait_for_function("__apiCalls.filter(c=>c.path==='/api/v1/safety/stop').length===2")
        page.locator('[data-line-mode=IR_LINE]').click()
        page.locator('[data-line-mode=OFF]').evaluate("button=>button.scrollIntoView({block:'end'})")
        page.mouse.move(380, 680)
        page.mouse.wheel(0, 150)
        page.wait_for_function("document.querySelector('[data-line-mode=OFF]').getBoundingClientRect().top<750")
        page.locator('[data-line-mode=OFF]').click()
        expect(dialog).to_have_count(0)
        page.wait_for_function("__apiCalls.some(c=>c.path==='/api/v1/line-follow/mode' && c.body.mode==='OFF')")
        page.evaluate("""() => {const prior=fetch;window.fetch=(url,options={})=>String(url).endsWith('/api/v1/line-follow/mode')?new Promise(resolve=>{const finish=()=>resolve(new Response(JSON.stringify({mode:JSON.parse(options.body).mode,state:'FOLLOW'})));if(JSON.parse(options.body).mode==='OFF')window.finishOff=finish;else window.finishLine=finish;}):prior(url,options);}""")
        page.locator('[data-line-mode=IR_LINE]').click()
        dialog.locator('ui-button[kind=irreversible]').click()
        page.wait_for_function("typeof finishLine==='function'")
        expect(page.locator('[data-line-mode=OFF]')).to_be_enabled()
        page.locator('[data-line-mode=OFF]').click()
        page.wait_for_function("typeof finishOff==='function'")
        page.evaluate('finishLine()')
        page.wait_for_timeout(80)
        expect(page.locator('[data-line-mode=IR_LINE]')).to_be_disabled()
        page.evaluate('finishOff()')
        page.wait_for_function("!document.querySelector('[data-line-mode=IR_LINE]').disabled")
        expect(page.locator('[data-line-mode=OFF]')).to_have_attribute('aria-pressed','true')
        browser.close()

@pytest.mark.parametrize("viewport", [(390, 844), (1366, 768)])
def test_compatibility_lane_follow_uses_drive_readiness_without_nav2(viewport):
    from playwright.sync_api import sync_playwright, expect
    with sync_playwright() as playwright:
        browser, page = _launch_page(playwright, width=viewport[0], height=viewport[1], extra_init="""
          window.__rosyCapabilitiesOverride = {
            teleop: true, navigation: {goal_navigation: false}, runtime: {drive: 'ready'}
          };
        """)
        page.goto("http://rosy.test/dashboard#compatibility")
        button = page.locator('[data-line-mode="IR_LINE"]')
        page.wait_for_function("document.querySelector('#robot-mode')?.textContent === '수동'")
        if output := os.environ.get("ROSY_SCREENSHOT_DIR"):
            shots = Path(output)
            shots.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(shots / f"lane-follow-no-nav2-{viewport[0]}x{viewport[1]}.png"), full_page=True)
        expect(button).to_be_enabled()
        button.click()
        dialog = page.locator("dialog.ui-confirm")
        expect(dialog).to_have_count(1)
        page.evaluate("""async () => {
          const {session} = await import('/dashboard/assets/client.js');
          const {updateLineFollowButtons} = await import('/dashboard/assets/telemetry.js');
          session.capabilities.runtime.drive = 'disabled';
          updateLineFollowButtons();
        }""")
        dialog.locator("ui-button[kind=irreversible]").click()
        expect(dialog).to_have_count(0)
        assert not page.evaluate("window.__apiCalls.some(call => call.path === '/api/v1/line-follow/mode')")
        expect(button).to_be_disabled()
        assert button.get_attribute("reason") == "구동 준비 확인 필요"
        expect(page.locator('[data-line-mode="OFF"]')).to_be_enabled()
        page.evaluate("""async () => {
          const {session} = await import('/dashboard/assets/client.js');
          const {updateLineFollowButtons} = await import('/dashboard/assets/telemetry.js');
          session.capabilities.runtime.drive = 'ready';
          updateLineFollowButtons();
        }""")
        button.click()
        dialog.locator("ui-button[kind=irreversible]").click()
        page.wait_for_function("window.__apiCalls.some(call => call.path === '/api/v1/line-follow/mode' && call.body.mode === 'IR_LINE')")
        browser.close()

def test_compatibility_confirmation_rechecks_capability_and_network_targets():
    from playwright.sync_api import sync_playwright, expect
    with sync_playwright() as playwright:
        browser, page = _launch_page(playwright)
        page.goto('http://rosy.test/dashboard#compatibility')
        page.wait_for_function("document.querySelector('#robot-mode').textContent==='수동'")
        page.locator('[data-mode=NAVIGATION]').click()
        dialog = page.locator('dialog.ui-confirm')
        page.evaluate("async()=>{const {session}=await import('/dashboard/assets/client.js');session.capabilities.navigation.goal_navigation=false;}")
        dialog.locator('ui-button[kind=irreversible]').click()
        assert page.evaluate("__apiCalls.filter(c=>c.path==='/api/v1/mode').length") == 0
        page.locator('#view-inspect').click()
        page.evaluate("async()=>{const {session}=await import('/dashboard/assets/client.js');clearInterval(session.refreshTimer);session.refreshTimer=null;document.querySelector('#network-card').dataset.available='true';document.querySelector('#network-connect').disabled=false;document.querySelector('#network-apply').disabled=false;}")
        page.locator('#network-ssid-input').fill('fixture-a')
        page.locator('#network-psk-input').fill('fixture-secret')
        page.locator('#network-connect').click()
        page.locator('#network-ssid-input').evaluate("input=>input.value='fixture-b'")
        dialog.locator('ui-button[kind=irreversible]').click()
        assert page.evaluate("__apiCalls.filter(c=>c.path==='/api/v1/host/network/connect').length") == 0
        assert page.locator('#network-psk-input').input_value() == 'fixture-secret'
        page.locator('#network-connect').click()
        dialog.locator('ui-button[kind=irreversible]').click()
        page.wait_for_function("__apiCalls.some(c=>c.path==='/api/v1/host/network/connect')")
        body=page.evaluate("__apiCalls.find(c=>c.path==='/api/v1/host/network/connect').body")
        assert body['ssid']=='fixture-b' and body['psk']=='fixture-secret' and body['confirmed'] is True
        assert body['idempotency_key']
        expect(page.locator('#network-psk-input')).to_have_value('')
        browser.close()

@pytest.mark.parametrize("viewport", [(390, 844), (1366, 768)])
def test_compatibility_old_auth_and_pagehide_cancel_confirmation_and_readbacks(viewport):
    from playwright.sync_api import sync_playwright, expect
    with sync_playwright() as playwright:
        browser, page = _launch_page(playwright, width=viewport[0], height=viewport[1], real_map=True, extra_init="""
          const interval=setInterval;
          window.setInterval=(fn,ms)=>{if(ms===5000)window.slowTick=fn;return interval(fn,ms);};
          window.__rosyMapSnapshot={width:10,height:10,resolution:1,origin:{x:-5,y:-5},
            data:Array(100).fill(0),map_id:'fixture-map'};
        """)
        page.goto('http://rosy.test/dashboard#compatibility')
        page.wait_for_function("document.querySelector('#robot-mode').textContent==='수동'")
        page.evaluate("""async()=>{const {session}=await import('/dashboard/assets/client.js');clearInterval(session.refreshTimer);session.refreshTimer=null;const prior=fetch;window.fetch=(url,options={})=>String(url).endsWith('/api/v1/mode')?new Promise(resolve=>window.finishOldMode=()=>resolve(new Response('{}'))):prior(url,options);}""")
        page.locator('[data-mode=IDLE]').click()
        page.locator('dialog.ui-confirm ui-button[kind=irreversible]').click()
        page.wait_for_function("typeof finishOldMode==='function'")
        page.locator('#open-auth').click()
        page.locator('#auth-tab-token').click()
        page.locator('#token-input').fill('replacement-fixture-token')
        page.locator('#auth-form').evaluate('form=>form.requestSubmit()')
        page.wait_for_function("document.querySelector('#auth-message').textContent==='연결되었습니다.'")
        before=page.evaluate("__apiCalls.filter(c=>c.path==='/api/v1/robot/state').length")
        page.evaluate('finishOldMode()')
        page.wait_for_timeout(80)
        assert page.evaluate("__apiCalls.filter(c=>c.path==='/api/v1/robot/state').length") == before
        assert '모드 요청을 전송했습니다' not in page.locator('#action-message').inner_text()
        page.wait_for_function("document.querySelector('#map-status')?.getAttribute('state') === 'ready'")
        page.locator('[data-map-click=goal]').click()
        page.locator('#map-canvas').focus()
        page.locator('#map-canvas').press('Enter')
        expect(page.locator('dialog.ui-confirm')).to_have_count(1)
        if output := os.environ.get("ROSY_SCREENSHOT_DIR"):
            shots = Path(output)
            shots.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(shots / f"auth-map-goal-confirm-{viewport[0]}x{viewport[1]}.png"), full_page=True)
        page.locator('#token-input').evaluate("input=>input.value='map-replacement-fixture-token'")
        page.locator('#auth-form').evaluate('form=>form.requestSubmit()')
        expect(page.locator('dialog.ui-confirm')).to_have_count(0)
        page.wait_for_function("document.querySelector('#auth-message').textContent==='연결되었습니다.'")
        assert page.evaluate("__apiCalls.filter(c=>c.path==='/api/v1/navigation/goal').length") == 0
        page.evaluate("""() => {const prior=fetch;let first=true;window.fetch=(url,options={})=>String(url).endsWith('/api/v1/auth/whoami')&&first?(first=false,new Promise(resolve=>window.finishRefusal=()=>resolve(new Response('{"detail":"old identity revoked"}',{status:401})))):prior(url,options);__sockets.at(-1).dispatchEvent(new CloseEvent('close',{code:4401}));}""")
        page.wait_for_function("typeof finishRefusal==='function'")
        page.locator('#token-input').evaluate("input=>input.value='post-refusal-fixture-token'")
        page.locator('#auth-form').evaluate('form=>form.requestSubmit()')
        page.wait_for_function("document.querySelector('#auth-message').textContent==='연결되었습니다.'")
        page.evaluate('finishRefusal()')
        page.wait_for_timeout(80)
        assert page.evaluate("sessionStorage.getItem('rosy.dashboard.token')") == 'post-refusal-fixture-token'
        assert page.locator('#robot-mode').inner_text() == '수동'
        for failed in (False, True):
            page.evaluate("""() => {const prior=fetch;let first=true;window.fetch=(url,options={})=>String(url).endsWith('/api/v1/map')&&first?(first=false,new Promise((resolve,reject)=>{window.finishMap=()=>resolve(new Response(JSON.stringify({width:2,height:2,resolution:1,origin:{x:0,y:0,yaw:0},data:[100,100,100,100],map_id:'obsolete-map'})));window.failMap=()=>reject(new Error('obsolete map failure'));})):prior(url,options);slowTick();}""")
            page.wait_for_function("typeof finishMap==='function'")
            page.locator('#open-auth').click()
            page.locator('#auth-tab-token').click()
            page.locator('#token-input').fill(f'next-fixture-token-{failed}')
            page.locator('#auth-form').evaluate('form=>form.requestSubmit()')
            page.wait_for_function("document.querySelector('#auth-message').textContent==='연결되었습니다.'")
            snapshot=page.locator('#field-map-panel').inner_html()
            raster=page.locator('#map-canvas').evaluate('canvas=>canvas.toDataURL()')
            page.evaluate('failMap()' if failed else 'finishMap()')
            page.wait_for_timeout(80)
            assert page.locator('#field-map-panel').inner_html()==snapshot
            assert page.locator('#map-canvas').evaluate('canvas=>canvas.toDataURL()')==raster
            page.evaluate('delete window.finishMap;delete window.failMap')
        page.evaluate("""() => {const prior=fetch;window.fetch=(url,options={})=>String(url).endsWith('/api/v1/navigation/goal')&&options.method==='POST'?new Promise(resolve=>window.finishGoal=()=>resolve(new Response('{}'))):prior(url,options);}""")
        page.locator('#map-canvas').focus()
        page.locator('#map-canvas').press('Enter')
        page.locator('dialog.ui-confirm ui-button[kind=irreversible]').click()
        page.wait_for_function("typeof finishGoal==='function'")
        page.locator('[data-mode=IDLE]').click()
        page.locator('dialog.ui-confirm').wait_for()
        page.evaluate("""() => {window.oldSocket=__sockets.at(-1);const prior=fetch;let first=true;window.fetch=(url,options={})=>String(url).endsWith('/api/v1/auth/whoami')&&first?(first=false,new Promise(resolve=>window.finishHiddenRefusal=()=>resolve(new Response('{"role":"administrator"}')))):prior(url,options);oldSocket.dispatchEvent(new CloseEvent('close',{code:4401}));}""")
        page.wait_for_function("typeof finishHiddenRefusal==='function'")
        page.evaluate("window.dispatchEvent(new PageTransitionEvent('pagehide'))")
        expect(page.locator('dialog.ui-confirm')).to_have_count(0)
        snapshot=page.locator('#connection-badge').inner_html()
        calls=page.evaluate('__apiCalls.length')
        count=page.evaluate('__sockets.length')
        map_snapshot=page.locator('#field-map-panel').inner_html()
        map_raster=page.locator('#map-canvas').evaluate('canvas=>canvas.toDataURL()')
        action=page.locator('#action-message').inner_html()
        page.evaluate('finishGoal()')
        page.evaluate('finishHiddenRefusal()')
        page.evaluate("oldSocket.dispatchEvent(new MessageEvent('message',{data:JSON.stringify({mode:'NAVIGATION'})}));oldSocket.dispatchEvent(new CloseEvent('close',{code:1006}))")
        page.wait_for_timeout(1_150)
        assert page.locator('#connection-badge').inner_html()==snapshot
        assert page.evaluate('__apiCalls.length')==calls
        assert page.evaluate('__sockets.length')==count
        assert page.locator('#field-map-panel').inner_html()==map_snapshot
        assert page.locator('#map-canvas').evaluate('canvas=>canvas.toDataURL()')==map_raster
        assert page.locator('#action-message').inner_html()==action
        page.evaluate("window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}))")
        page.wait_for_function('__sockets.length>'+str(count))
        page.evaluate("oldSocket.dispatchEvent(new MessageEvent('message',{data:JSON.stringify({mode:'NAVIGATION'})}))")
        assert page.locator('#robot-mode').inner_text()=='수동'
        browser.close()

def test_irreversible_mode_change_needs_confirm_and_decline_blocks_it():
    """D-92(a)/D-153 G3-5 — 불가역 모드 변경은 confirm을 지나며 거부하면 안 나간다."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        try:
            browser, page = _launch_page(playwright)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.goto(
            "http://rosy.test/dashboard#compatibility",
            wait_until="domcontentloaded",
            timeout=5_000,
        )
        page.wait_for_function(
            "document.getElementById('robot-mode')?.textContent === '수동'"
        )
        page.locator('[data-mode="IDLE"]').click()
        dialog = page.locator("dialog.ui-confirm")
        dialog.wait_for()
        prompt = dialog.locator("p").inner_text()
        dialog.locator("ui-button[kind=quiet]").click()
        declined_calls = page.evaluate(
            "window.__apiCalls.filter((call) => call.path === '/api/v1/mode')"
        )
        page.locator('[data-mode="IDLE"]').click()
        dialog.locator("ui-button[kind=irreversible]").click()
        page.wait_for_function(
            "window.__apiCalls.some((call) => call.path === '/api/v1/mode')"
        )
        browser.close()
    # D-359 US-009 (P2-2 review) — the confirm names the mode in Korean, never the enum.
    assert "대기 모드로 변경할까요" in prompt and "IDLE" not in prompt
    assert declined_calls == []
