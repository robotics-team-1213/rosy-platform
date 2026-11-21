from core_common.homography import Homography, fit

SRC = ((0.0, 0.0), (200.0, 0.0), (200.0, 100.0), (0.0, 100.0))
DST = ((-1.0, -0.5), (1.0, -0.5), (1.0, 0.5), (-1.0, 0.5))


def test_center_pixel_maps_to_origin():
    x, y = fit(SRC, DST).apply(100.0, 50.0)
    assert abs(x) < 1e-6
    assert abs(y) < 1e-6


def test_positive_x_corner_maps_to_far_edge():
    x, y = fit(SRC, DST).apply(200.0, 50.0)
    assert abs(x - 1.0) < 1e-6
    assert abs(y) < 1e-6


def test_heading_follows_a_pixel_edge():
    H = fit(SRC, DST)
    assert abs(H.yaw((100.0, 50.0), (150.0, 50.0))) < 1e-6
    assert abs(H.yaw((100.0, 50.0), (100.0, 80.0)) - 1.5708) < 1e-3


def test_fit_rejects_fewer_than_four_corners():
    try:
        fit(SRC[:3], DST[:3])
    except ValueError as exc:
        assert "four" in str(exc).lower()
    else:
        raise AssertionError("expected ValueError")


def test_homography_is_a_frozen_value():
    assert isinstance(fit(SRC, DST), Homography)
