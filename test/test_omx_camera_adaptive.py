"""Proposed regressions; copy into an authorized worktree before committing/running remotely."""
import importlib.util
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

REPO = Path(__file__).parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, REPO/'deploy/robot/omx'/f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('condition,values', [('UNDEREXPOSED', [400, 800]), ('OVEREXPOSED', [160, 80])])
@pytest.mark.parametrize('reset,fault', [(False, None), (True, None), (True, 'ENODEV'), (True, 'unknown')])
@pytest.mark.parametrize('middle', [False, True])
def test_recovery_uses_applied_controls_after_normal_reentry_or_device_reset(monkeypatch, tmp_path,
                                                                         condition, values, reset, fault, middle):
    env, runtime, quality = load('camera_environment'), load('camera_readiness'), load('camera_quality')
    monkeypatch.setitem(sys.modules, 'camera_quality', quality)
    clock = [0.]
    monkeypatch.setattr(env, 'time', SimpleNamespace(monotonic=lambda: clock[0], time=lambda: 1000+clock[0],
        time_ns=lambda: int((1000+clock[0])*1e9), sleep=lambda dt: clock.__setitem__(0, clock[0]+dt)))
    cameras = {role: dict(device=role, candidates=[dict(auto_exposure=1, exposure_time_absolute=n) for n in (400, 800)],
                         bright_candidates=[dict(auto_exposure=1, exposure_time_absolute=n) for n in (160, 80)])
               for role in ('top', 'front')}
    if middle:
        for spec in cameras.values():
            spec['candidates'].insert(0, dict(auto_exposure=1, exposure_time_absolute=160))
            spec['bright_candidates'].insert(0, dict(auto_exposure=1, exposure_time_absolute=400))
    original = dict(auto_exposure=3, exposure_time_absolute=80, gain=3)
    current = {role: dict(original) for role in cameras}
    baseline = {'cameras': {role: dict(device=role, original=dict(original), identity=role, producer={})
                            for role in cameras}}
    writes, reserved, resets, denied = [], [], [], []

    def response(*args, **kwargs):
        if reset and clock[0] >= 16 and not resets:
            current['top'] = dict(original)
            if fault == 'unknown':
                current['top']['gain'] = 6
            resets.append(clock[0])
        state = {'read_only': True}
        for role in cameras:
            normal = (7 if middle else 12) <= clock[0] < 16
            exposure = current[role]['exposure_time_absolute']
            state[role] = dict(fresh=True, source_stamp=1000+clock[0], sequence=int(clock[0]*100)+1,
                quality=dict(policy=quality.POLICY, usable=normal, condition='NORMAL' if normal else condition,
                    mean_intensity=100, spatial_contrast=100 if exposure == values[-1] else 10,
                    clipped_fraction=0))
        return io.BytesIO(json.dumps(state).encode())

    def write(role, name, value):
        writes.append((clock[0], role, name, value))
        current[role][name] = value

    def restore(root):
        for role in cameras:
            current[role] = dict(original)

    def reserve(root):
        if middle and clock[0] >= 16 and not denied:
            denied.append(clock[0])
            raise runtime.BudgetExhausted('one occupied budget window')
        reserved.append(clock[0])

    def read(device, names):
        if device == 'top' and fault == 'ENODEV' and 16 <= clock[0] < 22:
            raise OSError(19, 'camera temporarily unavailable')
        return {key: current[device][key] for key in names}

    monkeypatch.setattr(env.urllib.request, 'urlopen', response)
    backend = SimpleNamespace(prepare=lambda *a: baseline, identity=lambda d: d, producer=lambda *a: {},
        get_controls=read, write_control=write,
        restore_controls=runtime.restore_controls, apply_candidate=runtime.apply_candidate,
        save=runtime.save, append_event=runtime.append_event, restore=restore,
        control_intent=runtime.control_intent,
        validate_device_controls=lambda *a: None,
        reserve_budget=reserve, BudgetExhausted=runtime.BudgetExhausted)
    profile = dict(viewer_url='http://127.0.0.1:8767', cameras=cameras)
    if fault == 'unknown':
        with pytest.raises(RuntimeError, match='unowned camera controls'):
            env.monitor(profile, tmp_path, 'test-profile', 46, backend)
        assert not any(at >= 16 and role == 'top' for at, role, _, _ in writes)
        return
    env.monitor(profile, tmp_path, 'test-profile', 46, backend)
    assert any(name == 'exposure_time_absolute' and value == values[-1] for _, _, name, value in writes)
    if middle:
        assert len(denied) == 1
        assert any(at >= 16 and role == 'front' and name == 'exposure_time_absolute' and value == values[-1]
                   for at, role, name, value in writes)
        assert not any(at >= 16 and role == 'front' and name == 'exposure_time_absolute' and value != values[-1]
                       for at, role, name, value in writes)
    else:
        assert not any(at >= 16 and role == 'front' for at, role, _, _ in writes)
    if reset:
        assert any(at >= 16 and role == 'top' and name == 'exposure_time_absolute' and value == values[-1]
                   for at, role, name, value in writes)
    elif not middle:
        assert not any(at >= 16 for at, _, _, _ in writes)
        assert not any(at >= 16 for at in reserved)
    events = [json.loads(line) for line in (tmp_path/'environment.jsonl').read_text().splitlines()]
    assert all(not event['motion_admitted'] for event in events)
    assert all(current[role] == original for role in cameras)


