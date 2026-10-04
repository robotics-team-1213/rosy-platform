"""Minimal-authority configuration in deploy/site/site_functional_setup.py."""
import importlib.util
from pathlib import Path
import copy
import pytest
import os
import json
import sys
import types

SOURCE=Path(__file__).resolve().parents[1]/'deploy/site/site_functional_setup.py'
def module():
 spec=importlib.util.spec_from_file_location('site_functional_setup',SOURCE)
 result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result

USERS={'users':[{'principal_id':'operator-test','role':'operator','token_sha256':'a'*64}]}
CONFIG={'repo':'test/repo','health_url':'https://site.example.invalid/healthz','keep':3}

def test_plan_adds_viewer_preserves_existing_and_selects_enrolled_ids():
 users=copy.deepcopy(USERS);cfg=copy.deepcopy(CONFIG)
 next_users,next_config=module().build_plan(users,cfg,['robot-b','robot-a'],['camera-a'],'b'*64,'/etc/rosy/site/secrets/health.token')
 assert users==USERS and cfg==CONFIG
 assert next_users['users'][0]==USERS['users'][0]
 assert next_users['users'][1]['role']=='viewer'
 assert next_config['keep']==3
 assert next_config['functional_checks'][0]['required_ids']==['robot-a','robot-b']
 assert next_config['functional_checks'][1]['required_ids']==['camera-a']
 assert 'b'*64 not in str(next_config)

@pytest.mark.parametrize('changes',[
 {'users':{'users':[{'principal_id':'site-update-health','role':'operator','token_sha256':'a'*64}]}},
 {'digest':'a'*64},
 {'cfg':{**CONFIG,'functional_checks':[{'path':'custom','token_file':'existing','required_ids':['x']}]}}
])
def test_plan_refuses_existing_principal_digest_collision_and_local_check(changes):
 with pytest.raises(ValueError):module().build_plan(changes.get('users',USERS),changes.get('cfg',CONFIG),['r'],['s'],changes.get('digest','b'*64),'/etc/rosy/site/secrets/health.token')

def test_idempotent_plan_does_not_add_duplicate_user():
 m=module();users,cfg=m.build_plan(USERS,CONFIG,['r'],['s'],'b'*64,'/etc/rosy/site/secrets/health.token')
 users2,cfg2=m.build_plan(users,cfg,['r'],['s'],'b'*64,'/etc/rosy/site/secrets/health.token')
 assert users2==users and cfg2==cfg


class Host:
 def __init__(self, fail=False):self.state={'enabled':False,'active':True};self.events=[];self.fail=fail
 def timer(self):return dict(self.state)
 def stop_timer(self):self.events.append('stop');self.state={'enabled':False,'active':False}
 def restore_timer(self,state):self.events.append('restore');self.state=dict(state)
 def restart(self):self.events.append('restart')
 def guard(self):self.events.append('guard')
 def signed(self):self.events.append('signed')
 def verify(self):
  self.events.append('verify')
  if self.fail:self.fail=False;raise RuntimeError('injected unavailable functional API')


@pytest.fixture
def transaction(tmp_path,monkeypatch):
 if os.name=='nt':pytest.skip('Linux root ownership semantics; exercised separately on site host with temporary fixtures')
 m=module()
 # Ordinary site SSH user: only root ownership is simulated, bytes/modes/fsync are real.
 real_snapshot=m.snapshot
 def root_snapshot(path):
  entry=real_snapshot(path)
  if entry:entry.update(uid=0,gid=0)
  return entry
 monkeypatch.setattr(m,'snapshot',root_snapshot)
 monkeypatch.setattr(m.os,'fchown',lambda *args:None)
 targets={k:tmp_path/k for k in ('users','config','token')}
 for key in ('users','config'):m.replace(targets[key],m.document(('old-'+key).encode()))
 original={k:m.snapshot(p) for k,p in targets.items()}
 proposed={k:m.document(('new-'+k).encode()) for k in targets}
 host=Host();tx=m.Transaction(tmp_path/'journal',targets,host)
 return m,tx,original,proposed,host


def test_success_restores_timer_and_idempotence_avoids_restart(transaction):
 m,tx,old,new,host=transaction
 tx.apply(old,new)
 assert host.state=={'enabled':False,'active':True}
 assert not tx.journal.exists()
 assert {k:m.snapshot(p) for k,p in tx.targets.items()}==new
 host.events.clear();tx.apply(new,new)
 assert host.events==['verify']


def test_failed_verification_restores_exact_originals_and_removes_new_token(transaction):
 m,tx,old,new,host=transaction;host.fail=True
 with pytest.raises(RuntimeError):tx.apply(old,new)
 assert {k:m.snapshot(p) for k,p in tx.targets.items()}==old
 assert host.state=={'enabled':False,'active':True}
 assert not tx.journal.exists()


def test_prewrite_edit_is_preserved_and_timer_untouched(transaction):
 m,tx,old,new,host=transaction
 m.replace(tx.targets['users'],m.document(b'operator local change'))
 with pytest.raises(ValueError):tx.apply(old,new)
 assert tx.targets['users'].read_bytes()==b'operator local change'
 assert host.events==[] and not tx.journal.exists()


