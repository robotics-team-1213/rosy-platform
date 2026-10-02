"""D-423 §3.2: intake gates per task; object_det replays through the detector."""
import json
from pathlib import Path

import numpy as np
import pytest

from test_model_intake import intake  # path setup lives there
from control.sensing.perception.learned.detector import DetectResult
from control.sensing.perception.learned.lane_mask import NonFiniteLogits


def test_gate_file_has_an_object_det_section_without_lane_visibility():
    gate = intake.task_gate(intake.load_gate(intake.DEFAULT_GATE), "object_det")
    assert "min_visible_fraction" not in gate
    assert gate["max_nan_frames"] == 0 and gate["max_detections_per_frame_p95"] > 0
    lane = intake.task_gate(intake.load_gate(intake.DEFAULT_GATE), "lane_seg")
    assert lane["min_visible_fraction"] == 0.30 and "object_det" not in lane


class _Detector:
    model_revision = "object-det-r1"

    def __init__(self, per_frame=1, nan_at=None):
        self.n, self.per_frame, self.nan_at = 0, per_frame, nan_at

    def infer(self, bgr):
        self.n += 1
        if self.n == self.nan_at:
            raise NonFiniteLogits("nan")
        box = dict(label="cone", x=.1, y=.1, w=.1, h=.1, confidence=.9, bbox_xyxy=[1, 1, 2, 2])
        return DetectResult([box] * self.per_frame, 20.0, self.model_revision)


def test_detection_replay_counts_frames_boxes_and_nan(monkeypatch):
    monkeypatch.setattr(intake, "_video_frames", lambda path, n: iter([np.zeros((240, 320, 3), np.uint8)] * 4))
    stats = intake.replay_detections(_Detector(per_frame=2, nan_at=3), [Path("v.mp4")], 10)
    assert stats["frames"] == 4 and stats["nan_frames"] == 1 and stats["error_frames"] == 0
    assert stats["detections_per_frame"]["p95"] == 2 and stats["class_counts"] == {"cone": 6}


@pytest.mark.parametrize("stats,ok", [
    ({"frames": 10, "latency_ms": {"p50": 50.0}, "nan_frames": 0, "detections_per_frame": {"p95": 3}}, True),
    ({"frames": 10, "latency_ms": {"p50": 50.0}, "nan_frames": 0, "detections_per_frame": {"p95": 99}}, False),
])
def test_object_det_judge(stats, ok):
    gate = intake.task_gate(intake.load_gate(intake.DEFAULT_GATE), "object_det")
    assert (intake.judge(stats, gate)[0] == "pass") is ok


def test_run_routes_an_object_det_manifest_to_the_detector(tmp_path, monkeypatch):
    folder = tmp_path / "m"
    folder.mkdir()
    (folder / "model.onnx").write_bytes(b"x")
    fake = type("M", (), {"model_revision": "object-det-r1", "files": (), "task": "object_det"})()
    monkeypatch.setattr(intake, "load_manifest", lambda f: fake)
    monkeypatch.setattr(intake, "verify_files", lambda m: None)
    monkeypatch.setattr(intake.ObjectDetModel, "open", classmethod(lambda cls, f: _Detector()))
    monkeypatch.setattr(intake.LaneSegModel, "open", classmethod(
        lambda cls, f: pytest.fail("a detector must not open as a lane model")))
    monkeypatch.setattr(intake, "replay_videos", lambda gate, root: [Path("v.mp4")])
    monkeypatch.setattr(intake, "_video_frames", lambda path, n: iter([np.zeros((240, 320, 3), np.uint8)] * 3))
    rc, report = intake.run(str(folder), out=tmp_path / "out")
    assert rc == 0 and report["verdict"] == "pass" and report["task"] == "object_det"
    assert json.loads((tmp_path / "out" / "object-det-r1" / "intake_report.json").read_text())["task"] == "object_det"


# --- review 2026-10-03 M1: int8 distance from fp32 is gated for object_det ---

@pytest.mark.parametrize("rel,precision,ok", [(0.01, "int8", True), (0.2, "int8", False),
                                              (None, "int8", False), (None, "fp32", True)])
def test_object_det_int8_distance_is_gated(rel, precision, ok):
    gate = intake.task_gate(intake.load_gate(intake.DEFAULT_GATE), "object_det")
    assert 0 < gate["max_int8_vs_fp32_rel"] < 1
    stats = {"frames": 10, "latency_ms": {"p50": 50.0}, "nan_frames": 0,
             "detections_per_frame": {"p95": 3}, "precision": precision, "int8_vs_fp32_rel": rel}
    assert (intake.judge(stats, gate)[0] == "pass") is ok


def test_int8_metrics_come_from_the_manifest():
    manifest = type("M", (), {"files": (type("F", (), {"precision": "int8"})(),),
                              "raw": {"metrics": {"int8_vs_fp32_rel": 0.03}}})()
    assert intake.int8_metrics(manifest) == {"precision": "int8", "int8_vs_fp32_rel": 0.03}
