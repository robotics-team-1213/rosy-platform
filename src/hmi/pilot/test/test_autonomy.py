"""D-344 — autonomy.js 누르는 동안만 가는 차선 추종 상태 기계. Node 서브프로세스 패턴."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

MODULE = Path(__file__).resolve().parents[1] / "autonomy.js"


def _run_js(body):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is unavailable")
    script = f"""
import fs from 'node:fs';
const source = fs.readFileSync({json.dumps(str(MODULE))}, 'utf8');
const A = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const calls = [];
const timers = [];
let replies = {{}};
const request = async (method, path, body) => {{
  calls.push([method, path, body ?? null]);
  const r = replies[method + ' ' + path];
  return typeof r === 'function' ? r() : (r ?? {{status: 200, body: {{}}}});
}};
const schedule = (fn, ms) => {{ const t = {{fn, live: true}}; timers.push(t); return () => {{ t.live = false; }}; }};
const flush = async () => {{ for (let i = 0; i < 6; i += 1) await Promise.resolve(); }};
const fire = async () => {{ const due = timers.splice(0).filter(t => t.live); for (const t of due) {{ await t.fn(); await flush(); }} }};
const changes = [];
const make = () => A.createAutoSession({{request, schedule, onChange: c => changes.push(c.state + ':' + c.reason)}});
{body}
"""
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True,
                            text=True, encoding="utf-8", check=True)
    return json.loads(result.stdout)


def test_press_starts_hold_session_and_release_returns_to_manual():
    out = _run_js("""
    const s = make();
    await s.press();
    await fire(); await fire();                       // 틱 두 번: hold 가 나가야 한다
    await s.release('released');
    console.log(JSON.stringify({calls, state: s.state()}));
    """)
    calls = out["calls"]
    assert calls[0] == ["PUT", "/api/v1/line-follow/mode", {"mode": "CAMERA_LINE", "hold_s": 0.5}]
    assert ["POST", "/api/v1/line-follow/hold", None] in calls
    assert calls[-2] == ["PUT", "/api/v1/line-follow/mode", {"mode": "OFF"}]
    assert calls[-1] == ["POST", "/api/v1/mode", {"mode": "MANUAL"}]
    assert out["state"] == "idle"


def test_core_release_409_on_hold_ends_session_and_restores_manual():
    out = _run_js("""
    replies['POST /api/v1/line-follow/hold'] = {status: 409, body: {}};
    const s = make();
    await s.press();
    await fire();
    console.log(JSON.stringify({last: calls.slice(-2), state: s.state(), reason: s.reason()}));
    """)
    assert out["state"] == "idle" and out["reason"] == "core_released"
    assert out["last"][-1] == ["POST", "/api/v1/mode", {"mode": "MANUAL"}]


def test_refused_start_reports_reason_and_never_holds():
    out = _run_js("""
    replies['PUT /api/v1/line-follow/mode'] = {status: 501, body: {error: {code: 'CAPABILITY_NOT_SUPPORTED'}}};
    const s = make();
    await s.press();
    await fire();
    console.log(JSON.stringify({held: calls.some(c => c[1].endsWith('/hold')), reason: s.reason(), state: s.state()}));
    """)
    assert out == {"held": False, "reason": "CAPABILITY_NOT_SUPPORTED", "state": "idle"}


def test_release_while_starting_turns_it_off_right_after():
    out = _run_js("""
    let resolvePut;
    replies['PUT /api/v1/line-follow/mode'] = () => new Promise(r => { resolvePut = r; });
    const s = make();
    const pressing = s.press();
    await flush();
    s.release('released');                       // 켜지는 중에 손을 뗐다
    replies['PUT /api/v1/line-follow/mode'] = {status: 200, body: {}};
    resolvePut({status: 200, body: {}});
    await pressing; await flush();
    console.log(JSON.stringify({last: calls.slice(-2), held: calls.some(c => c[1].endsWith('/hold')), state: s.state()}));
    """)
    assert out["held"] is False and out["state"] == "idle"
    assert out["last"] == [["PUT", "/api/v1/line-follow/mode", {"mode": "OFF"}],
                           ["POST", "/api/v1/mode", {"mode": "MANUAL"}]]


def test_intent_view_maps_core_status_to_target_and_steer_direction():
    """D-364 §6: pilot shows where CORE aims and which way it actually turns."""
    out = _run_js("""
const v = A.intentView;
console.log(JSON.stringify([
  v({mode: 'CAMERA_LINE', state: 'TRACKING', error: 0.4, angular: -0.32}),
  v({mode: 'CAMERA_LINE', state: 'TRACKING', error: -2, angular: 0.5}),
  v({mode: 'CAMERA_LINE', state: 'TRACKING', error: 0.0, angular: 0.01}),
  v({mode: 'CAMERA_LINE', state: 'HOLD', error: null, angular: 0, reason: 'obstacle_ahead'}),
  v({mode: 'CAMERA_LINE', state: 'TRACKING', error: 0.1, angular: 0.5, reason: 'lane_edge_right'}),
  v({mode: 'OFF', state: 'OFF'}),
  v(null),
]));
""")
    right, left, straight, held, guard, off, none = out
    assert right["target"] == 70 and right["dir"] == "right" and right["text"] == "오른쪽 18°/s ▶"
    assert left["target"] == 0 and left["dir"] == "left" and left["text"].startswith("◀ 왼쪽 29")
    assert straight["dir"] == "straight" and straight["text"] == "▲ 직진"
    assert held["visible"] and not held["tracking"] and held["target"] is None and held["text"] == "멈춤"
    assert guard["guard"] is True
    assert off == {"visible": False} and none == {"visible": False}
