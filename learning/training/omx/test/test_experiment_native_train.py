"""Saved human reviews drive native ACT without changing collection truth."""
import copy
import hashlib
import io
import json
import uuid
import zipfile

import pytest

from test_experiment_reviews import workspace, body
from test_experiment_export import prepared as export_prepared
from test_experiment_native import capture
from test_native_cycle import module, splits


def submission(workspace):
    reviews, root, row = workspace
    saved = reviews.save(body(reviews.describe(row)), row)
    review = reviews.for_export(saved['saved_review_id'], row)
    request = dict(prepared_id=row['id'], review_id=review['id'], steps=2,
                   batch_size=1, request_id=str(uuid.uuid4()))
    return root, row, request, review


def test_admission_pins_saved_review_and_source_without_relabeling(workspace):
    import experiment_native_train as job
    root, row, body, review = submission(workspace)
    before = (root/'decisions.json').read_bytes()
    request, fields = job.prepare_request(body, row, review=review)
    assert request['review'] == review
    assert request['prepared_root'] == str(root)
    assert fields['execution_mode'] == 'native_train'
    assert fields['review_id'] == review['id']
    assert fields['method'] == 'act'
    assert (root/'decisions.json').read_bytes() == before


@pytest.mark.parametrize('fault', ['fixture', 'no_review', 'wrong_review', 'budget', 'path'])
def test_invalid_submission_never_admits_training(workspace, fault):
    import experiment_native_train as job
    root, row, body, review = submission(workspace)
    if fault == 'fixture':
        (root/'intake-receipt.json').write_text(json.dumps(dict(reader_verified=True, fixture_only=True)))
    elif fault == 'no_review':
        review = None
    elif fault == 'wrong_review':
        body['review_id'] = str(uuid.uuid4())
    elif fault == 'budget':
        body['steps'] = True
    else:
        body['path'] = str(root)
    with pytest.raises(ValueError):
        job.prepare_request(body, row, review=review)


def test_saved_segments_have_exact_version_and_independent_splits(workspace):
    import experiment_native_train as job
    import native_segments
    reviews, root, row = workspace
    source = reviews.source(row)
    segments = []
    for episode, split in zip(source['inspection']['episodes'], ['train', 'eval', 'exclude']):
        segments.append({**{k: episode[k] for k in ('episode_index', 'content_sha256', 'frames', 'session_id', 'cycle_id')},
                         'start_frame': 0, 'end_frame': episode['frames'], 'object': 'block',
                         'intervention': False, 'outcome': 'success', 'reviewer': 'operator',
                         'reason': 'Observed successful transfer', 'split': split})
    saved = dict(version=3, document=native_segments.selection(source['inspection'], segments))
    body = dict(prepared_id=row['id'], segment_version=3, steps=2, batch_size=1, request_id=str(uuid.uuid4()))
    request, fields = job.prepare_request(body, row, segments=saved)
    assert request['segments'] == saved and fields['segment_version'] == 3
    for invalid in [dict(saved, version=2), dict(saved, document=None)]:
        with pytest.raises(ValueError):
            job.prepare_request(body, row, segments=invalid)


def test_changed_source_or_snapshot_refuses_before_split_or_train(workspace, tmp_path, monkeypatch):
    import experiment_native_train as job
    root, row, body, review = submission(workspace)
    request, _ = job.prepare_request(body, row, review=review)
    monkeypatch.setattr(job.cycle, 'run_cycle', lambda *a, **k: pytest.fail('changed inputs trained'))
    tampered = copy.deepcopy(request)
    tampered['review']['decisions'][0]['reason'] = 'changed'
    with pytest.raises(ValueError):
        job.run(tampered, tmp_path/'tampered-review')
    (root/'environment.json').write_text('{"changed":true}')
    with pytest.raises(ValueError):
        job.run(request, tmp_path/'tampered-source')


