"""Executable contract for the dashboard's framework-free evidence wrapper."""

from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path


WEB_COMMON = Path(__file__).resolve().parents[2] / "web"
CI_WORKFLOW = Path(__file__).resolve().parents[4] / ".github" / "workflows" / "ci.yml"


def test_ci_installs_the_node_runtime_used_by_headless_contracts():
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "nodejs" in workflow


def _run(expression: str):
    source = base64.b64encode((WEB_COMMON / "core_ui_logic.js").read_bytes()).decode("ascii")
    script = f"""
import {{ HeadlessState }} from "data:text/javascript;base64,{source}";
const state = {json.dumps(_state())};
const headless = new HeadlessState(state);
console.log(JSON.stringify({expression}));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _state():
    return {
        "online": True,
        "pose": {"x": 1.25},
        "velocity": {"linear": 0.2},
        "evidence": {
            # The dates are deliberately misleading. The server enum wins.
            "pose": {
                "received_at": "2000-01-01T00:00:00Z",
                "evidence": "fresh",
                "stale_after_s": 0.01,
            },
            "velocity": {
                "received_at": "2999-01-01T00:00:00Z",
                "evidence": "delayed",
                "stale_after_s": 999999,
            },
            "battery": {"evidence": "disconnected", "stale_after_s": 2.0},
        },
    }


def test_server_evidence_enum_wins_over_client_clock_math():
    assert _run("({pose: headless.evidenceOf('pose'), velocity: headless.evidenceOf('velocity')})") == {
        "pose": "fresh",
        "velocity": "delayed",
    }


def test_delayed_and_disconnected_are_per_channel():
    assert _run("({delayed: headless.isDelayed('velocity'), disconnected: headless.isDisconnected('battery')})") == {
        "delayed": True,
        "disconnected": True,
    }


def test_get_value_returns_data_only_for_fresh_evidence():
    assert _run("({pose: headless.getValue('pose.x', 'pose'), velocity: headless.getValue('velocity.linear', 'velocity', null)})") == {
        "pose": 1.25,
        "velocity": None,
    }
