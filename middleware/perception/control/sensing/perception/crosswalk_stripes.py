"""Subject: along-lane crosswalk stripes on the keep-mode floor grid (D-491 §4).

The 260919 crosswalks are four 25 mm bars, 120 mm long, laid along the lane at
a 40 mm pitch. A grid row (fixed x ahead of base_link) through one crosses at
least three lit runs of bar width at that pitch; a boundary line is one run and
a ladder bar across the lane is one wide run. Only the robot's own corridor
counts, so a crosswalk in the next lane is not reported. The crosswalk is the
longest run of such rows. Observation only: CORE decides what the extent means.

crosswalk_class_extent is the same extent from a learned model's `crosswalk` class (D-597 amendment:
with learned_paint_target drivable the keeper's paint is the drivable way's boundary, which has no
bars): a grid row counts when the class covers CLASS_ROW_FRACTION of the robot's corridor.
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
#: Lane half-width (0.0925 m) rounded up: stripes are counted only across the robot's lane.
CORRIDOR_HALF_M = 0.10
#: Share of the corridor's cells a class row needs: the four bars alone cover about half of it.
CLASS_ROW_FRACTION = 0.25


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


def crosswalk_extent(grid: np.ndarray, x_rows: np.ndarray,
                     y_cols: np.ndarray) -> tuple[float, float] | None:
    """(near_m, far_m) ahead of base_link of the longest block of stripe rows, else None.

    grid is the BirdsEye 0/1 floor grid (row i at x_rows[i], column j at y_cols[j]).
    """
    lane = grid[:, np.abs(y_cols) <= CORRIDOR_HALF_M]
    # Cheap pre-filter (Pi CPU, D-185): a stripe row has at least MIN_STRIPES narrow bars lit.
    enough = lane.sum(axis=1) >= MIN_STRIPES * int(STRIPE_WIDTH_M[0] / BEV_CELL_M)
    return _longest_block([i for i in np.flatnonzero(enough) if _stripes(lane[i])], x_rows)


def crosswalk_class_extent(grid: np.ndarray, x_rows: np.ndarray,
                           y_cols: np.ndarray) -> tuple[float, float] | None:
    """(near_m, far_m) ahead of base_link of the longest block of rows where the model's crosswalk
    class (0/1 BirdsEye grid, as crosswalk_extent) covers CLASS_ROW_FRACTION of the corridor."""
    lane = grid[:, np.abs(y_cols) <= CORRIDOR_HALF_M]
    if not lane.shape[1]:
        return None
    return _longest_block(np.flatnonzero(lane.mean(axis=1) >= CLASS_ROW_FRACTION), x_rows)


def _longest_block(rows, x_rows) -> tuple[float, float] | None:
    """Edges of the longest run of rows (gaps up to MAX_GAP_ROWS bridged) at least MIN_ROWS long."""
    best = None
    start = last = None
    for i in rows:
        if last is None or i - last > MAX_GAP_ROWS + 1:
            start = i
        last = i
        if last - start + 1 >= MIN_ROWS and (best is None or last - start > best[1] - best[0]):
            best = (start, last)
    if best is None:
        return None
    half = BEV_CELL_M * 0.5
    return (round(float(x_rows[best[0]]) - half, 4), round(float(x_rows[best[1]]) + half, 4))


def keep_crosswalk(view, grid: np.ndarray, crosswalk_mask: np.ndarray | None,
                   shape: tuple[int, int]) -> tuple[float, float] | None:
    """The keeper's D-491 crosswalk: stripes in its paint grid, else (D-597 9) the learned crosswalk
    class mask (HxW 0/1 at the frame's `shape`, from the paint's own inference) on the same view."""
    found = crosswalk_extent(grid, view.x[:, 0], view.y[0, :])
    if found is not None or crosswalk_mask is None:
        return found
    if not isinstance(crosswalk_mask, np.ndarray) or crosswalk_mask.shape != tuple(shape):
        raise ValueError("crosswalk_mask must be an array of the frame's height x width")
    return crosswalk_class_extent(view.sample(crosswalk_mask > 0), view.x[:, 0], view.y[0, :])
