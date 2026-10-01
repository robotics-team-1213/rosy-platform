"""Subject: learned lane-segmentation logits to lane evidence (D-356).

preprocess   BGR frame -> NCHW float32 per the manifest InputSpec
lane_evidence  logits -> (visible, error, confidence, class fractions)

Evidence rule: bottom 40 % of rows (near field). Target pixels are the
`drivable` role when it covers >= 2 % of that band, else `lane_marking`.
error = (target centroid x - W/2) / (W/2), clipped to [-1, 1]; positive means
the lane is right of centre, the LaneObservation convention in lane.py.
confidence = fraction of band rows with a target pixel x mean max-softmax on
target pixels. `wall` role pixels (D-373 decision 9) are never a target;
wall_fraction is their share of the near-field band.
Shadow evidence only: nothing here commands motion (D-209)."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .manifest import ClassSpec, InputSpec

NEAR_FIELD_FRACTION = 0.40
DRIVABLE_MIN_FRACTION = 0.02


class NonFiniteLogits(ValueError):
    """The model output holds NaN/inf; no evidence can be derived from it."""


@dataclass(frozen=True)
class LaneMaskEvidence:
    visible: bool
    error: float | None
    confidence: float
    class_fractions: dict
    wall_fraction: float = 0.0


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
        raise NonFiniteLogits("non-finite logits")
    x = logits[0].astype(np.float32)
    # Class fractions need labels only: argmax over logits, no softmax (D-373
    # CPU budget). Softmax (for confidence) runs on the near-field band alone;
    # it is per pixel, so the band's values equal a full-frame softmax's.
    labels = x.argmax(axis=0)
    total = labels.size
    fractions = {c.name: float((labels == c.index).sum()) / total for c in classes}

    h, w = labels.shape
    band = slice(int(h * (1 - NEAR_FIELD_FRACTION)), h)
    band_probs = _softmax(x[:, band])
    band_labels = band_probs.argmax(axis=0)
    band_conf = band_probs.max(axis=0)

    def _target(role: str) -> np.ndarray:
        idx = [c.index for c in classes if c.role == role]
        return np.isin(band_labels, idx) if idx else np.zeros_like(band_labels, bool)

    wall = _target("wall")
    wall_fraction = float(wall.mean())
    target = _target("drivable") & ~wall
    if target.mean() < DRIVABLE_MIN_FRACTION:
        target = _target("lane_marking") & ~wall
    if not target.any():
        return LaneMaskEvidence(False, None, 0.0, fractions, wall_fraction)

    _, xs = np.nonzero(target)
    half = w / 2.0
    error = float(np.clip((xs.mean() - (w - 1) / 2.0) / half, -1.0, 1.0))
    row_coverage = float(target.any(axis=1).mean())
    confidence = float(np.clip(row_coverage * band_conf[target].mean(), 0.0, 1.0))
    return LaneMaskEvidence(True, error, confidence, fractions, wall_fraction)


def lane_marking_mask(logits: np.ndarray, classes, size: tuple[int, int] | None = None) -> np.ndarray:
    """uint8 0/1 mask of pixels whose argmax class has the lane_marking role (D-408).

    size (width, height) resizes it with nearest neighbour to the camera frame, so the
    lane keeper reads the same pixel grid as its ground plane."""
    if logits.ndim != 4 or logits.shape[0] != 1 or logits.shape[1] != len(classes):
        raise ValueError(f"logits shape {logits.shape} does not match {len(classes)} classes")
    if not np.isfinite(logits).all():
        raise NonFiniteLogits("non-finite logits")
    labels = logits[0].argmax(axis=0)
    mask = np.isin(labels, [c.index for c in classes if c.role == "lane_marking"]).astype(np.uint8)
    if size is not None and (mask.shape[1], mask.shape[0]) != tuple(size):
        mask = cv2.resize(mask, tuple(size), interpolation=cv2.INTER_NEAREST)
    return mask
