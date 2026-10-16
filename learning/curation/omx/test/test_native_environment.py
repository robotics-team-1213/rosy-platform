"""Environment observations remain byte-bound, sparse evidence rather than task labels."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def module():
    path = Path(__file__).resolve().parents[1] / 'native_environment.py'
    spec = importlib.util.spec_from_file_location('native_environment', path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.fixture
def inputs():
    events = []
    for stamp, condition in ((100, 'UNDEREXPOSED'), (150, 'NORMAL'), (300, 'OVEREXPOSED')):
        events.append(dict(policy='omx-photometric-v3', run_id='run-1', profile_sha256='a' * 64,
                           recorded_ns=stamp, expires_ns=stamp+20, motion_admitted=False,
                           physical_acceptance=False, photometric_ready=condition == 'NORMAL',
                           environment={r: dict(condition=condition, state='OBSERVING',
                                                environment_epoch=1, control_generation=0)
                                        for r in ('top', 'front')},
                           observations={r: dict(fresh=True, quality=dict(
                               policy='omx-photometric-v3', condition=condition)) for r in ('top', 'front')}))
    raw = ''.join(json.dumps(event) + '\n' for event in events).encode()
    windows = [dict(episode_index=i, start_ns=start, end_ns=end, run_id='run-1', profile_sha256='a' * 64)
               for i, (start, end) in enumerate(((90, 200), (290, 350), (400, 450)))]
    files = {'meta/info.json': 'b' * 64, 'data/part.parquet': 'c' * 64}
    return raw, windows, files


def seal(module, inputs):
    raw, windows, files = inputs
    return module.seal_environment(raw, windows, files, rig_revision='rig', calibration_revision='cal')


def bind(module, inputs, evidence):
    return module.bind_environment([dict(episode_index=i) for i in range(3)], inputs[2],
                                   rig_revision='rig', calibration_revision='cal', evidence=evidence)


def test_sparse_dark_bright_unknown_evidence_has_no_continuity_or_success_claim(module, inputs):
    evidence = seal(module, inputs)
    summary = bind(module, inputs, evidence)
    assert evidence['log_sha256'] == hashlib.sha256(inputs[0]).hexdigest()
    assert evidence['log_utf8'].encode() == inputs[0]
    assert summary['status'] == 'recorded'
    assert summary['photometric_continuity_verified'] is False
    assert summary['episodes'][0]['roles']['top']['image_conditions'] == {'UNDEREXPOSED': 1, 'NORMAL': 1}
    assert summary['episodes'][1]['roles']['front']['image_conditions'] == {'OVEREXPOSED': 1}
    assert summary['episodes'][2]['status'] == 'unobserved'
    assert summary['episodes'][2]['event_count'] == 0
    assert summary['physical_acceptance'] is False
    assert summary['task_success'] is None


@pytest.mark.parametrize('fault', ['hash', 'bytes', 'files', 'rig', 'calibration', 'order', 'window',
                                  'overlap', 'run', 'profile', 'policy', 'partial', 'nan', 'bool_time'])
def test_invalid_or_misbound_environment_is_rejected(module, inputs, fault):
    evidence = seal(module, inputs)
    if fault == 'hash': evidence['log_sha256'] = 'd' * 64
    if fault == 'files': evidence['dataset_files']['data/part.parquet'] = 'd' * 64
    if fault == 'rig': evidence['rig_revision'] = 'other'
    if fault == 'calibration': evidence['calibration_revision'] = 'other'
    if fault == 'order': evidence['episodes'][1]['episode_index'] = 0
    if fault == 'window': evidence['episodes'][0]['end_ns'] = 80
    if fault == 'overlap': evidence['episodes'][1]['start_ns'] = 180
    if fault == 'run': evidence['episodes'][0]['run_id'] = 'wrong-run'
    if fault == 'profile': evidence['episodes'][0]['profile_sha256'] = 'e' * 64
    if fault in ('bytes', 'policy', 'partial', 'nan', 'bool_time'):
        raw = evidence['log_utf8']
        if fault == 'bytes':
            evidence['log_utf8'] += ' '
        else:
            if fault == 'policy': raw = raw.replace('omx-photometric-v3', 'omx-photometric-v2')
            if fault == 'partial': raw = raw.rstrip('\n')
            if fault == 'nan': raw = raw.replace('"recorded_ns": 100', '"recorded_ns": NaN')
            if fault == 'bool_time': raw = raw.replace('"recorded_ns": 100', '"recorded_ns": true')
            evidence['log_utf8'] = raw
            evidence['log_sha256'] = hashlib.sha256(raw.encode()).hexdigest()
    with pytest.raises(ValueError, match='environment'):
        bind(module, inputs, evidence)


def test_missing_environment_is_explicitly_unknown(module, inputs):
    summary = bind(module, inputs, None)
    assert summary['status'] == 'unrecorded'
    assert all(item['status'] == 'unobserved' for item in summary['episodes'])


def test_stale_observation_is_unknown_and_smoothed_condition_is_not_current_image(module, inputs):
    raw, windows, files = inputs
    events = [json.loads(line) for line in raw.splitlines()]
    events[0]['observations']['top']['fresh'] = False
    events[1]['environment']['front']['condition'] = 'UNDEREXPOSED'
    evidence = seal(module, (''.join(json.dumps(e)+'\n' for e in events).encode(), windows, files))
    summary = bind(module, inputs, evidence)
    assert summary['episodes'][0]['roles']['top']['image_conditions'] == {'UNKNOWN': 1, 'NORMAL': 1}
    assert summary['episodes'][0]['roles']['front']['image_conditions'] == {'UNDEREXPOSED': 1, 'NORMAL': 1}


def test_sealing_and_binding_do_not_mutate_source(module, inputs):
    previous = copy.deepcopy(inputs)
    evidence = seal(module, inputs)
    bound = bind(module, inputs, evidence)
    bound['episodes'][0]['roles']['top']['image_conditions'].clear()
    assert inputs == previous
    assert bind(module, inputs, evidence)['episodes'][0]['event_count'] == 2
