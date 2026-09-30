"""Overhead camera to site-map registration proposal from painted lane lines (D-375).

Matches the known lane paint of the site map (``road_lines.stl``: metres,
Z-up, map frame of ``lane_graph.yaml``) against the white paint seen in one
camera frame and proposes an image-to-map homography. No printed markers.

Like the D-360 field proposal, the result is a *proposal* for operator review:
it never feeds sightings, ``CameraMap``, task acceptance, or motion. A weak or
ambiguous fit is a rejection with a reason, never a guessed pose.

Pipeline: thin-white-line mask -> dominant line yaw -> coarse similarity
search (4 rotations x mirror x scale, normalised cross-correlation of blurred
masks) -> ECC homography refinement of the best candidates -> tolerance-band
precision/recall score -> coverage and cut sides of the map outside the frame.
"""

from __future__ import annotations

import math
import struct
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

REGISTER_VERSION = "paint-register/1"

# Refinement and scoring work on an image this wide; the coarse search compares
# the map at a fixed _COARSE_PX_PER_M against the line image resampled per scale.
_FINE_WIDTH = 480
_COARSE_PX_PER_M = 40.0
# Map raster used as the ECC input image, metres per pixel.
_RASTER_RES_M = 0.005
# Coarse scale ladder: geometric step, and the range as fractions of the frame.
_SCALE_STEP = 1.08
_MIN_MAP_FRACTION = 0.5    # map long side >= this share of the frame long side
_MIN_TEMPLATE_INSIDE = 0.3  # coarse poses need this share of the paint inside the frame
_MAX_MAP_FRACTION = 1.4    # map short side <= this multiple of the frame short side
# Orientations (best coarse pose each) that are refined and compared.
_REFINE_ORIENTATIONS = 4
# ECC refinement pyramid: (map raster cell, blur) in metres on the floor.
_ECC_LEVELS = ((0.03, 0.08), (0.02, 0.04), (0.015, 0.02))
# Coarse-search tolerance band (coarse-image pixels).
_COARSE_BAND_PX = 1
# The score compares paint and image lines on the map at the coarse resolution
# (2.5 cm cells), with a tolerance band of one cell, the same as the coarse search.
_SCORE_RES_M = 1.0 / _COARSE_PX_PER_M
_TOLERANCE_CELLS = _COARSE_BAND_PX
# Acceptance gates.
# Real frames (2026-09-30, lab): a correct fit scored recall 0.91 / precision 0.96,
# wrong orientations and unconverged fits at most 0.78 / 0.72.
MIN_RECALL = 0.8
MIN_PRECISION = 0.8
MIN_COVERAGE = 0.2
MIN_ORIENTATION_MARGIN = 0.1
# A map side counts as cut when more than this share of the paint in its outer band
# (_SIDE_BAND of the map extent) is outside the frame.
CUT_SIDE_FRACTION = 0.1
_SIDE_BAND = 0.25

_SIDE_DIRECTIONS = {"+x": "east", "-x": "west", "+y": "north", "-y": "south"}


