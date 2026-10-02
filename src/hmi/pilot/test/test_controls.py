"""D-411 B: rosy.controls/1 on the Pilot side (controls.js) — reader, widget plan, fallbacks."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1] / "controls.js"


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


def test_read_controls_accepts_only_the_v1_schema():
    out = _run_js("""console.log(JSON.stringify([
      m.readControls({schema: 'rosy.controls/1', items: [{id: 'base', kind: 'base_velocity'}]}),
      m.readControls({schema: 'rosy.controls/2', items: []}),
      m.readControls(undefined),
    ]))""")
    assert out[0] == [{"id": "base", "kind": "base_velocity"}] and out[1] is None and out[2] is None


def test_empty_items_mean_no_controls_now_not_an_old_server():
    out = _run_js("console.log(JSON.stringify(m.readControls({schema: 'rosy.controls/1', items: []})))")
    assert out == []


def test_malformed_items_are_dropped_not_fatal():
    out = _run_js("""console.log(JSON.stringify(m.readControls({schema: 'rosy.controls/1',
      items: [null, {kind: 'joint_jog'}, {id: 'base', kind: 'base_velocity', future: 1}]})))""")
    assert out == [{"id": "base", "kind": "base_velocity", "future": 1}]


def test_widget_plan_marks_unknown_kinds_unsupported_without_throwing():
    out = _run_js("""console.log(JSON.stringify(m.widgetPlan(
      [{id: 'base', kind: 'base_velocity'}, {id: 'x', kind: 'laser', label: '레이저'}], ['base_velocity'])))""")
    assert [p["supported"] for p in out] == [True, False]


def test_pinky_fallback_and_profile_round_trip():
    out = _run_js("""
const items = m.fallbackPinkyControls({kind: 'base', command: 'velocity', pivot: true, fine: true, autonomy: ['line']});
console.log(JSON.stringify([items, m.profileFromBaseVelocity(items[0]),
  m.profileFromBaseVelocity({kind: 'base_velocity', pivot: false, fine: true, autonomy: []})]))""")
    assert out[0][0]["kind"] == "base_velocity"
    assert out[1] == {"kind": "base", "command": "velocity", "pivot": True, "fine": True, "autonomy": ["line"]}
    assert out[2]["pivot"] is False and out[2]["autonomy"] == []


def test_profile_ignores_autonomy_modes_pilot_does_not_know():
    out = _run_js("""console.log(JSON.stringify(m.profileFromBaseVelocity(
      {kind: 'base_velocity', pivot: true, fine: true, autonomy: ['line', 'dock']})))""")
    assert out["autonomy"] == ["line"]


def test_omx_fallback_keeps_the_legacy_gripper_jog():
    out = _run_js("""console.log(JSON.stringify(m.fallbackOmxControls(
      {joints: ['joint1', 'joint2'], gripper: 'gripper_joint_1'})))""")
    (jog,) = out
    assert jog["kind"] == "joint_jog" and jog["max_step_rad"] == 0.02
    assert [j["name"] for j in jog["joints"]] == ["joint1", "joint2", "gripper_joint_1"]


def test_omx_fallback_lists_a_joint_once():
    out = _run_js("console.log(JSON.stringify(m.fallbackOmxControls({joints: ['joint1'], gripper: 'joint1'})))")
    assert [j["name"] for j in out[0]["joints"]] == ["joint1"]
