"""Passive capture records accepted references and complete causal grids only."""
import copy
import io
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import pytest
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'training/omx'))
from experiment_profile import profile_revision
import passive_recording as recording


def rig(arms=2):
    profile = dict(schema='rosy.omx.learning-profile/1',name='explicit test rig',mode='cooperative',
        task='synthetic capture',arms=[dict(id=f'arm_{i}',joint_names=['j0','j1'],units='rad') for i in range(arms)],
        cameras=[dict(id=name,input_key='observation.images.'+name,arm_id=None,role=name,
            source_identity='device-'+name,placement=name,shape=[3,16,16],purposes=purposes)
            for name,purposes in [('top',['policy']),('wrist',['record']),('preview',['monitor'])]])
    revision = profile_revision(profile)
    producers = dict(arms={arm['id']:dict(kind='arm',owner_id='owner-'+arm['id'],
        source_identity='provider-'+arm['id'],session_epoch='arm-epoch',clock_domain='host-monotonic',
        rate_hz=20,joint_names=arm['joint_names'],state_units='rad',action_units='rad',
        calibration_revision='calibration-verified',profile_revision='owner-profile-verified',
        state_producer='measured-prestate',reference_producer='committed-reference',
        reference_stage='post_guard_accepted') for arm in profile['arms']},
        cameras={c['id']:dict(kind='camera',source_identity=c['source_identity'],session_epoch='camera-epoch',
            clock_domain='host-monotonic',rate_hz=10,shape=c['shape'],timestamp_semantics='host_receive')
            for c in profile['cameras'] if c['purposes'] != ['monitor']})
    timing = dict(fps=5,max_camera_age_s=.15,max_arm_age_s=.05,
        max_camera_skew_s=.1,max_arm_skew_s=.04,max_gap_s=.3)
    return profile,producers,timing


def sample_inputs(profile,producers,stamp,sequence):
    arms,cameras = [],[]
    for index,arm in enumerate(profile['arms']):
        desc = producers['arms'][arm['id']]
        arms.append(dict(schema='rosy.passive-owner-sample/1',arm_id=arm['id'],
            **{k:desc[k] for k in ('owner_id','source_identity','session_epoch','clock_domain',
                'joint_names','state_units','action_units','calibration_revision','profile_revision','reference_stage')},
            sequence=sequence*2,state_timestamp=stamp-.01,reference_timestamp=stamp-.005,
            state=[index+.1,index+.2],accepted_reference=[index+.3,index+.4],
            reference_id='sent-'+str(sequence)+'-'+arm['id']))
    for camera_id,desc in producers['cameras'].items():
        cameras.append(dict(schema='rosy.passive-camera-sample/1',camera_id=camera_id,
            **{k:desc[k] for k in ('source_identity','session_epoch','clock_domain','shape','timestamp_semantics')},
            sequence=sequence,timestamp=stamp-.02))
    return arms,cameras


def jpeg():
    stream=io.BytesIO()
    Image.new('RGB',(16,16),(80,120,160)).save(stream,format='JPEG')
    return stream.getvalue()


def push(recorder,profile,producers,stamp,sequence):
    arms,cameras=sample_inputs(profile,producers,stamp,sequence)
    for event in arms:
        recorder.push_arm(event,received_at=stamp)
    for event in cameras:
        recorder.push_camera(event,jpeg(),received_at=stamp)


def kept_episode(root):
    profile,producers,timing=rig()
    config=recording.preflight(profile,producers,timing,now=10.,clock_domain='host-monotonic')
    recorder=recording.Recorder(root,config)
    push(recorder,profile,producers,10.,0)
    recorder.start(10.)
    push(recorder,profile,producers,10.2,2)
    recorder.advance(10.2)
    recorder.stop(10.21)
    return recorder.keep(),profile,producers,timing