METADATA = '''
auto_exposure 0x009a0901 (menu) : min=0 max=3 default=3 value=3
    1: Manual Mode
    3: Aperture Priority Mode
exposure_time_absolute 0x009a0902 (int) : min=80 max=5000 step=1 default=80 value=80 flags=inactive
gain 0x00980913 (int) : min=1 max=7 step=1 default=4 value=4
gamma 0x00980910 (int) : min=10 max=30 step=10 default=20 value=20
'''


def test_capability_check_accepts_inactive_exposure_and_the_original_auto_mode():
    load('camera_readiness').validate_controls(METADATA, [dict(auto_exposure=1, exposure_time_absolute=800, gain=7),
                                                        dict(auto_exposure=3, exposure_time_absolute=80, gain=4)])


@pytest.mark.parametrize('metadata,controls', [
    (METADATA, dict(auto_exposure=1, gain=8)),
    (METADATA, dict(auto_exposure=1, gamma=15)),
    (METADATA, dict(auto_exposure=2)),
    (METADATA.replace('(menu)', '(int)'), dict(auto_exposure=1)),
    (METADATA.replace('1: Manual Mode', '2: Other Mode'), dict(auto_exposure=1)),
    (METADATA.replace('step=1 default=4', 'step=0 default=4'), dict(auto_exposure=1, gain=4)),
    (METADATA.replace('value=4', 'value=4 flags=read-only'), dict(auto_exposure=1, gain=4)),
    (METADATA.replace('value=4', 'value=4 flags=disabled'), dict(auto_exposure=1, gain=4)),
    (METADATA, dict(auto_exposure=3, exposure_time_absolute=6000)),
])
def test_capability_check_refuses_invalid_candidate_or_restore_values(metadata, controls):
    with pytest.raises(ValueError):
        load('camera_readiness').validate_controls(metadata, [controls])


def control_world(monkeypatch, root):
    runtime = load('camera_readiness')
    original = dict(auto_exposure=3, exposure_time_absolute=80, gain=3)
    spec = dict(device='camera', identity={'rdev': 7}, producer={'MainPID': '42', 'InvocationID': 'owner'},
                original=original)
    current, writes = dict(original), []
    monkeypatch.setattr(runtime, 'identity', lambda d: spec['identity'])
    monkeypatch.setattr(runtime, 'producer', lambda *a, **k: spec['producer'])
    monkeypatch.setattr(runtime, 'get_controls', lambda d, names: {n: current[n] for n in names})
    monkeypatch.setattr(runtime, 'command', lambda args: METADATA)
    def write(device, name, value):
        current[name] = value
        writes.append((name, value))
    monkeypatch.setattr(runtime, 'write_control', write)
    runtime.save(root/'baseline.json', dict(profile_sha256='digest', cameras={'top': spec}))
    runtime.save(root/'control-run.json', dict(run_id='run'))
    return runtime, spec, current, writes


