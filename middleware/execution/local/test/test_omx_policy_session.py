import hashlib
import json
from pathlib import Path
import sys
from dataclasses import replace

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT/'middleware/execution/local/src'),str(ROOT/'contracts/learning/src'),
               str(ROOT/'contracts/skill/src'),str(ROOT/'src/products/omx/adapter'),
               str(ROOT/'src/products/omx/adapter/test'),str(ROOT/'src/contracts/foundation'),str(ROOT/'test')]
from rosy.execution.local.omx_policy import PolicyLease, PolicyCandidate, CameraSnapshot, OwnerPolicySession, owner_binding
from rosy.execution.local.policy_install import InstallBinding,load_policy
from rosy.contracts.skill import AttemptIdentity
from rosy.contracts.learning import seal
from omx_adapter.command_owner import ArmCommandOwner,JointStateSnapshot
from omx_adapter.local_stop import LocalStopController
from omx_adapter.action_store import ActionStore
from test_omx_command_owner import make_config,FakeActionClient
from test_learning_artifact_contracts import policy


def setup_session(tmp_path,enabled=True,camera=False,**session_options):
    clock=[10.0]; authority=[True]
    cfg=make_config(allowed_owners=('learned_policy',), velocity_limits={'joint_1':1,'joint_2':1},
                    acceleration_limits={'joint_1':10,'joint_2':10})
    client=FakeActionClient()
    owner=ArmCommandOwner(cfg,client,monotonic=lambda:clock[0],session_id='owner-session')
    root=tmp_path/'policy';root.mkdir()
    blob=b'host-fixture';(root/'model.bin').write_bytes(blob)
    ref=dict(path='model.bin',bytes=len(blob),sha256=hashlib.sha256(blob).hexdigest())
    doc=policy();names=list(cfg.joint_names)
    doc.update(joint_names=names,files=[ref],normalization=ref,evaluations=[ref],owner=owner_binding(owner))
    doc['observation'].update(names=names);doc['action'].update(names=names,limits=[list(cfg.position_limits[n]) for n in names])
    if camera:
        doc['cameras']=[dict(name='front',identity='cam-front',calibration_sha256='a'*64,
                            source_shape=[3,2,2],model_shape=[3,2,2],color='rgb',scale=1/255)]
    doc=seal(doc);(root/'policy-artifact.json').write_text(json.dumps(doc))
    binding=InstallBinding(policy_revision=doc['revision'],profile=doc['profile'],robot_type=doc['robot_type'],
        environment='sim',device_profile_revision=doc['device_profile_revision'],camera_profile_revision=doc['camera_profile_revision'],
        owner=doc['owner'],cameras=doc['cameras'],normalization_sha256=ref['sha256'],action_names=tuple(names),
        action_limits=tuple(tuple(x) for x in doc['action']['limits']),timing=doc['timing'])
    identity=AttemptIdentity('mission','step','action','attempt',cfg.workcell_id,cfg.instance_id,'a'*64,2,7)
    lease=PolicyLease('lease','episode',doc['revision'],identity,10_000_000_000,10_900_000_000,'owner-session')
    db=tmp_path/'owner.sqlite3';ActionStore(db)
    fence=LocalStopController(db,workcell_id=cfg.workcell_id,instance_id=cfg.instance_id)
    fence.rearm(authority_epoch=2,dispatch_generation=7,operator_confirmed=True,fleet_fence_current=lambda *_:True)
    session=OwnerPolicySession(load_policy(root,binding),owner,fence,lease,
        owner_identity=lambda:dict(workcell_id=cfg.workcell_id,instance_id=cfg.instance_id,
                                   simulation=True,profile=doc['device_profile_revision']),
        authority_current=lambda _:authority[0],monotonic=lambda:clock[0],enabled=enabled,
        camera_current=(lambda:(CameraSnapshot('front','cam-front','a'*64,(3,2,2),10_000_000_000,'c'*64),)) if camera else None,
        **session_options)
    session.observe(JointStateSnapshot({'joint_1':0.1,'joint_2':0.0},10,10.0,'cal-7'))
    return session,client,clock,authority,root


def candidate(session,**changes):
    values=dict(lease_id='lease',episode_id='episode',policy_revision=session.lease.policy_revision,
                sequence=10,observed_at_ns=10_000_000_000,produced_at_ns=10_000_000_000,
                positions=(0.101,0.001))
    values.update(changes)
    return PolicyCandidate(**values)


