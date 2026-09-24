from games.field import Field
from games.field.homography import Homography, field_corners, fit


def test_center_pixel_maps_to_pitch_origin():
    field = Field(length_m=2.0, width_m=1.0)
    src = ((0.0, 0.0), (200.0, 0.0), (200.0, 100.0), (0.0, 100.0))
    H = fit(src, field_corners(field))
    x, y = H.apply(100.0, 50.0)
    assert abs(x) < 1e-6
    assert abs(y) < 1e-6


def test_positive_x_corner_maps_to_away_goal_line():
    field = Field(length_m=2.0, width_m=1.0)
    src = ((0.0, 0.0), (200.0, 0.0), (200.0, 100.0), (0.0, 100.0))
    H = fit(src, field_corners(field))
    x, y = H.apply(200.0, 50.0)
    assert abs(x - field.length_m / 2) < 1e-6
    assert abs(y) < 1e-6


def test_heading_follows_a_pixel_edge():
    field = Field(length_m=2.0, width_m=1.0)
    src = ((0.0, 0.0), (200.0, 0.0), (200.0, 100.0), (0.0, 100.0))
    H = fit(src, field_corners(field))
    yaw = H.yaw((100.0, 50.0), (150.0, 50.0))
    assert abs(yaw) < 1e-6
    yaw_up = H.yaw((100.0, 50.0), (100.0, 80.0))
    assert abs(yaw_up - 1.5708) < 1e-3


def test_fit_rejects_fewer_than_four_corners():
    try:
        fit(((0.0, 0.0), (1.0, 0.0), (1.0, 1.0)), ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0)))
    except ValueError as exc:
        assert "four" in str(exc).lower()
    else:
        raise AssertionError("expected ValueError")


def test_homography_is_exported():
    assert Homography is not None
