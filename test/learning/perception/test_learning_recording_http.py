"""A local recording workspace can configure rigs without a training interpreter."""
from contextlib import contextmanager
import json
import threading
from types import SimpleNamespace
import urllib.error
import urllib.request
import uuid
import sqlite3

import pytest

from review_app import ReviewStore, make_server


@contextmanager
def recording_server(tmp_path):
    server=make_server(ReviewStore(tmp_path/'review',empty_training=True),port=0)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    token=json.load(urllib.request.urlopen(base+'/api/learning/tasks'))['token']
    def call(path,body=None):
        request=urllib.request.Request(base+'/api/learning/recording'+path,
            data=None if body is None else json.dumps(body).encode(),
            headers={'Content-Type':'application/json','X-Pinky-Token':token})
        try:
            with urllib.request.urlopen(request,timeout=5) as response:return response.status,json.load(response)
        except urllib.error.HTTPError as error:return error.code,json.load(error)
    try:yield call
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)


def profile():
    return dict(schema='rosy.omx.learning-profile/1',name='single wrist',mode='independent',task='pick',
        arms=[dict(id='arm_a',joint_names=['joint1'],units='rad')],cameras=[dict(
            id='arm_a_wrist',input_key='observation.images.arm_a_wrist',arm_id='arm_a',role='wrist',
            source_identity='registered-wrist-a',placement='arm_a_wrist',shape=[3,32,32],purposes=['policy','record'])])


def timing():
    return dict(fps=5,max_camera_age_s=.15,max_arm_age_s=.05,
        max_camera_skew_s=.1,max_arm_skew_s=.04,max_gap_s=.2)


def test_recording_snapshot_reports_unconfigured_sources_without_a_learner(tmp_path):
    with recording_server(tmp_path) as call:
        code,value=call('/snapshot')
        assert code==200
        assert value['configured'] is False and value['active'] is None
        assert value['sources']==[] and value['import_available'] is False
        assert value['exporter']['available'] is False


def test_profile_versions_are_available_without_a_training_center(tmp_path):
    with recording_server(tmp_path) as call:
        body=dict(request_id=str(uuid.uuid4()),profile=profile())
        code,first=call('/profile',body)
        assert code==200 and first['physical_setup_verified'] is False, (code,first)
        assert call('/profile',body)[1]['id']==first['id']
        changed=profile();changed['cameras'][0]['placement']='new_wrist_position'
        code,second=call('/profile',dict(request_id=str(uuid.uuid4()),parent_id=first['id'],profile=changed))
        assert code==200 and second['revision']!=first['revision']
        assert call('/profile/'+first['id'])[1]['profile']['cameras'][0]['placement']=='arm_a_wrist'
        assert len(call('/profiles')[1]['profiles'])==2


def test_sessions_pin_the_saved_rig_and_refuse_unavailable_capture(tmp_path):
    with recording_server(tmp_path) as call:
        _,saved=call('/profile',dict(request_id=str(uuid.uuid4()),profile=profile()))
        body=dict(request_id=str(uuid.uuid4()),name='wrist take',profile_id=saved['id'],
            profile_revision=saved['revision'],timing=timing())
        code,session=call('/session',body)
        assert code==200 and session['profile_revision']==saved['revision']
        assert call('/session',body)[1]['id']==session['id']
        assert call('/session',dict(body,name='changed'))[0]==400
        assert call('/start',dict(session_id=session['id'],request_id=str(uuid.uuid4())))[0]==400
        current=call('/session/'+session['id'])[1]
        assert current['episodes']==[] and current['status']=='idle'


def test_export_finalization_does_not_block_polling_or_recording_stop(tmp_path):
    from learning_recordings import Recordings
    manager=Recordings(ReviewStore(tmp_path/'review',empty_training=True))
    entered,release=threading.Event(),threading.Event()
    def finalize(row):
        entered.set()
        assert release.wait(5)
        return dict(status='failed',artifact_url=None,error='fixture conversion failed')
    manager.jobs.refresh=finalize
    saved=manager.profiles.save(dict(request_id=str(uuid.uuid4()),profile=profile()))
    def create(name):
        return manager.create(dict(request_id=str(uuid.uuid4()),name=name,profile_id=saved['id'],
            profile_revision=saved['revision'],timing=timing()))
    converting,recording=create('conversion'),create('recording')
    with manager.lock,manager.store.connect() as db:
        row=manager._load(db,converting['id'])
        row.update(status='exporting',export_request='fixture')
        manager._save(db,row)
        row=manager._load(db,recording['id']);row['status']='recording';manager._save(db,row)
        manager.active=recording['id']
    manager._monitor(converting['id'],'fixture')
    try:
        assert entered.wait(2)
        finished=threading.Event()
        result=[]
        def stop():
            result.append(manager.get(converting['id'])['status'])
            manager.stop(dict(session_id=recording['id'],request_id=str(uuid.uuid4())))
            finished.set()
        caller=threading.Thread(target=stop,daemon=True);caller.start()
        assert finished.wait(2), 'recording Stop waited for conversion hashing'
        assert result==['exporting'] and manager.stop_event.is_set()
    finally:
        release.set();manager.close()
        for thread in manager.monitors:thread.join(timeout=5)


