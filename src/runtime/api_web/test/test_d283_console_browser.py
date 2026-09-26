"""G2 browser evidence through the real FastAPI app and CoreServices fixture."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright
import yaml


pytestmark = pytest.mark.skipif(
    os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
    reason="set ROSY_RUN_BROWSER_TESTS=1 to run the optional real-CORE Chromium review",
)


TOKENS = {
    "administrator": "rosy-dev-admin",
    "operator": "rosy-dev-operator",
}


def _core_client(tmp_path):
    from fastapi.testclient import TestClient
    from core_api_web.api.app import create_app
    from core_common.profile import RobotProfile, robot_config_dir
    from core.services import CoreServices

    root = Path(__file__).resolve().parents[4]
    config_dir = root / "src" / "runtime" / "gateway" / "config"
    config = yaml.safe_load((config_dir / "rosy_default.yaml").read_text(encoding="utf-8"))
    config["auth"] = {**config["auth"], **yaml.safe_load(
        (config_dir / "rosy_dev_auth.yaml").read_text(encoding="utf-8"))['auth']}
    robot_dir = robot_config_dir("pinky_pro")
    profile = RobotProfile.load(robot_dir / "profile.yaml")
    capabilities = yaml.safe_load((robot_dir / "capabilities.yaml").read_text(encoding="utf-8"))
    services = CoreServices.build(config, profile, capabilities, tmp_path / "docks.json")
    return TestClient(create_app(config, services))


def _capture(page, path: Path, token: str, width: int, height: int):
    page.set_viewport_size({"width": width, "height": height})
    page.add_init_script(f"sessionStorage.setItem('rosy.dashboard.token', {token!r})")
    page.goto("http://rosy.test/console")
    page.wait_for_selector("#action-tab-drive", timeout=20_000)
    page.wait_for_timeout(1_200)
    path.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(path), full_page=False)
    return page.evaluate("""() => {
      const rect = (selector) => {
        const node = document.querySelector(selector);
        if (!node) return null;
        const {x, y, right, bottom, width, height} = node.getBoundingClientRect();
        return {x, y, right, bottom, width, height};
      };
      const act = document.querySelector('[data-slot="act"]');
      const active = document.querySelector('.action-group-panel:not([hidden])');
      return {
        viewport: {width: innerWidth, height: innerHeight},
        document: {width: document.documentElement.scrollWidth, height: document.documentElement.scrollHeight},
        body: {width: document.body.scrollWidth, height: document.body.scrollHeight},
        eStop: rect('#shell-estop'), topbar: rect('ui-topbar'),
        sense: rect('[data-slot="sense"]'), observe: rect('[data-slot="observe"]'), act: rect('[data-slot="act"]'),
        actionPanel: active ? {
          box: (() => { const {x,y,right,bottom,width,height}=active.getBoundingClientRect(); return {x,y,right,bottom,width,height}; })(),
          scrollHeight: active.scrollHeight, clientHeight: active.clientHeight,
          sections: [...active.querySelectorAll('ui-section')].map((node) => {
            const {x,y,right,bottom,width,height}=node.getBoundingClientRect(); return {id:node.dataset.panel,x,y,right,bottom,width,height};
          }),
        } : null,
        observeSections: [...document.querySelectorAll('[data-slot="observe"] > ui-section')].map((node) => {
          const {bottom}=node.getBoundingClientRect(); return {title:node.getAttribute('aria-label'),bottom};
        }),
        actionGroups: [...document.querySelectorAll('[role="tab"]')].map((node) => ({name:node.textContent, selected:node.getAttribute('aria-selected')})),
        horizontalOverflow: document.documentElement.scrollWidth - innerWidth,
        verticalOverflow: document.documentElement.scrollHeight - innerHeight,
      };
    }""")


def test_real_core_console_fits_desktop_and_mobile_for_operator_and_administrator(tmp_path):
    client = _core_client(tmp_path)
    capture_dir = Path("X:/DevTemp/d283-console-core-browser")
    browser_errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for role, token in TOKENS.items():
            context = browser.new_context(viewport={"width": 1366, "height": 768})
            page = context.new_page()
            page.on("pageerror", lambda error: browser_errors.append(str(error)))

            def serve(route):
                request = route.request
                response = client.get(urlsplit(request.url).path, headers={"Authorization": f"Bearer {token}"})
                route.fulfill(status=response.status_code, headers={
                    "content-type": response.headers.get("content-type", "application/octet-stream"),
                    "cache-control": "no-store",
                }, body=response.content)

            page.route("**/*", serve)
            desktop = _capture(page, capture_dir / f"{role}-1366x768.png", token, 1366, 768)
            assert desktop["document"]["height"] == 768, desktop
            assert desktop["body"]["height"] == 768, desktop
            assert desktop["actionGroups"][0] == {"name": "운전", "selected": "true"}, desktop
            assert desktop["observe"]["right"] <= desktop["act"]["x"], desktop
            assert desktop["sense"]["x"] < desktop["observe"]["x"] < desktop["act"]["x"], desktop
            assert desktop["eStop"]["y"] >= 0 and desktop["eStop"]["bottom"] <= 768, desktop
            assert desktop["actionPanel"]["box"]["bottom"] <= desktop["act"]["bottom"], desktop
            assert desktop["actionPanel"]["scrollHeight"] <= desktop["actionPanel"]["clientHeight"], desktop
            assert all(section["bottom"] <= desktop["act"]["bottom"] for section in desktop["actionPanel"]["sections"]), desktop
            assert all(section["bottom"] <= desktop["observe"]["bottom"] for section in desktop["observeSections"]), desktop

            mobile = _capture(page, capture_dir / f"{role}-390x844.png", token, 390, 844)
            assert mobile["horizontalOverflow"] == 0, mobile
            assert mobile["eStop"]["bottom"] <= 844, mobile
            assert mobile["actionGroups"][0] == {"name": "운전", "selected": "true"}, mobile
            assert browser_errors == [], browser_errors
            context.close()
        browser.close()
