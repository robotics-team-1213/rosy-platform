"""Subject: an object_det model to DetectionEvidence-shaped packets (D-423 §2).

ObjectDetModel  manifest + sha256 + session + warm-up shape check -> infer()
letterbox       the camera frame into the model input, aspect kept, 114 grey pad
decode          [1, 4 + C, A] centre-size boxes + class scores -> per-class NMS ->
                boxes normalised to the camera frame (the D-137 wire convention)
detection_packet  one frame of evidence (core_common.protocol.detections fields)
                plus an additive `ranges` list aligned with `detections`

Advisory evidence only (D-137): nothing in the driving path reads it. The session
is the same lazily imported onnxruntime CPU session the lane model uses."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

import cv2
import numpy as np

from .lane_mask import NonFiniteLogits, preprocess
from .manifest import ManifestError, ModelManifest, load_manifest, verify_files
from .runner import _OrtSession

# Wire caps from control/control/detection_evidence.py: 64 boxes per packet.
MAX_DETECTIONS = 64
# Review M2: an untrained or broken model can score every anchor (2100 at 320x256);
# per-class NMS is quadratic, so only the best MAX_CANDIDATES go into it.
MAX_CANDIDATES = 300
# Review L5: a 2-3 Hz detector must not keep Pi cores spinning between frames.
SESSION_CONFIG = {"session.intra_op.allow_spinning": "0", "session.inter_op.allow_spinning": "0"}
PAD_VALUE = 114  # the ultralytics letterbox grey, so training and runtime pad alike
CONFIDENCE = 0.25
IOU = 0.5


def letterbox(bgr: np.ndarray, width: int, height: int):
    """(image, scale, pad_x, pad_y): the frame resized to fit, centred on grey."""
    h, w = bgr.shape[:2]
    scale = min(width / w, height / h)
    new_w, new_h = int(round(w * scale)), int(round(h * scale))
    resized = bgr if (new_w, new_h) == (w, h) else cv2.resize(
        bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)
    pad_x, pad_y = (width - new_w) // 2, (height - new_h) // 2
    image = np.full((height, width, 3), PAD_VALUE, np.uint8)
    image[pad_y:pad_y + new_h, pad_x:pad_x + new_w] = resized
    return image, scale, pad_x, pad_y


def _iou(box, others):
    x0 = np.maximum(box[0], others[:, 0])
    y0 = np.maximum(box[1], others[:, 1])
    x1 = np.minimum(box[2], others[:, 2])
    y1 = np.minimum(box[3], others[:, 3])
    inter = np.clip(x1 - x0, 0, None) * np.clip(y1 - y0, 0, None)
    area = (box[2] - box[0]) * (box[3] - box[1])
    areas = (others[:, 2] - others[:, 0]) * (others[:, 3] - others[:, 1])
    return inter / np.maximum(area + areas - inter, 1e-9)


def decode(output, names, *, scale, pad, frame_size, conf=CONFIDENCE, iou=IOU):
    """Detections sorted by confidence: label, normalised x/y/w/h, confidence, bbox_xyxy."""
    out = np.asarray(output, np.float32)[0].T                  # [A, 4 + C]
    scores = out[:, 4:]
    cls = scores.argmax(axis=1)
    best = scores[np.arange(len(cls)), cls]
    keep = best >= conf
    boxes, cls, best = out[keep, :4], cls[keep], best[keep]
    if len(best) > MAX_CANDIDATES:
        top = np.argpartition(-best, MAX_CANDIDATES - 1)[:MAX_CANDIDATES]
        boxes, cls, best = boxes[top], cls[top], best[top]
    fw, fh = frame_size
    xyxy = np.stack([boxes[:, 0] - boxes[:, 2] / 2, boxes[:, 1] - boxes[:, 3] / 2,
                     boxes[:, 0] + boxes[:, 2] / 2, boxes[:, 1] + boxes[:, 3] / 2], axis=1)
    xyxy = (xyxy - np.array([pad[0], pad[1], pad[0], pad[1]], np.float32)) / scale
    xyxy = np.clip(xyxy, 0, [fw, fh, fw, fh])
    found = []
    for c in np.unique(cls):
        idx = np.where(cls == c)[0]
        idx = idx[np.argsort(-best[idx], kind='stable')]
        while len(idx):
            i, idx = idx[0], idx[1:]
            x0, y0, x1, y1 = (float(v) for v in xyxy[i])
            if x1 - x0 > 0 and y1 - y0 > 0:
                found.append(dict(label=names[int(c)], x=x0 / fw, y=y0 / fh,
                                  w=min((x1 - x0) / fw, 1.0 - x0 / fw),
                                  h=min((y1 - y0) / fh, 1.0 - y0 / fh),
                                  confidence=min(float(best[i]), 1.0),
                                  bbox_xyxy=[x0, y0, x1, y1]))
            if len(idx):
                idx = idx[_iou(xyxy[i], xyxy[idx]) < iou]
    found.sort(key=lambda d: -d['confidence'])
    return found


def detector_session(path, threads):
    """The object_det onnxruntime CPU session: no spin-waiting, one inter-op thread."""
    return _OrtSession(path, threads, inter_op=1, config=SESSION_CONFIG)


@dataclass(frozen=True)
class DetectResult:
    detections: list
    latency_ms: float
    model_revision: str


class ObjectDetModel:
    def __init__(self, manifest: ModelManifest, session, *, conf=CONFIDENCE, iou=IOU):
        self.manifest, self._session, self._conf, self._iou = manifest, session, conf, iou
        self._names = tuple(c.name for c in manifest.classes)

    @property
    def model_revision(self) -> str:
        return self.manifest.model_revision

    @classmethod
    def open(cls, folder, *, session_factory: Callable | None = None, threads: int = 2,
             conf=CONFIDENCE, iou=IOU) -> "ObjectDetModel":
        manifest = load_manifest(folder)
        if manifest.task != "object_det":
            raise ManifestError(f"task {manifest.task}: this slot needs object_det")
        verify_files(manifest)
        factory = session_factory or detector_session
        try:
            session = factory(manifest.onnx_file(), threads)
        except Exception as exc:
            raise ManifestError(f"session: {exc}") from exc
        out = np.asarray(session.run(np.zeros(manifest.input.shape, np.float32)))
        if out.ndim != 3 or out.shape[:2] != (1, 4 + len(manifest.classes)):
            raise ManifestError(f"output shape {tuple(out.shape)} != (1, {4 + len(manifest.classes)}, A)")
        if not np.isfinite(out).all():
            raise ManifestError("warm-up produced non-finite output")
        return cls(manifest, session, conf=conf, iou=iou)

    def infer(self, bgr: np.ndarray) -> DetectResult:
        t0 = time.perf_counter()
        spec = self.manifest.input
        image, scale, pad_x, pad_y = letterbox(bgr, spec.width, spec.height)
        out = self._session.run(preprocess(image, spec))
        if not np.isfinite(out).all():
            raise NonFiniteLogits("object_det output holds NaN/inf")
        found = decode(out, self._names, scale=scale, pad=(pad_x, pad_y),
                       frame_size=(bgr.shape[1], bgr.shape[0]), conf=self._conf, iou=self._iou)
        return DetectResult(found[:MAX_DETECTIONS], (time.perf_counter() - t0) * 1000.0,
                            self.manifest.model_revision)


def detection_packet(result: DetectResult, *, observed_at, seq, frame_size, fps, ranges=None):
    """core_common DetectionEvidence fields; `ranges` (D-423) aligns with detections."""
    detections = result.detections[:MAX_DETECTIONS]
    packet = {
        'model_revision': result.model_revision, 'observed_at': float(observed_at),
        'seq': int(seq), 'input_width': int(frame_size[0]), 'input_height': int(frame_size[1]),
        'input_fps': float(fps), 'inference_ms': round(float(result.latency_ms), 2),
        'detections': [{k: d[k] for k in ('label', 'x', 'y', 'w', 'h', 'confidence')}
                       for d in detections],
    }
    if ranges is not None:
        packet['ranges'] = [None if r is None or r[0] is None else
                            {'m': round(float(r[0]), 3), 's': r[1]} for r in ranges[:len(detections)]]
    return packet
