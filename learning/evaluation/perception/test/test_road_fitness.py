"""D-665 source tests; synthetic arrays are not independent real/sim acceptance."""
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[4]
for directory in ("middleware/perception", "contracts/foundation", "operations/world/src",
                  "learning/evaluation/perception"):
    sys.path.insert(0, str(ROOT / directory))

from control.sensing.perception.learned.road_region import observed_road_region  # noqa: E402
from rosy.world.api import ObservationSnapshot, SnapshotValidity  # noqa: E402
from rosy.world.state.projections.road_region import road_region_input_errors  # noqa: E402
from road_fitness import _metrics, evaluate_frame, evaluate_model_frame, summarize_frames  # noqa: E402

CLASSES = [{"index": 0, "name": "floor", "role": "background"},
           {"index": 1, "name": "lane", "role": "lane_marking"},
           {"index": 2, "name": "road", "role": "drivable", "semantic": "road_surface/1"},
           {"index": 3, "name": "stop", "role": "stop_line"},
           {"index": 4, "name": "crosswalk", "role": "ignore"},
           {"index": 5, "name": "other_ignore", "role": "ignore"}]


def _labels(connected=False):
    labels = np.zeros((12, 12), np.int64)
    labels[:, :5] = labels[:, 7:] = 2
    labels[:, 5:7] = 1
    if connected:
        labels[9:, :] = 2
    return labels


def _snapshots():
    image = ObservationSnapshot("image", "camera", 1000, datetime(2026, 10, 11, tzinfo=timezone.utc),
                                "camera", "cal-v1", ("frame-sha",), SnapshotValidity.VALID, "tf-v1")
    anchor = replace(image, snapshot_id="anchor", source="pose_projection", evidence_refs=("image", "pose"))
    return image, anchor


def test_missing_anchor_image_reference_only_abstains_region():
    labels = _labels()
    image, anchor = _snapshots()
    road = (labels == 2).astype(np.uint8)
    region = road.copy()
    region[:, 7:] = 0
    report = evaluate_frame(labels, CLASSES, image, replace(anchor, evidence_refs=("other",)),
                            [[10, 2]], road, region, domain="real", conditions=[],
                            now_ns=1050, max_age_ns=100)
    assert "image_reference_missing" in report["input_errors"]
    assert report["road_surface"]["prediction_available"]
    assert not report["current_region"]["prediction_available"]


def test_fork_keeps_both_branches_without_selecting_a_drive_way():
    mask, reason = observed_road_region(_labels(True), CLASSES, ((10, 5),))
    assert reason == "ok" and mask[2, 2] and mask[2, 9]
    assert not mask[2, 5]


def test_region_excludes_other_road_and_does_not_fill_occlusions():
    labels = _labels()
    labels[6, 2] = 255
    mask, reason = observed_road_region(labels, CLASSES, ((10, 2),))
    assert reason == "ok" and mask[2, 2] and not mask[:, 7:].any()
    assert not mask[6, 2]


@pytest.mark.parametrize("paint", [3, 4, 5])
def test_only_declared_road_paint_connects_regions(paint):
    labels = _labels()
    labels[6, :5] = paint
    mask, reason = observed_road_region(labels, CLASSES, ((10, 2),))
    assert reason == "ok" and not mask[6].any()
    assert bool(mask[2, 2]) is (paint != 5)


@pytest.mark.parametrize("seeds,reason", [
    ((), "no_anchor"), (((20, 2),), "anchor_out_of_frame"),
    (((10, 5),), "anchor_not_on_observed_road"),
    (((10, 2), (10, 9)), "ambiguous_region"),
])
def test_membership_without_one_verified_component_abstains(seeds, reason):
    mask, actual = observed_road_region(_labels(), CLASSES, seeds)
    assert mask is None and actual == reason


@pytest.mark.parametrize("semantic", [None, "current_road_region/1", "trajectory_band/1"])
def test_region_logic_does_not_reinterpret_legacy_road_labels(semantic):
    classes = [dict(c) for c in CLASSES]
    classes[2]["semantic"] = semantic
    with pytest.raises(ValueError, match="road_surface"):
        observed_road_region(_labels(), classes, ((10, 2),))


