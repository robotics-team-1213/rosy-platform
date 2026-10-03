"""LOCAL G2 capture of the role procedure screens through FastAPI and Chromium."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import yaml
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[4]
SRC = ROOT / "src"
for package in ("runtime/api_web", "runtime/gateway", "runtime/events", "runtime/services", "contracts/foundation"):
    sys.path.insert(0, str(SRC / package))

pytestmark = pytest.mark.skipif(
    os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
    reason="set ROSY_RUN_BROWSER_TESTS=1 for LOCAL Chromium G2 capture",
)

TOKENS = {"operator": "rosy-dev-operator", "administrator": "rosy-dev-admin"}
CAPTURES = Path("X:/DevTemp/rosy-uiux-d306-roles-g2")
SCENARIOS = {
    "setup": ("normal", "empty", "delayed", "disconnected", "unavailable", "unsupported", "forbidden", "error", "safe_stop", "confirm_cancel"),
    "device": ("normal", "empty", "delayed", "disconnected", "unavailable", "forbidden", "error", "safe_stop", "confirm_cancel"),
}


def _core_client(tmp_path):
    from fastapi.testclient import TestClient
    from core_api_web.api.app import create_app
    from core_common.profile import RobotProfile, robot_config_dir
    from core.services import CoreServices

    config_dir = SRC / "contracts/foundation/config"
    config = yaml.safe_load((config_dir / "rosy_default.yaml").read_text(encoding="utf-8"))
    config["auth"] = {**config["auth"], **yaml.safe_load(
        (config_dir / "rosy_dev_auth.yaml").read_text(encoding="utf-8"))["auth"]}
    robot_dir = robot_config_dir("pinky_pro")
    profile = RobotProfile.load(robot_dir / "profile.yaml")
    capabilities = yaml.safe_load((robot_dir / "capabilities.yaml").read_text(encoding="utf-8"))
    services = CoreServices.build(config, profile, capabilities, tmp_path / "docks.json")
    return TestClient(create_app(config, services))


def _response(client, path, token, scenario, surface):
    from fastapi import Response

    response = client.get(path, headers={"Authorization": f"Bearer {token}"})
    if path == "/api/v1/robot/state" and response.status_code == 200:
        state = response.json()
        if scenario in {"delayed", "disconnected", "unavailable"}:
            state.setdefault("evidence", {})["pose"] = {
                "evidence": scenario,
                "received_at": (datetime.now(timezone.utc) - timedelta(seconds=22)).isoformat(),
            }
            state["pose"] = {"x": 1.2, "y": 0.3, "yaw": 0}
        else:
            state.setdefault("evidence", {})["pose"] = {"evidence": "fresh", "received_at": datetime.now(timezone.utc).isoformat()}
            state["pose"] = {"x": 1.2, "y": 0.3, "yaw": 0}
            if scenario == "safe_stop":
                state["mode"] = "SAFE_STOP"
        response = Response(content=json.dumps(state), media_type="application/json")
    elif scenario in {"normal", "empty", "confirm_cancel"} and surface == "setup" and path == "/api/v1/system/capabilities":
        data = response.json()
        data["navigation"] = {"goal_navigation": True}
        data["slam"] = True
        response = Response(content=json.dumps(data), media_type="application/json")
    elif scenario == "unsupported" and path == "/api/v1/system/capabilities":
        data = response.json()
        data["navigation"] = {"goal_navigation": False, "reason": "fixture: navigation 미제공"}
        data["slam"] = False
        data["slam_reason"] = "fixture: SLAM 미제공"
        response = Response(content=json.dumps(data), media_type="application/json")
    elif scenario == "empty" and path in {"/api/v1/waypoints", "/api/v1/docking/docks", "/api/v1/docking/types", "/api/v1/system/tokens"}:
        key = {"/api/v1/waypoints": "waypoints", "/api/v1/docking/docks": "docks",
               "/api/v1/docking/types": "types", "/api/v1/system/tokens": "tokens"}[path]
        response = Response(content=json.dumps({key: []}), media_type="application/json")
    elif scenario in {"forbidden", "error"} and path in {
        "/api/v1/waypoints", "/api/v1/host/network", "/api/v1/host/release",
    }:
        code = 403 if scenario == "forbidden" else 503
        response = Response(content=json.dumps({"error": {"code": "FORBIDDEN" if code == 403 else "UNAVAILABLE",
                                                         "message": "fixture: 권한 거부" if code == 403 else "fixture: 연결 오류"}}),
                            status_code=code, media_type="application/json")
    elif scenario in {"normal", "delayed", "disconnected", "unavailable", "confirm_cancel"} and surface == "device" and path in {
        "/api/v1/host/network", "/api/v1/host/release",
    }:
        data = {"mode": "SITE_STA", "ssid": "site-fixture"} if path.endswith("network") else {
            "state": "IDLE", "current": "r2", "previous": "r1"}
        observed_at = (datetime.now(timezone.utc) - timedelta(seconds=22 if scenario == "delayed" else 0)).isoformat()
        evidence_state = scenario if scenario in {"delayed", "disconnected", "unavailable"} else "fresh"
        response = Response(content=json.dumps({
            "available": scenario != "disconnected", "ok": scenario not in {"disconnected", "unavailable"},
            "code": "HOST_AGENT_TIMEOUT" if scenario == "disconnected" else "OK",
            "data": data if evidence_state in {"fresh", "delayed"} else None,
            "evidence": {"evidence": evidence_state,
                         "observed_at": observed_at if evidence_state in {"fresh", "delayed"} else None,
                         "age_s": 22 if evidence_state == "delayed" else 0 if evidence_state == "fresh" else None,
                         "stale_after_s": 15, "reason": "fixture: Host Agent 원본 조회"},
        }), media_type="application/json")
    return response


def test_role_procedure_g2_local_matrix(tmp_path):
    client = _core_client(tmp_path)
    CAPTURES.mkdir(parents=True, exist_ok=True)
    records = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for role, surface in (("operator", "setup"), ("administrator", "setup"),
                              ("administrator", "device"), ("operator", "device")):
            scenarios = ("forbidden",) if (role, surface) == ("operator", "device") else SCENARIOS[surface]
            for scenario in scenarios:
                for width, height in ((1366, 768), (390, 844)):
                    context = browser.new_context(viewport={"width": width, "height": height})
                    page = context.new_page()
                    errors = []
                    posts = []
                    dialogs = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    token = TOKENS[role]
                    page.add_init_script(f"sessionStorage.setItem('rosy.dashboard.token', {token!r})")

                    def serve(route):
                        request = route.request
                        path = urlsplit(request.url).path
                        if request.method != "GET":
                            posts.append({"path": path, "method": request.method})
                            route.fulfill(status=501, content_type="application/json", body='{"detail":"fixture blocks writes"}')
                            return
                        response = _response(client, path, token, scenario, surface)
                        route.fulfill(status=response.status_code, headers={
                            "content-type": response.headers.get("content-type", "application/octet-stream"),
                            "cache-control": "no-store",
                        }, body=response.content if hasattr(response, "content") else response.body)

                    page.route("**/*", serve)
                    page.goto(f"http://rosy.test/{surface}", wait_until="domcontentloaded")
                    if role == "operator" and surface == "device":
                        page.wait_for_function("document.querySelector('#surface-status')?.textContent.includes('역할')")
                    else:
                        # 첫 패널이 아니라 조립 완료를 기다린다 — showStatus("")는
                        # 모든 패널 마운트 뒤에만 불린다. 조립 중 캡처는 빈 카드와
                        # 로딩 문구를 남겨 G2 셀을 불성실하게 만든다(D-153.3).
                        page.wait_for_function("""() => {
                          const status = document.querySelector('#surface-status');
                          if (!status) return false;
                          if (status.hidden) return true;
                          const text = (status.textContent || '').trim();
                          return text !== '' && text !== '화면을 불러오는 중입니다.';
                        }""")
                    page.wait_for_timeout(500)
                    if scenario == "safe_stop":
                        page.wait_for_function("document.querySelector('#safety-mode-status')?.textContent.includes('안전 정지')")
                        assert page.locator("#safety-mode-status").is_visible()
                        assert "물리 상태는 별도로" in page.locator("#safety-mode-status").inner_text()
                    if scenario == "confirm_cancel":
                        def dismiss(dialog):
                            dialogs.append(dialog.message)
                            dialog.dismiss()
                        page.on("dialog", dismiss)
                        if surface == "setup":
                            button = page.locator('[data-panel="setup.localization"] ui-button').filter(has_text="맵핑 시작")
                        else:
                            button = page.get_by_role("button", name="이전 릴리스로 복귀", exact=True)
                            page.wait_for_function("""() => {
                              const cards = [...document.querySelectorAll('[data-panel="host.operations"] section.ui-readback')];
                              const release = cards[1];
                              const rollback = [...document.querySelectorAll('[data-panel="host.operations"] ui-button')]
                                .find(item => item.textContent.trim() === '이전 릴리스로 복귀');
                              return release?.dataset.available === 'true' && release.textContent.includes('r1')
                                && rollback && !rollback.disabled;
                            }""")
                        assert button.is_enabled(), (role, surface, scenario)
                        button.click()
                        page.wait_for_timeout(100)
                    filename = f"{role}-{surface}-{scenario}-{width}x{height}.png"
                    page.screenshot(path=str(CAPTURES / filename), full_page=True)
                    measure = page.evaluate("""() => ({
                      overflowX: Math.max(0, document.documentElement.scrollWidth - innerWidth),
                      panelCount: document.querySelectorAll('ui-section[data-panel]').length,
                      status: document.querySelector('#surface-status')?.textContent || '',
                      notices: [...document.querySelectorAll('ui-status')].map(node => node.textContent.trim()).filter(Boolean).slice(0, 18),
                      eStopVisible: (() => { const node=document.querySelector('#shell-estop'); return !!node && node.getBoundingClientRect().right <= innerWidth; })(),
                    })""")
                    records.append({"role": role, "surface": surface, "scenario": scenario,
                                    "viewport": f"{width}x{height}", "image": filename,
                                    "posts": posts, "dialogs": dialogs, "errors": errors, **measure})
                    assert errors == [], records[-1]
                    assert measure["overflowX"] == 0, records[-1]
                    if scenario == "confirm_cancel":
                        assert posts == [], records[-1]
                        assert len(dialogs) == 1, records[-1]
                    if role == "operator" and surface == "device":
                        assert page.locator('#surface-status a[href="/console"]').is_visible(), records[-1]
                        assert page.locator('#shell-role').inner_text() == "권한 제한", records[-1]
                    if surface == "setup" and scenario in {"delayed", "disconnected", "unavailable"}:
                        expected = {"delayed": "지연", "disconnected": "연결 끊김", "unavailable": "정보 없음"}[scenario]
                        reason = page.locator('[data-panel="setup.docking"] ui-status').filter(has_text=expected).first.inner_text()
                        assert expected in reason, records[-1]
                        if role == "administrator":
                            admin_reason = page.locator('[data-panel="setup.dock_admin"] ui-status').filter(has_text=expected).first.inner_text()
                            assert expected in admin_reason, records[-1]
                    if role == "administrator" and surface == "device" and scenario in {
                        "delayed", "disconnected", "unavailable",
                    }:
                        expected = {"delayed": "지연", "disconnected": "연결 끊김",
                                    "unavailable": "정보 없음"}[scenario]
                        card_status = page.locator("section.ui-readback ui-status").filter(has_text=expected).first.inner_text()
                        assert expected in card_status, records[-1]
                        assert page.get_by_role("button", name="사업장 Wi-Fi로 전환", exact=True).is_disabled(), records[-1]
                    context.close()
        browser.close()
    (CAPTURES / "matrix.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def test_existing_dock_type_ignores_hidden_new_type_fields(tmp_path):
    """An administrator can reuse a type after exploring the observation detector."""
    from fastapi import Response

    client = _core_client(tmp_path)
    writes = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script("sessionStorage.setItem('rosy.dashboard.token', 'rosy-dev-admin')")
        page.on("dialog", lambda dialog: dialog.accept())

        def serve(route):
            path = urlsplit(route.request.url).path
            if route.request.method == "POST":
                writes.append({"path": path, "body": route.request.post_data_json})
                route.fulfill(status=200, content_type="application/json", body='{"id":"dock-reused"}')
                return
            response = _response(client, path, TOKENS["administrator"], "normal", "setup")
            if path == "/api/v1/docking/types":
                response = Response(content=json.dumps({"types": [{"name": "known", "detector": "simulated"}]}),
                                    media_type="application/json")
            route.fulfill(status=response.status_code, headers={
                "content-type": response.headers.get("content-type", "application/octet-stream"),
            }, body=response.content if hasattr(response, "content") else response.body)

        page.route("**/*", serve)
        page.goto("http://rosy.test/setup", wait_until="domcontentloaded")
        form = page.locator('[data-panel="setup.dock_admin"] form')
        form.locator('ui-button[type="submit"]').wait_for(state="visible")
        page.wait_for_function("document.querySelector('[data-panel=\"setup.dock_admin\"] form ui-button[type=\"submit\"]')?.disabled === false")
        form.locator('[name="dock_id"]').fill("dock-reused")
        type_input = form.locator('[name="dock_type"]')
        type_input.fill("new-type")
        form.locator("select").select_option("observation")
        tag = form.locator('[name="tag_id"]')
        size = form.locator('[name="tag_size_m"]')
        tag.fill("17")
        size.fill("0.2")
        type_input.fill("known")
        assert tag.is_hidden() and size.is_hidden(), page.evaluate("""() => {
          const form = document.querySelector('[data-panel="setup.dock_admin"] form');
          return {type: form.querySelector('[name="dock_type"]').value,
            labels: [...form.querySelectorAll('.ui-field-label')].map(label => ({text: label.textContent, hidden: label.hidden})),
            options: document.querySelector('#setup-dock-types')?.innerHTML};
        }""")
        type_input.fill("new-type")
        assert tag.is_visible() and size.is_visible()
        assert tag.input_value() == "17" and size.input_value() == "0.2"
        type_input.fill("known")
        page.evaluate("""() => {
          const form = document.querySelector('[data-panel="setup.dock_admin"] form');
          form.querySelector('[name="tag_id"]').value = '';
          form.querySelector('[name="tag_size_m"]').value = '';
        }""")
        form.locator('ui-button[type="submit"]').click()
        page.wait_for_function("document.querySelector('[data-panel=\"setup.dock_admin\"] ui-status')?.textContent.includes('등록했습니다')")
        assert [write["path"] for write in writes] == ["/api/v1/docking/docks"]
        assert writes[0]["body"]["type"] == "known"
        browser.close()


def test_device_host_cards_clear_old_values_on_forbidden_and_recover(tmp_path):
    """A later denied read must not leave an earlier Host Agent result on screen."""
    client = _core_client(tmp_path)
    phase = {"scenario": "normal"}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script("sessionStorage.setItem('rosy.dashboard.token', 'rosy-dev-admin')")

        def serve(route):
            path = urlsplit(route.request.url).path
            response = _response(client, path, TOKENS["administrator"], phase["scenario"], "device")
            route.fulfill(status=response.status_code, headers={
                "content-type": response.headers.get("content-type", "application/octet-stream"),
                "cache-control": "no-store",
            }, body=response.content if hasattr(response, "content") else response.body)

        page.route("**/*", serve)
        page.goto("http://rosy.test/device", wait_until="domcontentloaded")
        cards = page.locator('[data-panel="host.operations"] section.ui-readback')
        page.wait_for_function("""() => {
          const lines = document.querySelectorAll('[data-panel="host.operations"] .host-card-headline');
          return lines[0]?.textContent.includes('site-fixture') && lines[1]?.textContent.includes('이전 r1');
        }""")
        phase["scenario"] = "forbidden"
        page.wait_for_function("""() => [...document.querySelectorAll('[data-panel="host.operations"] section.ui-readback')]
          .slice(0, 2).every(card => card.querySelector('ui-status')?.textContent.includes('권한'))""", timeout=30_000)
        assert "site-fixture" not in cards.nth(0).locator("dl").text_content()
        assert "r1" not in cards.nth(1).locator("dl").text_content()
        assert page.get_by_role("button", name="사업장 Wi-Fi로 전환", exact=True).is_disabled()
        assert page.get_by_role("button", name="이전 릴리스로 복귀", exact=True).is_disabled()
        phase["scenario"] = "normal"
        page.wait_for_function("""() => {
          const lines = document.querySelectorAll('[data-panel="host.operations"] .host-card-headline');
          return lines[0]?.textContent.includes('site-fixture') && lines[1]?.textContent.includes('이전 r1');
        }""", timeout=30_000)
        assert errors == []
        browser.close()


def test_device_procedure_places_status_and_actions_before_long_readouts(tmp_path):
    """Keep the next device action discoverable without scrolling past diagnostics."""
    client = _core_client(tmp_path)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for width, height in ((1366, 768), (390, 844)):
            page = browser.new_page(viewport={"width": width, "height": height})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.add_init_script("sessionStorage.setItem('rosy.dashboard.token', 'rosy-dev-admin')")

            def serve(route):
                path = urlsplit(route.request.url).path
                response = _response(client, path, TOKENS["administrator"], "normal", "device")
                route.fulfill(status=response.status_code, headers={
                    "content-type": response.headers.get("content-type", "application/octet-stream"),
                }, body=response.content if hasattr(response, "content") else response.body)

            page.route("**/*", serve)
            page.goto("http://rosy.test/device", wait_until="domcontentloaded")
            page.wait_for_function("""() => {
              const lines = document.querySelectorAll('[data-panel="host.operations"] .host-card-headline');
              return lines[0]?.textContent.includes('site-fixture') && lines[1]?.textContent.includes('이전 r1');
            }""")
            result = page.evaluate("""() => {
              const host = document.querySelector('[data-panel="host.system"]');
              const operations = document.querySelector('[data-panel="host.operations"]');
              const network = operations.querySelector('section.ui-readback');
              const button = [...network.querySelectorAll('ui-button')]
                .find(item => item.textContent === '사업장 Wi-Fi로 전환');
              const readout = network.querySelector('dl');
              return {hostBottom: host.getBoundingClientRect().bottom,
                operationsTop: operations.getBoundingClientRect().top,
                buttonTop: button.getBoundingClientRect().top,
                readoutTop: readout.getBoundingClientRect().top,
                overflow: document.documentElement.scrollWidth - innerWidth};
            }""")
            assert result["overflow"] == 0
            assert result["buttonTop"] < result["readoutTop"], result
            if width == 390:
                assert result["operationsTop"] < height, result
            button = page.get_by_role("button", name="사업장 Wi-Fi로 전환", exact=True)
            button.focus()
            assert button.evaluate("node => document.activeElement === node")
            assert button.evaluate("node => getComputedStyle(node).outlineStyle !== 'none' && parseFloat(getComputedStyle(node).outlineWidth) > 0")
            disclosure = page.locator('[data-panel="host.system"] details > summary')
            disclosure.focus()
            assert disclosure.evaluate("node => document.activeElement === node")
            assert errors == []
            page.close()
        denied = browser.new_page(viewport={"width": 390, "height": 844})
        denied.add_init_script("sessionStorage.setItem('rosy.dashboard.token', 'rosy-dev-operator')")
        def serve_denied(route):
            path = urlsplit(route.request.url).path
            response = _response(client, path, TOKENS["operator"], "normal", "device")
            route.fulfill(status=response.status_code, headers={
                "content-type": response.headers.get("content-type", "application/octet-stream"),
            }, body=response.content if hasattr(response, "content") else response.body)
        denied.route("**/*", serve_denied)
        denied.goto("http://rosy.test/device", wait_until="domcontentloaded")
        denied.wait_for_function("document.querySelector('#surface-status')?.textContent.includes('역할')")
        assert denied.locator('[data-panel="host.operations"]').count() == 0
        assert denied.locator('#surface-status a[href="/console"]').is_visible()
        denied.close()
        browser.close()


def test_role_procedure_first_boot_full_screen(tmp_path):
    """Capture the real shell while manifest and safety responses have not arrived."""
    client = _core_client(tmp_path)
    CAPTURES.mkdir(parents=True, exist_ok=True)
    records = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for role, surface in (("operator", "setup"), ("administrator", "setup"),
                              ("administrator", "device")):
            for width, height in ((1366, 768), (390, 844)):
                context = browser.new_context(viewport={"width": width, "height": height})
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                token = TOKENS[role]
                init_script = """() => {
                  sessionStorage.setItem('rosy.dashboard.token', __TOKEN__);
                  window.__pendingRequests = [];
                  const originalFetch = window.fetch.bind(window);
                  window.fetch = (input, options) => {
                    const path = String(input);
                    if (path.includes('/api/v1/ui/surfaces/') || path.includes('/api/v1/robot/state')) {
                      window.__pendingRequests.push(path);
                      return new Promise(() => {});
                    }
                    return originalFetch(input, options);
                  };
                }"""
                page.add_init_script(f"({init_script.replace('__TOKEN__', json.dumps(token))})()")

                def serve(route):
                    path = urlsplit(route.request.url).path
                    response = _response(client, path, token, "normal", surface)
                    route.fulfill(status=response.status_code, headers={
                        "content-type": response.headers.get("content-type", "application/octet-stream"),
                        "cache-control": "no-store",
                    }, body=response.content if hasattr(response, "content") else response.body)

                page.route("**/*", serve)
                page.goto(f"http://rosy.test/{surface}", wait_until="domcontentloaded")
                page.wait_for_function("window.__pendingRequests?.some(path => path.includes('/api/v1/ui/surfaces/'))")
                page.wait_for_function("window.__pendingRequests?.some(path => path.includes('/api/v1/robot/state'))")
                filename = f"{role}-{surface}-first-boot-{width}x{height}.png"
                page.screenshot(path=str(CAPTURES / filename), full_page=True)
                measured = page.evaluate("""() => ({
                  loading: document.querySelector('#surface-status')?.textContent || '',
                  safety: document.querySelector('#safety-mode-status')?.textContent || '',
                  safetyVisible: !document.querySelector('#safety-mode-status')?.hidden,
                  panelCount: document.querySelectorAll('ui-section[data-panel]').length,
                  overflowX: Math.max(0, document.documentElement.scrollWidth - innerWidth),
                  eStopVisible: document.querySelector('#shell-estop').getBoundingClientRect().right <= innerWidth,
                })""")
                records.append({"role": role, "surface": surface, "viewport": f"{width}x{height}",
                                "image": filename, "pending": page.evaluate("window.__pendingRequests"),
                                "errors": errors, **measured})
                assert "불러오는 중" in measured["loading"], records[-1]
                assert "안전 상태 확인 중" in measured["safety"] and measured["safetyVisible"], records[-1]
                assert measured["panelCount"] == 0 and measured["overflowX"] == 0, records[-1]
                assert measured["eStopVisible"] and errors == [], records[-1]
                context.close()
        for surface in ("setup", "device"):
            context = browser.new_context()
            page = context.new_page()

            def serve_anonymous(route):
                path = urlsplit(route.request.url).path
                response = _response(client, path, TOKENS["operator"], "normal", surface)
                route.fulfill(status=response.status_code, headers={
                    "content-type": response.headers.get("content-type", "application/octet-stream"),
                }, body=response.content if hasattr(response, "content") else response.body)

            page.route("**/*", serve_anonymous)
            page.goto(f"http://rosy.test/{surface}", wait_until="domcontentloaded")
            page.wait_for_function("document.querySelector('#surface-status')?.textContent.includes('로그인이 필요')")
            assert page.locator("#safety-mode-status").is_hidden()
            assert page.locator("ui-section[data-panel]").count() == 0
            context.close()
        browser.close()
    (CAPTURES / "first-boot-matrix.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def test_console_mode_feedback_full_shell_captures(tmp_path):
    from fastapi import Response

    client = _core_client(tmp_path)
    CAPTURES.mkdir(parents=True, exist_ok=True)
    records = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for width, height in ((1366, 768), (390, 844)):
            context = browser.new_context(viewport={"width": width, "height": height})
            page = context.new_page()
            errors = []
            posts = []
            phase = {"mode": "IDLE"}
            page.add_init_script("sessionStorage.setItem('rosy.dashboard.token', 'rosy-dev-operator')")
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("dialog", lambda dialog: dialog.accept())

            def serve(route):
                request = route.request
                path = urlsplit(request.url).path
                if request.method == "POST" and path == "/api/v1/mode":
                    posts.append({"path": path, "body": request.post_data_json})
                    route.fulfill(status=202, content_type="application/json", body='{"accepted":true}')
                    return
                if request.method != "GET":
                    route.fulfill(status=501, content_type="application/json", body='{"detail":"fixture blocks writes"}')
                    return
                response = _response(client, path, TOKENS["operator"], "normal", "console")
                if path == "/api/v1/system/capabilities" and response.status_code == 200:
                    data = response.json() if hasattr(response, "json") else json.loads(response.body)
                    data["navigation"] = {"goal_navigation": True}
                    response = Response(content=json.dumps(data), media_type="application/json")
                elif path == "/api/v1/robot/state" and response.status_code == 200:
                    data = response.json() if hasattr(response, "json") else json.loads(response.body)
                    data["mode"] = phase["mode"]
                    response = Response(content=json.dumps(data), media_type="application/json")
                route.fulfill(status=response.status_code, headers={
                    "content-type": response.headers.get("content-type", "application/octet-stream"),
                    "cache-control": "no-store",
                }, body=response.content if hasattr(response, "content") else response.body)

            page.route("**/*", serve)
            page.goto("http://rosy.test/console", wait_until="domcontentloaded")
            page.wait_for_selector('[data-panel="console.mode"]')
            button = page.locator('[data-panel="console.mode"] [data-mode="MANUAL"]')
            page.wait_for_function("""document.querySelector(
              '[data-panel="console.mode"] [data-mode="MANUAL"]'
            )?.disabled === false""")
            with page.expect_response(lambda response: response.url.endswith("/api/v1/mode") and response.request.method == "POST"):
                button.click()
            page.wait_for_function("""document.querySelector(
              '[data-panel="console.mode"] [role="status"]:last-of-type'
            )?.textContent.length > 0""")
            mode_status = page.locator('[data-panel="console.mode"] ui-status').nth(0)
            action_status = page.locator('[data-panel="console.mode"] ui-status[role="status"]').last
            assert "대기" in mode_status.inner_text()  # US-009: MODE_LABEL, enum in title
            assert "CORE" in action_status.inner_text(), action_status.inner_text()
            assert posts == [{"path": "/api/v1/mode", "body": {"mode": "MANUAL"}}]
            filename = f"operator-console-mode-feedback-{width}x{height}.png"
            page.screenshot(path=str(CAPTURES / filename), full_page=True)
            measured = page.evaluate("""() => ({
              overflowX: Math.max(0, document.documentElement.scrollWidth - innerWidth),
              eStopVisible: document.querySelector('#shell-estop')?.getBoundingClientRect().right <= innerWidth,
              action: [...document.querySelectorAll('[data-panel="console.mode"] [role="status"]')].at(-1)?.textContent || '',
              mode: document.querySelector('[data-panel="console.mode"] ui-status')?.textContent || '',
            })""")
            assert measured["overflowX"] == 0 and measured["eStopVisible"] and errors == [], measured
            phase["mode"] = "MANUAL"
            page.wait_for_function("""document.querySelector(
              '[data-panel="console.mode"] ui-status'
            )?.textContent.includes('수동')""")
            assert "CORE" in action_status.inner_text(), action_status.inner_text()
            records.append({"viewport": f"{width}x{height}", "image": filename,
                            "posts": posts, "errors": errors, **measured})
            context.close()
        browser.close()
    (CAPTURES / "console-mode-feedback-matrix.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def test_console_teleop_feedback_full_shell_captures(tmp_path):
    from fastapi import Response

    client = _core_client(tmp_path)
    CAPTURES.mkdir(parents=True, exist_ok=True)
    records = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for width, height in ((1366, 768), (390, 844)):
            context = browser.new_context(viewport={"width": width, "height": height})
            page = context.new_page()
            errors = []
            posts = []
            phase = {"fail_state": False}
            page.add_init_script("sessionStorage.setItem('rosy.dashboard.token', 'rosy-dev-operator')")
            page.on("pageerror", lambda error: errors.append(str(error)))

            def serve(route):
                request = route.request
                path = urlsplit(request.url).path
                if request.method == "POST" and path == "/api/v1/teleop":
                    posts.append({"path": path, "body": request.post_data_json})
                    route.fulfill(status=200, content_type="application/json", body="{}")
                    return
                if request.method != "GET":
                    route.fulfill(status=501, content_type="application/json", body='{"detail":"fixture blocks writes"}')
                    return
                if path == "/api/v1/robot/state" and phase["fail_state"]:
                    route.fulfill(status=503, content_type="application/json", body='{"detail":"fixture robot state unavailable"}')
                    return
                if path == "/api/v1/ui/surfaces/console":
                    response = _response(client, path, TOKENS["operator"], "normal", "console")
                    manifest = response.json() if hasattr(response, "json") else json.loads(response.body)
                    if not any(panel["id"] == "console.teleop" for panel in manifest["panels"]):
                        manifest["panels"].append({
                            "id": "console.teleop", "title": "수동 운전", "slot": "act", "order": 30,
                            "module": "/assets/panels/console/teleop.js",
                            "css": ["/assets/panels/surface-panels.css"], "action_group": "drive",
                            "state": "available", "reason": None,
                        })
                    response = Response(content=json.dumps(manifest), media_type="application/json")
                elif path == "/api/v1/robot/state":
                    data = {"mode": "MANUAL", "pose": {"x": 1, "y": 1, "yaw": 0},
                            "velocity": {"linear": 0, "angular": 0},
                            "evidence": {"pose": {"evidence": "fresh"}, "velocity": {"evidence": "fresh"}}}
                    response = Response(content=json.dumps(data), media_type="application/json")
                elif path == "/api/v1/system/capabilities":
                    response = Response(content=json.dumps({"teleop": True,
                        "navigation": {"goal_navigation": True}}), media_type="application/json")
                elif path == "/api/v1/safety/state":
                    response = Response(content='{"estop":false}', media_type="application/json")
                elif path == "/api/v1/host/commissioning":
                    response = Response(content='{"runtime_mode":"hardware"}', media_type="application/json")
                else:
                    response = _response(client, path, TOKENS["operator"], "normal", "console")
                route.fulfill(status=response.status_code, headers={
                    "content-type": response.headers.get("content-type", "application/octet-stream"),
                    "cache-control": "no-store",
                }, body=response.content if hasattr(response, "content") else response.body)

            page.route("**/*", serve)
            page.goto("http://rosy.test/console", wait_until="domcontentloaded")
            panel = page.locator('[data-panel="console.teleop"]')
            page.wait_for_selector('[data-panel="console.teleop"] .surface-teleop-controls ui-button')
            button = panel.locator(".surface-teleop-controls ui-button").first
            page.wait_for_function("document.querySelector('[data-panel=\"console.teleop\"] .surface-teleop-controls ui-button')?.disabled === false")
            page.evaluate("""() => {
              const button = document.querySelector('[data-panel="console.teleop"] .surface-teleop-controls ui-button');
              button.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,pointerId:1}));
              setTimeout(() => button.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,pointerId:1})), 180);
            }""")
            page.wait_for_function("document.querySelector('[data-panel=\"console.teleop\"] ui-status[role=\"status\"]:last-of-type')?.textContent.length > 0")
            page.wait_for_timeout(250)
            assert posts and posts[-1]["body"] == {"linear": 0, "angular": 0}, posts
            action_feedback = panel.locator('ui-status[role="status"]').last
            readiness_status = panel.locator("ui-status").first
            release_text = action_feedback.inner_text()
            phase["fail_state"] = True
            page.wait_for_function("document.querySelector('[data-panel=\"console.teleop\"] ui-status')?.textContent.includes('fixture robot state unavailable')")
            assert readiness_status.inner_text().find("fixture robot state unavailable") >= 0
            assert action_feedback.inner_text() == release_text
            filename = f"operator-console-teleop-feedback-{width}x{height}.png"
            page.screenshot(path=str(CAPTURES / filename), full_page=True)
            measured = page.evaluate("""() => ({
              overflowX: Math.max(0, document.documentElement.scrollWidth - innerWidth),
              eStopVisible: document.querySelector('#shell-estop')?.getBoundingClientRect().right <= innerWidth,
              readiness: document.querySelector('[data-panel="console.teleop"] ui-status')?.textContent || '',
              action: [...document.querySelectorAll('[data-panel="console.teleop"] ui-status[role="status"]')].at(-1)?.textContent || '',
            })""")
            assert measured["overflowX"] == 0 and measured["eStopVisible"] and errors == [], measured
            records.append({"viewport": f"{width}x{height}", "image": filename,
                            "posts": posts, "errors": errors, **measured})
            context.close()
        browser.close()
    (CAPTURES / "console-teleop-feedback-matrix.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def test_console_line_follow_and_docking_feedback_full_shell_captures(tmp_path):
    from fastapi import Response

    client = _core_client(tmp_path)
    capture_dir = CAPTURES / "line-follow-docking"
    capture_dir.mkdir(parents=True, exist_ok=True)
    records = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for width, height in ((1366, 768), (390, 844)):
            context = browser.new_context(viewport={"width": width, "height": height})
            page = context.new_page()
            errors = []
            posts = []
            phase = {"line_failed": False, "docking_failed": False}
            page.add_init_script("sessionStorage.setItem('rosy.dashboard.token', 'rosy-dev-operator')")
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("dialog", lambda dialog: dialog.accept())

            def serve(route):
                request = route.request
                path = urlsplit(request.url).path
                if request.method in {"POST", "PUT"}:
                    posts.append({"method": request.method, "path": path,
                                  "body": request.post_data_json})
                    if path == "/api/v1/line-follow/mode":
                        phase["line_failed"] = True
                    elif path in {"/api/v1/docking/dock", "/api/v1/docking/undock", "/api/v1/docking/cancel"}:
                        phase["docking_failed"] = True
                    route.fulfill(status=202, content_type="application/json", body='{"accepted":true}')
                    return
                if request.method != "GET":
                    route.fulfill(status=501, content_type="application/json", body='{"detail":"fixture blocks writes"}')
                    return
                if path == "/api/v1/ui/surfaces/console":
                    response = _response(client, path, TOKENS["operator"], "normal", "console")
                    manifest = response.json() if hasattr(response, "json") else json.loads(response.body)
                    additions = (
                        {"id":"console.docking", "title":"Docking", "slot":"act", "order":40,
                         "module":"/assets/panels/console/docking.js",
                         "css":["/assets/panels/surface-panels.css"], "action_group":"docking",
                         "state":"available", "reason":None},
                        {"id":"console.line_follow", "title":"Line follow", "slot":"act", "order":50,
                         "module":"/assets/panels/console/line-follow.js",
                         "css":["/assets/panels/surface-panels.css"], "action_group":"line_follow",
                         "state":"available", "reason":None},
                    )
                    present = {panel["id"] for panel in manifest["panels"]}
                    manifest["panels"].extend(panel for panel in additions if panel["id"] not in present)
                    groups = manifest.setdefault("action_groups", [])
                    group_ids = {group["id"] for group in groups}
                    groups.extend(group for group in (
                        {"id":"docking", "title":"Docking", "order":20},
                        {"id":"line_follow", "title":"Line follow", "order":30},
                    ) if group["id"] not in group_ids)
                    response = Response(content=json.dumps(manifest), media_type="application/json")
                elif path == "/api/v1/line-follow":
                    if phase["line_failed"]:
                        route.fulfill(status=503, content_type="application/json", body='{"detail":"fixture line status unavailable"}')
                        return
                    response = Response(content='{"mode":"OFF","state":"IDLE"}', media_type="application/json")
                elif path == "/api/v1/docking/status":
                    if phase["docking_failed"]:
                        route.fulfill(status=503, content_type="application/json", body='{"detail":"fixture docking status unavailable"}')
                        return
                    response = Response(content='{"supported":true,"state":"UNDOCKED"}', media_type="application/json")
                elif path == "/api/v1/docking/docks":
                    response = Response(content='{"docks":[{"id":"dock-a","type":"charger"},{"id":"dock-b","type":"charger"}]}',
                                        media_type="application/json")
                elif path == "/api/v1/system/capabilities":
                    response = Response(content='{"navigation":{"goal_navigation":true}}', media_type="application/json")
                else:
                    response = _response(client, path, TOKENS["operator"], "normal", "console")
                route.fulfill(status=response.status_code, headers={
                    "content-type": response.headers.get("content-type", "application/octet-stream"),
                    "cache-control": "no-store",
                }, body=response.content if hasattr(response, "content") else response.body)

            page.route("**/*", serve)
            page.goto("http://rosy.test/console", wait_until="domcontentloaded")
            page.locator("#action-tab-line_follow").click()
            line_panel = page.locator('[data-panel="console.line_follow"]')
            page.wait_for_selector('[data-panel="console.line_follow"] ui-button')
            page.wait_for_function("document.querySelector('[data-panel=\"console.line_follow\"] ui-button')?.disabled === false")
            line_panel.locator("ui-button").first.click()
            page.wait_for_function("document.querySelector('[data-panel=\"console.line_follow\"] ui-status[role=status]:last-of-type')?.textContent.includes('CORE')")
            page.wait_for_function("document.querySelector('[data-panel=\"console.line_follow\"] ui-status')?.textContent.includes('fixture line status unavailable')")
            line_filename = f"operator-console-line-follow-{width}x{height}.png"
            page.screenshot(path=str(capture_dir / line_filename), full_page=True)
            line_measured = page.evaluate("""() => ({
              overflowX: Math.max(0, document.documentElement.scrollWidth - innerWidth),
              eStopVisible: document.querySelector('#shell-estop')?.getBoundingClientRect().right <= innerWidth,
              readback: document.querySelector('[data-panel="console.line_follow"] ui-status')?.textContent || '',
              action: [...document.querySelectorAll('[data-panel="console.line_follow"] ui-status[role="status"]')].at(-1)?.textContent || '',
            })""")
            assert line_measured["overflowX"] == 0 and line_measured["eStopVisible"]
            assert "fixture line status unavailable" in line_measured["readback"] and "CORE" in line_measured["action"]
            records.append({"surface":"line_follow", "viewport":f"{width}x{height}",
                            "image":line_filename, "posts":list(posts), "errors":list(errors), **line_measured})

            phase["line_failed"] = False
            posts.clear()
            page.goto("http://rosy.test/console", wait_until="domcontentloaded")
            page.locator("#action-tab-docking").click()
            dock_panel = page.locator('[data-panel="console.docking"]')
            page.wait_for_selector('[data-panel="console.docking"] ui-button')
            dock_panel.locator("select").select_option("dock-b")
            dock_panel.locator("ui-button").first.click()
            page.wait_for_function("document.querySelector('[data-panel=\"console.docking\"] ui-status[role=status]:last-of-type')?.textContent.includes('CORE')")
            page.wait_for_function("document.querySelector('[data-panel=\"console.docking\"] ui-status')?.textContent.includes('fixture docking status unavailable')")
            assert dock_panel.locator("select").input_value() == "dock-b"
            assert len(posts) == 1, posts
            filename = f"operator-console-docking-{width}x{height}.png"
            page.screenshot(path=str(capture_dir / filename), full_page=True)
            measured = page.evaluate("""() => ({
              overflowX: Math.max(0, document.documentElement.scrollWidth - innerWidth),
              eStopVisible: document.querySelector('#shell-estop')?.getBoundingClientRect().right <= innerWidth,
              dockReadback: document.querySelector('[data-panel="console.docking"] ui-status')?.textContent || '',
              dockAction: [...document.querySelectorAll('[data-panel="console.docking"] ui-status[role="status"]')].at(-1)?.textContent || '',
            })""")
            assert measured["overflowX"] == 0 and measured["eStopVisible"] and errors == [], measured
            assert "fixture docking status unavailable" in measured["dockReadback"] and "CORE" in measured["dockAction"]
            records.append({"surface":"docking", "viewport": f"{width}x{height}", "image": filename,
                            "posts": list(posts), "errors": list(errors), **measured})
            context.close()
        browser.close()
    (capture_dir / "console-line-follow-docking-matrix.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def test_console_map_data_and_action_feedback_full_shell_captures(tmp_path):
    from fastapi import Response

    client = _core_client(tmp_path)
    capture_dir = CAPTURES / "map-data-action"
    capture_dir.mkdir(parents=True, exist_ok=True)
    records = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for width, height in ((1366, 768), (390, 844)):
            context = browser.new_context(viewport={"width": width, "height": height})
            page = context.new_page()
            errors = []
            posts = []
            page.add_init_script("sessionStorage.setItem('rosy.dashboard.token', 'rosy-dev-operator')")
            page.on("pageerror", lambda error: errors.append(str(error)))

            def serve(route):
                request = route.request
                path = urlsplit(request.url).path
                if request.method == "POST":
                    posts.append({"path": path, "body": request.post_data_json})
                    route.fulfill(status=202, content_type="application/json", body='{"accepted":true}')
                    return
                if request.method != "GET":
                    route.fulfill(status=501, content_type="application/json", body='{"detail":"fixture blocks writes"}')
                    return
                if path == "/api/v1/ui/surfaces/console":
                    response = _response(client, path, TOKENS["operator"], "normal", "console")
                    manifest = response.json() if hasattr(response, "json") else json.loads(response.body)
                    if not any(panel["id"] == "console.map" for panel in manifest["panels"]):
                        manifest["panels"].append({
                            "id":"console.map", "title":"Map and position", "slot":"observe", "order":20,
                            "module":"/assets/panels/console/map.js",
                            "css":["/assets/panels/surface-panels.css"],
                            "state":"available", "reason":None,
                        })
                    response = Response(content=json.dumps(manifest), media_type="application/json")
                elif path == "/api/v1/robot/state":
                    route.fulfill(status=503, content_type="application/json", body='{"detail":"fixture robot state unavailable"}')
                    return
                elif path == "/api/v1/map":
                    route.fulfill(status=404, content_type="application/json",
                                  body='{"error":{"code":"NOT_FOUND","message":"fixture map data unavailable"}}')
                    return
                elif path == "/api/v1/system/capabilities":
                    response = Response(content='{"navigation":{"goal_navigation":true}}', media_type="application/json")
                elif path == "/api/v1/host/commissioning":
                    response = Response(content='{"runtime_mode":"hardware"}', media_type="application/json")
                elif path == "/api/v1/navigation/path":
                    response = Response(content='{"poses":[]}', media_type="application/json")
                elif path.startswith("/api/v1/map/costmap"):
                    response = Response(content='{"data":[]}', media_type="application/json")
                else:
                    response = _response(client, path, TOKENS["operator"], "normal", "console")
                route.fulfill(status=response.status_code, headers={
                    "content-type": response.headers.get("content-type", "application/octet-stream"),
                    "cache-control": "no-store",
                }, body=response.content if hasattr(response, "content") else response.body)

            page.route("**/*", serve)
            page.goto("http://rosy.test/console", wait_until="domcontentloaded")
            panel = page.locator('[data-panel="console.map"]')
            page.wait_for_selector('[data-panel="console.map"] canvas')
            page.wait_for_function("document.querySelector('#map-status')?.getAttribute('state') === 'empty'")
            panel.locator('[data-map-click="goal"]').click()
            panel.locator("canvas").click(position={"x":40,"y":40})
            action = panel.locator('ui-status[role="status"]').last
            assert action.inner_text()
            assert posts == []
            filename = f"operator-console-map-data-action-{width}x{height}.png"
            page.screenshot(path=str(capture_dir / filename), full_page=True)
            measured = page.evaluate("""() => {
              const panel=document.querySelector('[data-panel="console.map"]');
              const statuses=[...panel.querySelectorAll('ui-status')].map(node=>node.textContent);
              return {
                overflowX:Math.max(0,document.documentElement.scrollWidth-innerWidth),
                eStopVisible:document.querySelector('#shell-estop')?.getBoundingClientRect().right<=innerWidth,
                mapData:document.querySelector('#map-status')?.textContent||'',
                readiness:statuses.find(text=>text.includes('fixture robot state unavailable'))||'',
                action:statuses.at(-1)||'',
              };
            }""")
            assert measured["overflowX"] == 0 and measured["eStopVisible"] and errors == [], measured
            assert page.locator('[data-panel="console.map"] ui-empty').is_visible()
            assert "fixture robot state unavailable" in measured["readiness"]
            assert measured["action"] and not posts
            records.append({"viewport":f"{width}x{height}", "image":filename,
                            "posts":posts, "errors":errors, **measured})
            context.close()
        browser.close()
    (capture_dir / "console-map-data-action-matrix.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def test_admin_hardware_refresh_feedback_full_shell_captures(tmp_path):
    from fastapi import Response

    client = _core_client(tmp_path)
    capture_dir = CAPTURES / "host-hardware-refresh"
    capture_dir.mkdir(parents=True, exist_ok=True)
    records = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for width, height in ((1366, 768), (390, 844)):
            context = browser.new_context(viewport={"width": width, "height": height})
            page = context.new_page()
            errors = []
            posts = []
            phase = {"accepted": False}
            page.add_init_script("""sessionStorage.setItem('rosy.dashboard.token', 'rosy-dev-admin');
              const nativeSetInterval=window.setInterval.bind(window);
              window.setInterval=(fn,delay,...args)=>nativeSetInterval(fn,delay===10000?250:delay,...args);""")
            page.on("pageerror", lambda error: errors.append(str(error)))

            def serve(route):
                request = route.request
                path = urlsplit(request.url).path
                if request.method == "POST" and path == "/api/v1/host/hardware/refresh":
                    posts.append({"path":path,"method":request.method})
                    phase["accepted"] = True
                    route.fulfill(status=202, content_type="application/json", body='{"accepted":true}')
                    return
                if request.method != "GET":
                    route.fulfill(status=501, content_type="application/json", body='{"detail":"fixture blocks writes"}')
                    return
                if path == "/api/v1/ui/surfaces/device":
                    response = _response(client, path, TOKENS["administrator"], "normal", "device")
                    manifest = response.json() if hasattr(response, "json") else json.loads(response.body)
                    if not any(panel["id"] == "host.hardware" for panel in manifest["panels"]):
                        manifest["panels"].append({
                            "id":"host.hardware", "title":"Board hardware", "slot":"main", "order":80,
                            "module":"/assets/panels/host/hardware.js",
                            "css":["/assets/panels/host/hardware.css"], "state":"available", "reason":None,
                        })
                    response = Response(content=json.dumps(manifest), media_type="application/json")
                elif path == "/api/v1/host/hardware":
                    stamp = "2026-09-28T02:00:00Z" if phase["accepted"] else "2026-09-28T01:00:00Z"
                    response = Response(content=json.dumps({
                        "available":True,"measured_at":stamp,"age_s":2,
                        "devices":[{"id":"camera","label":"Camera","state":"ok","evidence":"fixture readback"}],
                    }), media_type="application/json")
                else:
                    response = _response(client, path, TOKENS["administrator"], "normal", "device")
                route.fulfill(status=response.status_code, headers={
                    "content-type":response.headers.get("content-type","application/octet-stream"),
                    "cache-control":"no-store",
                }, body=response.content if hasattr(response,"content") else response.body)

            page.route("**/*", serve)
            page.goto("http://rosy.test/device", wait_until="domcontentloaded")
            panel = page.locator('[data-panel="host.hardware"]')
            page.wait_for_selector('[data-panel="host.hardware"] .hardware-refresh')
            page.wait_for_function("document.querySelector('[data-panel=\"host.hardware\"] .hardware-measured dd')?.textContent.length > 0")
            measured = panel.locator(".hardware-measured dd")
            action = panel.locator("#hardware-action-note")
            before = measured.inner_text()
            panel.locator(".hardware-refresh").click()
            page.wait_for_function("document.querySelector('#hardware-action-note')?.textContent.length > 0 && document.querySelector('[data-panel=\"host.hardware\"] .hardware-refresh')?.disabled === false")
            page.wait_for_function("previous => document.querySelector('[data-panel=\"host.hardware\"] .hardware-measured dd')?.textContent !== previous", arg=before)
            accepted = action.inner_text()
            assert accepted and measured.inner_text() != before
            page.wait_for_timeout(350)
            assert action.inner_text() == accepted
            assert posts == [{"path":"/api/v1/host/hardware/refresh","method":"POST"}]
            filename = f"administrator-device-hardware-refresh-{width}x{height}.png"
            page.screenshot(path=str(capture_dir / filename), full_page=True)
            measured_result = page.evaluate("""() => ({
              overflowX:Math.max(0,document.documentElement.scrollWidth-innerWidth),
              eStopVisible:document.querySelector('#shell-estop')?.getBoundingClientRect().right<=innerWidth,
              measurement:document.querySelector('[data-panel="host.hardware"] .hardware-measured dd')?.textContent||'',
              periodicStatus:document.querySelector('[data-panel="host.hardware"] .hardware-note')?.textContent||'',
              action:document.querySelector('#hardware-action-note')?.textContent||'',
            })""")
            assert measured_result["overflowX"] == 0 and measured_result["eStopVisible"] and errors == [], measured_result
            assert measured_result["measurement"] and measured_result["periodicStatus"] and measured_result["action"] == accepted
            records.append({"viewport":f"{width}x{height}","image":filename,"posts":posts,
                            "errors":errors,**measured_result})
            context.close()
        browser.close()
    (capture_dir / "admin-hardware-refresh-matrix.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def test_admin_identity_editor_poll_feedback_full_shell_captures(tmp_path):
    from fastapi import Response

    client = _core_client(tmp_path)
    capture_dir = CAPTURES / "admin-device-identity-feedback"
    capture_dir.mkdir(parents=True, exist_ok=True)
    records = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for width, height in ((1366, 768), (390, 844)):
            context = browser.new_context(viewport={"width": width, "height": height})
            page = context.new_page()
            errors = []
            posts = []
            reads = {"count": 0}
            page.add_init_script("""sessionStorage.setItem('rosy.dashboard.token', 'rosy-dev-admin');
              const nativeSetInterval=window.setInterval.bind(window);
              window.setInterval=(fn,delay,...args)=>nativeSetInterval(fn,delay===30000?250:delay,...args);""")
            page.on("pageerror", lambda error: errors.append(str(error)))

            def serve(route):
                request = route.request
                path = urlsplit(request.url).path
                if path == "/api/v1/system/info" and request.method == "PUT":
                    body = request.post_data_json
                    posts.append({"path": path, "method": "PUT", "robot_name": body.get("robot_name")})
                    route.fulfill(status=200, content_type="application/json",
                                  body=json.dumps({"robot_name": body.get("robot_name")}))
                    return
                if path == "/api/v1/system/info" and request.method == "GET":
                    reads["count"] += 1
                    route.fulfill(status=200, content_type="application/json", body=json.dumps({
                        "robot_id": "robot-fixture", "robot_name": "robot-fixture",
                        "robot_number": "fixture-01", "runtime_mode": "hardware",
                    }))
                    return
                if request.method != "GET":
                    route.fulfill(status=501, content_type="application/json", body='{"detail":"fixture blocks writes"}')
                    return
                response = _response(client, path, TOKENS["administrator"], "normal", "device")
                route.fulfill(status=response.status_code, headers={
                    "content-type": response.headers.get("content-type", "application/octet-stream"),
                    "cache-control": "no-store",
                }, body=response.content if hasattr(response, "content") else response.body)

            page.route("**/*", serve)
            page.goto("http://rosy.test/device", wait_until="domcontentloaded")
            host = page.locator('[data-panel="host.system"]')
            page.wait_for_selector('[data-panel="host.system"] [name="robot_name"]', state="attached")
            page.locator('[data-panel="host.system"] details.host-system-detail > summary').click()
            identity_input = host.locator('[name="robot_name"]')
            form = host.locator(".host-system-detail .ui-form")
            assert reads["count"] >= 1
            identity_input.fill("draft-pinky")
            baseline_reads = reads["count"]
            page.wait_for_timeout(700)
            assert reads["count"] >= baseline_reads + 2
            assert form.count() == 1
            assert identity_input.input_value() == "draft-pinky"

            form.evaluate("node => node.requestSubmit()")
            feedback = host.locator(".host-system-detail ui-status[role='status']")
            page.wait_for_function("document.querySelector('[data-panel=\"host.system\"] .host-system-detail ui-status[role=\"status\"]')?.getAttribute('state') === 'ready'")
            receipt = feedback.inner_text()
            reads_after_receipt = reads["count"]
            page.wait_for_timeout(450)
            assert reads["count"] > reads_after_receipt
            assert feedback.inner_text() == receipt
            assert form.count() == 1
            assert identity_input.input_value() == "draft-pinky"
            assert posts == [{"path": "/api/v1/system/info", "method": "PUT", "robot_name": "draft-pinky"}]
            filename = f"administrator-device-identity-feedback-{width}x{height}.png"
            page.screenshot(path=str(capture_dir / filename), full_page=True)
            result = page.evaluate("""() => ({
              overflowX:Math.max(0,document.documentElement.scrollWidth-innerWidth),
              eStopVisible:document.querySelector('#shell-estop')?.getBoundingClientRect().right<=innerWidth,
              formCount:document.querySelectorAll('[data-panel="host.system"] .host-system-detail .ui-form').length,
              value:document.querySelector('[data-panel="host.system"] [name="robot_name"]')?.value||'',
              readback:document.querySelector('[data-panel="host.system"] .host-system-overview ui-status')?.textContent||'',
              feedback:document.querySelector('[data-panel="host.system"] .host-system-detail ui-status[role="status"]')?.textContent||'',
            })""")
            assert result["overflowX"] == 0 and result["eStopVisible"] and errors == [], result
            assert result["formCount"] == 1 and result["value"] == "draft-pinky" and result["feedback"] == receipt
            records.append({"viewport": f"{width}x{height}", "image": filename, "posts": posts,
                            "identity_reads": reads["count"], "errors": errors, **result})
            context.close()
        browser.close()
    (capture_dir / "admin-device-identity-feedback-matrix.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def test_operator_device_entry_denial_captures(tmp_path):
    client = _core_client(tmp_path)
    capture_dir = CAPTURES / "operator-device-entry-denied"
    capture_dir.mkdir(parents=True, exist_ok=True)
    records = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for width, height in ((1366, 768), (390, 844)):
            context = browser.new_context(viewport={"width": width, "height": height})
            page = context.new_page()
            errors = []
            page.add_init_script("sessionStorage.setItem('rosy.dashboard.token', 'rosy-dev-operator');")
            page.on("pageerror", lambda error: errors.append(str(error)))

            def serve(route):
                path = urlsplit(route.request.url).path
                response = _response(client, path, TOKENS["operator"], "normal", "device")
                route.fulfill(status=response.status_code, headers={
                    "content-type": response.headers.get("content-type", "application/octet-stream"),
                    "cache-control": "no-store",
                }, body=response.content if hasattr(response, "content") else response.body)

            page.route("**/*", serve)
            page.goto("http://rosy.test/device", wait_until="domcontentloaded")
            page.wait_for_function("document.querySelector('#surface-status')?.textContent.trim().length > 0")
            console_link = page.locator('#surface-status a[href="/console"]')
            assert console_link.is_visible()
            assert page.locator('[data-panel="host.hardware"]').count() == 0
            assert page.locator('[data-panel="host.operations"]').count() == 0
            filename = f"operator-device-entry-denied-{width}x{height}.png"
            page.screenshot(path=str(capture_dir / filename), full_page=True)
            result = page.evaluate("""() => ({
              overflowX:Math.max(0,document.documentElement.scrollWidth-innerWidth),
              eStopVisible:document.querySelector('#shell-estop')?.getBoundingClientRect().right<=innerWidth,
              status:document.querySelector('#surface-status')?.textContent.trim()||'',
              consoleLinkVisible:!!document.querySelector('#surface-status a[href="/console"]'),
              hardwarePanelCount:document.querySelectorAll('[data-panel="host.hardware"]').length,
            })""")
            assert result["overflowX"] == 0 and errors == [], result
            assert result["consoleLinkVisible"] and result["hardwarePanelCount"] == 0
            records.append({"role":"operator","viewport":f"{width}x{height}",
                            "image":filename,"errors":errors,**result})
            context.close()
        browser.close()
    (capture_dir / "operator-device-entry-denied-matrix.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
