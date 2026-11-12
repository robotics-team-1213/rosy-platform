from __future__ import annotations

from test_dashboard_browser import (
    json, os, Path, pytest, WARM_SCAN, pytestmark, _launch_page, CONSOLE_STATE_INIT,
)


def test_irreversible_cyclone_apply_needs_confirm_and_decline_blocks_it():
    """D-123/D-92(a) — Cyclone 적용(저장+재부팅)도 confirm을 지나며 거부하면 안 나간다."""
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
        page.locator("#view-inspect").click()
        page.locator("#dds-cyclone-apply").click()
        dialog = page.locator("dialog.ui-confirm")
        dialog.wait_for()
        prompt = dialog.locator("p").inner_text()
        dialog.locator("ui-button[kind=quiet]").click()
        declined = page.evaluate(
            "window.__apiCalls.filter((call) =>"
            " call.path === '/api/v1/system/dds/cyclone')"
        )
        page.locator("#dds-cyclone-apply").click()
        dialog.locator("ui-button[kind=irreversible]").click()
        page.wait_for_function(
            "window.__apiCalls.some((call) =>"
            " call.path === '/api/v1/system/dds/cyclone')"
        )
        browser.close()
    assert "CycloneDDS를 저장하고 로봇을 재부팅할까요" in prompt
    assert declined == []

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
        page.goto("http://rosy.test/dashboard#compatibility", wait_until="domcontentloaded", timeout=5_000)
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
        assert "하드웨어 런타임 꺼짐" in capabilities
        assert page.locator('#capability-list [data-cause="runtime"]').count() == 5
        assert page.locator('[data-teleop="forward"]').is_disabled()
        # 4. hero and banner agree: no source, and the reason is CORE-only
        assert "하드웨어 런타임 꺼짐" in page.locator("#safety-source").inner_text()
        triage_text = page.locator("#triage").inner_text()
        assert "수신 끊김" not in triage_text
        assert "출처는 있는데" not in triage_text
        assert page.locator("#triage-title").inner_text() == "하드웨어 런타임 꺼짐"
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
        page.goto("http://rosy.test/dashboard#compatibility", wait_until="domcontentloaded", timeout=5_000)
        page.wait_for_function(
            "document.getElementById('triage-title')?.textContent === '안전 회로 수신 끊김'"
        )
        assert page.locator("#safety-label").inner_text() == "UNVERIFIED"
        assert page.locator("#safety-source").inner_text() == "안전 회로 수신 끊김"
        browser.close()

# Release 2026.09.24-010, rosy-pinky-e4us: CORE-only image, operator started
# rosy-io in no-motion mode. Battery and odometry flowed, motor/ready was
# false. The page said "HW OFF" and 5 / 5 motion capabilities available.
NO_MOTION_INIT = """
    window.__rosyInfoOverride = {robot_name: 'rosy-pinky-e4us', runtime_mode: 'core'};
    const fresh = (stale) => ({received_at: '2026-09-24T00:00:00.000Z', evidence: 'fresh', stale_after_s: stale});
    window.__rosyStateOverrides = {robot_state: {
      battery: {percent: 100, voltage: 8.69},
      evidence: {
        pose: fresh(2.0), velocity: fresh(0.5), battery: fresh(5.0),
        navigation: {received_at: null, evidence: 'unavailable', stale_after_s: 2.0},
        safety: {received_at: null, evidence: 'unavailable', stale_after_s: 0.2},
      },
    }};
    const drive = 'drive_disabled:no_motion';
    window.__rosyCapabilitiesOverride = {
      teleop: false, slam: false, docking: {supported: false},
      navigation: {goal_navigation: false, return_home: false},
      swarm: {follow: false, lead: false},
      withheld: {
        flags: ['teleop', 'navigation.goal_navigation', 'swarm.follow', 'swarm.lead',
                'slam', 'navigation.return_home'],
        reason: drive,
        reasons: {teleop: drive, 'navigation.goal_navigation': drive, 'swarm.follow': drive,
                  'swarm.lead': drive, slam: 'navigation_absent', 'navigation.return_home': drive},
      },
      runtime: {mode: 'core', hardware: 'on', evidence: ['odometry', 'battery'],
                drive: 'disabled', navigation: 'absent',
                maps: {occupancy: false, global_costmap: false}},
    };
    const row = (id, reason) => ({id, available: false, state: 'blocked', reason, reasons: [reason]});
    window.__rosyInventoryOverride = {
      device_state: 'READY',
      descriptors: [row('mobility.move', drive), row('mobility.navigate', drive),
                    row('mobility.follow', drive), row('mobility.lead', drive),
                    row('perception.localize', 'navigation_absent')],
    };
"""

