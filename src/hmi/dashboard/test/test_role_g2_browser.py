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
                        page.wait_for_function("document.querySelectorAll('ui-section[data-panel]').length > 0")
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
                            button = page.get_by_text("이전 릴리스로 복귀", exact=True)
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
                        reason = page.locator('[data-panel="setup.docking"] ui-status').inner_text()
                        expected = {"delayed": "지연", "disconnected": "연결 끊김", "unavailable": "정보 없음"}[scenario]
                        assert expected in reason, records[-1]
                        if role == "administrator":
                            admin_reason = page.locator('[data-panel="setup.dock_admin"] ui-status').inner_text()
                            assert expected in admin_reason, records[-1]
                    if role == "administrator" and surface == "device" and scenario in {
                        "delayed", "disconnected", "unavailable",
                    }:
                        expected = {"delayed": "지연", "disconnected": "연결 끊김",
                                    "unavailable": "정보 없음"}[scenario]
                        card_status = page.locator("section.ui-readback ui-status").first.inner_text()
                        assert expected in card_status, records[-1]
                        assert page.get_by_text("사업장 Wi-Fi로 전환", exact=True).is_disabled(), records[-1]
                    context.close()
        browser.close()
    (CAPTURES / "matrix.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


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
