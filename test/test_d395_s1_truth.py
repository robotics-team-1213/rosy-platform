"""D-395 S1 bench judge (tools/sim/d395_truth.py): pass box and mirror-lock flag."""

import importlib.util
import math
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "sim" / "d395_truth.py"


def _mod():
    spec = importlib.util.spec_from_file_location("d395_truth", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_parse_gz_model_pose_reads_xyz_then_rpy():
    text = ("Requesting state for world [map_v2_fleet]...\n\nModel: [12]\n  - Name: rosy_01\n"
            "  - Pose [ XYZ (m) ] [ RPY (rad) ]:\n    [-1.260012 0.490001 0.000412]\n"
            "    [0.000001 -0.000020 1.570790]\n")
    assert _mod().parse_gz_model_pose(text) == (-1.260012, 0.490001, 1.57079)
    assert _mod().parse_gz_model_pose("model not found") is None


def test_judge_passes_inside_5_cm_and_5_degrees_only():
    m = _mod()
    truth = (-1.26, 0.49, math.pi / 2)
    assert m.judge((-1.23, 0.50, math.pi / 2 + math.radians(4)), truth)["ok"]
    assert not m.judge((-1.20, 0.49, math.pi / 2), truth)["ok"]
    assert not m.judge((-1.26, 0.49, math.pi / 2 + math.radians(6)), truth)["ok"]


def test_judge_flags_the_180_degree_twin_as_a_mirror_lock():
    m = _mod()
    truth = (-0.70, 0.15, math.pi)
    verdict = m.judge((0.71, -0.16, 0.02), truth)
    assert verdict["mirror"] and not verdict["ok"]
    assert not m.judge(truth, truth)["mirror"]
    # Far from both: wrong, but not the mirror signature.
    assert not m.judge((0.0, 0.0, 0.0), truth)["mirror"]