@pytest.mark.parametrize('task_bound', [False, True])
def test_worker_retains_reload_evaluation_and_hash_verified_download(workspace, tmp_path, monkeypatch, task_submission, task_bound):
    import experiment_native_train as job
    root, row, body, review = submission(workspace)
    request, _ = job.prepare_request(body, row, review=review)
    if task_bound:
        root, row, body, review, tasks = task_submission
        request, _ = job.prepare_request(body, row, review=review, tasks=tasks, host_id='model')
    original = (root/'decisions.json').read_bytes()
    def split(source, report, decisions, output):
        assert source == root and decisions == review['decisions']
        output.mkdir()
        (output/'split-receipt.json').write_text('{}')
    def train(splits, output, **budgets):
        assert budgets == dict(steps=2, batch_size=1, device='cpu')
        model = output/'trainer/checkpoints/last/pretrained_model'
        model.mkdir(parents=True)
        for name in ['config.json', 'model.safetensors', 'policy_preprocessor.json', 'policy_postprocessor.json']:
            (model/name).write_bytes(b'fixture artifact')
        result = dict(artifact_files=job.cycle._artifact_files(model),
                      evaluation=dict(model_reloaded_in_new_process=True, samples=3, physical_task_success=None))
        (output/'cycle-receipt.json').write_text(json.dumps(result))
        (output/'evaluation.json').write_text(json.dumps(result['evaluation']))
        return result
    monkeypatch.setattr(job.cycle.native, 'split_reviewed', split)
    monkeypatch.setattr(job.cycle, 'run_cycle', train)
    output = tmp_path/'run'
    result = job.run(request, output)
    assert result['evaluation']['model_reloaded_in_new_process'] is True
    if task_bound:
        assert result['learning_task'] == request['learning_task']
        changed = copy.deepcopy(result['learning_task'])
        changed['task_id'] = str(uuid.uuid4())
        for row_binding in (changed, None):
            with pytest.raises(ValueError):
                job.archive(output, result, learning_task=row_binding)
    assert result['physical_learning_verified'] is result['policy_activation'] is False
    assert (root/'decisions.json').read_bytes() == original
    with zipfile.ZipFile(io.BytesIO(job.archive(output, result))) as archive:
        assert archive.read('model/model.safetensors') == b'fixture artifact'
        if task_bound:
            assert json.loads(archive.read('source-request.json'))['learning_task'] == result['learning_task']
            assert json.loads(archive.read('result.json'))['learning_task'] == result['learning_task']
        assert 'source-request.json' in archive.namelist()
        assert 'split-receipt.json' in archive.namelist()
    for relative in ['source-request.json', 'splits/split-receipt.json', 'training/cycle-receipt.json',
                     'training/evaluation.json', 'training/trainer/checkpoints/last/pretrained_model/model.safetensors']:
        path = output/relative
        before = path.read_bytes()
        path.write_bytes(b'changed')
        with pytest.raises(ValueError):
            job.archive(output, result)
        path.write_bytes(before)


@pytest.mark.parametrize('task_bound', [False, True])
def test_owned_launch_retry_busy_cancel_and_restart(workspace, tmp_path, monkeypatch, task_submission, task_bound):
    import experiment_native_train as job
    import experiment_center
    from types import SimpleNamespace
    from test_experiment_center import center
    _, prepared, body, _ = submission(workspace)
    c = center(tmp_path, monkeypatch)
    c.methods['act']['available'] = True
    if task_bound:
        _, prepared, body, _, c.tasks = task_submission
        c.host_id = 'model'
    proof = dict(pid=12345, start='77', boot='test-boot')
    monkeypatch.setattr(job, 'process_stamp', lambda *args: proof)
    monkeypatch.setattr(experiment_center, 'process_stamp', lambda *args: proof)
    calls, signals = [], []
    def popen(command, **kwargs):
        with c.connect() as db:
            stored = json.loads(db.execute('SELECT document FROM runs').fetchone()[0])
        assert stored['status'] == 'launching'
        calls.append(command)
        return SimpleNamespace(pid=12345, poll=lambda: None)
    monkeypatch.setattr(experiment_center.subprocess, 'Popen', popen)
    monkeypatch.setattr(experiment_center.os, 'killpg', lambda *args: signals.append(args))
    run = c.start_native(body, prepared)
    assert run['status'] == 'running' and calls[0][1].endswith('experiment_native_train.py')
    if task_bound:
        assert run['learning_task']['task_id'] == body['task_id']
        request = json.loads((c.root/'runs'/run['id']/'request.json').read_bytes())
        assert request['learning_task'] == run['learning_task']
    assert c.start_native(body, prepared)['id'] == run['id'] and len(calls) == 1
    with pytest.raises(ValueError, match='different inputs'):
        c.start_native(dict(body, steps=3), prepared)
    with pytest.raises(ValueError, match='one owned'):
        c.start_native(dict(body, request_id=str(uuid.uuid4())), prepared)
    monkeypatch.setattr(experiment_center.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout=b'False'))
    restarted = center(tmp_path, monkeypatch)
    assert restarted.snapshot()['runs'][0]['id'] == run['id']
    assert restarted.stop({'id': run['id']})['status'] == 'stopping'
    assert signals[0][0] == proof['pid']


