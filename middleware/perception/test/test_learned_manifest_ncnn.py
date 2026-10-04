"""D-431: explicit NCNN bundles; legacy ONNX readers reject schema 2."""

import hashlib
import json

import pytest

from control.sensing.perception.learned.manifest import ManifestError, load_manifest, verify_files
from test_learned_manifest_object_det import object_manifest


def ncnn_doc():
    return object_manifest(
        schema="rosy.perception.model/2", backend="ncnn",
        files=[{"name": name, "sha256": hashlib.sha256(b"fixture").hexdigest(), "precision": "fp32"}
               for name in ("model.param", "model.bin")],
        runtime={"param": "model.param", "bin": "model.bin", "input_blob": "in0", "output_blob": "out0",
                 "model_family": "yolov8", "model_version": "fixture", "exporter_version": "8.3.0",
                 "runtime_version": "1.0.0"})


def write_doc(folder, doc):
    (folder / "model_manifest.json").write_text(json.dumps(doc), encoding="utf-8")
    return folder


def test_legacy_onnx_defaults_and_ncnn_artifact_selection(tmp_path):
    assert load_manifest(write_doc(tmp_path, object_manifest())).backend == "onnx"
    model = load_manifest(write_doc(tmp_path, ncnn_doc()))
    assert model.backend == "ncnn"
    assert model.ncnn_files() == (tmp_path / "model.param", tmp_path / "model.bin")
    with pytest.raises(ManifestError, match="backend"):
        model.onnx_file()


@pytest.mark.parametrize("change", [
    {"schema": "rosy.perception.model/1"}, {"backend": "unknown"}, {"backend": None},
    {"task": "lane_seg"}, {"runtime": {}},
])
def test_invalid_backend_contract_is_refused(tmp_path, change):
    doc = ncnn_doc()
    doc.update(change)
    with pytest.raises(ManifestError):
        load_manifest(write_doc(tmp_path, doc))


@pytest.mark.parametrize("key,value", [
    ("param", "missing.param"), ("bin", "model.param"), ("input_blob", ""),
    ("output_blob", ""), ("model_family", "yolo26"), ("runtime_version", ""),
])
def test_bad_ncnn_runtime_metadata_is_refused(tmp_path, key, value):
    doc = ncnn_doc()
    doc["runtime"][key] = value
    with pytest.raises(ManifestError):
        load_manifest(write_doc(tmp_path, doc))


def test_ncnn_checks_both_files_and_hashes(tmp_path):
    m = load_manifest(write_doc(tmp_path, ncnn_doc()))
    (tmp_path / "model.param").write_bytes(b"fixture")
    with pytest.raises(ManifestError, match="missing"):
        verify_files(m)
    (tmp_path / "model.bin").write_bytes(b"altered")
    with pytest.raises(ManifestError, match="sha256"):
        verify_files(m)
    (tmp_path / "model.bin").write_bytes(b"fixture")
    verify_files(m)


def test_independently_verified_torchscript_lane_contract(tmp_path):
    doc = ncnn_doc()
    doc["task"] = "lane_seg"
    doc["runtime"]["model_family"] = "lane_torchscript"
    doc["output"] = {"layout": "nchw_logits", "classes": [
        {"index": 0, "name": "floor", "role": "background"},
        {"index": 1, "name": "line", "role": "lane_marking"}]}
    m = load_manifest(write_doc(tmp_path, doc))
    assert m.backend == "ncnn" and m.task == "lane_seg"


@pytest.mark.parametrize("name", ["../model.param", "..\\model.param", "/model.param"])
def test_paths_cannot_escape_the_bundle(tmp_path, name):
    doc = ncnn_doc()
    doc["files"][0]["name"] = name
    with pytest.raises(ManifestError):
        load_manifest(write_doc(tmp_path, doc))