@dataclass(frozen=True, eq=False)
class MapPaint:
    """Lane paint triangles in map metres, shape (N, 3, 2)."""

    triangles: np.ndarray
    bounds: tuple[float, float, float, float]  # xmin, xmax, ymin, ymax
    raster: np.ndarray                         # paint mask at _RASTER_RES_M, y up the map
    raster_matrix: np.ndarray                  # 2x3 metres -> raster px
    hull: np.ndarray                           # filled paint outline in the raster, slightly eroded
    samples: np.ndarray                        # (M, 2) paint points in metres, 1 cm grid

    @classmethod
    def from_triangles(cls, triangles: np.ndarray) -> "MapPaint":
        xs, ys = triangles[:, :, 0], triangles[:, :, 1]
        bounds = (float(xs.min()), float(xs.max()), float(ys.min()), float(ys.max()))
        if bounds[1] - bounds[0] <= 0.1 or bounds[3] - bounds[2] <= 0.1:
            raise ValueError("paint mesh is smaller than 10 cm")
        margin = 0.05
        matrix = np.array([[1 / _RASTER_RES_M, 0.0, (margin - bounds[0]) / _RASTER_RES_M],
                           [0.0, -1 / _RASTER_RES_M, (bounds[3] + margin) / _RASTER_RES_M]])
        size = (int(math.ceil((bounds[1] - bounds[0] + 2 * margin) / _RASTER_RES_M)),
                int(math.ceil((bounds[3] - bounds[2] + 2 * margin) / _RASTER_RES_M)))
        empty = np.zeros((1, 1), np.uint8)
        paint = cls(triangles, bounds, empty, matrix, empty, np.zeros((0, 2)))
        raster = paint.render(matrix, size)
        hull = np.zeros_like(raster)
        cv2.fillConvexPoly(hull, cv2.convexHull(cv2.findNonZero(raster)), 255)
        # Eroded so the lines just outside the outer boundary line (walls) are not "on the map".
        hull = cv2.erode(hull, np.ones((5, 5), np.uint8))
        object.__setattr__(paint, "raster", raster)
        object.__setattr__(paint, "hull", hull)
        # Paint sample points on a 1 cm grid, in metres, for the refinement.
        ys, xs = np.nonzero(raster[::2, ::2])
        pixels = np.stack([xs * 2.0, ys * 2.0], axis=1)
        inverse = cv2.invertAffineTransform(matrix)
        object.__setattr__(paint, "samples", pixels @ inverse[:, :2].T + inverse[:, 2])
        return paint

    @property
    def size(self) -> tuple[float, float]:
        xmin, xmax, ymin, ymax = self.bounds
        return xmax - xmin, ymax - ymin

    def render(self, matrix: np.ndarray, size: tuple[int, int]) -> np.ndarray:
        """Fill the paint through a 2x3 metres-to-pixel affine into a ``size`` (w, h) mask."""
        width, height = size
        pts = self.triangles.reshape(-1, 2) @ matrix[:, :2].T + matrix[:, 2]
        polys = np.round(pts * 4.0).astype(np.int32).reshape(-1, 3, 2)
        mask = np.zeros((height, width), np.uint8)
        # One call per triangle: a multi-polygon fillPoly XORs shared edges into holes.
        for poly in polys:
            cv2.fillConvexPoly(mask, poly, 255, lineType=cv2.LINE_8, shift=2)
        return mask


def load_map_paint(path: Path | str) -> MapPaint:
    """Read a binary STL of floor paint already in map metres (Z up), e.g. ``road_lines.stl``."""
    data = Path(path).read_bytes()
    if len(data) < 84:
        raise ValueError("not a binary STL: shorter than the 84-byte header")
    count = struct.unpack_from("<I", data, 80)[0]
    if count == 0 or len(data) != 84 + 50 * count:
        raise ValueError("not a binary STL: size does not match triangle count")
    rows = np.frombuffer(data, dtype=np.uint8, count=50 * count, offset=84).reshape(count, 50)
    vertices = rows[:, 12:48].copy().view("<f4").reshape(count, 3, 3).astype(np.float64)
    if not np.all(np.isfinite(vertices)):
        raise ValueError("STL has non-finite vertices")
    if np.ptp(vertices[:, :, 2]) > 0.01:
        raise ValueError("paint mesh is not flat on the floor (Z range > 1 cm)")
    return MapPaint.from_triangles(vertices[:, :, :2])


