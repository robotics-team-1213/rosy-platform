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
        (root / relative).write_bytes(bytes([100, 110, 120]) * 1024)
        images[role] = dict(path=relative, width=32, height=32, sha256=hashlib.sha256(
            (root / relative).read_bytes()).hexdigest(), source_stamp=1.)
    row = dict(frame_index=0, time_ns=start+1, joint_source_stamp=1., reference_source_stamp=1.,
               images=images, requested_target_rad=[0.] * 6,
               **{'observation.state': [0.] * 6, 'action': [0.] * 6})
    second = dict(row, frame_index=1, time_ns=start+2, joint_source_stamp=1.1, reference_source_stamp=1.1)
    (episode / 'samples.jsonl').write_text(json.dumps(row)+'\n'+json.dumps(second)+'\n', encoding='utf-8')
    event = dict(policy='omx-photometric-v3', run_id='run-1', profile_sha256='a'*64,
                 recorded_ns=start, motion_admitted=False, physical_acceptance=False,
                 photometric_ready=False, observations={}, environment={
                     role: dict(state='OBSERVING', condition=None, environment_epoch=0,
                                control_generation=0) for role in ('top', 'front')})
    (root / 'environment.jsonl').write_text(json.dumps(event)+'\n', encoding='utf-8')
    teacher = dict(schema='rosy.omx-collection-teacher.v1', steps=[dict(positions=[0.]*6, duration_s=.1)])
    (root/'teacher.json').write_text(json.dumps(teacher)+'\n')
    (root/'profile.json').write_text(json.dumps(dict(reach_tolerance_rad=[.01]*6))+'\n')
    cycle = session+'-cycle'
    command = cycle+'-0'
    events = [dict(kind='INTENT', command_id=command, cycle_id=cycle, step=teacher['steps'][0], time_ns=start),
              dict(kind='SUBMISSION', command_id=command, cycle_id=cycle,
                   decision=dict(accepted=True), time_ns=start+1),
              dict(kind='GOAL_ACCEPTED', command_id=command, goal_id='synthetic-goal', sequence=1,
                   observed_at_monotonic_s=1.),
              dict(kind='TERMINAL_RESULT', command_id=command, goal_id='synthetic-goal', sequence=2,
                   observed_at_monotonic_s=2., status=4, result_code=0),
              dict(kind='TERMINAL', command_id=command, cycle_id=cycle, time_ns=start+3,
                   result=dict(succeeded=True, source='native_follow_joint_trajectory')),
              dict(kind='REACHED', command_id=command, cycle_id=cycle, time_ns=start+4,
                   errors_rad=[0.]*6, tolerance_rad=[.01]*6)]
    (root/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
    manifest = dict(schema='rosy.omx-collection-session.v1', state='CLOSED', mode='hardware',
                    source_mode='scripted_teacher', session_id=session,
                    rig_revision='rig-1', calibration_revision='cal-1', teacher_sha256=hashlib.sha256(
                        json.dumps(teacher, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
                    fps=10, task='move block', camera_shapes={'top': [32,32,3], 'front': [32,32,3]},
                    body_units='normalized_-100_100', gripper_units='normalized_0_100',
                    stop=dict(hold_requested=True, terminal_observed=True, physical_stop_verified=False),
                    episodes=[dict(episode_index=0, cycle_id=session+'-cycle', start_ns=start,
                                   end_ns=start+10, run_id='run-1', profile_sha256='a'*64,
                                   complete=complete, frames=2, samples_path='episodes/000000/samples.jsonl',
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


def test_recorded_camera_models_are_hash_bound_raw_evidence(module, tmp_path):
    root = tmp_path / 'raw'
    manifest = raw_session(root)
    (root/'camera_info.jsonl').write_text(json.dumps(dict(time_ns=101, cameras={}))+'\n', encoding='utf-8')
    save_manifest(root, manifest)
    record = module.validate_session(root)
    assert 'camera_info.jsonl' in record['blobs']
    (root/'camera_info.jsonl').write_text('{}\n', encoding='utf-8')
    with pytest.raises(ValueError, match='hash'):
        module.validate_session(root)


@pytest.mark.parametrize('fault', ['hash', 'unlisted', 'traversal', 'rehearsal', 'incomplete',
                                  'units', 'frame', 'window', 'bounds', 'nan', 'image_size', 'environment', 'open'])
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
    elif fault == 'open': manifest['state'] = 'RUNNING'
    elif fault == 'environment': (root/'environment.jsonl').write_text('{}\n')
    elif fault == 'image_size': (root/'episodes/000000/top.rgb').write_bytes(b'x')
    else:
        lines = sample.read_text().splitlines()
        row = json.loads(lines[0])
        if fault == 'frame': row['frame_index'] = 1
        if fault == 'window': row['time_ns'] = 110
        if fault == 'bounds': row['action'][5] = -1
        if fault == 'nan': row['requested_target_rad'][0] = float('nan')
        sample.write_text(json.dumps(row)+'\n'+lines[1]+'\n')
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


def test_single_frame_complete_attempt_is_not_training_input(module, tmp_path):
    root = tmp_path/'raw'
    manifest = raw_session(root)
    sample = root/'episodes/000000/samples.jsonl'
    sample.write_text(sample.read_text().splitlines()[0]+'\n')
    manifest['episodes'][0]['frames'] = 1
    save_manifest(root, manifest)
    with pytest.raises(ValueError, match='two frames'):
        module.validate_session(root)


@pytest.mark.parametrize('fault', ['flipped_complete', 'teacher', 'submission', 'native_goal', 'native_result',
                                  'wrong_goal', 'sequence', 'clock', 'outer_terminal', 'stop', 'error',
                                  'extra_command', 'not_reached', 'no_reach', 'loosened_tolerance'])
def test_manifest_completion_cannot_upgrade_unverified_native_attempt(module, tmp_path, fault):
    root = tmp_path/'raw'
    manifest = raw_session(root)
    ledger = root/'events.jsonl'
    events = [json.loads(line) for line in ledger.read_text().splitlines()]
    if fault == 'flipped_complete':
        manifest['episodes'][0].update(complete=False, reason='aborted')
        events.append(dict(kind='ABORT', cycle_id=manifest['episodes'][0]['cycle_id'], reason='unsafe stop'))
    if fault == 'teacher': manifest['teacher_sha256'] = 'c'*64
    if fault == 'submission': events[1]['decision']['accepted'] = False
    if fault == 'native_goal': events.pop(2)
    if fault == 'native_result': events[3]['status'] = 6
    if fault == 'wrong_goal': events[3]['goal_id'] = 'different-goal'
    if fault == 'sequence': events[3]['sequence'] = 1
    if fault == 'clock': events[3]['observed_at_monotonic_s'] = float('inf')
    if fault == 'outer_terminal': events[4]['result']['source'] = 'synthetic-unverified'
    if fault == 'not_reached': events[5]['errors_rad'][5] = .02
    if fault == 'no_reach': events.pop(5)
    if fault == 'loosened_tolerance': events[5].update(errors_rad=[.1]*6, tolerance_rad=[.2]*6)
    if fault == 'stop': manifest['stop']['terminal_observed'] = False
    if fault == 'error': manifest['error'] = 'session fault'
    if fault == 'extra_command':
        events.append(dict(events[0], command_id=manifest['episodes'][0]['cycle_id']+'-1'))
    ledger.write_text(''.join(json.dumps(e)+'\n' for e in events))
    save_manifest(root, manifest)
    if fault == 'flipped_complete':
        # Change only unhashed manifest flags; byte-bound ABORT evidence remains untouched.
        manifest['episodes'][0].update(complete=True, reason='')
        (root/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        module.validate_session(root)


def test_real_lerobot_roundtrip_keeps_independent_capture_groups(module, tmp_path):
    pytest.importorskip('lerobot', reason='real LeRobot 0.4.4 roundtrip requires export environment')
    one, two, output = tmp_path/'one', tmp_path/'two', tmp_path/'dataset'
    raw_session(one)
    raw_session(two, session='session-2', start=200)
    receipt = module.prepare([two, one], output, 'rosy-test/intake')
    report = json.loads((output/'inspection.json').read_text())
    decisions = json.loads((output/'decisions.json').read_text())
    assert receipt['reader_verified'] is True
    assert receipt['episodes'] == [dict(episode_index=i, session_id=f'session-{i+1}',
                                       attempt_index=0, cycle_id=f'session-{i+1}-cycle') for i in range(2)]
    assert report['frame_count'] == 4
    assert report['reader_verified'] is True
    assert report['source_mode'] == 'scripted_teacher'
    assert report['environment_summary']['physical_acceptance'] is False
    assert all(e['outcome'] == 'unknown' and e['split'] == 'exclude' for e in decisions)
    assert (output/'rosy_provenance/session-000000/manifest.json').read_bytes() == (one/'manifest.json').read_bytes()
    from native_review import reviewed_splits
    with pytest.raises(ValueError, match='nonempty'):
        reviewed_splits(report, decisions)


def sealed_two_arm_recording(tmp_path, episodes=2, name='bench-two-arm-001', offset=0):
    """A real bi_omx_follower LeRobot v3 recording sealed by deploy/robot/omx/record_seal.py."""
    import numpy as np
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    names = [f'{arm}.{joint}' for arm in ('arm_a', 'arm_b') for joint in
             ('shoulder_pan.pos', 'shoulder_lift.pos', 'elbow_flex.pos',
              'wrist_flex.pos', 'wrist_roll.pos', 'gripper.pos')]
    features = {key: dict(dtype='float32', shape=(12,), names=names) for key in ('observation.state', 'action')}
    features['observation.images.top'] = dict(dtype='video', shape=(32, 32, 3), names=['height', 'width', 'channels'])
    root = tmp_path/'recordings'/name
    dataset = LeRobotDataset.create(repo_id='local/two-arm', fps=10, root=root, robot_type='bi_omx_follower',
                                    features=features, use_videos=True, video_backend='pyav', vcodec='h264',
                                    batch_encoding_size=1)
    try:
        for episode in range(episodes):
            for frame in range(3):
                dataset.add_frame({'observation.state': np.full(12, offset + episode + frame, np.float32),
                                   'action': np.full(12, offset + episode + frame + .5, np.float32),
                                   'observation.images.top': np.full((32, 32, 3), 40 * frame, np.uint8),
                                   'task': 'Hand the block over'})
            dataset.save_episode(parallel_encoding=False)
    finally:
        dataset.finalize()
    run = tmp_path/('run-' + name)
    run.mkdir()
    (run/'record.json').write_text(json.dumps(dict(dataset=dict(root=str(root)))))
    (run/'session.json').write_text(json.dumps(dict(config='record.json', teleop_only=False,
                                                    exit_code=0, safe_end=True)))
    calibration = tmp_path/'arm_a_follower.json'
    calibration.write_text('{"shoulder_pan": {"homing_offset": 0}}')
    spec = importlib.util.spec_from_file_location(
        'record_seal', Path(__file__).resolve().parents[4]/'deploy/robot/omx/record_seal.py')
    seal = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seal)
    seal.seal(run, name, tmp_path/'collections', rig_revision='bench-a-b-r1', calibrations=[calibration])
    return tmp_path/'collections'/name


def test_real_sealed_leader_recording_becomes_a_prepared_intake_with_one_session(module, tmp_path):
    pytest.importorskip('lerobot', reason='real LeRobot 0.4.4 roundtrip requires export environment')
    collection = sealed_two_arm_recording(tmp_path)
    output = tmp_path/'prepared'
    receipt = module.prepare_native([collection], output, 'local/two-arm')
    report = json.loads((output/'inspection.json').read_text())
    decisions = json.loads((output/'decisions.json').read_text())
    assert receipt['reader_verified'] is True and receipt['fixture_only'] is False
    assert report['robot_type'] == 'bi_omx_follower' and report['source_mode'] == 'leader_native'
    assert [(e['session_id'], e['cycle_id']) for e in report['episodes']] == [
        ('bench-two-arm-001', 'bench-two-arm-001-ep0000'), ('bench-two-arm-001', 'bench-two-arm-001-ep0001')]
    assert all(e['outcome'] == 'unknown' and e['split'] == 'exclude' for e in decisions)
    for name in ('intake-receipt.json', 'inspection.json', 'capture.json', 'environment.json', 'decisions.json'):
        assert (output/name).is_file()
    from native_capture import check_capture_groups
    with pytest.raises(ValueError, match='session_id crosses'):
        check_capture_groups(report['episodes'], [dict(split='train'), dict(split='eval')])


@pytest.mark.parametrize('fault', ['bytes', 'calibration', 'name'])
def test_altered_or_renamed_sealed_collection_is_refused_before_output(module, tmp_path, fault):
    pytest.importorskip('lerobot', reason='real LeRobot 0.4.4 roundtrip requires export environment')
    collection = sealed_two_arm_recording(tmp_path, episodes=1)
    if fault == 'bytes':
        (collection/'session.json').write_text('{}')
    elif fault == 'calibration':
        (collection/'calibration'/'arm_a_follower.json').write_text('{}')
    else:
        collection = collection.rename(collection.with_name('other-name'))
    with pytest.raises(ValueError):
        module.prepare_native([collection], tmp_path/'prepared', 'local/two-arm')
    assert not (tmp_path/'prepared').exists()


def test_two_real_recordings_reach_independent_splits_and_center_conversion(module, tmp_path):
    """Seal -> prepare-native -> human review -> sealed split -> Learning Center ACT arrays."""
    pytest.importorskip('lerobot', reason='real LeRobot 0.4.4 roundtrip requires export environment')
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]/'training'/'omx'))
    import experiment_native
    from native_review import split_reviewed
    first = sealed_two_arm_recording(tmp_path, name='bench-two-arm-001')
    second = sealed_two_arm_recording(tmp_path, episodes=1, name='bench-two-arm-002', offset=20)
    output = tmp_path/'prepared'
    module.prepare_native([first, second], output, 'local/two-arm')
    report = json.loads((output/'inspection.json').read_text())
    assert [e['session_id'] for e in report['episodes']] == ['bench-two-arm-001'] * 2 + ['bench-two-arm-002']
    decisions = json.loads((output/'decisions.json').read_text())
    for decision, split in zip(decisions, ('train', 'train', 'eval')):
        decision.update(split=split, outcome='success', object_result='moved_as_intended',
                        reviewer='bench operator', reason='watched full episode')
    splits = tmp_path/'splits'
    split_reviewed(output, report, decisions, splits)
    profile = dict(schema='rosy.omx.learning-profile/1', name='Two-arm bench', mode='independent',
                   task='Hand the block over',
                   arms=[dict(id=arm, joint_names=module.JOINTS[:], units='normalized_-100_100') for arm in ('arm_a', 'arm_b')],
                   cameras=[dict(id='top', input_key='observation.images.top', arm_id=None, role='top',
                                 source_identity='camera-by-id-top', placement='overhead-650mm',
                                 shape=[3, 32, 32], purposes=['policy', 'record'])])
    result = experiment_native.convert_native(splits, tmp_path/'center-upload', profile=profile)
    assert [row['split'] for row in result['episodes']] == ['train', 'train', 'eval']
    assert result['act_only'] is True and result['physical_acceptance'] is False


def teacher_fixture():
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import teacher_fixture as fixture
    return fixture


def test_sealed_scripted_teacher_collection_is_accepted_with_its_trajectory_hash(module, tmp_path):
    fixture = teacher_fixture()
    root = fixture.seal_teacher(tmp_path, 'arm-s-replay-1')
    manifest, digest = module._sealed_collection(root)
    assert manifest['source_mode'] == 'scripted_teacher' and module._hash(digest)
    assert manifest['teacher_sha256'] == hashlib.sha256((root/'teacher/trajectory.json').read_bytes()).hexdigest()
    assert 'teacher/trajectory.json' in manifest['files']


@pytest.mark.parametrize('fault', ['tampered', 'missing', 'uncovered', 'kind', 'schema', 'file', 'sha_format',
                                   'trajectory_schema', 'oversized', 'deep', 'long_list', 'not_object',
                                   'gap', 'bool', 'keys', 'unequal', 'episodes'])
def test_scripted_teacher_collection_without_its_exact_small_teacher_is_refused(module, tmp_path, fault):
    fixture = teacher_fixture()
    source = dict(oversized=dict(note='x'*5000), deep=dict(a=dict(b=dict(c=[1]))),
                  long_list=dict(dataset='local/omx-pick', method='dwell', episodes=list(range(65)), dwell_s=1),
                  not_object=[1, 2]).get(fault, fixture.SOURCE)
    teacher = dict(kind=dict(kind='leader'), schema=dict(schema='rosy.omx-replay-trajectory.v0'),
                   file=dict(file='teacher/other.json'),
                   gap=dict(segments=dict(A=[0, 3], reset=[4, 5], B=[5, 8])),
                   bool=dict(segments=dict(A=[0, True], reset=[1, 2], B=[2, 3])),
                   keys=dict(segments=dict(A=[0, 3], B=[3, 6])),
                   unequal=dict(segments=dict(A=[0, 3], reset=[3, 4], B=[4, 6]))).get(fault)
    root = fixture.seal_teacher(tmp_path, 'arm-s-replay-1', source=source, teacher=teacher)
    manifest = json.loads((root/'manifest.json').read_text())
    if fault == 'tampered':
        (root/'teacher/trajectory.json').write_text('{"schema": "rosy.omx-replay-trajectory.v1"}')
        fixture.write_manifest(root, manifest)  # files cover the new bytes; teacher_sha256 still names the old
    elif fault in ('missing', 'uncovered'):
        (root/'teacher/trajectory.json').unlink()
        if fault == 'uncovered':
            manifest = fixture.write_manifest(root, manifest)
    elif fault == 'sha_format':
        manifest['teacher_sha256'] = manifest['teacher_sha256'].upper()
    elif fault == 'trajectory_schema':
        (root/'teacher/trajectory.json').write_text(json.dumps(dict(schema='other', source=fixture.SOURCE)))
        manifest['teacher_sha256'] = hashlib.sha256((root/'teacher/trajectory.json').read_bytes()).hexdigest()
        fixture.write_manifest(root, manifest)
    elif fault == 'episodes':
        manifest['total_episodes'] = 3
    (root/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='teacher|replay'):
        module._sealed_collection(root)


PINNED_DRIVER = r'''
import json, pathlib, sys
source, tmp = map(pathlib.Path, sys.argv[1:])
sys.path[:0] = [str(source/'learning/curation/omx'), str(source/'learning/curation/omx/test')]
import collection_intake, teacher_fixture as fixture
from native_capture import bind_capture
recordings, collections = tmp/'recordings', tmp/'collections'
plain = fixture.seal_teacher(collections, 'arm-s-replay-1', fixture.teacher_dataset(recordings/'one'))
static = fixture.seal_teacher(collections, 'arm-s-replay-2', fixture.teacher_dataset(
    recordings/'two', marker={'static_episodes.json': json.dumps(dict(episodes=2, static=[1], threshold=1.0))}))
stopped = fixture.seal_teacher(collections, 'arm-s-replay-3', fixture.teacher_dataset(
    recordings/'three', marker={'DO_NOT_TRAIN.txt': 'leader never moved\n'}))
receipt = collection_intake.prepare_native([plain], tmp/'prepared', 'local/arm-s')
out = tmp/'prepared'
report = json.loads((out/'inspection.json').read_text())
capture = json.loads((out/'capture.json').read_text())
leaked = sorted(str(p.relative_to(out)) for p in out.rglob('*') if p.is_file()
                and fixture.REPLAY_PATH.encode() in p.read_bytes())
collection_intake.prepare_native([static], tmp/'prepared-static', 'local/arm-s-static')
static_report = json.loads((tmp/'prepared-static'/'inspection.json').read_text())
try:
    collection_intake.prepare_native([stopped], tmp/'prepared-stopped', 'local/arm-s-stopped')
    refused = None
except ValueError as exc:
    refused = str(exc)
print(json.dumps(dict(
    receipt_mode=receipt['source_mode'], reader=report['reader_verified'], mode=report['source_mode'],
    cycles=[(e['session_id'], e['cycle_id']) for e in report['episodes']],
    outcomes=sorted({(e['outcome'], e['split']) for e in report['episodes']}),
    teacher=capture['teacher_sha256'] == json.loads((plain/'manifest.json').read_text())['teacher_sha256'],
    teachers=[sorted(t) for t in capture['teachers']], leader_key='collection_manifest_sha256' in capture,
    in_report=report['capture_provenance'] == capture, leaked=leaked,
    static=static_report.get('excluded_episodes'), refused=refused,
    stopped_output=(tmp/'prepared-stopped').exists())))
'''


def test_pinned_real_scripted_teacher_collection_becomes_a_prepared_intake(tmp_path):
    """Real LeRobot 0.4.4 in the Learning center learner venv (see docs/solutions lerobot-lives-in...)."""
    import os
    import subprocess
    if os.environ.get('ROSY_RUN_PINNED_LEARNING') != '1':
        pytest.skip('explicit existing isolated learner environment required')
    python = Path.home()/'.local/share/rosy-learning-center/venv-cpu/bin/python'
    assert python.is_file(), 'existing pinned learner Python is unavailable'
    env = {key: os.environ[key] for key in ('HOME', 'PATH', 'USER', 'LOGNAME') if key in os.environ}
    env.update(HF_HUB_OFFLINE='1', HF_DATASETS_OFFLINE='1', CUDA_VISIBLE_DEVICES='', OMP_NUM_THREADS='2')
    result = subprocess.run([str(python), '-I', '-B', '-c', PINNED_DRIVER, str(Path(__file__).resolve().parents[4]),
                             str(tmp_path)], capture_output=True, text=True, env=env, timeout=300, check=False)
    assert result.returncode == 0, result.stderr[-4000:]
    proof = json.loads(result.stdout.splitlines()[-1])
    assert proof['receipt_mode'] == proof['mode'] == 'scripted_teacher' and proof['reader'] is True
    assert proof['cycles'] == [['arm-s-replay-1', 'arm-s-replay-1-ep0000'], ['arm-s-replay-1', 'arm-s-replay-1-ep0001']]
    assert proof['outcomes'] == [['unknown', 'exclude']]
    assert proof['teacher'] and proof['in_report'] and not proof['leader_key']
    assert proof['teachers'] == [['kind', 'segments', 'session_id', 'source', 'teacher_sha256']]
    assert proof['leaked'] == []
    assert [row['episode_index'] for row in proof['static']] == [1]
    assert 'DO_NOT_TRAIN' in proof['refused'] and proof['stopped_output'] is False
