"""The cell's completion reports a measured fold and a look at the bed, never `folded = placed` (2026-11-19)."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))
import cell_task_exec  # noqa: E402


def status_file(tmp_path, state, age=0.0):
    io = tmp_path / "chunk-io-s"
    io.mkdir()
    path = io / "chunk-status.jsonl"
    path.write_text(json.dumps({"command": "park", "ok": True, "state": state}) + "\n")
    t = time.time() - age
    import os
    os.utime(path, (t, t))
    return path


def test_fold_is_read_from_the_runner_state(tmp_path):
    status_file(tmp_path, [0.0, -58.0, 50.0, 50.0, -5.0, 49.0])
    fold = cell_task_exec.measured_fold("arm_s", tmp_path)
    assert fold["folded"] is True and fold["state"][1] == -58.0


def test_arm_over_the_bed_is_not_folded(tmp_path):
    status_file(tmp_path, [10.0, -10.0, 20.0, 40.0, 30.0, 60.0])
    assert cell_task_exec.measured_fold("arm_s", tmp_path)["folded"] is False


def test_stale_or_missing_status_is_not_folded(tmp_path):
    status_file(tmp_path, [0.0, -58.0, 50.0, 50.0, -5.0, 49.0], age=600)
    assert cell_task_exec.measured_fold("arm_s", tmp_path)["folded"] is False
    assert cell_task_exec.measured_fold("arm_a", tmp_path)["folded"] is False


def test_bed_look_failure_is_none_not_empty(tmp_path):
    out = cell_task_exec.source_clearance(tmp_path / "missing.json", tmp_path / "cat.json", (0, 0, 10, 10), "pinky")
    assert out["objects"] is None and out["error"]
