"""One native job/checkpoint SIM study; never an operating Fleet policy approval."""
import hashlib
import json
import math
from pathlib import Path
import threading
import time
from uuid import uuid4

from omx_adapter.command_owner import ArmCommandOwner
from rosy.contracts.skill import AttemptIdentity
from rosy.execution.local.omx_policy import PolicyLease, owner_binding
from rosy.execution.local.policy_install import InstalledPolicy
from native_sim_inputs import write_json
from sim_study_scope import NativeStudyScope, native_scope, scope_live


class NativeSimStudyAuthority:
    def __init__(self,state,policy,owner,episode_id,*,monotonic=time.monotonic):
        if (type(owner) is not ArmCommandOwner or type(policy) is not InstalledPolicy
                or owner._monotonic is not monotonic or not isinstance(episode_id,str)
                or not episode_id or len(episode_id)>128):
            raise ValueError('explicit installed policy and same-clock dedicated study owner required')
        self.scope=native_scope(state)
        if type(self.scope) is not NativeStudyScope:
            raise ValueError('actual native study scope required')
        self.policy,self.owner,self.clock=policy,owner,monotonic
        self._config,self._session=owner.config,owner.session_id
        self._manifest=policy._manifest
        self._lock=threading.RLock()
        self._revoked=threading.Event()
        self.reason=''
        self._stop_initialized=False
        approval=json.loads(self.scope.approval)
        doc=policy.recheck()
        receipt=json.loads((policy.root/'sim-installation.json').read_text())
        if (doc['environment']!='sim' or doc['owner']!=owner_binding(owner)
                or owner.config.allowed_owners!=('learned_policy',)
                or not policy.root.is_relative_to(self.scope.state/'pick-place')
                or receipt['parent']['revision']!=approval['parent_policy_revision']
                or doc['normalization']['sha256']!=approval['normalization_sha256']
                or doc['dataset_revisions']!=[approval['dataset_revision']]):
            raise ValueError('native study approval and independently installed checkpoint differ')
        self.revision=doc['revision']
        self.episode_id=episode_id
        self.identity=AttemptIdentity('sim-study:'+approval['run_id'],'policy-evaluate','model-only',
            episode_id,owner.config.workcell_id,owner.config.instance_id,approval['campaign_sha256'],1,1)
        self._lease_id=str(uuid4())
        self._issued=self._now()
        self._deadline=self._issued+600_000_000_000
        self._last=self._issued
        self.directory=self.scope.state/'pick-place'
        self.directory.mkdir(mode=0o700,exist_ok=True)
        if self.directory.resolve()!=self.directory or self.directory.is_symlink():
            raise ValueError('canonical study evidence directory required')
        self.claim=self.directory/'study-claim.json'
        claim=dict(schema='rosy.omx-native-sim-study-claim/1',approval=approval,
            policy_revision=self.revision,episode_id=episode_id,owner_session_id=self._session,
            issued_owner_ns=self._issued,deadline_owner_ns=self._deadline,
            operating_fleet_approval='NOT_CLAIMED',physical_device_authority=False)
        write_json(self.claim,claim)
        self._claim=self.claim.read_bytes()
        if not self.valid():raise PermissionError('native study scope closed during initialization')

    def _now(self):
        value=self.clock()
        if type(value) not in (int,float) or not math.isfinite(value) or value<0:
            raise PermissionError('invalid native study steady clock')
        return int(value*1e9)

    def valid(self):
        with self._lock:
            if self._revoked.is_set():return False
            try:
                now=self._now()
                if (not self._last<=now<self._deadline or self.owner.config is not self._config
                        or self.owner.session_id!=self._session or self.owner.state not in ('ready','active')
                        or self.claim.read_bytes()!=self._claim
                        or (self.directory/'study-revoked.json').exists()
                        or (self.policy.root/'policy-artifact.json').read_bytes()!=self._manifest
                        or not scope_live(self.scope)):
                    raise PermissionError('native study scope or lifetime ended')
                self._last=now
                return True
            except Exception as error:
                self.reason=type(error).__name__
                self._revoked.set()
                return False

    def issue(self):
        with self._lock:
            if not self.valid():raise PermissionError('native study authority closed')
            now=self._now()
            return PolicyLease(self._lease_id,self.episode_id,self.revision,self.identity,now,
                               min(now+1_000_000_000,self._deadline),self._session)

    def current(self,lease):
        with self._lock:
            if not self.valid():return False
            now=self._now()
            if (type(lease) is not PolicyLease or lease.lease_id!=self._lease_id
                    or lease.episode_id!=self.episode_id or lease.policy_revision!=self.revision
                    or lease.identity!=self.identity or lease.owner_session_id!=self._session
                    or not self._issued<=lease.issued_at_ns<=now<lease.expires_at_ns<=self._deadline
                    or lease.expires_at_ns-lease.issued_at_ns>1_000_000_000):
                self.reason='study_lease_invalid_or_expired'
                self._revoked.set()
                return False
            return True

    def revoke(self,reason):
        with self._lock:
            self._revoked.set()
            self.reason=reason
            try:
                write_json(self.directory/'study-revoked.json',dict(reason=reason,
                    claim_sha256=hashlib.sha256(self._claim).hexdigest(),owner_ns=self._now()))
            except FileExistsError:
                pass

    def stop_path_once(self):
        with self._lock:
            if not self.valid():raise PermissionError('native study authority closed')
            if self._stop_initialized:raise FileExistsError('study stop fence already initialized')
            self._stop_initialized=True
            return self.directory/'study-stop.sqlite3'
