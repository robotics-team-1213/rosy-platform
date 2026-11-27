"""Where a robot stands at a cell stop, read from the arm cell's fixed top camera (2026-11-27).

Model S was trained on top-camera frames with the robot parked at one spot. This module registers a live frame to a
stored reference frame of the fixed arm plate (SIFT + similarity RANSAC, so a camera that has rotated since is
absorbed), finds the robot's orange tray and returns its offset from the training target in the site frame, with an
uncertainty. The pixel to metre map lives in the data file ("px_to_site"), never in code; solve_px_to_site re-solves
it from frames taken before and after a known small move. Pure: no network, no clock.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

SCHEMA = "rosy.cell-topview.v1"


class TopviewError(Exception):
    """The frame cannot give a trustworthy pose; reason is a stable code."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class TopviewData:
    place: str
    view: str
    cell: str
    reference_gray: object  # numpy uint8 image
    mask_left_px: int
    tray_roi: tuple  # (x0, y0, x1, y1) in the live frame
    tray_hsv: tuple  # (lo, hi) HSV triples of the orange tray
    min_tray_area_px: int
    target_px: tuple  # training target in reference-frame pixels
    target_axis_deg: float  # training tray long axis in the reference frame (image angle, 0 = image x)
    px_to_site: tuple  # ((a, b), (c, d)): site (x, y) metres = A @ (du, dv) reference pixels
    position_sigma_m: float
    heading_sigma_rad: float
    min_inliers: int
    max_rms_px: float
    marker_dictionary: str
    marker_ids: dict
    max_frame_age_s: float
    max_corrections: int


def load_data(path) -> TopviewData:
    import cv2
    import numpy as np

    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema") != SCHEMA:
        raise ValueError(f"{path.name}: schema must be {SCHEMA}")
    ref = cv2.imread(str(path.parent / raw["reference_image"]), cv2.IMREAD_GRAYSCALE)
    if ref is None:
        raise ValueError(f"{path.name}: reference image unreadable")
    a = np.array(raw["px_to_site"], float)
    if a.shape != (2, 2) or not np.isfinite(a).all() or abs(np.linalg.det(a)) < 1e-12:
        raise ValueError(f"{path.name}: px_to_site must be an invertible 2x2")
    return TopviewData(
        place=raw["place"], view=raw["view"], cell=raw["cell"], reference_gray=ref,
        mask_left_px=int(raw["mask_left_px"]), tray_roi=tuple(raw["tray"]["roi"]),
        tray_hsv=(tuple(raw["tray"]["hsv_lo"]), tuple(raw["tray"]["hsv_hi"])),
        min_tray_area_px=int(raw["tray"]["min_area_px"]), target_px=tuple(raw["target_px"]),
        target_axis_deg=float(raw["target_axis_deg"]), px_to_site=tuple(tuple(r) for r in raw["px_to_site"]),
        position_sigma_m=float(raw["position_sigma_m"]), heading_sigma_rad=float(raw["heading_sigma_rad"]),
        min_inliers=int(raw["min_inliers"]), max_rms_px=float(raw["max_rms_px"]),
        marker_dictionary=raw["marker"]["dictionary"], marker_ids=dict(raw["marker"]["ids"]),
        max_frame_age_s=float(raw["max_frame_age_s"]), max_corrections=int(raw["max_corrections"]))


def _wrap_axis(angle: float) -> float:
    """Fold an angle of an undirected axis into (-pi/2, pi/2]."""
    return (angle + math.pi / 2) % math.pi - math.pi / 2


def register(data: TopviewData, gray):
    """2x3 affine (reference px -> live px), inlier count and rms px; TopviewError when it is not trustworthy."""
    import cv2
    import numpy as np

    def keypoints(img):
        mask = np.full(img.shape, 255, np.uint8)
        mask[:, :data.mask_left_px] = 0  # the robot stands here; only the fixed arm plate may anchor the frame
        return cv2.SIFT_create(4000).detectAndCompute(img, mask)

    k1, d1 = keypoints(data.reference_gray)
    k2, d2 = keypoints(gray)
    if d1 is None or d2 is None or len(k1) < 8 or len(k2) < 8:
        raise TopviewError("registration_no_features")
    pairs = cv2.BFMatcher().knnMatch(d1, d2, k=2)
    good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < 0.75 * p[1].distance]
    if len(good) < data.min_inliers:
        raise TopviewError("registration_too_few_matches")
    p1 = np.float32([k1[m.queryIdx].pt for m in good])
    p2 = np.float32([k2[m.trainIdx].pt for m in good])
    matrix, inliers = cv2.estimateAffinePartial2D(p1, p2, ransacReprojThreshold=2.0, maxIters=5000, confidence=0.999,
                                                  refineIters=20)
    if matrix is None or int(inliers.sum()) < data.min_inliers:
        raise TopviewError("registration_too_few_inliers")
    keep = inliers.ravel() > 0
    moved = p1[keep] @ matrix[:, :2].T + matrix[:, 2]
    rms = float(np.sqrt(np.mean(np.sum((moved - p2[keep]) ** 2, axis=1))))
    scale = math.hypot(matrix[0, 0], matrix[1, 0])
    if rms > data.max_rms_px or not 0.95 <= scale <= 1.05 or abs(math.degrees(math.atan2(matrix[1, 0], matrix[0, 0]))) > 20:
        raise TopviewError("registration_implausible")
    return matrix, int(keep.sum()), rms


