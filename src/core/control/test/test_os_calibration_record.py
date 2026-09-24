import pytest
import yaml

from control.calibration_storage import merge_calibration
from control.calibration_record import decode_record
from control.calibration_storage import single_calibration_path
from tools.migrate_calibration import migrate


CONTEXT = dict(robot_id='rosy_01', hardware_model='Pinky Pro', geometry_revision='geometry-1',
               sensor_revision='sensors-1', data_generation='release-1')
UPDATE = 'safety_node: {ros__parameters: {imu_roll0: 1.0}}'


def test_record_survives_restart_and_preserves_previous_revision(tmp_path):
    path = tmp_path / 'calibration.yaml'
    merge_calibration(str(path), UPDATE, context=CONTEXT, actor='maintainer')
    first, values = decode_record(path.read_text(), CONTEXT)
    assert first['revision'] == 1
    assert values == yaml.safe_load(path.read_text())
    merge_calibration(str(path), 'safety_node: {ros__parameters: {imu_pitch0: 2.0}}',
                      context=CONTEXT, actor='maintainer')
    second, values = decode_record(path.read_text(), dict(CONTEXT))
    assert second['revision'] == 2
    assert second['previous_digest'] == first['digest']
    assert values['/**/safety_node']['ros__parameters'] == {'imu_roll0': 1., 'imu_pitch0': 2.}


@pytest.mark.parametrize('field', list(CONTEXT))
def test_context_mismatch_preserves_file(tmp_path, field):
    path = tmp_path / 'calibration.yaml'
    merge_calibration(str(path), UPDATE, context=CONTEXT, actor='maintainer')
    original = path.read_bytes()
    wrong = dict(CONTEXT, **{field: 'different'})
    with pytest.raises(ValueError):
        merge_calibration(str(path), UPDATE, context=wrong, actor='maintainer')
    assert path.read_bytes() == original


def test_corruption_and_unbound_writer_cannot_replace_record(tmp_path):
    path = tmp_path / 'calibration.yaml'
    merge_calibration(str(path), UPDATE, context=CONTEXT, actor='maintainer')
    with pytest.raises(ValueError):
        merge_calibration(str(path), UPDATE)
    corrupted = path.read_text().replace('imu_roll0: 1.0', 'imu_roll0: 9.0')
    path.write_text(corrupted)
    with pytest.raises(ValueError):
        merge_calibration(str(path), UPDATE, context=CONTEXT, actor='maintainer')
    assert path.read_text() == corrupted


def test_legacy_file_is_not_silently_bound_to_identity(tmp_path):
    path = tmp_path / 'calibration.yaml'
    path.write_text(UPDATE)
    with pytest.raises(ValueError):
        merge_calibration(str(path), UPDATE, context=CONTEXT, actor='maintainer')
    assert path.read_text() == UPDATE


def test_preflight_rejects_identity_mismatch_and_export_cannot_strip_binding(tmp_path):
    path = tmp_path / 'calibration.yaml'
    merge_calibration(str(path), UPDATE, context=CONTEXT, actor='maintainer')
    with pytest.raises(ValueError, match='mismatch'):
        single_calibration_path(str(path), str(path), dict(CONTEXT, robot_id='rosy_02'))
    output = tmp_path / 'export.yaml'
    with pytest.raises(ValueError, match='identity-aware'):
        migrate([path], output)
    assert not output.exists()
