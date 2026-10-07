"""Direct entry to every Fleet console page in development mode, using real Chromium."""

import os
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.development_session import DevelopmentSessions
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint


pytestmark = pytest.mark.skipif(os.environ.get("ROSY_BROWSER_TESTS") != "1", reason="opt-in Chromium scenario")
ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("path, identity", [
    ("/console", "#user-role"),
    ("/console/install", "#user-role"),
    ("/console/site-map", "#session"),
    ("/console/cell", "#session"),
])
def test_direct_development_entry_needs_no_operator_token(tmp_path, path, identity):
    from playwright.sync_api import expect, sync_playwright

    robot = FakeRobot("rosy_01")
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "robot-only")], [robot])
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids=console.robot_ids)
    app = create_app(console, console_token="registry-only", task_service=tasks,
                     development_sessions=DevelopmentSessions(), web_common=ROOT / "shared" / "web",
                     start_task_dispatcher=False)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
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
                page = browser.new_page()
                page.goto(origin + path)
                expect(page.locator(identity)).to_contain_text("development-", timeout=15000)
                assert page.evaluate("sessionStorage.getItem('rosy-console-token')")
                credential = "#credential" if path in {"/console/site-map", "/console/cell"} else "#console-token"
                expect(page.locator(credential)).to_be_hidden()
            finally:
                browser.close()
    finally:
        server.should_exit = True
        worker.join(timeout=20)
        listener.close()
        assert not worker.is_alive()
