"""Conservatively register CAD landmark pixels between two nearly identical top views.

This estimates a 2-D image mapping only. It does not identify either physical fixture
or measure its support height, arm pose, or clearance.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import numpy as np


def _read(path):
    data = Path(path).read_bytes()
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE) if data else None
    if image is None:
        raise ValueError(f"unreadable image: {path}")
    return image, hashlib.sha256(data).hexdigest()


def _pairs(left, right):
    detector = cv2.SIFT_create(nfeatures=4000)
    a, da = detector.detectAndCompute(left, None)
    b, db = detector.detectAndCompute(right, None)
    if min(len(a), len(b)) < 35:
        raise ValueError("insufficient image features")
    matcher = cv2.BFMatcher()

    def unique_matches(first, second):
        return {m.queryIdx: m for m, n in matcher.knnMatch(first, second, k=2)
                if m.distance < 0.75 * n.distance}

    forward = unique_matches(da, db)
    reverse = unique_matches(db, da)
    used_source, used_target, pairs = set(), set(), []
    for m in sorted(forward.values(), key=lambda item: item.distance):
        back = reverse.get(m.trainIdx)
        if back is None or back.trainIdx != m.queryIdx:
            continue
        p, q = a[m.queryIdx].pt, b[m.trainIdx].pt
        cell_p, cell_q = tuple(int(v // 6) for v in p), tuple(int(v // 6) for v in q)
        if cell_p not in used_source and cell_q not in used_target:
            used_source.add(cell_p)
            used_target.add(cell_q)
            pairs.append([p, q])
    if len(pairs) < 35:
        raise ValueError("insufficient reciprocal, spatially distinct matches")
    return np.asarray(pairs, dtype=np.float32).transpose(1, 0, 2)


def _project(points, matrix):
    return cv2.perspectiveTransform(np.asarray(points, np.float32).reshape(-1, 1, 2), matrix)[:, 0]


def project_centers(source_path, reference_path, centers: dict[str, list[float]]) -> tuple[dict, dict]:
    """Return reference-image pixels and evidence; raise ValueError on unsupported mapping."""
    source, source_hash = _read(source_path)
    reference, reference_hash = _read(reference_path)
    h, w = source.shape
    if source.shape != reference.shape:
        raise ValueError("different image shapes")
    points = np.asarray(list(centers.values()), dtype=np.float64)
    if (not centers or points.shape != (len(centers), 2) or not np.isfinite(points).all()
            or (points < 0).any() or (points > [w-1, h-1]).any()):
        raise ValueError("invalid source centers")
    evidence = {"source_sha256": source_hash, "reference_sha256": reference_hash, "image_wh": [w, h]}
    if source_hash == reference_hash:
        return dict(zip(centers, points.tolist())), {**evidence, "method": "identical_bytes"}

    src, dst = _pairs(source, reference)
    # Entire 16px spatial blocks go to one split, so repeated descriptors cannot self-validate.
    blocks = (src // 16).astype(int)
    held = (blocks[:, 0] + 2 * blocks[:, 1]) % 3 == 0
    if held.sum() < 12 or (~held).sum() < 22:
        raise ValueError("insufficient spatially split matches")
    matrix, mask = cv2.findHomography(src[~held], dst[~held], cv2.RANSAC, 1.5)
    if matrix is None or not np.isfinite(matrix).all() or mask.sum() < max(20, 0.7 * (~held).sum()):
        raise ValueError("insufficient consistent plane matches")

    # At large shifts, even a good planar fit can transfer features at the wrong height.
    grid = [[x, y] for x in (0, w//2, w-1) for y in (0, h//2, h-1)]
    probe = np.vstack([grid, points])
    drift = float(np.linalg.norm(_project(probe, matrix) - probe, axis=1).max())
    if not np.isfinite(drift) or drift > 3:
        raise ValueError(f"camera displacement {drift:.2f}px exceeds 3px")
    hs, hd = src[held], dst[held]
    error = np.linalg.norm(_project(hs, matrix) - hd, axis=1)
    if not np.isfinite(error).all():
        raise ValueError("nonfinite held-out residual")
    good = error <= 1.5
    if good.mean() < 0.85:
        raise ValueError(f"held-out plane disagreement: {good.sum()}/{len(good)} within 1.5px")

    local = {}
    for name, xy in zip(centers, points):
        near = np.linalg.norm(hs - xy, axis=1) <= 90
        support = hs[near & good]
        if len(support) < 5 or good[near].mean() < 0.8:
            raise ValueError(f"insufficient local held-out agreement for {name}: {len(support)}/{near.sum()} within 1.5px")
        # Require surrounding observations; one edge of an unrelated fixture is insufficient.
        hull = cv2.convexHull(support)
        margin = cv2.pointPolygonTest(hull, tuple(map(float, xy)), True)
        if margin < 3:
            raise ValueError(f"local held-out matches do not surround {name}")
        local[name] = {"held_out": int(near.sum()), "agree": len(support), "hull_margin_px": margin,
                       "median_residual_px": float(np.median(error[near])), "max_residual_px": float(np.max(error[near]))}

    projected = _project(points, matrix)
    if not np.isfinite(projected).all() or (projected < 0).any() or (projected > [w-1,h-1]).any():
        raise ValueError("projection outside reference image")
    return dict(zip(centers, projected.tolist())), {**evidence, "method": "sift_held_out",
        "homography": matrix.tolist(), "max_displacement_px": drift, "fit_inliers": int(mask.sum()),
        "held_out": len(hs), "held_out_agree": int(good.sum()), "local": local}
