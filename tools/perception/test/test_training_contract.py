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
    with pytest.raises(ValueError):
        _write(tmp_path, classes=[("a", "background"), ("b", "nonsense")])


def test_export_cell_imports_without_torch():
    code = ("import sys; sys.path.insert(0, %r); import export_cell; "
            "assert callable(export_cell.export); assert 'torch' not in sys.modules"
            % str(TRAINING))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


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
    else:
        assert r.returncode == 1  # fake bytes are not a loadable ONNX
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


def test_check_manifest_ok_path_with_ort(tmp_path):
    torch = pytest.importorskip("torch")
    pytest.importorskip("onnxruntime")
    out = tmp_path / "m"
    doc = export_cell.export(torch.nn.Conv2d(3, 4, 3, padding=1), out, **KW)
    r = _check(out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.strip() == "OK " + doc["model_revision"]


def test_write_manifest_validates_before_writing(tmp_path):
    onnx = tmp_path / "src.onnx"
    onnx.write_bytes(b"x")
    out = tmp_path / "out"
    with pytest.raises(ValueError):
        export_cell.write_manifest(out, onnx_path=onnx,
                                   **dict(KW, classes=[("a", "background"), ("b", "bogus")]))
    with pytest.raises(ValueError):
        export_cell.write_manifest(out, onnx_path=onnx,
                                   **dict(KW, classes=[("a", "background"), ("b", "drivable")]))
    assert not out.exists()


def _mini_dataset(root, n_per_session=3):
    import json as _j
    frames = []
    for s in ("sA", "sB"):
        for i in range(n_per_session):
            for kind, ext in (("images", "jpg"), ("masks", "png")):
                f = root / kind / s / f"{i}.{ext}"
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(f"{kind}{s}{i}".encode())
            frames.append({"image": f"images/{s}/{i}.jpg", "mask": f"masks/{s}/{i}.png",
                           "session": s, "split": "val" if s == "sA" else "train"})
    doc = {"schema": "rosy.perception.dataset/1", "classes": [], "frames": frames,
           "deleted_indexes": [], "sources": []}
    (root / "manifest.json").write_text(_j.dumps(doc), encoding="utf-8")
    return doc


def test_stage_shards_from_manifest_and_rewrites_paths(tmp_path):
    src, dst = tmp_path / "ds", tmp_path / "stage"
    dst.mkdir()
    _mini_dataset(src)
    publish._stage(src, dst, 4)
    m = json.loads((dst / "manifest.json").read_text(encoding="utf-8"))
    assert len(m["frames"]) == 6
    shards = set()
    for k, fr in enumerate(m["frames"]):
        assert (dst / fr["image"]).is_file() and (dst / fr["mask"]).is_file()
        assert Path(fr["image"]).parent.name == Path(fr["mask"]).parent.name == f"shard_{k // 4:04d}"
        shards.add(Path(fr["image"]).parent.name)
        assert fr["session"] in fr["image"]
    assert shards == {"shard_0000", "shard_0001"}
    assert len({fr["image"] for fr in m["frames"]}) == 6  # same index in two sessions stays unique


def test_stage_fails_on_missing_file(tmp_path):
    src, dst = tmp_path / "ds", tmp_path / "stage"
    dst.mkdir()
    _mini_dataset(src)
    (src / "masks" / "sB" / "1.png").unlink()
    with pytest.raises(FileNotFoundError):
        publish._stage(src, dst, 1000)


def test_stage_keeps_session_prefixed_names_without_double_prefix(tmp_path):
    src, dst = tmp_path / "ds", tmp_path / "stage"
    dst.mkdir()
    frames = []
    for s in ("sA", "sB"):
        for kind, ext in (("images", "jpg"), ("masks", "png")):
            f = src / kind / s / f"{s}__000004.{ext}"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(b"x")
        frames.append({"image": f"images/{s}/{s}__000004.jpg",
                       "mask": f"masks/{s}/{s}__000004.png", "session": s, "split": "train"})
    (src / "manifest.json").write_text(json.dumps({"frames": frames}), encoding="utf-8")
    publish._stage(src, dst, 1000)
    m = json.loads((dst / "manifest.json").read_text(encoding="utf-8"))
    assert [Path(f["image"]).name for f in m["frames"]] == ["sA__000004.jpg", "sB__000004.jpg"]
    assert all((dst / f["mask"]).is_file() for f in m["frames"])
