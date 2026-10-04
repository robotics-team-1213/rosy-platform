"""D-431: NCNN intake requires hashed frame-parity evidence, not just loadability."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "middleware/perception/test"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
from test_learned_manifest_ncnn import ncnn_doc, write_doc  # noqa: E402
from control.sensing.perception.learned.manifest import ManifestError, load_manifest  # noqa: E402
import intake  # noqa: E402


def test_ncnn_intake_refuses_missing_and_failed_export_comparison(tmp_path):
    doc = ncnn_doc()
    with pytest.raises(ManifestError, match="parity"):
        intake.check_precision(load_manifest(write_doc(tmp_path, doc)))
    report = {"ok": False, "frames": 1, "results": [{"ok": False}]}
    data = json.dumps(report).encode()
    (tmp_path / "export_parity.json").write_bytes(data)
    doc["files"].append({"name": "export_parity.json", "sha256": hashlib.sha256(data).hexdigest(), "precision": "fp32"})
    with pytest.raises(ManifestError, match="parity"):
        intake.check_precision(load_manifest(write_doc(tmp_path, doc)))


def test_ncnn_valid_evidence_and_nonfinite_threshold_rejected(tmp_path):
    doc = ncnn_doc()
    report = {"ok": True, "frames": 1, "min_eval_frames": 1, "atol": 1e-3, "rtol": 1e-3,
              "min_box_iou": .95, "confidence_tolerance": .01,
              "results": [{"ok": True, "frame_sha256": "a" * 64, "max_abs_diff": .0001}]}

    def manifest():
        data = json.dumps(report).encode()
        (tmp_path / "export_parity.json").write_bytes(data)
        doc["files"] = [f for f in doc["files"] if f["name"] != "export_parity.json"]
        doc["files"].append({"name": "export_parity.json", "sha256": hashlib.sha256(data).hexdigest(),
                             "precision": "fp32"})
        return load_manifest(write_doc(tmp_path, doc))
    intake.check_precision(manifest())
    for key, bad in (("atol", float("inf")), ("min_box_iou", 0), ("confidence_tolerance", 1)):
        good = report[key]
        report[key] = bad
        with pytest.raises(ManifestError, match="parity"):
            intake.check_precision(manifest())
        report[key] = good