@dataclass(frozen=True)
class MapRegistration:
    image_to_map: np.ndarray        # 3x3, full-resolution image pixels -> map metres
    score: float                    # recall: share of in-frame paint matched by image lines
    precision: float                # share of image lines on the map that sit on paint
    coverage: float                 # share of the map paint area inside the frame
    cut_sides: tuple[str, ...]      # map sides cut off by the frame: "+x", "-x", "+y", "-y"
    side_outside: dict              # side -> share of that map edge outside the frame
    rotation_deg: float             # direction of map +x in the image, degrees CCW on screen
    mirrored: bool
    orientation_margin: float       # score gap to the best other orientation
    image_size: tuple[int, int]

    @property
    def map_to_image(self) -> np.ndarray:
        inverse = np.linalg.inv(self.image_to_map)
        return inverse / inverse[2, 2]

    def to_dict(self) -> dict:
        def rows(matrix):
            return [[float(f"{value:.8g}") for value in row] for row in matrix]
        return {
            "image_to_map": rows(self.image_to_map),
            "map_to_image": rows(self.map_to_image),
            "score": round(self.score, 3),
            "precision": round(self.precision, 3),
            "coverage": round(self.coverage, 3),
            "cut_sides": list(self.cut_sides),
            "cut_directions": [_SIDE_DIRECTIONS[side] for side in self.cut_sides],
            "side_outside": {side: round(value, 3) for side, value in self.side_outside.items()},
            "rotation_deg": round(self.rotation_deg, 1),
            "mirrored": self.mirrored,
            "orientation_margin": round(self.orientation_margin, 3),
        }


@dataclass(frozen=True)
class RegistrationResult:
    """``registration`` is the best fit found (or None); ``accepted`` says whether it passed the gates."""

    registration: MapRegistration | None
    accepted: bool
    reason: str
    elapsed_ms: float
    image_size: tuple[int, int]


def register_map_jpeg(jpeg: bytes, paint: MapPaint) -> RegistrationResult:
    """Decode one JPEG and register it; raises ``ValueError`` on bad input."""
    if not isinstance(jpeg, bytes) or not jpeg:
        raise ValueError("frame JPEG is empty")
    image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("frame JPEG decode failed")
    return register_map(image, paint)


def register_map(image: np.ndarray, paint: MapPaint) -> RegistrationResult:
    started = time.perf_counter()
    if image is None or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("expected a BGR image")
    height, width = image.shape[:2]
    if width < 64 or height < 64 or width > 8192 or height > 8192:
        raise ValueError("image dimensions are outside the supported range")
    registration, accepted, reason = _register(image, paint)
    elapsed = (time.perf_counter() - started) * 1000.0
    return RegistrationResult(registration, accepted, reason, elapsed, (width, height))


# -- pipeline ---------------------------------------------------------------


def _register(image: np.ndarray, paint: MapPaint) -> tuple[MapRegistration | None, bool, str]:
    height, width = image.shape[:2]
    fine_scale = min(1.0, _FINE_WIDTH / width)
    fine = cv2.resize(image, (round(width * fine_scale), round(height * fine_scale)),
                      interpolation=cv2.INTER_AREA)
    lines = _line_mask(fine)
    if cv2.countNonZero(lines) < 0.002 * lines.size:
        return None, False, "no white paint"

    yaw = _dominant_yaw(cv2.GaussianBlur(lines.astype(np.float32), (0, 0), 2.0))
    candidates = _coarse_search(lines, paint, yaw)
    if not candidates:
        return None, False, "no coarse match"

    to_raster = np.vstack([paint.raster_matrix, [0.0, 0.0, 1.0]])
    results = []
    for _, key, map_to_fine in candidates:
        # Keep the seed when refinement scores worse.
        for pose in (map_to_fine, _refine(lines, paint, map_to_fine)):
            warp = to_raster @ np.linalg.inv(pose)  # fine px -> raster px
            warp /= warp[2, 2]
            recall, precision, inside = _score(lines, paint, warp)
            # Same evidence weighting as the coarse search.
            results.append((recall * precision * math.sqrt(inside), recall, precision, key, warp))
    results.sort(key=lambda item: item[0], reverse=True)
    best_rank, best_recall, best_precision, best_key, best_warp = results[0]
    others = [r[0] for r in results if r[3] != best_key]
    # Relative gap to the best other orientation / mirror.
    margin = (best_rank - max(others)) / best_rank if others and best_rank > 0 else 1.0

    # Full-resolution image px -> map metres.
    fine_from_full = np.diag([fine_scale, fine_scale, 1.0])
    image_to_map = np.linalg.inv(to_raster) @ best_warp @ fine_from_full
    image_to_map /= image_to_map[2, 2]
    coverage, side_outside = _coverage(paint, image_to_map, (width, height))
    cut = _cut_sides(side_outside)
    rotation, mirrored = _orientation(image_to_map, (width, height))
    registration = MapRegistration(
        image_to_map=image_to_map, score=best_recall, precision=best_precision,
        coverage=coverage, cut_sides=cut, side_outside=side_outside, rotation_deg=rotation,
        mirrored=mirrored, orientation_margin=margin, image_size=(width, height),
    )
    if coverage < MIN_COVERAGE:
        return registration, False, f"too little of the map in view ({coverage:.2f})"
    if best_recall < MIN_RECALL:
        return registration, False, f"weak paint match ({best_recall:.2f})"
    if best_precision < MIN_PRECISION:
        return registration, False, f"too many unmatched lines ({best_precision:.2f})"
    if margin < MIN_ORIENTATION_MARGIN:
        return registration, False, f"orientation ambiguous (margin {margin:.2f})"
    if mirrored:
        return registration, False, "image is mirrored; check the camera app"
    return registration, True, "ok"


