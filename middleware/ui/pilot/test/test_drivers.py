"""D-323 T5 — drivers/registry와 pinky_core 게이트 판정. Node 서브프로세스 패턴."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _run_js(body):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is unavailable")
    script = f"""
import fs from 'node:fs';
const load = async (relpath) => await import('data:text/javascript;base64,'
  + Buffer.from(fs.readFileSync({json.dumps(str(ROOT))} + '/' + relpath, 'utf8'), 'utf8').toString('base64'));
const registry = await load('drivers/registry.js');
const pinky = await load('drivers/pinky_core.js');
registry.registerDriver(pinky.pinkyCore.kind, pinky.pinkyCore);
{body}
"""
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True,
                            text=True, encoding="utf-8", check=True)
    return json.loads(result.stdout)


def test_registry_returns_registered_driver_and_null_for_unknown():
    assert _run_js("""
    console.log(JSON.stringify({
      known: registry.driverFor('pinky_core').kind,
      unknown: registry.driverFor('omx_local'),
    }));
    """) == {"known": "pinky_core", "unknown": None}


def test_registry_rejects_wrong_duplicate_and_empty_kind():
    assert _run_js("""
    let sameDriverThrew = false;
    try { registry.registerDriver('pinky_core', pinky.pinkyCore); } catch (e) { sameDriverThrew = true; }
    let wrongDriverThrew = false;
    try { registry.registerDriver('pinky_core', {kind: 'pinky_core'}); } catch (e) { wrongDriverThrew = true; }
    let emptyThrew = false;
    try { registry.registerDriver('', {}); } catch (e) { emptyThrew = true; }
    console.log(JSON.stringify({sameDriverThrew, wrongDriverThrew, emptyThrew}));
    """) == {"sameDriverThrew": False, "wrongDriverThrew": True, "emptyThrew": True}


def test_gate_blocks_viewer_role():
    out = _run_js("""
    console.log(JSON.stringify(pinky.assessGate({role: 'viewer', capabilities: {teleop: true}})));
    """)
    assert out["allowed"] is False
    assert out["reasons"] == ["role:viewer"]


def test_gate_names_withheld_teleop_reason():
    out = _run_js("""
    console.log(JSON.stringify(pinky.assessGate({
      role: 'operator',
      capabilities: {teleop: false, withheld: {reasons: {teleop: 'drive_disabled:no_motion'}}},
    })));
    """)
    assert out["allowed"] is False
    assert out["reasons"] == ["teleop_withheld:drive_disabled:no_motion"]


def test_gate_blocks_without_runtime_drive():
    out = _run_js("""
    console.log(JSON.stringify(pinky.assessGate({
      role: 'operator',
      capabilities: {teleop: true, runtime: {drive: false}},
    })));
    """)
    assert out["allowed"] is False
    assert out["reasons"] == ["drive_disabled"]


def test_gate_allows_operator_with_teleop_and_drive():
    out = _run_js("""
    console.log(JSON.stringify(pinky.assessGate({
      role: 'operator',
      capabilities: {teleop: true, runtime: {drive: true}},
    })));
    """)
    assert out == {"allowed": True, "reasons": []}


def test_driver_paths_for_engage_disengage_and_stop():
    assert _run_js("""
    const calls = [];
    const post = (path, body) => { calls.push({path, body}); return Promise.resolve({status: 200}); };
    pinky.pinkyCore.engage(post);
    pinky.pinkyCore.disengage(post);
    pinky.pinkyCore.stop(post);
    console.log(JSON.stringify(calls));
    """) == [
        {"path": "/api/v1/mode", "body": {"mode": "MANUAL"}},
        {"path": "/api/v1/mode", "body": {"mode": "IDLE"}},
        {"path": "/api/v1/safety/stop", "body": {}},
    ]


def test_reason_codes_map_to_operator_korean():
    assert _run_js("""
    console.log(JSON.stringify([
      registry.driverFor('pinky_core').describeReason('role:viewer'),
      registry.driverFor('pinky_core').describeReason('teleop_withheld:drive_disabled:no_motion'),
      registry.driverFor('pinky_core').describeReason('teleop_withheld'),
      registry.driverFor('pinky_core').describeReason('drive_disabled'),
      registry.driverFor('pinky_core').describeReason('anything_else'),
    ]));
    """) == [
        "운전 권한이 없습니다 (현재 역할: 조회 전용)",
        "수동 운전이 보류되었습니다 — 구동 꺼짐 (무동작)",
        "수동 운전이 보류되었습니다",
        "구동이 꺼져 있습니다 (무동작)",
        "진입할 수 없습니다. 로봇 상태를 확인하세요",
    ]
