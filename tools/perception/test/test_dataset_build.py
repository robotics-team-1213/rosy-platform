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
        cv2.imwrite(str(d / "frames" / f"{i:06d}.jpg"), np.full((8, 8, 3), i * 10, np.uint8))
        rows.append(json.dumps({"index": i, "t": float(i), "source": "x",
                                "session": session, "side": {}}))
    (d / "frames.jsonl").write_text("\n".join(rows) + "\n")
    if with_meta:
        (d / "session.json").write_text(json.dumps({"session": session}))
    return d


def _labelmap(classes, colors=None):
    """CVAT-style labelmap; the background-role class is exported as 'background'."""
    lines = ["# label:color_rgb:parts:actions"]
    for c in classes:
        name = "background" if c["role"] == "background" else c["name"]
        r, g, b = (colors or {}).get(c["index"], c["color"])
        lines.append(f"{name}:{r},{g},{b}::")
    return "\n".join(lines) + "\n"


def _export(root, masks, classes=CLASSES, colors=None, sub=""):
    """masks: {name: (8,8) index array} -> CVAT-style export dir."""
    d = root / "export"
    (d / "SegmentationClass" / sub).mkdir(parents=True)
    (d / "labelmap.txt").write_text(_labelmap(classes, colors))
    table = {c["index"]: (colors or {}).get(c["index"], c["color"]) for c in classes}
    lut = np.array([table[i] for i in range(len(classes))], np.uint8)
    for name, idx in masks.items():
        cv2.imwrite(str(d / "SegmentationClass" / sub / f"{name}.png"), lut[idx][..., ::-1])
    return d


def _mask():
    m = np.zeros((8, 8), np.uint8)
    m[:, 3:5] = 1
    return m


def _names(*sessions, indexes=(0, 1)):
    return {f"{s}__{i:06d}": _mask() for s in sessions for i in indexes}


# --- colours: one source of truth ------------------------------------------------

def test_colour_index_round_trip():
    lut = {(0, 0, 0): 0, (230, 25, 75): 1}
    idx = _mask()
    rgb = np.array([[0, 0, 0], [230, 25, 75]], np.uint8)[idx]
    assert (build.colors_to_indices(rgb, lut, "f.png") == idx).all()


def test_unknown_colour_names_file():
    rgb = np.zeros((4, 4, 3), np.uint8)
    rgb[0, 0] = (1, 2, 3)
    with pytest.raises(build.BuildError, match=r"bad\.png.*\(1,2,3\)"):
        build.colors_to_indices(rgb, {(0, 0, 0): 0}, "bad.png")


def test_unknown_label_name_names_labelmap(tmp_path):
    a = _frames_dir(tmp_path, "s1", [0])
    b = _frames_dir(tmp_path, "s2", [0])
    exp = _export(tmp_path, _names("s1", "s2", indexes=(0,)))
    (exp / "labelmap.txt").write_text(_labelmap(CLASSES) + "cone:9,9,9::\n")
    with pytest.raises(build.BuildError, match=r"labelmap\.txt.*cone"):
        build.build_dataset(exp, [a, b], CLASSES, tmp_path / "ds")


def test_missing_labelmap_raises(tmp_path):
    a = _frames_dir(tmp_path, "s1", [0])
    b = _frames_dir(tmp_path, "s2", [0])
    exp = _export(tmp_path, _names("s1", "s2", indexes=(0,)))
    (exp / "labelmap.txt").unlink()
    with pytest.raises(build.BuildError, match="labelmap.txt"):
        build.build_dataset(exp, [a, b], CLASSES, tmp_path / "ds")


def test_recoloured_export_maps_by_label_name(tmp_path):
    a = _frames_dir(tmp_path, "s1", [0])
    b = _frames_dir(tmp_path, "s2", [0])
    exp = _export(tmp_path, _names("s1", "s2", indexes=(0,)),
                  colors={0: (10, 20, 30), 1: (200, 100, 50)})
    build.build_dataset(exp, [a, b], CLASSES, tmp_path / "ds")
    saved = cv2.imread(str(tmp_path / "ds" / "masks" / "s1" / "s1__000000.png"), cv2.IMREAD_UNCHANGED)
    assert (saved == _mask()).all()


def test_classes_need_one_background_role():
    bad = [dict(CLASSES[1], index=0), dict(CLASSES[1], index=1, name="line2")]
    with pytest.raises(build.BuildError, match="background"):
        build.label_to_index(bad)