def _line_mask(image: np.ndarray) -> np.ndarray:
    """Thin bright, unsaturated structures (lane paint); drops large white areas."""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    val = cv2.GaussianBlur(hsv[:, :, 2], (3, 3), 0)
    side = max(9, (min(image.shape[:2]) // 18) | 1)
    tophat = cv2.morphologyEx(val, cv2.MORPH_TOPHAT,
                              cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (side, side)))
    otsu, _ = cv2.threshold(tophat, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = ((tophat >= max(40.0, float(otsu))) & (hsv[:, :, 1] <= 70)).astype(np.uint8) * 255
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))


def _dominant_yaw(mask: np.ndarray) -> float:
    """Dominant line direction modulo 90 degrees, radians in (-pi/4, pi/4]."""
    gx = cv2.Sobel(mask, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(mask, cv2.CV_32F, 0, 1, ksize=3)
    magnitude = np.hypot(gx, gy)
    angle = np.arctan2(gy, gx)
    c = float(np.sum(magnitude * np.cos(4 * angle)))
    s = float(np.sum(magnitude * np.sin(4 * angle)))
    if math.hypot(c, s) < 1e-6:
        return 0.0
    # Gradient angles are measured with image y down; poses rotate counter-clockwise on screen.
    return -math.atan2(s, c) / 4.0


def _similarity(paint: MapPaint, scale: float, theta: float, mirror: bool) -> tuple[np.ndarray, tuple[int, int]]:
    """Metres -> template px for one pose, tight around the map bounds (image y down)."""
    xmin, xmax, ymin, ymax = paint.bounds
    flip = -1.0 if mirror else 1.0
    c, s = math.cos(theta), math.sin(theta)
    # Map (x, y up) -> screen (u, v down), rotated by theta CCW on screen.
    linear = scale * np.array([[c, flip * s], [-s, flip * c]]) @ np.diag([1.0, -1.0])
    corners = np.array([[xmin, ymin], [xmax, ymin], [xmax, ymax], [xmin, ymax]]) @ linear.T
    offset = -corners.min(axis=0) + 1.0
    size = np.ceil(corners.max(axis=0) - corners.min(axis=0) + 2.0).astype(int)
    return np.hstack([linear, offset[:, None]]), (int(size[0]), int(size[1]))


def _disk(radius: int) -> np.ndarray:
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))


