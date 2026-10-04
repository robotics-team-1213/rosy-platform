import numpy as np
import pytest

from tools.gz.track_map_audit import measure, measure_robot_reachable


WALLS = [([0, -1, 0, 0, 0, 0], [2, .02, .2]),
         ([0, 1, 0, 0, 0, 0], [2, .02, .2]),
         ([-1, 0, 0, 0, 0, 0], [.02, 2, .2]),
         ([1, 0, 0, 0, 0, 0], [.02, 2, .2])]


def raster():
    arr = np.zeros((202, 202), dtype=np.int16)
    arr[:2] = arr[-2:] = 100
    arr[:, :2] = arr[:, -2:] = 100
    return arr


def test_empty_and_cropped_maps_cannot_pass_full_world_audit():
    empty = measure(np.full((202, 202), -1), [-1.01, -1.01], .01, WALLS)
    assert empty['interior_unknown_fraction'] == 1
    assert not empty['map_raster_complete']
    cropped = measure(np.zeros((50, 50)), [-.25, -.25], .01, WALLS)
    assert cropped['interior_unknown_fraction'] > .9
    assert not cropped['map_raster_complete']


def test_complete_raster_passes_and_phantom_obstacle_fails():
    arr = raster()
    good = measure(arr, [-1.01, -1.01], .01, WALLS)
    assert good['map_raster_complete']
    arr[70:130, 70:130] = 100
    bad = measure(arr, [-1.01, -1.01], .01, WALLS)
    assert not bad['map_raster_complete']
    assert bad['phantom_fraction'] > .02


def test_exact_world_has_a_sealed_triangle_outside_spawn_component():
    from pathlib import Path
    import xml.etree.ElementTree as ET
    from tools.gz.prepare_track_world import boxes
    from tools.gz.track_map_audit import topology
    walls = boxes(ET.parse(Path(__file__).resolve().parents[1]/'map/map_260905.world'))
    result = topology(walls, [-.2, .27])
    assert result['free_components'] == 2
    assert .08 < result['sealed_free_area_m2'] < .11
    assert .02 < result['sealed_free_fraction'] < .04


def test_robot_reachable_audit_excludes_a_bay_narrower_than_the_body():
    from tools.gz.track_map_audit import measure_point_reachable

    # Split the room with a 180 mm throat.  A point passes, but the 172 mm
    # body plus 10 mm clearance on each side does not.
    walls = WALLS + [
        ([0, .545, 0, 0, 0, 0], [.02, .91, .2]),
        ([0, -.545, 0, 0, 0, 0], [.02, .91, .2]),
    ]
    resolution = .01
    origin = [-1.01, -1.01]
    arr = np.zeros((202, 202), dtype=np.int16)
    xs = origin[0] + (np.arange(arr.shape[1]) + .5) * resolution
    ys = origin[1] + (np.arange(arr.shape[0]) + .5) * resolution
    xx, yy = np.meshgrid(xs, ys)
    arr[xx < -.02] = -1

    point = measure_point_reachable(arr, origin, resolution, walls, [.5, 0.])
    robot = measure_robot_reachable(
        arr, origin, resolution, walls, [.5, 0.],
        robot_radius=.086, clearance_margin=.010)

    assert point['unknown_fraction'] > .05
    assert robot['unknown_fraction'] == 0
    assert robot['required_center_clearance_m'] == pytest.approx(.096)
    assert robot['robot_footprint_accessibility'] is True
