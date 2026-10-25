"""Low-light recovery must not mistake LEDs, replay, or brightness for field acceptance."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).parents[1]
FILES = {
    'camera_quality': REPO / 'deploy/robot/omx/camera_quality.py',
    'camera_readiness': REPO / 'deploy/robot/omx/camera_readiness.py',
    'commissioning_view': REPO / 'deploy/robot/omx/commissioning_view.py',
}


def load(name):
    spec = importlib.util.spec_from_file_location(name, FILES[name])
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
                quality=dict(usable=usable, policy='omx-photometric-v3',
                             condition='NORMAL' if usable else 'UNDEREXPOSED',
                             mean_intensity=100 if usable else 0, spatial_contrast=50, clipped_fraction=0))


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


def test_polling_the_same_fresh_frame_does_not_count_or_erase_distinct_confirmations():
    gate = load('camera_quality').Readiness(required=3)
    for index in range(1, 4):
        state = {role: sample(100+index/10, index) for role in ['top', 'front']}
        result = gate.update(state)
        assert result['photometric_ready'] is (index == 3)
        repeated = gate.update(state)
        assert not repeated['photometric_ready']
        assert repeated['confirmations'] == dict(top=index, front=index)
    state['front']['fresh'] = False
    assert gate.update(state)['confirmations']['front'] == 0


def test_contradictory_quality_for_the_same_frame_is_rejected():
    gate = load('camera_quality').Readiness(required=3)
    state = {role: sample() for role in ['top', 'front']}
    gate.update(state)
    changed = {role: {**item, 'quality': {**item['quality'], 'mean_intensity': 200}}
               for role, item in state.items()}
    assert gate.update(changed)['confirmations'] == dict(top=0, front=0)


def test_quality_and_jpeg_have_the_same_sample_lifetime():
    store = load('commissioning_view').ObservationStore()
    metrics = dict(usable=False, policy='omx-photometric-v3')
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
    spec = importlib.util.spec_from_file_location('camera_environment',
                                                REPO / 'deploy/robot/omx/camera_environment.py')
    environment = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(environment)
    monkeypatch.setitem(sys.modules, 'camera_environment', environment)
    runtime = load('camera_readiness')
    restored = []
    monkeypatch.setattr(runtime, 'prepare', lambda *a: {'cameras': {}})
    monkeypatch.setattr(runtime, 'save', lambda *a: (_ for _ in ()).throw(OSError('disk full')))
    monkeypatch.setattr(runtime, 'restore', lambda root: restored.append(root))
    with pytest.raises(OSError):
        runtime.run({'cameras': {}}, tmp_path, 'digest', .000000001)
    assert restored == [tmp_path]


@pytest.mark.parametrize('changes', [dict(source_stamp=float('nan')), dict(sequence=1),
                                   dict(quality={'policy': 'omx-photometric-v3'}),
                                   dict(quality={'policy': 'omx-photometric-v3', 'usable': 'false'})])
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


def test_deployment_candidates_match_the_bounded_tuner_contract():
    import json
    path = REPO / 'deploy/robot/omx/camera-readiness.json.example'
    assert load('camera_readiness').validate_profile(json.loads(path.read_text()))


def test_service_has_independent_restore_for_the_same_state_directory():
    import configparser
    import shlex
    unit = configparser.ConfigParser(interpolation=None)
    unit.read(REPO / 'deploy/robot/omx/rosy-omx-camera-readiness.service')
    start = shlex.split(unit['Service']['ExecStart'])
    stop = shlex.split(unit['Service']['ExecStopPost'])
    assert 'restore' in stop
    assert start[start.index('--state-dir')+1] == stop[stop.index('--state-dir')+1]
    assert unit['Service']['NoNewPrivileges'] == 'true'
    assert 'rosy-omx-camera-view.service' in unit['Unit']['Requires']
    # A boot-time refusal restores the originals in ExecStopPost; only a bounded retry reaches READY.
    assert unit['Service']['Restart'] == 'on-failure'
    assert int(unit['Unit']['StartLimitBurst']) <= 3
    # systemd permits repeated EnvironmentFile entries; ConfigParser defaults do not.
    view = configparser.ConfigParser(interpolation=None, strict=False)
    view.read(REPO / 'deploy/robot/omx/rosy-omx-camera-view.service')
    assert 'commissioning_view.py' in view['Service']['ExecStart']
    assert 'FASTDDS_DEFAULT_PROFILES_FILE="$ROSY_CAMERA_PIPELINE_ROOT/camera-view-receive.xml"' in view['Service']['ExecStart']
    assert 'rosy-omx-camera@top.service' in view['Unit']['After']
    assert 'rosy-omx-camera@front.service' in view['Unit']['After']


def _producer_world(runtime, monkeypatch, owners_by_call):
    """systemctl reports the preview active; fuser answers from the given sequence."""
    import subprocess
    calls = {'fuser': 0}

    def command(args):
        if args[0] == 'systemctl':
            return 'ActiveState=active\nMainPID=4242\nInvocationID=abc\n'
        owners = owners_by_call[min(calls['fuser'], len(owners_by_call)-1)]
        calls['fuser'] += 1
        if owners is None:
            raise subprocess.CalledProcessError(1, args)
        return owners
    clock = {'t': 0.0}
    monkeypatch.setattr(runtime, 'command', command)
    monkeypatch.setattr(runtime.time, 'monotonic', lambda: clock['t'])
    monkeypatch.setattr(runtime.time, 'sleep', lambda s: clock.__setitem__('t', clock['t']+s))
    return calls


def test_producer_waits_for_the_preview_to_open_the_camera_at_boot(monkeypatch):
    runtime = load('camera_readiness')
    calls = _producer_world(runtime, monkeypatch, [None, None, ' 4242'])
    assert runtime.producer('top', '/dev/video0')['MainPID'] == '4242'
    assert calls['fuser'] == 3


@pytest.mark.parametrize('owners', [None, ' 4242 999', ' 999'])
def test_producer_still_refuses_a_missing_or_shared_owner_after_the_wait(monkeypatch, owners):
    runtime = load('camera_readiness')
    _producer_world(runtime, monkeypatch, [owners])
    with pytest.raises(RuntimeError, match='sole camera owner'):
        runtime.producer('top', '/dev/video0', wait_s=2.0)


def test_a_reused_baseline_guards_the_current_preview_not_the_one_that_recorded_it(monkeypatch, tmp_path):
    import json
    runtime = load('camera_readiness')
    original = {'gain': 4}
    old = {'ActiveState': 'active', 'MainPID': '2153151', 'InvocationID': 'a'*32}
    now = {'ActiveState': 'active', 'MainPID': '2463', 'InvocationID': 'f'*32}
    (tmp_path/'baseline.json').write_text(json.dumps(dict(profile_sha256='p', recorded_ns=1, cameras={
        'top': dict(device='/dev/video0', identity={'rdev': 1}, producer=old, original=original)})))
    monkeypatch.setattr(runtime, 'identity', lambda device: {'rdev': 1})
    monkeypatch.setattr(runtime, 'producer', lambda role, device, wait_s=15.0: now)
    monkeypatch.setattr(runtime, 'get_controls', lambda device, names: dict(original))
    baseline = runtime.prepare({}, tmp_path, 'p')
    assert baseline['cameras']['top']['producer'] == now
    assert json.loads((tmp_path/'baseline.json').read_text())['cameras']['top']['producer'] == old  # file unchanged


def test_viewer_receive_profile_is_the_measured_4mib_udp_buffer_only():
    import xml.etree.ElementTree as ET
    ns = {'p': 'http://www.eprosima.com/XMLSchemas/fastRTPS_Profiles'}
    root = ET.parse(REPO / 'deploy/robot/omx/camera-view-receive.xml').getroot()
    transport = root.find('p:transport_descriptors/p:transport_descriptor', ns)
    assert transport.find('p:type', ns).text == 'UDPv4'
    assert int(transport.find('p:receiveBufferSize', ns).text) == 4 * 1024 * 1024
    participant = root.find('p:participant', ns)
    assert participant.get('is_default_profile') == 'true'
    assert participant.find('p:rtps/p:userTransports/p:transport_id', ns).text == transport.find('p:transport_id', ns).text