@pytest.mark.parametrize("change,reason", [
    ({"captured_at_ns": 800}, "anchor_stale"),
    ({"captured_at_ns": 1100}, "anchor_future"),
    ({"captured_at_ns": 1010}, "capture_time_mismatch"),
    ({"validity": SnapshotValidity.UNKNOWN}, "anchor_invalid"),
    ({"frame_id": "map"}, "frame_mismatch"),
    ({"calibration_revision": "other"}, "calibration_mismatch"),
    ({"transform_revision": None}, "transform_unverified"),
    ({"transform_revision": "other"}, "transform_mismatch"),
    ({"evidence_refs": ("other-image",)}, "image_reference_missing"),
])
def test_world_checks_projection_inputs_before_region_logic(change, reason):
    image, anchor = _snapshots()
    assert road_region_input_errors(image, anchor, now_ns=1050, max_age_ns=100) == ()
    errors = road_region_input_errors(image, replace(anchor, **change), now_ns=1050, max_age_ns=100)
    assert reason in errors


def test_paired_evaluation_keeps_truth_denominators_when_region_abstains():
    image, anchor = _snapshots()
    labels = _labels()
    road_truth = (labels == 2).astype(np.uint8)
    region_truth = np.zeros_like(road_truth)
    region_truth[:, :5] = 1
    region_truth[0] = 255
    report = evaluate_frame(labels, CLASSES, image, anchor, (), road_truth, region_truth,
                            domain="real", conditions=("occlusion",), now_ns=1050, max_age_ns=100)
    assert report["domain"] == "real" and report["conditions"] == ["occlusion"]
    assert report["road_surface"]["iou"] == 1
    assert report["current_region"]["valid_truth_pixels"] == 132
    assert report["current_region"]["unknown_truth_pixels"] == 12
    assert report["current_region"]["scored_pixels"] == 0
    assert report["current_region"]["iou"] is None and report["region_reason"] == "no_anchor"
    assert report["fitness_verdict"] == "HOLD"


def test_invalid_image_keeps_truth_counts_without_scoring_either_target():
    image, anchor = _snapshots()
    labels = _labels()
    truth = (labels == 2).astype(np.uint8)
    report = evaluate_frame(labels, CLASSES, replace(image, validity=SnapshotValidity.INVALID),
                            anchor, ((10, 2),), truth, truth, domain="real", conditions=(),
                            now_ns=1050, max_age_ns=100)
    assert report["road_surface"]["valid_truth_pixels"] == labels.size
    assert report["road_surface"]["scored_pixels"] == report["current_region"]["scored_pixels"] == 0
    assert report["region_reason"] == "invalid_inputs" and "image_invalid" in report["input_errors"]


def test_contradictory_road_and_region_truth_is_not_scored():
    image, anchor = _snapshots()
    labels = _labels()
    road_truth = (labels == 2).astype(np.uint8)
    region_truth = np.ones_like(road_truth)
    with pytest.raises(ValueError, match="outside declared road truth"):
        evaluate_frame(labels, CLASSES, image, anchor, ((10, 2),), road_truth, region_truth,
                       domain="real", conditions=(), now_ns=1050, max_age_ns=100)


@pytest.mark.parametrize("seeds", [None, (None,), ((True, 2),), ((1.5, 2),)])
def test_malformed_projection_pixels_are_rejected(seeds):
    with pytest.raises(ValueError, match="anchors"):
        observed_road_region(_labels(), CLASSES, seeds)


def test_wrong_region_is_measured_separately_from_correct_whole_road():
    image, anchor = _snapshots()
    labels = _labels()
    road_truth = (labels == 2).astype(np.uint8)
    region_truth = np.zeros_like(road_truth)
    region_truth[:, 7:] = 1
    report = evaluate_frame(labels, CLASSES, image, anchor, ((10, 2),), road_truth, region_truth,
                            domain="simulation", conditions=(), now_ns=1050, max_age_ns=100)
    assert report["road_surface"]["iou"] == 1
    assert report["current_region"]["iou"] == 0
    assert report["current_region"]["other_region_included_pixels"] == 60
    assert report["current_region"]["self_region_missed_pixels"] == 60
    assert report["fitness_verdict"] == "HOLD"


def test_boundary_error_measures_known_contours_in_pixels():
    truth = np.zeros((10, 10), np.uint8)
    truth[3:7, 3:7] = 1
    pred = np.zeros_like(truth, dtype=bool)
    pred[3:7, 4:8] = True
    metrics = _metrics(pred, truth, truth.shape)
    assert metrics["true_positive_pixels"] == 12
    assert metrics["outside_truth_pixels"] == 84
    assert metrics["boundary_status"] == "ok"
    assert metrics["boundary_truth_pixels"] == metrics["boundary_predicted_pixels"] == 12
    assert metrics["boundary_mean_error_px"] == pytest.approx(0.5)