def test_load_classes_colour_optional_for_prelabel(tmp_path):
    pytest.importorskip("yaml")
    yml = tmp_path / "c.yaml"
    yml.write_text("classes:\n  - {index: 0, name: floor, role: background}\n"
                   "  - {index: 1, name: line, role: lane_marking}\n")
    with pytest.raises(build.BuildError, match="color"):
        build.load_classes(yml)
    got = build.load_classes(yml, require_color=False)
    assert got[0]["color"] is None


def test_prelabel_uses_yaml_colours_and_default_fallback():
    model = [SimpleNamespace(index=0, name="floor", role="background"),
             SimpleNamespace(index=1, name="line", role="lane_marking"),
             SimpleNamespace(index=2, name="stop", role="stop_line")]
    yaml_classes = [
        {"index": 0, "name": "floor", "role": "background", "color": [0, 0, 0]},
        {"index": 1, "name": "line", "role": "lane_marking", "color": [1, 2, 3]},
        {"index": 2, "name": "stop", "role": "stop_line", "color": None}]
    resolved = prelabel.resolve_classes(yaml_classes, model)
    assert resolved[1]["color"] == [1, 2, 3]
    assert resolved[2]["color"] == list(prelabel.DEFAULT_PALETTE[2])
    text = prelabel.labelmap_text(resolved)
    assert text == ("# label:color_rgb:parts:actions\nbackground:0,0,0::\n"
                    f"line:1,2,3::\nstop:{','.join(map(str, prelabel.DEFAULT_PALETTE[2]))}::\n")


def test_prelabel_refuses_classes_disagreeing_with_model():
    model = [SimpleNamespace(index=0, name="floor", role="background"),
             SimpleNamespace(index=1, name="line", role="lane_marking")]
    bad = [dict(CLASSES[0]), dict(CLASSES[1], name="other")]
    with pytest.raises(build.BuildError, match="model"):
        prelabel.resolve_classes(bad, model)


def test_duplicate_colour_or_label_in_labelmap_rejected(tmp_path):
    for extra in ("cone:0,0,0::\n", "line:1,1,1::\n"):
        lm = tmp_path / "labelmap.txt"
        lm.write_text(_labelmap(CLASSES) + extra)
        with pytest.raises(build.BuildError, match="labelmap.txt.*duplicate"):
            build.parse_labelmap(lm, CLASSES + [{"index": 2, "name": "cone",
                                                 "role": "stop_line", "color": [5, 5, 5]}])


def test_duplicate_classes_rejected():
    dup_color = [CLASSES[0], dict(CLASSES[1], color=[0, 0, 0])]
    dup_name = [CLASSES[0], dict(CLASSES[1], name="floor")]
    model = [SimpleNamespace(index=0, name="floor", role="background"),
             SimpleNamespace(index=1, name="line", role="lane_marking")]
    with pytest.raises(build.BuildError, match="duplicate colo"):
        build.label_to_index(dup_color)
    with pytest.raises(build.BuildError, match="duplicate"):
        build.label_to_index(dup_name)
    with pytest.raises(build.BuildError, match="duplicate colo"):
        prelabel.resolve_classes(dup_color, model)


def test_default_palette_colour_clash_rejected():
    model = [SimpleNamespace(index=0, name="floor", role="background"),
             SimpleNamespace(index=1, name="line", role="lane_marking")]
    clash = [dict(CLASSES[0]), dict(CLASSES[1], color=None)]
    clash[0]["color"] = list(prelabel.DEFAULT_PALETTE[1])
    with pytest.raises(build.BuildError, match="duplicate colo"):
        prelabel.resolve_classes(clash, model)


def test_upload_image_copies_original_jpeg_bytes(tmp_path):
    src = tmp_path / "orig.jpg"
    cv2.imwrite(str(src), np.full((8, 8, 3), 77, np.uint8))
    dst = prelabel.write_upload_image(tmp_path / "o", "s1__000001", cv2.imread(str(src)), src)
    assert dst.read_bytes() == src.read_bytes()


# --- round trip: prelabel zip -> CVAT recolours -> build ---------------------------

