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
    """D-396 order: URDF nominal file < accepted camera_profile record < operator override."""
    store = CalibrationStore(tmp_path)
    rid = store.add(ROBOT, 'camera_profile', {**FILE, 'pitch_rad': 0.20}, method='t/1')
    store.set_status(ROBOT, 'camera_profile', rid, 'accepted', actor='operator')
    values, source = calibrated('camera_profile', FILE, static_source='camera_nominal.yaml',
                                root=tmp_path, robot=ROBOT, override={'pitch_rad': 0.15})
    assert values['pitch_rad'] == 0.15 and values['fx'] == 281.6
    assert rid in source and 'operator override pitch_rad' in source
