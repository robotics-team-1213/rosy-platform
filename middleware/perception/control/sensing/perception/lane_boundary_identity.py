"""Conservative identity check for a stationary odometry-carried paint boundary."""

import numpy as np


STATIC_MAX_LATERAL_SHIFT_M = 0.02
STATIC_MIN_SHARED_ROWS = 8


def stationary_boundary_replaced(fresh_cells, remembered_cells, lateral_m):
    """Reject a matched component whose centre moved while the robot did not.

    Compare only BEV distance rows where both components are visible. A partial
    occlusion can remove an end of the same curved line without changing its
    location at shared ranges. This is a contradiction check, not identity proof:
    another stripe at the same location still needs independent evidence.
    """
    shared = np.flatnonzero(fresh_cells.any(axis=1) & remembered_cells.any(axis=1))
    if len(shared) < STATIC_MIN_SHARED_ROWS:
        return False
    shifts = [abs(float(np.median(lateral_m[row, fresh_cells[row]]))
                  - float(np.median(lateral_m[row, remembered_cells[row]])))
              for row in shared]
    return float(np.median(shifts)) > STATIC_MAX_LATERAL_SHIFT_M
