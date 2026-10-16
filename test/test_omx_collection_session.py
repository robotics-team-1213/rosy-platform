"""Tomorrow's collection path must fail closed before and during a trajectory."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'deploy/robot/omx'))


@pytest.fixture
def module():
    spec = importlib.util.spec_from_file_location('collection_session', ROOT/'deploy/robot/omx/collection_session.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def profile():
    return dict(schema='rosy.omx-collection-profile.v1', enabled=False, workcell_id='fixture',
                instance_id='fixture', rig_revision='fixture-rig', calibration_revision='fixture-cal',
                task='fixture only', fps=10, max_image_age_s=.5, max_sample_gap_s=.3,
                max_state_age_s=.2, max_reference_age_s=.2, free_disk_bytes=1024, max_frame_jitter_s=.2,
                camera_shapes={r: [2, 2, 3] for r in ('top', 'front')},
                joint_names=['joint'+str(i) for i in range(6)],
                normalization=[[-1., 1.]]*6, max_session_s=5.)


class Backend:
    mode = 'rehearsal'
    def __init__(self, fault=None):
        self.fault, self.commands, self.stops, self.n = fault, [], [], 0
    def observe(self):
        self.n += 1
        now = time.time_ns()
        conditions = 'UNDEREXPOSED' if self.fault == 'dark' and self.commands else 'NORMAL'
        env = dict(policy='omx-photometric-v3', recorded_ns=now, expires_ns=now+750_000_000,
                   run_id='fixture-run', profile_sha256='a'*64, physical_acceptance=False,
                   motion_admitted=False, photometric_ready=conditions == 'NORMAL',
                   environment={r: dict(state='NORMAL', condition='NORMAL', pending='NORMAL',
                       confirmations=3, source_after=0., environment_epoch=1, control_generation=0)
                       for r in ('top', 'front')}, observations={})
        for role in ('top', 'front'):
            if self.fault == 'generation' and self.commands:
                env['environment'][role]['control_generation'] = 1
            env['observations'][role] = dict(fresh=True, source_stamp=now/1e9, sequence=self.n,
                source_age_s=0., receipt_age_s=0., quality=dict(policy='omx-photometric-v3',
                condition=conditions, usable=conditions == 'NORMAL', mean_intensity=90.,
                spatial_contrast=20., p5=10., p95=150., dark_fraction=.1, clipped_fraction=.01))
        return dict(environment=env, time_ns=now, observation_state=[0.]*6, action=[0.]*6,
                    joint_source_stamp=now/1e9, reference_source_stamp=now/1e9,
                    state_age_s=0., reference_age_s=0.,
                    images={r: dict(data=b'\x00'*12, width=2, height=2, source_stamp=now/1e9,
                                   sequence=self.n) for r in ('top', 'front')})
    def submit(self, step, command_id):
        self.commands.append(command_id)
        return dict(accepted=self.fault != 'reject', reason='fixture')
    def terminal(self):
        return dict(succeeded=True, source='fixture') if self.n >= 15 else None
    def stop(self, reason):
        self.stops.append(reason)
        return dict(hold_requested=True, physical_stop_verified=False)
    def drain_events(self):
        return []


def teacher():
    return dict(schema='rosy.omx-collection-teacher.v1', steps=[dict(positions=[0.]*6, duration_s=.2)])


def test_rehearsal_records_windows_original_images_and_never_claims_hardware(module, tmp_path):
    backend = Backend()
    result = module.run_session(profile(), teacher(), tmp_path/'capture', backend)
    assert result['mode'] == 'rehearsal' and result['source_mode'] == 'simulation'
    assert result['episodes'][0]['complete'] is True
    assert result['episodes'][0]['frames'] >= 2
    assert result['episodes'][0]['start_ns'] < result['episodes'][0]['end_ns']
    assert result['episodes'][0]['outcome'] == 'unknown'
    assert backend.stops and len(backend.commands) == 1
    assert 'environment.jsonl' in result['files']
    assert all((tmp_path/'capture'/p).is_file() for p in result['files'])


@pytest.mark.parametrize('fault', ['dark', 'reject', 'generation'])
def test_degradation_or_owner_rejection_stops_and_preserves_incomplete_attempt(module, tmp_path, fault):
    backend = Backend(fault)
    result = module.run_session(profile(), teacher(), tmp_path/fault, backend)
    assert result['episodes'][0]['complete'] is False
    assert result['episodes'][0]['reason']
    assert backend.stops and len(backend.commands) == 1
    assert (tmp_path/fault/'manifest.json').is_file()


def test_disabled_profile_cannot_construct_hardware_runtime(module):
    with pytest.raises(ValueError, match='disabled|acceptance'):
        module.validate_profile(profile(), mode='hardware')


def test_existing_output_is_never_overwritten_or_armed(module, tmp_path):
    backend = Backend()
    root = tmp_path/'old'; root.mkdir()
    (root/'original').write_text('preserve')
    with pytest.raises(ValueError, match='exists|new'):
        module.run_session(profile(), teacher(), root, backend)
    assert not backend.commands and (root/'original').read_text() == 'preserve'


@pytest.mark.parametrize('fault', ['stale', 'overexposed', 'run', 'future', 'pending'])
def test_environment_envelope_rejects_bad_receipts(module, fault):
    sample = Backend().observe(); env = sample['environment']; now = sample['time_ns']
    if fault == 'stale': env['expires_ns'] = now-1
    if fault == 'overexposed': env['observations']['top']['quality']['condition'] = 'OVEREXPOSED'
    if fault == 'run': env['run_id'] = ''
    if fault == 'future': env['recorded_ns'] = now+1_000_000_000
    if fault == 'pending': env['environment']['front']['pending'] = 'UNDEREXPOSED'
    with pytest.raises(ValueError):
        module.validate_environment(env, profile(), now_ns=now)


def test_same_fresh_waiting_frame_is_acceptable_without_counting_another_frame(module):
    sample = Backend().observe(); env = sample['environment']
    env['photometric_ready'] = False
    for role in ('top', 'front'): env['environment'][role]['state'] = 'WAITING_FRAME'
    module.validate_environment(env, profile(), now_ns=sample['time_ns'])