def test_cvat_round_trip_identical_masks(tmp_path):
    a = _frames_dir(tmp_path, "s1", [0, 1])
    b = _frames_dir(tmp_path, "s2", [0, 1])
    items = [(n, m) for n, m in _names("s1", "s2").items()]
    items[1] = (items[1][0], np.fliplr(_mask()).copy())
    zpath = tmp_path / "cvat_import.zip"
    prelabel.write_cvat_zip(zpath, CLASSES, items)
    exp = tmp_path / "cvat_export"
    with zipfile.ZipFile(zpath) as z:
        z.extractall(exp)
    # simulate CVAT re-colouring: new colours in labelmap.txt and in the PNGs
    new = {"background": (12, 34, 56), "line": (200, 201, 202)}
    old = {"background": (0, 0, 0), "line": (230, 25, 75)}
    lines = ["# label:color_rgb:parts:actions"] + [f"{k}:{','.join(map(str, v))}::"
                                                   for k, v in new.items()]
    (exp / "labelmap.txt").write_text("\n".join(lines) + "\n")
    for p in (exp / "SegmentationClass").glob("*.png"):
        img = cv2.imread(str(p))
        for k in old:
            img[(img == np.array(old[k][::-1], np.uint8)).all(axis=2)] = new[k][::-1]
        cv2.imwrite(str(p), img)
    out = tmp_path / "ds"
    build.build_dataset(exp, [a, b], CLASSES, out)
    for name, mask in items:
        s, i = name.split("__")
        got = cv2.imread(str(out / "masks" / s / f"{s}__{int(i):06d}.png"), cv2.IMREAD_UNCHANGED)
        assert (got == mask).all(), name


def test_upload_images_use_exact_zip_names(tmp_path):
    prelabel.write_upload_image(tmp_path, "s1__000004", np.zeros((8, 8, 3), np.uint8), None)
    assert (tmp_path / "images" / "s1__000004.jpg").is_file()
    zpath = tmp_path / "c.zip"
    prelabel.write_cvat_zip(zpath, CLASSES, [("s1__000004", _mask())])
    with zipfile.ZipFile(zpath) as z:
        assert "SegmentationClass/s1__000004.png" in z.namelist()
        assert z.read("ImageSets/Segmentation/default.txt").decode() == "s1__000004\n"


def test_cvat_zip_layout_and_background_label(tmp_path):
    path = tmp_path / "c.zip"
    prelabel.write_cvat_zip(path, CLASSES, [("s1__000000", _mask())])
    with zipfile.ZipFile(path) as z:
        assert sorted(z.namelist()) == ["ImageSets/Segmentation/default.txt",
                                        "SegmentationClass/s1__000000.png", "labelmap.txt"]
        assert z.read("labelmap.txt").decode() == (
            "# label:color_rgb:parts:actions\nbackground:0,0,0::\nline:230,25,75::\n")
        png = cv2.imdecode(np.frombuffer(z.read("SegmentationClass/s1__000000.png"), np.uint8),
                           cv2.IMREAD_COLOR)
    assert tuple(png[0, 3][::-1]) == (230, 25, 75) and tuple(png[0, 0]) == (0, 0, 0)


# --- split / mapping / layout ------------------------------------------------------

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
    saved = cv2.imread(str(out / "masks" / "s1" / "s1__000000.png"), cv2.IMREAD_UNCHANGED)
    assert (saved == _mask()).all()
    assert json.loads((out / "manifest.json").read_text()) == m


def test_six_session_split(tmp_path):
    sessions = [f"s{n}" for n in range(6)]
    dirs = [_frames_dir(tmp_path, s, [0]) for s in sessions]
    exp = _export(tmp_path, _names(*sessions, indexes=(0,)))
    m = build.build_dataset(exp, dirs, CLASSES, tmp_path / "ds")
    split = {f["session"]: f["split"] for f in m["frames"]}
    assert {s for s, v in split.items() if v == "val"} == {"s0", "s5"}
    assert sum(v == "train" for v in split.values()) == 4


def test_index_is_not_position(tmp_path):
    a = _frames_dir(tmp_path, "s1", [5, 9])
    b = _frames_dir(tmp_path, "s2", [7])
    exp = _export(tmp_path, {"s1__000009": _mask(), "s2__000007": _mask()})
    out = tmp_path / "ds"
    m = build.build_dataset(exp, [a, b], CLASSES, out)
    assert {f["image"] for f in m["frames"]} == {"images/s1/s1__000009.jpg",
                                                "images/s2/s2__000007.jpg"}
    img = cv2.imread(str(out / "images" / "s1" / "s1__000009.jpg"))
    assert abs(int(img.mean()) - 90) <= 2