def test_no_motion_hardware_runtime_is_on_and_says_the_drive_is_off():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        try:
            browser, page = _launch_page(playwright, extra_init=NO_MOTION_INIT, real_map=True)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.goto("http://rosy.test/dashboard#compatibility", wait_until="domcontentloaded", timeout=5_000)
        page.wait_for_function(
            "document.getElementById('safety-label')?.textContent === 'NO DRIVE'"
        )
        page.wait_for_function(
            "document.getElementById('capability-count')?.textContent === '0 / 5'"
        )
        page.wait_for_timeout(300)
        # 1. the runtime is on; only the drive is off, so not "HW OFF"
        assert page.locator("#safety-source").inner_text() == "하드웨어 런타임 켜짐 · 구동 꺼짐 (무동작)"
        # 2. motion is withheld with its own reason, told once, without alarm colour
        capabilities = page.locator("#capability-list").inner_text()
        assert "구동 꺼짐 (무동작)" in capabilities
        assert "내비게이션 스택 없음" in capabilities
        assert page.locator('#capability-list [data-cause="runtime"]').count() == 5
        assert page.locator("#triage-title").inner_text() == "하드웨어 런타임 켜짐 · 구동 꺼짐 (무동작)"
        assert page.locator("#triage").get_attribute("data-category") == "observation"
        assert "내비게이션 스택 없음" in page.locator("#triage-context").inner_text()
        warm = page.evaluate(WARM_SCAN)
        assert set(warm) <= {"ui-button#emergency-stop.stop-button"}, warm
        # 3. teleop is off and says why
        assert page.locator('[data-teleop="forward"]').is_disabled()
        assert "구동 꺼짐" in page.locator("#teleop-message").inner_text()
        # 4. no map source: the real map module does not ask for one (no 404s)
        paths = [call["path"] for call in page.evaluate("window.__apiCalls")]
        assert "/api/v1/system/capabilities" in paths
        assert "/api/v1/map" not in paths
        assert "/api/v1/map/costmap" not in paths
        browser.close()

def test_map_snapshots_are_asked_for_when_the_server_has_them():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    init = NO_MOTION_INIT + """
    window.__rosyCapabilitiesOverride.runtime.maps = {occupancy: true, global_costmap: true};
    """
    with sync_playwright() as playwright:
        try:
            browser, page = _launch_page(playwright, extra_init=init, real_map=True)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.goto("http://rosy.test/dashboard#compatibility", wait_until="domcontentloaded", timeout=5_000)
        page.wait_for_function(
            "window.__apiCalls.some((call) => call.path === '/api/v1/map/costmap')"
        )
        paths = [call["path"] for call in page.evaluate("window.__apiCalls")]
        assert "/api/v1/map" in paths
        browser.close()

@pytest.mark.parametrize("viewport", [(390, 844), (1366, 768)])
def test_compatibility_map_trust_tracks_localization_and_recovers(viewport):
    from playwright.sync_api import sync_playwright, expect
    init = """
      window.__rosyMapSnapshot={width:100,height:80,resolution:0.1,origin:{x:-5,y:-4},
        data:Array(8000).fill(0),map_id:'fixture-map'};
      window.__rosyPathSnapshot={poses:[{x:1.25,y:-0.5},{x:2,y:-0.1},{x:3,y:1}],
        map_id:'fixture-map',frame_id:'map',age_s:0.5};
      const fresh={evidence:'fresh',stale_after_s:2};
      window.__rosyStateOverrides={robot_state:{mode:'NAVIGATION',navigation:'NAVIGATING',map_id:'fixture-map',
        localization:{state:'LOCALIZED',pose_frame:'map'},
        evidence:{pose:fresh,velocity:fresh,battery:fresh,safety:fresh,navigation:fresh}}};
    """
    blue_pixels = """() => {
      const canvas=document.querySelector('#map-canvas');
      const data=canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data;
      let count=0;
      for(let i=0;i<data.length;i+=4)
        if(data[i+2]>data[i+1]*1.2 && data[i+2]>data[i]*1.5 && data[i+2]>100) count++;
      return count;
    }"""
    with sync_playwright() as playwright:
        browser, page = _launch_page(playwright, extra_init=init, width=viewport[0], height=viewport[1], real_map=True)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto('http://rosy.test/dashboard#compatibility')
        page.wait_for_function("document.querySelector('#map-status')?.getAttribute('state') === 'ready'")
        page.wait_for_function("document.querySelector('[data-map-click=goal]')?.disabled === false")
        page.wait_for_function(f"() => ({blue_pixels})() > 0")
        assert page.evaluate(blue_pixels) > 0
        page.evaluate("""async () => {
          const {session}=await import('/dashboard/assets/client.js');
          const state=structuredClone(session.robotState);
          state.localization={state:'SUSPECT',pose_frame:'odom'};
          __sockets.at(-1).dispatchEvent(new MessageEvent('message',{data:JSON.stringify(state)}));
        }""")
        if output := os.environ.get("ROSY_SCREENSHOT_DIR"):
            shots = Path(output)
            shots.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(shots / f"compat-map-suspect-{viewport[0]}x{viewport[1]}.png"), full_page=True)
        expect(page.locator('[data-map-click=goal]')).to_be_disabled()
        expect(page.locator('[data-map-click=pose]')).to_be_enabled()
        assert page.locator('[data-map-click=goal]').get_attribute('reason') == '위치 추정 확인 후 가능'
        assert page.evaluate(blue_pixels) == 0
        page.evaluate("""async () => {
          const {session}=await import('/dashboard/assets/client.js');
          const state=structuredClone(session.robotState);
          state.localization={state:'LOCALIZED',pose_frame:'map'};
          __sockets.at(-1).dispatchEvent(new MessageEvent('message',{data:JSON.stringify(state)}));
        }""")
        expect(page.locator('[data-map-click=goal]')).to_be_enabled()
        page.wait_for_function(f"() => ({blue_pixels})() > 0")
        page.evaluate("""async () => {
          const {session}=await import('/dashboard/assets/client.js');
          const state=structuredClone(session.robotState);
          state.mode='SAFE_STOP';
          __sockets.at(-1).dispatchEvent(new MessageEvent('message',{data:JSON.stringify(state)}));
        }""")
        expect(page.locator('[data-map-click=goal]')).to_be_disabled()
        expect(page.locator('[data-map-click=pose]')).to_be_enabled()
        assert page.locator('[data-map-click=goal]').get_attribute('reason') == '안전 정지 중 주행 목표 불가'
        assert page.evaluate(blue_pixels) == 0
        assert errors == []
        browser.close()

