import hashlib
import json
import zipfile
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

import build
import prelabel

CLASSES = [
    {"index": 0, "name": "floor", "role": "background", "color": [0, 0, 0]},
    {"index": 1, "name": "line", "role": "lane_marking", "color": [230, 25, 75]},
]


def _frames_dir(root, session, indexes, with_meta=True):
    d = root / session
    (d / "frames").mkdir(parents=True)
    rows = []
    for i in indexes:
        cv2.imwrite(str(d / "frames" / f"{i:06d}.jpg"), np.full((8, 8, 3), i, np.uint8))
        rows.append(json.dumps({"index": i, "t": float(i), "source": "x",
                                "session": session, "side": {}}))
    (d / "frames.jsonl").write_text("\n".join(rows) + "\n")
    if with_meta:
        (d / "session.json").write_text(json.dumps({"session": session}))
    return d


def _export(root, masks):
    """masks: {name: (8,8) index array} -> CVAT-style colour PNGs."""
    d = root / "export"
    (d / "SegmentationClass").mkdir(parents=True)
    for name, idx in masks.items():
        rgb = np.array([c["color"] for c in CLASSES], np.uint8)[idx]
        cv2.imwrite(str(d / "SegmentationClass" / f"{name}.png"), rgb[..., ::-1])
    return d


def _mask():
    m = np.zeros((8, 8), np.uint8)
    m[:, 3:5] = 1
    return m


def test_colour_index_round_trip():
    idx = _mask()
    rgb = np.array([c["color"] for c in CLASSES], np.uint8)[idx]
    assert (build.colors_to_indices(rgb, CLASSES, "f.png") == idx).all()


def test_unknown_colour_names_file():
    rgb = np.zeros((4, 4, 3), np.uint8)
    rgb[0, 0] = (1, 2, 3)
    with pytest.raises(build.BuildError, match=r"bad\.png.*\(1,2,3\)"):
        build.colors_to_indices(rgb, CLASSES, "bad.png")


def test_two_sessions_split_without_overlap(tmp_path):
    a = _frames_dir(tmp_path, "s1", [0, 1])
    b = _frames_dir(tmp_path, "s2", [0])
    exp = _export(tmp_path, {"s1__000000": _mask(), "s1__000001": _mask(), "s2__000000": _mask()})
    out = tmp_path / "ds"
    m = build.build_dataset(exp, [a, b], CLASSES, out)
    assert m["schema"] == "rosy.perception.dataset/1"
    by_split = {}
    for f in m["frames"]:
        by_split.setdefault(f["split"], set()).add(f["session"])
    assert set(by_split) == {"train", "val"}
    assert not by_split["train"] & by_split["val"]
    assert m["sources"] == [{"session": "s1"}, {"session": "s2"}]
    saved = cv2.imread(str(out / "masks" / "s1" / "0.png"), cv2.IMREAD_UNCHANGED)
    assert (saved == _mask()).all()
    assert (out / "images" / "s2" / "0.jpg").is_file()
    assert json.loads((out / "manifest.json").read_text()) == m


def test_one_session_raises(tmp_path):
    a = _frames_dir(tmp_path, "s1", [0, 1])
    exp = _export(tmp_path, {"s1__000000": _mask(), "s1__000001": _mask()})
    with pytest.raises(build.BuildError, match="at least 2 sessions"):
        build.build_dataset(exp, [a], CLASSES, tmp_path / "ds")


def test_deleted_indexes_excluded(tmp_path):
    dirs = [_frames_dir(tmp_path, s, [0, 1]) for s in ("s1", "s2")]
    exp = _export(tmp_path, {f"{s}__00000{i}": _mask() for s in ("s1", "s2") for i in (0, 1)})
    m = build.build_dataset(exp, dirs, CLASSES, tmp_path / "ds", deleted_indexes=[0])
    assert {f["image"] for f in m["frames"]} == {"images/s1/1.jpg", "images/s2/1.jpg"}
    assert m["deleted_indexes"] == ["0"]


def test_deleted_by_session_index_keeps_other_sessions(tmp_path):
    a = _frames_dir(tmp_path, "s1", [0, 1])
    b = _frames_dir(tmp_path, "s2", [0, 1])
    exp = _export(tmp_path, {f"{s}__00000{i}": _mask() for s in ("s1", "s2") for i in (0, 1)})
    m = build.build_dataset(exp, [a, b], CLASSES, tmp_path / "ds", deleted_indexes=["s1/1"])
    assert {f["image"] for f in m["frames"]} == {
        "images/s1/0.jpg", "images/s2/0.jpg", "images/s2/1.jpg"}


def test_bare_index_ambiguous_across_dirs(tmp_path):
    a = _frames_dir(tmp_path, "s1", [0])
    b = _frames_dir(tmp_path, "s2", [0])
    exp = _export(tmp_path, {"000000": _mask()})
    with pytest.raises(build.BuildError, match="ambiguous"):
        build.build_dataset(exp, [a, b], CLASSES, tmp_path / "ds")


