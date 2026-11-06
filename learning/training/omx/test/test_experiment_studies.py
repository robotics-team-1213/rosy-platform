"""Uploaded studies retain project identity, immutable bytes and recoverable request ownership."""
import base64
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest

from test_experiment_center import center
from experiment_studies import Studies
from experiment_io import write_json
import experiment_lerobot_source as source


def _setup(tmp_path,monkeypatch):
    c=center(tmp_path,monkeypatch)
    c.bind_workspace('study-project')
    c.host_id='ai'
    c.methods['act']['available']=True
    return c,Studies(c)


def submission(raw=b'{}'):
    return dict(request_id=str(uuid.uuid4()),name='Uploaded demonstration',files=[
        dict(name='meta/info.json',size=len(raw),sha256=hashlib.sha256(raw).hexdigest())])


def chunk(study,raw=b'{}',offset=0):
    return dict(study_id=study['id'],name='meta/info.json',offset=offset,
        data=base64.b64encode(raw).decode())


def test_create_retries_bind_actor_and_content_and_require_project(tmp_path,monkeypatch):
    c,studies=_setup(tmp_path,monkeypatch)
    body=submission()
    actor={'user_id':'creator'}
    first=studies.create(body,actor)
    assert first['id']==body['request_id'] and first['project_id']=='study-project'
    assert first['status']=='uploading' and first['upload']['uploaded_bytes']==0
    assert studies.create(body,actor)==first
    for changed,who in [(dict(body,name='Changed'),actor),(body,{'user_id':'different'})]:
        with pytest.raises(ValueError):
            studies.create(changed,who)
    c2= center(tmp_path/'unbound',monkeypatch)
    with pytest.raises(ValueError,match='project|workspace'):
        Studies(c2).create(submission(),None)


def test_resume_reports_actual_bytes_and_preserves_partial_overlap(tmp_path,monkeypatch):
    c,studies=_setup(tmp_path,monkeypatch)
    study=studies.create(submission(b'abcdef'),None)
    folder=c.root/'studies'/study['id']/'source/meta'
    folder.mkdir(parents=True,exist_ok=True)
    (folder/'info.json').write_bytes(b'abc')
    assert studies.get(study['id'])['upload']['files'][0]['offset']==3
    body=chunk(study,b'abcdef')
    assert studies.upload(body)['offset']==6
    assert studies.upload(body)['offset']==6
    assert studies.get(study['id'])['upload']['uploaded_bytes']==6
    for changed in [dict(body,data=base64.b64encode(b'ABCDEF').decode()),
                    dict(body,name='../outside.json'),dict(body,offset=7),
                    dict(body,data=base64.b64encode(b'abcdefextra').decode())]:
        with pytest.raises(ValueError):
            studies.upload(changed)
    assert (folder/'info.json').read_bytes()==b'abcdef'
    restarted=Studies(c)
    assert restarted.get(study['id'])['upload']['uploaded_bytes']==6
    assert not (c.root/'outside.json').exists()


def test_seal_reserves_same_inspection_and_blocks_later_writes(tmp_path,monkeypatch):
    import experiment_studies as module
    c,studies=_setup(tmp_path,monkeypatch)
    study=studies.create(submission(),None)
    with pytest.raises(ValueError,match='complete|missing|size'):
        studies.inspect(dict(study_id=study['id'],request_id=str(uuid.uuid4())))
    studies.upload(chunk(study))
    calls=[]
    def launch(c,db,request_id,binding,row,stamp):
        calls.append(row)
        db.execute('INSERT INTO runs VALUES (?,?,?,?,?)',(row['id'],request_id,json.dumps(row),binding,'{}'))
        db.commit()
        return dict(row,status='running')
    monkeypatch.setattr(module,'launch',launch)
    body=dict(study_id=study['id'],request_id=str(uuid.uuid4()))
    first=studies.inspect(body)
    assert first['execution_mode']=='lerobot_inspect' and len(calls)==1
    assert studies.inspect(body)['id']==first['id'] and len(calls)==1
    assert studies.get(study['id'])['upload']['locked'] is True
    with pytest.raises(ValueError,match='locked|immutable|sealed'):
        studies.upload(chunk(study))
    request=json.loads((c.root/'runs'/first['id']/'request.json').read_text())
    assert request['project_id']=='study-project' and request['study_id']==study['id']
    assert request['schema']=='rosy.lerobot-inspect-request/1'
    assert request['source_root']==str(c.root/'studies'/study['id']/'source')


def test_symlink_uploaded_path_and_parent_are_refused(tmp_path,monkeypatch):
    c,studies=_setup(tmp_path,monkeypatch)
    study=studies.create(submission(),None)
    folder=c.root/'studies'/study['id']/'source'
    outside=tmp_path/'outside'
    outside.mkdir()
    try:
        (folder/'meta').symlink_to(outside,target_is_directory=True)
    except OSError:
        pytest.skip('symlink privilege unavailable')
    with pytest.raises(ValueError):
        studies.upload(chunk(study))
    assert not (outside/'info.json').exists()


