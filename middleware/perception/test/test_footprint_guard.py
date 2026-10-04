import math
from control.control.footprint_guard import translation_clearance


def test_straight_front_uses_chassis_edge_not_turning_radius():
    # Test fixture dimensions, not a physical model declaration.
    f, r = translation_clearance([(.07, 0), (-.12, 0)], (.076, .04, .077))
    assert math.isclose(f, .02)
    assert math.isclose(r, .034)


def test_side_jamb_in_swept_strip_is_not_discarded_by_front_cone():
    assert translation_clearance([(.045, .08)], (.076, .04, .077)) == (0., 0.)
    assert translation_clearance([(.045, .09)], (.076, .04, .077)) is None
    assert translation_clearance([(.2, .15), (-.2, -.15)], (.076, .04, .077)) is None


def test_unknown_and_overlapping_points_cannot_authorize_translation():
    assert translation_clearance([], (.076, .04, .077)) is None
    assert translation_clearance([(math.nan, 0)], (.076, .04, .077)) is None
    assert translation_clearance([(0., 0.)], (.076, .04, .077)) == (0., 0.)


def test_side_point_3cm_off_the_body_does_not_freeze_straight_motion():
    """D-424 (E): the box is the URDF body (half width 0.05655 + 0.010), not 0.077 + 0.010.
    A wall 7 cm beside the base centre is outside the swept strip."""
    from control.control.footprint_guard import translation_clearance
    from control.sensing.body import footprint_bounds
    clearance = translation_clearance([(0., .07), (.30, 0.), (-.30, 0.)], footprint_bounds())
    assert clearance is not None and clearance != (0., 0.)
    assert clearance[0] > .2 and clearance[1] > .2
