from pathlib import Path


ROOT = Path(__file__).parents[1]


def source(relative):
    return ROOT.joinpath(relative).read_text(encoding='utf-8')


def test_camera_node_has_tunable_fail_closed_homography_contract():
    node = source('control/camera_detect_node.py')
    config = source('config/camera.yaml')

    for token in (
        'camera_ground_mode', 'camera_homography_path',
        'camera_homography_enabled', 'camera_homography_allow_uniform_resize',
        'camera_homography_max_fit_rmse_cm',
        'camera_homography_max_validation_rmse_cm',
        'camera_homography_max_validation_error_cm',
        'camera_homography_min_validation_points',
        'camera_homography_min_validation_frames',
        'camera_homography_min_validation_span_cm',
        'camera_homography_max_range_m',
    ):
        assert token in node
        assert token in config
    assert "'camera/calibration/status'" in node
    assert "'camera/calibration/cmd'" in node
    assert 'TRANSIENT_LOCAL' in node
    assert "camera_ground_mode: pinhole" in config
    assert 'camera_homography_enabled: false' in config


def test_web_only_relays_bounded_enable_disable_and_renders_node_checks():
    node = source('control/web_node.py')
    http = source('control/web_http.py')
    page = source('web/dashboard.html')

    assert "'camera/calibration/status'" in node
    assert "'camera/calibration/cmd'" in node
    assert "self.path == '/camera/calibration'" in http
    assert "body not in ('enable', 'disable')" in http
    assert 'camera_ground_toggle' in page
    assert "post('/camera/calibration'" in page
    for check in ('profile_loaded', 'image_contract', 'intrinsic_calibration', 'reference_fit',
                  'independent_validation', 'physical_validation'):
        assert 'camera_ground_check_' + check in page
    assert 'cameraGroundCalibration' in page
