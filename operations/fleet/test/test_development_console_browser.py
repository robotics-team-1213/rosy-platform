"""Direct entry to every Fleet console page in development mode, using real Chromium."""

import os
import re
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from browser_harness import browser_tests_enabled, safe_listener

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.development_session import DevelopmentSessions
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint


pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in Chromium scenario")
ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("path, identity", [
    ("/console", "#user-role"),
    ("/console/install", "#user-role"),
    ("/console/site-map", "#user-role"),
    ("/console/cell", "#user-role"),
])
def test_direct_development_entry_needs_no_operator_token(tmp_path, path, identity):
    from playwright.sync_api import expect, sync_playwright

    robot = FakeRobot("rosy_01")
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "robot-only")], [robot])
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids=console.robot_ids)
    app = create_app(console, console_token="registry-only", task_service=tasks,
                     development_sessions=DevelopmentSessions(), web_common=ROOT / "shared" / "web",
                     start_task_dispatcher=False)
    listener = safe_listener()
    origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", timeout_graceful_shutdown=3))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 20
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 390, "height": 844} if path == "/console" else None)
                if path == "/console":
                    page.route("**/api/fleet/site-map", lambda route: route.fulfill(json={"maps": [{
                        "map_id": "site", "bounds_m": {"min_x": 0, "max_x": 2, "min_y": 0, "max_y": 2},
                        "polygon_m": [[0, 0], [2, 0], [2, 2], [0, 2]], "sources": [],
                    }]}))
                    # A slow robot map must not leave the authenticated site view locked.
                    page.route("**/api/fleet/map", lambda route: None)
                    page.route("**/api/fleet/tracking", lambda route: route.fulfill(json={
                        "lease_s": 1, "sources": [{"source_id": "camera", "status": "OK", "age_ms": 50}],
                        "robots": [{"robot_id": "rosy_01", "status": "MARKER",
                                    "camera": {"x": 1, "y": 1}, "pose": None}], "unknown": [],
                    }))
                page.goto(origin + path)
                # D-540 2: the development principal id lives in title; the badge says development once.
                expect(page.locator(identity)).to_have_attribute("title", re.compile("^development-"), timeout=15000)
                expect(page.locator(identity)).to_have_text("운영자")
                expect(page.locator("#development-badge")).to_be_visible()
                expect(page.locator("#estop")).to_be_enabled()
                assert page.evaluate("sessionStorage.getItem('rosy-console-token')")
                expect(page.locator("#console-token")).to_be_hidden()
                if path == "/console":
                    expect(page.locator("#topbar-more")).to_have_attribute("aria-expanded", "false")
                    expect(page.locator("#topbar-extra")).to_be_hidden()
                    expect(page.locator("#connection-guide")).to_be_hidden()
                    expect(page.locator("#map-stage")).to_have_attribute("data-map-state", "site", timeout=10000)
                    expect(page.locator("#map-canvas")).to_have_attribute("role", "img")
                    expect(page.locator("#map-tag")).to_contain_text("카메라 관측 1/1대", timeout=10000)
                    assert page.locator("ui-topbar").bounding_box()["height"] < 170
                    output = os.environ.get("ROSY_UX_EVIDENCE_DIR")
                    if output:
                        target = Path(output)
                        target.mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=str(target / "fleet-dev-menu-390x844.png"))
                        page.set_viewport_size({"width": 1440, "height": 900})
                        page.screenshot(path=str(target / "fleet-dev-menu-1440x900.png"))
                        page.set_viewport_size({"width": 390, "height": 844})
                    page.locator("#topbar-more").click()
                    expect(page.locator("#topbar-extra")).to_be_visible()
            finally:
                browser.close()
    finally:
        server.should_exit = True
        worker.join(timeout=20)
        listener.close()
        assert not worker.is_alive()
