"""Owned passive export jobs survive polling and preserve upload identities."""
import base64
import hashlib
import json
from types import SimpleNamespace
import uuid
import zipfile

import pytest

from learning_recording_jobs import Jobs
import learning_recording_jobs as module


def _setup(tmp_path, monkeypatch):
    python = tmp_path/'python'
    python.touch()
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0))
    process = SimpleNamespace(pid=123, returncode=None)
    process.poll = lambda: process.returncode
    process.wait = lambda **kwargs: process.returncode
    monkeypatch.setattr(module.subprocess, 'Popen', lambda *a, **k: process)
    monkeypatch.setattr(module, 'process_stamp', lambda pid, request=None: dict(pid=pid, start='1', boot='test'))
    # the 5 GiB export check read the host's real /tmp and failed on the site PC (2026-11-08)
    monkeypatch.setattr(module.shutil, 'disk_usage', lambda path: SimpleNamespace(free=1 << 40))
    jobs = Jobs(tmp_path/'recordings', str(python))
    session = dict(id=str(uuid.uuid4()), name='two wrist takes', profile_revision='a'*64,
                   export=None, study_id=None, profile=dict(cameras=[dict(
                       input_key='observation.images.arm_a_wrist', purposes=['policy'])]))
    episodes = [tmp_path/'episode-a', tmp_path/'episode-b']
    for path in episodes:
        path.mkdir()
    return jobs, session, episodes, process


def finished(jobs, session, process):
    job = jobs.root/session['id']/'exports'
    receipts = list(job.rglob('job.json'))
    assert len(receipts) == 1
    output = receipts[0].parent/'dataset'
    output.mkdir()
    raw = {'meta/info.json': json.dumps(dict(codebase_version='v3.0', features={
               'observation.images.arm_a_wrist': dict(dtype='image')})).encode(),
           'data/chunk-000/file-000.parquet': b'policy-only fixture',
           'source-provenance.json': b'{"content_integrity_only":true}'}
    for name, data in raw.items():
        path = output/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    receipt = dict(schema='rosy.passive-export-result/1', frames=4, episodes=2,
        profile_revision=session['profile_revision'], policy_camera_keys=['observation.images.arm_a_wrist'],
        reader_verified=True, physical_learning_verified=False,
        files={name: hashlib.sha256(data).hexdigest() for name, data in raw.items()})
    output.with_name('dataset.receipt.json').write_text(json.dumps(receipt))
    process.returncode = 0
    return output, raw


def test_no_exporter_is_unavailable_without_a_training_center(tmp_path):
    value = Jobs(tmp_path/'recordings', None).availability()
    assert value['available'] is False and value['reason']


def test_export_is_owned_async_and_recovered_from_receipts(tmp_path, monkeypatch):
    jobs, session, episodes, process = _setup(tmp_path, monkeypatch)
    request_id = str(uuid.uuid4())
    first = jobs.start(session, episodes, request_id)
    assert first['status'] in ('launching', 'running')
    assert jobs.start(session, episodes, request_id) == first
    assert not any(str(tmp_path) in str(v) for v in first.values())
    output, raw = finished(jobs, session, process)
    complete = jobs.refresh(session)
    assert complete['status'] == 'succeeded' and complete['artifact_url'].endswith(session['id'])
    restarted = Jobs(jobs.root, jobs.python)
    assert restarted.refresh(session) == complete
    with zipfile.ZipFile(restarted.artifact(session)) as archive:
        assert set(archive.namelist()) == set(raw)
        assert archive.read('data/chunk-000/file-000.parquet') == raw['data/chunk-000/file-000.parquet']
    (output/'data/chunk-000/file-000.parquet').write_bytes(b'changed')
    with pytest.raises(ValueError):
        restarted.artifact(session)


def test_export_rejects_changed_identity_and_incomplete_evidence(tmp_path, monkeypatch):
    jobs, session, episodes, process = _setup(tmp_path, monkeypatch)
    request_id = str(uuid.uuid4())
    jobs.start(session, episodes, request_id)
    with pytest.raises(ValueError):
        jobs.start(dict(session, profile_revision='b'*64), episodes, request_id)
    output, _ = finished(jobs, session, process)
    (output/'private-token.txt').write_text('must never enter archive')
    assert jobs.refresh(session)['status'] == 'failed'


def test_publish_uses_manifest_chunks_exact_actor_and_request_identity(tmp_path, monkeypatch):
    jobs, session, episodes, process = _setup(tmp_path, monkeypatch)
    jobs.start(session, episodes, str(uuid.uuid4()))
    _, raw = finished(jobs, session, process)
    jobs.refresh(session)
    calls = []
    uploads = {}
    class Studies:
        def create(self, body, actor):
            calls.append((body, actor))
            return dict(id=body['request_id'])
        def upload(self, body):
            data = base64.b64decode(body['data'])
            assert len(data) <= 256*1024
            key = body['name']
            previous = uploads.get(key, b'')
            if body['offset'] < len(previous):
                assert previous[body['offset']:body['offset']+len(data)] == data
            else:
                uploads[key] = previous+data
            return dict(offset=body['offset']+len(data))
    jobs.center = SimpleNamespace(studies=Studies())
    actor = dict(user_id='operator')
    request_id = str(uuid.uuid4())
    first = jobs.publish(session, request_id, actor)
    assert first == jobs.publish(session, request_id, actor)
    assert first['url'] == '/learning/imitate?study='+first['study_id']+'&panel=inspect'
    assert calls[0][0]['request_id'] == first['study_id'] and calls[0][1] == actor
    assert uploads == raw
    with pytest.raises(ValueError):
        Jobs(jobs.root, jobs.python).publish(session, str(uuid.uuid4()), actor)


def test_nonpolicy_feature_is_rejected_even_with_self_consistent_file_hashes(tmp_path, monkeypatch):
    jobs, session, episodes, process = _setup(tmp_path, monkeypatch)
    jobs.start(session, episodes, str(uuid.uuid4()))
    output, _ = finished(jobs, session, process)
    info = json.loads((output/'meta/info.json').read_text())
    info['features']['observation.images.review_only'] = dict(dtype='image')
    raw = json.dumps(info).encode()
    (output/'meta/info.json').write_bytes(raw)
    path = output.with_name('dataset.receipt.json')
    receipt = json.loads(path.read_text())
    receipt['files']['meta/info.json'] = hashlib.sha256(raw).hexdigest()
    path.write_text(json.dumps(receipt))
    assert jobs.refresh(session)['status'] == 'failed'


def test_export_waits_for_its_child_to_finish_exec_before_proving_ownership(tmp_path, monkeypatch):
    jobs,session,episodes,process=_setup(tmp_path,monkeypatch)
    proof=dict(pid=process.pid,start='1',boot='test')
    results=iter([None,None,proof])
    monkeypatch.setattr(module,'process_stamp',lambda *args:next(results))
    monkeypatch.setattr(module.time,'sleep',lambda seconds:None)
    assert jobs.start(session,episodes,str(uuid.uuid4()))['status']=='running'


def test_export_reserves_space_before_starting_a_worker(tmp_path,monkeypatch):
    jobs,session,episodes,process=_setup(tmp_path,monkeypatch)
    monkeypatch.setattr(module.shutil,'disk_usage',lambda path:SimpleNamespace(free=0))
    with pytest.raises(ValueError,match='공간'):
        jobs.start(session,episodes,str(uuid.uuid4()))
    assert not list(jobs.root.rglob('job.json'))
