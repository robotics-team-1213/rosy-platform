"""affected_ros.consolidate merges small same-environment PR jobs and never mixes environments or kinds (11-20)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "harness"))
import affected_ros  # noqa: E402


def _e(name, ros, paths, kind="pytest"):
    return {"name": name, "invocations": [paths], "ros": ros, "kind": kind}


def test_small_same_environment_jobs_merge_and_keep_every_invocation():
    out = affected_ros.consolidate([_e("affected-1", "overlay", ["a/test_x.py"]),
                                    _e("affected-2", "overlay", ["b/test_y.py"])], {})
    assert len(out) == 1 and out[0]["invocations"] == [["a/test_x.py"], ["b/test_y.py"]]


def test_environments_kinds_and_non_affected_jobs_stay_apart():
    out = affected_ros.consolidate([_e("affected-1", "overlay", ["a/test_x.py"]),
                                    _e("affected-2", "full", ["b/test_y.py"]),
                                    _e("build-smoke", "overlay", [], kind="smoke")], {})
    assert [o["name"] for o in out] == ["affected-1", "affected-2", "build-smoke"]


def test_heavy_jobs_are_not_merged_past_the_weight_cap():
    heavy = {"test_big.py": affected_ros.JOB_WEIGHT}
    out = affected_ros.consolidate([_e("affected-1", "overlay", ["a/test_big.py"]),
                                    _e("affected-2", "overlay", ["b/test_y.py"])], heavy)
    assert len(out) == 2
