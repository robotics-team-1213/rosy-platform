"""Bounded D-520 paint evidence from a keeper's already sampled BEV grid."""

import numpy as np

ARC_PAINT_MIN_X_M = 0.10
ARC_PAINT_MAX_X_M = 0.40
ARC_PAINT_X_BINS = 12
ARC_PAINT_PER_BIN = 4


def extract_paint_points(view, grid, stride):
    """Return all coarse lit cells for line fitting and at most 48 debug points.

    Spread evidence over forward distance before sampling lateral quantiles, so
    one dense cross line cannot consume the entire frame's bounded payload.
    No boundary or floor-truth verdict is made here.
    """
    cells = np.flatnonzero(grid[::stride, ::stride].ravel())
    points = np.stack([view.x[::stride, ::stride].ravel()[cells],
                       view.y[::stride, ::stride].ravel()[cells]], axis=1)
    debug = []
    x = points[:, 0]
    for index in range(ARC_PAINT_X_BINS):
        lower = ARC_PAINT_MIN_X_M + (ARC_PAINT_MAX_X_M - ARC_PAINT_MIN_X_M) * index / ARC_PAINT_X_BINS
        upper = ARC_PAINT_MIN_X_M + (ARC_PAINT_MAX_X_M - ARC_PAINT_MIN_X_M) * (index + 1) / ARC_PAINT_X_BINS
        in_bin = points[(x >= lower) & (x <= upper if index == ARC_PAINT_X_BINS - 1 else x < upper)]
        if len(in_bin):
            chosen = np.linspace(0, len(in_bin) - 1, min(len(in_bin), ARC_PAINT_PER_BIN), dtype=int)
            debug.extend(np.round(in_bin[chosen], 3).tolist())
    return points, debug
