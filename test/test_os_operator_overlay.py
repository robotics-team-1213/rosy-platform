"""Privileged operator overlay publication uses the existing canonical transaction."""
import io
import subprocess
import sys
from pathlib import Path

import pytest

from test_os_first_boot_state import SERIAL, _provision_a


def test_nominal_profile_is_captured_with_overlay_and_survives_missing_source(tmp_path, monkeypatch):
    import os_state_config as m
    import yaml

    first, root_a, root_b, _, bundle = _provision_a(tmp_path, monkeypatch, protocol=2)
    repository = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(repository / 'middleware/perception'))
    from control.sensing.perception.camera_ground import nominal_ground_plane

    original = (repository / 'middleware/devices/pinky/profile/config/camera_nominal.yaml').read_bytes()
    profile = tmp_path / 'root-a-only-camera.yaml'
    profile.write_bytes(original)
    overlay = tmp_path / 'line.yaml'
    overlay.write_text(yaml.safe_dump({'/**/line_observer_node': {'ros__parameters': {
        'camera_lane_mode': 'keep', 'camera_ground_source': 'NOMINAL', 'allow_nominal_ground': True,
        'nominal_camera_profile_path': str(profile)}}}))
    with monkeypatch.context() as command:
        command.setattr(m.os, 'geteuid', lambda: 0)
        assert m.main(['--file', 'line_observer_overrides.yaml', '--input', str(overlay),
                       '--profile-input', str(profile)], root=root_a) == 0
    profile.unlink()
    for root in (root_b, root_a):
        first.FirstBootProvisioner(root=root).apply(bundle=bundle, hardware_serial=SERIAL)
        params = yaml.safe_load((root / 'etc/rosy/line_observer_overrides.yaml').read_bytes())[
            '/**/line_observer_node']['ros__parameters']
        assert params['nominal_camera_profile_path'] == '/etc/rosy/camera_nominal.yaml'
        captured = root / params['nominal_camera_profile_path'].lstrip('/')
        assert captured.read_bytes() == original
        assert nominal_ground_plane(source='NOMINAL', allowed=True, width_px=320, height_px=240,
                                    profile=yaml.safe_load(captured.read_bytes())) is not None
    with monkeypatch.context() as command:
        command.setattr(m.os, 'geteuid', lambda: 0)
        assert m.main(['--file', 'line_observer_overrides.yaml', '--clear'], root=root_b) == 0
    first.FirstBootProvisioner(root=root_a).apply(bundle=bundle, hardware_serial=SERIAL)
    assert not (root_a / 'etc/rosy/camera_nominal.yaml').exists()


def test_operator_overlay_entrypoint_imports_in_isolation():
    import os_state_config

    result = subprocess.run([sys.executable, '-I', '-B', os_state_config.__file__, '--help'],
                            capture_output=True, text=True, check=False, timeout=10)
    assert result.returncode == 0, result.stderr
    assert '--file' in result.stdout and '--clear' in result.stdout


@pytest.mark.parametrize('filename', ['ir_calibration.yaml', 'line_observer_overrides.yaml'])
def test_operator_cli_publishes_and_clears_across_roots(tmp_path, monkeypatch, filename):
    import os_state_config as m

    first, root_a, root_b, _, bundle = _provision_a(tmp_path, monkeypatch, protocol=2)
    with monkeypatch.context() as command:
        command.setattr(m.os, 'geteuid', lambda: 0)
        command.setattr(m.sys, 'stdin', io.TextIOWrapper(io.BytesIO(b'operator: calibration\n')))
        assert m.main(['--file', filename, '--input', '-'], root=root_a) == 0
    first.FirstBootProvisioner(root=root_b).apply(bundle=bundle, hardware_serial=SERIAL)
    target = root_b / 'etc/rosy' / filename
    assert target.read_bytes() == b'operator: calibration\n'
    assert target.stat().st_mode & 0o7777 == 0o644
    with monkeypatch.context() as command:
        command.setattr(m.os, 'geteuid', lambda: 0)
        assert m.main(['--file', filename, '--clear'], root=root_b) == 0
    first.FirstBootProvisioner(root=root_a).apply(bundle=bundle, hardware_serial=SERIAL)
    assert not target.exists() and not (root_a / 'etc/rosy' / filename).exists()


@pytest.mark.parametrize('fault', ['nonroot', 'oversize', 'invalid_utf8', 'legacy'])
def test_operator_cli_refuses_before_canonical_mutation(tmp_path, monkeypatch, fault):
    import os_state_config as m

    _, root, _, common, _ = _provision_a(tmp_path, monkeypatch, protocol=2)
    before = (common / 'state/current.json').read_bytes()
    monkeypatch.setattr(m.os, 'geteuid', lambda: 1000 if fault == 'nonroot' else 0)
    raw = b'x' * 65537 if fault == 'oversize' else b'\xff' if fault == 'invalid_utf8' else b'operator: test\n'
    monkeypatch.setattr(m.sys, 'stdin', io.TextIOWrapper(io.BytesIO(raw)))
    destination = tmp_path / 'legacy' if fault == 'legacy' else root
    destination.mkdir(exist_ok=True)
    assert m.main(['--file', 'ir_calibration.yaml', '--input', '-'], root=destination) == 1
    assert (common / 'state/current.json').read_bytes() == before
    assert not (destination / 'etc/rosy/ir_calibration.yaml').exists()


@pytest.mark.parametrize('fault', ['missing_argument', 'mismatched_reference', 'missing_file',
                                  'oversize', 'nonmapping', 'invalid_yaml'])
def test_nominal_profile_failure_does_not_publish_half_a_generation(tmp_path, monkeypatch, fault):
    import os_state_config as m
    import yaml

    _, root, _, common, _ = _provision_a(tmp_path, monkeypatch, protocol=2)
    before = (common / 'state/current.json').read_bytes()
    profile = tmp_path / 'profile.yaml'
    profile.write_bytes(b'x' * 65537 if fault == 'oversize' else b'[]' if fault == 'nonmapping'
                        else b'profile: [' if fault == 'invalid_yaml' else b'height_m: 0.06\n')
    if fault == 'missing_file':
        profile.unlink()
    reference = str(profile.with_name('different.yaml') if fault == 'mismatched_reference' else profile)
    document = {'/**/line_observer_node': {'ros__parameters': {
        'camera_ground_source': 'NOMINAL', 'nominal_camera_profile_path': reference}}}
    monkeypatch.setattr(m.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(m.sys, 'stdin', io.TextIOWrapper(io.BytesIO(yaml.safe_dump(document).encode())))
    argv = ['--file', 'line_observer_overrides.yaml', '--input', '-']
    if fault != 'missing_argument':
        argv += ['--profile-input', str(profile)]
    assert m.main(argv, root=root) == 1
    assert (common / 'state/current.json').read_bytes() == before
    assert not (root / 'etc/rosy/camera_nominal.yaml').exists()
    assert not (root / 'etc/rosy/line_observer_overrides.yaml').exists()