def test_large_native_request_reaches_review_validation_and_keeps_error_receipt(workspace, tmp_path):
    import experiment_native_train as job
    from experiment_reviews import canonical
    _, row, body, review = submission(workspace)
    request, _ = job.prepare_request(body, row, review=review)
    request['review']['decisions'] *= 2000
    request['review']['sha256'] = hashlib.sha256(canonical(request['review']['decisions'])).hexdigest()
    path, output = tmp_path/'large-request.json', tmp_path/'refused'
    path.write_bytes(canonical(request))
    assert path.stat().st_size > 1024*1024
    with pytest.raises(ValueError, match='cover every episode'):
        job.main(['--request', str(path), '--out', str(output)])
    assert json.loads((output/'error.json').read_bytes())['status'] == 'failed'


def test_oversized_request_is_refused_during_admission(workspace, monkeypatch):
    import experiment_native_train as job
    _, row, body, review = submission(workspace)
    monkeypatch.setattr(job, 'REQUEST_LIMIT', 256)
    with pytest.raises(ValueError, match='request exceeds'):
        job.prepare_request(body, row, review=review)


PINNED_DRIVER = r'''
import io, json, pathlib, sqlite3, sys, time, uuid, zipfile
source, tmp = map(pathlib.Path, sys.argv[1:3])
steps = int(sys.argv[3])
sys.path[:0] = [str(source/'learning/training/omx'), str(source/'learning/curation/omx'),
                str(source/'learning/curation/omx/test'), str(source/'learning/curation/perception')]
import teacher_fixture as fixture
import collection_intake, experiment_native_train as job, native_segments
from experiment_center import Center
from learning_tasks import Tasks
collections = [fixture.seal_teacher(tmp/'collections', 'synthetic-session-'+str(i),
                fixture.teacher_dataset(tmp/'recordings'/str(i))) for i in range(2)]
prepared = tmp/'prepared'
collection_intake.prepare_native(collections, prepared, 'local/synthetic-native-pipeline', **fixture.OPERATOR)
row = dict(id=uuid.uuid4().hex, kind='omx', path=str(prepared), name='SYNTHETIC NUMERICAL TEST ONLY')
c = Center(dict(schema='rosy.omx.center-config/1', root=str(tmp/'center'), host_id='model',
                python=dict(act=sys.executable, hilserl=sys.executable)))
project = 'synthetic-native-pipeline'
actor = {'user_id': 'synthetic-test'}
c.bind_workspace(project)
c.tasks = Tasks(tmp/'tasks.sqlite', project)
info = json.loads((prepared/'meta/info.json').read_bytes())
assert set(key for key in info['features'] if key.startswith('observation.images.')) == {'observation.images.top'}
assert job.cycle.native.joint_layout(info) == job.cycle.native.JOINTS
height, width, channels = info['features']['observation.images.top']['shape']
assert channels == 3
profile = c.profiles.save(dict(request_id=str(uuid.uuid4()), profile=dict(
    schema='rosy.omx.learning-profile/1', name='SYNTHETIC NUMERICAL SETUP ONLY',
    mode='independent', task='Synthetic transfer',
    arms=[dict(id='follower_1', joint_names=job.cycle.native.JOINTS[:], units='normalized_-100_100')],
    cameras=[dict(id='top', input_key='observation.images.top', arm_id=None, role='top',
        source_identity='synthetic-camera-top', placement='synthetic-overhead',
        shape=[3, height, width], purposes=['policy', 'record'])])), actor)
robot = c.tasks.robot(dict(request_id=str(uuid.uuid4()), name='SYNTHETIC ROBOT ONLY', kind='omx',
    model_revision='synthetic-fixture-r1', device_id='synthetic-device'), actor)
task = c.tasks.task(dict(request_id=str(uuid.uuid4()), name='SYNTHETIC NUMERICAL TASK ONLY',
    objective='Synthetic transfer', success='Synthetic transfer completed', failure='Synthetic transfer failed',
    reset='Synthetic reset', mode='independent', adapter='omx', profile_id=profile['id'],
    participants=[dict(robot_id=robot['id'], component_id='follower_1', role='transfer')]), actor, profile)
view = c.review(row)
c.tasks.bind_native(task['id'], row['id'], view['source_revision'], profile['revision'],
    ['follower_1'], actor, request_id=str(uuid.uuid4()))
expected = c.tasks.resolve_native(task['id'], row['id'], view['source_revision'], profile['revision'],
    ['follower_1'], 'model')
before = (prepared/'decisions.json').read_bytes()
decisions = [dict(episode_index=e['episode_index'], outcome='success' if i in (0,3) else 'unknown',
    split='train' if i==0 else 'eval' if i==3 else 'exclude', object_result='unknown',
    reason='SYNTHETIC TEST LABEL ONLY') for i,e in enumerate(view['inspection']['episodes'])]
saved = c.save_review(dict(prepared_id=row['id'], source_revision=view['source_revision'],
    decisions=decisions, reviewer='SYNTHETIC TEST ONLY', confirmed=True, request_id=str(uuid.uuid4())), row)
proof=[]
for mode in ['episodes','segments']:
    body = dict(prepared_id=row['id'], task_id=task['id'], compute_host='model',
                steps=steps, batch_size=1, request_id=str(uuid.uuid4()))
    segments=None
    if mode=='episodes':
        body['review_id']=saved['saved_review_id']
    else:
        report=json.loads((prepared/'inspection.json').read_text())
        rows=[]
        for i in (0,3):
            episode=report['episodes'][i]
            rows.append(dict(episode, start_frame=0, end_frame=episode['frames'], object='synthetic block',
                intervention=False, outcome='success', reviewer='SYNTHETIC TEST ONLY',
                reason='SYNTHETIC TEST LABEL ONLY', split='train' if i==0 else 'eval'))
            rows[-1]={key:value for key,value in rows[-1].items() if key in {
                'episode_index','content_sha256','frames','session_id','cycle_id','start_frame','end_frame',
                'object','intervention','outcome','reviewer','reason','split'}}
        segments=dict(version=1,document=native_segments.selection(report,rows))
        body['segment_version']=1
    run=c.start_native(body,row,segments)
    assert c.start_native(body,row,segments)['id']==run['id']
    request=json.loads((c.root/'runs'/run['id']/'request.json').read_bytes())
    assert request['learning_task'] == run['learning_task'] == expected
    assert request['prepared_id'] == expected['prepared_id'] == row['id']
    assert request['source_revision'] == expected['source_revision'] == view['source_revision']
    deadline=time.monotonic()+240
    while time.monotonic()<deadline:
        current=next(r for r in c.snapshot()['runs'] if r['id']==run['id'])
        if current['status'] not in ('launching','running','stopping'):break
        time.sleep(.5)
    assert current['status']=='succeeded', current
    result=current['result']
    assert current['learning_task'] == result['learning_task'] == request['learning_task'] == expected
    assert result['learning_task']['task_id'] == task['id']
    assert result['evaluation']['model_reloaded_in_new_process'] is True
    assert result['evaluation']['samples']==3
    assert result['physical_learning_verified'] is result['policy_activation'] is False
    download=c.artifact(run['id'])
    (tmp/(mode+'.zip')).write_bytes(download)
    with zipfile.ZipFile(io.BytesIO(download)) as archive:
        assert archive.read('model/model.safetensors')
        assert json.loads(archive.read('source-request.json'))['learning_task'] == expected
        assert json.loads(archive.read('result.json'))['learning_task'] == expected
    assert (prepared/'decisions.json').read_bytes()==before
    proof.append(dict(mode=mode,run_id=run['id'],task_id=task['id'],source_revision=view['source_revision'],steps=steps,policy_revision=result['policy_revision'],artifact=str(tmp/(mode+'.zip')),
        evaluation=result['evaluation'],physical_learning_verified=False))
print(json.dumps(dict(source='synthetic_smoke',task_id=task['id'],runs=proof)))
'''