def inspection_run(tmp_path,monkeypatch):
    import experiment_studies as module
    import experiment_lerobot_worker as worker
    c,studies=_setup(tmp_path,monkeypatch)
    study=studies.create(submission(),None)
    studies.upload(chunk(study))
    calls=[]
    def launch(c,db,request_id,binding,row,stamp):
        calls.append(row)
        db.execute('INSERT INTO runs VALUES (?,?,?,?,?)',(row['id'],request_id,json.dumps(row),binding,'{}'))
        db.commit()
        return row
    monkeypatch.setattr(module,'launch',launch)
    checked=dict(robot_type='fixture',fps=20,total_episodes=3,total_frames=30,
        episodes=[dict(index=i,frames=10,task='fixture') for i in range(3)],
        state=dict(shape=[7],names=None),action=dict(shape=[5],names=None),
        cameras=[dict(key='observation.images.front',shape=[16,16,3],dtype='image')],
        units='dataset-native/unverified',capture_session_independence='unknown')
    checked['revision']=source.digest(checked)
    run=studies.inspect(dict(study_id=study['id'],request_id=str(uuid.uuid4())))
    output=c.root/'runs'/run['id']/'output'
    output.mkdir()
    write_json(output/'result.json',dict(schema='rosy.lerobot-inspect-result/1',
        study_id=study['id'],project_id='study-project',inspection=checked,
        manifest_revision=study['upload']['manifest_revision'],
        source_revision=study['upload']['manifest_revision'],evidence_files={}))
    monkeypatch.setattr(worker,'check_result',lambda output,result,request:result)
    return c,studies,study,run,calls


def test_inspection_completion_and_saved_split_bind_exact_source_before_train(tmp_path,monkeypatch):
    c,studies,study,run,calls=inspection_run(tmp_path,monkeypatch)
    current=studies.get(study['id'])
    assert current['status']=='ready' and current['inspection']['state']['shape']==[7]
    body=dict(study_id=study['id'],source_revision=current['source_revision'],
        train=[0],validation=[],eval=[2],request_id=str(uuid.uuid4()))
    with pytest.raises(ValueError,match='revision'):
        studies.split(dict(body,source_revision='0'*64))
    saved=studies.split(body)
    assert studies.split(body)['split']==saved['split']
    request=dict(study_id=study['id'],split_revision=saved['split']['revision'],steps=2,
        batch_size=1,seed=0,request_id=str(uuid.uuid4()))
    trained=studies.start(request)
    assert trained['execution_mode']=='lerobot_train'
    assert studies.start(request)['id']==trained['id'] and len(calls)==2
    with pytest.raises(ValueError,match='identity'):
        studies.start(dict(request,steps=3))
    worker=json.loads((c.root/'runs'/trained['id']/'request.json').read_text())
    assert worker['split']==saved['split'] and worker['source_revision']==current['source_revision']
    assert worker['inspection']['revision']==current['inspection']['revision']
    assert worker['compute_host']==trained['compute_host']=='ai'
    assert 'optimizer_lr' not in worker and 'chunk_size' not in worker
    tuned=dict(request,optimizer_lr=1e-4,chunk_size=20,request_id=str(uuid.uuid4()))
    for bad,message in [(dict(tuned,optimizer_lr=1.0),'learning rate'),(dict(tuned,optimizer_lr=1),'learning rate'),
            (dict(tuned,chunk_size=101),'chunk size'),(dict(tuned,chunk_size=2.0),'chunk size'),(dict(tuned,extra=1),'fixed')]:
        with pytest.raises(ValueError,match=message):
            studies.start(bad)


def test_inspection_requires_server_host_even_with_ready_interpreter(tmp_path,monkeypatch):
    c,studies=_setup(tmp_path,monkeypatch)
    study=studies.create(submission(),None)
    studies.upload(chunk(study))
    c.host_id=None
    with pytest.raises(ValueError,match='host'):
        studies.inspect(dict(study_id=study['id'],request_id=str(uuid.uuid4())))
    assert studies.get(study['id'])['upload']['locked'] is False


def test_tampered_owned_request_cannot_mark_inspection_success(tmp_path,monkeypatch):
    c,studies,study,run,_=inspection_run(tmp_path,monkeypatch)
    file=c.root/'runs'/run['id']/'request.json'
    request=json.loads(file.read_text())
    request['project_id']='foreign-project'
    write_json(file,request)
    current=studies.get(study['id'])
    assert current['status']=='failed' and current['inspection'] is None
    assert current['runs'][0]['status']=='failed' and 'result' not in current['runs'][0]
