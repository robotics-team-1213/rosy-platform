"""HOST authority/latch tests with explicitly mocked kernel scope, no SIM acceptance."""
from dataclasses import replace
import json
import os
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/p) for p in ('test','deploy/robot/omx','learning/training/omx')]
from test_omx_sim_policy_install import inputs
from sim_policy_install import prepare_install
from sim_study_scope import NativeStudyScope
import sim_study_authority as study
from sim_study_stop import NativeSimStopFence


def case(tmp_path,monkeypatch):
    parent_root,parent,owner=inputs(tmp_path)
    state=tmp_path/'state';(state/'pick-place').mkdir(parents=True)
    clock=[10.];monotonic=lambda:clock[0]
    owner._monotonic=monotonic
    policy=prepare_install(parent_root,parent['revision'],state/'pick-place/installed',owner,
                           normalization_sha256=parent['normalization']['sha256'])
    approval=dict(schema='rosy.omx-native-policy-study-approval/1',source='operator_local',
        approval='isolated-policy-study',uid=os.getuid(),run_id='a'*40+'-'+'b'*12,
        source_revision='a'*40,policy_input=str(parent_root),campaign_sha256='c'*64,
        parent_policy_revision=parent['revision'],normalization_sha256=parent['normalization']['sha256'],
        dataset_revision=parent['dataset_revisions'][0])
    scope=NativeStudyScope(state,ROOT,parent_root,json.dumps(approval).encode(),b'{}',
        '/system.slice/rosy-native-sim-test.service','d'*64,'e'*64)
    live=[True]
    monkeypatch.setattr(study,'native_scope',lambda requested:scope)
    monkeypatch.setattr(study,'scope_live',lambda _:live[0])
    authority=study.NativeSimStudyAuthority(state,policy,owner,'episode',monotonic=monotonic)
    return authority,policy,owner,clock,monotonic,live


def test_scoped_lease_and_explicit_operator_stop_source(tmp_path,monkeypatch):
    authority,_,owner,*_=case(tmp_path,monkeypatch)
    lease=authority.issue()
    assert authority.current(lease)
    assert lease.identity.mission_id.startswith('sim-study:')
    fence=NativeSimStopFence(authority)
    status=fence.snapshot(workcell_id=owner.config.workcell_id,instance_id=owner.config.instance_id)
    assert status.source.value=='operator_local'
    assert status.reason=='OPERATOR_APPROVED_ISOLATED_SIM_STUDY'
    assert fence.is_open(authority_epoch=1,dispatch_generation=1)
    with pytest.raises(PermissionError):
        fence.rearm(authority_epoch=2,dispatch_generation=2,operator_confirmed=True,
                    fleet_fence_current=lambda *_:True)


def test_one_job_claim_blocks_new_authority_and_new_database_lifetime(tmp_path,monkeypatch):
    authority,policy,owner,_,clock,_=case(tmp_path,monkeypatch)
    NativeSimStopFence(authority)
    with pytest.raises((FileExistsError,PermissionError)):
        NativeSimStopFence(authority)
    with pytest.raises(FileExistsError):
        study.NativeSimStudyAuthority(authority.scope.state,policy,owner,'different-episode',monotonic=clock)


def test_same_scope_renewal_keeps_identity_and_original_lease_time(tmp_path,monkeypatch):
    authority,_,_,clock,*_=case(tmp_path,monkeypatch)
    original=authority.issue();clock[0]+=.1
    renewed=authority.issue()
    assert renewed.identity==original.identity and renewed.lease_id==original.lease_id
    assert renewed.expires_at_ns>original.expires_at_ns
    assert original.issued_at_ns==10_000_000_000
    assert authority.current(original) and authority.current(renewed)


@pytest.mark.parametrize('change',[dict(episode_id='other'),dict(policy_revision='f'*64),
                                   dict(owner_session_id='other')])
def test_wrong_scope_latches_without_reissuance(tmp_path,monkeypatch,change):
    authority,*_=case(tmp_path,monkeypatch)
    assert not authority.current(replace(authority.issue(),**change))
    with pytest.raises(PermissionError):authority.issue()


@pytest.mark.parametrize('fault',['expired_lease','expired_study','revoked','isolation'])
def test_expiry_revoke_or_isolation_loss_never_reopens(tmp_path,monkeypatch,fault):
    authority,_,_,clock,_,live=case(tmp_path,monkeypatch)
    lease=authority.issue()
    if fault=='expired_lease':clock[0]+=1.001
    elif fault=='expired_study':clock[0]+=600.001
    elif fault=='revoked':authority.revoke('operator_test')
    else:live[0]=False
    assert not authority.current(lease)
    live[0]=True
    with pytest.raises(PermissionError):authority.issue()


def test_final_stop_callback_failure_has_research_reason_and_persistent_latch(tmp_path,monkeypatch):
    authority,_,owner,*_=case(tmp_path,monkeypatch)
    fence=NativeSimStopFence(authority)
    with pytest.raises(PermissionError,match='study'):
        fence.run_if_open(authority_epoch=1,dispatch_generation=1,fleet_fence_current=lambda:False,
                          operation=lambda:pytest.fail('closed study dispatched'))
    status=fence.snapshot(workcell_id=owner.config.workcell_id,instance_id=owner.config.instance_id)
    assert status.source.value=='operator_local'
    assert 'FLEET' not in status.reason
    assert not fence.is_open(authority_epoch=1,dispatch_generation=1)
