"""Durable camera startup guard; real files simulate abrupt host resets."""
import importlib.util
from pathlib import Path
import pytest

NATIVE = Path(__file__).resolve().parents[1] / 'deploy/robot/pinky_pro/native'

@pytest.fixture
def guard():
    spec = importlib.util.spec_from_file_location('camera_guard', NATIVE / 'camera-boot-guard.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def test_two_unconfirmed_boots_hold_camera_across_future_boots(guard, tmp_path):
    state = tmp_path / 'guard.json'
    assert guard.check(state, 'boot-a') == 0
    assert guard.check(state, 'boot-a') == 0  # same-boot process retry is not another reset
    assert guard.check(state, 'boot-b') == 0
    assert guard.check(state, 'boot-c') == 1
    assert guard.check(state, 'boot-d') == 1

def test_healthy_start_clears_unconfirmed_history(guard, tmp_path):
    state = tmp_path / 'guard.json'
    guard.check(state, 'boot-a')
    guard.check(state, 'boot-b')
    guard.healthy(state, 'boot-b')
    assert guard.check(state, 'boot-c') == 0
    assert guard.check(state, 'boot-d') == 0

def test_clean_stop_does_not_count_as_a_host_crash(guard, tmp_path):
    state = tmp_path / 'guard.json'
    for boot in ['boot-a', 'boot-b', 'boot-c', 'boot-d']:
        assert guard.check(state, boot) == 0
        guard.stopped(state, boot, 'success')

def test_failed_stop_preserves_pending_start(guard, tmp_path):
    state = tmp_path / 'guard.json'
    guard.check(state, 'boot-a')
    guard.stopped(state, 'boot-a', 'signal')
    guard.check(state, 'boot-b')
    assert guard.check(state, 'boot-c') == 1

def test_corrupt_state_refuses_camera_without_overwriting_evidence(guard, tmp_path):
    state = tmp_path / 'guard.json'
    state.write_text('{incomplete')
    with pytest.raises(ValueError):
        guard.check(state, 'boot-a')
    assert state.read_text() == '{incomplete'

def test_old_boot_cannot_clear_current_pending_start(guard, tmp_path):
    state = tmp_path / 'guard.json'
    guard.check(state, 'boot-a')
    guard.check(state, 'boot-b')
    guard.healthy(state, 'boot-a')
    guard.stopped(state, 'boot-a', 'success')
    assert guard.check(state, 'boot-c') == 1

def test_camera_is_optional_and_has_bounded_local_retries():
    unit = (NATIVE / 'rosy-camera.service').read_text()
    target = (NATIVE / 'rosy-runtime.target').read_text()
    assert 'ExecCondition=/usr/bin/python3 -I -B /opt/rosy/current/deploy/robot/native/camera-boot-guard.py check' in unit
    assert 'StartLimitIntervalSec=300' in unit
    assert 'StartLimitBurst=3' in unit
    assert 'RestartSec=10' in unit
    assert 'Wants=rosy-io.service rosy-camera.service' in target

def test_camera_survival_observer_does_not_block_restart():
    unit = (NATIVE / 'rosy-camera.service').read_text()
    assert 'ExecStartPost=' not in unit
    assert 'Wants=rosy-camera-healthy.timer' in unit
    timer = (NATIVE / 'rosy-camera-healthy.timer').read_text()
    assert 'BindsTo=rosy-camera.service' in timer
    assert 'After=rosy-camera.service' in timer
    assert 'PartOf=rosy-camera.service' in timer
    assert 'OnActiveSec=90' in timer
    service = (NATIVE / 'rosy-camera-healthy.service').read_text()
    assert 'ExecCondition=/usr/bin/systemctl is-active --quiet rosy-camera.service' in service
    assert 'camera-boot-guard.py healthy' in service

def test_observer_units_reach_image_and_image_layer_sync():
    sync = (NATIVE / 'sync-image-layer.py').read_text()
    image = (NATIVE.parent / 'image/build-native-payload.sh').read_text()
    for name in ['rosy-camera-healthy.timer','rosy-camera-healthy.service']:
        assert '"'+name+'"' in sync
        assert '$NATIVE_RUNTIME_SOURCE/'+name in image
