"""Robot-driven camera calibration candidate from pose/marker pairs (D-1007).

Offline and numpy only. Each sample pairs a robot's site-map pose (AMCL pushed through the
D-1003 transform by the caller) with the pixel centre of that robot's marker in a camera
frame. ``solve_candidate`` fits a plane homography with RANSAC, scores it on spatially held-out
samples, and returns a *reviewable candidate*: the floor homography, residuals, and the
convex hull of the inlier points as its validity region. Nothing here feeds sightings,
``CameraMap`` or any motion; applying a candidate is an operator approval (D-1006 7).

The marker sits MARKER_HEIGHT_M above the floor, so the fit is for that plane. The floor
homography follows from the camera nadir and height solved from the plane fit and the lens FOV.
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np

from rosy_vision.project import MARKER_HEIGHT_M, MARKER_MOUNT_XY_M
from rosy_vision.track import geometry

CANDIDATE_VERSION = "robot-correspondence/1"

# Starting values from one incident (2026-11-09), not evidence: tune on recorded drives.
MAX_POSE_AGE_S = 0.3        # AMCL pose older than this at the frame time
MAX_TIME_SKEW_S = 0.1       # |t_pose - t_image|
MAX_SPEED_MPS = 0.15        # faster robots blur pose-vs-frame by v * skew
DEDUPE_M = 0.15             # samples closer than this to a kept one add no spread
INLIER_M = 0.05             # RANSAC gate, map metres
MIN_INLIERS = 12
MIN_SPREAD = 0.25           # hull area / track area
MIN_ELONGATION = 0.05       # smaller / larger principal variance of the inlier points (collinear = 0)
MIN_TIME_SPAN_S = 20.0      # one pass in one frame burst is one sample
HELDOUT_CELL_M = 0.3
HELDOUT_EVERY = 5           # every 5th occupied cell is held out
MIN_HELDOUT = 4
HELDOUT_FACTOR = 1.5        # held-out RMS may be at most this times the fit RMS ...
HELDOUT_FLOOR_M = 0.03      # ... or this floor, whichever is larger
HULL_MARGIN_M = 0.05
RANSAC_ITERATIONS = 400


@dataclass(frozen=True)
class Sample:
    t_image: float        # frame capture time, Vision clock
    t_pose: float         # pose stamp, same clock
    px: tuple[float, float]       # marker centre in the full-resolution frame
    x: float              # robot base_footprint, site map metres
    y: float
    yaw: float
    amcl_state: str       # only "LOCALIZED" counts
    pose_age_s: float
    speed_mps: float


def gate_samples(samples: Iterable[Sample]) -> tuple[list[Sample], dict]:
    """Keep fresh, localized, slow, time-aligned samples; thin near-duplicates. Counts say why."""
    dropped = {"not_localized": 0, "stale": 0, "skewed": 0, "fast": 0, "invalid": 0, "duplicate": 0}
    kept: list[Sample] = []
    for s in samples:
        values = (s.t_image, s.t_pose, s.px[0], s.px[1], s.x, s.y, s.yaw, s.pose_age_s, s.speed_mps)
        if not all(math.isfinite(v) for v in values):
            dropped["invalid"] += 1
        elif s.amcl_state != "LOCALIZED":
            dropped["not_localized"] += 1
        elif not 0.0 <= s.pose_age_s <= MAX_POSE_AGE_S:
            dropped["stale"] += 1
        elif abs(s.t_pose - s.t_image) > MAX_TIME_SKEW_S:
            dropped["skewed"] += 1
        elif s.speed_mps > MAX_SPEED_MPS:
            dropped["fast"] += 1
        elif any(math.dist((s.x, s.y), (k.x, k.y)) < DEDUPE_M for k in kept):
            dropped["duplicate"] += 1
        else:
            kept.append(s)
    return kept, dropped


def marker_xy(s: Sample) -> tuple[float, float]:
    """Sticker centre on the map: the robot pose plus the D-587 mount offset turned by yaw."""
    mx, my = MARKER_MOUNT_XY_M
    c, sn = math.cos(s.yaw), math.sin(s.yaw)
    return s.x + mx * c - my * sn, s.y + mx * sn + my * c


def solve_candidate(samples: Sequence[Sample], *, image_size: tuple[int, int],
                    hfov_deg: float | None, track_bounds_m: Sequence[float],
                    approved_map_to_image: Sequence[float] | None = None, seed: int = 0) -> dict:
    """A candidate dict; ``status`` is ``ok`` or the first failing gate. Never raises on data."""
    kept, dropped = gate_samples(samples)
    out = {"version": CANDIDATE_VERSION, "status": "insufficient_samples", "use": "review-only",
           "n_input": len(samples), "n_kept": len(kept), "dropped": dropped}
    if len(kept) < MIN_INLIERS:
        return out
    pix = np.array([s.px for s in kept], float)
    world = np.array([marker_xy(s) for s in kept], float)
    times = np.array([s.t_image for s in kept], float)

    inliers = _ransac(pix, world, np.random.default_rng(seed))
    out["n_inliers"] = int(inliers.sum())
    if inliers.sum() < MIN_INLIERS:
        out["status"] = "insufficient_inliers"
        return out
    if np.ptp(times[inliers]) < MIN_TIME_SPAN_S:
        out["status"] = "insufficient_time_span"
        return out
    pts = world[inliers]
    out["spread"] = round(_hull_area(pts) / _area(track_bounds_m), 3)
    out["elongation"] = round(_elongation(pts), 3)
    if out["spread"] < MIN_SPREAD or out["elongation"] < MIN_ELONGATION:
        out["status"] = "insufficient_spread"
        return out

    held = _heldout(pts)
    fit_pix, fit_world = pix[inliers][~held], world[inliers][~held]
    if held.sum() < MIN_HELDOUT or len(fit_pix) < MIN_INLIERS - MIN_HELDOUT:
        out["status"] = "insufficient_heldout"
        return out
    h_train = _dlt(fit_pix, fit_world)
    rms_fit = _rms(h_train, fit_pix, fit_world)
    rms_held = _rms(h_train, pix[inliers][held], world[inliers][held])
    h_all = _dlt(pix[inliers], world[inliers])  # final plane fit uses every inlier
    out.update(rms_m=round(_rms(h_all, pix[inliers], world[inliers]), 4),
               heldout_rms_m=round(rms_held, 4), n_heldout=int(held.sum()))
    if rms_held > max(HELDOUT_FACTOR * rms_fit, HELDOUT_FLOOR_M):
        out["status"] = "heldout_residual_high"
        return out

    floor = _floor_homography(h_all, image_size, hfov_deg)
    if floor is None:
        out["status"] = "camera_not_solvable"
        return out
    out["image_to_map"] = [float(f"{v:.8g}") for v in floor.reshape(-1)]
    out["plane_height_m"] = MARKER_HEIGHT_M
    out["valid_region_m"] = _grown_hull(pts, HULL_MARGIN_M)
    if approved_map_to_image is not None:
        out["approved_delta_m"] = _approved_delta(floor, approved_map_to_image, pix[inliers])
    out["status"] = "ok"
    return out


# -- numerics ---------------------------------------------------------------


def _dlt(pix: np.ndarray, world: np.ndarray) -> np.ndarray:
    """Pixel -> map homography by normalised DLT; needs >= 4 points."""
    def norm(p):
        c = p.mean(axis=0)
        s = math.sqrt(2.0) / max(np.sqrt(((p - c) ** 2).sum(axis=1)).mean(), 1e-12)
        return np.array([[s, 0, -s * c[0]], [0, s, -s * c[1]], [0, 0, 1.0]])
    tp, tw = norm(pix), norm(world)
    p = np.c_[pix, np.ones(len(pix))] @ tp.T
    w = np.c_[world, np.ones(len(world))] @ tw.T
    rows = []
    for (u, v, _), (x, y, _) in zip(p, w):
        rows.append([u, v, 1, 0, 0, 0, -x * u, -x * v, -x])
        rows.append([0, 0, 0, u, v, 1, -y * u, -y * v, -y])
    h = np.linalg.svd(np.array(rows))[2][-1].reshape(3, 3)
    h = np.linalg.inv(tw) @ h @ tp
    return h / h[2, 2] if abs(h[2, 2]) > 1e-12 else h


def _errors(h: np.ndarray, pix: np.ndarray, world: np.ndarray) -> np.ndarray:
    mapped = geometry.apply(h, pix)
    return np.linalg.norm(mapped - world, axis=1)  # NaN (behind camera) never passes a gate


def _rms(h, pix, world) -> float:
    return float(math.sqrt(np.mean(_errors(h, pix, world) ** 2)))


def _ransac(pix: np.ndarray, world: np.ndarray, rng) -> np.ndarray:
    best = np.zeros(len(pix), bool)
    for _ in range(RANSAC_ITERATIONS):
        idx = rng.choice(len(pix), 4, replace=False)
        if _elongation(world[idx]) < 1e-3:
            continue
        try:
            err = _errors(_dlt(pix[idx], world[idx]), pix, world)
        except np.linalg.LinAlgError:
            continue
        mask = err < INLIER_M
        if mask.sum() > best.sum():
            best = mask
    if best.sum() >= 4:  # refit on the consensus set once and re-gate
        refit = _errors(_dlt(pix[best], world[best]), pix, world) < INLIER_M
        if refit.sum() >= best.sum():
            best = refit
    return best


def _heldout(pts: np.ndarray) -> np.ndarray:
    """Whole spatial cells go held-out together, so neighbours of a fit sample never grade it."""
    cells = [tuple(c) for c in np.floor(pts / HELDOUT_CELL_M).astype(int)]
    order = sorted(set(cells))
    chosen = {c for i, c in enumerate(order) if i % HELDOUT_EVERY == HELDOUT_EVERY - 1}
    return np.array([c in chosen for c in cells])


def _elongation(pts: np.ndarray) -> float:
    eig = np.linalg.eigvalsh(np.cov((pts - pts.mean(axis=0)).T))
    return float(eig[0] / eig[1]) if eig[1] > 1e-12 else 0.0


def _hull(pts: np.ndarray) -> np.ndarray:
    p = sorted(map(tuple, pts))
    def half(seq):
        h = []
        for q in seq:
            while len(h) >= 2 and (h[-1][0] - h[-2][0]) * (q[1] - h[-2][1]) - (h[-1][1] - h[-2][1]) * (q[0] - h[-2][0]) <= 0:
                h.pop()
            h.append(q)
        return h[:-1]
    return np.array(half(p) + half(p[::-1]))


def _hull_area(pts: np.ndarray) -> float:
    h = _hull(pts)
    if len(h) < 3:
        return 0.0
    x, y = h[:, 0], h[:, 1]
    return float(abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2.0)


def _area(bounds: Sequence[float]) -> float:
    return max((bounds[2] - bounds[0]) * (bounds[3] - bounds[1]), 1e-9)


def _grown_hull(pts: np.ndarray, margin: float) -> list[list[float]]:
    """Convex hull (counter-clockwise), each vertex pushed ``margin`` away from the centroid."""
    h = _hull(pts)
    centre = h.mean(axis=0)
    d = h - centre
    grown = h + d / np.maximum(np.linalg.norm(d, axis=1, keepdims=True), 1e-9) * margin
    return [[round(float(x), 4), round(float(y), 4)] for x, y in grown]


def _floor_homography(plane: np.ndarray, size, hfov_deg) -> np.ndarray | None:
    """Pixel -> floor map from the plane-at-marker-height fit: scale about the camera nadir
    by H / (H - h), H the camera height above the floor."""
    cam = geometry.camera_from_homography(plane, size, hfov_deg)
    if cam is None:
        return None
    cx, cy, above = cam
    height = above + MARKER_HEIGHT_M
    k = height / above  # = H / (H - h) with above = H - h
    scale = np.array([[k, 0, cx * (1 - k)], [0, k, cy * (1 - k)], [0, 0, 1.0]])
    return geometry.normalized(scale @ plane)


def _approved_delta(floor: np.ndarray, approved_map_to_image: Sequence[float], pix: np.ndarray) -> dict:
    """How far the approved record would place these same pixels from the candidate (floor
    plane, metres): the number a reviewer reads to tell a moved camera from noise."""
    approved = np.linalg.inv(geometry.as_matrix(approved_map_to_image))
    d = np.linalg.norm(geometry.apply(floor, pix) - geometry.apply(approved, pix), axis=1)
    d = d[np.isfinite(d)]
    return {"median_m": round(float(np.median(d)), 3), "p90_m": round(float(np.percentile(d, 90)), 3)}


def main(argv: Sequence[str]) -> int:
    """``python -m rosy_vision.correspondence samples.jsonl W H HFOV MINX MINY MAXX MAXY``."""
    path, w, h, hfov, *bounds = argv
    rows = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    samples = [Sample(r["t_image"], r["t_pose"], tuple(r["px"]), r["x"], r["y"], r["yaw"],
                      r["amcl_state"], r["pose_age_s"], r["speed_mps"]) for r in rows]
    print(json.dumps(solve_candidate(samples, image_size=(int(w), int(h)), hfov_deg=float(hfov),
                                     track_bounds_m=[float(b) for b in bounds]), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
