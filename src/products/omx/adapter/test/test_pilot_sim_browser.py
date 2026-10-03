"""Rendered tablet path from pairing through bounded simulated jogs."""

import contextlib
import socket
import threading
import time
import uuid
from pathlib import Path

import pytest
import uvicorn

playwright = pytest.importorskip("playwright.sync_api")

from omx_adapter.pilot_sim_api import create_pilot_sim_app


ROOT = Path(__file__).resolve().parents[5]


class Runtime:
    """Behaves like PilotSimRuntime: while a goal executes the owner is "active" and the
    snapshot is not ready; a goal needs a sequence a ready snapshot served; one goal at a time.
    ``settle_s=None`` keeps every goal running (LOCAL_ACCEPTED) forever."""

    instance_id = "sim-1"
    joint_names = ("joint1", "gripper_joint_1")
    gripper = "gripper_joint_1"
    camera_available = False

    def __init__(self, settle_s=None, gripper_mode=False):
        self.settle_s = settle_s
        self.gripper_mode = gripper_mode    # D-411 C server: absolute gripper goals, gripper readback
        self.gripper_goals = []
        self.gripper_state = None           # test override of the derived state
        self.jogs = []
        self.refused = []
        self.sequence = 8
        self.served = set()
        self.started = {}
        self.positions = {"joint1": 0.0, "gripper_joint_1": 0.0}

    def _state(self, command_id):
        if self.settle_s is not None and time.monotonic() - self.started[command_id] >= self.settle_s:
            return "SUCCEEDED"
        return "LOCAL_ACCEPTED"

    def _running(self):
        return bool(self.jogs) and self._state(self.jogs[-1].request_id) != "SUCCEEDED"

    def snapshot(self):
        running = self._running()
        self.sequence += 1
        if not running:
            self.served.add(self.sequence)
        snapshot = {"instance_id": self.instance_id, "ready": not running,
                    "owner_state": "active" if running else "ready",
                    "state_sequence": self.sequence, "joint_age_ms": 10, "positions": dict(self.positions),
                    "active_goal": self.jogs[-1].request_id if running else None}
        if self.gripper_mode:
            position = self.positions[self.gripper]
            gripping = running and self.gripper_goals and self.jogs[-1] is self.gripper_goals[-1]
            snapshot["gripper"] = {"joint": self.gripper, "position": position, "open": 1.0, "closed": 0.0,
                                   "state": self.gripper_state or ("moving" if gripping else
                                                                   "closed" if abs(position) <= 0.05 else "open")}
        return snapshot

    def submit(self, jog):
        reason = ("goal_active" if self._running()
                  else "readback_not_recently_served" if jog.state_sequence not in self.served else "")
        if reason:
            self.refused.append(reason)
            return {"command_id": jog.request_id, "state": "REJECTED", "reason": reason}
        self.jogs.append(jog)
        self.started[jog.request_id] = time.monotonic()
        self.positions[jog.joint] += jog.delta_rad
        return {"command_id": jog.request_id, "state": "LOCAL_ACCEPTED"}

    def submit_gripper(self, goal):
        # Same owner rules as a jog: one goal at a time, a freshly served ready sequence.
        reason = ("goal_active" if self._running()
                  else "readback_not_recently_served" if goal.state_sequence not in self.served
                  else "gripper_limit" if not -0.1 <= goal.position <= 1.1 else "")
        if reason:
            self.refused.append(reason)
            return {"command_id": goal.request_id, "state": "REJECTED", "reason": reason}
        self.gripper_goals.append(goal)
        self.jogs.append(goal)
        self.started[goal.request_id] = time.monotonic()
        self.positions[self.gripper] = goal.position
        return {"command_id": goal.request_id, "state": "LOCAL_ACCEPTED"}

    def goal(self, command_id):
        state = self._state(command_id)
        # A ROS-stage receipt carries the ROS goal id (OmxSimGoal validation).
        return {"command_id": command_id, "state": state,
                **({"ros_goal_id": str(uuid.uuid5(uuid.NAMESPACE_URL, command_id))} if state == "SUCCEEDED" else {})}

    def cancel(self, command_id):
        return {"command_id": command_id, "state": "CANCEL_REQUESTED"}

    def cancel_active(self):
        pass

    def on_watchdog(self):
        pass

    def controls(self):
        if self.gripper_mode:
            return {"schema": "rosy.controls/1", "items": [
                {"id": "arm", "kind": "joint_jog", "label": "팔", "max_step_rad": 0.05, "duration_s": 0.4,
                 "command": "bounded_goal", "joints": [{"name": "joint1", "lower": -1.0, "upper": 1.0}]},
                {"id": "gripper", "kind": "gripper", "label": "그리퍼", "joint": self.gripper, "closed": 0.0,
                 "open": 1.0, "unit": "rad", "presets": {"open": 1.0, "half": 0.5, "close": 0.0},
                 "readback": ["position", "grasp"], "max_velocity": 0.5}]}
        # D-411 B: the screen draws what the target announces (an empty list = no controls).
        return {"schema": "rosy.controls/1", "items": [{
            "id": "arm", "kind": "joint_jog", "label": "팔", "max_step_rad": 0.05, "duration_s": 0.4,
            "command": "bounded_goal", "joints": [{"name": "joint1", "lower": -1.0, "upper": 1.0},
                                                  {"name": "gripper_joint_1", "lower": -0.01, "upper": 0.019}]}]}


