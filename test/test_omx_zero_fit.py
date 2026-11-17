"""omx_zero_fit: five joint zeros come back from gripper markers seen by a camera fixed by the base marker."""
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/sim"))
import omx_zero_fit as zf  # noqa: E402

CAMS = [zf.camera("top")]


def data(seed, n, px, q_noise=0.0, table=False):
    rng = np.random.default_rng(seed)
    zero = zf.PRIOR_DEG + rng.normal(0, 2.0, 5)
    table_mm = zf.TABLE_PRIOR_MM + rng.normal(0, zf.TABLE_SIGMA_MM) if table else 0.0
    poses = zf.sample_poses(rng, n, zero, CAMS)
    reported, obs, touch = zf.observe(rng, poses, zero, CAMS, px, q_noise, table_mm)
    return zero, table_mm, reported, obs, touch


def test_noise_free_markers_return_the_zeros():
    zero, _, reported, obs, _ = data(1, 12, px=1e-9)
    fitted, _, _ = zf.fit(reported, obs, CAMS, px=1.0)
    assert np.abs(fitted - zero).max() < 0.02  # FK rounds positions to 1 um; 0.02 deg is that rounding, not the method


def test_one_touch_also_returns_the_table_offset():
    zero, table, reported, obs, touch = data(2, 12, px=1e-9, table=True)
    fitted, fitted_table, _ = zf.fit(reported, obs, CAMS, px=1.0, touch_z=touch, with_table=True)
    assert np.abs(fitted - zero).max() < 0.05 and abs(fitted_table - table) < 1.5  # touch is ruled to +-0.5 mm


def test_poses_that_leave_the_image_or_drop_to_the_table_are_never_used():
    rng = np.random.default_rng(3)
    for q in zf.sample_poses(rng, 8, zf.PRIOR_DEG, CAMS):
        pts = zf.landmarks(q, zf.PRIOR_DEG)
        uv, depth = zf.project(pts, CAMS[0])
        assert pts[:, 2].min() >= 20.0 and (depth > 50).all() and (uv >= 10).all()
        assert (uv[:, 0] <= 630).all() and (uv[:, 1] <= 470).all()


def test_the_same_seed_gives_the_same_result():
    a, b = zf.trial(4, 12, 1.0, CAMS), zf.trial(4, 12, 1.0, CAMS)
    assert np.array_equal(a[0], b[0])


def test_one_pixel_and_sixteen_poses_stay_inside_the_budget_and_three_pixels_do_not():
    # 2026-11-17 sweep, 20 seeds: 1 px / 16 poses p90 [0.04 0.09 0.13 0.18 0.34] deg, 3 px p90 j4 0.68, j5 0.99
    good = np.array([zf.trial(s, 16, 1.0, CAMS)[0] for s in range(8)])
    coarse = np.array([zf.trial(s, 16, 3.0, CAMS)[0] for s in range(8)])
    assert np.median(good, 0).max() <= zf.BUDGET_DEG
    assert np.percentile(coarse, 90, 0).max() > zf.BUDGET_DEG
