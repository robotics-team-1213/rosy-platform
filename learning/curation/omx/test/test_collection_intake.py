"""Closed-record intake refuses altered evidence before creating training artifacts."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def module():
    path = Path(__file__).resolve().parents[1] / 'collection_intake.py'
    spec = importlib.util.spec_from_file_location('collection_intake', path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def raw_session(root, *, session='session-1', start=100, complete=True):
    root.mkdir()
    episode = root / 'episodes/000000'
    episode.mkdir(parents=True)
    images = {}
    for role in ('top', 'front'):
        relative = f'episodes/000000/{role}.rgb'
        (root / relative).write_bytes(bytes([100, 110, 120]) * 16)
        images[role] = dict(path=relative, width=4, height=4, sha256=hashlib.sha256(
            (root / relative).read_bytes()).hexdigest(), source_stamp=1.)
    row = dict(frame_index=0, time_ns=start+1, joint_source_stamp=1., reference_source_stamp=1.,
               images=images, requested_target_rad=[0.] * 6,
               **{'observation.state': [0.] * 6, 'action': [0.] * 6})
    (episode / 'samples.jsonl').write_text(json.dumps(row)+'\n', encoding='utf-8')
    event = dict(policy='omx-photometric-v3', run_id='run-1', profile_sha256='a'*64,
                 recorded_ns=start, motion_admitted=False, physical_acceptance=False,
                 photometric_ready=False, observations={}, environment={
                     role: dict(state='OBSERVING', condition=None, environment_epoch=0,
                                control_generation=0) for role in ('top', 'front')})
    (root / 'environment.jsonl').write_text(json.dumps(event)+'\n', encoding='utf-8')
    manifest = dict(schema='rosy.omx-collection-session.v1', mode='hardware',
                    source_mode='scripted_teacher', session_id=session,
                    rig_revision='rig-1', calibration_revision='cal-1', teacher_sha256='b'*64,
                    fps=10, task='move block', camera_shapes={'top': [4,4,3], 'front': [4,4,3]},
                    body_units='normalized_-100_100', gripper_units='normalized_0_100',
                    episodes=[dict(episode_index=0, cycle_id=session+'-cycle', start_ns=start,
                                   end_ns=start+10, run_id='run-1', profile_sha256='a'*64,
                                   complete=complete, frames=1, samples_path='episodes/000000/samples.jsonl',
                                   reason='', outcome='unknown')])
    save_manifest(root, manifest)
    return manifest


def save_manifest(root, manifest):
    manifest['files'] = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in root.rglob('*') if p.is_file() and p.name != 'manifest.json'}
    (root / 'manifest.json').write_text(json.dumps(manifest)+'\n', encoding='utf-8')


def test_complete_session_preserves_unknown_outcome_and_lineage(module, tmp_path):
    root = tmp_path / 'raw'
    raw_session(root)
    record = module.validate_session(root)
    assert record['manifest']['episodes'][0]['outcome'] == 'unknown'
    assert record['selected'][0]['episode_index'] == 0
    assert record['manifest_sha256'] == hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest()


@pytest.mark.parametrize('fault', ['hash', 'unlisted', 'traversal', 'rehearsal', 'incomplete',
                                  'units', 'frame', 'window', 'bounds', 'nan', 'image_size', 'environment'])
def test_invalid_sessions_refused_before_output(module, tmp_path, fault):
    root, output = tmp_path/'raw', tmp_path/'output'
    manifest = raw_session(root)
    sample = root / 'episodes/000000/samples.jsonl'
    if fault == 'hash': sample.write_text('{}\n')
    elif fault == 'unlisted': (root/'stray').write_text('unexpected')
    elif fault == 'traversal': manifest['episodes'][0]['samples_path'] = '../outside'
    elif fault == 'rehearsal': manifest.update(mode='rehearsal', source_mode='simulation')
    elif fault == 'incomplete': manifest['episodes'][0]['complete'] = False
    elif fault == 'units': manifest['body_units'] = 'radians'
    elif fault == 'environment': (root/'environment.jsonl').write_text('{}\n')
    elif fault == 'image_size': (root/'episodes/000000/top.rgb').write_bytes(b'x')
    else:
        row = json.loads(sample.read_text())
        if fault == 'frame': row['frame_index'] = 1
        if fault == 'window': row['time_ns'] = 110
        if fault == 'bounds': row['action'][5] = -1
        if fault == 'nan': row['requested_target_rad'][0] = float('nan')
        sample.write_text(json.dumps(row)+'\n')
    if fault not in ('hash', 'unlisted'): save_manifest(root, manifest)
    with pytest.raises(ValueError):
        module.prepare([root], output, 'test/omx')
    assert not output.exists()


def test_completed_only_is_explicit_and_retains_all_attempts(module, tmp_path):
    root = tmp_path/'raw'
    manifest = raw_session(root)
    failed = dict(manifest['episodes'][0], episode_index=1, cycle_id='failed', start_ns=111,
                  end_ns=120, complete=False, frames=0, samples_path='episodes/000001/samples.jsonl',
                  reason='stale reference')
    (root/'episodes/000001').mkdir()
    (root/'episodes/000001/samples.jsonl').write_bytes(b'')
    manifest['episodes'].append(failed)
    save_manifest(root, manifest)
    record = module.validate_session(root, completed_only=True)
    assert len(record['selected']) == 1
    assert len(record['manifest']['episodes']) == 2


def test_aggregate_overlap_and_incompatible_teacher_refused(module, tmp_path):
    one, two = tmp_path/'one', tmp_path/'two'
    raw_session(one)
    manifest = raw_session(two, session='session-2')
    with pytest.raises(ValueError, match='overlap'):
        module.prepare([one, two], tmp_path/'out', 'test/omx')
    manifest['episodes'][0].update(start_ns=200, end_ns=210)
    manifest['teacher_sha256'] = 'c'*64
    save_manifest(two, manifest)
    with pytest.raises(ValueError):
        module.prepare([one, two], tmp_path/'out', 'test/omx')
