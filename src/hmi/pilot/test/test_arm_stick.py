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


def test_limit_step_clamps_to_the_room_left_in_the_joint_range():
    out = _run_js("""
const r = {lower: -1, upper: 1};
console.log(JSON.stringify([
  m.limitStep({joint: 'j', delta: 0.05}, r, 0.98),
  m.limitStep({joint: 'j', delta: -0.05}, r, -0.97),
  m.limitStep({joint: 'j', delta: 0.05}, r, 0.9995),
  m.limitStep({joint: 'j', delta: 0.05}, r, 1.2),
  m.limitStep({joint: 'j', delta: -0.05}, r, 1.2),
  m.limitStep({joint: 'j', delta: 0.05}, {lower: null, upper: null}, 5),
  m.limitStep({joint: 'j', delta: 0.05}, r, undefined),
  m.limitStep(null, r, 0),
]))""")
    assert out[0] == {"joint": "j", "delta": 0.02}
    assert out[1] == {"joint": "j", "delta": -0.03}
    assert out[2] is None and out[3] is None          # at/past the limit: nothing toward it
    assert out[4] == {"joint": "j", "delta": -0.05}   # away from the limit is still allowed
    assert out[5] == {"joint": "j", "delta": 0.05} and out[6] == {"joint": "j", "delta": 0.05}
    assert out[7] is None


def test_jogger_stops_at_the_joint_limit_instead_of_sending_a_refused_goal():
    out = _run_js("""
const sent = []; const pos = {joint1: 0.99};
const jog = m.createArmJogger({submit: async (s) => { sent.push(s); return `c${sent.length}`; },
  mapping: {x: 'joint1', y: 'joint2'}, maxStep: 0.05, limits: {joint1: {lower: -1, upper: 1}},
  positionOf: (name) => pos[name]});
jog.press({x: 1, y: 0});
await new Promise((r) => setTimeout(r, 0));
pos.joint1 = 1.0;
jog.settled('SUCCEEDED', 'c1');
await new Promise((r) => setTimeout(r, 0));
console.log(JSON.stringify({deltas: sent.map((s) => s.delta), atLimit: jog.atLimit(), state: jog.state()}));
""")
    assert out == {"deltas": [0.01], "atLimit": True, "state": {"pressed": True, "inFlight": False}}


def test_not_now_keeps_the_stick_pressed_and_poke_retries():
    out = _run_js("""
const sent = []; let ready = false;
const jog = m.createArmJogger({submit: async (s) => { if (!ready) return null; sent.push(s); return 'c1'; },
  mapping: {x: 'joint1', y: 'joint2'}, maxStep: 0.05});
jog.press({x: 1, y: 0});
await new Promise((r) => setTimeout(r, 0));
const waiting = jog.state();
ready = true;
jog.poke();
await new Promise((r) => setTimeout(r, 0));
console.log(JSON.stringify({waiting, sent: sent.length, state: jog.state()}));
""")
    assert out == {"waiting": {"pressed": True, "inFlight": False}, "sent": 1,
                   "state": {"pressed": True, "inFlight": True}}