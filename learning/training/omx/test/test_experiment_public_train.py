"""Public research remains source-bound and uses the existing owned lifecycle."""
import copy
import hashlib
import io
import json
import sys
from types import SimpleNamespace
import uuid
import zipfile

import pytest

from test_experiment_center import center
import experiment_public_train as job
import experiment_public_source as source
from experiment_io import write_json


def submission():
    return dict(request_id=str(uuid.uuid4()), repo_id=source.REPO, revision=source.REVISION,
                steps=2, batch_size=1, confirmed_source=True)


@pytest.mark.parametrize('change', [dict(path='/tmp/source'), dict(python='python'), dict(token='secret'),
    dict(method='hilserl'), dict(confirmed_source=False), dict(revision='main'), dict(repo_id='other/data'),
    dict(steps=True), dict(steps=0), dict(batch_size=9)])
def test_admission_is_a_closed_confirmed_recipe(change):
    with pytest.raises(ValueError):
        job.check_request(dict(submission(), **change))


@pytest.mark.parametrize('name', ['../data.parquet', '/meta/info.json', 'meta/../info.json',
    'meta\\info.json', 'C:/info.json', 'code.py', 'videos/other/chunk-000/file-000.mp4'])
def test_download_paths_are_bounded_and_never_remote_code(name):
    with pytest.raises(ValueError):
        source.allowed(name)


def test_source_layout_and_public_credentials_are_explicit(monkeypatch):
    monkeypatch.setenv('HF_TOKEN', 'must-not-pass')
    monkeypatch.setenv('HUGGING_FACE_HUB_TOKEN', 'must-not-pass')
    assert 'HF_TOKEN' not in job.public_environment()
    assert 'HUGGING_FACE_HUB_TOKEN' not in job.public_environment()
    assert job.public_environment()['HF_HUB_DISABLE_IMPLICIT_TOKEN'] == '1'
    info = dict(codebase_version='v3.0', robot_type='so100', total_episodes=50, fps=30,
        features={key: dict(names=source.NAMES[:], shape=[6], dtype='float32')
                  for key in ('action', 'observation.state')})
    info['features'].update({key: dict(shape=[480, 640, 3]) for key in source.CAMERAS})
    assert source.check_info(info) == info
    changed = copy.deepcopy(info)
    changed['features']['action']['names'][0] = 'omx_joint_1'
    with pytest.raises(ValueError):
        source.check_info(changed)


@pytest.mark.parametrize('fault', ['budget', 'path', 'hash'])
def test_download_checks_tree_budget_path_and_actual_bytes(tmp_path, monkeypatch, fault):
    raw = b'fixed public source bytes'
    entry = SimpleNamespace(path='README.md', size=len(raw), lfs=None,
        blob_id=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest())
    if fault == 'budget':
        entry.size = source.LIMIT+1
    elif fault == 'path':
        entry.path = '../escape.py'
    else:
        entry.blob_id = '0'*40
    class API:
        def __init__(self, token):
            assert token is False
        def list_repo_tree(self, repo, **kwargs):
            assert repo == source.REPO and kwargs['revision'] == source.REVISION and kwargs['token'] is False
            return [entry]
    downloads = []
    def fetch(repo, name, **kwargs):
        downloads.append(name)
        assert kwargs['token'] is False and kwargs['revision'] == source.REVISION
        path = kwargs['local_dir']/name
        path.write_bytes(raw)
        return str(path)
    monkeypatch.setitem(sys.modules, 'huggingface_hub', SimpleNamespace(HfApi=API, hf_hub_download=fetch))
    monkeypatch.setattr(source, 'probe', source.descriptor)
    with pytest.raises(ValueError):
        source.download(tmp_path/'source')
    assert downloads == (['README.md'] if fault == 'hash' else [])
    assert not (tmp_path/'escape.py').exists()


def test_owned_launch_retry_busy_stop_restart_and_source_revalidation(tmp_path, monkeypatch):
    import experiment_center
    c = center(tmp_path, monkeypatch)
    c.methods['act']['available'] = True
    probes = []
    def describe():
        probes.append(True)
        return dict(source.descriptor(), available=True, reason=None)
    monkeypatch.setattr(c, 'public_source', describe)
    proof = dict(pid=12345, start='77', boot='test-boot')
    monkeypatch.setattr(job, 'process_stamp', lambda *args: proof)
    monkeypatch.setattr(experiment_center, 'process_stamp', lambda *args: proof)
    calls, signals = [], []
    def popen(command, **kwargs):
        calls.append(command)
        assert kwargs['env']['HF_HUB_DISABLE_IMPLICIT_TOKEN'] == '1'
        assert 'HF_TOKEN' not in kwargs['env']
        return SimpleNamespace(pid=12345, poll=lambda: None)
    monkeypatch.setattr(experiment_center.subprocess, 'Popen', popen)
    monkeypatch.setattr(experiment_center.os, 'killpg', lambda *args: signals.append(args))
    body = submission()
    row = c.start_public(body)
    assert row['status'] == 'running' and calls[0][1].endswith('experiment_public_train.py')
    assert row['source']['robot_type'] == 'so100' and 'learning_task' not in row
    assert c.start_public(body)['id'] == row['id'] and len(calls) == len(probes) == 1
    with pytest.raises(ValueError, match='different inputs'):
        c.start_public(dict(body, steps=3))
    with pytest.raises(ValueError, match='one owned'):
        c.start_public(dict(body, request_id=str(uuid.uuid4())))
    monkeypatch.setattr(experiment_center.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout=b'False'))
    restarted = center(tmp_path, monkeypatch)
    assert restarted.snapshot()['runs'][0]['id'] == row['id']
    assert restarted.stop({'id': row['id']})['status'] == 'stopping'
    assert signals[0][0] == proof['pid']
    monkeypatch.setattr(experiment_center, 'process_stamp', lambda *args: None)
    assert restarted.snapshot()['runs'][0]['status'] == 'cancelled'


