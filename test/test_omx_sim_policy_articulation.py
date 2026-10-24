"""Sampled articulation must remain original, clean and fresh at launch."""
import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy/robot/omx'))


def module():
    return importlib.import_module('sim_policy_articulation')


def message(stamp=1_000_000_000):
    names=['gripper_joint_2','joint5','joint4','joint3','joint2','joint1','gripper_joint_1']
    return NS(name=names,position=[-.2,.5,.4,.3,.2,.1,.2],velocity=[],
        header=NS(stamp=NS(sec=stamp//10**9,nanosec=stamp%10**9),frame_id='original'))


def ready_trace():
    clock=[10.];trace=module().ArticulationCapture(clock=lambda:clock[0])
    trace.observe(message());clock[0]=10.02;trace.observe(message(1_020_000_000))
    return trace,clock


def test_original_order_values_clocks_and_optional_velocity_survive_close():
    trace,clock=ready_trace();msg=message(1_040_000_000);msg.velocity=[.1]*7
    clock[0]=10.04;trace.observe(msg);msg.position[0]=999
    assert trace.ready
    doc=trace.finish();sample=doc['samples'][-1]
    assert sample['joint_names']==message().name and sample['positions'][0]==-.2
    assert sample['velocities']==[.1]*7 and doc['samples'][0]['velocities']==[]
    assert sample['ros_stamp_ns']==1_040_000_000 and sample['received_owner_ns']==10_040_000_000
    assert sample['frame_id']=='original' and doc['summary']['status']=='captured'
    trace.observe(message());assert len(doc['samples'])==3
    json.dumps(doc,allow_nan=False)


@pytest.mark.parametrize('fault',['missing','extra','duplicate','nan','shape','velocity','frame','stamp'])
def test_invalid_message_inside_storage_throttle_is_sticky(fault):
    trace,clock=ready_trace();clock[0]=10.021;msg=message(1_021_000_000)
    if fault=='missing':msg.name.pop();msg.position.pop()
    elif fault=='extra':msg.name.append('joint8');msg.position.append(0.)
    elif fault=='duplicate':msg.name[0]=msg.name[1]
    elif fault=='nan':msg.position[0]=float('nan')
    elif fault=='shape':msg.position.pop()
    elif fault=='velocity':msg.velocity=[float('inf')]*7
    elif fault=='frame':msg.header.frame_id='x'*513
    else:msg.header.stamp.nanosec=10**9
    trace.observe(msg);clock[0]=10.04;trace.observe(message(1_040_000_000))
    assert not trace.ready and trace.status()['invalid_messages']==1
    assert trace.finish()['summary']['status']=='incomplete'


@pytest.mark.parametrize('fault',['source','receipt','finish'])
def test_clock_rollback_cannot_be_complete(fault):
    trace,clock=ready_trace()
    if fault=='source':clock[0]=10.04;trace.observe(message(999_999_999))
    elif fault=='receipt':clock[0]=9.;trace.observe(message(1_040_000_000))
    else:clock[0]=9.
    assert trace.finish()['summary']['status']=='incomplete'


def test_frozen_source_does_not_refresh_progress_receipt():
    trace,clock=ready_trace();before=trace.status()['latest_advance_owner_ns']
    clock[0]=11.;trace.observe(message(1_020_000_000))
    assert trace.status()['latest_advance_owner_ns']==before
    fresh=module().ArticulationCapture(clock=lambda:clock[0])
    fresh.observe(message());clock[0]=11.02;fresh.observe(message())
    assert not fresh.ready


def test_zero_time_warmup_requires_two_subsequent_positive_stored_stamps():
    clock=[10.];trace=module().ArticulationCapture(clock=lambda:clock[0])
    trace.observe(message(0));clock[0]=10.02;trace.observe(message())
    assert not trace.ready
    clock[0]=10.04;trace.observe(message(1_020_000_000))
    assert trace.ready


def test_storage_limit_marks_capture_incomplete(monkeypatch):
    m=module();monkeypatch.setattr(m,'MAX_SAMPLES',2)
    trace,clock=ready_trace();clock[0]=10.04;trace.observe(message(1_040_000_000))
    doc=trace.finish();assert len(doc['samples'])==2 and doc['summary']['truncated']
    assert doc['summary']['status']=='incomplete'


@pytest.mark.parametrize('fault',['none','missing','invalid','truncated','stale','future','frozen'])
def test_launch_requires_current_clean_progress_after_homing(tmp_path,monkeypatch,fault):
    job=importlib.import_module('sim_pick_place_policy_job');trace,clock=ready_trace()
    status=trace.status()
    if fault=='invalid':status['invalid_messages']=1
    elif fault=='truncated':status['truncated']=True
    elif fault=='stale':clock[0]=11.
    elif fault=='future':clock[0]=9.
    elif fault=='frozen':
        clock[0]=11.;trace.observe(message(1_020_000_000));status=trace.status()
    if fault!='missing':(tmp_path/'articulation-ready.json').write_text(json.dumps(status))
    monkeypatch.setattr(job.time,'monotonic',lambda:clock[0])
    if fault=='none':job.require_articulation(tmp_path)
    else:
        with pytest.raises((ValueError,FileNotFoundError)):job.require_articulation(tmp_path)


@pytest.mark.parametrize('fault',['none','missing','incomplete','invalid','truncated'])
def test_joint_artifact_is_required_when_closing_policy_diagnostic(tmp_path,fault):
    job=importlib.import_module('sim_pick_place_policy_job')
    contacts=importlib.import_module('test_omx_sim_policy_contacts')
    trace=contacts.module().ContactCapture(clock=lambda:10.)
    for label in ('table','infeed'):trace.observe(label,contacts.message())
    (tmp_path/'policy-contacts.json').write_text(json.dumps(trace.finish()))
    articulation,_=ready_trace();doc=articulation.finish()
    if fault=='incomplete':doc['summary']['status']='incomplete'
    elif fault=='invalid':doc['summary']['invalid_messages']=1
    elif fault=='truncated':doc['summary']['truncated']=True
    if fault!='missing':(tmp_path/'policy-articulation.json').write_text(json.dumps(doc))
    observer=NS(poll=lambda:None,terminate=lambda:None,wait=lambda **_:0)
    report,clean=job.close_contact_diagnostic(observer,NS(close=lambda:True),tmp_path,articulation=True)
    assert clean and report['verified']==(fault=='none')
    if fault=='none':assert len(report['articulation']['sha256'])==64


def test_stream_lost_during_homing_prevents_actual_policy_start(tmp_path,monkeypatch):
    job=importlib.import_module('sim_pick_place_policy_job');events=[];directory=tmp_path/'episode'
    def home_wait(**_):
        receipt=dict(success=True,purpose='startup_home_only',owner_final=dict(active_goal=None,owner_state='ready'))
        (directory/'startup/teacher-result.json').write_text(json.dumps(receipt))
        events.append('home-exited');return 0
    class Children:
        def __init__(self,*_):pass
        def start(self,name,*_,**kwargs):
            events.append(name)
            return NS(wait=home_wait,poll=lambda:None)
        def assert_alive(self):pass
    def require(_):
        events.append('freshness-check')
        if 'home-exited' in events:raise ValueError('articulation capture not clean and fresh')
    monkeypatch.setattr(job,'Children',Children)
    monkeypatch.setattr(job,'isolation_guard',lambda *_:None)
    monkeypatch.setattr(job,'camera_world',lambda *_:{})
    monkeypatch.setattr(job,'contact_world',lambda *_:dict(derived_sha256='fixture'))
    monkeypatch.setattr(job,'controller_readiness',lambda **_:None)
    monkeypatch.setattr(job,'wait_contacts',lambda *_:None)
    monkeypatch.setattr(job,'wait_articulation',lambda *_:None)
    monkeypatch.setattr(job,'require_articulation',require)
    monkeypatch.setattr(job,'close_contact_diagnostic',lambda *_,**__: (dict(verified=True),True))
    assert job.run(directory,contacts=True)==1
    assert events.count('freshness-check')==2 and 'policy' not in events
    assert events.index('freshness-check')<events.index('startup-home')<events.index('home-exited')
    result=json.loads((directory/'result.json').read_text())
    assert result['result']=='HOLD' and 'not clean and fresh' in result['error']
