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
