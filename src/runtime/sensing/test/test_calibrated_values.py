"""Sensing nodes read the accepted calibration record, else the static file (D-47 addendum)."""
from core_common.calibration_store import CalibrationStore

from control.calibrated_values import calibrated

ROBOT = 'rosy-test'
FILE = {'width': 320, 'height': 240, 'fx': 281.6, 'cx': 160.0, 'cy': 120.0, 'pitch_rad': 0.1396,
        'height_m': 0.067, 'x_offset_m': 0.034, 'max_range_m': 0.6}


def test_static_profile_without_an_accepted_record(tmp_path):
    store = CalibrationStore(tmp_path)
    store.add(ROBOT, 'camera_profile', {**FILE, 'pitch_rad': 0.20}, method='t/1')  # candidate only
    values, source = calibrated('camera_profile', FILE, static_source='camera_nominal.yaml',
                                root=tmp_path, robot=ROBOT)
    assert values == FILE and source.startswith('camera_nominal.yaml')


def test_accepted_record_overrides_the_file_and_is_named(tmp_path):
    store = CalibrationStore(tmp_path)
    rid = store.add(ROBOT, 'camera_profile', {**FILE, 'pitch_rad': 0.20, 'roll_rad': -0.01}, method='t/1')
    store.set_status(ROBOT, 'camera_profile', rid, 'accepted', actor='operator')
    values, source = calibrated('camera_profile', FILE, static_source='camera_nominal.yaml',
                                root=tmp_path, robot=ROBOT)
    assert values['pitch_rad'] == 0.20 and values['fx'] == 281.6
    assert rid in source


def test_operator_override_wins_over_the_accepted_record(tmp_path):
    """D-397 order: URDF nominal file < accepted camera_profile record < operator override."""
    store = CalibrationStore(tmp_path)
    rid = store.add(ROBOT, 'camera_profile', {**FILE, 'pitch_rad': 0.20}, method='t/1')
    store.set_status(ROBOT, 'camera_profile', rid, 'accepted', actor='operator')
    values, source = calibrated('camera_profile', FILE, static_source='camera_nominal.yaml',
                                root=tmp_path, robot=ROBOT, override={'pitch_rad': 0.15})
    assert values['pitch_rad'] == 0.15 and values['fx'] == 281.6
    assert rid in source and 'operator override pitch_rad' in source


def test_nominal_camera_profile_reads_the_file_then_the_accepted_record(tmp_path):
    """D-423: camera_detect_node's NOMINAL plane takes the same path as line_observer."""
    import math
    import yaml
    from control.calibrated_values import nominal_camera_profile
    path = tmp_path / 'camera_nominal.yaml'
    path.write_text(yaml.safe_dump(FILE), encoding='utf-8')
    store_root = tmp_path / 'store'
    values, source = nominal_camera_profile(str(path), root=store_root, robot=ROBOT)
    assert values == FILE and str(path) in source
    store = CalibrationStore(store_root)
    rid = store.add(ROBOT, 'camera_profile', {**FILE, 'pitch_rad': math.radians(11.2)}, method='t/1')
    store.set_status(ROBOT, 'camera_profile', rid, 'accepted', actor='operator')
    values, source = nominal_camera_profile(str(path), root=store_root, robot=ROBOT)
    assert values['pitch_rad'] == math.radians(11.2) and rid in source


def test_unreadable_nominal_profile_gives_no_profile_and_says_why(tmp_path):
    from control.calibrated_values import nominal_camera_profile
    values, source = nominal_camera_profile(str(tmp_path / 'missing.yaml'), root=tmp_path, robot=ROBOT)
    assert values == {} and 'unreadable' in source
    values, source = nominal_camera_profile('', root=tmp_path, robot=ROBOT)
    assert values == {} and 'no profile file' in source


def test_lidar_nose_is_the_urdf_nominal_until_a_mount_record_is_accepted(tmp_path):
    import math
    from control.calibrated_values import lidar_nose_rad
    from control.sensing.lidar import NOSE_YAW
    nose, source = lidar_nose_rad(root=tmp_path, robot=ROBOT)
    assert nose == NOSE_YAW and 'no accepted lidar_mount record' in source
    store = CalibrationStore(tmp_path)
    rid = store.add(ROBOT, 'lidar_mount', {'lidar_yaw_offset': math.radians(181.8)}, method='t/1')
    store.set_status(ROBOT, 'lidar_mount', rid, 'accepted', actor='operator')
    nose, source = lidar_nose_rad(root=tmp_path, robot=ROBOT)
    assert nose == math.radians(181.8) and rid in source


def test_operator_override_beats_the_accepted_profile_and_mount_records(tmp_path):
    """D-397 order for the D-423 readers too: an operator override wins over an accepted record."""
    import math
    import yaml
    from control.calibrated_values import lidar_nose_rad, nominal_camera_profile
    path = tmp_path / 'camera_nominal.yaml'
    path.write_text(yaml.safe_dump(FILE), encoding='utf-8')
    store = CalibrationStore(tmp_path / 'store')
    rid = store.add(ROBOT, 'camera_profile', {**FILE, 'pitch_rad': 0.20}, method='t/1')
    store.set_status(ROBOT, 'camera_profile', rid, 'accepted', actor='operator')
    values, source = nominal_camera_profile(str(path), root=tmp_path / 'store', robot=ROBOT,
                                            override={'pitch_rad': 0.15})
    assert values['pitch_rad'] == 0.15 and 'operator override pitch_rad' in source
    rid = store.add(ROBOT, 'lidar_mount', {'lidar_yaw_offset': math.radians(181.8)}, method='t/1')
    store.set_status(ROBOT, 'lidar_mount', rid, 'accepted', actor='operator')
    nose, source = lidar_nose_rad(root=tmp_path / 'store', robot=ROBOT,
                                  override={'lidar_yaw_offset': math.radians(182.5)})
    assert nose == math.radians(182.5) and 'operator override lidar_yaw_offset' in source


def test_non_mapping_profile_gives_no_profile_and_says_why(tmp_path):
    from control.calibrated_values import nominal_camera_profile
    path = tmp_path / 'camera_nominal.yaml'
    path.write_text('- 1\n- 2\n', encoding='utf-8')
    values, source = nominal_camera_profile(str(path), root=tmp_path, robot=ROBOT)
    assert values == {} and 'not a mapping' in source