def test_seal_keeps_unknown_outcome_real_sent_vectors_and_review_frames(tmp_path):
    seal,profile,_,_=kept_episode(tmp_path/'episode')
    assert seal['schema']=='rosy.passive-recording-seal/1'
    assert seal['task_outcome']=='unknown'
    assert seal['physical_learning_verified'] is False
    assert seal['frames']==2
    checked=recording.verify(tmp_path/'episode')
    assert checked==seal
    rows=recording.frames(tmp_path/'episode',checked)
    assert rows[0]['action']==[.3,.4,1.3,1.4]
    assert rows[0]['state']==[.1,.2,1.1,1.2]
    assert set(rows[0]['cameras'])=={'top','wrist'}
    assert rows[0]['cameras']['top']['sequence']!=rows[1]['cameras']['top']['sequence']
    assert rows[0]['cameras']['top']['sha256']==rows[1]['cameras']['top']['sha256']


def test_missing_warmup_and_interior_tick_cannot_be_silently_trimmed(tmp_path):
    profile,producers,timing=rig()
    config=recording.preflight(profile,producers,timing,now=10.,clock_domain='host-monotonic')
    recorder=recording.Recorder(tmp_path/'episode',config)
    with pytest.raises(ValueError):
        recorder.start(10.)
    recorder.discard()
    recorder=recording.Recorder(tmp_path/'other',config)
    push(recorder,profile,producers,10.,0)
    recorder.start(10.)
    with pytest.raises(ValueError):
        recorder.advance(10.2)
    with pytest.raises(ValueError):
        recorder.keep()
    recorder.discard()


@pytest.mark.parametrize('field,value',[('session_epoch','restarted'),('source_identity','swapped'),
    ('clock_domain','other-clock'),('joint_names',['j1','j0']),('accepted_reference',None),
    ('reference_stage','requested'),('calibration_revision','changed')])
def test_owner_identity_and_complete_accepted_reference_are_frozen(tmp_path,field,value):
    profile,producers,timing=rig()
    recorder=recording.Recorder(tmp_path/'episode',recording.preflight(
        profile,producers,timing,now=10.,clock_domain='host-monotonic'))
    arms,_=sample_inputs(profile,producers,10.,0)
    arms[0][field]=value
    with pytest.raises(ValueError):
        recorder.push_arm(arms[0],received_at=10.)
    recorder.discard()


def test_preflight_never_invents_reference_provider_or_silently_changes_fps():
    profile,producers,timing=rig()
    for bad in [dict(timing,fps=30),dict(timing,max_gap_s=float('nan'))]:
        with pytest.raises(ValueError):
            recording.preflight(profile,producers,bad,now=10.,clock_domain='host-monotonic')
    changed=copy.deepcopy(producers)
    changed['arms']['arm_0'].pop('reference_producer')
    with pytest.raises(ValueError):
        recording.preflight(profile,changed,timing,now=10.,clock_domain='host-monotonic')


def test_raw_byte_changes_are_rejected(tmp_path):
    seal,_,_,_=kept_episode(tmp_path/'episode')
    image=next((tmp_path/'episode').rglob('*.jpg'))
    image.write_bytes(b'changed')
    with pytest.raises(ValueError):
        recording.verify(tmp_path/'episode')


def test_success_requires_an_explicit_human_actor(tmp_path):
    profile,producers,timing=rig(arms=1)
    recorder=recording.Recorder(tmp_path/'episode',recording.preflight(
        profile,producers,timing,now=10.,clock_domain='host-monotonic'))
    push(recorder,profile,producers,10.,0)
    recorder.start(10.)
    recorder.stop(10.01)
    assert recorder.summary()['integrity_verified'] is True
    with pytest.raises(ValueError):
        recorder.keep(task_outcome='success')
    assert recorder.keep()['task_outcome']=='unknown'


def test_external_provider_failure_closes_writer_and_prevents_keep(tmp_path):
    profile,producers,timing=rig()
    recorder=recording.Recorder(tmp_path/'episode',recording.preflight(
        profile,producers,timing,now=10.,clock_domain='host-monotonic'))
    push(recorder,profile,producers,10.,0)
    recorder.start(10.)
    summary=recorder.invalidate('configured descriptor changed')
    assert summary['status']=='invalid' and summary['integrity_verified'] is False
    assert not recorder.writer.is_alive()
    with pytest.raises(ValueError):
        recorder.keep()


