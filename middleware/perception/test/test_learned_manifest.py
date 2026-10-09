"""D-356 model manifest: the only contract between external training and the robot."""

import hashlib
import json

import pytest

from control.sensing.perception.learned.manifest import (
    ManifestError,
    ROLES,
    load_manifest,
    verify_files,
)


def _manifest(**over):
    doc = {
        "schema": "rosy.perception.model/1",
        "model_revision": "lane-seg-20260930-abcdef12",
        "task": "lane_seg",
        "files": [{"name": "model.onnx", "sha256": "0" * 64, "precision": "fp32"}],
        "input": {"shape": [1, 3, 240, 320], "color": "rgb", "scale": 1 / 255,
                  "mean": [0.0, 0.0, 0.0], "std": [1.0, 1.0, 1.0], "layout": "nchw"},
        "output": {"layout": "nchw_logits", "classes": [
            {"index": 0, "name": "floor", "role": "background"},
            {"index": 1, "name": "line", "role": "lane_marking"},
        ]},
        "dataset": {"repo": "org/rosy-lane-seg-data", "revision": "a" * 40},
        "camera_profile_revision": "cam-rev-1",
        "metrics": {"val_iou": {"line": 0.8}},
        "trainer": "colab:lane_unet.ipynb@2026-09-30",
    }
    doc.update(over)
    return doc


def _write(tmp_path, doc):
    p = tmp_path / "model_manifest.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def test_valid_manifest_loads(tmp_path):
    m = load_manifest(_write(tmp_path, _manifest()))
    assert m.model_revision == "lane-seg-20260930-abcdef12"
    assert m.input.shape == (1, 3, 240, 320)
    assert m.role_indices("lane_marking") == (1,)
    assert m.onnx_file().name == "model.onnx"


@pytest.mark.parametrize("patch", [
    {"schema": "rosy.perception.model/2"},
    {"task": "detection"},
    {"model_revision": ""},
    {"files": []},
    {"input": {"shape": [1, 3, 240], "color": "rgb", "scale": 1, "mean": [0, 0, 0],
               "std": [1, 1, 1], "layout": "nchw"}},
    {"input": {"shape": [1, 3, 240, 320], "color": "hsv", "scale": 1, "mean": [0, 0, 0],
               "std": [1, 1, 1], "layout": "nchw"}},
    {"input": {"shape": [1, 3, 240, 320], "color": "rgb", "scale": 1, "mean": [0, 0, 0],
               "std": [1, 0, 1], "layout": "nchw"}},
])
def test_invalid_top_level_rejected(tmp_path, patch):
    with pytest.raises(ManifestError):
        load_manifest(_write(tmp_path, _manifest(**patch)))


def test_unknown_role_rejected(tmp_path):
    doc = _manifest()
    doc["output"]["classes"][1]["role"] = "lane"
    with pytest.raises(ManifestError, match="role"):
        load_manifest(_write(tmp_path, doc))


def test_missing_lane_marking_rejected(tmp_path):
    doc = _manifest()
    doc["output"]["classes"][1]["role"] = "drivable"
    with pytest.raises(ManifestError, match="lane_marking"):
        load_manifest(_write(tmp_path, doc))


def test_class_indices_must_be_dense(tmp_path):
    doc = _manifest()
    doc["output"]["classes"][1]["index"] = 2
    with pytest.raises(ManifestError, match="index"):
        load_manifest(_write(tmp_path, doc))


def test_roles_are_closed():
    assert ROLES == ("background", "lane_marking", "drivable", "stop_line", "ignore", "wall")


def test_wall_role_accepted(tmp_path):
    doc = _manifest()
    doc["output"]["classes"].append({"index": 2, "name": "wall", "role": "wall"})
    m = load_manifest(_write(tmp_path, doc))
    assert m.role_indices("wall") == (2,)


def test_verify_files_checks_sha256(tmp_path):
    data = b"onnx-bytes"
    (tmp_path / "model.onnx").write_bytes(data)
    doc = _manifest(files=[{"name": "model.onnx",
                            "sha256": hashlib.sha256(data).hexdigest(),
                            "precision": "fp32"}])
    m = load_manifest(_write(tmp_path, doc))
    verify_files(m)  # no raise
    (tmp_path / "model.onnx").write_bytes(b"tampered")
    with pytest.raises(ManifestError, match="sha256"):
        verify_files(m)


def test_file_names_cannot_escape_the_folder(tmp_path):
    doc = _manifest(files=[{"name": "../x.onnx", "sha256": "0" * 64, "precision": "fp32"}])
    with pytest.raises(ManifestError, match="name"):
        load_manifest(_write(tmp_path, doc))


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(files=["model.onnx"]),
    lambda d: d.update(files=[d["files"][0], dict(d["files"][0])]),
    lambda d: d["output"]["classes"][1].update(name="floor"),
    lambda d: d["dataset"].update(revision=""),
    lambda d: d["dataset"].update(repo=" "),
    lambda d: d.update(camera_profile_revision=""),
])
def test_more_invalid_manifests_rejected(tmp_path, mutate):
    doc = _manifest()
    mutate(doc)
    with pytest.raises(ManifestError):
        load_manifest(_write(tmp_path, doc))


def test_verify_files_rejects_path_outside_folder(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "outside.onnx").write_bytes(b"x")
    doc = _manifest(files=[{"name": "model.onnx", "sha256": hashlib.sha256(b"x").hexdigest(),
                            "precision": "fp32"}])
    p = tmp_path / "sub" / "model_manifest.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    m = load_manifest(p)
    link = tmp_path / "sub" / "model.onnx"
    try:
        link.symlink_to(tmp_path / "outside.onnx")
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(ManifestError, match="outside"):
        verify_files(m)


@pytest.mark.parametrize("rev", ["bad rev", "../x", "-x", ".hidden", "a/b", "a;b", "x\n"])
def test_model_revision_must_be_path_safe(tmp_path, rev):
    with pytest.raises(ManifestError):
        load_manifest(_write(tmp_path, _manifest(model_revision=rev)))


def test_check_revision_is_the_shared_rule():
    from control.sensing.perception.learned.manifest import check_revision
    assert check_revision("lane-seg-20260930-abcdef12") == "lane-seg-20260930-abcdef12"
    with pytest.raises(ManifestError):
        check_revision("a b")


def test_model_version_is_optional_and_parsed(tmp_path):
    """D-558: legacy manifests have none; a present one must be v<major>.<minor>.<NN>."""
    assert load_manifest(_write(tmp_path, _manifest())).model_version is None
    assert load_manifest(_write(tmp_path, _manifest(model_version="v13.1.00"))).model_version == "v13.1.00"
    for bad in ("v13.1.0", "13.1.00", 13, "v13.1.00; x"):
        with pytest.raises(ManifestError, match="model_version"):
            load_manifest(_write(tmp_path, _manifest(model_version=bad)))
