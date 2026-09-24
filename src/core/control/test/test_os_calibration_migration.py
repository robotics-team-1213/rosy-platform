from pathlib import Path

import pytest
import yaml

from tools.migrate_calibration import migrate


def test_legacy_merge_preserves_sources_and_unmeasured_fields(tmp_path):
    sources = [tmp_path / 'cliff.yaml', tmp_path / 'drive.yaml']
    originals = [b'safety_node:\n  ros__parameters:\n    cliff_raw_max: 700\n',
                 b'safety_node:\n  ros__parameters:\n    cmd_linear_sign: -1.0\n    robot_radius: 0.08\n']
    for source, data in zip(sources, originals):
        source.write_bytes(data)
    destination = tmp_path / 'new' / 'calibration.yaml'
    migrate(sources, destination)
    values = yaml.safe_load(destination.read_text())['/**/safety_node']['ros__parameters']
    assert values == {'cliff_raw_max': 700, 'cmd_linear_sign': -1., 'robot_radius': .08}
    assert [source.read_bytes() for source in sources] == originals


def test_conflict_or_existing_destination_never_overwrites(tmp_path):
    first, second, output = [tmp_path / name for name in ('a.yaml', 'b.yaml', 'out.yaml')]
    first.write_text('safety_node: {ros__parameters: {cmd_linear_sign: 1.0}}')
    second.write_text('safety_node: {ros__parameters: {cmd_linear_sign: -1.0}}')
    with pytest.raises(ValueError, match='Conflicting'):
        migrate([first, second], output)
    assert not output.exists()
    output.write_bytes(b'original')
    with pytest.raises(ValueError, match='already exists'):
        migrate([first], output)
    assert output.read_bytes() == b'original'