def test_pinned_numerical_native_pipeline_trains_reloads_and_evaluates(tmp_path):
    import os
    from pathlib import Path
    import subprocess
    if os.environ.get('ROSY_RUN_PINNED_LEARNING') != '1':
        pytest.skip('explicit existing isolated learner environment required')
    python = Path.home()/'.local/share/rosy-learning-center/venv-cpu/bin/python'
    assert python.is_file(), 'existing pinned learner Python is unavailable'
    scenario = Path(os.environ.get('ROSY_NATIVE_PIPELINE_EVIDENCE', str(tmp_path)))
    if scenario != tmp_path:
        scenario.mkdir(parents=True, exist_ok=False)
    steps = int(os.environ.get('ROSY_NATIVE_PIPELINE_STEPS', '2'))
    assert 1 <= steps <= 100000
    env = {key: os.environ[key] for key in ('HOME', 'PATH', 'USER', 'LOGNAME') if key in os.environ}
    env.update(HF_HUB_OFFLINE='1', HF_DATASETS_OFFLINE='1', CUDA_VISIBLE_DEVICES='', OMP_NUM_THREADS='2')
    completed = subprocess.run([str(python), '-I', '-B', '-c', PINNED_DRIVER,
        str(Path(__file__).resolve().parents[4]), str(scenario), str(steps)],
        capture_output=True, text=True, env=env, timeout=540, check=False)
    assert completed.returncode == 0, completed.stdout[-1500:] + completed.stderr[-5000:]
    proof = json.loads(completed.stdout.splitlines()[-1])
    assert proof['source'] == 'synthetic_smoke'
    assert str(uuid.UUID(proof['task_id'])) == proof['task_id']
    assert all(run['task_id'] == proof['task_id'] for run in proof['runs'])
    assert [run['mode'] for run in proof['runs']] == ['episodes', 'segments']
    print(json.dumps(proof))


