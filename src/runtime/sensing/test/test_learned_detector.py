"""D-423 §2: the object_det backend -- letterbox, decode, NMS, DetectionEvidence-shaped packets."""
import hashlib
import json

import numpy as np
import pytest

from control.sensing.perception.learned.detector import (
    MAX_DETECTIONS, ObjectDetModel, decode, detection_packet, letterbox)
from control.sensing.perception.learned.manifest import OBJECT_CLASSES, ManifestError

H, W = 256, 320          # model input (stride 32)
C = len(OBJECT_CLASSES)


class FakeSession:
    """[1, 4 + C, A] like an ultralytics export; `boxes` are (cx, cy, w, h, class, score)."""

    def __init__(self, boxes=(), anchors=40, channels=4 + C, nan=False):
        self.boxes, self.anchors, self.channels, self.nan = boxes, anchors, channels, nan

    def run(self, x):
        assert x.shape == (1, 3, H, W) and x.dtype == np.float32
        out = np.zeros((1, self.channels, self.anchors), np.float32)
        for a, (cx, cy, w, h, cls, score) in enumerate(self.boxes):
            out[0, :4, a] = (cx, cy, w, h)
            out[0, 4 + cls, a] = score
        if self.nan:
            out[0, 0, 0] = np.nan
        return out


def model_dir(tmp_path, revision="object-det-20261003-00000001"):
    d = tmp_path / revision
    d.mkdir()
    (d / "model.onnx").write_bytes(b"fake")
    sha = hashlib.sha256(b"fake").hexdigest()
    (d / "model_manifest.json").write_text(json.dumps({
        "schema": "rosy.perception.model/1", "model_revision": revision, "task": "object_det",
        "files": [{"name": "model.onnx", "sha256": sha, "precision": "int8"}],
        "input": {"shape": [1, 3, H, W], "color": "rgb", "scale": 1 / 255,
                  "mean": [0, 0, 0], "std": [1, 1, 1], "layout": "nchw"},
        "output": {"layout": "yolo_cxcywh_scores", "classes": [
            {"index": i, "name": n, "role": "object"} for i, n in enumerate(OBJECT_CLASSES)]},
        "dataset": {"repo": "org/d", "revision": "a" * 40},
        "camera_profile_revision": "cam-1"}), encoding="utf-8")
    return d


def open_model(tmp_path, **kw):
    return ObjectDetModel.open(model_dir(tmp_path), session_factory=lambda p, t: FakeSession(**kw))


def test_letterbox_keeps_aspect_and_centres_the_frame():
    frame = np.full((240, 320, 3), 200, np.uint8)
    image, scale, pad_x, pad_y = letterbox(frame, W, H)
    assert image.shape == (H, W, 3) and scale == 1.0
    assert (pad_x, pad_y) == (0, 8)
    assert (image[:8] == 114).all() and (image[8:248] == 200).all() and (image[248:] == 114).all()


def test_decode_undoes_the_letterbox_and_normalises_to_the_frame():
    out = np.zeros((1, 4 + C, 3), np.float32)
    out[0, :4, 0] = (160, 128, 40, 60)          # model pixels; centre of the padded image
    out[0, 4 + 2, 0] = 0.9                      # cone
    found = decode(out, OBJECT_CLASSES, scale=1.0, pad=(0, 8), frame_size=(320, 240),
                   conf=0.25, iou=0.5)
    assert len(found) == 1
    d = found[0]
    assert d['label'] == 'cone' and d['confidence'] == pytest.approx(0.9)
    assert d['x'] == pytest.approx(140 / 320) and d['y'] == pytest.approx(90 / 240)
    assert d['w'] == pytest.approx(40 / 320) and d['h'] == pytest.approx(60 / 240)
    assert d['bbox_xyxy'] == pytest.approx([140, 90, 180, 150])


def test_low_scores_drop_and_nms_keeps_the_best_of_overlapping_boxes_per_class():
    out = np.zeros((1, 4 + C, 4), np.float32)
    out[0, :4, 0], out[0, 4 + 0, 0] = (100, 100, 40, 40), 0.8      # robot
    out[0, :4, 1], out[0, 4 + 0, 1] = (102, 101, 40, 40), 0.7      # same robot, suppressed
    out[0, :4, 2], out[0, 4 + 1, 2] = (102, 101, 40, 40), 0.6      # a box there: other class stays
    out[0, :4, 3], out[0, 4 + 3, 3] = (250, 60, 20, 20), 0.1       # under the threshold
    found = decode(out, OBJECT_CLASSES, scale=1.0, pad=(0, 0), frame_size=(320, 256),
                   conf=0.25, iou=0.5)
    assert sorted((d['label'], round(d['confidence'], 2)) for d in found) == [
        ('obstacle_box', 0.6), ('robot', 0.8)]


def test_boxes_are_clipped_inside_the_frame_and_degenerate_ones_dropped():
    out = np.zeros((1, 4 + C, 2), np.float32)
    out[0, :4, 0], out[0, 4, 0] = (5, 128, 40, 40), 0.9            # hangs off the left edge
    out[0, :4, 1], out[0, 4 + 1, 1] = (160, 3, 30, 0.0), 0.9       # zero height
    found = decode(out, OBJECT_CLASSES, scale=1.0, pad=(0, 8), frame_size=(320, 240),
                   conf=0.25, iou=0.5)
    assert len(found) == 1
    d = found[0]
    assert d['x'] == 0.0 and d['x'] + d['w'] <= 1.0 and d['y'] + d['h'] <= 1.0


