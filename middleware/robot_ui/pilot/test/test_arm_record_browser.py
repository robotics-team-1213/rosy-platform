"""OMX SIM demonstration flow: start pose, task, recording, outcome buttons and the sensor table."""
import os
from pathlib import Path

import pytest
from browser_harness import browser_tests_enabled

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")

MOUNT = """async () => {
  const {mountArm} = await import('/pilot/assets/screens/arm.js');
  const root = document.createElement('main'); root.dataset.screen = 'arm'; document.body.replaceChildren(root);
  window.pos = {joint1: 0, joint2: 0.2, gripper: 0.5}; window.sent = []; window.outcome = null;
  window.recordState = {status: 'idle', frame_count: 0, issues: []};
  const ranges = [{name: 'joint1', lower: -1.5, upper: 1.5}, {name: 'joint2', lower: -1.5, upper: 1.5}];
  const driver = {request: async (path, options = {}) => {
    if (path === '/pair') return {token: 'test-only'};
    if (path === '/whoami') return {role: 'operator'};
    if (path === '/seat') return {seat_id: 'seat-test'};
    if (options.method === 'DELETE' || path.startsWith('/seat/')) return {};
    if (path === '/state') return {ready: true, owner_state: 'ready', state_sequence: window.sent.length + 1,
      positions: {...window.pos}, joint_age_ms: 40,
      gripper: {joint: 'gripper', position: window.pos.gripper, open: 1, closed: 0, state: 'open'}};
    if (path === '/goals' && options.method === 'POST') {
      const goal = JSON.parse(options.body);
      window.sent.push(goal.delta_rad);
      window.pos[goal.joint] = Math.round((window.pos[goal.joint] + goal.delta_rad) * 1e4) / 1e4;
      return {command_id: `c${window.sent.length}`, state: 'RUNNING', ros_goal_id: null};
    }
    if (path.startsWith('/goals/')) return {state: 'SUCCEEDED'};
    if (path === '/camera') return {fresh: true, age_ms: 10};
    if (path === '/camera/frame') return new Blob([], {type: 'image/jpeg'});
    if (path === '/recordings' && options.method === 'POST') {
      window.task = JSON.parse(options.body).task;
      window.recordState = {status: 'recording', episode_id: 'episode-test', frame_count: 3, issues: []};
    }
    if (path.endsWith('/stop')) {
      window.outcome = JSON.parse(options.body).outcome;
      window.recordState = {...window.recordState, status: 'complete', task_outcome: window.outcome};
    }
    return window.recordState;
  }};
  window.disposeArm = mountArm(root, {instance_id: 'sim-test', joints: ['joint1', 'joint2'], gripper: 'gripper',
    camera: true, recording: true, controls: {schema: 'rosy.controls/1', items: [{id: 'arm', kind: 'joint_jog',
    label: '팔', joints: ranges, max_step_rad: 0.05, duration_s: 0.4, command: 'bounded_goal'}]},
    ...(window.extraTarget ?? {})}, driver);
}"""


def text(page, selector):
    return page.locator(selector).inner_text()


