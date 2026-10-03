"""D-321 addendum: the dashboard shows "보정 중 — <label>" while a calibration lease is alive.

The state comes from a real CoreServices + FastAPI app (no canned activity): the test
opens the lease through the API, so the chip proves the whole path CORE → screen.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]
SRC = ROOT / "src"
for package in ("runtime/api_web", "runtime/gateway", "runtime/events", "runtime/services",
                "contracts/foundation"):
    sys.path.insert(0, str(SRC / package))

pytestmark = pytest.mark.skipif(
    os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
    reason="set ROSY_RUN_BROWSER_TESTS=1 for LOCAL Chromium capture",
)

OPERATOR = "rosy-dev-operator"
SHOTS = Path(os.environ.get("ROSY_SHOT_DIR", "X:/DevTemp/calibration-mode"))


def _core_client(tmp_path):
    from fastapi.testclient import TestClient
    from core_api_web.api.app import create_app
    from core_common.profile import RobotProfile, robot_config_dir
    from core.services import CoreServices

    config_dir = SRC.parent / "contracts/foundation/config"
    config = yaml.safe_load((config_dir / "rosy_default.yaml").read_text(encoding="utf-8"))
    config["auth"] = {**config["auth"], **yaml.safe_load(
        (config_dir / "rosy_dev_auth.yaml").read_text(encoding="utf-8"))["auth"]}
    robot_dir = robot_config_dir("pinky_pro")
    profile = RobotProfile.load(robot_dir / "profile.yaml")
    capabilities = yaml.safe_load((robot_dir / "capabilities.yaml").read_text(encoding="utf-8"))
    services = CoreServices.build(config, profile, capabilities, tmp_path / "docks.json")
    return TestClient(create_app(config, services))


def _serve(client):
    def serve(route):
        request = route.request
        parts = urlsplit(request.url)
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        if request.method != "GET":
            route.fulfill(status=501, content_type="application/json",
                          body='{"detail":"fixture blocks writes"}')
            return
        response = client.get(path, headers={"Authorization": f"Bearer {OPERATOR}"})
        route.fulfill(status=response.status_code, headers={
            "content-type": response.headers.get("content-type", "application/octet-stream"),
            "cache-control": "no-store",
        }, body=response.content)
    return serve


def test_console_robot_card_and_dashboard_hero_show_the_calibration_chip(tmp_path):
    from playwright.sync_api import sync_playwright

    client = _core_client(tmp_path)
    headers = {"Authorization": f"Bearer {OPERATOR}"}
    SHOTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1366, "height": 768})
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script("sessionStorage.setItem('rosy.dashboard.token', 'rosy-dev-operator')")
        page.route("**/*", _serve(client))

        page.goto("http://rosy.test/console", wait_until="domcontentloaded")
        page.wait_for_selector('[data-panel="console.overview"] dl.ui-readout dd')
        assert page.locator("[data-calibration-chip]").count() == 0

        opened = client.post("/api/v1/calibration/session", headers=headers,
                             json={"kind": "drive", "label": "주행 보정", "ttl_s": 300})
        assert opened.status_code == 201
        chip = page.locator('[data-panel="console.overview"] ui-tag[data-calibration-chip]')
        chip.wait_for(timeout=5_000)
        assert chip.inner_text() == "보정 중 — 주행 보정"
        assert chip.get_attribute("status") == "warn"
        page.screenshot(path=str(SHOTS / "dashboard-console-calibration-chip.png"))

        page.goto("http://rosy.test/dashboard", wait_until="domcontentloaded")
        hero = page.locator("#calibration-chip")
        page.wait_for_function(
            "document.querySelector('#calibration-chip')?.hidden === false", timeout=10_000)
        assert hero.inner_text() == "보정 중 — 주행 보정"
        page.screenshot(path=str(SHOTS / "dashboard-hero-calibration-chip.png"))

        session_id = opened.json()["session"]["id"]
        assert client.delete(f"/api/v1/calibration/session/{session_id}",
                             headers=headers).status_code == 200
        page.wait_for_function(
            "document.querySelector('#calibration-chip')?.hidden === true", timeout=10_000)
        browser.close()
    assert errors == [], errors