@pytest.fixture
def task_submission(workspace, tmp_path, capture):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'learning/curation/perception'))
    from learning_tasks import Tasks
    from experiment_profile import profile_revision
    root, row, body, review = submission(workspace)
    store = Tasks(tmp_path / 'tasks.sqlite', 'project-a')
    robot = store.robot(dict(request_id=str(uuid.uuid4()), name='Fixture arm', kind='omx',
        model_revision='fixture-r1', device_id='fixture-device'), {'user_id': 'alice'})
    content = capture[2]
    profile = dict(id=str(uuid.uuid4()), revision=profile_revision(content), profile=content)
    task = store.task(dict(request_id=str(uuid.uuid4()), name='Fixture task', objective='Transfer',
        success='Transferred', failure='Dropped', reset='Return', mode='independent',
        participants=[dict(robot_id=robot['id'], component_id='follower_1', role='transfer')],
        adapter='omx', profile_id=profile['id']), {'user_id': 'alice'}, profile)
    store.bind_native(task['id'], row['id'], review['source_revision'], profile['revision'],
                      ['follower_1'], {'user_id': 'alice'}, request_id=str(uuid.uuid4()))
    return root, row, dict(body, task_id=task['id'], compute_host='model'), review, store


def test_task_bound_native_admission_keeps_exact_native_lineage(task_submission):
    import experiment_native_train as job
    root, row, body, review, tasks = task_submission
    request, fields = job.prepare_request(body, row, review=review, tasks=tasks, host_id='model')
    binding = request['learning_task']
    assert fields['learning_task'] == binding
    assert binding['task_id'] == body['task_id'] and binding['prepared_id'] == row['id']
    assert binding['source_revision'] == request['source_revision']
    assert binding['compute_host'] == 'model' and binding['component_ids'] == ['follower_1']
    assert 'dataset_id' not in binding


@pytest.mark.parametrize('fault', ['missing_task', 'missing_host', 'host', 'unbound', 'joint', 'camera'])
def test_task_bound_native_admission_refuses_before_worker_reservation(task_submission, fault):
    import experiment_native_train as job
    root, row, body, review, tasks = task_submission
    host = 'model'
    if fault == 'missing_task':
        body.pop('task_id')
    elif fault == 'missing_host':
        body.pop('compute_host')
    elif fault == 'host':
        host = 'ai'
    elif fault == 'unbound':
        body['task_id'] = str(uuid.uuid4())
    else:
        metadata = json.loads((root/'meta/info.json').read_bytes())
        if fault == 'joint':
            metadata['features']['action']['names'].reverse()
        else:
            metadata['features']['observation.images.top']['shape'] = [9, 9, 3]
        (root/'meta/info.json').write_text(json.dumps(metadata))
        import experiment_export
        inspection = json.loads((root/'inspection.json').read_bytes())
        inspection['files'] = experiment_export.native.dataset_files(root)
        (root/'inspection.json').write_text(json.dumps(inspection))
    with pytest.raises(ValueError):
        job.prepare_request(body, row, review=review, tasks=tasks, host_id=host)


def test_native_worker_rejects_task_snapshot_tampering_before_training(task_submission, tmp_path, monkeypatch):
    import experiment_native_train as job
    root, row, body, review, tasks = task_submission
    request, _ = job.prepare_request(body, row, review=review, tasks=tasks, host_id='model')
    monkeypatch.setattr(job.cycle, 'run_cycle', lambda *a, **k: pytest.fail('tampered task trained'))
    for field, value in [('task_revision', 'b'*64), ('source_revision', 'b'*64),
                         ('component_ids', ['other']), ('robots', [])]:
        changed = copy.deepcopy(request)
        changed['learning_task'][field] = value
        with pytest.raises(ValueError):
            job.run(changed, tmp_path/field)
