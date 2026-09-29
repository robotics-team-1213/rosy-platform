"""Task 8: HF publish sharding and the trainer contract (D-356)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
TRAINING = ROOT / "tools" / "perception" / "training"
if str(TRAINING) not in sys.path:
    sys.path.insert(0, str(TRAINING))

import export_cell  # noqa: E402
import publish  # noqa: E402
from control.sensing.perception.learned.manifest import (  # noqa: E402
    ManifestError, load_manifest, verify_files)

CLASSES = [("background", "background"), ("lane", "lane_marking"),
           ("road", "drivable"), ("stop", "stop_line")]
KW = dict(classes=CLASSES, color="rgb", scale=1 / 255, mean=[0, 0, 0], std=[1, 1, 1],
          dataset_repo="org/ds", dataset_revision="a" * 40,
          camera_profile_revision="cam-1", trainer="colab-x")


def _write(tmp_path, **over):
    onnx = tmp_path / "src.onnx"
    onnx.write_bytes(b"fake-onnx")
    out = tmp_path / "out"
    kw = dict(KW, **over)
    doc = export_cell.write_manifest(out, onnx_path=onnx, date="20260930", **kw)
    return out, doc


def test_shard_paths_sizes_and_order():
    paths = [f"images/{i:05d}.jpg" for i in range(2501)]
    shards = publish.shard_paths(paths, size=1000)
    assert [len(s) for s in shards] == [1000, 1000, 501]
    assert [p for s in shards for p in s] == sorted(paths)
    assert publish.shard_paths(list(reversed(paths)), size=1000) == shards
    assert publish.shard_paths([]) == []


def test_write_manifest_valid_and_revision(tmp_path):
    out, doc = _write(tmp_path, val_iou={"lane": 0.5})
    m = load_manifest(out)
    verify_files(m)
    assert m.model_revision == doc["model_revision"]
    assert m.model_revision.startswith("lane-seg-20260930-")
    assert len(m.model_revision.split("-")[-1]) == 8
    assert (out / "model.onnx").read_bytes() == b"fake-onnx"
    assert m.role_indices("lane_marking") == (1,)
    assert doc["metrics"] == {"val_iou": {"lane": 0.5}}
    assert doc["trainer"] == "colab-x"


def test_write_manifest_rejects_bad_role(tmp_path):
    with pytest.raises(ManifestError):
        _write(tmp_path, classes=[("a", "background"), ("b", "nonsense")])


def test_export_cell_imports_without_torch():
    assert callable(export_cell.export)


def _check(folder):
    return subprocess.run([sys.executable, str(TRAINING / "check_manifest.py"), str(folder)],
                          capture_output=True, text=True)


def test_check_manifest_cli_ok_and_tampered(tmp_path):
    out, doc = _write(tmp_path)
    r = _check(out)
    # host without onnxruntime cannot open fake bytes; only manifest+hash are checked there
    try:
        import onnxruntime  # noqa: F401
        have_ort = True
    except ImportError:
        have_ort = False
    if not have_ort:
        assert r.returncode == 0, r.stdout + r.stderr
        assert r.stdout.startswith("OK " + doc["model_revision"])
    (out / "model.onnx").write_bytes(b"tampered")
    r = _check(out)
    assert r.returncode == 1
    assert "sha256" in (r.stdout + r.stderr)


def test_export_tiny_torch_model_opens(tmp_path):
    torch = pytest.importorskip("torch")
    pytest.importorskip("onnxruntime")
    from control.sensing.perception.learned.runner import LaneSegModel
    model = torch.nn.Conv2d(3, 4, 3, padding=1)
    out = tmp_path / "m"
    export_cell.export(model, out, **KW)
    m = LaneSegModel.open(out)
    assert m.manifest.input.shape == (1, 3, 240, 320)
    assert _check(out).returncode == 0
