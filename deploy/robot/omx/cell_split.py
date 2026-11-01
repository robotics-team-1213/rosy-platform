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

    blob = (np.asarray(mask) > 0).astype(np.uint8)
    if blob.sum() < 2 * min_piece_px:
        return []
    dist = cv2.distanceTransform(blob, cv2.DIST_L2, 5)
    n, markers = cv2.connectedComponents((dist > peak_frac * dist.max()).astype(np.uint8))
    if n <= 2:  # background plus one marker: one box
        return []
    markers = markers + 1  # watershed: 0 is unknown, 1 the background
    markers[blob == 0] = 1
    markers[(blob == 1) & (dist <= peak_frac * dist.max())] = 0
    cv2.watershed(cv2.cvtColor(blob * 255, cv2.COLOR_GRAY2BGR), markers)
    pieces = [(markers == k) & (blob == 1) for k in range(2, n + 1)]
    pieces = [p for p in pieces if p.sum() >= min_piece_px]
    return pieces if len(pieces) >= 2 else []
