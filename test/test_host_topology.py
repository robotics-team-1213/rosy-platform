"""Only explicitly selected arms determine service checks, never USB enumeration."""
import importlib.util
from pathlib import Path


def collector():
    source = Path(__file__).resolve().parents[1] / 'tools/remote/host_topology.py'
    spec = importlib.util.spec_from_file_location('host_topology', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def selection(tmp_path, arms):
    config = tmp_path / '.config/rosy'
    config.mkdir(parents=True)
    manifest = tmp_path / 'cells.yaml'
    manifest.write_text('workcells:\n- workcell_id: selected\n  arms:\n' + ''.join(f'  - arm_id: {arm}\n' for arm in arms))
    (config / 'omx-observation-bridge.env').write_text(
        f'ROSY_WORKCELL_OBSERVATIONS="{manifest}"\nROSY_OBSERVATION_WORKCELL=selected\nPRIVATE_TOKEN=never-report-this\n')
    return config


def test_only_selected_arms_are_collected_even_when_other_arm_configs_exist(tmp_path):
    config = selection(tmp_path, ['_first', 'second', 'third'])
    for arm in ['_first', 'second', 'third', 'not_selected']:
        (config / f'omx-observer-{arm}.env').write_text(f'ROSY_OBSERVER_DEVICE=/dev/serial/by-id/{arm}\n')
    found = collector().collect(tmp_path)
    assert set(found['arms']) == {'_first', 'second', 'third'}
    assert all(item == {'configured': True, 'connected': False} for item in found['arms'].values())
    assert 'never-report-this' not in str(found)


def test_missing_selection_and_duplicate_arm_ids_are_configuration_errors(tmp_path):
    module = collector()
    assert 'error' in module.collect(tmp_path)
    selection(tmp_path, ['same', 'same'])
    assert 'error' in module.collect(tmp_path)


def test_env_selection_is_data_and_never_a_shell_command(tmp_path):
    config = selection(tmp_path, ['selected_arm'])
    marker = tmp_path / 'must-not-exist'
    (config / 'omx-observation-bridge.env').write_text(
        f'ROSY_WORKCELL_OBSERVATIONS="$(touch {marker})"\nROSY_OBSERVATION_WORKCELL=selected\n')
    assert 'error' in collector().collect(tmp_path)
    assert not marker.exists()