def test_recording_archive_streams_headers_and_closes_its_manager(tmp_path):
    archive=tmp_path/'dataset.zip';archive.write_bytes(b'ZIP-fixture'*10000)
    closed=[]
    recordings=SimpleNamespace(artifact=lambda uid:archive,close=lambda:closed.append(True))
    server=make_server(ReviewStore(tmp_path/'review',empty_training=True),port=0,recordings=recordings)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    uid=str(uuid.uuid4())
    try:
        url=f'http://127.0.0.1:{server.server_port}/api/learning/recording/artifact/{uid}'
        with urllib.request.urlopen(url,timeout=5) as response:
            assert response.headers['Content-Type']=='application/zip'
            assert int(response.headers['Content-Length'])==archive.stat().st_size
            assert response.headers['Content-Disposition']==f'attachment; filename="{uid}.zip"'
            assert response.read()==archive.read_bytes()
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)
    assert closed==[True]


def test_review_of_another_session_is_rejected_while_any_capture_is_active(tmp_path):
    from learning_recordings import Recordings
    manager=Recordings(ReviewStore(tmp_path/'review',empty_training=True))
    saved=manager.profiles.save(dict(request_id=str(uuid.uuid4()),profile=profile()))
    session=manager.create(dict(request_id=str(uuid.uuid4()),name='draft review',profile_id=saved['id'],
        profile_revision=saved['revision'],timing=timing()))
    episode_id=str(uuid.uuid4())
    with manager.store.connect() as db:
        row=manager._load(db,session['id']);row['status']='ready'
        row['episodes']=[dict(id=episode_id,status='draft',frames=2,integrity_verified=True,
            task_outcome='unknown',error=None)]
        manager._save(db,row)
    manager.active=str(uuid.uuid4())
    try:
        with pytest.raises(ValueError,match='녹화'):
            manager.keep(dict(session_id=session['id'],episode_id=episode_id,
                request_id=str(uuid.uuid4()),task_outcome='unknown'))
    finally:manager.close()


@pytest.mark.parametrize('registry_full',[False,True])
def test_raw_failure_cannot_strand_a_session_as_recording(tmp_path,monkeypatch,registry_full):
    from learning_recordings import Recordings
    manager=Recordings(ReviewStore(tmp_path/'review',empty_training=True))
    saved=manager.profiles.save(dict(request_id=str(uuid.uuid4()),profile=profile()))
    session=manager.create(dict(request_id=str(uuid.uuid4()),name='disk failure',profile_id=saved['id'],
        profile_revision=saved['revision'],timing=timing()))
    episode_id=str(uuid.uuid4())
    with manager.store.connect() as db:
        row=manager._load(db,session['id']);row['status']='recording'
        row['episodes']=[dict(id=episode_id,status='recording',frames=0,integrity_verified=False,
            task_outcome='unknown',error=None)]
        manager._save(db,row)
    manager.active=session['id']
    def source_failure(*args):raise ValueError('source epoch changed')
    def summary_failure(*args):raise OSError('raw storage is full')
    monkeypatch.setattr(manager.sources,'poll',source_failure)
    recorder=SimpleNamespace(invalidate=summary_failure,summary=lambda:dict(status='invalid',frames=0,
        integrity_verified=False,task_outcome='unknown',error='raw storage is full'))
    if registry_full:
        def registry_failure(*args):raise sqlite3.OperationalError('database or disk is full')
        monkeypatch.setattr(manager,'_save',registry_failure)
    try:
        manager._capture(session['id'],episode_id,recorder,{})
        current=manager.get(session['id'])
        assert manager.active is None and current['status']=='failed'
        assert current['episodes'][0]['status']=='invalid' and current['error']
    finally:manager.close()


def test_export_terminal_status_survives_registry_write_failure(tmp_path,monkeypatch):
    from learning_recordings import Recordings
    manager=Recordings(ReviewStore(tmp_path/'review',empty_training=True))
    saved=manager.profiles.save(dict(request_id=str(uuid.uuid4()),profile=profile()))
    session=manager.create(dict(request_id=str(uuid.uuid4()),name='export storage failure',
        profile_id=saved['id'],profile_revision=saved['revision'],timing=timing()))
    with manager.store.connect() as db:
        row=manager._load(db,session['id']);row.update(status='exporting',export_request='fixture')
        manager._save(db,row)
    monkeypatch.setattr(manager.jobs,'refresh',lambda row:dict(status='failed',artifact_url=None,error='disk full'))
    def fail_save(*args):raise sqlite3.OperationalError('database or disk is full')
    monkeypatch.setattr(manager,'_save',fail_save)
    try:
        manager._monitor_export(session['id'],'fixture')
        current=manager.get(session['id'])
        assert current['status']=='failed' and current['export']['status']=='failed'
        assert current['error'] and not manager.failed_sessions[session['id']]['export']['artifact_url']
    finally:manager.close()