def test_default_disabled_never_dispatches(tmp_path):
    session,client,*_=setup_session(tmp_path,enabled=False)
    with pytest.raises(PermissionError):session.submit(candidate(session))
    assert not client.commands


def test_exact_candidate_reaches_existing_owner_through_real_fence(tmp_path):
    session,client,*_=setup_session(tmp_path)
    result=session.submit(candidate(session))
    assert result.accepted and len(client.commands)==1
    assert client.commands[0].owner=='learned_policy'
    assert client.commands[0].source_state_sequence==10


@pytest.mark.parametrize('change',[dict(lease_id='other'),dict(episode_id='other'),
    dict(policy_revision='b'*64),dict(sequence=9),dict(observed_at_ns=9_900_000_000),
    dict(produced_at_ns=10_000_000_001),dict(positions=(2,0))])
def test_bad_candidate_latches_without_submission(tmp_path,change):
    session,client,*_=setup_session(tmp_path)
    with pytest.raises(PermissionError):session.submit(candidate(session,**change))
    assert session.hold_reason and not client.commands
    with pytest.raises(PermissionError):session.submit(candidate(session))


def test_lease_expiry_cancels_active_policy_and_never_auto_recovers(tmp_path):
    session,client,clock,*_=setup_session(tmp_path)
    session.submit(candidate(session));clock[0]=11
    with pytest.raises(PermissionError):session.poll()
    assert client.handles[0].cancel_calls==1 and session.owner.state=='hold'
    clock[0]=10
    with pytest.raises(PermissionError):session.submit(candidate(session))
    assert len(client.commands)==1


def test_authority_revocation_is_rechecked_inside_fence(tmp_path):
    session,client,_,authority,*_=setup_session(tmp_path)
    authority[0]=False
    with pytest.raises(PermissionError):session.submit(candidate(session))
    assert not client.commands


def test_mutated_artifact_blocks_final_submission(tmp_path):
    session,client,_,_,root=setup_session(tmp_path)
    (root/'model.bin').write_bytes(b'changed')
    with pytest.raises(PermissionError):session.submit(candidate(session))
    assert not client.commands


def test_stale_observation_poll_cancels_active_goal(tmp_path):
    session,client,clock,*_=setup_session(tmp_path)
    session.submit(candidate(session));clock[0]=10.051
    with pytest.raises(PermissionError):session.poll()
    assert client.handles[0].cancel_calls==1


@pytest.mark.parametrize('method',['poll','renew'])
def test_authority_permission_error_latches_and_cancels(tmp_path,method):
    session,client,*_=setup_session(tmp_path)
    session.submit(candidate(session))
    def unavailable(_):raise PermissionError('issuer unavailable')
    session._authority=unavailable
    with pytest.raises(PermissionError):
        if method=='poll':session.poll()
        else:session.renew(replace(session.lease,expires_at_ns=10_950_000_000))
    assert session.hold_reason and client.handles[0].cancel_calls==1


def test_renew_keeps_exact_identity_and_does_not_clear_hold(tmp_path):
    session,client,*_=setup_session(tmp_path)
    renewed=replace(session.lease,expires_at_ns=10_950_000_000)
    session.renew(renewed)
    assert session.lease==renewed
    changed=replace(renewed,identity=replace(renewed.identity,dispatch_generation=8),expires_at_ns=10_990_000_000)
    with pytest.raises(PermissionError):session.renew(changed)
    with pytest.raises(PermissionError):session.renew(replace(renewed,expires_at_ns=10_990_000_000))
    assert not client.commands


def test_revocation_between_checks_blocks_at_real_stop_fence(tmp_path):
    session,client,*_=setup_session(tmp_path)
    calls=[]
    def changing(_):calls.append(1);return len(calls)==1
    session._authority=changing
    with pytest.raises(PermissionError):session.submit(candidate(session))
    assert not client.commands
    assert not session.fence.is_open(authority_epoch=2,dispatch_generation=7)


@pytest.mark.parametrize('clock',[9.9,11.0])
def test_rollback_or_expired_clock_never_dispatches(tmp_path,clock):
    session,client,time,*_=setup_session(tmp_path)
    time[0]=clock
    with pytest.raises(PermissionError):session.submit(candidate(session))
    assert not client.commands


