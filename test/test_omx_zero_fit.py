"""omx_zero_fit: five joint zeros and the 6-DOF camera come back together from gripper landmarks and two
ruler-measured base markers; the cell cameras (S vertical, A/B tilted 13.1 deg) are data, not code paths."""
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/sim"))
import omx_zero_fit as zf  # noqa: E402

CAM = zf.cell_camera("S")


def data(seed, n, px, cam=CAM, span=90.0, base_err=0.0, prior=(None, None), table=False, q_noise=0.0):
    rng = np.random.default_rng(seed)
    zero = zf.PRIOR_DEG + rng.normal(0, 2.0, 5)
    table_mm = zf.TABLE_PRIOR_MM + rng.normal(0, zf.TABLE_SIGMA_MM) if table else 0.0
    poses = zf.sample_poses(rng, n, zero, [cam])
    base = zf.measured_base(rng, zf.base_corners(span), base_err)
    reported, obs, touch, base_obs = zf.observe(rng, poses, zero, [cam], px, q_noise, table_mm, base, px)
    return zero, table_mm, reported, obs, touch, base, base_obs


def test_noise_free_markers_return_the_zeros():
    zero, _, reported, obs, _, base, base_obs = data(1, 12, px=1e-9)
    res = zf.fit(reported, obs, [CAM], 1.0, base_obs=base_obs, base_meas=base)
    assert np.abs(res.x[:5] - zero).max() < 0.02  # FK rounds positions to 1 um; 0.02 deg is that rounding, not the method


def test_one_touch_also_returns_the_table_offset():
    zero, table, reported, obs, touch, base, base_obs = data(2, 12, px=1e-9, table=True)
    res = zf.fit(reported, obs, [CAM], 1.0, base_obs=base_obs, base_meas=base, touch_z=touch, with_table=True)
    assert np.abs(res.x[:5] - zero).max() < 0.05 and abs(res.x[5] - table) < 1.5  # touch is ruled to +-0.5 mm


def test_poses_that_leave_the_image_or_drop_to_the_table_are_never_used():
    rng = np.random.default_rng(3)
    for q in zf.sample_poses(rng, 8, zf.PRIOR_DEG, [CAM]):
        pts = zf.landmarks(q, zf.PRIOR_DEG)
        uv, depth = zf.project(pts, CAM)
        assert pts[:, 2].min() >= 20.0 and (depth > 50).all() and (uv >= 10).all()
        assert (uv[:, 0] <= 630).all() and (uv[:, 1] <= 470).all()


def test_the_same_seed_gives_the_same_result():
    a, b = zf.trial(4, 12, 1.0, CAM), zf.trial(4, 12, 1.0, CAM)
    assert np.array_equal(a[0], b[0])


def test_one_pixel_and_sixteen_poses_stay_inside_the_budget_and_three_pixels_do_not():
    # base markers 90 mm apart, camera free: 1 px keeps every joint's error p90 inside 0.5 deg; 3 px does not
    good = np.array([zf.trial(s, 16, 1.0, CAM)[0] for s in range(8)])
    coarse = np.array([zf.trial(s, 16, 3.0, CAM)[0] for s in range(8)])
    assert np.median(good, 0).max() <= zf.BUDGET_DEG
    assert np.percentile(coarse, 90, 0).max() > zf.BUDGET_DEG


def test_zero_fit_tilted_camera_within_budget():
    """Cell A (596 mm, tilted 13.1 deg), 1 px corners, 16 poses, base span 90 mm: still inside the budget."""
    cam = zf.cell_camera("A")
    errs = np.array([zf.trial(s, 16, 1.0, cam, span_mm=90.0)[0] for s in range(8)])
    assert np.percentile(errs, 90, 0).max() <= zf.BUDGET_DEG
    assert np.median(errs, 0).max() <= zf.BUDGET_DEG
