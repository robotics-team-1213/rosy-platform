"""D-670 truth-free observation boundary, with a portable model session."""
from dataclasses import replace
from datetime import datetime, timezone
import json

import numpy as np
import pytest

from core_common.observation import ObservationSnapshot, SnapshotValidity
from control.sensing.perception.learned.manifest import ManifestError
from control.sensing.perception.learned.runner import LaneSegModel
from test_learned_runner import FakeSession, _model_dir


class RoadSession(FakeSession):
    def run(self, x):
        out = super().run(x)
        out[0, 2] = 10
        return out


def _model(tmp_path, semantic="road_surface/1"):
    folder = _model_dir(tmp_path)
    path = folder / "model_manifest.json"
    doc = json.loads(path.read_text())
    doc["input"].update(shape=[1, 3, 2, 4], crop={"from_frame": [4, 4], "rows": [2, 4]})
    doc["output"]["classes"].append({"index": 2, "name": "drivable", "role": "drivable",
                                      "semantic": semantic})
    path.write_text(json.dumps(doc), encoding="utf-8")
    return LaneSegModel.open(folder, session_factory=lambda *_: RoadSession(n_classes=3, lane_col=5))


def _snapshots():
    image = ObservationSnapshot("image-1", "camera", 1000, datetime.now(timezone.utc),
                                "camera-front", "cal-1", ("frame-1",), SnapshotValidity.VALID, "tf-1")
    anchor = replace(image, snapshot_id="anchor-1", source="projection", evidence_refs=("image-1",))
    return image, anchor


def _observe(model, image=None, anchor=None, seeds=None):
    from control.sensing.perception.learned.road_observation import observe_model_frame

    default_image, default_anchor = _snapshots()
    return observe_model_frame(model, np.zeros((8, 8, 3), np.uint8),
                               image or default_image, anchor or default_anchor,
                               [[6, 2]] if seeds is None else seeds, now_ns=1001, max_age_ns=100)


def test_raw_road_inference_keeps_crop_unknown(tmp_path):
    model = _model(tmp_path)
    labels, latency = model.infer_road_surface(np.zeros((8, 8, 3), np.uint8))
    assert labels.shape == (4, 4) and labels.dtype == np.uint8
    assert (labels[:2] == 255).all() and (labels[2:] == 2).all()
    assert latency >= 0
    with pytest.raises(ManifestError, match="drivable semantic"):
        model.infer(np.zeros((8, 8, 3), np.uint8))


@pytest.mark.parametrize("semantic", ["current_road_region/1", "trajectory_band/1"])
def test_raw_road_inference_refuses_other_meanings_before_session(tmp_path, semantic):
    model = _model(tmp_path, semantic)
    model._session.run = lambda _: pytest.fail("incompatible model reached inference")
    with pytest.raises(ValueError, match="road_surface"):
        model.infer_road_surface(np.zeros((8, 8, 3), np.uint8))


@pytest.mark.parametrize("fault", ["shape", "nan"])
def test_raw_road_inference_refuses_invalid_logits(tmp_path, fault):
    model = _model(tmp_path)
    output = np.full((1, 3, 2, 4), np.nan if fault == "nan" else 0, np.float32)
    model._session.run = lambda _: output[:, :, :1] if fault == "shape" else output
    with pytest.raises(ValueError, match="logits"):
        model.infer_road_surface(np.zeros((8, 8, 3), np.uint8))


def test_observation_has_no_truth_or_drive_inputs_and_reports_loaded_binding(tmp_path):
    model = _model(tmp_path)
    result = _observe(model)
    assert np.array_equal(result["road_surface"], result["current_region"])
    assert result["labels"][:2].tolist() == [[255] * 4] * 2
    assert result["region_reason"] == "ok" and result["input_errors"] == ()
    assert result["model_revision"] == model.model_revision
    assert result["camera_profile_revision"] == model.manifest.camera_profile_revision
    assert result["preprocessing"]["input"] == model.manifest.raw["input"]
    assert result["preprocessing"]["source_shape"] == [8, 8]
    assert result["preprocessing"]["prediction_shape"] == [4, 4]
    assert result["preprocessing"]["predicted_rows"] == [2, 4]
    assert result["preprocessing"]["seed_pixels"] == [[3, 1]]
    assert result["fitness_verdict"] == "HOLD" and result["infer_latency_ms"] >= 0


@pytest.mark.parametrize("fault", ["invalid", "stale", "future"])
def test_invalid_image_abstains_without_inference(tmp_path, fault):
    model = _model(tmp_path)
    image, anchor = _snapshots()
    image = (replace(image, validity=SnapshotValidity.INVALID) if fault == "invalid" else
             replace(image, captured_at_ns=1 if fault == "stale" else 2000))
    model._session.run = lambda _: pytest.fail("invalid image reached inference")
    result = _observe(model, image, anchor)
    assert all(result[k] is None for k in ("labels", "road_surface", "current_region", "infer_latency_ms"))
    assert f"image_{fault}" in result["input_errors"] and result["fitness_verdict"] == "HOLD"


@pytest.mark.parametrize("change,error", [({"frame_id": "other-frame"}, "frame_mismatch"),
                                         ({"evidence_refs": ("other",)}, "image_reference_missing")])
def test_invalid_anchor_keeps_road_but_abstains_region(tmp_path, change, error):
    image, anchor = _snapshots()
    result = _observe(_model(tmp_path), image, replace(anchor, **change))
    assert result["road_surface"] is not None and result["current_region"] is None
    assert error in result["input_errors"] and result["region_reason"] == "invalid_inputs"


def test_raw_road_labels_use_declared_channel_indices_when_manifest_rows_are_unsorted(tmp_path):
    model = _model(tmp_path)
    path = model.manifest.folder / "model_manifest.json"
    doc = json.loads(path.read_text())
    doc["output"]["classes"].reverse()
    path.write_text(json.dumps(doc), encoding="utf-8")
    model = LaneSegModel.open(model.manifest.folder,
                             session_factory=lambda *_: RoadSession(n_classes=3))
    labels, _ = model.infer_road_surface(np.zeros((8, 8, 3), np.uint8))
    assert (labels[2:] == 2).all()


@pytest.mark.parametrize("seeds,reason", [([], "no_anchor"), ([[0, 2]], "anchor_not_on_observed_road"),
                                        ([[8, 2]], "anchor_out_of_frame")])
def test_observation_never_supplies_a_fallback_anchor(tmp_path, seeds, reason):
    result = _observe(_model(tmp_path), seeds=seeds)
    assert result["current_region"] is None and result["region_reason"] == reason
    assert result["road_surface"] is not None


def test_raw_road_inference_rejects_invalid_frame_before_session(tmp_path):
    model = _model(tmp_path)
    model._session.run = lambda _: pytest.fail("invalid frame reached inference")
    with pytest.raises(ValueError, match="BGR"):
        model.infer_road_surface(np.zeros((8, 8, 3), np.float32))