def test_physical_identity_change_cancels_policy(tmp_path):
    session,client,*_=setup_session(tmp_path)
    session.submit(candidate(session))
    session._identity=lambda:dict(simulation=False)
    with pytest.raises(PermissionError):session.poll()
    assert client.handles[0].cancel_calls==1


def test_changed_owner_envelope_cancels_policy(tmp_path):
    session,client,*_=setup_session(tmp_path)
    session.submit(candidate(session))
    session.owner.config=replace(session.owner.config,calibration_revision='other')
    with pytest.raises(PermissionError):session.poll()
    assert client.handles[0].cancel_calls==1


def test_observation_change_inside_final_fence_rejects_old_candidate(tmp_path):
    session,client,*_=setup_session(tmp_path)
    calls=[]
    def changing(_):
        calls.append(1)
        if len(calls)==2:
            session.observe(JointStateSnapshot({'joint_1':0.12,'joint_2':0.0},11,10.0,'cal-7'))
        return True
    session._authority=changing
    with pytest.raises(PermissionError):session.submit(candidate(session))
    assert not client.commands


def test_clock_advance_in_fence_invalidates_action_before_owner(tmp_path):
    session,client,clock,*_=setup_session(tmp_path)
    calls=[]
    def changing(_):
        calls.append(1)
        if len(calls)==2:clock[0]=11
        return True
    session._authority=changing
    with pytest.raises(PermissionError):session.submit(candidate(session))
    assert not client.commands


def test_authority_latency_expiry_in_final_guard_never_dispatches(tmp_path):
    session,client,clock,*_=setup_session(tmp_path)
    session._lease=replace(session.lease,expires_at_ns=10_030_000_000)
    calls=[]
    def delayed(_):
        calls.append(1)
        if len(calls)==3:clock[0]=10.04
        return True
    session._authority=delayed
    with pytest.raises(PermissionError):session.submit(candidate(session))
    assert session.hold_reason and not client.commands


def test_observation_failure_latches_and_cancels_active_command(tmp_path):
    session,client,*_=setup_session(tmp_path)
    session.submit(candidate(session))
    with pytest.raises(PermissionError):session.observe(None)
    assert session.hold_reason and client.handles[0].cancel_calls==1


def test_exact_camera_frame_reaches_owner(tmp_path):
    session,client,*_=setup_session(tmp_path,camera=True)
    assert session.submit(candidate(session,camera_frames=('c'*64,))).accepted
    assert len(client.commands)==1


@pytest.mark.parametrize('change',[dict(name='other'),dict(identity='other'),dict(calibration_sha256='b'*64),
    dict(source_shape=(3,4,4)),dict(received_at_ns=9_900_000_000),dict(received_at_ns=10_000_000_001),
    dict(frame_sha256='d'*64)])
def test_camera_mismatch_never_dispatches(tmp_path,change):
    session,client,*_=setup_session(tmp_path,camera=True)
    camera=session._cameras()[0]
    session._cameras=lambda:(replace(camera,**change),)
    with pytest.raises(PermissionError):session.submit(candidate(session,camera_frames=('c'*64,)))
    assert session.hold_reason and not client.commands


def test_missing_camera_provider_never_dispatches(tmp_path):
    session,client,*_=setup_session(tmp_path,camera=True)
    session._cameras=None
    with pytest.raises(PermissionError):session.submit(candidate(session,camera_frames=('c'*64,)))
    assert not client.commands


def test_camera_change_in_final_authority_callback_rejects_old_frame(tmp_path):
    session,client,*_=setup_session(tmp_path,camera=True)
    camera=session._cameras()[0];calls=[]
    def changing(_):
        calls.append(1)
        if len(calls)==3:session._cameras=lambda:(replace(camera,frame_sha256='d'*64),)
        return True
    session._authority=changing
    with pytest.raises(PermissionError):session.submit(candidate(session,camera_frames=('c'*64,)))
    assert not client.commands


def test_camera_provider_delay_cannot_bypass_short_lease(tmp_path):
    session,client,clock,*_=setup_session(tmp_path,camera=True)
    session._lease=replace(session.lease,expires_at_ns=10_030_000_000)
    camera=session._cameras()[0]
    def delayed():clock[0]=10.04;return (camera,)
    session._cameras=delayed
    with pytest.raises(PermissionError):session.submit(candidate(session,camera_frames=('c'*64,)))
    assert not client.commands