def test_unknown_neighbours_are_not_a_scored_boundary():
    truth = np.full((8, 8), 255, np.uint8)
    truth[3:5, 3:5] = 1
    metrics = _metrics(truth == 1, truth, truth.shape)
    assert metrics["boundary_status"] == "no_known_boundary"
    assert metrics["boundary_truth_pixels"] == 0
    assert metrics["boundary_mean_error_px"] is None


def test_missing_prediction_does_not_report_zero_boundary_error():
    truth = np.zeros((10, 10), np.uint8)
    truth[3:7, 3:7] = 1
    metrics = _metrics(np.zeros_like(truth, dtype=bool), truth, truth.shape)
    assert metrics["boundary_status"] == "missing_predicted_boundary"
    assert metrics["boundary_truth_pixels"] == 12
    assert metrics["boundary_mean_error_px"] is None


def test_summary_keeps_abstained_denominators_and_separates_domains():
    image, anchor = _snapshots()
    labels = _labels()
    truth = (labels == 2).astype(np.uint8)
    def frame(domain, seeds):
        return evaluate_frame(labels, CLASSES, image, anchor, seeds, truth, truth,
                              domain=domain, conditions=("junction",), now_ns=1050, max_age_ns=100)
    result = summarize_frames([frame("real", ((10, 2),)), frame("real", ()),
                               frame("simulation", ((10, 9),))])
    real = result["domains"]["real"]["current_region"]
    sim = result["domains"]["simulation"]["current_region"]
    assert real["valid_truth_pixels"] == 288 and real["truth_pixels"] == 240
    assert real["scored_pixels"] == 144 and real["scored_truth_pixels"] == 120
    assert real["scored_frames"] == 1 and real["abstained_frames"] == 1
    assert real["pixel_coverage"] == real["frame_coverage"] == 0.5
    assert real["truth_pixel_coverage"] == 0.5
    assert real["iou"] == 0.5 and sim["scored_frames"] == 1
    assert result["conditions"]["real"]["junction"]["frames"] == 2
    assert result["domains"]["real"]["region_reasons"] == {"ok": 1, "no_anchor": 1}
    assert result["fitness_verdict"] == "HOLD"


def test_summary_empty_domain_is_visible_and_iou_uses_pixel_counts():
    image, anchor = _snapshots()
    labels = _labels()
    truth = (labels == 2).astype(np.uint8)
    reports = []
    for target in (truth, np.where(truth, 255, 0).astype(np.uint8)):
        reports.append(evaluate_frame(labels, CLASSES, image, anchor, (), target,
                                      np.full_like(target, 255), domain="real", conditions=(),
                                      now_ns=1050, max_age_ns=100))
    result = summarize_frames(reports)
    assert result["domains"]["real"]["road_surface"]["iou"] == 1
    assert result["domains"]["simulation"]["frames"] == 0
    assert result["domains"]["simulation"]["road_surface"]["iou"] is None
    assert summarize_frames([])["domains"]["real"]["road_surface"]["pixel_coverage"] is None


def test_summary_preserves_other_region_errors_and_boundary_denominator():
    image, anchor = _snapshots()
    labels = _labels()
    road_truth = (labels == 2).astype(np.uint8)
    region_truth = np.zeros_like(road_truth)
    region_truth[:, 7:] = 1
    frames = [evaluate_frame(labels, CLASSES, image, anchor, seeds, road_truth, region_truth,
                             domain="real", conditions=(), now_ns=1050, max_age_ns=100)
              for seeds in (((10, 2),), ())]
    result = summarize_frames(frames)["domains"]["real"]
    metrics = result["current_region"]
    assert result["unconditioned_frames"] == 2
    assert metrics["other_region_truth_pixels"] == 120
    assert metrics["scored_other_region_truth_pixels"] == 60
    assert metrics["other_region_included_pixels"] == metrics["self_region_missed_pixels"] == 60
    assert metrics["boundary_scored_pixels"] > 0
    assert metrics["boundary_mean_error_px"] == pytest.approx(
        metrics["boundary_distance_sum_px"] / metrics["boundary_scored_pixels"])
    assert metrics["boundary_statuses"] == {"ok": 1, "abstained": 1}


