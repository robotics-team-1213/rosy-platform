"""D-323 T3 — stick.js 순수 입력 매핑. Node 서브프로세스 패턴(test_camera_capture.py).

부호 규약은 REP-103(angular > 0 = 반시계·좌회전)이다. 2026-09-29 가제보 실측에서
angular +0.5 가 yaw +18° 로 나왔고, 옛 매핑은 화면 오른쪽 입력에 angular + 를 보내
오른쪽으로 꺾으면 왼쪽으로 돌았다. 아래 시험이 그 규약을 고정한다.
"""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

MODULE = Path(__file__).resolve().parents[1] / "stick.js"


def _run_js(body):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is unavailable")
    script = f"""
import fs from 'node:fs';
const source = fs.readFileSync({json.dumps(str(MODULE))}, 'utf8');
const stick = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
{body}
"""
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True,
                            text=True, encoding="utf-8", check=True)
    return json.loads(result.stdout)


PRELUDE = """
const near = (a, b) => Math.abs(a - b) < 1e-9;
const cfg = {...stick.DEFAULT_CONFIG, curve: 'linear', deadzone: 0.1, preset: 'high'};
const core = {manual_linear: 0.15, manual_angular: 0.6, max_linear: 0.2, max_angular: 0.8};
const lim = stick.resolveLimits(core, cfg);
"""


def test_deadzone_inside_is_zero_outside_is_continuous_and_full_is_one():
    assert _run_js(PRELUDE + """
    const c = stick.DEFAULT_CONFIG;
    console.log(JSON.stringify({
      inside: stick.shapeAxis(0.05, c),
      boundary: stick.shapeAxis(c.deadzone, c),
      continuous: stick.shapeAxis(0.6, c) > stick.shapeAxis(0.5, c),
      full: near(stick.shapeAxis(1, c), 1) && near(stick.shapeAxis(1, cfg), 1),
      clamped: near(stick.shapeAxis(1.7, c), 1) && near(stick.shapeAxis(-2, c), -1),
      symmetric: [0.25, 0.5, 0.77, 1].every(v => near(stick.shapeAxis(-v, c), -stick.shapeAxis(v, c))),
      expoSofter: stick.shapeAxis(0.5, c) < stick.shapeAxis(0.5, cfg),
    }));
    """) == {"inside": 0, "boundary": 0, "continuous": True, "full": True,
             "clamped": True, "symmetric": True, "expoSofter": True}


def test_right_input_turns_clockwise_left_turns_counterclockwise():
    """화면·게임패드·키보드·페달 모두 오른쪽 = angular 음수(시계, REP-103)."""
    assert _run_js(PRELUDE + """
    const right = [
      stick.mapInput({kind: 'stick', x: 1, y: 0}, cfg, lim),
      stick.mapInput({kind: 'pad', x: 1, y: 0}, cfg, lim),
      stick.mapInput({kind: 'keys', right: true}, cfg, lim),
      stick.mapInput({kind: 'pedals', forward: true, x: 1}, cfg, lim),
      stick.mapInput({kind: 'pivot', dir: -1}, cfg, lim),
    ];
    const left = stick.mapInput({kind: 'stick', x: -1, y: 0}, cfg, lim);
    console.log(JSON.stringify({
      rightIsClockwise: right.every(c => c.angular < 0),
      leftIsCounterClockwise: left.angular > 0,
      forwardIsPositive: stick.mapInput({kind: 'stick', x: 0, y: 1}, cfg, lim).linear > 0,
      invertFlipsOnlyAngular: (() => {
        const inv = stick.mapInput({kind: 'stick', x: 0.8, y: 0.5}, {...cfg, invertAngular: true}, lim);
        const base = stick.mapInput({kind: 'stick', x: 0.8, y: 0.5}, cfg, lim);
        return near(inv.angular, -base.angular) && near(inv.linear, base.linear);
      })(),
    }));
    """) == {"rightIsClockwise": True, "leftIsCounterClockwise": True,
             "forwardIsPositive": True, "invertFlipsOnlyAngular": True}


