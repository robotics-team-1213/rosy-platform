"""Deterministic host simulation for both D-143 sensing modes."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).parents[1]
REPO_ROOT = ROOT.parents[2]


def _module():
    for package in ("core_common", "core_events", "core_features"):
        path = str(REPO_ROOT / "src/core" / package)
        if path not in sys.path:
            sys.path.insert(0, path)
    path = REPO_ROOT / "tools/simulate_line_follow.py"
    spec = importlib.util.spec_from_file_location("simulate_line_follow", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_both_modes_track_turn_slow_and_fail_closed(tmp_path):
    summary = _module().run_simulation(tmp_path)

    assert set(summary["modes"]) == {"IR_LINE", "CAMERA_LINE"}
    for result in summary["modes"].values():
        assert result["tracking_samples"] >= 40
        assert result["closed_loop"] is True
        assert result["converged"] is True
        assert abs(result["final_cross_track_m"]) < abs(result["initial_cross_track_m"])
        assert 0.0 < result["minimum_tracking_speed"] < result["straight_speed"] <= 0.10
        assert result["stale_stop"] is True
        assert result["loss_latched"] is True
        assert result["final_reason"] == "reselection_required"

    saved = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert saved == summary
    assert {"cross_track_m", "yaw_rad"} <= set(summary["series"]["IR_LINE"][0])
    assert "IR_LINE" in (tmp_path / "line_follow_simulation.svg").read_text(encoding="utf-8")


def test_repository_tool_entrypoint_loads_without_external_pythonpath():
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools/simulate_line_follow.py"), "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
