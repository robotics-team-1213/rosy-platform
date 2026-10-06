"""road_draft: robot-anchored drivable drafts (pure numpy/cv2)."""
import numpy as np

import road_draft as rd


def test_parse_points_scales_0_1000_and_dedupes():
    raw = '[{"point_2d": [500, 500], "label": "floor"}, {"point_2d": [501, 501]}, {"point_2d": [1000, 0]}]'
    assert rd.parse_points(raw, 320, 240) == [[160, 120], [319, 0]]


def test_parse_points_survives_truncated_json_and_caps():
    raw = "`" * 3 + 'json\n[' + ', '.join(f'{{"point_2d": [{10 * i}, 900]}}' for i in range(40)) + ', {"point_2d": [99'
    pts = rd.parse_points(raw, 320, 240, cap=5)
    assert len(pts) == 5 and pts[0] == [0, 216]


def test_bright_is_relative_to_lower_half_floor():
    lum = np.full((60, 80), 90.0)
    lum[40:45, :] = 200.0          # tape
    lum[:10, :] = 230.0            # white wall, also bright
    b = rd.bright_mask(lum)
    assert b[42, 5] and b[5, 5] and not b[55, 5]


def test_yellow_mask():
    rgb = np.zeros((2, 2, 3), np.float32)
    rgb[0, 0] = (230, 180, 20)
    rgb[1, 1] = (200, 200, 200)
    assert rd.yellow_mask(rgb).tolist() == [[True, False], [False, False]]


def test_footprint_band_is_bottom_centre():
    rows, cols = rd.footprint_band(240, 320)
    assert (rows.start, rows.stop, cols.start, cols.stop) == (200, 240, 80, 240)


def test_footprint_seed_prefers_bottom_centre_carpet():
    bright = np.zeros((60, 80), bool)
    lane = np.zeros((60, 80), bool)
    lane[:, 38:43] = True                       # a line straight under the camera
    x, y = rd.footprint_seed(bright, lane)
    assert not lane[y, x] and y >= 50 and abs(x - 40) <= 4


def test_footprint_seed_none_when_band_is_all_tape():
    bright = np.zeros((60, 80), bool)
    bright[50:, :] = True
    assert rd.footprint_seed(bright, np.zeros((60, 80), bool)) is None


def test_gate_drops_points_on_tape_or_lane():
    bright = np.zeros((10, 10), bool); bright[1, 1] = True
    lane = np.zeros((10, 10), bool); lane[2, 2] = True
    assert rd.gate_road_points([[1, 1], [2, 2], [5, 5]], bright, lane) == [[5, 5]]


def _scene():
    """Carpet everywhere, one white line across row 30: the robot is below it."""
    carpet = np.ones((60, 80), bool)
    lane = np.zeros((60, 80), bool)
    lane[29:32, :] = True
    carpet[lane] = False
    return carpet, lane


def test_robot_road_stops_at_the_line():
    carpet, lane = _scene()
    road, unsure = rd.robot_road(carpet, lane)
    assert road[55, 40] and not road[10, 40]
    assert unsure[10, 40] and not unsure[55, 40] and not unsure[30, 40]


def test_robot_road_empty_without_footprint_carpet():
    carpet, lane = _scene()
    carpet[50:, :] = False
    road, unsure = rd.robot_road(carpet, lane)
    assert not road.any() and unsure[10, 40]


def test_close_mask_fills_speckle():
    m = np.ones((20, 20), bool); m[10, 10] = False
    assert rd.close_mask(m)[10, 10]


def test_compose_keeps_lane_wall_and_yellow():
    base = np.full((4, 4), rd.FLOOR, np.uint8)
    base[0, :] = rd.WALL
    base[1, 0] = rd.LANE
    base[3, 3] = rd.IGNORE
    road = np.ones((4, 4), bool)
    yellow = np.zeros((4, 4), bool); yellow[2, 2] = True
    out = rd.compose(base, road, yellow)
    assert (out[0] == rd.WALL).all() and out[1, 0] == rd.LANE
    assert out[2, 2] == rd.FLOOR and out[3, 3] == rd.DRIVABLE and out[1, 1] == rd.DRIVABLE
    assert base[1, 1] == rd.FLOOR      # input untouched
