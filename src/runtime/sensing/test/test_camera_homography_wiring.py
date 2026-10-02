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
    page = source('web/diagnostic.html')

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


def test_camera_node_offers_nominal_ground_and_lidar_region_range_off_by_default():
    """D-423: opt-in NOMINAL plane + LiDAR region range; the device default stays unranged."""
    node = source('control/camera_detect_node.py')
    config = source('config/camera.yaml')
    for token in ('nominal_camera_profile_path', 'allow_nominal_ground', 'region_lidar_range',
                  'region_lidar_max_age_s', 'region_lidar_tolerance_m', 'region_lidar_tolerance_ratio',
                  'accept_simulation_scans'):
        assert f"'{token}'" in node
        assert f'{token}:' in config
    assert "camera_ground_mode: pinhole" in config
    assert 'allow_nominal_ground: false' in config
    assert 'region_lidar_range: false' in config
    assert "nominal_camera_profile_path: ''" in config
    assert 'accept_simulation_scans: false' in config
    # Overrides rely on the node's declared NaN default: no '.nan' in a ROS params file,
    # since rcl_yaml_param_parser support is unverified on the device. Named in a comment.
    assert '.nan' not in config
    for token in ('camera_pitch_rad_override', 'camera_height_m_override', 'lidar_yaw_offset_override'):
        assert f"'{token}'" in node and token in config and f'{token}:' not in config
    assert '/opt/rosy/current/install/share/pinky_pro/config/camera_nominal.yaml' in config
    # The same store path as line_observer: URDF nominal < accepted record.
    assert 'nominal_camera_profile(' in node and 'lidar_nose_rad(' in node
    assert "LaserScan, 'scan'" in node and 'qos_profile_sensor_data' in node
    assert 'is_robot_scan(' in node and 'range_regions(' in node
    assert 'ground_source=' in node
