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
road ahead without crossing a lane line (D-566 item 4, lane_bounded_drivable),
with everything beyond lane_left / lane_right blocked on rows showing both (D-576).
Target components smaller than MIN_COMPONENT_PX are dropped before any of
that: in the 2026-10-02 audit speckle took `visible` from 0.896 to 1.000 and
offset jitter up 31 %; the filter brought it back to 0.885 and +1 %.
VisibleHysteresis is the per-stream visible latch; the node owns one.
Shadow evidence only: nothing here commands motion (D-209). Promotion past
shadow needs the D-205 replay bench, not these unit numbers.

on_floor (D-588 floor gate on the D-408 paint mask): lane_marking pixels the
model put on a wall, or along the wall's foot, are not lane paint.
1. Wall body: wall pixels of 8-connected wall components touching the top image
   row (a wall in view rises above the frame top; a stray speck on the floor
   does not). Per column, the foot is its lowest wall-body pixel.
2. From the foot the column walks down through wall, lane and plain floor
   (background role) pixels. It stops at any other class (drivable, stop line,
   crosswalk, ...) or after more than FOOT_GAP_PX plain floor pixels in a row.
   Every lane pixel above that stop is dropped: paint on the wall face, the
   seam, and a band the model paints just below the seam.
Tape stays wherever drivable floor or a wider floor gap separates it from the
wall. Columns without a wall body are untouched."""

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
#: times the widest unclipped span of the CLAMP_ROWS rows below it, so a gap in
#: a line cannot leak the fill sideways. Clipped rows never become the reference
#: (or 1.15 per row compounds through the gap), and a window rather than the
#: narrowest row keeps one noisy narrow row from choking the road above (v13.1.01
#: val 2026-10-09: near-centre 0.65 -> 0.15 with a narrowest-row reference).
#: Perspective narrows the road upward; 1.15 leaves room for curves.
MAX_ROW_GROWTH = 1.15
CLAMP_ROWS = 10
#: Seed search depth: rows above the lowest drivable row in which the seed
#: region is chosen: the centre column's, or when a line covers the centre
#: column there the one with most drivable pixels (D-576: a line across the
#: bottom centre must not leave the fill in a sliver beside it).
SEED_ROWS = 15
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
    frame_h = spec.crop[0] if spec.crop is not None else spec.height
    if bgr.shape[:2] != (frame_h, spec.width):
        bgr = cv2.resize(bgr, (spec.width, frame_h), interpolation=cv2.INTER_AREA)
    if spec.crop is not None:
        bgr = bgr[spec.crop[2]:spec.crop[3]]
    img = bgr[..., ::-1] if spec.color == "rgb" else bgr
    x = img.astype(np.float32) * np.float32(spec.scale)
    x = (x - np.asarray(spec.mean, np.float32)) / np.asarray(spec.std, np.float32)
    return np.ascontiguousarray(x.transpose(2, 0, 1)[None])


#: uncrop_logits: the background logit of rows outside an input crop (all others are 0).
UNCROPPED_BACKGROUND_LOGIT = 1.0


def uncrop_logits(logits: np.ndarray, spec: InputSpec, classes) -> np.ndarray:
    """Logits of a cropped-input model (manifest `input.crop`) placed back on the full frame
    grid: rows outside the crop are background (not predicted, so never lane or drivable).
    Without a crop the logits are returned as they are."""
    if spec.crop is None:
        return logits
    frame_h, _, row_from, row_to = spec.crop
    out = np.zeros(logits.shape[:2] + (frame_h, logits.shape[3]), np.float32)
    out[:, [c.index for c in classes if c.role == "background"][0]] = UNCROPPED_BACKGROUND_LOGIT
    out[:, :, row_from:row_to] = logits
    return out


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


def beyond_boundary(labels: np.ndarray, left_idx: int, right_idx: int) -> np.ndarray:
    """D-576 per-row rule: on rows showing both lines with max(lane_left) < min(lane_right),
    the pixels left of the leftmost lane_left and right of the rightmost lane_right.

    Endpoint extensions of the lines were tried first and cut the robot's own road at V corners,
    far line ends and crosswalks (sheets4 review, 2026-10-09), so other rows are left alone."""
    cols = np.arange(labels.shape[-1])
    left, right = labels == left_idx, labels == right_idx
    has = left.any(-1) & right.any(-1)
    first = np.where(left.any(-1), left.argmax(-1), -1)
    last = np.where(right.any(-1), labels.shape[-1] - 1 - right[..., ::-1].argmax(-1), labels.shape[-1])
    max_left = np.where(left.any(-1), labels.shape[-1] - 1 - left[..., ::-1].argmax(-1), -1)
    min_right = np.where(right.any(-1), right.argmax(-1), labels.shape[-1])
    rows = (has & (max_left < min_right))[..., None]
    return rows & ((cols < first[..., None]) | (cols > last[..., None]))


def lane_bounded_drivable(labels: np.ndarray, drivable_idx: int, lane_idxs, *, ignore_top: int = 0,
                          through_idxs=(), max_row_growth: float = MAX_ROW_GROWTH,
                          boundary: tuple[int, int] | None = None) -> np.ndarray:
    """Drivable pixels 4-connected to the road ahead without entering a lane pixel (D-566 item 4).

    Seed region: within the lowest SEED_ROWS rows that hold drivable, the region of the centre
    column's lowest drivable pixel, or when the centre column has none there (a line covers it)
    the region with most drivable pixels in those rows; seed at its pixel nearest the centre
    column. Region: the seed's 4-connected component of passable pixels (drivable, or
    through_idxs such as crosswalk paint, never lane_idxs). Going up from the seed row, a region
    row wider than max_row_growth x the widest unclipped span of the CLAMP_ROWS rows below keeps
    only its run nearest the middle of the row below, clipped around it (the first CLAMP_ROWS
    rows above the seed only build that reference). Below the seed row, runs
    touching the row above are kept. boundary=(lane_left, lane_right) first blocks what lies
    beyond those lines on rows showing both (beyond_boundary, D-576). Returns a bool mask of
    drivable pixels only."""
    drivable = labels == drivable_idx
    passable = (drivable | np.isin(labels, list(through_idxs))) & ~np.isin(labels, list(lane_idxs))
    if boundary is not None:
        passable &= ~beyond_boundary(labels, *boundary)
    passable[:ignore_top] = False
    out = np.zeros(labels.shape, bool)
    rows = np.flatnonzero((drivable & passable).any(axis=1))
    if not rows.size:
        return out
    low = max(rows.max() - SEED_ROWS + 1, 0)
    _, comp = cv2.connectedComponents(passable.astype(np.uint8), connectivity=4)
    ys, xs = np.nonzero(drivable[low:rows.max() + 1] & passable[low:rows.max() + 1])
    ids = comp[ys + low, xs]
    centre = ids[xs == labels.shape[1] // 2]
    # The centre column's region when the robot's front is drivable there; when a line covers it,
    # the region with most drivable pixels in the seed rows (D-576, drive frame 32).
    best = centre[np.argmax(ys[xs == labels.shape[1] // 2])] if centre.size else np.bincount(ids).argmax()
    pick = np.flatnonzero(ids == best)[np.argmin(np.abs(xs[ids == best] - (labels.shape[1] - 1) / 2.0))]
    seed_row, seed_col = int(ys[pick]) + low, int(xs[pick])
    region = comp == best
    cols = np.arange(labels.shape[1])
    out[seed_row] = _row_runs(passable[seed_row], cols == seed_col)
    below, recent = out[seed_row], []
    for row in range(seed_row - 1, ignore_top - 1, -1):
        warm = len(recent) < CLAMP_ROWS
        # The first CLAMP_ROWS rows only build the reference (one seed row can be a sliver), from
        # the runs touching the row below so an off-road strip joined further up stays out.
        keep = _row_runs(region[row], below) if warm else region[row].copy()
        kept = np.flatnonzero(keep)
        if not kept.size:
            break
        width = max_row_growth * max(recent[-CLAMP_ROWS:]) if not warm else np.inf
        if kept[-1] - kept[0] + 1 <= width:
            recent.append(int(kept[-1] - kept[0]) + 1)
        else:  # too wide: the one run nearest the middle of the row below, then clip around it
            span = np.flatnonzero(below)
            mid = (span[0] + span[-1]) / 2.0
            keep = _row_runs(keep, cols == kept[np.argmin(np.abs(kept - mid))])
            keep &= np.abs(cols - mid) <= width / 2.0
            if not keep.any():
                break
        out[row] = below = keep
    below = out[seed_row]
    for row in range(seed_row + 1, labels.shape[0]):
        below = out[row] = _row_runs(passable[row], below)
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
        names = {c.name: c.index for c in classes}
        drivable = lane_bounded_drivable(
            band_labels, roles["drivable"][0], roles.get("lane_marking", ()), through_idxs=roles.get("ignore", ()),
            boundary=(names["lane_left"], names["lane_right"]) if {"lane_left", "lane_right"} <= set(names) else None)
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


class NoWallClass(ValueError):
    """The floor gate needs a `wall` role class and the model has none."""


#: Step 2 of on_floor at the model's 240-row input, from the 2026-10-10 SIM replay (D-588): the
#: band 28e8454d paints below the wall seam sits 2-9 plain floor rows under the foot; the real tape
#: 7.5 cm off the wall has drivable floor or 13+ rows between.
FOOT_GAP_PX = 12


def on_floor(labels: np.ndarray, wall_index, lane_index, background_index,
             gap_px: int = FOOT_GAP_PX) -> np.ndarray:
    """bool HxW: True below the stop of each column's walk from the wall foot (module doc)."""
    h = labels.shape[0]
    wall = np.isin(labels, wall_index)
    lane = np.isin(labels, lane_index)
    floor = np.isin(labels, background_index)
    n, comp = cv2.connectedComponents(wall.astype(np.uint8), connectivity=8)
    top = np.zeros(n, bool)
    top[np.unique(comp[0])] = True
    top[0] = False
    body = top[comp]
    rows = np.arange(h)[:, None]
    has_body = body.any(axis=0)
    foot = np.where(has_body, h - 1 - np.argmax(body[::-1], axis=0), h)
    below = rows > foot[None, :]
    floor_run = rows - np.maximum.accumulate(np.where(floor, -1, rows), axis=0)
    stop = below & (~(wall | lane | floor) | (floor_run > gap_px))
    first = np.where(stop.any(axis=0), np.argmax(stop, axis=0), h)
    # a stop inside a long floor run ends the walk where that run began
    end = np.where(floor[np.minimum(first, h - 1), np.arange(labels.shape[1])] & (first < h),
                   first - gap_px - 1, first - 1)
    return rows > np.where(has_body, end, -1)[None, :]


