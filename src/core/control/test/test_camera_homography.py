import copy
import json

import pytest

from control.sensing.camera_homography import (
    CalibrationThresholds,
    HomographyGroundPlane,
    evaluate_homography_profile,
    load_homography_profile,
)


MATRIX = [[0.1, 0.0, -32.0], [0.01, -0.1, 48.0], [0.0, 0.0, 1.0]]
POINTS = [(200, 180), (320, 180), (440, 180), (200, 240),
          (320, 240), (440, 240), (200, 300), (440, 300)]


def project(point, matrix=MATRIX):
    u, v = point
    denominator = matrix[2][0] * u + matrix[2][1] * v + matrix[2][2]
    return [
        (matrix[0][0] * u + matrix[0][1] * v + matrix[0][2]) / denominator,
        (matrix[1][0] * u + matrix[1][1] * v + matrix[1][2]) / denominator,
    ]


def frame(name, points=POINTS):
    return {
        'image': name,
        'pixel_points': [list(point) for point in points],
        'ground_points_cm': [project(point) for point in points],
    }


def validated_profile():
    return {
        'version': 3,
        'status': 'validated',
        'method': 'charuco_ground_homography',
        'image_size': [640, 480],
        'processed_rotate_deg': 180,
        'camera_profile_revision': 'camera-profile-v1',
        'intrinsic_calibration': {
            'revision': 'ov5647-intrinsic-v1',
            'image_size': [640, 480],
            'distortion_model': 'opencv_plumb_bob',
            'points_undistorted': True,
        },
        'image_to_ground_homography': MATRIX,
        'coordinates': {
            'x': 'board-relative lateral right; NOT robot lateral',
            'y': 'forward floor distance from camera ground projection, cm',
        },
        'reference_frames': [frame('fit-a.jpg')],
        'validation_frames': [frame('holdout-a.jpg'), frame('holdout-b.jpg')],
        'physical_validation': {
            'square_size_measured': True,
            'board_flat': True,
            'camera_mount_locked': True,
            'robot_forward_axis_checked': True,
        },
    }


def evaluate(profile, **overrides):
    args = dict(
        runtime_image_size=(640, 480),
        runtime_rotate_deg=180,
        runtime_profile_revision='camera-profile-v1',
        thresholds=CalibrationThresholds(min_validation_points=8),
        allow_uniform_resize=False,
        source='test-profile.json',
    )
    args.update(overrides)
    return evaluate_homography_profile(profile, **args)


def test_approximate_profile_stays_a_candidate_even_with_small_residuals():
    profile = validated_profile()
    profile['status'] = 'approximate_requires_physical_validation'

    result = evaluate(profile)

    assert result.candidate is True
    assert result.eligible is False
    assert result.checks['validated_status']['passed'] is False
    assert result.status(enabled_requested=True)['active'] is False
    assert result.status(enabled_requested=True)['reason'] == 'validation_failed'


def test_reference_error_is_recomputed_instead_of_trusting_reported_rmse():
    profile = validated_profile()
    profile['fit_rmse_cm'] = 0.001
    profile['image_to_ground_homography'] = copy.deepcopy(MATRIX)
    profile['image_to_ground_homography'][1][2] += 20.0

    result = evaluate(profile)

    assert result.checks['reference_fit']['passed'] is False
    assert result.metrics['fit_rmse_cm'] > 10.0
    assert result.eligible is False


def test_validated_independent_profile_can_be_enabled_and_reports_range():
    result = evaluate(validated_profile())

    assert result.eligible is True
    assert result.status(enabled_requested=False)['active'] is False
    status = result.status(enabled_requested=True)
    assert status['active'] is True
    assert status['lateral_available'] is False
    assert status['validated_range_m'] == pytest.approx([0.2, 0.344])
    assert result.model.distance(240, 320) == pytest.approx(0.272)


def test_validation_images_must_be_independent_of_fit_images():
    profile = validated_profile()
    profile['validation_frames'][0]['image'] = 'fit-a.jpg'

    result = evaluate(profile)

    assert result.checks['independent_validation']['passed'] is False
    assert result.eligible is False