@pytest.mark.parametrize('switched',[0,1,2,3])
def test_interrupted_transaction_is_undone_before_next_attempt(transaction,switched):
 m,tx,old,new,host=transaction
 journal={'timer':host.timer(),'files':{k:[old[k],new[k]] for k in tx.targets}}
 m.replace(tx.journal,m.document(json.dumps(journal).encode()));host.stop_timer()
 for key in list(tx.targets)[:switched]:m.replace(tx.targets[key],new[key])
 tx.recover()
 assert {k:m.snapshot(p) for k,p in tx.targets.items()}==old
 assert host.state=={'enabled':False,'active':True}
 assert not tx.journal.exists()


@pytest.mark.parametrize('corruption',['backup','target'])
def test_recovery_validates_every_file_before_any_restoration(transaction,corruption):
 m,tx,old,new,host=transaction
 journal={'timer':host.timer(),'files':{k:[old[k],new[k]] for k in tx.targets}}
 for key in tx.targets:m.replace(tx.targets[key],new[key])
 if corruption=='backup':journal['files']['config'][0]['data']='Y29ycnVwdA=='
 else:m.replace(tx.targets['config'],m.document(b'unknown operator edit'))
 m.replace(tx.journal,m.document(json.dumps(journal).encode()))
 before={k:m.snapshot(p) for k,p in tx.targets.items()}
 with pytest.raises(ValueError):tx.recover()
 assert {k:m.snapshot(p) for k,p in tx.targets.items()}==before
 assert host.events==[] and tx.journal.exists()


def test_preserves_fleet_group_read_access_without_exposing_raw_token():
 m=module();old=m.document(b'old',0o440);old['gid']=10001
 new=m.updated(b'new',old)
 assert (new['mode'],new['uid'],new['gid'])==(0o440,0,10001)
 assert m.protected(new,'users') and not m.protected(new,'token')
 assert m.protected(m.document(b'config',0o644),'config')
 assert not m.protected(m.document(b'users',0o644),'users')


def test_real_host_verification_initializes_signed_runtime_during_recovery(monkeypatch,tmp_path):
 m=module();calls=[]
 paths=types.SimpleNamespace(link=tmp_path/'candidate',site_env=tmp_path/'env')
 paths.link.mkdir()
 io=types.SimpleNamespace(Http=lambda:None,Paths=lambda:paths,
  functional_reason=lambda *a:'',load_config=lambda p:{'health_url':'https://site.example.invalid/healthz','health_ca':None,'public_key':str(tmp_path/'key')},
  SERVICES=('fleet',),runtime_reason=lambda *a:'',read_env=lambda p:{'ROSY_SITE_IMAGE_TAG':'candidate'})
 class Updater:
  def __init__(self,*a,**k):calls.append('init');self._accepted_images={'candidate':{'fleet':['sha256:approved']}}
  def _verify(self,*a,**k):calls.append('signed')
  def _compose(self,*a,**k):return types.SimpleNamespace(stdout=json.dumps([{'Service':'fleet','Image':'rosy-site-fleet:candidate','ID':'example'}]) if a[1]=='ps' else 'fleet example')
  def _run(self,*a):return types.SimpleNamespace(stdout='sha256:approved')
  def _containers_reason(self,*a):calls.append('containers');return ''
 monkeypatch.setitem(sys.modules,'site_update_io',io)
 monkeypatch.setitem(sys.modules,'rosy_site_autoupdate',types.SimpleNamespace(SiteUpdater=Updater))
 host=m.Host({},tmp_path/'token');host.http=types.SimpleNamespace(status=lambda *a:200)
 host.verify()
 assert calls==['init','signed','containers']


def test_unavailable_recovery_restores_files_but_never_blindly_restarts(transaction):
 m,tx,old,new,host=transaction
 journal={'timer':host.timer(),'files':{k:[old[k],new[k]] for k in tx.targets}}
 m.replace(tx.journal,m.document(json.dumps(journal).encode()))
 for key in tx.targets:m.replace(tx.targets[key],new[key])
 def unavailable():raise RuntimeError('read-only idle proof unavailable')
 host.guard=unavailable
 with pytest.raises(RuntimeError):tx.recover()
 assert {k:m.snapshot(p) for k,p in tx.targets.items()}==old
 assert host.events==['signed','stop'] and tx.journal.exists()
 assert host.state=={'enabled':False,'active':False}


@pytest.mark.parametrize('restored',[0,1,2,3])
def test_recovery_resumes_after_each_rollback_write(transaction,restored):
 m,tx,old,new,host=transaction
 journal={'timer':host.timer(),'files':{k:[old[k],new[k]] for k in tx.targets}}
 m.replace(tx.journal,m.document(json.dumps(journal).encode()));host.stop_timer()
 for key in tx.targets:m.replace(tx.targets[key],new[key])
 for key in list(tx.targets)[:restored]:m.replace(tx.targets[key],old[key])
 tx.recover()
 assert {k:m.snapshot(p) for k,p in tx.targets.items()}==old
 assert host.state=={'enabled':False,'active':True} and not tx.journal.exists()


def test_invalid_recovery_timer_cannot_touch_files_or_restart(transaction):
 m,tx,old,new,host=transaction
 journal={'timer':{'enabled':'false','active':'false'},'files':{k:[old[k],new[k]] for k in tx.targets}}
 m.replace(tx.journal,m.document(json.dumps(journal).encode()))
 with pytest.raises(ValueError):tx.recover()
 assert {k:m.snapshot(p) for k,p in tx.targets.items()}==old and host.events==[]
