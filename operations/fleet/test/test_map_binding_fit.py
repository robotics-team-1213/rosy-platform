"""D-1022: robot map -> site fit, its refusals, and the marker-free proposal from the arena walls."""
import math

import pytest

from fleet.localization.map_binding import (BindingError, Fit, bound_pose, fit_rigid, judge, min_area_rect,
                                            propose_from_walls)

ARENA = (-1.22, -0.61, 1.22, 0.61)
TRUTH = Fit(math.radians(30), 0.4, -0.2, ())  # robot map -> site


def robot_of(site_pts):
    return [TRUTH.inverse(p) for p in site_pts]


SITE = [(-1.0, -0.5), (1.0, -0.5), (0.9, 0.45), (-0.6, 0.4)]
HOLD = [(0.0, 0.0)]


def test_a_clean_fit_recovers_the_transform_and_passes_holdout():
    fit, errors = judge(robot_of(SITE), SITE, [(TRUTH.inverse(p), p) for p in HOLD])
    assert fit.yaw == pytest.approx(TRUTH.yaw) and (fit.tx, fit.ty) == pytest.approx((TRUTH.tx, TRUTH.ty))
    assert max(errors) < 1e-9
    assert bound_pose(fit, (*TRUTH.inverse((0.2, 0.1)), 0.0))[:2] == pytest.approx((0.2, 0.1))


@pytest.mark.parametrize("code, robot, site, hold", [
    ("TOO_FEW_PAIRS", robot_of(SITE[:2]), SITE[:2], HOLD),
    ("COLLINEAR", robot_of([(-1, 0), (0, 0), (1, 0)]), [(-1, 0), (0, 0), (1, 0)], HOLD),
    ("SPAN", robot_of([(0, 0), (0.3, 0), (0, 0.3)]), [(0, 0), (0.3, 0), (0, 0.3)], HOLD),
    ("HOLDOUT_REQUIRED", robot_of(SITE), SITE, []),
])
def test_refusals(code, robot, site, hold):
    with pytest.raises(BindingError) as err:
        judge(robot, site, [(TRUTH.inverse(p), p) for p in hold])
    assert err.value.code == code


def test_a_wrong_point_is_a_residual_refusal_and_a_mirror_is_named():
    robot = robot_of(SITE)
    robot[2] = (robot[2][0] + 0.2, robot[2][1])
    with pytest.raises(BindingError) as err:
        judge(robot, SITE, [(TRUTH.inverse(p), p) for p in HOLD])
    assert err.value.code == "RESIDUAL"
    mirrored = [(p[0], -p[1]) for p in robot_of(SITE)]
    with pytest.raises(BindingError) as err:
        judge(mirrored, SITE, [(TRUTH.inverse(p), p) for p in HOLD])
    assert err.value.code == "MIRRORED"


def test_a_bad_holdout_refuses():
    with pytest.raises(BindingError) as err:
        judge(robot_of(SITE), SITE, [(TRUTH.inverse((0, 0)), (0.1, 0))])
    assert err.value.code == "HOLDOUT"


def _walls(fit=TRUTH, step=0.05):
    """Occupied cells of the arena walls, expressed in the robot map frame."""
    pts = []
    x = ARENA[0]
    while x <= ARENA[2] + 1e-9:
        pts += [(x, ARENA[1]), (x, ARENA[3])]
        x += step
    y = ARENA[1]
    while y <= ARENA[3] + 1e-9:
        pts += [(ARENA[0], y), (ARENA[2], y)]
        y += step
    return [fit.inverse(p) for p in pts]


def test_min_area_rect_finds_the_arena_rotated():
    centre, w, h, _ = min_area_rect(_walls())
    assert (w, h) == pytest.approx((2.44, 1.22), abs=0.06)
    assert centre == pytest.approx(TRUTH.inverse((0, 0)), abs=0.03)


@pytest.mark.parametrize("seed_site", [(-0.42, 0.38), (0.9, -0.3)])
def test_walls_plus_one_seed_give_pairs_that_bind_to_the_truth(seed_site):
    robot, site = propose_from_walls(_walls(), ARENA, seed_robot=TRUTH.inverse(seed_site), seed_site=seed_site)
    fit, _ = judge(robot, site, [(TRUTH.inverse(p), p) for p in HOLD], max_residual=0.06)
    assert fit.apply(TRUTH.inverse((0.5, 0.2))) == pytest.approx((0.5, 0.2), abs=0.03)


def test_a_seed_at_the_centre_cannot_choose_the_orientation():
    with pytest.raises(BindingError) as err:
        propose_from_walls(_walls(), ARENA, seed_robot=TRUTH.inverse((0.0, 0.0)), seed_site=(0.0, 0.0))
    assert err.value.code == "SEED_AMBIGUOUS"


def test_walls_of_another_size_are_refused():
    small = [(p[0] * 0.6, p[1] * 0.6) for p in _walls(Fit(0, 0, 0, ()))]
    with pytest.raises(BindingError) as err:
        propose_from_walls(small, ARENA, seed_robot=(-0.4, 0.3), seed_site=(-0.4, 0.3))
    assert err.value.code == "WALLS_MISMATCH"