def test_fault_after_configured_reason_still_raises_a_blocked_fault():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    init = NO_MOTION_INIT + """
    const faulted = (id, first) => ({id, available: false, state: 'blocked', reason: first,
                                     reasons: [first, 'device_state:FAULT']});
    window.__rosyInventoryOverride = {
      device_state: 'FAULT',
      descriptors: [faulted('mobility.move', drive), faulted('mobility.navigate', drive),
                    faulted('perception.localize', 'navigation_absent')],
    };
    """
    with sync_playwright() as playwright:
        try:
            browser, page = _launch_page(playwright, extra_init=init)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.goto("http://rosy.test/dashboard#compatibility", wait_until="domcontentloaded", timeout=5_000)
        page.wait_for_function("document.getElementById('triage')?.dataset.category === 'blocked' && document.getElementById('triage-context')?.textContent.includes('하드웨어 런타임 켜짐')")
        assert "고장" in page.locator("#triage-detail").inner_text()
        assert "하드웨어 런타임 켜짐 · 구동 꺼짐 (무동작)" in page.locator("#triage-context").text_content()
        assert "구동 꺼짐 (무동작) · 고장" in page.locator("#capability-list").inner_text()
        browser.close()

def test_api_estop_does_not_claim_a_motor_power_cut():
    """An API e-stop is a software stop; the banner must not say power was cut."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    init = CORE_ONLY_VIEWER_INIT + """
    window.__rosyStateOverrides.robot_state.safety = {estop: true};
    window.__rosySafetyOverride = {estop: true, source: 'api:operator'};
    const both = (id) => ({id, available: false, state: 'blocked', reason: 'runtime_mode:core',
                           reasons: ['runtime_mode:core', 'device_state:SAFE_STOP']});
    window.__rosyInventoryOverride = {
      device_state: 'SAFE_STOP',
      descriptors: ['mobility.move', 'mobility.navigate', 'mobility.follow',
                    'mobility.lead', 'perception.localize'].map(both),
    };
    """
    with sync_playwright() as playwright:
        try:
            browser, page = _launch_page(playwright, extra_init=init)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.goto("http://rosy.test/dashboard#compatibility", wait_until="domcontentloaded", timeout=5_000)
        page.wait_for_function(
            "document.getElementById('triage-title')?.textContent === 'API 비상정지 (operator)'"
        )
        banner = page.locator("#triage").inner_text()
        assert "모터 전원이 끊겼" not in banner
        assert "현장에서 해제" not in banner
        assert "소프트웨어 정지" in page.locator("#triage-detail").inner_text()
        assert page.locator("#safety-label").inner_text() == "STOPPED"
        assert page.locator("#safety-source").inner_text() == "API 비상정지 (operator)"
        # The runtime reason comes first and SAFE_STOP is still shown.
        capabilities = page.locator("#capability-list").inner_text()
        assert "하드웨어 런타임 꺼짐 · 정지 상태" in capabilities
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
            "http://rosy.test/dashboard#compatibility",
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

@pytest.mark.parametrize("viewport", [(390, 844), (1366, 768)])
def test_navigation_teleop_disabled_reasons_fit_the_action_column(viewport):
    from playwright.sync_api import sync_playwright
    init = """window.__rosyStateOverrides={robot_state:{mode:'NAVIGATION'}};"""
    with sync_playwright() as playwright:
        browser, page = _launch_page(playwright, extra_init=init, width=viewport[0], height=viewport[1])
        page.goto("http://rosy.test/dashboard#compatibility")
        page.wait_for_function("document.querySelector('#robot-mode')?.textContent === '내비게이션'")
        page.wait_for_function("document.querySelector('.teleop-pad ui-button')?.hasAttribute('reason')")
        if output := os.environ.get("ROSY_SCREENSHOT_DIR"):
            shots = Path(output)
            shots.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(shots / f"navigation-teleop-{viewport[0]}x{viewport[1]}.png"), full_page=True)
        sizes = page.evaluate("""() => {
          const act=document.querySelector('.region-act');
          const pad=document.querySelector('.teleop-pad');
          return {act:[act.clientWidth,act.scrollWidth,act.clientHeight,act.scrollHeight],pad:[pad.clientWidth,pad.scrollWidth],
            reasons:[...pad.querySelectorAll('ui-button')].map(button => button.querySelector('small[data-reason]')?.textContent)};
        }""")
        browser.close()
    assert len(sizes["reasons"]) == 4 and all(sizes["reasons"]), sizes
    assert sizes["act"][1] <= sizes["act"][0] + 1, sizes
    if viewport[0] >= 1024:
        assert sizes["act"][3] <= sizes["act"][2] + 1, sizes
    assert sizes["pad"][1] <= sizes["pad"][0] + 1, sizes

def test_wide_but_short_operate_view_keeps_three_columns():
    """D-359 US-008: at 1366x600 (height < 40rem) the frame lets go and the page scrolls, but the
    three regions stay side by side — the columns follow width only."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser, page = _launch_page(playwright, width=1366, height=600)
        page.goto("http://rosy.test/dashboard#compatibility", wait_until="domcontentloaded", timeout=5_000)
        page.wait_for_function("document.getElementById('robot-mode')?.textContent !== undefined")
        page.wait_for_timeout(700)
        probe = page.evaluate("""() => {
          const rect = (s) => document.querySelector(s).getBoundingClientRect().toJSON();
          const stop = document.getElementById('emergency-stop').getBoundingClientRect();
          return {overflow: document.documentElement.scrollWidth - innerWidth,
                  sense: rect('.region-sense'), observe: rect('.region-observe'), act: rect('.region-act'),
                  estop: stop.top >= 0 && stop.bottom <= innerHeight && stop.right <= innerWidth};
        }""")
        browser.close()
    assert probe["overflow"] <= 0, probe
    assert probe["sense"]["right"] <= probe["observe"]["x"] + 1, probe
    assert probe["observe"]["right"] <= probe["act"]["x"] + 1, probe
    assert probe["sense"]["y"] == probe["observe"]["y"] == probe["act"]["y"], probe
    assert probe["estop"], probe

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
            "http://rosy.test/dashboard#compatibility",
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
            "http://rosy.test/dashboard#compatibility",
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
            "http://rosy.test/dashboard#compatibility",
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
    page.goto("http://rosy.test/dashboard#compatibility", wait_until="domcontentloaded", timeout=5_000)
    page.wait_for_selector('#compatibility-shell[data-ready="true"]')
    return browser, page

