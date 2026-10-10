"""D-423 §2: the object_det task in the rosy.perception.model/1 manifest."""

import json

import pytest

from control.sensing.perception.learned.manifest import (
    OBJECT_CLASSES, TASKS, ManifestError, load_manifest)


def object_manifest(**over):
    doc = {
        "schema": "rosy.perception.model/1",
        "model_revision": "object-det-20261003-abcdef12",
        "task": "object_det",
        "files": [{"name": "model.onnx", "sha256": "0" * 64, "precision": "int8"}],
        "input": {"shape": [1, 3, 256, 320], "color": "rgb", "scale": 1 / 255,
                  "mean": [0.0, 0.0, 0.0], "std": [1.0, 1.0, 1.0], "layout": "nchw"},
        "output": {"layout": "yolo_cxcywh_scores", "classes": [
            {"index": i, "name": name, "role": "object"} for i, name in enumerate(OBJECT_CLASSES)]},
        "dataset": {"repo": "org/rosy-object-det-data", "revision": "b" * 40},
        "camera_profile_revision": "cam-rev-1",
    }
    doc.update(over)
    return doc


def write(tmp_path, doc):
    path = tmp_path / "model_manifest.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def test_object_det_is_a_task_with_the_user_chosen_class_contract():
    assert TASKS == ("lane_seg", "object_det")
    assert OBJECT_CLASSES == ("robot", "obstacle_box", "cone", "traffic_light", "sign", "person")


def test_valid_object_det_manifest_loads(tmp_path):
    m = load_manifest(write(tmp_path, object_manifest()))
    assert m.task == "object_det"
    assert m.output_layout == "yolo_cxcywh_scores"
    assert [c.name for c in m.classes] == list(OBJECT_CLASSES)
    assert m.role_indices("object") == tuple(range(len(OBJECT_CLASSES)))


def test_lane_manifest_keeps_its_logits_layout(tmp_path):
    doc = object_manifest(task="lane_seg", output={"layout": "nchw_logits", "classes": [
        {"index": 0, "name": "floor", "role": "background"},
        {"index": 1, "name": "line", "role": "lane_marking"}]})
    assert load_manifest(write(tmp_path, doc)).output_layout == "nchw_logits"


def _classes(names):
    return [{"index": i, "name": n, "role": "object"} for i, n in enumerate(names)]


@pytest.mark.parametrize("output", [
    {"layout": "nchw_logits", "classes": _classes(OBJECT_CLASSES)},          # lane layout
    {"layout": "yolo_cxcywh_scores", "classes": _classes(OBJECT_CLASSES[:5])},  # a class missing
    {"layout": "yolo_cxcywh_scores", "classes": _classes(OBJECT_CLASSES[::-1])},  # order changed
    {"layout": "yolo_cxcywh_scores", "classes": _classes(OBJECT_CLASSES[:5] + ("person_feet",))},
    {"layout": "yolo_cxcywh_scores", "classes": [
        {"index": i, "name": n, "role": "background"} for i, n in enumerate(OBJECT_CLASSES)]},
])
def test_object_det_refuses_any_other_output_contract(tmp_path, output):
    with pytest.raises(ManifestError):
        load_manifest(write(tmp_path, object_manifest(output=output)))


def test_object_det_input_must_be_stride_32(tmp_path):
    bad = object_manifest()
    bad["input"] = dict(bad["input"], shape=[1, 3, 240, 320])   # 240 is not a multiple of 32
    with pytest.raises(ManifestError, match="multiple of 32"):
        load_manifest(write(tmp_path, bad))


def test_lane_seg_cannot_claim_the_detection_layout(tmp_path):
    doc = object_manifest(task="lane_seg")
    with pytest.raises(ManifestError):
        load_manifest(write(tmp_path, doc))
