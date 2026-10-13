"""D-457 3: homography helpers — camera position from a floor homography and height parallax."""

import math

import numpy as np
import pytest

from rosy_vision.track import geometry

SIZE = (1280, 720)
FOCAL = 800.0
HFOV = math.degrees(2 * math.atan((SIZE[0] / 2) / FOCAL))


def _rotation(pitch_deg, yaw_deg=0.0, roll_deg=0.0):
    down = np.array([[1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, -1.0]])
    a, y, r = (math.radians(v) for v in (pitch_deg, yaw_deg, roll_deg))
    tilt = np.array([[1.0, 0.0, 0.0], [0.0, math.cos(a), -math.sin(a)], [0.0, math.sin(a), math.cos(a)]])
    spin = np.array([[math.cos(y), -math.sin(y), 0.0], [math.sin(y), math.cos(y), 0.0], [0.0, 0.0, 1.0]])
    bank = np.array([[math.cos(r), 0.0, math.sin(r)], [0.0, 1.0, 0.0], [-math.sin(r), 0.0, math.cos(r)]])
    return bank @ tilt @ down @ spin


def _k():
    return np.array([[FOCAL, 0.0, SIZE[0] / 2], [0.0, FOCAL, SIZE[1] / 2], [0.0, 0.0, 1.0]])


def _image_to_map(centre, pitch_deg, yaw_deg=0.0, roll_deg=0.0):
    rotation = _rotation(pitch_deg, yaw_deg, roll_deg)
    t = -rotation @ np.asarray(centre, float)
    map_to_image = _k() @ np.column_stack([rotation[:, 0], rotation[:, 1], t])
    return np.linalg.inv(map_to_image)


@pytest.mark.parametrize("pitch", [0.0, 20.0])
@pytest.mark.parametrize("scale", [1.0, -3.0])
def test_camera_position_is_recovered_from_the_floor_homography(pitch, scale):
    camera = geometry.camera_from_homography(_image_to_map((1.0, 0.5, 2.5), pitch) * scale, SIZE, HFOV)
    assert camera == pytest.approx((1.0, 0.5, 2.5), abs=1e-6)


def test_no_lens_or_implausible_height_means_no_camera():
    image_to_map = _image_to_map((1.0, 0.5, 2.5), 0.0)
    assert geometry.camera_from_homography(image_to_map, SIZE, None) is None
    assert geometry.camera_from_homography(image_to_map, SIZE, 0.0) is None
    assert geometry.camera_from_homography(_image_to_map((0.0, 0.0, 20.0), 0.0), SIZE, HFOV) is None


def test_parallax_pulls_a_top_point_toward_the_nadir():
    assert geometry.parallax_correct((1.0, 0.0), (0.0, 0.0, 2.5), 0.125) == pytest.approx((0.95, 0.0))
    assert geometry.parallax_correct((0.0, 0.0), (0.0, 0.0, 2.5), 0.125) == pytest.approx((0.0, 0.0))


def test_apply_and_scaled_agree_for_a_resized_image():
    image_to_map = np.array([[0.005, 0.0, 0.0], [0.0, -0.005, 3.6], [0.0, 0.0, 1.0]])
    full = geometry.apply(image_to_map, [[600.0, 200.0]])[0]
    half = geometry.apply(geometry.scaled(image_to_map, 0.5, 0.5), [[300.0, 100.0]])[0]
    assert full == pytest.approx((3.0, 2.6)) and half == pytest.approx(full)


def test_centre_scale_maps_pixel_centres_between_resolutions():
    # Pixel 100 of a 640 wide image covers [100, 101) of 640; at 1280 that is pixels 200-201,
    # whose shared centre is 200.5. So index 100 of the small image is 200.5 in the large one.
    small_to_large = geometry.centre_scale(2.0, 2.0)
    assert geometry.apply(small_to_large, [[100.0, 50.0]])[0] == pytest.approx((200.5, 100.5))
    assert geometry.centre_scale(1.0, 1.0) == pytest.approx(np.eye(3))
    large_to_small = geometry.centre_scale(0.5, 0.5)
    assert geometry.apply(large_to_small, [[200.5, 100.5]])[0] == pytest.approx((100.0, 50.0))


def test_as_matrix_refuses_non_finite_values_and_normalized_divides_by_h22():
    with pytest.raises(ValueError):
        geometry.as_matrix([float("nan")] + [0.0] * 8)
    assert geometry.normalized(np.diag([2.0, 2.0, 2.0]))[2, 2] == pytest.approx(1.0)


def test_camera_position_is_recovered_with_yaw_pitch_and_roll():
    camera = geometry.camera_from_homography(_image_to_map((1.0, 0.5, 2.5), 15.0, 30.0, 8.0), SIZE, HFOV)
    assert camera == pytest.approx((1.0, 0.5, 2.5), abs=1e-6)


def test_a_wrong_lens_is_refused_instead_of_giving_a_wrong_camera():
    image_to_map = _image_to_map((1.0, 0.5, 2.5), 25.0, 20.0)
    assert geometry.camera_from_homography(image_to_map, SIZE, 40.0) is None


def test_ray_cast_top_point_is_corrected_to_its_floor_position():
    centre, height = (1.0, 0.5, 2.5), 0.125
    rotation = _rotation(20.0, 30.0, 5.0)
    floor = np.array([1.4, 0.9])
    top = np.array([floor[0], floor[1], height])
    cam = _k() @ rotation @ (top - np.asarray(centre))
    pixel = cam[:2] / cam[2]
    image_to_map = _image_to_map(centre, 20.0, 30.0, 5.0)
    seen = geometry.apply(image_to_map, [pixel])[0]
    camera = geometry.camera_from_homography(image_to_map, SIZE, HFOV)
    assert geometry.parallax_correct(seen, camera, height) == pytest.approx(tuple(floor), abs=1e-6)


def test_apply_returns_nan_on_the_horizon_and_behind_the_camera_without_warnings(recwarn):
    homography = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.001, 1.0]])
    out = geometry.apply(homography, [[10.0, 0.0], [10.0, -1000.0], [10.0, -2000.0], [10.0, 100.0]])
    assert np.isnan(out[1]).all() and np.isnan(out[2]).all()
    assert out[0] == pytest.approx((10.0, 0.0)) and np.isfinite(out[3]).all()
    assert not [w for w in recwarn if issubclass(w.category, RuntimeWarning)]


@pytest.mark.parametrize("height", [-0.1, 2.5, 3.0])
def test_parallax_height_must_be_below_the_camera(height):
    with pytest.raises(ValueError):
        geometry.parallax_correct((1.0, 0.0), (0.0, 0.0, 2.5), height)