def _storage(page):
    return page.evaluate(
        "({session: sessionStorage.getItem('rosy.dashboard.token'),"
        " local: localStorage.getItem('rosy.dashboard.paired')})"
    )

def test_legacy_dashboard_refresh_and_back_keep_the_tab_token():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        try:
            browser, page = _open_dashboard(playwright)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        assert page.evaluate("sessionStorage.getItem('rosy.dashboard.token')") == "operator-test-token"
        page.goto("http://rosy.test/dashboard", wait_until="domcontentloaded", timeout=5_000)
        page.reload(wait_until="domcontentloaded", timeout=5_000)
        page.go_back(wait_until="domcontentloaded", timeout=5_000)
        assert page.url == "http://rosy.test/dashboard?view=compatibility#compatibility"
        assert page.evaluate("sessionStorage.getItem('rosy.dashboard.token')") == "operator-test-token"
        browser.close()

def test_legacy_dashboard_skip_link_keeps_owner_after_fragment_and_refresh():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser, page = _open_dashboard(playwright)
        try:
            page.keyboard.press("Tab")
            assert page.locator(":focus").get_attribute("href") == "#dashboard-main"
            page.keyboard.press("Enter")
            assert page.locator(":focus").get_attribute("id") == "dashboard-main"
            assert page.url.endswith("?view=compatibility#dashboard-main")
            assert page.locator("#compatibility-shell").is_visible()
            page.reload(wait_until="domcontentloaded")
            page.wait_for_selector('#compatibility-shell[data-ready="true"]')
            assert page.locator("#compatibility-shell").is_visible()
            assert page.locator("#entry-shell").is_hidden()
        finally:
            browser.close()

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
        page.wait_for_function("() => window.__apiCalls.some(call => call.path === '/api/v1/auth/connection')")
        assert _storage(page) == {"session": None, "local": None}
        assert "open" in page.locator("#auth-drawer").get_attribute("class")
        assert page.evaluate("window.__apiCalls.map(({method,path})=>({method,path}))") == [
            {"method": "GET", "path": "/api/account/session"}, {"method": "GET", "path": "/api/v1/auth/connection"}]
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

# --- D-247: the inspect view's device card and the operate view's motion reason ---

#: rosy_18 as checked by hand on 2026-09-25, one row per state.
HARDWARE_INIT = """
    window.__rosyHardware = {
      available: true, schema: 1, measured_at: new Date(Date.now() - 42000).toISOString(),
      age_s: 42, stale: false, boot_id: 'b', detail: '',
      devices: [
        {id: 'motor.1', label: '구동 모터 1 (XL330)', bus: 'UART4 /dev/rosy-motor', state: 'ok',
         evidence: 'odom 수신 중 (토픽 판정)', product: true, held_by: 'rosy-io.service', source: 'topic'},
        {id: 'imu', label: 'IMU (BNO055)', bus: 'I2C0 /dev/i2c-0 0x28', state: 'bus_missing',
         evidence: '/dev/i2c-0 없음', product: false},
        {id: 'adc.battery', label: '배터리 전압 (ADC)', bus: 'I2C1 /dev/i2c-1 0x08', state: 'no_response',
         evidence: 'ETIMEDOUT — 로봇 전원을 완전히 껐다 켜세요', product: true},
        {id: 'lamp', label: 'LED 램프 (WS2812)', bus: 'GPIO BCM 19 PWM', state: 'driver_missing',
         evidence: '/dev/ws281x_pwm 없음', product: false},
        {id: 'buzzer', label: '부저', bus: 'GPIO (ROSY_BUZZER_PIN, 기본 BCM 4)', state: 'needs_human',
         evidence: 'BCM 4 · 꺼짐 (ROSY_BUZZER_ENABLED=false) · 소리는 사람이 확인', product: false},
        {id: 'lidar', label: 'LiDAR (RPLIDAR C1)', bus: 'UART0 /dev/ttyAMA0', state: 'not_measured',
         evidence: 'rosy-io 사용 중 — 토픽으로 판정', product: true, held_by: 'rosy-io.service'},
      ],
    };
"""