def test_camera_provider_failure_cancels_active_command(tmp_path):
    session,client,*_=setup_session(tmp_path,camera=True)
    session.submit(candidate(session,camera_frames=('c'*64,)))
    def unavailable():raise RuntimeError('capture unavailable')
    session._cameras=unavailable
    with pytest.raises(PermissionError):session.poll()
    assert client.handles[0].cancel_calls==1


def test_camera_arriving_after_action_production_never_dispatches(tmp_path):
    session,client,clock,*_=setup_session(tmp_path,camera=True)
    camera=replace(session._cameras()[0],received_at_ns=10_010_000_000)
    session._cameras=lambda:(camera,);clock[0]=10.02
    with pytest.raises(PermissionError):session.submit(candidate(session,camera_frames=('c'*64,)))
    assert not client.commands


@pytest.mark.parametrize('inside_fence',[False,True])
def test_fresh_original_observation_survives_bounded_joint_update(tmp_path,inside_fence):
    session,client,clock,*_=setup_session(tmp_path)
    clock[0]=10.02
    snapshot=JointStateSnapshot({'joint_1':0.102,'joint_2':0.002},11,10.01,'cal-7')
    if inside_fence:
        calls=[]
        def updating(_):
            calls.append(1)
            if len(calls)==3:session.observe(snapshot)
            return True
        session._authority=updating
    else:session.observe(snapshot)
    assert session.submit(candidate(session,produced_at_ns=10_015_000_000)).accepted
    command=client.commands[0]
    assert command.source_state_sequence==10
    assert dict(command.expected_start_state_positions)=={'joint_1':0.1,'joint_2':0.0}


@pytest.mark.parametrize('mode',['stale','moved','timestamp','evicted'])
def test_invalid_historical_input_never_dispatches(tmp_path,mode):
    session,client,clock,*_=setup_session(tmp_path,observation_history_capacity=1 if mode=='evicted' else 64)
    clock[0]=10.06 if mode=='stale' else 10.02
    session.observe(JointStateSnapshot({'joint_1':0.12 if mode=='moved' else 0.1,'joint_2':0.0},11,clock[0],'cal-7'))
    action=candidate(session,produced_at_ns=int(clock[0]*1e9),
                     observed_at_ns=10_000_000_001 if mode=='timestamp' else 10_000_000_000)
    with pytest.raises(PermissionError):session.submit(action)
    assert session.hold_reason and not client.commands


@pytest.mark.parametrize('capacity',[0,-1,4097,True,1.5])
def test_invalid_observation_history_capacity(tmp_path,capacity):
    with pytest.raises(ValueError,match='history capacity'):
        setup_session(tmp_path,observation_history_capacity=capacity)


@pytest.mark.parametrize('mode',['stale','moved','evicted'])
def test_historical_source_invalidated_inside_final_authority_is_rejected(tmp_path,mode):
    session,client,clock,*_=setup_session(tmp_path,observation_history_capacity=1 if mode=='evicted' else 64)
    calls=[]
    def changing(_):
        calls.append(1)
        if len(calls)==3:
            clock[0]=10.06 if mode=='stale' else 10.02
            session.observe(JointStateSnapshot({'joint_1':0.12 if mode=='moved' else 0.1,'joint_2':0.0},
                                               11,clock[0],'cal-7'))
        return True
    session._authority=changing
    with pytest.raises(PermissionError):session.submit(candidate(session))
    assert session.hold_reason and not client.commands


def test_final_callback_cannot_widen_installed_source_tolerance(tmp_path):
    session,client,*_=setup_session(tmp_path)
    calls=[]
    def widening(_):
        calls.append(1)
        if len(calls)==3:
            session.owner.config=replace(session.owner.config,max_start_state_tolerances={'joint_1':0.1,'joint_2':0.1})
            session.observe(JointStateSnapshot({'joint_1':0.12,'joint_2':0.0},11,10.0,'cal-7'))
        return True
    session._authority=widening
    with pytest.raises(PermissionError):session.submit(candidate(session))
    assert session.hold_reason and not client.commands