def test_one_session_raises(tmp_path):
    a = _frames_dir(tmp_path, "s1", [0, 1])
    exp = _export(tmp_path, _names("s1"))
    with pytest.raises(build.BuildError, match="at least 2 sessions"):
        build.build_dataset(exp, [a], CLASSES, tmp_path / "ds")


def test_nested_segmentation_class_folder(tmp_path):
    a = _frames_dir(tmp_path, "s1", [0])
    b = _frames_dir(tmp_path, "s2", [0])
    exp = _export(tmp_path, _names("s1", "s2", indexes=(0,)), sub="train")
    m = build.build_dataset(exp, [a, b], CLASSES, tmp_path / "ds")
    assert len(m["frames"]) == 2


def test_bare_index_ambiguous_across_dirs(tmp_path):
    a = _frames_dir(tmp_path, "s1", [0])
    b = _frames_dir(tmp_path, "s2", [0])
    exp = _export(tmp_path, {"000000": _mask()})
    with pytest.raises(build.BuildError, match="ambiguous"):
        build.build_dataset(exp, [a, b], CLASSES, tmp_path / "ds")


# --- deletes -------------------------------------------------------------------------

def _delete_setup(tmp_path):
    dirs = [_frames_dir(tmp_path, s, [0, 1]) for s in ("s1", "s2", "s3")]
    return dirs, _export(tmp_path, _names("s1", "s2", "s3"))


def test_delete_both_spellings_and_stored_normalised(tmp_path):
    dirs, exp = _delete_setup(tmp_path)
    m = build.build_dataset(exp, dirs, CLASSES, tmp_path / "ds",
                            deleted_indexes=["s1/1", "s2__000000", "s1__000001"])
    assert {f["image"] for f in m["frames"]} == {
        "images/s1/s1__000000.jpg", "images/s2/s2__000001.jpg",
        "images/s3/s3__000000.jpg", "images/s3/s3__000001.jpg"}
    assert m["deleted_indexes"] == ["s1__000001", "s2__000000"]


def test_delete_bare_int_rejected(tmp_path):
    dirs, exp = _delete_setup(tmp_path)
    with pytest.raises(build.BuildError, match="ambiguous|session"):
        build.build_dataset(exp, dirs, CLASSES, tmp_path / "ds", deleted_indexes=[0])


def test_delete_matching_nothing_rejected(tmp_path):
    dirs, exp = _delete_setup(tmp_path)
    with pytest.raises(build.BuildError, match="s9__000001"):
        build.build_dataset(exp, dirs, CLASSES, tmp_path / "ds", deleted_indexes=["s9/1"])


def test_cli_zip_and_classes_yaml(tmp_path):
    pytest.importorskip("yaml")
    a = _frames_dir(tmp_path, "s1", [0])
    b = _frames_dir(tmp_path, "s2", [0])
    exp = _export(tmp_path, _names("s1", "s2", indexes=(0,)))
    zpath = tmp_path / "e.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        for p in exp.rglob("*"):
            if p.is_file():
                z.write(p, p.relative_to(exp).as_posix())
    yml = tmp_path / "classes.yaml"
    yml.write_text("classes:\n" + "".join(
        f"  - {{index: {c['index']}, name: {c['name']}, role: {c['role']}, color: {c['color']}}}\n"
        for c in CLASSES))
    out = tmp_path / "ds"
    assert build.main([str(zpath), "--frames", str(a), str(b), "--classes", str(yml),
                       "--out", str(out)]) == 0
    assert len(json.loads((out / "manifest.json").read_text())["frames"]) == 2


# --- ranking ---------------------------------------------------------------------------

def _logits(shape_hw=(10, 10), lane_cols=None, sharp=8.0):
    """1x2xHxW logits; class 1 on lane_cols, class 0 elsewhere."""
    lg = np.zeros((1, 2) + shape_hw, np.float32)
    lg[0, 0] = sharp
    if lane_cols is not None:
        lg[0, 0, :, lane_cols] = 0
        lg[0, 1, :, lane_cols] = sharp
    return lg


MODEL_CLASSES = (SimpleNamespace(index=0, name="floor", role="background"),
                 SimpleNamespace(index=1, name="line", role="lane_marking"))


