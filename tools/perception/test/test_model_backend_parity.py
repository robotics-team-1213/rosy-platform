"""D-431: real-frame comparison must fail on changed detections or non-finite output."""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))


def compare():
    from compare_backends import compare_outputs
    return compare_outputs


def test_comparison_refuses_nonfinite_and_shape_changes():
    ref = np.ones((1, 10, 3), np.float32)
    assert compare()(ref, ref.copy(), atol=1e-3, rtol=1e-3)["ok"]
    bad = ref.copy()
    bad[0, 0, 0] = np.nan
    assert not compare()(ref, bad, atol=1e-3, rtol=1e-3)["ok"]
    assert not compare()(ref, ref[:, :, :2], atol=1e-3, rtol=1e-3)["ok"]
    assert not compare()(ref, ref * 2, atol=1e-3, rtol=1e-3)["ok"]


def test_decoded_comparison_catches_class_count_and_box_changes():
    from compare_backends import detection_parity
    box = {"label": "robot", "bbox_xyxy": [10, 10, 40, 40], "confidence": .9}
    assert detection_parity([box], [box.copy()], min_iou=.95, confidence_tolerance=.01)
    for bad in ([], [dict(box, label="cone")], [dict(box, bbox_xyxy=[20, 20, 50, 50])],
                [dict(box, confidence=.8)]):
        assert not detection_parity([box], bad, min_iou=.95, confidence_tolerance=.01)


def test_cli_requires_real_frames_and_rejects_unsupported_ncnn_kinds():
    import convert
    ap = convert._arguments()
    common = ["m.pt", "--out", "out", "--dataset-repo", "r", "--dataset-revision", "a" * 40,
              "--camera-profile-revision", "c", "--trainer", "t", "--backend", "ncnn"]
    args = ap.parse_args(common + ["--kind", "ultralytics", "--task", "object_det"])
    assert "--frames" in convert._refusal(args)
    args = ap.parse_args(common + ["--kind", "torchscript", "--task", "object_det", "--frames", "frames"])
    assert "ultralytics" in convert._refusal(args)
    args = ap.parse_args(common + ["--kind", "ultralytics", "--task", "object_det", "--frames", "frames", "--int8"])
    assert "int8" in convert._refusal(args)


def test_torchscript_lane_export_is_a_separate_supported_path():
    import convert
    args = convert._arguments().parse_args([
        "m.pt", "--out", "out", "--kind", "torchscript", "--task", "lane_seg", "--backend", "ncnn",
        "--frames", "frames", "--classes", "classes.yaml", "--dataset-repo", "r", "--dataset-revision", "r1",
        "--camera-profile-revision", "c", "--trainer", "t"])
    assert convert._refusal(args) is None


def test_ncnn_revision_changes_with_inference_contract_and_evidence():
    import copy
    from export_ncnn import set_revision
    doc = {"task": "lane_seg", "input": {"color": "rgb"},
           "output": {"classes": [{"name": "line", "role": "lane_marking"}]}, "files": []}
    set_revision(doc)
    for key, value in (("input", {"color": "bgr"}),
                       ("output", {"classes": [{"name": "line", "role": "ignore"}]}),
                       ("files", [{"name": "export_parity.json", "sha256": "a" * 64}])):
        changed = copy.deepcopy(doc)
        changed[key] = value
        set_revision(changed)
        assert changed["model_revision"] != doc["model_revision"]
