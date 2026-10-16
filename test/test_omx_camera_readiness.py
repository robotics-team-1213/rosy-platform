"""Low-light recovery must not mistake LEDs, replay, or brightness for field acceptance."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).parents[1] / 'deploy/robot/omx'


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def textured():
    gradient = np.linspace(40, 200, 640).astype(np.uint8)
    return np.repeat(np.tile(gradient, (120, 1))[:, :, None], 3, axis=2)


def test_a_bright_led_in_an_otherwise_dark_image_is_not_usable():
    quality = load('camera_quality')
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame[200:210, 300:310] = 255
    assert not quality.frame_quality(frame)['usable']
    assert quality.frame_quality(textured())['usable']


@pytest.mark.parametrize('value', [0, 100, 255])
def test_black_flat_or_clipped_images_do_not_pass(value):
    frame = np.full((120, 160, 3), value, dtype=np.uint8)
    assert not load('camera_quality').frame_quality(frame)['usable']


def sample(stamp=100, sequence=1, usable=True):
    return dict(fresh=True, source_stamp=stamp, sequence=sequence,
                quality=dict(usable=usable, policy='omx-photometric-v2'))


def test_readiness_requires_both_streams_advancing_and_never_admits_motion():
    gate = load('camera_quality').Readiness(required=3)
    for index in range(3):
        result = gate.update({role: sample(100+index/10, index+1) for role in ['top', 'front']})
    assert result['photometric_ready']
    assert not result['motion_admitted']
    assert not gate.update({'top': sample(101, 4)})['photometric_ready']


def test_replay_stale_or_missing_quality_cannot_hold_readiness_open():
    gate = load('camera_quality').Readiness(required=1)
    state = {role: sample() for role in ['top', 'front']}
    assert gate.update(state)['photometric_ready']
    assert not gate.update(state)['photometric_ready']
    state = {role: sample(101, 2) for role in ['top', 'front']}
    state['front']['fresh'] = False
    assert not gate.update(state)['photometric_ready']
    state['front'] = sample(102, 3)
    del state['front']['quality']
    assert not gate.update(state)['photometric_ready']


def test_quality_and_jpeg_have_the_same_sample_lifetime():
    store = load('commissioning_view').ObservationStore()
    metrics = dict(usable=False, policy='omx-photometric-v2')
    store.put('top', 100, b'jpeg', quality=metrics, received=10, wall=100)
    metrics['usable'] = True
    assert not store.snapshot(now=10.1, wall=100.1)['top']['quality']['usable']
    assert store.snapshot(now=13, wall=103)['top']['quality'] is None


def test_restore_attempts_all_controls_after_a_partial_failure():
    runtime = load('camera_readiness')
    writes = []

    def write(name, value):
        writes.append((name, value))
        if name == 'gain':
            raise OSError('USB write failed')

    errors = runtime.restore_controls(dict(auto_exposure=3, exposure_time_absolute=156,
                                           gain=0, gamma=100), write)
    assert errors
    assert ('gamma', 100) in writes
    assert writes[-1] == ('auto_exposure', 3)


def test_profile_rejects_camera_identity_guess_and_unbounded_exposure():
    runtime = load('camera_readiness')
    def profile(device, exposure):
        return dict(viewer_url='http://127.0.0.1:8767', cameras={role: dict(
            device=device, candidates=[dict(auto_exposure=1, exposure_time_absolute=exposure)])
            for role in ['top', 'front']})
    with pytest.raises(ValueError):
        runtime.validate_profile(profile('/dev/video0', 400))
    with pytest.raises(ValueError):
        runtime.validate_profile(profile('/dev/v4l/by-id/selected-camera', 100000))
    with pytest.raises(ValueError):
        runtime.validate_profile(profile('/dev/v4l/by-id/selected-camera', 400))


def test_settings_restoration_still_runs_when_receipt_storage_fails(monkeypatch, tmp_path):
    import sys
    quality = load('camera_quality')
    monkeypatch.setitem(sys.modules, 'camera_quality', quality)
    runtime = load('camera_readiness')
    restored = []
    monkeypatch.setattr(runtime, 'prepare', lambda *a: {'cameras': {}})
    monkeypatch.setattr(runtime, 'save', lambda *a: (_ for _ in ()).throw(OSError('disk full')))
    monkeypatch.setattr(runtime, 'restore', lambda root: restored.append(root))
    with pytest.raises(OSError):
        runtime.run({'cameras': {}}, tmp_path, 'digest', .000000001)
    assert restored == [tmp_path]


@pytest.mark.parametrize('changes', [dict(source_stamp=float('nan')), dict(sequence=1),
                                   dict(quality={'policy': 'omx-photometric-v2'}),
                                   dict(quality={'policy': 'omx-photometric-v2', 'usable': 'false'})])
def test_invalid_observation_cannot_trigger_tuning(changes):
    item = sample(101, 2, False)
    item.update(changes)
    assert not load('camera_quality').advancing_frame(item, (100, 1))


def test_manual_exposure_is_enabled_before_dependent_controls():
    calls = []
    load('camera_readiness').apply_candidate(
        dict(exposure_time_absolute=400, gain=50, auto_exposure=1),
        lambda name, value: calls.append((name, value)))
    assert calls[0] == ('auto_exposure', 1)


def test_durable_baseline_includes_directory_fsync(monkeypatch, tmp_path):
    import stat
    runtime = load('camera_readiness')
    modes = []
    monkeypatch.setattr(runtime.os, 'fsync', lambda fd: modes.append(runtime.os.fstat(fd).st_mode))
    runtime.save(tmp_path/'baseline.json', {'original': 1}, exclusive=True)
    assert any(stat.S_ISDIR(mode) for mode in modes)


def test_sensor_noise_cannot_be_promoted_to_useful_scene_structure():
    rng = np.random.default_rng(42)
    noise = rng.integers(0, 150, size=(480, 640, 3), dtype=np.uint8)
    assert not load('camera_quality').frame_quality(noise)['usable']


def test_older_viewer_brightness_only_decision_is_not_accepted():
    item = sample()
    item['quality'] = dict(policy='omx-photometric-v1', usable=True)
    assert not load('camera_quality').advancing_frame(item, (0, 0))

