"""D-554: a lane-derived dataset admits drivable_head without IndexedReview; no Job, GPU or READY."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "training"))
import lane_derived_drivable as ldd  # noqa: E402
import train_job  # noqa: E402
from job_state import JobError  # noqa: E402
from store import Store, content_sha  # noqa: E402
from test_lane_derived_drivable import _frame, _source  # noqa: E402


def _setup(tmp_path):
    from export_cell import write_manifest
    derived = tmp_path / "derived"
    ldd.derive(_source(tmp_path, [("train", "a", _frame()), ("val", "b", _frame())]), derived)
    store = Store(tmp_path / "store")
    path, digest = store.put_dataset(derived, "lane-derived")
    evaluation = tmp_path / "replay" / "eval"
    evaluation.mkdir(parents=True)
    (evaluation / "manifest.json").write_text(json.dumps({"purpose": "eval", "frames": [{"session": "other"}]}))
    evaluation = evaluation.rename(evaluation.with_name(content_sha(evaluation)))
    gate = tmp_path / "gate.json"
    gate.write_text(json.dumps({"require_eval": True, "eval_set": evaluation.name, "min_lane_marking_iou": 0.1}))
    profile = tmp_path / "profile.json"
    profile.write_text('{"accepted":true}')
    parent = tmp_path / "parent"
    raw = tmp_path / "source.onnx"
    raw.write_bytes(b"parent onnx")
    write_manifest(parent, onnx_path=raw, classes=[(c["name"], c["role"]) for c in ldd.CLASSES[:-1]],
                   color="rgb", scale=1 / 255, mean=[0, 0, 0], std=[1, 1, 1], dataset_repo="store:lane",
                   dataset_revision="a" * 64, camera_profile_revision="camera", trainer="parent")
    script = tmp_path / "lane.pt"
    script.write_bytes(b"parent torchscript")
    config = dict(store=str(store.root), dataset="lane-derived@" + digest, gate=str(gate),
                  replay_root=str(evaluation.parent), camera_profile=str(profile),
                  intake_out=str(tmp_path / "intake"),
                  training=dict(seed=1, epochs=1, lr=0.001, batch_size=1, recipe="drivable_head",
                                parent_model=str(parent), parent_torchscript=str(script), ignore_top=110))
    return config, Path(path), script


class Boundary(Exception):
    pass


def test_derived_dataset_admits_drivable_head_and_rechecks_hashes(tmp_path, monkeypatch):
    config, dataset, script = _setup(tmp_path)
    seen = {}

    def candidate(cfg, out, ds, profile, training, parent, inputs, check):
        seen.update(inputs)
        check()
        frame = json.loads((ds / "manifest.json").read_text())["frames"][0]
        (ds / frame["mask"]).write_bytes(b"changed")
        with pytest.raises(JobError, match="D-554 lane-derived dataset changed"):
            check()
        raise Boundary

    monkeypatch.setattr(train_job, "_run_drivable_candidate", candidate)
    monkeypatch.setattr(train_job, "gpu_lease", lambda: pytest.fail("no real GPU"))
    with pytest.raises(Boundary):
        train_job.run(config, tmp_path / "job")
    assert seen["lane_derived"]["annotation_origin"] == "derived_from_reviewed_lanes"
    assert seen["lane_derived"]["adr"] == "D-554"
    assert seen["parent_lane_model"]["model_revision"].startswith("lane-seg-")
    assert "learning/training/perception/dataset/lane_derived_drivable.py" in seen["source_files"]
    assert not (tmp_path / "job").exists()


def test_derived_recheck_binds_parent_files(tmp_path, monkeypatch):
    config, _, script = _setup(tmp_path)

    def candidate(cfg, out, ds, profile, training, parent, inputs, check):
        script.write_bytes(b"swapped parent")
        check()

    monkeypatch.setattr(train_job, "_run_drivable_candidate", candidate)
    with pytest.raises(JobError, match="parent/trainer source changed"):
        train_job.run(config, tmp_path / "job")


def test_derived_dataset_refuses_other_recipes_and_tampered_files(tmp_path):
    config, dataset, _ = _setup(tmp_path)
    baseline = dict(config, training=dict(seed=1, epochs=1, lr=0.001, batch_size=1, base=8, recipe="baseline"))
    with pytest.raises(JobError, match="only the drivable_head"):
        train_job.run(baseline, tmp_path / "job")
    doc = json.loads((dataset / "manifest.json").read_text())
    doc["annotation_origin"] = "untrusted"
    (dataset / "manifest.json").write_text(json.dumps(doc))
    renamed = dataset.rename(dataset.with_name(content_sha(dataset)))
    config["dataset"] = "lane-derived@" + renamed.name
    with pytest.raises(JobError, match="lane-derived admission denied"):
        train_job.run(config, tmp_path / "job")
