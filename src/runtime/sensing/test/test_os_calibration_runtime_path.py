from pathlib import Path
import os

import pytest

from control.calibration_record import runtime_calibration_path


CONTEXT = dict(robot_id='rosy_01', hardware_model='Pinky Pro', geometry_revision='g1',
               sensor_revision='s1', data_generation='release-1')


def test_runtime_path_requires_matching_active_generation(tmp_path):
    target = tmp_path / 'calibration' / 'rosy_01' / 'calibration.yaml'
    assert runtime_calibration_path(str(target), CONTEXT, 'release-1', tmp_path) == str(target.resolve())
    for generation in ('', 'release-2'):
        with pytest.raises(ValueError):
            runtime_calibration_path(str(target), CONTEXT, generation, tmp_path)


def test_runtime_path_rejects_other_robot_or_generation_tree(tmp_path):
    for target in (tmp_path / 'other.yaml', tmp_path / 'calibration' / 'rosy_02' / 'calibration.yaml',
                   tmp_path.parent / 'previous' / 'calibration.yaml'):
        with pytest.raises(ValueError):
            runtime_calibration_path(str(target), CONTEXT, 'release-1', tmp_path)


def test_robot_identity_cannot_be_a_path(tmp_path):
    context = dict(CONTEXT, robot_id='../rosy_02')
    with pytest.raises(ValueError):
        runtime_calibration_path(str(tmp_path / 'calibration.yaml'), context, 'release-1', tmp_path)


def test_link_cannot_redirect_robot_data_to_another_tree(tmp_path):
    (tmp_path / 'calibration').mkdir()
    outside = tmp_path / 'other-generation'
    outside.mkdir()
    try:
        (tmp_path / 'calibration' / 'rosy_01').symlink_to(outside, target_is_directory=True)
    except OSError:
        if os.name == 'nt':
            pytest.skip('Windows symlink privilege unavailable; also run this test on Linux')
        raise
    with pytest.raises(ValueError, match='link'):
        runtime_calibration_path(str(tmp_path / 'calibration' / 'rosy_01' / 'calibration.yaml'),
                                 CONTEXT, 'release-1', tmp_path)