def test_delta_counts_only_for_same_revision_and_formula_is_shared():
    side = {"perception/learned/shadow": {"model_revision": "r1", "confidence": 0.9,
                                          "error_delta": 0.4}}
    lg = _logits(lane_cols=slice(4, 6))
    base = prelabel.score_frame(lg, MODEL_CLASSES, {}, "r1")
    same = prelabel.score_frame(lg, MODEL_CLASSES, side, "r1")
    other = prelabel.score_frame(lg, MODEL_CLASSES, side, "r2")
    assert same["recorded"] and same["error_delta"] == 0.4
    assert same["score"] == pytest.approx(base["score"] + 0.4)
    assert same["confidence"] == base["confidence"] != 0.9  # never the recorded confidence
    assert same["entropy"] == base["entropy"]
    assert not other["recorded"] and other["score"] == pytest.approx(base["score"])
    assert other["error_delta"] is None


def test_recomputed_score_rises_with_entropy_and_lane_shortage():
    lane = prelabel.score_frame(_logits(lane_cols=slice(4, 6)), MODEL_CLASSES, {}, "r")
    no_lane = prelabel.score_frame(_logits(), MODEL_CLASSES, {}, "r")
    fuzzy = prelabel.score_frame(_logits(lane_cols=slice(4, 6), sharp=0.1),
                                 MODEL_CLASSES, {}, "r")
    assert no_lane["lane_shortage"] > lane["lane_shortage"]
    assert no_lane["score"] > lane["score"]
    assert fuzzy["entropy"] > lane["entropy"] and fuzzy["score"] > lane["score"]


# --- end to end (needs onnxruntime) ---------------------------------------------------------

def test_prelabel_end_to_end_real_onnx(tmp_path):
    pytest.importorskip("onnxruntime")
    onnx = pytest.importorskip("onnx")
    pytest.importorskip("yaml")
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
    yml = tmp_path / "classes.yaml"
    yml.write_text("classes:\n" + "".join(
        f"  - {{index: {c['index']}, name: {c['name']}, role: {c['role']}, color: {c['color']}}}\n"
        for c in CLASSES))
    fd = tmp_path / "fr"
    (fd / "frames").mkdir(parents=True)
    img = np.zeros((24, 32, 3), np.uint8)
    img[:, 20:28, 2] = 255
    cv2.imwrite(str(fd / "frames" / "000000.jpg"), img)
    cv2.imwrite(str(fd / "frames" / "000001.jpg"), np.zeros((24, 32, 3), np.uint8))
    side = {"perception/learned/shadow": {"model_revision": "r1", "confidence": 0.9,
                                          "error_delta": 0.4}}
    (fd / "frames.jsonl").write_text(
        json.dumps({"index": 0, "t": 0, "source": "x", "session": "s1", "side": side}) + "\n"
        + json.dumps({"index": 1, "t": 1, "source": "x", "session": "s1"}) + "\n")
    out = tmp_path / "out"
    assert prelabel.main([str(fd), "--model", str(d), "--classes", str(yml),
                          "--out", str(out)]) == 0
    mask = cv2.imread(str(out / "masks" / "s1__000000.png"), cv2.IMREAD_UNCHANGED)
    assert mask[0, 24] == 1 and mask[0, 2] == 0
    assert (out / "images" / "s1__000000.jpg").is_file()
    lines = (out / "ranking.csv").read_text().splitlines()
    assert lines[0].startswith("name,score") and len(lines) == 3
    with zipfile.ZipFile(out / "cvat_import.zip") as z:
        assert "SegmentationClass/s1__000000.png" in z.namelist()


def test_roles_are_the_closed_contract_list_with_wall():
    wall = CLASSES + [{"index": 2, "name": "wall", "role": "wall", "color": [9, 9, 9]}]
    assert build.label_to_index(wall)["wall"] == 2
    bad = CLASSES + [{"index": 2, "name": "wall", "role": "walls", "color": [9, 9, 9]}]
    with pytest.raises(build.BuildError, match="role"):
        build.label_to_index(bad)


def test_prelabel_refuses_an_unknown_role_even_if_the_model_agrees():
    model = [SimpleNamespace(index=0, name="floor", role="background"),
             SimpleNamespace(index=1, name="line", role="lane_marking"),
             SimpleNamespace(index=2, name="x", role="bogus")]
    yaml_classes = [dict(CLASSES[0]), dict(CLASSES[1]),
                    {"index": 2, "name": "x", "role": "bogus", "color": [5, 5, 5]}]
    with pytest.raises(build.BuildError, match="role"):
        prelabel.resolve_classes(yaml_classes, model)