@pytest.mark.parametrize('field,value',[('source_identity','other-camera'),('session_epoch','new-epoch'),
    ('clock_domain','exposure-clock'),('shape',[3,32,32])])
def test_camera_binding_changes_fail_closed(tmp_path,field,value):
    profile,producers,timing=rig()
    recorder=recording.Recorder(tmp_path/'episode',recording.preflight(
        profile,producers,timing,now=10.,clock_domain='host-monotonic'))
    _,cameras=sample_inputs(profile,producers,10.,0)
    cameras[0][field]=value
    with pytest.raises(ValueError):
        recorder.push_camera(cameras[0],jpeg(),received_at=10.)
    recorder.discard()


def test_fresh_references_do_not_hide_excessive_measured_state_skew(tmp_path):
    profile,producers,timing=rig()
    recorder=recording.Recorder(tmp_path/'episode',recording.preflight(
        profile,producers,timing,now=10.,clock_domain='host-monotonic'))
    arms,cameras=sample_inputs(profile,producers,10.,0)
    arms[0]['state_timestamp']=9.95
    arms[1]['state_timestamp']=9.995
    for event in arms:
        recorder.push_arm(event,received_at=10.)
    for event in cameras:
        recorder.push_camera(event,jpeg(),received_at=10.)
    with pytest.raises(ValueError):
        recorder.start(10.)
    recorder.discard()


def stopped_draft(root):
    profile,producers,timing=rig()
    recorder=recording.Recorder(root,recording.preflight(
        profile,producers,timing,now=10.,clock_domain='host-monotonic'))
    push(recorder,profile,producers,10.,0)
    recorder.start(10.)
    recorder.stop(10.01)
    return recorder


def test_stopped_draft_resumes_without_overwriting_raw_or_accepting_more_inputs(tmp_path):
    root=tmp_path/'episode'
    original=stopped_draft(root)
    before=recording.hashes(root)
    recovered=recording.Recorder.resume(root)
    assert recovered.summary()==original.summary()
    assert recording.hashes(root)==before
    profile,producers,_=rig()
    arms,_=sample_inputs(profile,producers,10.2,2)
    with pytest.raises(ValueError):
        recovered.push_arm(arms[0],received_at=10.2)
    assert recovered.keep()['task_outcome']=='unknown'
    assert recording.verify(root)['frames']==1


def test_kept_capture_retry_after_restart_preserves_original_human_label(tmp_path):
    root=tmp_path/'episode'
    recorder=stopped_draft(root)
    first=recorder.keep(task_outcome='success',actor={'user_id':'reviewer'})
    before={path.relative_to(root).as_posix():path.read_bytes() for path in root.rglob('*') if path.is_file()}
    resumed=recording.Recorder.resume(root)
    assert resumed.keep(task_outcome='success',actor={'user_id':'reviewer'})==first
    assert before=={path.relative_to(root).as_posix():path.read_bytes() for path in root.rglob('*') if path.is_file()}
    for outcome,actor in [('failure',{'user_id':'reviewer'}),('success',{'user_id':'other'}),('unknown',None)]:
        with pytest.raises(ValueError):
            resumed.keep(task_outcome=outcome,actor=actor)


def test_resume_rejects_changed_raw_and_unclosed_capture(tmp_path):
    root=tmp_path/'episode'
    stopped_draft(root)
    next(root.rglob('*.jpg')).write_bytes(b'changed')
    with pytest.raises(ValueError):
        recording.Recorder.resume(root)
    profile,producers,timing=rig()
    recorder=recording.Recorder(tmp_path/'open',recording.preflight(
        profile,producers,timing,now=10.,clock_domain='host-monotonic'))
    push(recorder,profile,producers,10.,0)
    recorder.start(10.)
    with pytest.raises(ValueError):
        recording.Recorder.resume(tmp_path/'open')
    recorder.discard()


