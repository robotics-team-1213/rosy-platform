#!/usr/bin/env python3
"""Separate boxes that only touch, inside one foreground blob of the top view (2026-10-29).

A 1-cell and a 2-cell lying corner to corner on the floor made one blob that matched no catalogue entry, so neither
could be picked and no push could part them (every push start fell on the other box). Where boxes only touch, the
blob has a narrow neck: the distance to the background is small there and large in each box's middle. Markers are
the parts of the distance map above a fraction of its peak, one per box; a watershed from them gives each box its
own pixels. A blob with one marker is returned as no split. Plain OpenCV/numpy: no cell config, so any camera and
surface can use it; cell_objects decides whether the pieces are real (each must match the catalogue).
"""
from __future__ import annotations

import numpy as np


def split_touching(mask, peak_frac: float = 0.6, min_piece_px: int = 200) -> list:
    """Boolean masks (same shape as `mask`), one per touching box, or [] when the blob is one piece.
    `peak_frac`: markers are where the distance to the background is above this fraction of its maximum; a neck
    thinner than that fraction of the widest box separates them. Pieces under `min_piece_px` are dropped."""
    import cv2

    arr = np.asarray(mask) > 0
    ys, xs = np.nonzero(arr)
    if len(xs) < 2 * min_piece_px:
        return []
    h, w = arr.shape
    y0, y1 = max(0, int(ys.min()) - 1), min(h, int(ys.max()) + 2)
    x0, x1 = max(0, int(xs.min()) - 1), min(w, int(xs.max()) + 2)
    blob = arr[y0:y1, x0:x1].astype(np.uint8)
    dist = cv2.distanceTransform(blob, cv2.DIST_L2, 5)
    thresh = peak_frac * float(dist.max())
    n, markers = cv2.connectedComponents((dist > thresh).astype(np.uint8))
    if n <= 2:  # background plus one marker: one box
        return []
    markers = markers + 1  # watershed: 0 is unknown, 1 the background
    markers[blob == 0] = 1
    markers[(blob == 1) & (dist <= thresh)] = 0
    cv2.watershed(cv2.cvtColor(blob * 255, cv2.COLOR_GRAY2BGR), markers)
    pieces = []
    for k in range(2, n + 1):
        sub = (markers == k) & (blob == 1)
        if int(sub.sum()) >= min_piece_px:
            full = np.zeros(arr.shape, bool)
            full[y0:y1, x0:x1] = sub
            pieces.append(full)
    return pieces if len(pieces) >= 2 else []