@contextlib.contextmanager
def _paired_page(runtime):
    app = create_pilot_sim_app(runtime=runtime, pilot_root=ROOT / "middleware/ui/pilot",
                               common_root=ROOT / "shared/web", pairing_code="ABCD-EFGH")
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
                yield page, errors
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_sim_pilot_pair_and_jog_rendered():
    runtime = Runtime()
    with _paired_page(runtime) as (page, errors):
        assert page.locator("[data-estop]").is_hidden()
        page.locator("[data-sim-delta='0.02']").click()
        page.get_by_text("명령 LOCAL_ACCEPTED").wait_for()
        assert len(runtime.jogs) == 1
        assert runtime.jogs[0].joint == "joint1"
        assert runtime.jogs[0].delta_rad == 0.02
        assert runtime.jogs[0].duration_s == 0.4
        assert page.locator("[data-arm-pad]").is_visible()
        assert errors == []


def test_sim_stick_held_sends_sequential_goals_through_the_real_api():
    """Review C1 over the real SIM HTTP API: busy owner ≠ blocked; fresh ready sequence each goal."""
    runtime = Runtime(settle_s=0.3)
    with _paired_page(runtime) as (page, errors):
        box = page.locator("[data-arm-pad]").bounding_box()
        page.mouse.move(box["x"] + box["width"] - 2, box["y"] + box["height"] / 2)
        page.mouse.down()
        page.wait_for_timeout(2600)
        page.mouse.up()
        sent = len(runtime.jogs)
        page.wait_for_timeout(800)
        assert sent >= 3, sent
        assert len(runtime.jogs) == sent
        assert runtime.refused == []
        assert {jog.joint for jog in runtime.jogs} == {"joint1"}
        assert all(0 < jog.delta_rad <= 0.05 for jog in runtime.jogs)
        assert errors == []


def test_sim_gripper_presets_slider_and_badge_through_the_real_api():
    """D-411 C over the real SIM HTTP API: POST /gripper, one goal at a time, grasp badge."""
    expect = playwright.expect
    runtime = Runtime(settle_s=0.3, gripper_mode=True)
    with _paired_page(runtime) as (page, errors):
        badge = page.locator("[data-gripper-state]")
        slider = page.locator("[data-gripper-percent]")
        expect(badge).to_have_text("닫힘")
        assert page.locator("[data-sim-joint] option").all_inner_texts() == ["joint1"]
        page.click("[data-gripper-preset='half']")
        expect(badge).to_have_text("열림")
        assert [goal.position for goal in runtime.gripper_goals] == [0.5]
        assert runtime.gripper_goals[0].duration_s == 1.12
        expect(slider).to_be_enabled()
        slider.evaluate("""(s) => { s.value = '100'; s.dispatchEvent(new Event('input', {bubbles: true}));
          s.dispatchEvent(new Event('change', {bubbles: true})); }""")
        expect(slider).to_have_value("100")
        expect(page.locator("[data-gripper-preset='close']")).to_be_enabled()
        assert [goal.position for goal in runtime.gripper_goals] == [0.5, 1.0]
        page.click("[data-gripper-preset='close']")
        expect(slider).to_have_value("10")     # a full stroke needs > 2.0 s at 0.9 x 0.5 rad/s: 0.9 rad first
        expect(page.locator("[data-gripper-preset='close']")).to_be_enabled()
        page.click("[data-gripper-preset='close']")
        expect(slider).to_have_value("0")
        expect(slider).to_be_enabled()
        runtime.gripper_state = "holding"
        expect(badge).to_have_text("쥐고 있음")
        assert [goal.position for goal in runtime.gripper_goals] == [0.5, 1.0, 0.1, 0.0]
        assert runtime.refused == []
        assert errors == [], errors
