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
The road edge is a boundary line's centre (D-554 item 10): with a drivable
class, the inner half of each lane_left / lane_right run that touches drivable
in its row is drivable target too (lane_left: centre to right edge,
lane_right: left edge to centre). Models without drivable are unchanged.
Before that union, drivable is cut to the region reachable from the robot's
road ahead without crossing a lane line (D-566 item 4, lane_bounded_drivable).
Target components smaller than MIN_COMPONENT_PX are dropped before any of
that: in the 2026-10-02 audit speckle took `visible` from 0.896 to 1.000 and
offset jitter up 31 %; the filter brought it back to 0.885 and +1 %.
VisibleHysteresis is the per-stream visible latch; the node owns one.
Shadow evidence only: nothing here commands motion (D-209). Promotion past
shadow needs the D-205 replay bench, not these unit numbers."""

from __future__ import annotations

from dataclasses import dataclass, replace

import cv2
import numpy as np

from .manifest import ClassSpec, InputSpec

NEAR_FIELD_FRACTION = 0.40
DRIVABLE_MIN_FRACTION = 0.02
#: 8-connected target components below this many pixels are noise. 40 px at the
#: 320x240 model input, the same floor as lane_keep_lines.DENOISE_MIN_AREA_PX.
MIN_COMPONENT_PX = 40
#: lane_bounded_drivable: going up, a row's filled span may be at most this many
#: times the narrowest span below it (not just the row below, or 1.15 per row
#: compounds through a line gap), so a gap cannot leak the fill sideways.
#: Perspective narrows the road upward; 1.15 leaves room for curves.
MAX_ROW_GROWTH = 1.15
#: Seed search depth: the drivable pixel nearest the centre column within this
#: many rows of the lowest drivable row.
SEED_ROWS = 8
#: Shadow `visible` latch on confidence (audit 2026-10-02): on at 0.35, off below 0.25.
VISIBLE_ENTER = 0.35
VISIBLE_EXIT = 0.25


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


def _drop_small(mask: np.ndarray, min_px: int) -> np.ndarray:
    if min_px <= 1 or not mask.any():
        return mask
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    keep = np.zeros(n, bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= min_px
    return keep[labels]


def _row_runs(passable: np.ndarray, touch: np.ndarray) -> np.ndarray:
    """The contiguous runs of a passable row that contain a touch pixel."""
    run = np.cumsum(passable & ~np.r_[False, passable[:-1]]) * passable
    hit = np.unique(run[touch & passable])
    return np.isin(run, hit[hit > 0])


def lane_bounded_drivable(labels: np.ndarray, drivable_idx: int, lane_idxs, *, ignore_top: int = 0,
                          through_idxs=(), max_row_growth: float = MAX_ROW_GROWTH) -> np.ndarray:
    """Drivable pixels 4-connected to the road ahead without entering a lane pixel (D-566 item 4).

    Seed: the drivable pixel nearest the centre column in the lowest SEED_ROWS rows that hold
    drivable. The fill walks up and down from the seed row, row by row, keeping runs of passable
    pixels (drivable, or through_idxs such as crosswalk paint, never lane_idxs) that touch the
    kept run of the neighbouring row. Going up, a row wider than max_row_growth x the narrowest
    span below keeps only its run nearest the middle of the row below, clipped around it. Returns a bool mask of drivable pixels only."""
    drivable = labels == drivable_idx
    passable = (drivable | np.isin(labels, list(through_idxs))) & ~np.isin(labels, list(lane_idxs))
    passable[:ignore_top] = False
    out = np.zeros(labels.shape, bool)
    rows = np.flatnonzero((drivable & passable).any(axis=1))
    if not rows.size:
        return out
    centre = (labels.shape[1] - 1) / 2.0
    ys, xs = np.nonzero(drivable[max(rows.max() - SEED_ROWS + 1, 0):rows.max() + 1] & passable[
        max(rows.max() - SEED_ROWS + 1, 0):rows.max() + 1])
    pick = np.argmin(np.abs(xs - centre))
    seed_row = int(ys[pick]) + max(rows.max() - SEED_ROWS + 1, 0)
    seed = np.zeros(labels.shape[1], bool)
    seed[xs[pick]] = True
    out[seed_row] = _row_runs(passable[seed_row], seed)
    cols = np.arange(labels.shape[1])
    for step, stop in ((-1, ignore_top - 1), (1, labels.shape[0])):
        below = out[seed_row]
        narrowest = np.inf
        for row in range(seed_row + step, stop, step):
            keep = _row_runs(passable[row], below)
            if not keep.any():
                break
            if step < 0:
                span = np.flatnonzero(below)
                narrowest = min(narrowest, span[-1] - span[0] + 1)
                width = max_row_growth * narrowest
                mid = (span[0] + span[-1]) / 2.0
                kept = np.flatnonzero(keep)
                if kept[-1] - kept[0] + 1 > width:  # too wide: first the one run nearest mid,
                    keep = _row_runs(keep, cols == kept[np.argmin(np.abs(kept - mid))])
                    kept = np.flatnonzero(keep)
                if kept[-1] - kept[0] + 1 > width:  # then clip that run around mid
                    keep &= np.abs(cols - mid) <= width / 2.0
                    if not keep.any():
                        break
            out[row] = keep
            below = keep
    return out & drivable


def _with_inner_line_half(drivable: np.ndarray, labels: np.ndarray, classes) -> np.ndarray:
    index = {c.name: c.index for c in classes}
    if not drivable.any() or "lane_left" not in index or "lane_right" not in index:
        return drivable
    out = drivable.copy()
    w = labels.shape[1]
    for name in ("lane_left", "lane_right"):
        line = labels == index[name]
        for row in np.flatnonzero(line.any(axis=1)):
            step = np.diff(np.r_[0, line[row].astype(np.int8), 0])
            for a, b in zip(np.flatnonzero(step == 1), np.flatnonzero(step == -1) - 1):
                if name == "lane_left" and b + 1 < w and drivable[row, b + 1]:
                    out[row, (a + b + 1) // 2:b + 1] = True
                elif name == "lane_right" and a > 0 and drivable[row, a - 1]:
                    out[row, a:(a + b) // 2 + 1] = True
    return out


def lane_evidence(logits: np.ndarray, classes: tuple[ClassSpec, ...], *,
                  min_component_px: int = MIN_COMPONENT_PX) -> LaneMaskEvidence:
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
    drivable = _target("drivable")
    if drivable.any():  # D-566 item 4: only the road reachable without crossing a line
        roles = {}
        for c in classes:
            roles.setdefault(c.role, []).append(c.index)
        drivable = lane_bounded_drivable(band_labels, roles["drivable"][0], roles.get("lane_marking", ()),
                                         through_idxs=roles.get("ignore", ()))
    target = _drop_small(_with_inner_line_half(drivable & ~wall, band_labels, classes),
                         min_component_px)
    if target.mean() < DRIVABLE_MIN_FRACTION:
        target = _drop_small(_target("lane_marking") & ~wall, min_component_px)
    if not target.any():
        return LaneMaskEvidence(False, None, 0.0, fractions, wall_fraction)

    _, xs = np.nonzero(target)
    half = w / 2.0
    error = float(np.clip((xs.mean() - (w - 1) / 2.0) / half, -1.0, 1.0))
    row_coverage = float(target.any(axis=1).mean())
    confidence = float(np.clip(row_coverage * band_conf[target].mean(), 0.0, 1.0))
    return LaneMaskEvidence(True, error, confidence, fractions, wall_fraction)


class VisibleHysteresis:
    """Per-stream latch on `visible`: turns on when confidence reaches `enter`,
    off when the lane is gone or confidence drops below `exit`. Evidence that is
    latched off loses its error; confidence is passed through as measured."""

    def __init__(self, enter: float = VISIBLE_ENTER, exit: float = VISIBLE_EXIT):
        if not 0.0 <= exit <= enter <= 1.0:
            raise ValueError(f"need 0 <= exit ({exit}) <= enter ({enter}) <= 1")
        self.enter, self.exit = float(enter), float(exit)
        self.on = False

    def update(self, ev: LaneMaskEvidence) -> LaneMaskEvidence:
        threshold = self.exit if self.on else self.enter
        self.on = ev.visible and ev.confidence >= threshold
        return ev if self.on else replace(ev, visible=False, error=None)


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
