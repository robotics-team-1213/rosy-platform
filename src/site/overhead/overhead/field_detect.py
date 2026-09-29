"""Overhead field boundary proposal (D-360).

Finds the white wall/tape outline around the grey carpet in one camera frame
and proposes its four image corners. The result is a *proposal* for operator
review in the Fleet console: it never feeds sightings, ``CameraMap``, task
acceptance, or motion. No field (or a field that runs past the frame) means
no proposal, never an invented corner.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import cv2
import numpy as np

DETECTOR_VERSION = "white-outline/1"

# Work on a bounded copy; corners are mapped back to full-resolution pixels.
_WORK_MAX_SIDE = 640
# The field must cover at least this share of the frame to be proposed.
_MIN_AREA_FRACTION = 0.04
# A corner closer than this share of the short image side to the frame edge
# means the field is clipped by the frame, so the outline is not the field.
_EDGE_MARGIN_FRACTION = 0.01
# Proposals below this confidence are dropped.
MIN_CONFIDENCE = 0.5
# |aspect - 1| at or below this is reported as a square.
SQUARE_TOLERANCE = 0.1
_MAX_ASPECT = 8.0


@dataclass(frozen=True)
class FieldProposal:
    """Four image-pixel corners in top-left, top-right, bottom-right, bottom-left order."""

    corners: tuple[tuple[float, float], ...]
    confidence: float
    aspect_ratio: float
    shape: str
    image_size: tuple[int, int]

    def to_dict(self) -> dict:
        width, height = self.image_size
        return {
            "corners": [[round(x, 2), round(y, 2)] for x, y in self.corners],
            "corners_normalized": [
                [round(x / max(1, width - 1), 5), round(y / max(1, height - 1), 5)]
                for x, y in self.corners
            ],
            "confidence": round(self.confidence, 3),
            "aspect_ratio": round(self.aspect_ratio, 4),
            "shape": self.shape,
        }


@dataclass(frozen=True)
class FieldDetection:
    proposal: FieldProposal | None
    reason: str
    elapsed_ms: float
    image_size: tuple[int, int]


def detect_field_jpeg(jpeg: bytes) -> FieldDetection:
    """Decode one JPEG and detect the field; raises ``ValueError`` on bad input."""
    if not isinstance(jpeg, bytes) or not jpeg:
        raise ValueError("frame JPEG is empty")
    image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("frame JPEG decode failed")
    return detect_field(image)


def detect_field(image: np.ndarray) -> FieldDetection:
    started = time.perf_counter()
    if image is None or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("expected a BGR image")
    height, width = image.shape[:2]
    if width < 32 or height < 32 or width > 8192 or height > 8192:
        raise ValueError("image dimensions are outside the supported range")
    proposal, reason = _detect(image)
    elapsed = (time.perf_counter() - started) * 1000.0
    return FieldDetection(proposal, reason, elapsed, (width, height))


def _detect(image: np.ndarray) -> tuple[FieldProposal | None, str]:
    height, width = image.shape[:2]
    scale = min(1.0, _WORK_MAX_SIDE / max(width, height))
    work = image if scale == 1.0 else cv2.resize(
        image, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
    mask = _white_mask(work)
    if mask is None:
        return None, "no white boundary"

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    work_area = float(work.shape[0] * work.shape[1])
    candidates = []
    for contour in contours:
        hull = cv2.convexHull(contour)
        hull_area = cv2.contourArea(hull)
        if hull_area >= _MIN_AREA_FRACTION * work_area:
            candidates.append((hull_area, contour, hull))
    if not candidates:
        return None, "no outline large enough"
    candidates.sort(key=lambda item: item[0], reverse=True)

    reason = "no four-sided outline"
    for _, contour, hull in candidates[:3]:
        quad = _hull_to_quad(hull)
        if quad is None:
            continue
        quad = _refine(_outer_points(contour, hull), quad)
        if quad is None:
            continue
        quad = quad / scale
        verdict = _check(quad, width, height)
        if verdict:
            reason = verdict
            continue
        confidence = _edge_support(mask, quad * scale)
        if confidence < MIN_CONFIDENCE:
            reason = f"weak boundary support ({confidence:.2f})"
            continue
        ordered = _order(quad)
        aspect = _aspect(ordered)
        shape = "square" if abs(max(aspect, 1 / aspect) - 1.0) <= SQUARE_TOLERANCE else "rectangle"
        return FieldProposal(
            corners=tuple((float(x), float(y)) for x, y in ordered),
            confidence=float(confidence), aspect_ratio=float(aspect), shape=shape,
            image_size=(width, height),
        ), "ok"
    return None, reason


def _white_mask(work: np.ndarray) -> np.ndarray | None:
    hsv = cv2.cvtColor(work, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1]
    val = cv2.GaussianBlur(hsv[:, :, 2], (5, 5), 0)
    otsu, _ = cv2.threshold(val, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    threshold = max(150.0, float(otsu))
    mask = ((val >= threshold) & (sat <= 70)).astype(np.uint8) * 255
    if cv2.countNonZero(mask) < 0.002 * mask.size:
        return None
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)


def _hull_to_quad(hull: np.ndarray) -> np.ndarray | None:
    perimeter = cv2.arcLength(hull, True)
    for factor in (0.01, 0.02, 0.03, 0.04, 0.06, 0.08):
        approx = cv2.approxPolyDP(hull, factor * perimeter, True)
        if len(approx) == 4:
            return approx.reshape(4, 2).astype(np.float64)
        if len(approx) < 4:
            return None
    return None


def _outer_points(contour: np.ndarray, hull: np.ndarray) -> np.ndarray:
    """Outline points on the hull boundary; drops the inner wall edge of an opened ring."""
    points = contour.reshape(-1, 2)
    hull_f = hull.astype(np.float32)
    keep = [abs(cv2.pointPolygonTest(hull_f, (float(x), float(y)), True)) <= 1.5 for x, y in points]
    return points[np.array(keep, dtype=bool)].astype(np.float64)


def _refine(points: np.ndarray, quad: np.ndarray) -> np.ndarray | None:
    """Sub-pixel corners: fit a line to the outline points along each side, intersect."""
    tolerance = max(2.0, 0.015 * cv2.arcLength(quad.astype(np.float32).reshape(-1, 1, 2), True))
    lines = []
    for index in range(4):
        start, end = quad[index], quad[(index + 1) % 4]
        direction = end - start
        length = float(np.hypot(*direction))
        if length < 4.0:
            return None
        unit = direction / length
        rel = points - start
        along = rel @ unit
        across = np.abs(rel[:, 0] * unit[1] - rel[:, 1] * unit[0])
        keep = (across <= tolerance) & (along >= 0.1 * length) & (along <= 0.9 * length)
        side = points[keep]
        if len(side) < 8:
            lines.append((start, unit))
            continue
        vx, vy, x0, y0 = cv2.fitLine(side.astype(np.float32), cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
        lines.append((np.array([x0, y0], dtype=np.float64), np.array([vx, vy], dtype=np.float64)))
    refined = []
    for index in range(4):
        (p1, d1), (p2, d2) = lines[index - 1], lines[index]
        matrix = np.array([d1, -d2]).T
        if abs(np.linalg.det(matrix)) < 1e-6:
            return None
        t, _ = np.linalg.solve(matrix, p2 - p1)
        refined.append(p1 + t * d1)
    refined = np.array(refined)
    # Refinement may never move a corner far from the polygon approximation.
    if np.max(np.hypot(*(refined - quad).T)) > 4 * tolerance:
        return quad
    return refined


def _check(quad: np.ndarray, width: int, height: int) -> str:
    contour = quad.astype(np.float32).reshape(-1, 1, 2)
    if not cv2.isContourConvex(contour):
        return "outline is not convex"
    margin = _EDGE_MARGIN_FRACTION * min(width, height)
    if (np.any(quad[:, 0] < margin) or np.any(quad[:, 0] > width - 1 - margin)
            or np.any(quad[:, 1] < margin) or np.any(quad[:, 1] > height - 1 - margin)):
        return "field runs past the frame"
    if cv2.contourArea(contour) < _MIN_AREA_FRACTION * width * height:
        return "outline too small"
    for index in range(4):
        a, b, c = quad[index - 1], quad[index], quad[(index + 1) % 4]
        u, v = a - b, c - b
        cosine = abs(float(u @ v) / (np.hypot(*u) * np.hypot(*v) + 1e-9))
        if cosine > 0.85:  # interior angle outside roughly 32..148 degrees
            return "corner angle out of range"
    aspect = _aspect(_order(quad))
    if max(aspect, 1 / aspect) > _MAX_ASPECT:
        return "aspect ratio out of range"
    return ""


def _edge_support(mask: np.ndarray, quad: np.ndarray) -> float:
    """Share of points along the four sides that sit on the white boundary."""
    support = cv2.dilate(mask, np.ones((5, 5), np.uint8))
    h, w = support.shape
    hits = total = 0
    for index in range(4):
        start, end = quad[index], quad[(index + 1) % 4]
        centroid = quad.mean(axis=0)
        for t in np.linspace(0.05, 0.95, 48):
            point = start + t * (end - start)
            # Sample just inside the outline; the outer contour sits on the wall's outer edge.
            inward = centroid - point
            point = point + 2.0 * inward / (np.hypot(*inward) + 1e-9)
            x, y = int(round(point[0])), int(round(point[1]))
            total += 1
            if 0 <= x < w and 0 <= y < h and support[y, x]:
                hits += 1
    return hits / total if total else 0.0


def _order(quad: np.ndarray) -> np.ndarray:
    """Top-left, top-right, bottom-right, bottom-left in image coordinates (y down)."""
    centroid = quad.mean(axis=0)
    angles = np.arctan2(quad[:, 1] - centroid[1], quad[:, 0] - centroid[0])
    clockwise = quad[np.argsort(angles)]  # increasing angle is clockwise on screen
    start = int(np.argmin(clockwise.sum(axis=1)))
    return np.roll(clockwise, -start, axis=0)


def _aspect(ordered: np.ndarray) -> float:
    top = np.hypot(*(ordered[1] - ordered[0]))
    bottom = np.hypot(*(ordered[2] - ordered[3]))
    left = np.hypot(*(ordered[3] - ordered[0]))
    right = np.hypot(*(ordered[2] - ordered[1]))
    return float((top + bottom) / max(1e-9, left + right))
