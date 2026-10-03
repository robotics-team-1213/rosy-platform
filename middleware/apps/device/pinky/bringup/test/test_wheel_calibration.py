"""Bringup wheel geometry: URDF nominal < accepted calibration record < operator override (D-47 addendum, D-397)."""

import sys
from pathlib import Path

sys.path.append(str((Path(__file__).resolve().parents[6] / "contracts") / 'foundation'))

from bringup.wheel_calibration import calibrated_wheels  # noqa: E402
from core_common.calibration_store import CalibrationStore  # noqa: E402

ROBOT = 'rosy-test'


def test_parameters_stand_without_an_accepted_record(tmp_path):
    CalibrationStore(tmp_path).add(ROBOT, 'wheel_odometry',
                                   {'wheel_radius': 0.0271, 'wheel_separation': 0.0968}, method='t/1')
    values, source = calibrated_wheels(0.028, 0.0971, root=tmp_path, robot=ROBOT)
    assert values == {'wheel_radius': 0.028, 'wheel_separation': 0.0971}
    assert source.startswith('bringup parameters')


import pytest  # noqa: E402


@pytest.mark.parametrize('values', [
    {'wheel_radius': 0.031, 'wheel_separation': 0.0968},     # radius +11 % of the URDF 0.028
    {'wheel_radius': 0.0271, 'wheel_separation': 0.080},     # separation -18 % of 0.0971
    {'wheel_radius': True, 'wheel_separation': 0.0968},
    {'wheel_radius': '0.027', 'wheel_separation': 0.0968},
    {'wheel_separation': 0.0968},
])
def test_implausible_accepted_record_falls_back_with_a_reason(tmp_path, values):
    store = CalibrationStore(tmp_path)
    rid = store.add(ROBOT, 'wheel_odometry', values, method='t/1')
    store.set_status(ROBOT, 'wheel_odometry', rid, 'accepted', actor='operator')
    got, source = calibrated_wheels(0.028, 0.0971, root=tmp_path, robot=ROBOT)
    assert got == {'wheel_radius': 0.028, 'wheel_separation': 0.0971}
    assert 'rejected' in source and rid in source


def test_latest_accepted_record_wins(tmp_path):
    store = CalibrationStore(tmp_path)
    old = store.add(ROBOT, 'wheel_odometry', {'wheel_radius': 0.0270, 'wheel_separation': 0.0965},
                    method='t/1', created_at='2026-10-01T10:00:00.000000Z')
    new = store.add(ROBOT, 'wheel_odometry', {'wheel_radius': 0.0271, 'wheel_separation': 0.0968},
                    method='t/1', created_at='2026-10-01T11:00:00.000000Z')
    for rid in (old, new):
        store.set_status(ROBOT, 'wheel_odometry', rid, 'accepted', actor='operator')
    values, source = calibrated_wheels(0.028, 0.0971, root=tmp_path, robot=ROBOT)
    assert values == {'wheel_radius': 0.0271, 'wheel_separation': 0.0968} and new in source

def _accept(tmp_path, values):
    store = CalibrationStore(tmp_path)
    rid = store.add(ROBOT, 'wheel_odometry', values, method='t/1')
    store.set_status(ROBOT, 'wheel_odometry', rid, 'accepted', actor='operator')
    return rid


def test_order_urdf_nominal_then_record_then_operator_override(tmp_path):
    """D-397: the 8kcn fit (0.0272 / 0.0975) refines the URDF 0.028 / 0.0971; a launch override wins."""
    nominal = {'wheel_radius': 0.028, 'wheel_separation': 0.0971}
    assert calibrated_wheels(*nominal.values(), root=tmp_path, robot=ROBOT)[0] == nominal
    rid = _accept(tmp_path, {'wheel_radius': 0.0272, 'wheel_separation': 0.0975})
    values, source = calibrated_wheels(*nominal.values(), root=tmp_path, robot=ROBOT)
    assert values == {'wheel_radius': 0.0272, 'wheel_separation': 0.0975} and rid in source
    values, source = calibrated_wheels(*nominal.values(), root=tmp_path, robot=ROBOT,
                                       override={'wheel_radius': 0.0269, 'wheel_separation': 0.0})
    assert values == {'wheel_radius': 0.0269, 'wheel_separation': 0.0975}
    assert rid in source and 'operator override wheel_radius' in source


def test_zero_or_missing_override_is_not_an_override(tmp_path):
    _accept(tmp_path, {'wheel_radius': 0.0266, 'wheel_separation': 0.0953})   # 9dfk fit
    for override in (None, {}, {'wheel_radius': 0.0, 'wheel_separation': 0.0}):
        values, source = calibrated_wheels(0.028, 0.0971, root=tmp_path, robot=ROBOT, override=override)
        assert values == {'wheel_radius': 0.0266, 'wheel_separation': 0.0953}
        assert 'operator override' not in source


@pytest.mark.parametrize('bad', [float('nan'), -0.03, True, 'x'])
def test_unusable_override_is_dropped_and_logged(tmp_path, bad):
    logged = []
    values, source = calibrated_wheels(0.028, 0.0971, root=tmp_path, robot=ROBOT,
                                       override={'wheel_radius': bad}, log=logged.append)
    assert values == {'wheel_radius': 0.028, 'wheel_separation': 0.0971}
    assert 'operator override' not in source and len(logged) == 1 and 'dropped' in logged[0]


def test_implausible_override_is_refused(tmp_path):
    values, source = calibrated_wheels(0.028, 0.0971, root=tmp_path, robot=ROBOT,
                                       override={'wheel_radius': 0.040})   # +43 %
    assert values['wheel_radius'] == 0.028 and 'refused' in source
