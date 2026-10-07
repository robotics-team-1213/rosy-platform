"""Subject: along-lane crosswalk stripes on the keep-mode floor grid (D-491 §4).

The 260919 crosswalks are four 25 mm bars, 120 mm long, laid along the lane at
a 40 mm pitch. A grid row (fixed x ahead of base_link) through one crosses at
least three lit runs of bar width at that pitch; a boundary line is one run and
a ladder bar across the lane is one wide run. The crosswalk is the longest run
of such rows. Observation only: CORE decides what the extent means.
"""

from __future__ import annotations

import numpy as np

from .lane_bev import BEV_CELL_M

#: Bar width and centre pitch bands around the 260919 25 mm / 40 mm bars.
STRIPE_WIDTH_M = (0.012, 0.040)
STRIPE_PITCH_M = (0.030, 0.050)
MIN_STRIPES = 3
#: Rows of stripes needed (20 mm of x) and row gaps bridged inside one crosswalk.
MIN_ROWS = 8
MAX_GAP_ROWS = 2


def _stripes(row: np.ndarray) -> bool:
    edges = np.flatnonzero(np.diff(np.concatenate(([0], row.astype(np.int8), [0]))))
    starts, ends = edges[0::2], edges[1::2]
    widths = (ends - starts) * BEV_CELL_M
    centres = (starts + ends) * 0.5 * BEV_CELL_M
    run = 1
    for k in range(len(starts)):
        if not STRIPE_WIDTH_M[0] <= widths[k] <= STRIPE_WIDTH_M[1]:
            run = 1
            continue
        pitch_ok = (k > 0 and STRIPE_WIDTH_M[0] <= widths[k - 1] <= STRIPE_WIDTH_M[1]
                    and STRIPE_PITCH_M[0] <= centres[k] - centres[k - 1] <= STRIPE_PITCH_M[1])
        run = run + 1 if pitch_ok else 1
        if run >= MIN_STRIPES:
            return True
    return False


def crosswalk_extent(grid: np.ndarray, x_rows: np.ndarray) -> tuple[float, float] | None:
    """(near_m, far_m) ahead of base_link of the longest block of stripe rows, else None.

    grid is the BirdsEye 0/1 floor grid (row i at x_rows[i], columns across the lane).
    """
    best = None
    start = last = None
    for i, row in enumerate(grid):
        if not _stripes(row):
            continue
        if last is None or i - last > MAX_GAP_ROWS + 1:
            start = i
        last = i
        if last - start + 1 >= MIN_ROWS and (best is None or last - start > best[1] - best[0]):
            best = (start, last)
    if best is None:
        return None
    half = BEV_CELL_M * 0.5
    return (round(float(x_rows[best[0]]) - half, 4), round(float(x_rows[best[1]]) + half, 4))