@pytest.mark.parametrize('crash', range(3))
def test_independent_restore_recovers_each_partial_candidate_write(monkeypatch, tmp_path, crash):
    runtime, spec, current, writes = control_world(monkeypatch, tmp_path)
    requested = dict(auto_exposure=1, exposure_time_absolute=800, gain=7)
    runtime.control_intent(tmp_path, 'top', spec, 'digest', 'run', current, requested)
    def write(name, value):
        runtime.write_control('camera', name, value)
        if len(writes) == crash+1:
            raise OSError('interrupted candidate write')
    with pytest.raises(OSError):
        runtime.apply_candidate(requested, write)
    runtime.restore(tmp_path)
    assert current == spec['original']
    assert json.loads((tmp_path/'restoration.json').read_text())['top']['restored']


@pytest.mark.parametrize('crash', range(4))
def test_restore_intent_survives_each_interrupted_restore_step(monkeypatch, tmp_path, crash):
    runtime, spec, current, writes = control_world(monkeypatch, tmp_path)
    current.update(auto_exposure=3, exposure_time_absolute=800, gain=7)
    runtime.control_intent(tmp_path, 'top', spec, 'digest', 'run', current, spec['original'], phase='restoring')
    def write(name, value):
        runtime.write_control('camera', name, value)
        if len(writes) == crash+1:
            raise KeyboardInterrupt('restore process died')
    with pytest.raises(KeyboardInterrupt):
        runtime.restore_controls(spec['original'], write)
    runtime.restore(tmp_path)
    assert current == spec['original']


@pytest.mark.parametrize('damage', ['unknown-control', 'old-run', 'other-owner', 'other-baseline', 'corrupt', 'missing'])
def test_restore_refuses_unknown_controls_or_unbound_intent(monkeypatch, tmp_path, damage):
    runtime, spec, current, writes = control_world(monkeypatch, tmp_path)
    requested = dict(auto_exposure=1, exposure_time_absolute=800, gain=7)
    record = runtime.control_intent(tmp_path, 'top', spec, 'digest', 'run', current, requested)
    current.update(requested)
    if damage == 'unknown-control':
        current['gain'] = 6
    elif damage == 'old-run':
        record['run_id'] = 'earlier'
    elif damage == 'other-owner':
        record['producer'] = {'MainPID': '43', 'InvocationID': 'other'}
    elif damage == 'other-baseline':
        record['binding']['profile_sha256'] = 'other'
    path = tmp_path/'control-intent-top.json'
    if damage == 'missing':
        path.unlink()
    elif damage == 'corrupt':
        path.write_text('{')
    else:
        runtime.save(path, record)
    with pytest.raises(RuntimeError, match='restore incomplete'):
        runtime.restore(tmp_path)
    assert writes == []
    assert not json.loads((tmp_path/'restoration.json').read_text())['top']['restored']


def test_resumed_baseline_rechecks_hardware_and_keeps_original_evidence(monkeypatch, tmp_path):
    runtime, spec, current, writes = control_world(monkeypatch, tmp_path)
    before = (tmp_path/'baseline.json').read_bytes()
    profile = dict(cameras={'top': dict(device='camera', candidates=[dict(auto_exposure=1, exposure_time_absolute=800)])})
    monkeypatch.setattr(runtime, 'command', lambda args: METADATA.replace('max=7', 'max=2'))
    with pytest.raises(ValueError):
        runtime.prepare(profile, tmp_path, 'digest')
    assert writes == [] and (tmp_path/'baseline.json').read_bytes() == before


def test_restore_checks_intermediate_manual_mode_before_any_write(monkeypatch, tmp_path):
    runtime, spec, current, writes = control_world(monkeypatch, tmp_path)
    requested = dict(auto_exposure=1, exposure_time_absolute=800, gain=7)
    runtime.control_intent(tmp_path, 'top', spec, 'digest', 'run', current, requested)
    current.update(requested)
    monkeypatch.setattr(runtime, 'command', lambda args: METADATA.replace('1: Manual Mode', '2: Other Mode'))
    with pytest.raises(RuntimeError, match='restore incomplete'):
        runtime.restore(tmp_path)
    assert writes == []
