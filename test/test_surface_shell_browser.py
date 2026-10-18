"""D-204 — 셸이 매니페스트대로 조립하고, 깨진 패널 하나가 화면을 멈추지 않는다."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest
import yaml
from browser_harness import browser_tests_enabled, open_page

pytestmark = pytest.mark.skipif(
    not browser_tests_enabled(),
    reason="set ROSY_RUN_BROWSER_TESTS=1 to run the optional Chromium regression",
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "contracts" / "foundation" / "config"
for name in ("middleware/core/api", "middleware/core/gateway", "middleware/core/events",
             "middleware/core/services", "contracts/foundation"):
    path = str(ROOT / name)
    if path not in sys.path:
        sys.path.insert(0, path)

TOKEN = "sessionStorage.setItem('rosy.dashboard.token', 'rosy-dev-admin');"
BROKEN = {"id": "broken.panel", "title": "깨진 패널", "slot": "main", "order": 1,
          "module": "/assets/panels/broken/missing.js", "css": [], "action_group": None, "state": "available", "reason": None}


@pytest.fixture
def app_client(tmp_path):
    from fastapi.testclient import TestClient

    from core.services import CoreServices
    from core_api_web.api.app import create_app
    from core_common.profile import RobotProfile, robot_config_dir

    config = yaml.safe_load((CONFIG / "rosy_default.yaml").read_text(encoding="utf-8"))
    config["auth"] = {**config["auth"], **yaml.safe_load(
        (CONFIG / "rosy_dev_auth.yaml").read_text(encoding="utf-8"))["auth"]}
    robot_dir = robot_config_dir("pinky_pro")
    profile = RobotProfile.load(robot_dir / "profile.yaml")
    caps = yaml.safe_load((robot_dir / "capabilities.yaml").read_text(encoding="utf-8"))
    services = CoreServices.build(config, profile, caps, tmp_path / "wp.json")
    return TestClient(create_app(config, services)), services


def _proxy(page, client, *, break_one=False):
    def handle(route):
        request = route.request
        url = urlparse(request.url)
        path = url.path + (f"?{url.query}" if url.query else "")
        response = client.request(request.method, path, headers=request.headers,
                                  content=request.post_data_buffer)
        body = response.content
        if break_one and url.path == "/api/v1/ui/surfaces/device":
            manifest = response.json()
            manifest["panels"].insert(0, BROKEN)
            manifest["revision"] = "sha256:broken"
            body = json.dumps(manifest).encode("utf-8")
        headers = {k: v for k, v in response.headers.items() if k.lower() not in {"content-length", "content-encoding"}}
        route.fulfill(status=response.status_code, headers=headers, body=body)

    page.route("http://rosy.test/**", handle)


def test_the_device_surface_mounts_the_events_panel(app_client):
    sync_api = pytest.importorskip("playwright.sync_api")
    client, services = app_client
    services.events.publish("system.test", severity="warning", source="test", data={})
    with sync_api.sync_playwright() as playwright:
        browser, page, errors = open_page(playwright, 1280, 800)
        try:
            _proxy(page, client)
            page.add_init_script(script=TOKEN)
            page.goto("http://rosy.test/device", wait_until="domcontentloaded")
            page.wait_for_selector('ui-section[data-panel="system.events"] .event-type', state="attached")
            # Other events may also have been published while the page loaded, so
            # only require that *some* event row shows the one we published (T9-a).
            types = page.locator(".event-type").all_text_contents()
            assert "system.test" in types
            # D-741 6: the rail writes the short name under the icon; the full name is the accessible name.
            current = page.locator('#surface-switch a.ui-rail-item[aria-current="page"]')
            assert current.get_attribute("aria-label") == "설치·정비"
            assert current.text_content() == "설치"
            assert page.locator("#shell-role").text_content() == "관리자"
            assert not errors
        finally:
            browser.close()


def test_a_broken_panel_stays_in_its_slot(app_client):
    sync_api = pytest.importorskip("playwright.sync_api")
    client, _ = app_client
    with sync_api.sync_playwright() as playwright:
        browser, page, _errors = open_page(playwright, 1280, 800)
        try:
            _proxy(page, client, break_one=True)
            page.add_init_script(script=TOKEN)
            page.goto("http://rosy.test/device", wait_until="domcontentloaded")
            page.wait_for_selector('ui-section[data-panel="broken.panel"][data-failed="true"]')
            page.wait_for_selector('ui-section[data-panel="system.events"] ol.event-list', state="attached")
            order = page.eval_on_selector_all("ui-section[data-panel]", "els => els.map(e => e.dataset.panel)")
            assert order[0] == "broken.panel" and "system.events" in order
            assert page.locator('ui-section[data-failed="true"]').count() == 1
        finally:
            browser.close()


def test_the_shell_estop_reaches_the_safety_route(app_client):
    sync_api = pytest.importorskip("playwright.sync_api")
    client, services = app_client
    with sync_api.sync_playwright() as playwright:
        browser, page, _errors = open_page(playwright, 1280, 800)
        try:
            _proxy(page, client)
            page.add_init_script(script=TOKEN)
            page.goto("http://rosy.test/device", wait_until="domcontentloaded")
            page.click("#shell-estop")
            page.wait_for_function("() => document.getElementById('shell-notice').textContent.length > 0")
            assert page.locator("#shell-notice").text_content().startswith("비상 정지 요청 접수")
            assert services.safety.estop is True
        finally:
            browser.close()
