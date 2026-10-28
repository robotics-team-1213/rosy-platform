"""Batch export selection and refusals for teacher SIM reach episodes (lerobot_export mocked)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SPEC = importlib.util.spec_from_file_location("sim_batch_export", ROOT / "learning/curation/omx/sim_batch_export.py")
batch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(batch)
TASK = json.loads((ROOT / "deploy/robot/omx/sim/reach_task.example.json").read_text(encoding="utf-8"))
NAMES = TASK["joint_names"]
SOURCE = {"joint_names": NAMES, "position_limits_rad": {n: [-1.0, 1.0] for n in NAMES}, "fps": 10,
          "camera": {"name": "front", "identity": "cam", "width": 4, "height": 4,
                     "camera_info_sha256": "a" * 64},
          "calibration_revision": "sim", "world_sha256": "b" * 64}


def write_recording(root: Path, episode_id: str, *, status="complete", issues=(), outcome="success",
                    durations=(0.4, 0.4, 0.4), source=None):
    folder = root / episode_id
    folder.mkdir(parents=True)
    rows = [{"frame_index": i, "duration_s": d} for i, d in enumerate(durations)]
    (folder / "samples.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    (folder / "manifest.json").write_text(json.dumps({
        "schema": "rosy.omx-demonstration.v1", "episode_id": episode_id, "status": status,
        "issues": list(issues), "task_outcome": outcome, "frame_count": len(rows),
        "provenance": source or SOURCE}), encoding="utf-8")


def episode(index, *, success=True, status="complete", issues=(), reason=""):
    return {"index": index, "seed": 1000 + index, "success": success, "reason": reason,
            "recording": {"episode_id": f"ep-{index}", "status": status, "issues": list(issues),
                          "frame_count": 3, "task_outcome": "success" if success else "failure"}}


def write_results(path: Path, episodes):
    path.write_text(json.dumps({"schema": batch.RESULTS_SCHEMA, "task_id": TASK["task_id"], "task_sha256": "c" * 64,
                                "task": TASK, "episodes": episodes}), encoding="utf-8")
    return path


class Exporter:
    def __init__(self, fail=()):
        self.calls, self.fail = [], set(fail)

    def __call__(self, episode, output, repo_id):
        self.calls.append(Path(episode).name)
        if Path(episode).name in self.fail:
            raise ValueError("export requires lerobot==0.4.4; found 0.3.0")
        output.mkdir()
        (output / "rosy_export.json").write_text('{"status": "verified"}', encoding="utf-8")
        return {"status": "verified"}


@pytest.fixture
def layout(tmp_path):
    recordings = tmp_path / "recordings"
    recordings.mkdir()
    return tmp_path, recordings


def test_complete_successes_export_and_the_highest_seed_is_the_eval(layout):
    tmp, recordings = layout
    for i in range(4):
        write_recording(recordings, f"ep-{i}")
    results = write_results(tmp / "results.json", [episode(i) for i in (2, 0, 3, 1)])
    exporter = Exporter()
    manifest = batch.batch_export(results, recordings, tmp / "out", exporter=exporter)
    assert manifest["status"] == "ready" and manifest["refused"] == []
    assert [e["seed"] for e in manifest["train"]] == [1000, 1001, 1002]
    assert [e["seed"] for e in manifest["eval"]] == [1003]
    assert exporter.calls == ["ep-0", "ep-1", "ep-2", "ep-3"]
    args = manifest["act_job_args"]
    assert args[0] == "--train-export" and args[-2] == "--eval-export" and args[-1].endswith("/exports/ep-3")
    assert len(args) == 6 and manifest["jog_duration_s"] == 0.4
    assert json.loads((tmp / "out/batch-manifest.json").read_text(encoding="utf-8")) == manifest


def test_failed_incomplete_mismatched_and_missing_episodes_are_refused_with_reasons(layout):
    tmp, recordings = layout
    write_recording(recordings, "ep-0")
    write_recording(recordings, "ep-1")
    write_recording(recordings, "ep-2", outcome="failure")
    write_recording(recordings, "ep-3", status="incomplete", issues=["frame_gap"])
    write_recording(recordings, "ep-4", durations=(0.4, 0.5))
    write_recording(recordings, "ep-5", source={**SOURCE, "world_sha256": "d" * 64})
    write_recording(recordings, "ep-7", source={**SOURCE, "joint_names": NAMES[::-1]})
    write_recording(recordings, "ep-8")
    write_recording(recordings, "ep-9")
    episodes = [episode(0), episode(1), episode(2, success=False, reason="max_steps_without_reaching_tolerance"),
                episode(3, status="incomplete", issues=["frame_gap"]), episode(4), episode(5),
                episode(6), episode(7), episode(8), episode(9)]
    exporter = Exporter(fail={"ep-8"})
    manifest = batch.batch_export(write_results(tmp / "results.json", episodes), recordings, tmp / "out",
                                  exporter=exporter)
    refused = {e["episode_id"]: e["reasons"] for e in manifest["refused"]}
    assert refused["ep-2"][0] == "teacher_failure:max_steps_without_reaching_tolerance"
    assert "source_outcome_failure" in refused["ep-2"]
    assert refused["ep-3"] == ["recording_incomplete", "recording_issues:frame_gap", "source_incomplete:frame_gap"]
    assert refused["ep-4"] == ["duration_mismatch:[0.4, 0.5]"]
    assert refused["ep-5"] == ["provenance_mismatch:world_sha256"]
    assert refused["ep-6"] == ["source_missing"]
    assert "joint_order_differs_from_task" in refused["ep-7"]
    assert refused["ep-8"][0].startswith("export_failed:export requires lerobot==0.4.4")
    assert [e["episode_id"] for e in manifest["train"]] == ["ep-0", "ep-1"]
    assert [e["episode_id"] for e in manifest["eval"]] == ["ep-9"] and manifest["status"] == "ready"
    assert "ep-2" not in exporter.calls and "ep-3" not in exporter.calls


def test_too_few_exportable_episodes_is_insufficient_with_no_act_job_args(layout):
    tmp, recordings = layout
    write_recording(recordings, "ep-0")
    write_recording(recordings, "ep-1")
    manifest = batch.batch_export(write_results(tmp / "results.json", [episode(0), episode(1)]), recordings,
                                  tmp / "out", exporter=Exporter())
    assert manifest["status"] == "insufficient" and manifest["act_job_args"] == []
    assert len(manifest["train"]) == 1 and len(manifest["eval"]) == 1


def test_output_must_be_new_and_results_schema_explicit(layout):
    tmp, recordings = layout
    results = write_results(tmp / "results.json", [])
    with pytest.raises(ValueError, match="new output directory"):
        batch.batch_export(results, recordings, recordings / "out", exporter=Exporter())
    (tmp / "exists").mkdir()
    with pytest.raises(ValueError, match="new output directory"):
        batch.batch_export(results, recordings, tmp / "exists", exporter=Exporter())
    results.write_text(json.dumps({"schema": "other"}), encoding="utf-8")
    with pytest.raises(ValueError, match="teacher results must be"):
        batch.batch_export(results, recordings, tmp / "out", exporter=Exporter())


def test_run_exporter_calls_the_lerobot_export_cli_and_requires_a_verified_receipt(layout, monkeypatch):
    tmp, _ = layout
    fake = tmp / "fake_export.py"
    fake.write_text("import json, sys, pathlib\n"
                    "out = pathlib.Path(sys.argv[2]); out.mkdir()\n"
                    "assert sys.argv[3:] == ['--repo-id', 'rosy-local/test']\n"
                    "status = 'failed' if 'bad' in sys.argv[1] else 'verified'\n"
                    "(out / 'rosy_export.json').write_text(json.dumps({'status': status}))\n"
                    "sys.exit(1 if status == 'failed' else 0)\n", encoding="utf-8")
    monkeypatch.setattr(batch, "EXPORTER", fake)
    assert batch.run_exporter(tmp / "good", tmp / "o1", "rosy-local/test", python=sys.executable) == {
        "status": "verified"}
    with pytest.raises(ValueError, match="exit 1, status failed"):
        batch.run_exporter(tmp / "bad", tmp / "o2", "rosy-local/test", python=sys.executable)
