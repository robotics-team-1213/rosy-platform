"""Archived review reads stopped evidence without requiring connected hardware."""
from contextlib import contextmanager
import io
import json
import threading
import time
import urllib.error
import urllib.request
import uuid

from PIL import Image
import pytest

from review_app import ReviewStore, make_server
from learning_recordings import Recordings
import passive_recording as recording


def stopped_episode(manager):
    profile = dict(schema='rosy.omx.learning-profile/1', name='saved wrist', mode='independent',
        task='synthetic review', arms=[dict(id='arm_a', joint_names=['j0','j1'], units='rad')],
        cameras=[dict(id=name, input_key='observation.images.'+name, arm_id='arm_a' if name=='wrist' else None,
            role='wrist' if name=='wrist' else 'side', source_identity='saved-'+name,
            placement=name, shape=[3,16,16], purposes=purposes)
            for name,purposes in [('wrist',['policy']),('side',['record'])]])
    timing = dict(fps=5,max_camera_age_s=.15,max_arm_age_s=.05,
        max_camera_skew_s=.1,max_arm_skew_s=.04,max_gap_s=.3)
    producers = dict(arms={'arm_a':dict(kind='arm',owner_id='owner-a',source_identity='source-a',
        session_epoch='arm-epoch',clock_domain='host-monotonic',rate_hz=20,joint_names=['j0','j1'],
        state_units='rad',action_units='rad',calibration_revision='verified-calibration',
        profile_revision='verified-owner-profile',state_producer='measured-prestate',
        reference_producer='committed-reference',reference_stage='post_guard_accepted')},
        cameras={camera['id']:dict(kind='camera',source_identity=camera['source_identity'],
            session_epoch='camera-epoch',clock_domain='host-monotonic',rate_hz=10,
            shape=camera['shape'],timestamp_semantics='host_receive') for camera in profile['cameras']})
    saved=manager.profiles.save(dict(request_id=str(uuid.uuid4()),profile=profile))
    session=manager.create(dict(request_id=str(uuid.uuid4()),name='stored take',profile_id=saved['id'],
        profile_revision=saved['revision'],timing=timing))
    eid=str(uuid.uuid4())
    root=manager._episode_root(session['id'],eid)
    config=recording.preflight(profile,producers,timing,now=10.,clock_domain='host-monotonic')
    recorder=recording.Recorder(root,config)
    for index,stamp in enumerate((10.,10.2)):
        desc=producers['arms']['arm_a']
        recorder.push_arm(dict(schema='rosy.passive-owner-sample/1',arm_id='arm_a',
            **{key:desc[key] for key in ('owner_id','source_identity','session_epoch','clock_domain',
                'joint_names','state_units','action_units','calibration_revision','profile_revision','reference_stage')},
            sequence=index*2,state_timestamp=stamp-.01,reference_timestamp=stamp-.005,
            state=[.1+index,.2+index],accepted_reference=[.3+index,.4+index],reference_id='accepted-'+str(index)),
            received_at=stamp)
        for name,desc in producers['cameras'].items():
            stream=io.BytesIO()
            Image.new('RGB',(16,16),(190,20,40) if name=='wrist' else (20,40,190)).save(stream,format='JPEG')
            recorder.push_camera(dict(schema='rosy.passive-camera-sample/1',camera_id=name,
                **{key:desc[key] for key in ('source_identity','session_epoch','clock_domain','shape','timestamp_semantics')},
                sequence=index*2,timestamp=stamp-.02),stream.getvalue(),received_at=stamp)
        recorder.start(stamp) if index==0 else recorder.advance(stamp)
    recorder.stop(10.21)
    with manager.store.connect() as db:
        row=manager._load(db,session['id'])
        row.update(status='ready',episodes=[dict(recorder.summary(),id=eid)])
        manager._save(db,row)
    return session['id'],eid,root


@contextmanager
def endpoint(tmp_path):
    manager=Recordings(ReviewStore(tmp_path/'review',empty_training=True))
    sid,eid,root=stopped_episode(manager)
    server=make_server(manager.store,port=0,recordings=manager)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    token=json.load(urllib.request.urlopen(base+'/api/learning/tasks'))['token']
    def call(path,body=None):
        request=urllib.request.Request(base+path,data=None if body is None else json.dumps(body).encode(),
            headers={'Content-Type':'application/json','X-Pinky-Token':token})
        try:
            with urllib.request.urlopen(request,timeout=5) as response:
                data=response.read()
                return response.status,json.loads(data) if response.headers['Content-Type'].startswith('application/json') else data
        except urllib.error.HTTPError as error:return error.code,json.load(error)
    try:yield manager,call,sid,eid,root
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)


def ready(call,sid,eid):
    path=f'/api/learning/recording/review/{sid}/{eid}'
    code,value=call(path+'?refresh=1')
    assert code==200,(code,value)
    deadline=time.monotonic()+5
    while value['status']=='preparing' and time.monotonic()<deadline:
        time.sleep(.02)
        code,value=call(path)
        assert code==200,(code,value)
    assert value['status']=='ready',value
    return value