def test_cli_zip_and_classes_yaml(tmp_path):
    pytest.importorskip("yaml")
    a = _frames_dir(tmp_path, "s1", [0])
    b = _frames_dir(tmp_path, "s2", [0])
    exp = _export(tmp_path, {"s1__000000": _mask(), "s2__000000": _mask()})
    zpath = tmp_path / "e.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        for p in exp.rglob("*.png"):
            z.write(p, p.relative_to(exp).as_posix())
    yml = tmp_path / "classes.yaml"
    yml.write_text("classes:\n" + "".join(
        f"  - {{index: {c['index']}, name: {c['name']}, role: {c['role']}, color: {c['color']}}}\n"
        for c in CLASSES))
    out = tmp_path / "ds"
    assert build.main([str(zpath), "--frames", str(a), str(b), "--classes", str(yml),
                       "--out", str(out)]) == 0
    assert len(json.loads((out / "manifest.json").read_text())["frames"]) == 2


def test_rank_score():
    assert prelabel.rank_score(0.9, None) == pytest.approx(0.1)
    assert prelabel.rank_score(0.5, -0.3) == pytest.approx(0.8)
    assert prelabel.rank_score(0.2, 0.0) > prelabel.rank_score(0.9, 0.0)


def test_cvat_zip_layout(tmp_path):
    classes = [SimpleNamespace(index=0, name="floor"), SimpleNamespace(index=1, name="line")]
    path = tmp_path / "c.zip"
    prelabel.write_cvat_zip(path, classes, [("s1__000000", _mask())])
    with zipfile.ZipFile(path) as z:
        assert sorted(z.namelist()) == ["ImageSets/Segmentation/default.txt", "SegmentationClass/s1__000000.png",
                                        "labelmap.txt"]
        assert z.read("labelmap.txt").decode() == (
            "# label:color_rgb:parts:actions\nfloor:0,0,0::\nline:230,25,75::\n")
        assert z.read("ImageSets/Segmentation/default.txt").decode() == "s1__000000\n"
        png = cv2.imdecode(np.frombuffer(z.read("SegmentationClass/s1__000000.png"), np.uint8),
                           cv2.IMREAD_COLOR)
    assert tuple(png[0, 3][::-1]) == (230, 25, 75) and tuple(png[0, 0]) == (0, 0, 0)


def test_prelabel_end_to_end_real_onnx(tmp_path):
    pytest.importorskip("onnxruntime")
    onnx = pytest.importorskip("onnx")
    from onnx import TensorProto, helper
    w = np.zeros((2, 3, 1, 1), np.float32)
    w[1, 0, 0, 0] = 1.0  # class 1 logit = R channel; class 0 constant 0.5
    b = np.array([0.5, 0.0], np.float32)
    graph = helper.make_graph(
        [helper.make_node("Conv", ["x", "w", "b"], ["y"])], "g",
        [helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, 3, 24, 32])],
        [helper.make_tensor_value_info("y", TensorProto.FLOAT, [1, 2, 24, 32])],
        [helper.make_tensor("w", TensorProto.FLOAT, w.shape, w.flatten()),
         helper.make_tensor("b", TensorProto.FLOAT, b.shape, b)])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 8
    d = tmp_path / "model"
    d.mkdir()
    onnx.save(model, d / "model.onnx")
    (d / "model_manifest.json").write_text(json.dumps({
        "schema": "rosy.perception.model/1", "model_revision": "r1", "task": "lane_seg",
        "files": [{"name": "model.onnx", "precision": "fp32",
                   "sha256": hashlib.sha256((d / "model.onnx").read_bytes()).hexdigest()}],
        "input": {"shape": [1, 3, 24, 32], "color": "rgb", "scale": 1 / 255,
                  "mean": [0, 0, 0], "std": [1, 1, 1], "layout": "nchw"},
        "output": {"layout": "nchw_logits", "classes": [
            {"index": 0, "name": "floor", "role": "background"},
            {"index": 1, "name": "line", "role": "lane_marking"}]},
        "dataset": {"repo": "org/d", "revision": "a" * 40},
        "camera_profile_revision": "cam-1"}))
    fd = tmp_path / "fr"
    (fd / "frames").mkdir(parents=True)
    img = np.zeros((24, 32, 3), np.uint8)
    img[:, 20:28, 2] = 255
    cv2.imwrite(str(fd / "frames" / "000000.jpg"), img)
    cv2.imwrite(str(fd / "frames" / "000001.jpg"), np.zeros((24, 32, 3), np.uint8))
    side = {"perception/learned/shadow": {"confidence": 0.9, "error_delta": 0.4}}
    (fd / "frames.jsonl").write_text(
        json.dumps({"index": 0, "t": 0, "source": "x", "session": "s1", "side": side}) + "\n"
        + json.dumps({"index": 1, "t": 1, "source": "x", "session": "s1"}) + "\n")
    out = tmp_path / "out"
    assert prelabel.main([str(fd), "--model", str(d), "--out", str(out)]) == 0
    mask = cv2.imread(str(out / "masks" / "s1__000000.png"), cv2.IMREAD_UNCHANGED)
    assert mask[0, 24] == 1 and mask[0, 2] == 0
    lines = (out / "ranking.csv").read_text().splitlines()
    assert lines[0] == "name,score,confidence,error_delta" and len(lines) == 3
    assert "cvat_import.zip" in {p.name for p in out.iterdir()}