def lane_marking_mask(logits: np.ndarray, classes, size: tuple[int, int] | None = None, *,
                      floor_gate: bool = False) -> np.ndarray:
    """uint8 0/1 mask of pixels whose argmax class has the lane_marking role (D-408).

    size (width, height) resizes it with nearest neighbour to the camera frame, so the
    lane keeper reads the same pixel grid as its ground plane. floor_gate drops lane
    pixels that are not floor paint (on_floor, D-588); it raises NoWallClass when the
    model has no wall role, so the caller falls back instead of trusting ungated paint."""
    if logits.ndim != 4 or logits.shape[0] != 1 or logits.shape[1] != len(classes):
        raise ValueError(f"logits shape {logits.shape} does not match {len(classes)} classes")
    if not np.isfinite(logits).all():
        raise NonFiniteLogits("non-finite logits")
    labels = logits[0].argmax(axis=0)
    lane_index = [c.index for c in classes if c.role == "lane_marking"]
    mask = np.isin(labels, lane_index)
    if floor_gate:
        wall_index = [c.index for c in classes if c.role == "wall"]
        if not wall_index:
            raise NoWallClass("floor gate needs a wall role class")
        mask &= on_floor(labels, wall_index, lane_index,
                         [c.index for c in classes if c.role == "background"])
    mask = mask.astype(np.uint8)
    if size is not None and (mask.shape[1], mask.shape[0]) != tuple(size):
        mask = cv2.resize(mask, tuple(size), interpolation=cv2.INTER_NEAREST)
    return mask