def test_open_infer_and_packet(tmp_path):
    model = open_model(tmp_path, boxes=[(160, 128, 40, 60, 2, 0.9)])
    result = model.infer(np.zeros((240, 320, 3), np.uint8))
    assert [d['label'] for d in result.detections] == ['cone']
    packet = detection_packet(result, observed_at=12.5, seq=7, frame_size=(320, 240), fps=8.0,
                              ranges=[(0.42, 'L')])
    assert packet['model_revision'] == 'object-det-20261003-00000001'
    assert packet['seq'] == 7 and packet['input_width'] == 320 and packet['input_height'] == 240
    assert packet['inference_ms'] >= 0
    assert set(packet['detections'][0]) == {'label', 'x', 'y', 'w', 'h', 'confidence'}
    assert packet['ranges'] == [{'m': 0.42, 's': 'L'}]


def test_packet_validates_against_the_core_common_contract(tmp_path):
    detections = pytest.importorskip('core_common.protocol.detections')
    pytest.importorskip('pydantic')
    model = open_model(tmp_path, boxes=[(160, 128, 40, 60, 2, 0.9), (10, 10, 30, 30, 0, 0.6)])
    packet = detection_packet(model.infer(np.zeros((240, 320, 3), np.uint8)), observed_at=1.0,
                              seq=0, frame_size=(320, 240), fps=8.0, ranges=[None, None])
    parsed = detections.DetectionEvidence.model_validate(packet)
    assert len(parsed.detections) == 2
    assert packet['ranges'] == [None, None]


def test_packet_caps_the_detection_count(tmp_path):
    boxes = [(10 + 7 * (i % 40), 10 + 30 * (i // 40), 5, 5, i % C, 0.9) for i in range(120)]
    model = open_model(tmp_path, boxes=boxes, anchors=120)
    result = model.infer(np.zeros((240, 320, 3), np.uint8))
    packet = detection_packet(result, observed_at=1.0, seq=0, frame_size=(320, 240), fps=8.0)
    assert len(packet['detections']) == MAX_DETECTIONS
    assert 'ranges' not in packet


@pytest.mark.parametrize('kw', [dict(channels=4 + C + 1), dict(nan=True)])
def test_open_refuses_a_wrong_output_shape_or_nan_warmup(tmp_path, kw):
    with pytest.raises(ManifestError):
        open_model(tmp_path, **kw)


def test_open_refuses_a_lane_model(tmp_path):
    d = model_dir(tmp_path)
    doc = json.loads((d / 'model_manifest.json').read_text())
    doc.update(task='lane_seg', output={'layout': 'nchw_logits', 'classes': [
        {'index': 0, 'name': 'floor', 'role': 'background'},
        {'index': 1, 'name': 'line', 'role': 'lane_marking'}]})
    (d / 'model_manifest.json').write_text(json.dumps(doc))
    with pytest.raises(ManifestError, match='object_det'):
        ObjectDetModel.open(d, session_factory=lambda p, t: FakeSession())


def test_non_finite_output_after_warm_up_is_refused_per_frame(tmp_path):
    from control.sensing.perception.learned.lane_mask import NonFiniteLogits
    model = open_model(tmp_path)
    model._session = FakeSession(nan=True)
    with pytest.raises(NonFiniteLogits):
        model.infer(np.zeros((240, 320, 3), np.uint8))


def test_a_flood_of_candidates_is_capped_before_nms():
    """Review M2: an untrained or broken model can score every anchor; NMS stays bounded."""
    from control.sensing.perception.learned.detector import MAX_CANDIDATES
    anchors = 5000
    out = np.zeros((1, 4 + C, anchors), np.float32)
    out[0, 0] = np.tile(np.arange(0, 320, 4, dtype=np.float32), anchors // 80 + 1)[:anchors]
    out[0, 1] = np.repeat(np.arange(0, 256, 4, dtype=np.float32), 80)[:anchors]
    out[0, 2:4] = 3.0
    out[0, 4] = np.linspace(0.3, 0.99, anchors)
    found = decode(out, OBJECT_CLASSES, scale=1.0, pad=(0, 0), frame_size=(320, 256), conf=0.25, iou=0.5)
    assert MAX_CANDIDATES == 300
    assert len(found) <= MAX_CANDIDATES
    assert found[0]['confidence'] == pytest.approx(0.99)        # the best survive the cap


def test_detector_session_options_keep_the_pi_cores_quiet(monkeypatch):
    """Review L5: no spin-waiting threads and one inter-op thread, for this node's session only."""
    import sys
    import types
    from control.sensing.perception.learned import runner

    class Options:
        def __init__(self):
            self.entries = {}

        def add_session_config_entry(self, key, value):
            self.entries[key] = value

    made = {}

    class Session:
        def __init__(self, path, sess_options, providers):
            made['options'] = sess_options

        def get_inputs(self):
            return [types.SimpleNamespace(name='images')]

    fake = types.SimpleNamespace(SessionOptions=Options, InferenceSession=Session)
    monkeypatch.setitem(sys.modules, 'onnxruntime', fake)
    monkeypatch.setattr(runner, 'add_learned_site', lambda: None)
    from control.sensing.perception.learned.detector import detector_session
    detector_session('m.onnx', 2)
    opts = made['options']
    assert opts.intra_op_num_threads == 2 and opts.inter_op_num_threads == 1
    assert opts.entries == {'session.intra_op.allow_spinning': '0', 'session.inter_op.allow_spinning': '0'}
    runner._OrtSession('m.onnx', 2)                              # the lane session is untouched
    assert made['options'].entries == {}
