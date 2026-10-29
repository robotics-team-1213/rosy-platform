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
@pytest.mark.parametrize('reset', [False, True])
def test_recovery_uses_applied_controls_after_normal_reentry_or_device_reset(monkeypatch, tmp_path,
                                                                         condition, values, reset):
    env, runtime, quality = load('camera_environment'), load('camera_readiness'), load('camera_quality')
    monkeypatch.setitem(sys.modules, 'camera_quality', quality)
    clock = [0.]
    monkeypatch.setattr(env, 'time', SimpleNamespace(monotonic=lambda: clock[0], time=lambda: 1000+clock[0],
        time_ns=lambda: int((1000+clock[0])*1e9), sleep=lambda dt: clock.__setitem__(0, clock[0]+dt)))
    cameras = {role: dict(device=role, candidates=[dict(auto_exposure=1, exposure_time_absolute=n) for n in (400, 800)],
                         bright_candidates=[dict(auto_exposure=1, exposure_time_absolute=n) for n in (160, 80)])
               for role in ('top', 'front')}
    original = dict(auto_exposure=3, exposure_time_absolute=80, gain=3)
    current = {role: dict(original) for role in cameras}
    baseline = {'cameras': {role: dict(device=role, original=dict(original), identity=role, producer={})
                            for role in cameras}}
    writes, reserved, resets = [], [], []

    def response(*args, **kwargs):
        if reset and clock[0] >= 16 and not resets:
            current['top'] = dict(original)
            resets.append(clock[0])
        state = {'read_only': True}
        for role in cameras:
            normal = 12 <= clock[0] < 16
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

    monkeypatch.setattr(env.urllib.request, 'urlopen', response)
    backend = SimpleNamespace(prepare=lambda *a: baseline, identity=lambda d: d, producer=lambda *a: {},
        get_controls=lambda d, names: {key: current[d][key] for key in names}, write_control=write,
        restore_controls=runtime.restore_controls, apply_candidate=runtime.apply_candidate,
        save=runtime.save, append_event=runtime.append_event, restore=restore,
        control_intent=runtime.control_intent,
        reserve_budget=lambda root: reserved.append(clock[0]), BudgetExhausted=runtime.BudgetExhausted)
    env.monitor(dict(viewer_url='http://127.0.0.1:8767', cameras=cameras), tmp_path, 'test-profile', 36, backend)
    assert any(name == 'exposure_time_absolute' and value == values[-1] for _, _, name, value in writes)
    assert not any(at >= 16 and role == 'front' for at, role, _, _ in writes)
    if reset:
        assert any(at >= 16 and role == 'top' and name == 'exposure_time_absolute' and value == values[-1]
                   for at, role, name, value in writes)
    else:
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
    (METADATA.replace('1: Manual Mode', '2: Other Mode'), dict(auto_exposure=1)),
    (METADATA.replace('step=1 default=4', 'step=0 default=4'), dict(auto_exposure=1, gain=4)),
    (METADATA.replace('value=4', 'value=4 flags=read-only'), dict(auto_exposure=1, gain=4)),
    (METADATA.replace('value=4', 'value=4 flags=disabled'), dict(auto_exposure=1, gain=4)),
    (METADATA, dict(auto_exposure=3, exposure_time_absolute=6000)),
])
def test_capability_check_refuses_invalid_candidate_or_restore_values(metadata, controls):
    with pytest.raises(ValueError):
        load('camera_readiness').validate_controls(metadata, [controls])