def test_unknown_truth_is_unscorable_rather_than_an_abstained_prediction():
    image, anchor = _snapshots()
    labels = _labels()
    truth = np.full_like(labels, 255)
    frame = evaluate_frame(labels, CLASSES, image, anchor, ((10, 2),), truth, truth,
                           domain="real", conditions=(), now_ns=1050, max_age_ns=100)
    metrics = summarize_frames([frame])["domains"]["real"]["current_region"]
    assert metrics["prediction_frames"] == metrics["unscorable_truth_frames"] == 1
    assert metrics["scored_frames"] == metrics["abstained_frames"] == 0
    assert metrics["frame_coverage"] == 0 and metrics["pixel_coverage"] is None
    assert metrics["unknown_truth_pixels"] == labels.size and metrics["iou"] is None


@pytest.mark.parametrize("conditions", ["junction", None, {"junction": True}, [""]])
def test_conditions_require_an_explicit_sequence_of_names(conditions):
    image, anchor = _snapshots()
    labels = _labels()
    truth = (labels == 2).astype(np.uint8)
    with pytest.raises(ValueError, match="conditions"):
        evaluate_frame(labels, CLASSES, image, anchor, (), truth, truth,
                       domain="real", conditions=conditions, now_ns=1050, max_age_ns=100)


def _replay_model(tmp_path, crop=True, real_runtime=False):
    import hashlib
    import json
    import cv2
    from control.sensing.perception.learned.runner import LaneSegModel
    height = 4 if crop else 6
    labels = cv2.resize(_labels(), (6, 6), interpolation=cv2.INTER_NEAREST)[-height:]
    logits = np.eye(len(CLASSES), dtype=np.float32)[labels].transpose(2, 0, 1)[None]
    model_path = tmp_path / "model.onnx"
    if real_runtime:
        onnx = pytest.importorskip("onnx")
        pytest.importorskip("onnxruntime")
        graph = onnx.helper.make_graph([onnx.helper.make_node("Constant", [], ["logits"],
                                         value=onnx.numpy_helper.from_array(logits))], "fixture",
                                       [onnx.helper.make_tensor_value_info("input", onnx.TensorProto.FLOAT,
                                                                          [1, 3, height, 6])],
                                       [onnx.helper.make_tensor_value_info("logits", onnx.TensorProto.FLOAT,
                                                                          list(logits.shape))])
        doc = onnx.helper.make_model(graph, opset_imports=[onnx.helper.make_opsetid("", 17)], ir_version=9)
        model_path.write_bytes(doc.SerializeToString())
    else:
        model_path.write_bytes(b"synthetic-session-fixture")
    spec = {"shape": [1, 3, height, 6], "layout": "nchw", "color": "rgb", "scale": 1 / 255,
            "mean": [0, 0, 0], "std": [1, 1, 1]}
    if crop:
        spec["crop"] = {"from_frame": [6, 6], "rows": [2, 6]}
    raw = {"schema": "rosy.perception.model/1", "model_revision": "lane-seg-20261011-abcdef12",
           "task": "lane_seg", "input": spec,
           "files": [{"name": "model.onnx", "precision": "fp32",
                      "sha256": hashlib.sha256(model_path.read_bytes()).hexdigest()}],
           "output": {"layout": "nchw_logits", "classes": CLASSES},
           "dataset": {"repo": "fixture", "revision": "a" * 64}, "camera_profile_revision": "cal-v1"}
    (tmp_path / "model_manifest.json").write_text(json.dumps(raw), encoding="utf-8")
    if real_runtime:
        return LaneSegModel.open(tmp_path)
    from types import SimpleNamespace
    return LaneSegModel.open(tmp_path, session_factory=lambda path, threads:
                             SimpleNamespace(run=lambda x: logits.copy()))


