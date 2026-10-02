"""Rendered tablet path from pairing through one bounded simulated jog."""

import socket
import threading
from pathlib import Path

import pytest
import uvicorn

playwright = pytest.importorskip("playwright.sync_api")

from omx_adapter.pilot_sim_api import create_pilot_sim_app


ROOT = Path(__file__).resolve().parents[5]


class Runtime:
    instance_id = "sim-1"
    joint_names = ("joint1", "gripper_joint_1")
    gripper = "gripper_joint_1"
    camera_available = False

    def __init__(self):
        self.jogs = []

    def snapshot(self):
        return {"instance_id": self.instance_id, "ready": True, "owner_state": "ready",
                "state_sequence": 8, "joint_age_ms": 10,
                "positions": {"joint1": 0.0, "gripper_joint_1": 0.0}, "active_goal": None}

    def submit(self, jog):
        self.jogs.append(jog)
        return {"command_id": jog.request_id, "state": "LOCAL_ACCEPTED"}

    def goal(self, command_id):
        return {"command_id": command_id, "state": "LOCAL_ACCEPTED"}

    def cancel(self, command_id):
        return {"command_id": command_id, "state": "CANCEL_REQUESTED"}

    def cancel_active(self):
        pass

    def on_watchdog(self):
        pass

    def controls(self):
        return {"schema": "rosy.controls/1", "items": []}


def test_sim_pilot_pair_and_jog_rendered():
    runtime = Runtime()
    app = create_pilot_sim_app(runtime=runtime, pilot_root=ROOT / "src/hmi/pilot",
                               common_root=ROOT / "src/hmi/web_common", pairing_code="ABCD-EFGH")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            thread.join(0.05)
        assert server.started
        with playwright.sync_playwright() as engine:
            browser = engine.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1200, "height": 800})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{port}/pilot")
                page.locator("[data-sim-code]").fill("ABCD-EFGH")
                page.locator("[data-sim-connect]").click()
                page.get_by_text("조작 가능").wait_for()
                assert page.locator("[data-estop]").is_hidden()
                page.locator("[data-sim-delta='0.02']").click()
                page.get_by_text("명령 LOCAL_ACCEPTED").wait_for()
                assert len(runtime.jogs) == 1
                assert runtime.jogs[0].joint == "joint1"
                assert runtime.jogs[0].delta_rad == 0.02
                assert errors == []
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
