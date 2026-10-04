"""Wheel gains must be explicit, finite, and verified before playback."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import drive_runtime
import run_rosy


class Drive:
    def __init__(self, damping=0, readback_offset=0):
        self.values = {'stiffness': 625, 'damping': damping, 'target': 4}
        self.readback_offset = readback_offset

    def author(self, key, value):
        self.values[key] = value
        return self.attr(key)

    def attr(self, key):
        return SimpleNamespace(Get=lambda: self.values[key] + self.readback_offset)

    def CreateStiffnessAttr(self, value):
        return self.author('stiffness', value)

    def CreateDampingAttr(self, value):
        return self.author('damping', value)

    def CreateTargetVelocityAttr(self, value):
        return self.author('target', value)

    def GetStiffnessAttr(self):
        return self.attr('stiffness')

    def GetDampingAttr(self):
        return self.attr('damping')

    def GetTargetVelocityAttr(self):
        return self.attr('target')


@pytest.mark.parametrize('damping', [0, -1, float('nan'), float('inf')])
def test_invalid_override_does_not_author_drive(damping):
    drive = Drive()
    with pytest.raises(ValueError):
        drive_runtime.configure_velocity_drive(drive, damping)
    assert drive.values == {'stiffness': 625, 'damping': 0, 'target': 4}


def test_explicit_gain_replaces_position_drive_and_initial_target_is_zero():
    drive = Drive()
    assert drive_runtime.configure_velocity_drive(drive, 50) == 50
    assert drive.values == {'stiffness': 0, 'damping': 50, 'target': 0}


@pytest.mark.parametrize('existing,expected', [(25, 25), (0, 1)])
def test_omitted_override_preserves_existing_positive_gain(existing, expected):
    drive = Drive(existing)
    assert drive_runtime.configure_velocity_drive(drive, None) == expected


def test_sdk_ignoring_authored_values_fails_before_playback():
    with pytest.raises(RuntimeError, match='readback'):
        drive_runtime.configure_velocity_drive(Drive(readback_offset=1), 50)


def cli_args(value):
    return ['run_rosy.py', '--urdf', 'unused', '--output-dir', 'unused', '--namespace', 'rosy_99',
            '--wheel-damping', value]


@pytest.mark.parametrize('value', ['0', '-1', 'nan', 'inf'])
def test_invalid_cli_gain_is_rejected_during_argument_preflight(monkeypatch, value):
    monkeypatch.setattr(sys, 'argv', cli_args(value))
    with pytest.raises(SystemExit) as exc:
        run_rosy.parse_args()
    assert exc.value.code == 2


def test_cli_exposes_explicit_gain_and_runner_uses_verified_configuration(monkeypatch):
    monkeypatch.setattr(sys, 'argv', cli_args('50'))
    assert run_rosy.parse_args().wheel_damping == 50
    source = Path(run_rosy.__file__).read_text()
    assert 'configure_velocity_drive(drive, args.wheel_damping)' in source


@pytest.mark.parametrize('damping', [float('nan'), float('inf')])
def test_corrupt_imported_gain_is_not_silently_replaced(damping):
    drive = Drive(damping)
    with pytest.raises(ValueError):
        drive_runtime.configure_velocity_drive(drive, None)
    assert drive.values['stiffness'] == 625