def find_tray(data: TopviewData, bgr):
    """(centroid px, unit long-axis vector px) of the largest orange blob in the ROI."""
    import cv2
    import numpy as np

    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(data.tray_hsv[0]), np.array(data.tray_hsv[1]))
    x0, y0, x1, y1 = data.tray_roi
    roi = np.zeros_like(mask)
    roi[y0:y1, x0:x1] = mask[y0:y1, x0:x1]
    count, labels, stats, _ = cv2.connectedComponentsWithStats(roi)
    if count < 2:
        raise TopviewError("tray_not_found")
    best = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    if stats[best, cv2.CC_STAT_AREA] < data.min_tray_area_px:
        raise TopviewError("tray_too_small")
    ys, xs = np.where(labels == best)
    pts = np.column_stack([xs, ys]).astype(float)
    centre = pts.mean(0)
    values, vectors = np.linalg.eigh(np.cov((pts - centre).T))
    if values[1] < 1.3 * values[0]:
        raise TopviewError("tray_axis_ambiguous")
    return centre, vectors[:, 1]


def marker_check(data: TopviewData, gray, expected):
    """Marker id seen on the robot, or None when the marker is not visible (S3 crops it at the frame's top edge).

    A different robot's id is a refusal; an unseen marker is not (the tray is the measured evidence)."""
    import cv2

    dictionary = getattr(cv2.aruco, data.marker_dictionary, None)
    if dictionary is None or expected is None:
        return None
    _, ids, _ = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(dictionary)).detectMarkers(gray)
    seen = {int(i) for i in ids.ravel()} & set(data.marker_ids.values()) if ids is not None else set()  # known Pinkies only
    want = data.marker_ids.get(expected)
    if seen and want not in seen:
        raise TopviewError("marker_other_robot")
    return want if want in seen else None


def observe(data: TopviewData, jpeg: bytes, robot_id=None) -> dict:
    """Offset of the robot from the training target. dx/dy are site metres (robot minus target), dyaw the heading
    error (rad); raises TopviewError."""
    import cv2
    import numpy as np

    bgr = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    if bgr is None or bgr.shape[:2] != data.reference_gray.shape:
        raise TopviewError("frame_unreadable")
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    matrix, inliers, rms = register(data, gray)
    marker = marker_check(data, gray, robot_id)
    centre, axis = find_tray(data, bgr)
    back = cv2.invertAffineTransform(matrix)
    ref_px = back[:, :2] @ centre + back[:, 2]
    ref_axis = back[:, :2] @ axis
    ref_axis /= np.linalg.norm(ref_axis)
    a = np.array(data.px_to_site, float)
    dx, dy = a @ (ref_px - np.array(data.target_px))
    t = math.radians(data.target_axis_deg)
    target_axis = a @ np.array([math.cos(t), math.sin(t)])
    live_axis = a @ ref_axis
    dyaw = _wrap_axis(math.atan2(live_axis[1], live_axis[0]) - math.atan2(target_axis[1], target_axis[0]))
    metres_per_px = math.sqrt(abs(np.linalg.det(a)))
    sigma = math.hypot(data.position_sigma_m, 2.0 * rms * metres_per_px)
    return {"dx": float(dx), "dy": float(dy), "dyaw": float(dyaw), "sigma_m": sigma,
            "sigma_rad": data.heading_sigma_rad, "inliers": inliers, "rms_px": rms, "marker_id": marker,
            "ref_px": [float(ref_px[0]), float(ref_px[1])], "tray_px": [float(centre[0]), float(centre[1])]}


def solve_px_to_site(moves, base) -> list:
    """Re-solve the pixel to site map from known moves: moves = [(ref_px_before, ref_px_after, site_delta)].

    Two or more non-parallel moves fit all four entries; one move only rescales base (axes stay as commissioned)."""
    import numpy as np

    px = np.array([[a[0] - b[0], a[1] - b[1]] for b, a, _ in moves], float)
    site = np.array([d for _, _, d in moves], float)
    if len(moves) >= 2 and np.linalg.matrix_rank(px, tol=1e-6 * max(1.0, np.abs(px).max())) == 2:
        return np.linalg.lstsq(px, site, rcond=None)[0].T.tolist()
    predicted = px @ np.array(base, float).T
    denominator = float((predicted * predicted).sum())
    if denominator <= 0:
        raise TopviewError("calibration_no_motion")
    return (float((predicted * site).sum()) / denominator * np.array(base, float)).tolist()


def _calibrate(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Re-solve px_to_site from frames before and after a known move.")
    parser.add_argument("data")
    parser.add_argument("before")
    parser.add_argument("after")
    parser.add_argument("--forward", type=float, required=True, help="commanded forward move, metres")
    parser.add_argument("--left", type=float, default=0.0, help="commanded left move, metres")
    parser.add_argument("--yaw", type=float, required=True, help="robot yaw in the site frame, radians")
    args = parser.parse_args(argv)
    data = load_data(args.data)
    seen = [observe(data, Path(p).read_bytes()) for p in (args.before, args.after)]
    c, s = math.cos(args.yaw), math.sin(args.yaw)
    delta = (c * args.forward - s * args.left, s * args.forward + c * args.left)
    print(json.dumps({"px_to_site": solve_px_to_site([(seen[0]["ref_px"], seen[1]["ref_px"], delta)], data.px_to_site),
                      "measured_move_m": [seen[1]["dx"] - seen[0]["dx"], seen[1]["dy"] - seen[0]["dy"]],
                      "commanded_move_m": list(delta)}))


if __name__ == "__main__":
    _calibrate()
