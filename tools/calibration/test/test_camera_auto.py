"""Read-only automatic camera capture rejects insufficient physical evidence."""
import importlib.util
import math
import json
from types import SimpleNamespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def test_stationary_capture_rejects_stale_and_nonfinite_odometry():
    guard = module('camera_capture').StationaryCapture()
    assert 'stale_odometry' in guard.faults(1)
    guard.observe_odom(0, 0, 0, 0, 0, 0)
    assert not guard.faults(.1)
    assert 'stale_odometry' in guard.faults(.3)
    guard.observe_odom(math.nan, 0, 0, 0, 0, .4)
    assert 'invalid_odometry' in guard.faults(.4)


@pytest.mark.parametrize('pose', [(0, 0, 0, .01, 0), (.006, 0, 0, 0, 0),
                                  (0, 0, .03, 0, 0), (0, 0, 0, 0, .03)])
def test_motion_or_drift_fault_is_latched(pose):
    guard = module('camera_capture').StationaryCapture()
    guard.observe_odom(0, 0, 0, 0, 0, 0)
    guard.observe_odom(*pose, .1)
    guard.observe_odom(0, 0, 0, 0, 0, .2)
    assert guard.faults(.2)


def test_yaw_wrap_does_not_invent_motion():
    guard = module('camera_capture').StationaryCapture()
    guard.observe_odom(0, 0, math.pi-.001, 0, 0, 0)
    guard.observe_odom(0, 0, -math.pi+.001, 0, 0, .1)
    assert not guard.faults(.1)


def test_replayed_old_or_future_sensor_stamps_are_not_fresh_samples():
    clock = module('camera_capture').SampleClock()
    assert clock.observe('odom', 100, 100.1, .25) is None
    assert clock.observe('odom', 100, 100.11, .25) == 'repeated_odom'
    assert clock.observe('scan', 99, 100, .5) == 'stale_scan'
    assert clock.observe('camera', 101, 100, .5) == 'stale_camera'
    assert clock.observe('odom', math.nan, 100, .25) == 'stale_odom'
    assert clock.observe('camera', 0, 0, .5) == 'stale_camera'


def test_same_length_scan_with_different_angles_cannot_be_combined():
    geometry = module('camera_capture').ScanGeometry()
    assert geometry.observe(360, -math.pi, .01, .1, 10) is None
    assert geometry.observe(360, -math.pi, .02, .1, 10) == 'scan_geometry_changed'
    assert geometry.observe(360, math.nan, .01, .1, 10) == 'invalid_scan_geometry'
    assert geometry.observe(360, -math.pi, 0, .1, 10) == 'invalid_scan_geometry'


def test_cli_never_treats_weak_candidate_or_base_height_as_calibrated():
    auto = module('camera_auto')
    assert auto.verdict({'fit': {'candidate': {'recommended': False}}}) == 'REJECTED'
    assert auto.verdict({'fit': {'candidate': {'recommended': True, 'height_source': 'base'}}}) == 'CANDIDATE'
    assert auto.verdict({'fit': {'error': 'missing samples'}}) == 'REJECTED'


def test_ssh_uses_pinned_alias_and_readonly_worker():
    auto = module('camera_auto')
    args = auto.ssh_command('rosy-pinky-9dfk')
    assert 'StrictHostKeyChecking=yes' in args
    assert 'BatchMode=yes' in args
    assert 'rosy-pinky-9dfk' in args
    assert args[-1].endswith("exec python3 -'")
    with pytest.raises(ValueError):
        auto.ssh_command('-oProxyCommand=evil')


def test_output_cannot_escape_scratch_root_or_overwrite_evidence(tmp_path):
    auto = module('camera_auto')
    output = tmp_path/'new.json'
    assert auto.checked_output(output, root=tmp_path) == output.resolve()
    with pytest.raises(ValueError):
        auto.checked_output(tmp_path/'..'/'source.json', root=tmp_path)
    output.write_text('preserve')
    with pytest.raises(ValueError):
        auto.checked_output(output, root=tmp_path)
    assert output.read_text() == 'preserve'


def test_rejected_device_fit_is_saved_without_apply_or_success(monkeypatch, tmp_path):
    auto = module('camera_auto')
    reply = {'faults': [], 'fit': {'candidate': {'recommended': False, 'why': 'few walls'}}}
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout=json.dumps(reply).encode())
    monkeypatch.setattr(auto.subprocess, 'run', run)
    output = tmp_path/'result.json'
    assert auto.main(['--robot', 'rosy-pinky-9dfk', '--output', str(output)]) == 2
    saved = json.loads(output.read_text())
    assert saved['verdict'] == 'REJECTED' and saved['applied'] is False
    assert len(calls) == 1