def test_validation_requires_multiple_frames_and_distance_span():
    one_frame = validated_profile()
    one_frame['validation_frames'] = one_frame['validation_frames'][:1]
    narrow = validated_profile()
    narrow_points = [(200, 240), (320, 240), (440, 240), (250, 240),
                     (390, 240), (210, 240), (430, 240), (300, 240)]
    narrow['validation_frames'] = [frame('narrow-a.jpg', narrow_points),
                                   frame('narrow-b.jpg', narrow_points)]

    assert evaluate(one_frame).checks['independent_validation']['passed'] is False
    assert evaluate(narrow).checks['independent_validation']['passed'] is False


def test_intrinsic_calibration_and_undistorted_points_are_required():
    missing = validated_profile()
    missing.pop('intrinsic_calibration')
    distorted = validated_profile()
    distorted['intrinsic_calibration']['points_undistorted'] = False

    assert evaluate(missing).checks['intrinsic_calibration']['passed'] is False
    assert evaluate(distorted).checks['intrinsic_calibration']['passed'] is False
    assert evaluate(missing).eligible is False
    assert evaluate(distorted).eligible is False


def test_resolution_rotation_and_revision_mismatches_fail_closed():
    profile = validated_profile()
    wrong_size = evaluate(profile, runtime_image_size=(320, 240))
    wrong_rotation = evaluate(profile, runtime_rotate_deg=0)
    wrong_revision = evaluate(profile, runtime_profile_revision='camera-profile-v2')

    assert wrong_size.checks['image_contract']['passed'] is False
    assert wrong_rotation.checks['image_contract']['passed'] is False
    assert wrong_revision.checks['image_contract']['passed'] is False
    assert not wrong_size.eligible and not wrong_rotation.eligible and not wrong_revision.eligible


def test_uniform_resize_is_explicit_and_maps_runtime_pixels_back_to_profile():
    result = evaluate(
        validated_profile(), runtime_image_size=(320, 240), allow_uniform_resize=True)

    assert result.eligible is True
    assert result.checks['image_contract']['detail'] == 'uniform_resize_0.500000'
    assert result.model.distance(120, 160) == pytest.approx(0.272)


def test_region_range_uses_bottom_centre_not_only_the_row():
    model = HomographyGroundPlane(
        MATRIX, runtime_image_size=(640, 480), profile_image_size=(640, 480),
        min_range_m=0.1, max_range_m=0.5, lateral_robot_frame=False)

    assert model.region_distance([100, 50, 300, 240]) == pytest.approx(0.26)
    assert model.region_distance([300, 50, 500, 240]) == pytest.approx(0.28)


def test_board_relative_x_is_never_reported_as_robot_lateral():
    result = evaluate(validated_profile())

    assert result.model.lateral(320, 240) is None


def test_near_zero_denominator_and_out_of_range_are_unknown():
    model = HomographyGroundPlane(
        [[0.1, 0.0, 0.0], [0.0, -0.1, 48.0], [0.0, -1.0 / 240.0, 1.0]],
        runtime_image_size=(640, 480), profile_image_size=(640, 480),
        min_range_m=0.1, max_range_m=0.5, lateral_robot_frame=True)

    assert model.distance(240, 320) is None
    assert model.distance(0, 320) == pytest.approx(0.48)
    assert model.distance(479, 320) is None


def test_loader_hashes_source_and_missing_file_is_an_inactive_status(tmp_path):
    path = tmp_path / 'camera.json'
    path.write_text(json.dumps(validated_profile()), encoding='utf-8')
    loaded = load_homography_profile(
        path, runtime_image_size=(640, 480), runtime_rotate_deg=180,
        runtime_profile_revision='camera-profile-v1',
        thresholds=CalibrationThresholds(min_validation_points=8),
        allow_uniform_resize=False)
    missing = load_homography_profile(
        tmp_path / 'missing.json', runtime_image_size=(640, 480),
        runtime_rotate_deg=180, runtime_profile_revision='camera-profile-v1',
        thresholds=CalibrationThresholds(min_validation_points=8),
        allow_uniform_resize=False)

    assert len(loaded.source_sha256) == 64
    assert loaded.eligible is True
    assert missing.candidate is False
    assert missing.checks['profile_loaded']['passed'] is False
    assert missing.status(enabled_requested=True)['active'] is False


def test_out_of_bounds_threshold_is_inactive_and_status_is_strict_json():
    result = evaluate(
        validated_profile(),
        thresholds=CalibrationThresholds(max_fit_rmse_cm=float('nan')))

    assert result.eligible is False
    assert result.checks['thresholds']['passed'] is False
    assert 'NaN' not in json.dumps(result.status(enabled_requested=True), allow_nan=False)
