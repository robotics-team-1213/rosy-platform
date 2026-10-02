"""D-395 S1 bench driver (tools/sim/d395_s1_bench.py): truth-trail fallback for the drive start."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "sim" / "d395_s1_bench.py"


def _mod():
    spec = importlib.util.spec_from_file_location("d395_s1_bench", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_last_trail_pose_returns_the_newest_sample_of_that_robot():
    trail = [(1.0, "rosy_01", -0.70, 0.15, 3.14), (2.0, "rosy_02", -1.26, 0.49, 1.57),
             (3.0, "rosy_01", -0.70, 0.10, -1.57), (4.0, "rosy_02", -1.26, 0.49, 1.57)]
    assert _mod().last_trail_pose(trail, "rosy_01") == (-0.70, 0.10, -1.57)


def test_last_trail_pose_is_none_without_a_sample():
    m = _mod()
    assert m.last_trail_pose([], "rosy_01") is None
    assert m.last_trail_pose([(1.0, "rosy_02", 0.0, 0.0, 0.0)], "rosy_01") is None