@pytest.mark.parametrize("crop", [True, False])
@pytest.mark.parametrize("real_runtime", [False, True])
def test_model_replay_resizes_truth_and_anchor_with_the_model_roi(tmp_path, crop, real_runtime):
    model = _replay_model(tmp_path, crop, real_runtime)
    image, anchor = _snapshots()
    truth = (_labels() == 2).astype(np.uint8)
    region_truth = np.zeros_like(truth)
    region_truth[:, :5] = 1
    report = evaluate_model_frame(model, np.zeros((12, 12, 3), np.uint8), image, anchor,
                                  ((10, 2),), truth, region_truth, domain="real", conditions=(),
                                  now_ns=1050, max_age_ns=100)
    assert report["road_surface"]["iou"] == report["current_region"]["iou"] == 1
    assert report["road_surface"]["scored_pixels"] == (24 if crop else 36)
    assert report["preprocessing"]["excluded_truth_pixels"]["road_surface"] == (12 if crop else 0)
    assert report["preprocessing"]["seed_pixels"] == [[5, 1]]
    assert report["model_revision"] == model.model_revision
    assert report["fitness_verdict"] == "HOLD"
    metrics = summarize_frames([report])["domains"]["real"]["road_surface"]
    assert metrics["unknown_truth_pixels"] == 0
    assert metrics["pixel_coverage"] == 1
    assert metrics["full_grid_pixel_coverage"] == pytest.approx(2 / 3 if crop else 1)
    assert metrics["roi_excluded_target_truth_pixels"] == (10 if crop else 0)


def test_replay_unknown_roi_anchor_abstains_and_does_not_score_top_as_background(tmp_path):
    model = _replay_model(tmp_path)
    image, anchor = _snapshots()
    truth = (_labels() == 2).astype(np.uint8)
    report = evaluate_model_frame(model, np.zeros((12, 12, 3), np.uint8), image, anchor,
                                  ((0, 2),), truth, truth, domain="real", conditions=(),
                                  now_ns=1050, max_age_ns=100)
    assert report["current_region"]["scored_pixels"] == 0
    assert report["region_reason"] == "anchor_not_on_observed_road"
    assert report["road_surface"]["unknown_truth_pixels"] == 0
    assert report["road_surface"]["roi_excluded_valid_truth_pixels"] == 12


def test_replay_checks_truth_before_resizing_and_rejects_nonfinite_logits(tmp_path):
    model = _replay_model(tmp_path)
    image, anchor = _snapshots()
    truth = (_labels() == 2).astype(np.uint8)
    invalid = truth.copy()
    invalid[1, 1] = 7
    with pytest.raises(ValueError, match="truth"):
        evaluate_model_frame(model, np.zeros((12, 12, 3), np.uint8), image, anchor, (), invalid, truth,
                             domain="real", conditions=(), now_ns=1050, max_age_ns=100)
    model._session.run = lambda x: np.full((1, len(CLASSES), 4, 6), np.nan, np.float32)
    with pytest.raises(ValueError, match="logits"):
        evaluate_model_frame(model, np.zeros((12, 12, 3), np.uint8), image, anchor, (), truth, truth,
                             domain="real", conditions=(), now_ns=1050, max_age_ns=100)


def test_replay_refuses_contradictory_truth_even_outside_prediction_roi(tmp_path):
    model = _replay_model(tmp_path)
    image, anchor = _snapshots()
    road = (_labels() == 2).astype(np.uint8)
    region = road.copy()
    region[0, 6] = 1
    with pytest.raises(ValueError, match="outside declared road"):
        evaluate_model_frame(model, np.zeros((12, 12, 3), np.uint8), image, anchor, (), road, region,
                             domain="real", conditions=(), now_ns=1050, max_age_ns=100)


def test_replay_session_receives_only_preprocessed_rgb_image(tmp_path):
    model = _replay_model(tmp_path)
    image, anchor = _snapshots()
    truth = (_labels() == 2).astype(np.uint8)
    bgr = np.zeros((12, 12, 3), np.uint8)
    bgr[..., 2] = 255
    inputs = []
    run = model._session.run
    def capture(tensor):
        inputs.append(tensor.copy())
        return run(tensor)
    model._session.run = capture
    evaluate_model_frame(model, bgr, image, anchor, ((10, 2),), truth, truth,
                         domain="real", conditions=(), now_ns=1050, max_age_ns=100)
    assert len(inputs) == 1 and inputs[0].shape == (1, 3, 4, 6)
    assert (inputs[0][:, 0] == 1).all() and not inputs[0][:, 1:].any()


@pytest.mark.parametrize("seeds", [None, ((True, 2),), ((1.5, 2),)])
def test_replay_does_not_coerce_malformed_anchor_pixels(tmp_path, seeds):
    model = _replay_model(tmp_path)
    image, anchor = _snapshots()
    truth = (_labels() == 2).astype(np.uint8)
    with pytest.raises(ValueError, match="anchors"):
        evaluate_model_frame(model, np.zeros((12, 12, 3), np.uint8), image, anchor, seeds, truth, truth,
                             domain="real", conditions=(), now_ns=1050, max_age_ns=100)
