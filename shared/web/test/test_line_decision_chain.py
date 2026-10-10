"""Camera preview decision chain rows 3-5: the headline names the layer that stops the robot."""

from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess

WEB_COMMON = Path(__file__).resolve().parents[1]


def _chain(status):
    source = base64.b64encode((WEB_COMMON / "core_ui_logic.js").read_bytes()).decode("ascii")
    script = (f'import * as logic from "data:text/javascript;base64,{source}";\n'
              f"console.log(JSON.stringify(logic.lineDecisionChain({json.dumps(status)})));\n")
    result = subprocess.run(["node", "--input-type=module", "--eval", script],
                            check=True, capture_output=True, text=True, encoding="utf-8")
    return json.loads(result.stdout)


def test_a_core_gate_hold_with_an_open_stuck_is_stopped_by_core():
    view = _chain({"state": "HOLD", "reason": "lane_departure", "linear": 0, "angular": 0,
                   "stuck": {"stuck_id": "stuck-3d", "cause": "no_motion", "detail": "lane_departure",
                             "phase": "WAITING_CONSOLE", "held_s": 5.5, "last_answer": "WAIT"}})
    assert view["headline"] == {"level": "error",
                                "text": "STOPPED BY: 3 CORE GATES - lane_departure (stuck 6 s, Fleet WAIT)"}
    assert [row["level"] for row in view["rows"]] == ["error", "error", "warning"]
    assert view["rows"][1]["text"].startswith("no_motion/lane_departure")


def test_each_reason_family_points_at_its_layer():
    assert "1-2 PERCEPTION/STEERING" in _chain({"state": "LOST", "reason": "camera_reselection_required"})["headline"]["text"]
    assert "5 FLEET/AI - fleet_wrong_way" in _chain({"state": "HOLD", "reason": "fleet_wrong_way"})["headline"]["text"]
    recovering = _chain({"state": "RECOVERING", "reason": "stuck_back_off"})["headline"]
    assert recovering == {"level": "warning", "text": "RECOVERING BY: 4 STUCK - stuck_back_off"}
    assert _chain({"state": "TRACKING", "reason": "tracking"})["headline"] == {"level": "ready", "text": "MOVING - TRACKING"}
    assert _chain({})["headline"]["level"] == "unavailable"


def test_only_reported_gates_are_shown():
    gates = _chain({"state": "HOLD", "reason": "obstacle_ahead", "body_gap_m": 0.04, "stop_gap_m": 0.06,
                    "crosswalk": {"state": "clear"}, "authority": {"state": "granted"}})["rows"][0]["text"]
    assert gates == "HOLD obstacle_ahead · v - w - · body gap 0.04/0.06 m · crosswalk clear · authority granted"
    assert "lane_cue not reported" in _chain({"state": "TRACKING"})["rows"][2]["text"]