def test_inspect_view_lists_every_device_with_its_state_and_bench_tag():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        try:
            browser, page = _launch_page(playwright, extra_init=HARDWARE_INIT, width=1366, height=768)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.goto("http://rosy.test/dashboard#compatibility", wait_until="domcontentloaded", timeout=5_000)
        page.locator("#view-inspect").click()
        page.wait_for_function("document.querySelectorAll('#hardware-list .device-row').length === 6")
        rows = page.evaluate(
            "[...document.querySelectorAll('#hardware-list .device-row')].map((row) => ({"
            " id: row.dataset.device,"
            " chip: row.querySelector('.device-state').textContent,"
            " status: row.querySelector('.device-state').dataset.status || null,"
            " bench: Boolean([...row.querySelectorAll('.device-name ui-tag')]"
            "   .find((tag) => tag.textContent === '벤치 전용')),"
            " bus: getComputedStyle(row.querySelector('.device-bus')).fontFamily,"
            " hangul: row.querySelector('.device-bus').hasAttribute('data-hangul') }))"
        )
        assert [(row["id"], row["chip"], row["status"], row["bench"]) for row in rows] == [
            ("motor.1", "정상", "OK", False),
            ("imu", "버스 없음", "WARNING", True),
            ("adc.battery", "응답 없음", "ERROR", False),
            ("lamp", "드라이버 없음", "WARNING", True),
            ("buzzer", "사람 확인 필요", None, True),
            ("lidar", "측정 안 함", None, False),
        ]
        # D-359 US-008: a bus string carrying Hangul (the buzzer's) is drawn in the body family,
        # because mono fonts have no Hangul; every other bus stays mono.
        assert [row["id"] for row in rows if row["hangul"]] == ["buzzer"], rows
        assert all("mono" in row["bus"].lower() or "consol" in row["bus"].lower()
                   for row in rows if not row["hangul"]), rows
        assert page.locator("#hardware-card").get_attribute("data-available") == "true"
        assert page.locator("#hardware-measured").inner_text().endswith("42초 전")
        assert "전원을 완전히 껐다 켜세요" in page.locator("#hardware-list").inner_text()
        # The populated card keeps the closed type scale and the contrast floor.
        page.evaluate(f"window.STEPS = {TYPE_STEPS}")
        assert page.evaluate(OFF_SCALE_CENSUS) == []
        assert page.evaluate(TEXT_FLOOR_CENSUS) == []
        # An administrator can ask for a new run; it goes to the refresh route only.
        refresh = page.locator("#hardware-refresh")
        assert refresh.is_enabled()
        refresh.click()
        page.wait_for_function(
            "window.__apiCalls.some((call) => call.method === 'POST'"
            " && call.path === '/api/v1/host/hardware/refresh')"
        )
        page.wait_for_function(
            "document.getElementById('hardware-note')?.textContent === '장치 점검을 요청했습니다.'")
        browser.close()

def test_a_viewer_sees_the_device_card_but_cannot_rerun_the_probe():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        try:
            browser, page = _launch_page(playwright, extra_init=CORE_ONLY_VIEWER_INIT + HARDWARE_INIT)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.goto("http://rosy.test/dashboard#compatibility", wait_until="domcontentloaded", timeout=5_000)
        page.locator("#view-inspect").click()
        page.wait_for_function("document.querySelectorAll('#hardware-list .device-row').length === 6")
        assert page.locator("#hardware-refresh").is_disabled()
        browser.close()

def test_no_probe_result_yet_is_said_not_blanked():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        try:
            browser, page = _launch_page(playwright)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.goto("http://rosy.test/dashboard#compatibility", wait_until="domcontentloaded", timeout=5_000)
        page.locator("#view-inspect").click()
        page.wait_for_function(
            "document.getElementById('hardware-card')?.dataset.available === 'false'")
        assert page.locator("#hardware-note").inner_text() == "장치 점검 결과가 아직 없습니다"
        assert page.locator("#hardware-list .device-row").count() == 0
        browser.close()