def test_start_pose_task_recording_and_failure_case_flow(tablet_page):
    base_url, page, errors = tablet_page
    page.goto(f"{base_url}/pilot")
    page.evaluate("localStorage.clear(); sessionStorage.clear()")
    page.evaluate(MOUNT)
    page.fill("[data-sim-code]", "test-only")
    page.click("[data-sim-connect]")

    # Sensor values: one row per arm joint plus the gripper, each with a range bar.
    page.wait_for_function("document.querySelectorAll('[data-sim-sensors] tr').length === 3")
    assert "11.5°" in text(page, "[data-sim-sensors]") and "열림 50%" in text(page, "[data-sim-sensors]")
    assert page.locator("[data-sim-sensors] meter").count() == 3
    assert text(page, "[data-sim-sensor-age]").startswith("수신 중")

    # Start pose: save here, move away, then return in bounded steps of at most max_step_rad.
    assert page.locator("[data-sim-home-go]").evaluate("b => b.disabled")
    page.click("[data-sim-home-save]")
    page.wait_for_function("document.querySelector('[data-sim-home-status]').textContent.includes('시작 자세에 있습니다')")
    page.evaluate("window.pos.joint1 = 0.3")
    page.wait_for_function("document.querySelector('[data-sim-home-status]').textContent.includes('시작 자세와 다릅니다')")
    page.click("[data-sim-home-go]")
    page.wait_for_function("document.querySelector('[data-sim-home-status]').textContent === '시작 자세에 있습니다'",
                           timeout=20_000)
    sent = page.evaluate("window.sent")
    assert len(sent) == 6 and all(abs(delta) <= 0.05 for delta in sent), sent
    assert page.locator("[data-sim-step='home']").get_attribute("data-state") == "done"

    # Task first: recording stays off until the task is written, and the text is kept for the next try.
    start = page.locator("[data-sim-record-start]")
    assert start.evaluate("b => b.disabled") and start.get_attribute("reason") == "과제 설명을 먼저 적으세요"
    page.fill("[data-sim-task]", "파란 상자를 벨트 표시 안에 놓기")
    page.wait_for_function("!document.querySelector('[data-sim-record-start]').disabled")
    assert page.evaluate("sessionStorage.getItem(`rosy.pilot.omx-sim.task.${location.origin}`)") == "파란 상자를 벨트 표시 안에 놓기"
    start.click()
    page.wait_for_function("document.querySelector('[data-sim-record-status]').dataset.state === 'recording'")
    assert text(page, "[data-sim-record-status]").startswith("● 녹화 중 · 00:0")
    assert page.locator("[data-sim-home-go]").get_attribute("reason") == "녹화 중에는 이동하지 않습니다"
    # The stop card is pinned in view while recording, even scrolled to the stick at the top.
    page.evaluate("window.scrollTo(0, 0)")
    box = page.locator("[data-sim-record-stop='failure']").bounding_box()
    assert box and box["y"] + box["height"] <= page.viewport_size["height"], box
    assert text(page, "[data-sim-record-live]").startswith("● 녹화 중")
    if os.environ.get("ROSY_SHOT_DIR"):
        shots = Path(os.environ["ROSY_SHOT_DIR"])
        shots.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(shots / "pilot-arm-record-flow-2000x1200.png"), full_page=True)

    # Stopping names the outcome in one press: here the try is kept as a failure case.
    page.click("[data-sim-record-stop='failure']")
    page.wait_for_function("window.outcome === 'failure'")
    page.wait_for_function("!document.querySelector('[data-sim-record-last]').hidden")
    assert "실패 사례" in text(page, "[data-sim-record-last]") and window_task(page) == "파란 상자를 벨트 표시 안에 놓기"
    assert page.locator("[data-sim-record-stop='success']").evaluate("b => b.disabled")
    assert page.locator("[data-sim-step='stop']").evaluate("li => getComputedStyle(li).position") == "static"

    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth") <= 390
    page.evaluate("window.disposeArm()")
    assert errors == [], errors


def window_task(page):
    return page.evaluate("window.task")


def test_profile_start_pose_and_task_need_no_tablet_setup(tablet_page):
    base_url, page, errors = tablet_page
    page.goto(f"{base_url}/pilot")
    page.evaluate("localStorage.clear(); sessionStorage.clear();"
                  "window.extraTarget = {start_pose: {joint1: 0.1, joint2: 0.2}, task: '프로파일 과제'}")
    page.evaluate(MOUNT)
    page.fill("[data-sim-code]", "test-only")
    page.click("[data-sim-connect]")
    page.wait_for_function("document.querySelector('[data-sim-home-status]').textContent.includes('시작 자세와 다릅니다')")
    assert page.locator("[data-sim-home-save]").is_hidden() and page.locator("[data-sim-home-source]").is_visible()
    assert page.input_value("[data-sim-task]") == "프로파일 과제"
    page.wait_for_function("document.querySelector(\"[data-sim-step='task']\").dataset.state === 'done'")
    page.click("[data-sim-home-go]")
    page.wait_for_function("document.querySelector('[data-sim-home-status]').textContent === '시작 자세에 있습니다'",
                           timeout=20_000)
    assert page.evaluate("window.sent") == [0.05, 0.05]
    assert page.evaluate("Object.keys(localStorage).filter((key) => key.includes('home'))") == []
    page.evaluate("window.disposeArm()")
    assert errors == [], errors
