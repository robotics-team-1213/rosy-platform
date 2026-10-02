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
    assert out[1] == {"kind": "base", "command": "velocity", "pivot": True, "fine": True, "autonomy": ["line"],
                      "max_linear": None, "max_angular": None}
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


def test_profile_carries_the_announced_manual_limits():
    out = _run_js("""console.log(JSON.stringify([
      m.profileFromBaseVelocity({kind: 'base_velocity', max_linear: 0, max_angular: 0.6, pivot: true, fine: false}),
      m.profileFromBaseVelocity(m.fallbackPinkyControls({pivot: true, fine: true})[0])]))""")
    assert out[0]["max_linear"] == 0 and out[0]["max_angular"] == 0.6 and out[0]["fine"] is False
    assert out[1]["max_linear"] is None and out[1]["max_angular"] is None

def test_gripper_percent_position_and_duration():
    out = _run_js("""
const g = {open: 1.0, closed: 0.0};
const r = {open: 0.0, closed: 1.0};
console.log(JSON.stringify([
  m.gripperPercent(0.25, g), m.gripperPosition(25, g), m.gripperPercent(2, g), m.gripperPercent(-1, g),
  m.gripperPercent(0.25, r), m.gripperPosition(100, r), m.gripperPosition('x', g), m.gripperPercent(NaN, g),
  m.gripperDuration(0, 1, g), m.gripperDuration(0, 0.5, g), m.gripperDuration(0.5, 0.52, g),
  m.gripperDuration(undefined, 0.5, g), m.gripperDuration(1, 0, r)]))""")
    assert out == [25, 0.25, 100, 0, 75, 0, 0, None, 2.0, 1.0, 0.2, 2.0, 2.0]


def test_gripper_state_labels():
    out = _run_js("""console.log(JSON.stringify([
  ['open', 'closed', 'holding', 'moving', 'unknown', 'squeezing', undefined].map(m.gripperStateLabel),
  m.GRIPPER_GOAL_MIN_S, m.GRIPPER_GOAL_MAX_S]))""")
    assert out == [["열림", "닫힘", "쥐고 있음", "이동 중", "알 수 없음", "알 수 없음", "알 수 없음"], 0.2, 2.0]


def test_gripper_goal_bounds_match_the_sim_contract():
    import re
    contract = (MODULE.parents[2] / "contracts/foundation/core_common/protocol/omx_sim.py").read_text(encoding="utf-8")
    bounds = [float(re.search(rf"^GRIPPER_GOAL_{edge}_DURATION_S = ([0-9.]+)$", contract, re.M).group(1))
              for edge in ("MIN", "MAX")]
    out = _run_js("console.log(JSON.stringify([m.GRIPPER_GOAL_MIN_S, m.GRIPPER_GOAL_MAX_S]))")
    assert out == bounds