def test_an_administrator_tests_the_buzzer_and_records_what_was_heard():
    """D-247 6: 울려 보기 -> 들림 goes to the two admin routes and turns the row to 정상."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        try:
            browser, page = _launch_page(playwright, extra_init=HARDWARE_INIT, width=1366, height=768)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.goto("http://rosy.test/dashboard#compatibility", wait_until="domcontentloaded", timeout=5_000)
        page.locator("#view-inspect").click()
        page.wait_for_function("document.querySelectorAll('#hardware-list .device-row').length === 6")
        # Only the buzzer and the lamp have a test, and the lamp without a driver cannot start one.
        # D-359 §5.3: the disabled reason is a <small data-reason> inside the button, so the label
        # is read without it and the reason is checked on its own.
        actions = page.evaluate(
            "[...document.querySelectorAll('#hardware-list .device-actions')].map((box) => ({"
            " device: box.closest('.device-row').dataset.device,"
            " buttons: [...box.querySelectorAll('ui-button')].map((b) => {"
            "   const label = [...b.childNodes].filter((n) => !n.matches?.('small[data-reason]'))"
            "     .map((n) => n.textContent).join('');"
            "   return [label, b.disabled, b.getAttribute('reason')]; }) }))"
        )
        assert actions == [{"device": "lamp", "buttons": [["켜 보기", True, "드라이버 없음"]]},
                           {"device": "buzzer", "buttons": [["울려 보기", False, None]]}]
        page.locator("#hardware-list [data-device='buzzer'] [data-hw-action='test']").click()
        page.wait_for_function(
            "window.__apiCalls.some((call) => call.method === 'POST'"
            " && call.path === '/api/v1/host/hardware/test' && call.body?.device === 'buzzer')")
        heard = page.locator("#hardware-list [data-device='buzzer'] [data-hw-action='observed']")
        heard.wait_for(timeout=10_000)
        assert heard.inner_text() == "들림"
        assert page.locator("#hardware-list [data-device='buzzer'] [data-hw-action='not-observed']") \
            .inner_text() == "안 들림"
        assert page.locator("#hardware-list [data-device='buzzer'] .device-test").inner_text() == \
            "BCM 4 · 2 kHz · duty 10 % · 3×150 ms"
        # The lamp row shows no buzzer outcome.
        assert page.locator("#hardware-list [data-device='lamp'] .device-test").count() == 0
        heard.click()
        page.wait_for_function(
            "window.__apiCalls.some((call) => call.method === 'POST'"
            " && call.path === '/api/v1/host/hardware/confirm'"
            " && call.body?.device === 'buzzer' && call.body?.observed === true)")
        page.wait_for_function(
            "document.querySelector(\"#hardware-list [data-device='buzzer'] .device-state\")"
            "?.textContent === '정상'")
        assert page.locator("#hardware-list [data-device='buzzer'] .device-evidence").inner_text() \
            .startswith("사람 확인: ")
        # No HTML is built from server text anywhere in the card.
        assert page.evaluate("document.querySelectorAll('#hardware-list script, #hardware-list img').length") == 0
        page.evaluate(f"window.STEPS = {TYPE_STEPS}")
        assert page.evaluate(OFF_SCALE_CENSUS) == []
        assert page.evaluate(TEXT_FLOOR_CENSUS) == []
        browser.close()

def test_a_viewer_gets_no_buzzer_or_lamp_test():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        try:
            browser, page = _launch_page(playwright, extra_init=CORE_ONLY_VIEWER_INIT + HARDWARE_INIT)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.goto("http://rosy.test/dashboard#compatibility", wait_until="domcontentloaded", timeout=5_000)
        page.locator("#view-inspect").click()
        page.wait_for_function("document.querySelectorAll('#hardware-list .device-row').length === 6")
        assert page.locator("#hardware-list .device-actions").count() == 0
        assert page.locator("#hardware-list [data-hw-action]").count() == 0
        browser.close()

@pytest.mark.parametrize("viewport", FIT_VIEWPORTS)
def test_the_test_buttons_keep_the_inspect_view_inside_the_screen_width(viewport):
    """D-201: the admin action rows wrap inside the card; nothing scrolls sideways."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    outcome = HARDWARE_INIT + (
        "window.__rosyHardware.test = {request_id: '00112233445566778899aabb', action: 'buzzer',"
        " state: 'done', detail: 'BCM 4 · 2 kHz · duty 10 % · 3×150 ms',"
        " finished_at: new Date().toISOString()};"
    )
    with sync_playwright() as playwright:
        try:
            browser, page = _launch_page(playwright, extra_init=outcome, width=viewport[0], height=viewport[1])
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.goto("http://rosy.test/dashboard#compatibility", wait_until="domcontentloaded", timeout=5_000)
        page.locator("#view-inspect").click()
        page.wait_for_function(
            "document.querySelectorAll(\"#hardware-list [data-hw-action='observed']\").length === 1")
        fit = page.evaluate(
            "(() => { const card = document.getElementById('hardware-card').getBoundingClientRect();"
            " const boxes = [...document.querySelectorAll('#hardware-list .device-actions > *')]"
            "   .map((node) => node.getBoundingClientRect());"
            " return { page: document.documentElement.scrollWidth - document.documentElement.clientWidth,"
            "  outside: boxes.filter((box) => box.left < card.left - 1 || box.right > card.right + 1).length };"
            "})()")
        assert fit == {"page": 0, "outside": 0}, f"{viewport}: {fit}"
        browser.close()

MOTION_REASON = "모터가 꺼진 CORE 전용 모드입니다. 관리자가 모터 모드로 올려야 움직입니다."

@pytest.mark.parametrize("viewport", FIT_VIEWPORTS)
def test_core_only_operate_view_says_why_it_cannot_move_and_still_fits(viewport):
    """D-247 7 + D-201: the reason replaces the vague profile line without scrolling the console."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    reason = CORE_ONLY_VIEWER_INIT + (
        "window.__rosyCommissioningOverride = {runtime_mode: 'core', motor_hold: true,"
        f" motion_reason: '{MOTION_REASON}'}};"
    )
    fits = {}
    with sync_playwright() as playwright:
        for label, init in (("before", CORE_ONLY_VIEWER_INIT), ("reason", reason)):
            try:
                browser, page = _launch_page(playwright, extra_init=init, width=viewport[0], height=viewport[1])
            except Exception as error:
                pytest.skip(f"Playwright Chromium unavailable: {error}")
            page.goto("http://rosy.test/dashboard#compatibility", wait_until="domcontentloaded", timeout=5_000)
            page.wait_for_function(
                "document.getElementById('capability-count')?.textContent === '0 / 5'")
            if label == "reason":
                page.wait_for_function(
                    f"document.getElementById('teleop-message')?.textContent === '{MOTION_REASON}'")
                assert "권한" not in page.locator("#teleop-message").inner_text()
            page.wait_for_timeout(300)
            fits[label] = page.evaluate(FIT_PROBE)
            browser.close()
    fit = fits["reason"]
    assert fit["docOverflow"] <= 0, f"{viewport}: 이유 문장이 운용 뷰를 스크롤시킨다(D-201): {fits}"
    assert fit["estopInside"], fits
    # The CORE-only viewer state already overflows the act column by a few px at
    # 1366x768 with the old sentence (2026-09-25, feed2fc7); the reason must not add to it.
    assert fit["actOverflow"] <= max(1, fits["before"]["actOverflow"]), (
        f"{viewport}: 이유 문장이 조작 열을 더 넘치게 한다(D-201): {fits}")

def test_map_keyboard_crosshair_posts_a_goal_with_the_same_confirm():
    """D-259 — 지도 클릭 목표의 키보드 길. 진짜 map.js로 탄다(픽스처 스텁이 아님)."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        try:
            browser, page = _launch_page(playwright, width=1366, height=768, real_map=True, extra_init="""
              window.__rosyMapSnapshot={width:10,height:10,resolution:1,origin:{x:-5,y:-5},
                data:Array(100).fill(0),map_id:'fixture-map'};
            """)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto("http://rosy.test/dashboard#compatibility", wait_until="domcontentloaded",
                  timeout=5_000)
        page.wait_for_function(
            "document.getElementById('robot-mode')?.textContent === '수동'")
        page.wait_for_function("document.querySelector('#map-status')?.getAttribute('state') === 'ready'")
        canvas = page.locator("#map-canvas")
        assert canvas.get_attribute("tabindex") == "0"
        canvas.focus()
        canvas.press("ArrowRight")
        canvas.press("ArrowDown")
        page.click('[data-map-click="goal"]')
        canvas.focus()
        canvas.press("Enter")
        page.locator("dialog.ui-confirm ui-button[kind=irreversible]").click()
        page.wait_for_function(
            "() => window.__apiCalls.some((call) => call.path === "
            "'/api/v1/navigation/goal' && call.method === 'POST')",
            timeout=8000,
        )
        canvas.press("Escape")
        assert not errors, f"페이지 오류: {errors}"
        browser.close()

