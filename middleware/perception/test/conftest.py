"""Put this test directory on sys.path so `import lane_sim` resolves under
pytest's rootdir rules even when a test file is collected from elsewhere.

Tests marked `drift` (the odometry drift grid, minutes of closed loop) run
only when selected: `pytest -m drift`."""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
# D-964: runner and lane-corner fixtures (test_learned_runner, test_lane_corner) moved with the code
# they test to perception_runtime; control's paint and bend tests reuse them from there.
sys.path.append(str(pathlib.Path(__file__).resolve().parents[3] / "integrations" / "perception" / "test"))
# perception_runtime itself, so a test file collected on its own (tools/collect_alone.py) imports it too.
sys.path.insert(1, str(pathlib.Path(__file__).resolve().parents[3] / "integrations" / "perception"))
# core_common (calibration store) for the calibration-step tests; sensing imports it lazily.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "contracts" / "foundation"))


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "drift: the odometry drift grid (slow); run with -m drift")


def pytest_collection_modifyitems(config, items):
    if "drift" in (config.getoption("markexpr") or ""):
        return
    skip = pytest.mark.skip(reason="odometry drift grid: run with -m drift")
    for item in items:
        if "drift" in item.keywords:
            item.add_marker(skip)
