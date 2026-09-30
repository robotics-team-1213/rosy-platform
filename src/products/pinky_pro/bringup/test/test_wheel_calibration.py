"""Bringup wheel geometry: accepted calibration record, else the parameters (D-47 addendum)."""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[4] / 'contracts' / 'foundation'))

from bringup.wheel_calibration import calibrated_wheels  # noqa: E402
from core_common.calibration_store import CalibrationStore  # noqa: E402

ROBOT = 'rosy-test'


def test_parameters_stand_without_an_accepted_record(tmp_path):
    CalibrationStore(tmp_path).add(ROBOT, 'wheel_odometry',
                                   {'wheel_radius': 0.0271, 'wheel_separation': 0.0968}, method='t/1')
    values, source = calibrated_wheels(0.027, 0.0961, root=tmp_path, robot=ROBOT)
    assert values == {'wheel_radius': 0.027, 'wheel_separation': 0.0961}
    assert source.startswith('bringup parameters')


import pytest  # noqa: E402


@pytest.mark.parametrize('values', [
    {'wheel_radius': 0.031, 'wheel_separation': 0.0968},     # radius +15 %
    {'wheel_radius': 0.0271, 'wheel_separation': 0.080},     # separation -17 %
    {'wheel_radius': True, 'wheel_separation': 0.0968},
    {'wheel_radius': '0.027', 'wheel_separation': 0.0968},
    {'wheel_separation': 0.0968},
])
def test_implausible_accepted_record_falls_back_with_a_reason(tmp_path, values):
    store = CalibrationStore(tmp_path)
    rid = store.add(ROBOT, 'wheel_odometry', values, method='t/1')
    store.set_status(ROBOT, 'wheel_odometry', rid, 'accepted', actor='operator')
    got, source = calibrated_wheels(0.027, 0.0961, root=tmp_path, robot=ROBOT)
    assert got == {'wheel_radius': 0.027, 'wheel_separation': 0.0961}
    assert 'rejected' in source and rid in source


def test_latest_accepted_record_wins(tmp_path):
    store = CalibrationStore(tmp_path)
    old = store.add(ROBOT, 'wheel_odometry', {'wheel_radius': 0.0270, 'wheel_separation': 0.0965},
                    method='t/1', created_at='2026-10-01T10:00:00.000000Z')
    new = store.add(ROBOT, 'wheel_odometry', {'wheel_radius': 0.0271, 'wheel_separation': 0.0968},
                    method='t/1', created_at='2026-10-01T11:00:00.000000Z')
    for rid in (old, new):
        store.set_status(ROBOT, 'wheel_odometry', rid, 'accepted', actor='operator')
    values, source = calibrated_wheels(0.027, 0.0961, root=tmp_path, robot=ROBOT)
    assert values == {'wheel_radius': 0.0271, 'wheel_separation': 0.0968} and new in source