# --- D-260 5: the operate view's summary line ------------------------------------

STATUS_SUMMARY_INIT = """
    window.__rosyStatusSummary = {
      state: 'caution', label: '주의', reason: '배터리 전압 (ADC) 응답 없음',
      state_line: '주의: 배터리 전압 (ADC) 응답 없음',
      motion_reason: '모터가 꺼진 CORE 전용 모드입니다. 관리자가 모터 모드로 올려야 움직입니다.',
      runtime_mode: 'core', boot: {available: true, stage: 'CORE_READY'},
      devices: {available: true, stale: false, ok: 12, total: 14, problems: [
        {id: 'adc.battery', label: '배터리 전압 (ADC)', state: 'no_response', product: true},
        {id: 'imu', label: 'IMU (BNO055)', state: 'bus_missing', product: false}]},
      battery: {percent: 81.4, voltage: 7.93, warning_percent: 20, low: false},
      temperature_c: 51.2,
      todos: [
        {id: 'adc_power_cycle', text: '로봇 전원을 완전히 껐다 켜세요 (ADC)', device: 'adc.battery'},
        {id: 'promote_motor', text: '관리자가 모터 모드로 승격'},
        {id: 'human_test', text: '<img src=x onerror=alert(1)>부저: 시험 동작으로 확인', device: 'buzzer'}],
    };
"""

SUMMARY_PROBE = """() => {
  const box = (id) => document.getElementById(id).getBoundingClientRect();
  const summary = box('status-summary');
  return {
    page: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    inside: ['summary-state', 'summary-devices', 'summary-power', 'summary-todo-toggle'].every((id) => {
      const r = box(id);
      return r.width > 0 && r.left >= summary.left - 1 && r.right <= summary.right + 1
        && r.bottom <= window.innerHeight;
    }),
    height: Math.round(summary.height),
  };
}"""

def _summary_page(playwright, extra_init, width=1366, height=768):
    browser, page = _launch_page(playwright, extra_init=extra_init, width=width, height=height)
    page.goto("http://rosy.test/dashboard#compatibility", wait_until="domcontentloaded", timeout=5_000)
    page.wait_for_function("document.getElementById('status-summary')?.dataset.state !== 'unknown'")
    return browser, page

def test_the_summary_line_says_state_devices_power_and_todos():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        try:
            browser, page = _summary_page(playwright, STATUS_SUMMARY_INIT)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        assert page.locator("#summary-state").inner_text() == "주의"
        assert page.locator("#summary-state").get_attribute("data-state") == "caution"
        assert page.locator("#summary-reason").inner_text() == "배터리 전압 (ADC) 응답 없음"
        assert page.locator("#summary-devices").inner_text() == "정상 12/14 · 배터리 전압 (ADC) 응답 없음"
        assert page.locator("#summary-power").inner_text() == "81 % · 7.93 V · 51 °C"
        toggle = page.locator("#summary-todo-toggle")
        assert toggle.inner_text() == "할 일 3" and toggle.get_attribute("aria-expanded") == "false"
        assert page.locator("#summary-todos").is_hidden()
        toggle.click()
        assert toggle.get_attribute("aria-expanded") == "true"
        items = page.locator("#summary-todos li").all_inner_texts()
        assert items[:2] == ["로봇 전원을 완전히 껐다 켜세요 (ADC)", "관리자가 모터 모드로 승격"]
        # Server text is text: the list builds no element from it.
        assert items[2].startswith("<img") and page.locator("#summary-todos img").count() == 0
        # The open list overlays the console; nothing scrolls.
        fit = page.evaluate(FIT_PROBE)
        assert fit["docOverflow"] <= 0 and fit["actOverflow"] <= 1, fit
        page.keyboard.press("Escape")
        assert page.locator("#summary-todos").is_hidden()
        # The line keeps the closed type scale and the contrast floor.
        page.evaluate(f"window.STEPS = {TYPE_STEPS}")
        assert page.evaluate(OFF_SCALE_CENSUS) == []
        assert page.evaluate(TEXT_FLOOR_CENSUS) == []
        # It is refreshed with the other slow data, as a viewer route.
        assert any(call["path"] == "/api/v1/host/status-summary" and call["method"] == "GET"
                   for call in page.evaluate("window.__apiCalls"))
        browser.close()