def test_worker_rechecks_source_preserves_evidence_and_rejects_archive_tamper(tmp_path, monkeypatch):
    body = submission()
    request = job.check_request(body)
    write_json(tmp_path/'request.json', request)
    output = tmp_path/'output'
    probes = []
    def download(root):
        probes.append(True)
        root.mkdir()
        return dict(source.descriptor(), files={'meta/info.json': 'a'*64})
    def derive(root, destination):
        for name in ('dataset', 'train-dataset'):
            (destination/name).mkdir()
            (destination/name/'data.parquet').write_bytes(b'original raw action and state')
        return dict(reader_verified=True, files=source.hashes(destination/'dataset'),
                    train_files=source.hashes(destination/'train-dataset'))
    def train(destination, checked):
        assert checked == request
        model = destination/'trainer/checkpoints/last/pretrained_model'
        model.mkdir(parents=True)
        for name in ('config.json', 'model.safetensors', 'policy_preprocessor.json', 'policy_postprocessor.json'):
            (model/name).write_bytes(b'fixture model')
        write_json(destination/'evaluation.json', dict(model_reloaded_in_new_process=True,
            samples=128, units='dataset-native/unverified', physical_task_success=None))
        return source.hashes(model)
    monkeypatch.setattr(source, 'download', download)
    monkeypatch.setattr(source, 'derive', derive)
    monkeypatch.setattr(job, 'train', train)
    result = job.run(request, output)
    assert probes == [True] and result['evaluation']['model_reloaded_in_new_process']
    assert result['policy_activation'] is result['physical_learning_verified'] is False
    with zipfile.ZipFile(io.BytesIO(job.archive(output, result))) as zipped:
        assert zipped.read('model/model.safetensors') == b'fixture model'
        assert set(result['evidence_files']) <= set(zipped.namelist())
        assert b'prepared_root' not in zipped.read('source-request.json')
    for relative in ('source-request.json', 'source-manifest.json', 'provenance.json', 'evaluation.json',
                     'trainer/checkpoints/last/pretrained_model/model.safetensors'):
        path = output/relative
        before = path.read_bytes()
        path.write_bytes(b'changed')
        with pytest.raises((ValueError, json.JSONDecodeError)):
            job.archive(output, result)
        path.write_bytes(before)
    write_json(tmp_path/'request.json', job.check_request(dict(body, request_id=str(uuid.uuid4()))))
    with pytest.raises(ValueError, match='lineage'):
        job.archive(output, result)


def test_unavailable_source_never_launches(tmp_path, monkeypatch):
    c = center(tmp_path, monkeypatch)
    c.methods['act']['available'] = True
    monkeypatch.setattr(c, 'public_source', lambda: dict(available=False, reason='source changed'))
    with pytest.raises(ValueError, match='source changed'):
        c.start_public(submission())
    assert c.snapshot()['runs'] == []


def test_center_caches_only_successful_source_without_sharing_mutable_state(tmp_path, monkeypatch):
    c = center(tmp_path, monkeypatch)
    c.methods['act']['available'] = True
    failed = dict(source.descriptor(), available=False, reason='temporary metadata failure')
    success = dict(source.descriptor(), available=True, reason=None)
    responses, calls = [failed, success], []
    def describe(python):
        calls.append(python)
        return responses.pop(0)
    monkeypatch.setattr(job, 'describe', describe)
    assert c.public_source()['available'] is False
    public = c.public_source()
    assert public['available'] is True and len(calls) == 2
    public['recipe']['train_episodes'].clear()
    assert c.public_source()['recipe']['train_episodes'] == list(range(8))
    assert success['recipe']['train_episodes'] == list(range(8)) and len(calls) == 2
    c.methods['act']['available'] = False
    assert c.public_source()['available'] is False and len(calls) == 2
    c.methods['act']['available'] = True
    assert c.public_source()['available'] is True and len(calls) == 2
