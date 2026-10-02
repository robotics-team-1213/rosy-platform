"""D-395 §7: paint separates a pose from its 180-degree mirror on map_v2_fleet."""
import math

import pytest

from control.sensing.perception.paint_hypothesis import paint_score
from loc_world import mirror, paint_map, paint_points

POSES = [(-1.26, .49, math.pi / 2), (-1.26, .49, -math.pi / 2), (.86, -.52, 0.),
         (.86, -.52, math.pi), (0., .51, 0.), (-.9, -.509, 0.)]


@pytest.mark.parametrize("pose", POSES)
def test_the_true_pose_explains_the_paint_and_the_mirror_does_not(pose):
    points = paint_points(pose)
    assert paint_score(paint_map(), points, pose) > .9
    assert paint_score(paint_map(), points, mirror(pose)) < .1


def test_too_few_or_non_finite_points_are_no_evidence():
    assert paint_score(paint_map(), [(.2, 0.)] * 9, (0., 0., 0.)) is None
    assert paint_score(paint_map(), [(math.nan, 0.)] * 20, (0., 0., 0.)) is None
    assert paint_score(paint_map(), [(.2, 0.)] * 20, (math.nan, 0., 0.)) is None


def _floor_with_a_line(ground, width=320, height=240, left_m=0.):
    """Grey carpet with a white tape line along x at lateral `left_m`, drawn through the BEV grid."""
    import numpy as np
    from control.sensing.perception.lane_bev import BirdsEye
    image = np.full((height, width, 3), 90, np.uint8)
    view = BirdsEye(ground, width, height, 0.)
    on = view.observable & (np.abs(view.y - left_m) < .0125)
    image[view._pixel_row[on], view._pixel_col[on]] = 235
    return image


def _ground():
    from control.sensing.perception.camera_ground import ground_plane
    return ground_plane(height_m=.063, pitch_rad=math.radians(11.8), focal_px=260., principal_x=160.,
                        principal_y=120., max_range_m=.6)


def test_camera_paint_points_lie_on_the_painted_line_in_base_link():
    import numpy as np
    from control.sensing.perception.paint_hypothesis import camera_paint_points
    points = camera_paint_points(_floor_with_a_line(_ground(), left_m=.05), _ground(), 0.)
    assert len(points) >= 10
    assert np.median(np.abs(points[:, 1] - .05)) < .01 and np.all(points[:, 0] > 0)


def test_camera_paint_points_feed_paint_score_and_tell_the_side():
    import numpy as np
    from control.sensing.perception.paint_hypothesis import camera_paint_points

    class LineAtY0:                     # a 25 mm tape: distance is 0 on the paint
        def distance_at(self, xy):
            return np.maximum(0., np.abs(xy[..., 1]) - .0125)
    points = camera_paint_points(_floor_with_a_line(_ground(), left_m=0.), _ground(), 0.)
    assert paint_score(LineAtY0(), points, (0., 0., 0.)) > .5
    assert paint_score(LineAtY0(), points, (0., .06, 0.)) < .1


def test_no_ground_or_bare_carpet_gives_no_points():
    import numpy as np
    from control.sensing.perception.paint_hypothesis import camera_paint_points
    bare = np.full((240, 320, 3), 90, np.uint8)
    assert len(camera_paint_points(bare, _ground(), 0.)) == 0
    assert len(camera_paint_points(bare, None, 0.)) == 0
