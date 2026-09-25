"""Closed-loop semantic road host simulation uses the production subjects."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

from PIL import Image


ROOT = Path(__file__).parents[1]
REPO_ROOT = ROOT.parents[2]


def _module():
    roots = {
        "core": "src/runtime/core",
        "core_common": "src/contracts/core_common",
        "core_events": "src/runtime/core_events",
        "core_features": "src/runtime/core_features",
    }
    for package in roots:
        path = str(REPO_ROOT / roots[package])
        if path not in sys.path:
            sys.path.insert(0, path)
    path = REPO_ROOT / "tools/simulate_semantic_road.py"
    spec = importlib.util.spec_from_file_location(
        "simulate_semantic_road", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_red_wait_green_resume_and_stale_stop_are_closed_loop(tmp_path):
    summary = _module().run_simulation(tmp_path)

    assert summary["status"] == "SEMANTIC_ROAD_HOST_SIM_PASS"
    assert summary["map_id"] == "map_260905_update_v2"
    assert summary["scene_revision"] == "road-scene-v1"
    assert summary["semantic_features"] == {
        "lanes": 1,
        "crosswalks": 1,
        "stop_lines": 1,
        "traffic_signals": 1,
    }
    samples = {item["phase"]: item for item in summary["samples"]}
    assert samples["clear"]["policy_state"] == "FOLLOW"
    assert samples["clear"]["command_linear"] > 0.0
    assert samples["approach"]["policy_state"] == "APPROACH"
    assert 0.0 < samples["approach"]["command_linear"] \
        < samples["clear"]["command_linear"]
    assert samples["red_stop"]["policy_state"] == "STOP_REQUIRED"
    assert samples["red_wait"]["policy_state"] == "WAIT_SIGNAL"
    assert samples["red_wait"]["command_linear"] == 0.0
    assert samples["red_wait"]["signal_colour"] == "RED"
    assert samples["red_wait"]["crosswalk_visible"] is True
    assert samples["green_proceed"]["policy_state"] == "PROCEED"
    assert samples["green_proceed"]["command_linear"] > 0.0
    assert samples["stale"]["policy_state"] == "HOLD"
    assert samples["stale"]["policy_reason"] == "road_evidence_stale"
    assert samples["stale"]["command_linear"] == 0.0
    assert summary["semantic_truth_fed_to_detector"] is False
    assert summary["physical_device_validated"] is False

    saved = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert saved == summary
    graphic = (tmp_path / "semantic_road_simulation.svg").read_text(
        encoding="utf-8")
    assert "map_260905_update_v2" in graphic
    assert "WAIT_SIGNAL" in graphic
    assert "PROCEED" in graphic
    preview = Image.open(tmp_path / "camera_preview_demo.jpg")
    assert preview.size == (320, 240)
    animation = Image.open(tmp_path / "camera_preview_simulation.gif")
    assert animation.is_animated is True
    assert animation.n_frames == 6


def test_repository_tool_entrypoint_loads_without_external_pythonpath():
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools/simulate_semantic_road.py"), "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
