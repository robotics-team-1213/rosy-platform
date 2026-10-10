"""D-491 §4: along-lane crosswalk stripes on the keep-mode floor grid."""
import numpy as np

from control.sensing.perception.crosswalk_stripes import crosswalk_class_extent, crosswalk_extent
from control.sensing.perception.lane_bev import BEV_CELL_M, BEV_X_MIN_M, BEV_X_MAX_M, BEV_Y_HALF_M

ROWS = int(round((BEV_X_MAX_M - BEV_X_MIN_M) / BEV_CELL_M))
COLS = int(round(2 * BEV_Y_HALF_M / BEV_CELL_M))
X = BEV_X_MIN_M + (np.arange(ROWS) + 0.5) * BEV_CELL_M
Y = BEV_Y_HALF_M - (np.arange(COLS) + 0.5) * BEV_CELL_M


def paint(grid, x0, x1, y0, y1):
    rows = (X >= x0) & (X < x1)
    cols = (Y >= y0) & (Y < y1)
    grid[np.ix_(rows, cols)] = 1


def lane(offset=0.0):
    grid = np.zeros((ROWS, COLS), np.uint8)
    for side in (1, -1):  # 28 mm boundary lines, inner edge 77 mm from the centre
        paint(grid, 0.09, 0.40, offset + side * 0.077 - (side < 0) * 0.028,
              offset + side * 0.077 + (side > 0) * 0.028)
    return grid


def crosswalk(grid, x0, offset=0.0):
    for centre in (-0.060, -0.020, 0.020, 0.060):  # four 25 mm bars, 40 mm pitch, 120 mm long
        paint(grid, x0, x0 + 0.120, offset + centre - 0.0125, offset + centre + 0.0125)
    return grid


def test_crosswalk_ahead_reports_its_near_and_far_edge():
    near, far = crosswalk_extent(crosswalk(lane(), 0.15), X, Y)
    assert abs(near - 0.15) <= BEV_CELL_M and abs(far - 0.27) <= BEV_CELL_M


def test_offset_robot_and_bars_merged_with_a_boundary_still_count():
    # 20 mm off centre: the outer bar runs into the boundary line on one side.
    assert crosswalk_extent(crosswalk(lane(0.02), 0.15, 0.02), X, Y) is not None


def test_plain_lane_and_ladder_marks_are_not_a_crosswalk():
    assert crosswalk_extent(lane(), X, Y) is None
    ladder = lane()
    for x in (0.15, 0.19, 0.23):  # bars across the lane (D-162 ladder) are not along-lane stripes
        paint(ladder, x, x + 0.025, -0.077, 0.077)
    assert crosswalk_extent(ladder, X, Y) is None


def test_two_stripes_or_a_sliver_are_not_enough():
    two = lane()
    for centre in (-0.020, 0.020):
        paint(two, 0.15, 0.27, centre - 0.0125, centre + 0.0125)
    assert crosswalk_extent(two, X, Y) is None
    assert crosswalk_extent(crosswalk(lane(), 0.15)[:0], X[:0], Y) is None
    sliver = lane()
    for centre in (-0.060, -0.020, 0.020, 0.060):
        paint(sliver, 0.15, 0.155, centre - 0.0125, centre + 0.0125)
    assert crosswalk_extent(sliver, X, Y) is None


def test_a_crosswalk_in_the_next_lane_is_not_ours():
    # Next lane centred 0.185 m to the left: its bars sit at y 0.125..0.245.
    assert crosswalk_extent(crosswalk(lane(), 0.15, 0.185), X, Y) is None


def test_crosswalk_class_across_the_lane_reports_its_edges():
    # D-597 amendment: the model's crosswalk class (bars only or the whole band) on the own corridor.
    for grid in (crosswalk(np.zeros((ROWS, COLS), np.uint8), 0.15), np.zeros((ROWS, COLS), np.uint8)):
        if not grid.any():
            paint(grid, 0.15, 0.27, -0.09, 0.09)
        near, far = crosswalk_class_extent(grid, X, Y)
        assert abs(near - 0.15) <= BEV_CELL_M and abs(far - 0.27) <= BEV_CELL_M


def test_crosswalk_class_beside_the_lane_or_a_speck_is_not_ours():
    beside = np.zeros((ROWS, COLS), np.uint8)
    paint(beside, 0.15, 0.27, 0.11, 0.25)                    # the next lane's crosswalk
    assert crosswalk_class_extent(beside, X, Y) is None
    speck = np.zeros((ROWS, COLS), np.uint8)
    paint(speck, 0.15, 0.155, -0.09, 0.09)                   # two rows: a stray label
    assert crosswalk_class_extent(speck, X, Y) is None


def test_class_extent_counts_only_the_cells_the_camera_sees():
    import numpy as np
    from control.sensing.perception.crosswalk_stripes import crosswalk_class_extent
    x = np.arange(0.10, 0.40, 0.0025)
    y = np.arange(-0.10, 0.1001, 0.005)
    grid = np.zeros((len(x), len(y)), np.uint8)
    seen = np.zeros_like(grid, bool)
    seen[:, np.abs(y) <= 0.03] = True                  # near the robot only the middle is in view
    grid[(x >= 0.15) & (x <= 0.25)] = 1
    grid[:, np.abs(y) > 0.03] = 0
    assert crosswalk_class_extent(grid, x, y) is None
    near, far = crosswalk_class_extent(grid, x, y, seen)
    assert 0.14 <= near <= 0.16 and 0.24 <= far <= 0.26
