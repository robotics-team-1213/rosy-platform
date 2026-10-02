"""D-411 B: arm joystick pure logic (arm-stick.js) — bounded goals, one at a time (D-390 §2)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1] / "arm-stick.js"


def _run_js(body):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is unavailable")
    script = f"""
import fs from 'node:fs';
const source = fs.readFileSync({json.dumps(str(MODULE))}, 'utf8');
const m = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
{body}
"""
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True,
                            text=True, encoding="utf-8", check=True)
    return json.loads(result.stdout)


def test_the_module_imports_nothing():
    source = MODULE.read_text(encoding="utf-8")
    assert "import " not in source and "fetch(" not in source and "document" not in source


def test_axes_from_offset_clamps_and_flips_y():
    out = _run_js("console.log(JSON.stringify([m.axesFromOffset(50, -50, 100), m.axesFromOffset(300, 0, 100)]))")
    assert out == [{"x": 0.5, "y": 0.5}, {"x": 1, "y": 0}]


def test_step_uses_the_dominant_axis_scaled_past_the_deadzone():
    out = _run_js("""
const map = {x: 'joint1', y: 'joint2'};
console.log(JSON.stringify([
  m.stepFor({x: 0.1, y: 0.05}, map, 0.05),
  m.stepFor({x: 1, y: 0.3}, map, 0.05),
  m.stepFor({x: 0.2, y: -1}, map, 0.05),
  m.stepFor({x: 0.575, y: 0}, map, 0.05),
]))""")
    assert out[0] is None
    assert out[1] == {"joint": "joint1", "delta": 0.05}
    assert out[2] == {"joint": "joint2", "delta": -0.05}
    assert out[3] == {"joint": "joint1", "delta": 0.025}


def test_step_without_a_mapped_axis_sends_nothing():
    out = _run_js("console.log(JSON.stringify([m.stepFor({x: 0, y: 1}, {x: 'joint1', y: ''}, 0.05),"
                  " m.stepFor({x: 1, y: 0}, {x: 'joint1'}, 0)]))")
    assert out == [None, None]


def test_jogger_sends_the_next_goal_only_after_the_previous_settles():
    out = _run_js("""
const sent = [];
const jog = m.createArmJogger({submit: async (step) => { sent.push(step); return true; },
                               mapping: {x: 'joint1', y: 'joint2'}, maxStep: 0.05});
jog.press({x: 1, y: 0});
await new Promise((r) => setTimeout(r, 0));
jog.move({x: 1, y: 0});
await new Promise((r) => setTimeout(r, 0));
const beforeSettle = sent.length;
jog.settled('SUCCEEDED');
await new Promise((r) => setTimeout(r, 0));
const afterSettle = sent.length;
const released = jog.release();
jog.settled('SUCCEEDED');
await new Promise((r) => setTimeout(r, 0));
console.log(JSON.stringify({beforeSettle, afterSettle, released, final: sent.length, state: jog.state()}));
""")
    assert out["beforeSettle"] == 1 and out["afterSettle"] == 2
    assert out["released"] == {"inFlight": True}
    assert out["final"] == 2 and out["state"] == {"pressed": False, "inFlight": False}


def test_a_failed_goal_stops_the_jogger_until_pressed_again():
    out = _run_js("""
const sent = [];
const jog = m.createArmJogger({submit: async (s) => { sent.push(s); return true; },
                               mapping: {x: 'joint1', y: 'joint2'}, maxStep: 0.05});
jog.press({x: 1, y: 0});
await new Promise((r) => setTimeout(r, 0));
jog.settled('UNKNOWN_HOLD');
await new Promise((r) => setTimeout(r, 0));
console.log(JSON.stringify({sent: sent.length, state: jog.state()}));
""")
    assert out == {"sent": 1, "state": {"pressed": False, "inFlight": False}}


def test_a_rejected_submit_stops_the_jogger():
    out = _run_js("""
const sent = [];
const jog = m.createArmJogger({submit: async (s) => { sent.push(s); throw new Error('409'); },
                               mapping: {x: 'joint1', y: 'joint2'}, maxStep: 0.05});
jog.press({x: 1, y: 0});
await new Promise((r) => setTimeout(r, 0));
jog.move({x: 1, y: 0});
await new Promise((r) => setTimeout(r, 0));
console.log(JSON.stringify({sent: sent.length, state: jog.state()}));
""")
    assert out == {"sent": 1, "state": {"pressed": False, "inFlight": False}}


def test_a_settle_for_another_command_is_ignored():
    out = _run_js("""
const sent = [];
const jog = m.createArmJogger({submit: async (s) => { sent.push(s); return `c${sent.length}`; },
                               mapping: {x: 'joint1', y: 'joint2'}, maxStep: 0.05});
jog.press({x: 1, y: 0});
await new Promise((r) => setTimeout(r, 0));
jog.settled('SUCCEEDED', 'button-goal');
await new Promise((r) => setTimeout(r, 0));
const ignored = sent.length;
jog.settled('SUCCEEDED', 'c1');
await new Promise((r) => setTimeout(r, 0));
console.log(JSON.stringify({ignored, after: sent.length, state: jog.state()}));
""")
    assert out == {"ignored": 1, "after": 2, "state": {"pressed": True, "inFlight": True}}
