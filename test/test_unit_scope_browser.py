"""D-960 §4 on a real loopback Fleet: a cell and 통합관제 R each show only what they own (synthetic robots)."""
from hashlib import sha256
import json
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import urlsplit

import pytest
import uvicorn

from browser_harness import browser_tests_enabled, launch_options, safe_listener

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in real Chromium scenario")
ROOT = Path(__file__).resolve().parents[1]
MANIFEST = {"revision": "scope-v1", "units": [
    {"id": "R", "resources": ["robot:r"]}, {"id": "ARM-CELL", "parent": "R", "resources": ["workcell:arm_a"]}]}


@pytest.fixture
def unit_fleet(tmp_path, request):
    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole
    from fleet.server.task_service import FleetTaskService
    from fleet.server.task_store import FleetTaskStore
    from fleet.swarm.robots import RobotEndpoint
    from operations.fleet.test.fakes import FakeRobot

    unit, neighbor = request.param
    token = secrets.token_urlsafe(24)
    (tmp_path / "peer.token").write_text("peer-service-" + secrets.token_urlsafe(12), encoding="utf-8")
    robots = [("r", FakeRobot("r"))] if unit == "R" else []
    console = FleetConsole([RobotEndpoint(rid, "http://robot.invalid", "synthetic-device-token") for rid, _ in robots],
                           [robot for _, robot in robots])
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids=console.robot_ids)
    config = tmp_path / "control-unit.json"
    config.write_text(json.dumps({"unit_id": unit, "manifest": MANIFEST,
        "peers": {neighbor: {"url": "http://peer.invalid:8080", "token_file": "peer.token"}}}), encoding="utf-8")
    users = {sha256(token.encode()).hexdigest(): {"principal_id": "named-loopback-operator", "role": "operator"},
             sha256(b"neighbor-inbound").hexdigest(): {"principal_id": "control-unit:" + neighbor, "role": "service"}}
    app = create_app(console, task_service=tasks, control_unit_config=config, site_users=users,
                     start_task_dispatcher=False, omx_instances={}, web_common=ROOT / "shared/web")
    listener = safe_listener()
    origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False,
                                           proxy_headers=False, timeout_graceful_shutdown=3, log_config=None))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        yield unit, origin, token
    finally:
        server.should_exit = True
        worker.join(15)
        listener.close()


@pytest.mark.parametrize("unit_fleet", [("ARM-CELL", "R"), ("R", "ARM-CELL")], indirect=True, ids=["cell", "root"])
def test_each_unit_screen_shows_only_its_own_jobs(unit_fleet):
    from playwright.sync_api import expect, sync_playwright

    unit, origin, token = unit_fleet
    cell = unit == "ARM-CELL"
    with sync_playwright() as playwright:
        options = launch_options()
        options["args"] = [f"--explicitly-allowed-ports={urlsplit(origin).port}"]
        browser = playwright.chromium.launch(**options)
        try:
            page = browser.new_page(viewport={"width": 1366, "height": 900})
            page.set_default_timeout(15000)
            page.add_init_script("sessionStorage.setItem('rosy-console-token', " + json.dumps(token) + ");")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(origin + "/console")
            expect(page.locator("#fleet-name")).to_have_text("ARM-CELL" if cell else "통합관제 R")
            expect(page.locator("#fleet-name")).to_have_attribute(
                "title", "셀 관제 · 맡은 일: 팔 셀" if cell else "통합관제 · 맡은 일: 주행 로봇, 하위 관제")
            expect(page.locator("#estop")).to_be_visible()  # every unit keeps its E-stop
            for block in ("#charge-bays-fold", ".formation"):  # Pinky jobs belong to R (D-960 §2)
                (expect(page.locator(block)).to_be_hidden if cell else expect(page.locator(block)).to_be_attached)()

            page.goto(origin + "/console/cell")
            expect(page.locator("#estop")).to_be_visible()
            if cell:
                expect(page.locator("#cell-main")).to_be_visible()
                expect(page.locator("#cell-unit-note")).to_be_hidden()
            else:
                expect(page.locator("#cell-unit-note")).to_be_visible()
                expect(page.locator("#cell-main")).to_be_hidden()

            page.goto(origin + "/console/install")
            expect(page.locator("#robot-enrollment")).to_be_hidden()  # a manifest fixes the roster on both
            assert errors == [], errors
        finally:
            browser.close()