def test_saved_review_http_serves_stored_views_and_distinct_measured_and_accepted_values(tmp_path):
    with endpoint(tmp_path) as (manager,call,sid,eid,root):
        summary=ready(call,sid,eid)
        assert manager.snapshot()['configured'] is False
        assert summary['frames']==2 and summary['fps']==5
        assert summary['physical_learning_verified'] is False
        assert [camera['id'] for camera in summary['cameras']]==['wrist','side']
        revision=summary['evidence_revision']
        code,frame=call(f'/api/learning/recording/review-frame/{sid}/{eid}/{revision}/1')
        assert code==200,(code,frame)
        assert frame['frame_index']==1 and frame['total_frames']==2 and frame['grid_time']==10.2
        assert frame['arms'][0]['joint_names']==['j0','j1'] and frame['arms'][0]['units']=='rad'
        assert frame['arms'][0]['state']==[1.1,1.2]
        assert frame['arms'][0]['accepted_reference']==[1.3,1.4]
        assert frame['arms'][0]['state_timestamp']<frame['arms'][0]['reference_timestamp']
        raw=json.loads((root/'frames.jsonl').read_text().splitlines()[1])
        for camera in frame['cameras']:
            assert '/review-image/' in camera['image_url'] and '/preview/' not in camera['image_url']
            code,image=call(camera['image_url'])
            assert code==200 and image==(root/raw['cameras'][camera['id']]['path']).read_bytes()
        assert frame['cameras'][1]['purposes']==['record']
        assert manager.get(sid)['episodes'][0]['task_outcome']=='unknown'
        assert manager.get(sid)['episodes'][0]['status']=='draft'
        assert call('/record-review.js')[0]==200
        assert call('/api/learning/recording/review-close',dict(session_id=sid,episode_id=eid))[0]==200
        assert call(frame['cameras'][0]['image_url'])[0]==400


def test_saved_review_refuses_wrong_revision_unknown_selection_and_changed_image(tmp_path):
    with endpoint(tmp_path) as (manager,call,sid,eid,root):
        summary=ready(call,sid,eid);revision=summary['evidence_revision']
        prefix=f'/api/learning/recording/review-frame/{sid}/{eid}'
        assert call(prefix+'/'+'0'*64+'/0')[0]==400
        assert call(prefix+'/'+revision+'/2')[0]==400
        assert call(f'/api/learning/recording/review/{sid}/{uuid.uuid4()}')[0]==400
        assert call(f'/api/learning/recording/review/{sid}/{eid}?refresh=2')[0]==400
        _,frame=call(prefix+'/'+revision+'/0')
        assert call(frame['cameras'][0]['image_url'].rsplit('/',1)[0]+'/missing')[0]==400
        raw=json.loads((root/'frames.jsonl').read_text().splitlines()[0])
        (root/raw['cameras']['side']['path']).write_bytes(b'tampered')
        assert call(frame['cameras'][1]['image_url'])[0]==400
        manager.active=str(uuid.uuid4())
        assert call(f'/api/learning/recording/review/{sid}/{eid}')[0]==400
        manager.active=None


def test_review_preparation_is_bounded_cancellable_and_does_not_hold_capture_lock(tmp_path,monkeypatch):
    import passive_review
    entered,release=threading.Event(),threading.Event()
    original=passive_review.Review.build
    def delayed(*args,**kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args,**kwargs)
    monkeypatch.setattr(passive_review.Review,'build',delayed)
    with endpoint(tmp_path) as (manager,call,sid,eid,root):
        try:
            path=f'/api/learning/recording/review/{sid}/{eid}'
            assert call(path)[1]['status']=='preparing'
            assert entered.wait(2)
            assert manager.snapshot()['review_busy'] is True
            with pytest.raises(ValueError,match='검수'):
                manager.start(dict(session_id=sid,request_id=str(uuid.uuid4())))
            done=threading.Event()
            def stop():
                manager.get(sid)
                try:
                    manager.stop(dict(session_id=sid,request_id=str(uuid.uuid4())))
                except ValueError as error:
                    assert '진행 중인 녹화' in str(error)
                finally:done.set()
            thread=threading.Thread(target=stop,daemon=True);thread.start()
            assert done.wait(2),'recording Stop waited for review validation'
            assert call('/api/learning/recording/review-close',dict(session_id=sid,episode_id=eid))[0]==200
        finally:release.set()


@pytest.mark.parametrize('decision',['keep','discard'])
def test_saved_review_cache_is_invalidated_by_external_episode_decision(tmp_path,decision):
    with endpoint(tmp_path) as (manager,call,sid,eid,root):
        summary=ready(call,sid,eid)
        path=f'/api/learning/recording/review-frame/{sid}/{eid}/{summary["evidence_revision"]}/0'
        _,frame=call(path)
        body=dict(session_id=sid,episode_id=eid,request_id=str(uuid.uuid4()))
        if decision=='keep':body['task_outcome']='unknown'
        assert call('/api/learning/recording/'+decision,body)[0]==200
        assert call(frame['cameras'][0]['image_url'])[0]==400
        if decision=='keep':assert ready(call,sid,eid)['task_outcome']=='unknown'
        else:assert call(f'/api/learning/recording/review/{sid}/{eid}')[0]==400