def _coarse_search(lines: np.ndarray, paint: MapPaint, yaw: float) -> list:
    """Best similarity pose per (quarter turn, mirror): ``(score, key, map metres -> lines px)``.

    The map template stays at ``_COARSE_PX_PER_M``; the line image is resampled per
    candidate scale instead, so tolerances and line widths mean the same in every
    comparison and small scales do not win by density.
    """
    height, width = lines.shape
    long_m, short_m = max(paint.size), min(paint.size)
    s_min = _MIN_MAP_FRACTION * max(width, height) / long_m
    s_max = _MAX_MAP_FRACTION * min(width, height) / short_m
    templates = []
    base = np.dstack([paint.raster, paint.hull]).astype(np.float32) / 255.0
    base_matrix = np.vstack([paint.raster_matrix, [0.0, 0.0, 1.0]])
    factor = _COARSE_PX_PER_M * _RASTER_RES_M
    small_size = (round(base.shape[1] * factor), round(base.shape[0] * factor))
    small = cv2.resize(base, small_size, interpolation=cv2.INTER_AREA)
    fx, fy = small_size[0] / base.shape[1], small_size[1] / base.shape[0]
    small_matrix = np.array([[fx, 0.0, 0.5 * fx - 0.5], [0.0, fy, 0.5 * fy - 0.5],
                             [0.0, 0.0, 1.0]]) @ base_matrix
    for quarter in range(4):
        for mirror in (False, True):
            matrix, (tw, th) = _similarity(paint, _COARSE_PX_PER_M, yaw + quarter * math.pi / 2, mirror)
            resample = (np.vstack([matrix, [0.0, 0.0, 1.0]]) @ np.linalg.inv(small_matrix))[:2]
            warped = cv2.warpAffine(small, resample, (tw, th), flags=cv2.INTER_LINEAR)
            paint_t = (warped[:, :, 0] > 0.15).astype(np.float32)
            hull_t = (warped[:, :, 1] > 0.5).astype(np.float32)
            band_t = cv2.dilate(paint_t, _disk(_COARSE_BAND_PX)) * hull_t
            templates.append(((quarter, mirror), matrix, paint_t, hull_t, band_t))

    source = lines.astype(np.float32) / 255.0
    best: dict[tuple[int, bool], tuple[float, tuple, np.ndarray]] = {}
    scale = s_min
    while scale <= s_max:
        ratio = _COARSE_PX_PER_M / scale
        size = (max(8, round(width * ratio)), max(8, round(height * ratio)))
        resampled = cv2.resize(source, size, interpolation=cv2.INTER_AREA if ratio < 1 else cv2.INTER_LINEAR)
        image = (resampled > 0.2).astype(np.float32)
        band = cv2.dilate(image, _disk(_COARSE_BAND_PX))
        for key, matrix, paint_t, hull_t, band_t in templates:
            th, tw = paint_t.shape
            px, py = int(0.7 * tw), int(0.7 * th)

            def pad(array):
                return cv2.copyMakeBorder(array, py, py, px, px, cv2.BORDER_CONSTANT, value=0)

            if image.shape[0] + 2 * py < th or image.shape[1] + 2 * px < tw:
                continue
            # Tolerance-band recall (paint near lines) and precision (lines near paint,
            # counted only inside the map outline so walls off the map do not count).
            inside = cv2.matchTemplate(pad(np.ones_like(image)), paint_t, cv2.TM_CCORR)
            matched = cv2.matchTemplate(pad(band), paint_t, cv2.TM_CCORR)
            on_map = cv2.matchTemplate(pad(image), hull_t, cv2.TM_CCORR)
            explained = cv2.matchTemplate(pad(image), band_t, cv2.TM_CCORR)
            total = float(paint_t.sum())
            recall = matched / np.maximum(inside, 1.0)
            # A window with few lines on the map is no evidence: floor the denominator.
            precision = explained / np.maximum(on_map, np.maximum(0.5 * inside, 1.0))
            # More of the map in view is more evidence; a small in-frame corner of the
            # map matches clutter too easily.
            response = recall * precision * np.sqrt(np.clip(inside / total, 0.0, 1.0))
            response[inside < _MIN_TEMPLATE_INSIDE * total] = 0.0
            _, value, _, loc = cv2.minMaxLoc(response)
            if not math.isfinite(value) or (key in best and value <= best[key][0]):
                continue
            to_lines = np.array([[1 / ratio, 0.0, 0.0], [0.0, 1 / ratio, 0.0], [0.0, 0.0, 1.0]])
            shift = np.array([[1.0, 0.0, loc[0] - px], [0.0, 1.0, loc[1] - py], [0.0, 0.0, 1.0]])
            best[key] = (value, key, to_lines @ shift @ np.vstack([matrix, [0.0, 0.0, 1.0]]))
        scale *= _SCALE_STEP
    ranked = sorted(best.values(), key=lambda item: item[0], reverse=True)
    return ranked[:_REFINE_ORIENTATIONS]


