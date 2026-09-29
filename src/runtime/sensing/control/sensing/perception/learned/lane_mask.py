"""Subject: learned lane-segmentation logits to lane evidence (D-356).

preprocess   BGR frame -> NCHW float32 per the manifest InputSpec
lane_evidence  logits -> (visible, error, confidence, class fractions)

Evidence rule: bottom 40 % of rows (near field). Target pixels are the
`drivable` role when it covers >= 2 % of that band, else `lane_marking`.
error = (target centroid x - W/2) / (W/2), clipped to [-1, 1]; positive means
the lane is right of centre, the LaneObservation convention in lane.py.
confidence = fraction of band rows with a target pixel x mean max-softmax on
target pixels. Shadow evidence only: nothing here commands motion (D-209)."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .manifest import ClassSpec, InputSpec

NEAR_FIELD_FRACTION = 0.40
DRIVABLE_MIN_FRACTION = 0.02


@dataclass(frozen=True)
class LaneMaskEvidence:
    visible: bool
    error: float | None
    confidence: float
    class_fractions: dict


def preprocess(bgr: np.ndarray, spec: InputSpec) -> np.ndarray:
    if bgr.ndim != 3 or bgr.shape[2] != 3:
        raise ValueError("expected an HxWx3 BGR frame")
    if bgr.shape[:2] != (spec.height, spec.width):
        bgr = cv2.resize(bgr, (spec.width, spec.height), interpolation=cv2.INTER_AREA)
    img = bgr[..., ::-1] if spec.color == "rgb" else bgr
    x = img.astype(np.float32) * np.float32(spec.scale)
    x = (x - np.asarray(spec.mean, np.float32)) / np.asarray(spec.std, np.float32)
    return np.ascontiguousarray(x.transpose(2, 0, 1)[None])


def _softmax(logits: np.ndarray) -> np.ndarray:
    z = logits - logits.max(axis=0, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=0, keepdims=True)


def lane_evidence(logits: np.ndarray, classes: tuple[ClassSpec, ...]) -> LaneMaskEvidence:
    if logits.ndim != 4 or logits.shape[0] != 1 or logits.shape[1] != len(classes):
        raise ValueError(f"logits shape {logits.shape} does not match {len(classes)} classes")
    if not np.isfinite(logits).all():
        raise ValueError("non-finite logits")
    probs = _softmax(logits[0].astype(np.float32))
    labels = probs.argmax(axis=0)
    total = labels.size
    fractions = {c.name: float((labels == c.index).sum()) / total for c in classes}

    h, w = labels.shape
    band = slice(int(h * (1 - NEAR_FIELD_FRACTION)), h)
    band_labels = labels[band]
    band_conf = probs.max(axis=0)[band]

    def _target(role: str) -> np.ndarray:
        idx = [c.index for c in classes if c.role == role]
        return np.isin(band_labels, idx) if idx else np.zeros_like(band_labels, bool)

    target = _target("drivable")
    if target.mean() < DRIVABLE_MIN_FRACTION:
        target = _target("lane_marking")
    if not target.any():
        return LaneMaskEvidence(False, None, 0.0, fractions)

    _, xs = np.nonzero(target)
    half = w / 2.0
    error = float(np.clip((xs.mean() - half) / half, -1.0, 1.0))
    row_coverage = float(target.any(axis=1).mean())
    confidence = float(np.clip(row_coverage * band_conf[target].mean(), 0.0, 1.0))
    return LaneMaskEvidence(True, error, confidence, fractions)