def test_committed_seal_with_pending_draft_summary_cannot_be_relabelled_on_recovery(tmp_path):
    root=tmp_path/'episode'
    recorder=stopped_draft(root)
    draft=recording.read_json(root/'episode.json')
    seal=recorder.keep(task_outcome='success',actor={'user_id':'reviewer'})
    original=(root/'seal.json').read_bytes()
    recording.write_json(root/'episode.json',draft)
    resumed=recording.Recorder.resume(root)
    with pytest.raises(ValueError):
        resumed.keep(task_outcome='failure',actor={'user_id':'reviewer'})
    assert (root/'seal.json').read_bytes()==original
    assert resumed.keep(task_outcome='success',actor={'user_id':'reviewer'})==seal
    assert recording.verify(root)==seal


def test_disk_reserve_refuses_new_episode_without_creating_raw_directory(tmp_path,monkeypatch):
    profile,producers,timing=rig()
    config=recording.preflight(profile,producers,timing,now=10.,clock_domain='host-monotonic')
    monkeypatch.setattr('shutil.disk_usage',lambda *_:SimpleNamespace(free=0))
    recorder=None
    root=tmp_path/'episode'
    try:
        with pytest.raises(ValueError,match='space|reserve'):
            recorder=recording.Recorder(root,config)
    finally:
        if recorder is not None:
            recorder.discard()
    assert not root.exists()


@pytest.mark.parametrize('operation',['invalidate','advance'])
def test_summary_disk_failure_cannot_hide_terminal_invalid_state_or_leave_writer_running(tmp_path,monkeypatch,operation):
    profile,producers,timing=rig()
    recorder=recording.Recorder(tmp_path/'episode',recording.preflight(
        profile,producers,timing,now=10.,clock_domain='host-monotonic'))
    push(recorder,profile,producers,10.,0)
    recorder.start(10.)
    def unavailable_summary():
        raise OSError(28,'no space left on device')
    monkeypatch.setattr(recorder,'_save_summary',unavailable_summary)
    if operation=='invalidate':
        summary=recorder.invalidate('source spool stopped')
        assert summary['status']=='invalid'
    else:
        with pytest.raises(ValueError,match='summary'):
            recorder.advance(10.2)
    assert recorder.summary()['status']=='invalid'
    assert 'summary' in recorder.summary()['error'].lower()
    assert not recorder.writer.is_alive()
    with pytest.raises(ValueError):
        recorder.keep()


def test_disk_reserve_is_rechecked_by_background_writer_and_raw_is_preserved(tmp_path,monkeypatch):
    profile,producers,timing=rig()
    recorder=recording.Recorder(tmp_path/'episode',recording.preflight(
        profile,producers,timing,now=10.,clock_domain='host-monotonic'))
    monkeypatch.setattr('shutil.disk_usage',lambda *_:SimpleNamespace(free=0))
    push(recorder,profile,producers,10.,0)
    recorder.start(10.)
    try:
        with pytest.raises(ValueError,match='space|reserve|writer'):
            recorder.stop(10.01)
    finally:
        recorder.invalidate('test cleanup after disk reserve failure')
    assert (tmp_path/'episode'/'config.json').is_file()
    assert not (tmp_path/'episode'/'seal.json').exists()


def test_constructor_summary_failure_does_not_leak_an_idle_writer(tmp_path,monkeypatch):
    profile,producers,timing=rig()
    before={thread.ident for thread in threading.enumerate() if thread.name=='passive-recording-disk'}
    def unavailable_summary(_):
        raise OSError(28,'no space left on device')
    monkeypatch.setattr(recording.Recorder,'_save_summary',unavailable_summary)
    with pytest.raises(ValueError,match='summary|storage'):
        recording.Recorder(tmp_path/'episode',recording.preflight(
            profile,producers,timing,now=10.,clock_domain='host-monotonic'))
    assert {thread.ident for thread in threading.enumerate() if thread.name=='passive-recording-disk'}==before
    assert (tmp_path/'episode'/'config.json').is_file()
