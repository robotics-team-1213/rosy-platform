"""D-323 T3 — stick.js 순수 입력 매핑. Node 서브프로세스 패턴(test_camera_capture.py)."""

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
const cfg = {...stick.DEFAULT_CONFIG};
"""


def test_deadzone_inside_is_zero_outside_is_continuous_and_full_is_one():
    assert _run_js(PRELUDE + """
    console.log(JSON.stringify({
      inside: stick.shapeAxis(0.1, cfg),
      boundary: stick.shapeAxis(cfg.deadzone, cfg),
      above: stick.shapeAxis(0.5, cfg) > 0,
      continuous: stick.shapeAxis(0.6, cfg) > stick.shapeAxis(0.5, cfg),
      full: near(stick.shapeAxis(1, cfg), 1),
      clamped: near(stick.shapeAxis(1.7, cfg), 1) && near(stick.shapeAxis(-2, cfg), -1),
    }));
    """) == {"inside": 0, "boundary": 0, "above": True, "continuous": True,
             "full": True, "clamped": True}


def test_origin_symmetry():
    assert _run_js(PRELUDE + """
    const samples = [0.25, 0.5, 0.77, 1];
    console.log(JSON.stringify(samples.every(s =>
      near(stick.shapeAxis(-s, cfg), -stick.shapeAxis(s, cfg)))));
    """) is True


def test_expo_curve_is_softer_mid_and_equal_at_full():
    assert _run_js(PRELUDE + """
    const expo = {...cfg, curve: 'expo'};
    console.log(JSON.stringify({
      softer: stick.shapeAxis(0.6, expo) < stick.shapeAxis(0.6, cfg),
      full: near(stick.shapeAxis(1, expo), 1),
    }));
    """) == {"softer": True, "full": True}


def test_pad_maps_axes_with_preset_scale():
    assert _run_js(PRELUDE + """
    const out = stick.mapInput({kind: 'pad', x: 1, y: 1}, cfg);
    const stop = stick.mapInput({kind: 'pad', x: 0.05, y: 0.05}, cfg);
    console.log(JSON.stringify({
      linear: near(out.linear, stick.PRESETS.low.linear),
      angular: near(out.angular, stick.PRESETS.low.angular),
      stop: stop.linear === 0 && stop.angular === 0,
    }));
    """) == {"linear": True, "angular": True, "stop": True}


def test_pedals_forward_reverse_conflict_and_none():
    assert _run_js(PRELUDE + """
    const f = stick.mapInput({kind: 'pedals', forward: true, reverse: false, steer: 0}, cfg);
    const r = stick.mapInput({kind: 'pedals', forward: false, reverse: true, steer: 0}, cfg);
    const both = stick.mapInput({kind: 'pedals', forward: true, reverse: true, steer: 0}, cfg);
    const none = stick.mapInput({kind: 'pedals', forward: false, reverse: false, steer: 0}, cfg);
    console.log(JSON.stringify({
      forward: near(f.linear, stick.PRESETS.low.linear),
      reverseSymmetric: near(r.linear, -stick.PRESETS.low.linear),
      conflict: both.linear === 0,
      none: none.linear === 0,
    }));
    """) == {"forward": True, "reverseSymmetric": True, "conflict": True, "none": True}


def test_keys_map_full_axis_and_opposites_cancel():
    assert _run_js(PRELUDE + """
    const up = stick.mapInput({kind: 'keys', up: true, down: false, left: false, right: false}, cfg);
    const both = stick.mapInput({kind: 'keys', up: true, down: true, left: false, right: false}, cfg);
    console.log(JSON.stringify({
      up: near(up.linear, stick.PRESETS.low.linear),
      cancel: both.linear === 0,
    }));
    """) == {"up": True, "cancel": True}


def test_invert_angular_flips_sign_only():
    assert _run_js(PRELUDE + """
    const inverted = {...cfg, invertAngular: true};
    const a = stick.mapInput({kind: 'pad', x: 0.8, y: 0}, cfg);
    const b = stick.mapInput({kind: 'pad', x: 0.8, y: 0}, inverted);
    console.log(JSON.stringify({
      flipped: near(b.angular, -a.angular),
      linearUntouched: near(b.linear, a.linear),
    }));
    """) == {"flipped": True, "linearUntouched": True}


def test_preset_high_scales_more_and_never_exceeds_preset():
    assert _run_js(PRELUDE + """
    const low = stick.mapInput({kind: 'pad', x: 1, y: 1}, {...cfg, preset: 'low'});
    const high = stick.mapInput({kind: 'pad', x: 1, y: 1}, {...cfg, preset: 'high'});
    console.log(JSON.stringify({
      more: high.linear > low.linear && high.angular > low.angular,
      bounded: high.linear <= stick.PRESETS.high.linear + 1e-9
            && high.angular <= stick.PRESETS.high.angular + 1e-9,
      unknownPresetFallsSafe: stick.mapInput({kind: 'pad', x: 1, y: 1}, {...cfg, preset: 'turbo'})
        .linear <= stick.PRESETS.low.linear + 1e-9,
    }));
    """) == {"more": True, "bounded": True, "unknownPresetFallsSafe": True}