def _refine(lines: np.ndarray, paint: MapPaint, map_to_fine: np.ndarray) -> np.ndarray:
    """ECC homography from the map raster (template) to the line image, map metres -> fine px.

    The map is the template, so only the floor inside the map is compared; lines off the
    map (walls, neighbouring tracks) are never sampled. Both sides are blurred by the
    same floor distance per pyramid level. Keeps the last good pose on failure.
    """
    current = map_to_fine / map_to_fine[2, 2]
    valid = np.full(lines.shape, 255, np.uint8)
    source = lines.astype(np.float32)
    for cell_m, blur_m in _ECC_LEVELS:
        px_per_m = math.sqrt(abs(np.linalg.det(current[:2, :2])))
        fine_blur = cv2.GaussianBlur(source, (0, 0), max(0.8, blur_m * px_per_m))
        step = cell_m / _RASTER_RES_M
        height, width = paint.raster.shape
        size = (math.ceil(width / step), math.ceil(height / step))
        template = cv2.resize(paint.raster.astype(np.float32), size, interpolation=cv2.INTER_AREA)
        template = cv2.GaussianBlur(template, (0, 0), max(0.8, blur_m / cell_m))
        to_cells = np.diag([1 / step, 1 / step, 1.0]) @ np.vstack([paint.raster_matrix, [0.0, 0.0, 1.0]])
        guess = (current @ np.linalg.inv(to_cells)).astype(np.float32)
        try:
            _, refined = cv2.findTransformECC(
                template, fine_blur, guess, cv2.MOTION_HOMOGRAPHY,
                (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 50, 1e-4), valid, 1)
        except cv2.error:
            return current
        if not np.all(np.isfinite(refined)):
            return current
        current = refined.astype(np.float64) @ to_cells
        current /= current[2, 2]
    return current


def _score(lines: np.ndarray, paint: MapPaint, warp: np.ndarray) -> tuple[float, float, float]:
    """(recall, precision, share of paint in frame) of ``warp`` (fine px -> raster px).

    The line image is resampled onto the map at ``_SCORE_RES_M`` so the tolerance is a
    distance on the floor and a far camera (small map) is not scored more leniently.
    """
    step = _SCORE_RES_M / _RASTER_RES_M
    to_score = np.diag([1 / step, 1 / step, 1.0]) @ warp
    height, width = paint.raster.shape
    size = (math.ceil(width / step), math.ceil(height / step))
    paint_s = cv2.resize(paint.raster, size, interpolation=cv2.INTER_AREA) > 38
    hull_s = cv2.resize(paint.hull, size, interpolation=cv2.INTER_AREA) > 128
    # Area-average the lines to the cell size before resampling (warpPerspective has no
    # INTER_AREA), matching how the coarse search sees the image.
    jacobian = np.linalg.inv(to_score)
    cell_px = math.sqrt(abs(np.linalg.det(jacobian[:2, :2] / jacobian[2, 2])))
    if not math.isfinite(cell_px) or cell_px > 0.25 * min(lines.shape):
        return 0.0, 0.0, 0.0  # degenerate pose
    k = max(1, round(cell_px))
    smooth = cv2.blur(lines.astype(np.float32) / 255.0, (k, k)) if k > 1 else lines.astype(np.float32) / 255.0
    seen = cv2.warpPerspective(smooth, to_score, size, flags=cv2.INTER_LINEAR) > 0.2
    valid = cv2.warpPerspective(np.ones(lines.shape, np.uint8), to_score, size,
                                flags=cv2.INTER_NEAREST) > 0
    band = _disk(_TOLERANCE_CELLS)
    paint_in = paint_s & valid
    if not paint_in.any():
        return 0.0, 0.0, 0.0
    inside = float(paint_in.sum() / max(1, paint_s.sum()))
    seen_band = cv2.dilate(seen.astype(np.uint8), band) > 0
    recall = float((paint_in & seen_band).sum() / paint_in.sum())
    # Precision only inside the painted area's hull, so walls and other tracks are not counted.
    on_map = seen & hull_s
    paint_band = cv2.dilate(paint_s.astype(np.uint8), band) > 0
    precision = float((on_map & paint_band).sum() / max(on_map.sum(), 0.5 * paint_in.sum(), 1))
    return recall, precision, inside


