"""Tomorrow's collection path must fail closed before and during a trajectory."""
import copy
import importlib.util
from pathlib import Path
import sys
import time
from types import SimpleNamespace

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
                task='fixture only', fps=10, max_image_age_s=.5, max_sample_gap_s=.6,
                max_state_age_s=.2, max_reference_age_s=.2, free_disk_bytes=1024, max_frame_jitter_s=.5,  # loaded remote runners (2026-10-19)
                camera_shapes={r: [2, 2, 3] for r in ('top', 'front')},
                joint_names=['joint'+str(i) for i in range(6)],
                normalization=[[-1., 1.]]*6, reach_tolerance_rad=[.01]*6, max_session_s=5.)


class Backend:
    mode = 'rehearsal'
    def __init__(self, fault=None):
        self.fault, self.commands, self.stops, self.n = fault, [], [], 0
        self.clock = time
    def observe(self):
        self.n += 1
        now = self.clock.time_ns()
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
        # no_motion: the controller reports success while the joints stay where they started.
        joints = [.1]*6 if self.commands and self.fault != 'no_motion' else [0.]*6
        return dict(environment=env, time_ns=now, observation_state=[0.]*6, action=[0.]*6, joint_positions=joints,
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
    return dict(schema='rosy.omx-collection-teacher.v1', steps=[dict(positions=[.1]*6, duration_s=.2)])


@pytest.fixture
def rehearsal_clock(module, monkeypatch):
    # Share simulated time between producer and consumer; real fsync latency is not fixture image age.
    clock_ns = [1_000_000_000]
    def now():
        clock_ns[0] += 1_000_000
        return clock_ns[0]
    def sleep(seconds):
        clock_ns[0] += int(seconds * 1e9)
    clock = SimpleNamespace(time_ns=now, monotonic=lambda: clock_ns[0] / 1e9, sleep=sleep)
    monkeypatch.setattr(module, 'time', clock)
    return clock


@pytest.mark.parametrize('storage_delay', [0, .6])
def test_rehearsal_records_windows_original_images_and_never_claims_hardware(module, tmp_path, monkeypatch, storage_delay, rehearsal_clock):
    original = module.RawCollection.environment
    receipts = 0
    def environment(store, receipt):
        nonlocal receipts
        receipts += 1
        if storage_delay and receipts == 2:
            time.sleep(storage_delay)
        return original(store, receipt)
    monkeypatch.setattr(module.RawCollection, 'environment', environment)
    backend = Backend()
    backend.clock = rehearsal_clock
    result = module.run_session(profile(), teacher(), tmp_path/'capture', backend)
    assert result['mode'] == 'rehearsal' and result['source_mode'] == 'simulation'
    assert result['episodes'][0]['complete'] is True
    assert result['episodes'][0]['frames'] >= 2
    assert result['episodes'][0]['start_ns'] < result['episodes'][0]['end_ns']
    assert result['episodes'][0]['outcome'] == 'unknown'
    assert backend.stops and len(backend.commands) == 1
    assert 'environment.jsonl' in result['files']
    assert all((tmp_path/'capture'/p).is_file() for p in result['files'])


@pytest.mark.parametrize('fault', ['dark', 'reject', 'generation', 'no_motion'])
def test_degradation_or_owner_rejection_stops_and_preserves_incomplete_attempt(module, tmp_path, fault):
    backend = Backend(fault)
    result = module.run_session(profile(), teacher(), tmp_path/fault, backend)
    assert result['episodes'][0]['complete'] is False
    assert result['episodes'][0]['reason']
    assert backend.stops and len(backend.commands) == 1
    assert (tmp_path/fault/'manifest.json').is_file()


def test_successful_terminal_without_reaching_the_target_holds_and_records_no_reach(module, tmp_path):
    backend = Backend('no_motion')
    result = module.run_session(profile(), teacher(), tmp_path/'still', backend)
    assert result['episodes'][0]['complete'] is False
    assert 'did not reach' in result['episodes'][0]['reason'] and backend.stops
    kinds = [line.split('"kind": "')[1].split('"')[0]
             for line in (tmp_path/'still'/'events.jsonl').read_text().splitlines() if '"kind": "' in line]
    assert 'TERMINAL' in kinds and 'REACHED' not in kinds and kinds[-1] == 'ABORT'


def test_reached_step_records_measured_errors(module, tmp_path, rehearsal_clock):
    backend = Backend()
    backend.clock = rehearsal_clock
    module.run_session(profile(), teacher(), tmp_path/'ok', backend)
    text = (tmp_path/'ok'/'events.jsonl').read_text()
    assert '"kind": "REACHED"' in text and '"errors_rad": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]' in text


@pytest.mark.parametrize('reach', [None, [], [.01]*5, [0.]*6, [.3]*6, [float('nan')]*6])
def test_profile_requires_a_measured_reach_tolerance(module, reach):
    value = profile()
    if reach is None:
        del value['reach_tolerance_rad']
    else:
        value['reach_tolerance_rad'] = reach
    with pytest.raises(ValueError, match='reach tolerance'):
        module.validate_profile(value, mode='rehearsal')


def test_step_smaller_than_its_tolerance_is_refused_before_dispatch(module, tmp_path):
    backend = Backend()
    small = dict(teacher(), steps=[dict(positions=[.005]*6, duration_s=.2)])
    result = module.run_session(profile(), small, tmp_path/'small', backend)
    assert result['episodes'][0]['complete'] is False and 'unprovable' in result['episodes'][0]['reason']
    assert backend.commands == [] and backend.stops


def test_reach_tolerance_is_bounded_by_the_joint_span(module):
    value = profile()
    value['normalization'] = [[-1., 1.]]*5+[[0., .5]]
    value['reach_tolerance_rad'] = [.01]*5+[.06]
    with pytest.raises(ValueError, match='reach tolerance'):
        module.validate_profile(value, mode='rehearsal')


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


def test_slow_intent_storage_cannot_dispatch_after_session_deadline(module, tmp_path, monkeypatch):
    config=profile();config['max_session_s']=.05
    plan=teacher();plan['steps'][0]['duration_s']=.01
    backend=Backend()
    original=module.append
    def slow(path,value):
        if value.get('kind')=='INTENT': time.sleep(.08)
        return original(path,value)
    monkeypatch.setattr(module,'append',slow)
    result=module.run_session(config,plan,tmp_path/'slow',backend)
    assert not backend.commands and backend.stops
    assert not result['episodes'][0]['complete']


def test_repolling_original_environment_does_not_inflate_raw_log(module,tmp_path):
    store=module.RawCollection(tmp_path/'log',profile(),'a'*64,'rehearsal')
    env=Backend().observe()['environment']
    store.environment(env);store.environment(copy.deepcopy(env))
    assert len((store.root/'environment.jsonl').read_text().splitlines())==1
    changed=copy.deepcopy(env);changed['photometric_ready']=False
    with pytest.raises(ValueError,match='changed'): store.environment(changed)


class IntrinsicsBackend(Backend):
    def observe(self):
        sample = super().observe()
        k = [1., 0., 1., 0., 1., 1., 0., 0., 1.] if self.n < 8 else [2., 0., 1., 0., 2., 1., 0., 0., 1.]
        sample['camera_info'] = {r: dict(frame_id=r, width=2, height=2, distortion_model='plumb_bob', d=[0.]*5,
                                         k=k, r=[1., 0., 0., 0., 1., 0., 0., 0., 1.], p=[0.]*12, binning=[0, 0])
                                 for r in ('top', 'front')}
        return sample


def test_published_camera_models_are_hashed_raw_evidence_only_when_changed(module, tmp_path, rehearsal_clock):
    import json
    backend = IntrinsicsBackend()
    backend.clock = rehearsal_clock
    result = module.run_session(profile(), teacher(), tmp_path/'capture', backend)
    assert result['episodes'][0]['complete'] is True and 'camera_info.jsonl' in result['files']
    rows = [json.loads(line) for line in (tmp_path/'capture/camera_info.jsonl').read_text().splitlines()]
    assert [row['cameras']['top']['k'][0] for row in rows] == [1., 2.]
    assert all(type(row['time_ns']) is int for row in rows)


def test_sessions_without_camera_info_keep_previous_raw_layout(module, tmp_path):
    result = module.run_session(profile(), teacher(), tmp_path/'capture', Backend())
    assert 'camera_info.jsonl' not in result['files']


@pytest.mark.parametrize('fault', ['missing', 'placeholder', 'rotation', 'far'])
def test_declared_camera_mounts_are_explicit_metres_and_unit_quaternions(module, fault):
    mount = dict(parent_frame='link0', translation_m=[.3, 0., .5], rotation_xyzw=[0., 0., 0., 1.],
                 method='tape measure from base origin')
    document = profile()
    document['camera_mounts'] = {r: dict(mount) for r in ('top', 'front')}
    module.validate_profile(document, mode='rehearsal')
    if fault == 'missing': del document['camera_mounts']['front']
    if fault == 'placeholder': document['camera_mounts']['top']['parent_frame'] = '<frame>'
    if fault == 'rotation': document['camera_mounts']['top']['rotation_xyzw'] = [0., 0., 0., 2.]
    if fault == 'far': document['camera_mounts']['top']['translation_m'] = [30., 0., 0.]
    with pytest.raises(ValueError, match='camera'):
        module.validate_profile(document, mode='rehearsal')
