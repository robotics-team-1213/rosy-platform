"""Dataset coverage and idempotent READY recovery after process interruption."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "training"))
from train_job import check_coverage, publish_ready  # noqa: E402
from job_state import JobError, Rejected  # noqa: E402
from export_cell import write_manifest  # noqa: E402


def model(folder):
    folder.mkdir()
    path = folder / "model.onnx"
    path.write_bytes(b"test weights, not an inference artifact")
    doc = write_manifest(folder, onnx_path=path, classes=[("floor", "background"),
                         ("line", "lane_marking")], color="rgb", scale=1/255,
                         mean=[0, 0, 0], std=[1, 1, 1], dataset_repo="store:example",
                         dataset_revision="a"*64, camera_profile_revision="provisional",
                         trainer="test")
    report = {"verdict": "pass", "model_revision": doc["model_revision"],
              "files": [{"name": f["name"], "sha256": f["sha256"]} for f in doc["files"]]}
    (folder / "intake_report.json").write_text(json.dumps(report))
    return doc


def test_coverage_rejects_validation_wall_without_training_wall():
    with pytest.raises(JobError, match="wall"):
        check_coverage([{"name": "floor"}, {"name": "line"}, {"name": "wall"}],
                       [0, 1, 0], [100, 1, 10])
    assert check_coverage([{"name": "floor"}, {"name": "line"}, {"name": "wall"}],
                          [1, 1, 0], [1, 1, 0]) == ["wall"]


def test_ready_recovery_preserves_files_and_never_duplicates(tmp_path):
    folder = tmp_path / "artifact"
    doc = model(folder)
    store = tmp_path / "store"
    first = publish_ready(folder, store, "run1")
    assert first.parent == store / "models/inbox"
    before = {p.name: p.read_bytes() for p in first.iterdir()}
    assert publish_ready(folder, store, "run1") == first
    assert before == {p.name: p.read_bytes() for p in first.iterdir()}
    accepted = store / "models/accepted" / doc["model_revision"]
    accepted.parent.mkdir(parents=True, exist_ok=True)
    first.rename(accepted)
    assert publish_ready(folder, store, "run1") == accepted
    assert not list((store / "models/inbox").iterdir())


def test_watcher_rejection_is_not_published_again(tmp_path):
    folder = tmp_path / "artifact"
    model(folder)
    store = tmp_path / "store"
    inbox = publish_ready(folder, store, "run1")
    rejected = store / "models/rejected" / inbox.name
    inbox.rename(rejected)
    (rejected / "REJECTED.txt").write_text("new quality gate rejected")
    with pytest.raises(Rejected, match="watcher"):
        publish_ready(folder, store, "run1")
    assert not list((store / "models/inbox").iterdir())


def test_ready_rejects_failed_or_mismatched_report(tmp_path):
    folder = tmp_path / "artifact"
    model(folder)
    report = json.loads((folder / "intake_report.json").read_text())
    report["verdict"] = "fail"
    (folder / "intake_report.json").write_text(json.dumps(report))
    with pytest.raises(Rejected):
        publish_ready(folder, tmp_path / "store", "run1")
    report["verdict"] = "pass"
    report["files"][0]["sha256"] = "0" * 64
    (folder / "intake_report.json").write_text(json.dumps(report))
    with pytest.raises(JobError, match="files"):
        publish_ready(folder, tmp_path / "store", "run1")


def test_partial_ready_recovers_but_modified_existing_file_refused(tmp_path):
    folder = tmp_path / "artifact"
    doc = model(folder)
    partial = tmp_path / "store/models/inbox" / (doc["model_revision"] + "__run1")
    partial.mkdir(parents=True)
    (partial / "model.onnx.part").write_bytes(b"interrupted copy")
    ready = publish_ready(folder, tmp_path / "store", "run1")
    assert (ready / "READY").is_file() and not (ready / "model.onnx.part").exists()
    (ready / "model.onnx").write_bytes(b"tampered")
    with pytest.raises(JobError, match="existing"):
        publish_ready(folder, tmp_path / "store", "run1")


def test_resume_uses_frozen_intake_proof_when_shared_report_changes(tmp_path):
    from train_job import snapshot_intake
    from job_state import Job
    folder = tmp_path / "artifact"
    model(folder)
    report = json.loads((folder / "intake_report.json").read_text())
    shared = tmp_path / "shared-intake.json"
    shared.write_text(json.dumps(report))
    with Job(tmp_path / "job", {}) as job:
        job.step("intake", lambda attempt: snapshot_intake(folder, json.loads(shared.read_text())))
    shared.write_text(json.dumps({**report, "latency_ms_p50": 99}))
    with Job(tmp_path / "job", {}) as job:
        qualified = job.step("intake", lambda attempt: pytest.fail("do not repeat intake"))
    assert qualified["artifact"] == str(folder)
    assert "latency_ms_p50" not in json.loads((folder / "intake_report.json").read_text())