def _coverage(paint: MapPaint, image_to_map: np.ndarray, size: tuple[int, int]
              ) -> tuple[float, dict]:
    """Share of paint area in the frame, and per map side the share of the paint in that
    side's outer band (``_SIDE_BAND`` of the map extent) that lies outside the frame."""
    width, height = size
    points = paint.samples  # equal-area 1 cm samples
    inside = _in_frame(np.linalg.inv(image_to_map), points, width, height)
    coverage = float(inside.mean())
    xmin, xmax, ymin, ymax = paint.bounds
    bx, by = _SIDE_BAND * (xmax - xmin), _SIDE_BAND * (ymax - ymin)
    bands = {
        "+x": points[:, 0] > xmax - bx, "-x": points[:, 0] < xmin + bx,
        "+y": points[:, 1] > ymax - by, "-y": points[:, 1] < ymin + by,
    }
    side_outside = {side: float(1.0 - inside[band].mean()) if band.any() else 0.0
                    for side, band in bands.items()}
    return coverage, side_outside


def _cut_sides(side_outside: dict) -> tuple[str, ...]:
    """Sides mostly responsible for the missing paint: a corner cut names two sides,
    a strip cut along one side names only that side."""
    worst = max(side_outside.values())
    return tuple(side for side in ("+x", "-x", "+y", "-y")
                 if side_outside[side] > CUT_SIDE_FRACTION and side_outside[side] >= 0.5 * worst)


def _in_frame(map_to_image: np.ndarray, points: np.ndarray, width: int, height: int) -> np.ndarray:
    homogeneous = np.hstack([points, np.ones((len(points), 1))]) @ map_to_image.T
    w = homogeneous[:, 2]
    with np.errstate(divide="ignore", invalid="ignore"):
        u, v = homogeneous[:, 0] / w, homogeneous[:, 1] / w
    return (w > 0) & (u >= 0) & (u <= width - 1) & (v >= 0) & (v <= height - 1)


def _orientation(image_to_map: np.ndarray, size: tuple[int, int]) -> tuple[float, bool]:
    """Screen direction of map +x (degrees CCW, y up on screen) and mirror flag at the frame centre."""
    map_to_image = np.linalg.inv(image_to_map)
    centre = image_to_map @ np.array([size[0] / 2, size[1] / 2, 1.0])
    centre = centre[:2] / centre[2]

    def project(point):
        p = map_to_image @ np.array([point[0], point[1], 1.0])
        return p[:2] / p[2]

    origin = project(centre)
    ex = project(centre + [0.1, 0.0]) - origin
    ey = project(centre + [0.0, 0.1]) - origin
    rotation = math.degrees(math.atan2(-ex[1], ex[0])) % 360.0
    # Non-mirrored overhead view: map +y is +90 deg from +x on screen (y up), so the screen cross is > 0.
    cross = ex[0] * (-ey[1]) - (-ex[1]) * ey[0]
    return rotation, bool(cross < 0)