def test_pivot_is_in_place_rotation_from_every_pivot_input():
    assert _run_js(PRELUDE + """
    const sideways = stick.mapInput({kind: 'stick', x: 1, y: 0}, cfg, lim);
    const nearlySideways = stick.mapInput({kind: 'stick', x: 0.95, y: 0.15}, cfg, lim);   // ~9°
    const diagonal = stick.mapInput({kind: 'stick', x: 0.7, y: 0.7}, cfg, lim);
    const button = stick.mapInput({kind: 'pivot', dir: 1}, cfg, lim);
    console.log(JSON.stringify({
      sideways: sideways.pivot && sideways.linear === 0 && near(sideways.angular, -lim.angular),
      snapped: nearlySideways.pivot && nearlySideways.linear === 0,
      diagonalIsArc: !diagonal.pivot && diagonal.linear > 0 && diagonal.angular < 0,
      button: button.pivot && button.linear === 0 && near(button.angular, lim.angular),
      pedalsIgnoredWhilePivot: stick.mapInput({kind: 'pivot', dir: 1, forward: true}, cfg, lim).linear === 0,
      invertLeavesPivotLabelsTrue: stick.mapInput({kind: 'pivot', dir: 1}, {...cfg, invertAngular: true}, lim).angular > 0,
    }));
    """) == {"sideways": True, "snapped": True, "diagonalIsArc": True, "button": True,
             "pedalsIgnoredWhilePivot": True, "invertLeavesPivotLabelsTrue": True}


def test_presets_are_fractions_of_core_manual_limits_never_above():
    """CORE 가 축마다 자르면(box clip) 회전 반경이 틀어진다 — 앱이 먼저 한도 안에 둔다."""
    assert _run_js(PRELUDE + """
    const at = (preset, fine = false) => stick.resolveLimits(core, {...cfg, preset, fine});
    const full = (preset, fine) => stick.mapInput({kind: 'stick', x: -0.7071, y: 0.7071}, {...cfg, preset, fine}, at(preset, fine));
    const high = full('high');
    console.log(JSON.stringify({
      highEqualsCore: near(at('high').linear, 0.15) && near(at('high').angular, 0.6),
      ordered: at('low').linear < at('mid').linear && at('mid').linear < at('high').linear,
      withinCore: high.linear <= 0.15 + 1e-9 && Math.abs(high.angular) <= 0.6 + 1e-9,
      fine: near(at('high', true).linear, 0.15 * stick.FINE_SCALE),
      sessionCapLowers: near(stick.resolveLimits({...core, session_linear: 0.05}, cfg).linear, 0.05),
      unknownPresetFallsLow: near(stick.resolveLimits(core, {...cfg, preset: 'turbo'}).linear, 0.15 * stick.PRESETS.low),
      fallbackWithoutCore: near(stick.resolveLimits(null, cfg).linear, stick.FALLBACK_LIMITS.linear),
    }));
    """) == {"highEqualsCore": True, "ordered": True, "withinCore": True, "fine": True,
             "sessionCapLowers": True, "unknownPresetFallsLow": True, "fallbackWithoutCore": True}


def test_radial_deadzone_keeps_direction_and_opposites_cancel():
    assert _run_js(PRELUDE + """
    const d = stick.shapeStick(0.5, 0.5, cfg);
    const keysBoth = stick.mapInput({kind: 'keys', up: true, down: true}, cfg, lim);
    const pedalsBoth = stick.mapInput({kind: 'pedals', forward: true, reverse: true}, cfg, lim);
    const idle = stick.mapInput({kind: 'stick', x: 0.05, y: 0.05}, cfg, lim);
    console.log(JSON.stringify({
      directionKept: near(d.x, d.y),
      magnitudeCapped: Math.hypot(...Object.values(stick.shapeStick(1, 1, cfg))) <= 1 + 1e-9,
      keysCancel: keysBoth.linear === 0,
      pedalsCancel: pedalsBoth.linear === 0,
      idle: idle.linear === 0 && idle.angular === 0 && idle.pivot === false,
    }));
    """) == {"directionKept": True, "magnitudeCapped": True, "keysCancel": True,
             "pedalsCancel": True, "idle": True}