def test_the_device_summary_opens_the_device_card_at_the_first_problem():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        try:
            browser, page = _summary_page(playwright, STATUS_SUMMARY_INIT + HARDWARE_INIT)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.wait_for_function("document.querySelectorAll('#hardware-list .device-row').length === 6")
        page.locator("#summary-devices").click()
        page.wait_for_function("document.body.dataset.view === 'inspect'")
        assert page.locator("#view-inspect-panel").is_visible()
        assert page.evaluate("document.activeElement?.dataset.device") == "adc.battery"
        browser.close()

@pytest.mark.parametrize("payload,chip", [
    ("{state: 'failed', label: '실패', reason: 'rosy-core', todos: [{id: 'failed_unit',"
     " text: '실패한 부팅 단계를 확인하세요 (rosy-core)'}], devices: {available: false}, battery: {}}", "실패"),
    ("{state: 'ready', label: '준비됨', reason: '', todos: [], devices: {available: true, ok: 14,"
     " total: 14, problems: []}, battery: {percent: 90, voltage: 8.1, low: false}, temperature_c: 48}", "준비됨"),
])
def test_failed_and_ready_render_without_a_list_to_open(payload, chip):
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        try:
            browser, page = _summary_page(playwright, f"window.__rosyStatusSummary = {payload};")
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        assert page.locator("#summary-state").inner_text() == chip
        if chip == "준비됨":
            assert page.locator("#summary-devices").inner_text() == "정상 14/14"
            assert page.locator("#summary-todo-toggle").inner_text() == "할 일 0"
            assert page.locator("#summary-todo-toggle").is_disabled()
            # D-82: a ready robot shows nothing warm on the summary line.
            warm = page.evaluate(WARM_SCAN)
            assert not [hit for hit in warm if "summary" in hit], warm
        else:
            assert page.locator("#summary-devices").inner_text() == "장치 점검 전"
            assert page.locator("#summary-power").inner_text() == "— % · — °C"
        browser.close()

@pytest.mark.parametrize("viewport", FIT_VIEWPORTS)
def test_a_held_robot_s_long_reason_keeps_the_console_inside_the_screen(viewport):
    """D-201: the held reason is the longest sentence; it is cut, never wraps or scrolls."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    held = STATUS_SUMMARY_INIT + (
        "Object.assign(window.__rosyStatusSummary, {state: 'ready_held', label: '준비됨 — 못 움직임',"
        " reason: 'CORE 전용 모드'});"
    )
    with sync_playwright() as playwright:
        try:
            browser, page = _summary_page(playwright, held + CONSOLE_STATE_INIT["safe-stop"],
                                          width=viewport[0], height=viewport[1])
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        assert page.locator("#summary-state").inner_text() == "준비됨 — 못 움직임"
        # Held: the reason is D-247 7's sentence, whole in the title when it is cut.
        assert page.locator("#summary-reason").get_attribute("title").startswith("모터가 꺼진 CORE 전용 모드")
        page.wait_for_timeout(300)
        fit = page.evaluate(FIT_PROBE)
        line = page.evaluate(SUMMARY_PROBE)
        browser.close()
    assert fit["docOverflow"] <= 0 and fit["actOverflow"] <= 1 and fit["estopInside"], f"{viewport}: {fit}"
    assert line["page"] == 0 and line["inside"], f"{viewport}: {line}"

BRIDGE_INIT = """
(() => {
  const native = window.fetch.bind(window);
  window.fetch = async (input, options = {}) => {
    const path = new URL(typeof input === 'string' ? input : input.url, location.href).pathname;
    if (path === '/api/v1/ui/surfaces/console') {
      const surfaces = (window.__callerRole === 'viewer')
        ? [{id: 'console', title: '운용'}]
        : [{id: 'console', title: '운용'}, {id: 'setup', title: '작업 준비'}, {id: 'device', title: '설치·정비'}];
      return new Response(JSON.stringify({surface: 'console', role: window.__callerRole || 'administrator',
        revision: 'bridge-test', panels: [], surfaces}), {
        status: 200, headers: {'Content-Type': 'application/json'}});
    }
    return native(input, options);
  };
})()
"""

@pytest.mark.parametrize("role, expected", [
    ("administrator", ["/console", "/setup", "/device"]),
    ("viewer", ["/console"]),
])
def test_the_home_bridge_offers_the_caller_role_surfaces(role, expected):
    # 비평 P1: /dashboard는 브리지다 — 목적지는 매니페스트 surfaces가 말하고
    # 서버가 역할로 걸러 준다. 클라이언트는 그릴 뿐이다.
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        try:
            browser, page = _launch_page(
                playwright, extra_init=BRIDGE_INIT + f"window.__callerRole = {role!r};")
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.route("http://rosy.test/console", lambda route: route.fulfill(
            status=200, content_type="text/html",
            body="<!doctype html><html lang=ko><body data-console=1></body></html>"))
        page.goto("http://rosy.test/dashboard#compatibility", wait_until="domcontentloaded", timeout=5000)
        page.wait_for_function(
            "() => document.querySelectorAll('#surface-bridge a').length === " + str(len(expected)))
        drawn = page.evaluate(
            "() => [...document.querySelectorAll('#surface-bridge a')].map((a) => a.getAttribute('href'))")
        assert page.locator("#surface-bridge").get_attribute("aria-label") == "역할 화면"
        page.click("#surface-bridge a[href='/console']")
        page.wait_for_function("() => document.body.dataset.console === '1'")
        browser.close()
    assert drawn == expected
