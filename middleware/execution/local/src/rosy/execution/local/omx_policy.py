"""Default-disabled SIM policy session over the existing owner and stop fence.

The authority provider must validate an installed policy and a currently authorized
local lease. This module defines no issuer, network endpoint, promotion or recovery.
"""
from dataclasses import dataclass, fields
from collections import OrderedDict
import hashlib
import inspect
import json
import math
from pathlib import Path
import threading
import time
from uuid import uuid4

from rosy.contracts.skill import AttemptIdentity
from omx_adapter.command_owner import ArmCommandOwner, TrajectoryCommand, JointStateSnapshot
from omx_adapter.local_stop import LocalStopController
from .policy_install import InstalledPolicy


def _ns(value):
    if type(value) is not int or not 0 <= value < 2**63:
        raise ValueError('nonnegative integer owner-monotonic nanoseconds required')


def _text(value):
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError('explicit trimmed identity required')


def _sha(value):
    if not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('lowercase SHA256 required')


@dataclass(frozen=True)
class CameraSnapshot:
    """Metadata from trusted local capture; timestamps use the owner clock."""
    name: str
    identity: str
    calibration_sha256: str
    source_shape: tuple
    received_at_ns: int
    frame_sha256: str

    def __post_init__(self):
        _text(self.name);_text(self.identity)
        _sha(self.calibration_sha256);_sha(self.frame_sha256);_ns(self.received_at_ns)
        shape=tuple(self.source_shape)
        if len(shape)!=3 or any(type(v) is not int or v<=0 for v in shape):
            raise ValueError('positive integer camera CHW shape required')
        object.__setattr__(self,'source_shape',shape)


@dataclass(frozen=True)
class PolicyLease:
    lease_id: str
    episode_id: str
    policy_revision: str
    identity: AttemptIdentity
    issued_at_ns: int
    expires_at_ns: int
    owner_session_id: str

    def __post_init__(self):
        for value in (self.lease_id,self.episode_id,self.policy_revision,self.owner_session_id): _text(value)
        if not isinstance(self.identity, AttemptIdentity): raise ValueError('AttemptIdentity required')
        _ns(self.issued_at_ns); _ns(self.expires_at_ns)
        if self.expires_at_ns <= self.issued_at_ns: raise ValueError('lease expiry must follow issuance')


@dataclass(frozen=True)
class PolicyCandidate:
    lease_id: str
    episode_id: str
    policy_revision: str
    sequence: int
    observed_at_ns: int
    produced_at_ns: int
    positions: tuple
    camera_frames: tuple = ()
    camera_received_at_ns: tuple = ()

    def __post_init__(self):
        for value in (self.lease_id,self.episode_id,self.policy_revision): _text(value)
        for value in (self.sequence,self.observed_at_ns,self.produced_at_ns): _ns(value)
        positions=tuple(self.positions)
        if not positions or any(type(v) not in (float,int) or not math.isfinite(v) for v in positions):
            raise ValueError('finite joint targets required')
        object.__setattr__(self,'positions',positions)
        frames=tuple(self.camera_frames)
        for frame in frames:_sha(frame)
        object.__setattr__(self,'camera_frames',frames)
        stamps=tuple(self.camera_received_at_ns)
        for stamp in stamps:_ns(stamp)
        object.__setattr__(self,'camera_received_at_ns',stamps)


def owner_binding(owner):
    """Bind source bytes and the effective owner envelope, not a caller stage string."""
    config={field.name:getattr(owner.config,field.name) for field in fields(owner.config)}
    for name,value in list(config.items()):
        if hasattr(value,'items'): config[name]=dict(value)
    payload=json.dumps(config,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    source=Path(inspect.getfile(ArmCommandOwner)).read_bytes()
    return dict(kind='omx_local_controller',controller_revision='sha256:'+hashlib.sha256(source).hexdigest(),
                envelope_revision='sha256:'+hashlib.sha256(payload).hexdigest())


class OwnerPolicySession:
    """One lease/episode; all faults latch HOLD and never release owner/local stop."""
    def __init__(self,policy,owner,fence,lease,*,authority_current,owner_identity,monotonic=time.monotonic,
                 enabled=False,max_lease_duration_ns=1_000_000_000,camera_current=None,
                 observation_history_capacity=64,execution_journal=None):
        if not isinstance(policy,InstalledPolicy) or not isinstance(owner,ArmCommandOwner):
            raise ValueError('installed policy and existing OMX owner required')
        if not isinstance(fence,LocalStopController) or not isinstance(lease,PolicyLease):
            raise ValueError('existing persistent stop fence and scoped lease required')
        if type(enabled) is not bool or not callable(authority_current) or not callable(owner_identity):
            raise ValueError('explicit local authority provider and enabled flag required')
        _ns(max_lease_duration_ns)
        if max_lease_duration_ns==0: raise ValueError('positive installed lease budget required')
        if type(observation_history_capacity) is not int or not 1<=observation_history_capacity<=4096:
            raise ValueError('observation history capacity must be an integer from 1 to 4096')
        self.policy,self.owner,self.fence=policy,owner,fence
        self._lease=lease; self._authority=authority_current; self._clock=monotonic
        self._identity=owner_identity
        if camera_current is not None and not callable(camera_current):raise ValueError('local camera provider required')
        self._cameras=camera_current
        if execution_journal is not None:
            from .policy_journal import PolicyExecutionJournal
            if not isinstance(execution_journal,PolicyExecutionJournal):
                raise ValueError('native policy execution journal required')
        self._execution_journal=execution_journal
        self.enabled=enabled;self._ttl=max_lease_duration_ns
        self._lock=threading.RLock();self._snapshot=None;self._active_command=None
        self._history=OrderedDict();self._history_capacity=observation_history_capacity
        self._camera_history=OrderedDict()
        self._last_now=None;self._last_submit=None;self.hold_reason='';self.cancel_decision=None
        self._owner_session=owner.session_id
        self._config=owner.config
        self._binding()

    @property
    def lease(self): return self._lease

    def _owner_current(self):
        self._check_hold()
        if self.owner.config is not self._config or self.owner.session_id!=self._owner_session:
            self._fail('policy_owner_binding_changed')

    def _check_hold(self):
        if self.hold_reason:raise PermissionError(self.hold_reason)

    def _stop_open(self):
        identity=self.lease.identity
        if not self.fence.is_open(authority_epoch=identity.authority_epoch,dispatch_generation=identity.dispatch_generation):
            self._fail('local_stop_closed')

    def _binding(self):
        doc=self.policy.recheck();cfg=self.owner.config;identity=self.lease.identity
        if doc['profile']!='omx_joint_target_v1' or doc['environment']!='sim':
            raise ValueError('only the isolated OMX SIM policy profile is supported')
        observed=self._identity()
        self._owner_current()
        if (not isinstance(observed,dict) or observed.get('simulation') is not True
                or (observed.get('workcell_id'),observed.get('instance_id'))!=(cfg.workcell_id,cfg.instance_id)
                or observed.get('profile')!=doc['device_profile_revision']):
            raise ValueError('current owner identity does not confirm installed SIM scope')
        if doc['owner']!=owner_binding(self.owner) or tuple(doc['joint_names'])!=cfg.joint_names:
            raise ValueError('installed policy does not bind this controller/config/joint order')
        if not cfg.enabled or 'learned_policy' not in cfg.allowed_owners:
            raise ValueError('existing owner does not admit learned_policy')
        if any(getattr(cfg,name) is None for name in ('velocity_limits','acceleration_limits','max_start_state_tolerances')):
            raise ValueError('explicit owner rate and start-state limits required')
        if ((identity.workcell_id,identity.instance_id)!=(cfg.workcell_id,cfg.instance_id)
                or (self.fence.workcell_id,self.fence.instance_id)!=(cfg.workcell_id,cfg.instance_id)
                or self.owner.session_id!=self._owner_session
                or self.lease.owner_session_id!=self.owner.session_id
                or self.lease.policy_revision!=doc['revision']):
            raise ValueError('lease/fence/owner/policy scope differs')
        return doc

    def _fail(self,reason):
        if not self.hold_reason:
            self.hold_reason=reason
            if self._active_command is not None:
                self.cancel_decision=self.owner.cancel(command_id=self._active_command,owner='learned_policy')
        raise PermissionError(self.hold_reason)

    def _now(self):
        value=self._clock()
        self._check_hold()
        if type(value) not in (int,float) or not math.isfinite(value) or value<0:
            self._fail('invalid_owner_clock')
        now=int(value*1_000_000_000)
        if self._last_now is not None and now<self._last_now: self._fail('owner_clock_rollback')
        self._last_now=now
        return now

    def _lease_time(self,lease,now):
        if (lease.expires_at_ns-lease.issued_at_ns>self._ttl
                or not lease.issued_at_ns<=now<lease.expires_at_ns):
            self._fail('policy_lease_expired_or_invalid')

    def _check_lease(self,lease,now):
        self._lease_time(lease,now)
        if self._authority(lease) is not True: self._fail('policy_authority_stale')
        now=self._now()
        self._lease_time(lease,now)
        return now

    def _guard(self):
        if self.hold_reason: raise PermissionError(self.hold_reason)
        if not self.enabled: self._fail('policy_session_disabled')
        doc=self._binding()
        self._check_lease(self.lease,self._now())
        cameras=()
        if doc['cameras']:
            if self._cameras is None:self._fail('policy_camera_missing')
            cameras=tuple(self._cameras())
            if len(cameras)!=len(doc['cameras']):self._fail('policy_camera_count')
            for snapshot,expected in zip(cameras,doc['cameras']):
                if (not isinstance(snapshot,CameraSnapshot)
                        or (snapshot.name,snapshot.identity,snapshot.calibration_sha256,snapshot.source_shape)!=
                           (expected['name'],expected['identity'],expected['calibration_sha256'],tuple(expected['source_shape']))):
                    self._fail('policy_camera_binding')
        now=self._now()
        self._lease_time(self.lease,now)
        self._owner_current()
        self._stop_open()
        now=self._now()
        self._lease_time(self.lease,now)
        self._owner_current()
        self._fresh(doc,now,cameras)
        if cameras:
            key=(tuple(c.frame_sha256 for c in cameras),tuple(c.received_at_ns for c in cameras))
            self._camera_history[key]=cameras
            self._camera_history.move_to_end(key)
            while len(self._camera_history)>self._history_capacity:self._camera_history.popitem(last=False)
        return doc,now,cameras

    def _fresh(self,doc,now,cameras):
        if self._snapshot is None: self._fail('policy_observation_missing')
        stamp=int(self._snapshot.received_at*1_000_000_000)
        if not 0<=now-stamp<=doc['timing']['max_observation_age_ns']:
            self._fail('policy_observation_stale')
        if any(not 0<=now-c.received_at_ns<=doc['timing']['max_observation_age_ns'] for c in cameras):
            self._fail('policy_camera_stale')

    def observe(self,snapshot):
        with self._lock:
            try:
                if self.hold_reason: raise PermissionError(self.hold_reason)
                if not isinstance(snapshot,JointStateSnapshot):self._fail('policy_observation_type')
                if not self.owner.observe_joint_state(snapshot): self._fail('owner_observation_rejected')
                self._snapshot=snapshot
                self._history[snapshot.sequence]=snapshot
                while len(self._history)>self._history_capacity:self._history.popitem(last=False)
            except PermissionError:
                if not self.hold_reason:self._fail('policy_observation_unavailable')
                raise
            except Exception as exc:self._fail('policy_observation_validation:'+type(exc).__name__)

    def capture_observation(self):
        """Freeze guarded metadata; composition must supply its exact RGB bytes."""
        with self._lock:
            try:
                _,_,cameras=self._guard()
                return self._snapshot,cameras
            except PermissionError:
                if not self.hold_reason:self._fail('policy_capture_authority_closed')
                raise
            except Exception as exc:self._fail('policy_capture_validation:'+type(exc).__name__)

    def _camera_source(self,candidate,doc,now,current):
        if candidate.camera_received_at_ns:
            if (len(candidate.camera_frames)!=len(doc['cameras'])
                    or len(candidate.camera_received_at_ns)!=len(doc['cameras'])):
                self._fail('policy_camera_source_count')
            source=self._camera_history.get((candidate.camera_frames,candidate.camera_received_at_ns))
            if source is None:self._fail('policy_camera_source_unknown')
        else:
            source=current
            if candidate.camera_frames!=tuple(c.frame_sha256 for c in source):self._fail('policy_camera_frame_mismatch')
        if any(not 0<=now-c.received_at_ns<=doc['timing']['max_observation_age_ns'] for c in source):
            self._fail('policy_camera_source_stale')
        if any(c.received_at_ns>candidate.produced_at_ns for c in source):self._fail('policy_camera_action_causality')
        return source

    def _source(self,candidate,doc,now):
        source=self._history.get(candidate.sequence)
        if (source is None or candidate.sequence>self._snapshot.sequence
                or candidate.observed_at_ns!=int(source.received_at*1_000_000_000)):
            self._fail('policy_candidate_scope_or_observation')
        if not 0<=now-candidate.observed_at_ns<=doc['timing']['max_observation_age_ns']:
            self._fail('policy_source_observation_stale')
        self._owner_current()
        cfg=self._config
        if source.calibration_revision!=cfg.calibration_revision:
            self._fail('policy_source_calibration')
        if any(abs(self._snapshot.positions[name]-source.positions[name])>cfg.max_start_state_tolerances[name]
               for name in cfg.joint_names):
            self._fail('policy_source_start_state_changed')
        return source

    def submit(self,candidate):
        with self._lock:
            try:
                doc,now,cameras=self._guard()
                if not isinstance(candidate,PolicyCandidate): self._fail('policy_candidate_type')
                lease=self.lease
                if ((candidate.lease_id,candidate.episode_id,candidate.policy_revision)!=
                        (lease.lease_id,lease.episode_id,lease.policy_revision)):
                    self._fail('policy_candidate_scope_or_observation')
                self._source(candidate,doc,now)
                self._camera_source(candidate,doc,now,cameras)
                if not candidate.observed_at_ns<=candidate.produced_at_ns<=now:
                    self._fail('policy_action_clock')
                if now-candidate.produced_at_ns>doc['timing']['max_action_age_ns']:
                    self._fail('policy_action_stale')
                if len(candidate.positions)!=len(doc['joint_names']) or any(
                        not low<=value<=high for value,(low,high) in zip(candidate.positions,doc['action']['limits'])):
                    self._fail('policy_action_envelope')
                if self._last_submit is not None and now-self._last_submit<doc['timing']['period_ns']:
                    self._fail('policy_period_not_elapsed')
                def final_submit():
                    _,final_now,final_cameras=self._guard()
                    source=self._source(candidate,doc,final_now)
                    self._camera_source(candidate,doc,final_now,final_cameras)
                    if final_now-candidate.produced_at_ns>doc['timing']['max_action_age_ns']:
                        self._fail('policy_action_stale_at_submit')
                    cfg=self._config
                    command=TrajectoryCommand(workcell_id=cfg.workcell_id,instance_id=cfg.instance_id,
                        command_id=str(uuid4()),session_id=self.owner.session_id,owner='learned_policy',
                        positions=dict(zip(cfg.joint_names,candidate.positions)),
                        duration_s=doc['timing']['period_ns']/1_000_000_000,source_state_sequence=candidate.sequence,
                        calibration_revision=cfg.calibration_revision,joint_names=cfg.joint_names,
                        expected_start_state_positions=dict(source.positions),
                        start_state_tolerances=dict(cfg.max_start_state_tolerances))
                    if self._execution_journal is not None:
                        self._execution_journal.prepare(self.lease,candidate,command)
                        # Storage can block while authority, installed bytes or
                        # owner/camera identity changes. Re-admit after commit
                        # inside the existing final submission fence.
                        _,_,final_cameras=self._guard()
                    self._stop_open()
                    final_now=self._now()
                    self._lease_time(self.lease,final_now)
                    self._fresh(doc,final_now,final_cameras)
                    self._source(candidate,doc,final_now)
                    self._camera_source(candidate,doc,final_now,final_cameras)
                    if final_now-candidate.produced_at_ns>doc['timing']['max_action_age_ns']:
                        self._fail('policy_action_stale_at_submit')
                    self._check_hold()
                    decision=self.owner.submit(command)
                    if not decision.accepted: self._fail('owner_rejected:'+decision.reason)
                    self._active_command=command.command_id;self._last_submit=final_now
                    return decision
                identity=lease.identity
                return self.fence.run_if_open(authority_epoch=identity.authority_epoch,
                    dispatch_generation=identity.dispatch_generation,
                    fleet_fence_current=lambda:self._authority(self.lease) is True,operation=final_submit)
            except PermissionError:
                if not self.hold_reason:self._fail('local_stop_or_authority_closed')
                raise
            except Exception as exc:
                self._fail('policy_submit_validation:'+type(exc).__name__)

    def poll(self):
        with self._lock:
            try:
                self._guard()
                identity=self.lease.identity
                if not self.fence.is_open(authority_epoch=identity.authority_epoch,dispatch_generation=identity.dispatch_generation):
                    self._fail('local_stop_closed')
                result=self.owner.poll()
                if self.owner.state=='hold':self._fail('owner_hold')
                return result
            except PermissionError:
                if not self.hold_reason:self._fail('policy_poll_authority_closed')
                raise
            except Exception as exc:self._fail('policy_poll_validation:'+type(exc).__name__)

    def renew(self,lease):
        with self._lock:
            try:
                doc,now,cameras=self._guard()
                old=self.lease
                if (not isinstance(lease,PolicyLease) or (lease.lease_id,lease.episode_id,lease.policy_revision,lease.identity)!=
                        (old.lease_id,old.episode_id,old.policy_revision,old.identity)
                        or lease.owner_session_id!=old.owner_session_id
                        or lease.issued_at_ns<old.issued_at_ns or lease.expires_at_ns<=old.expires_at_ns):
                    self._fail('policy_lease_changed')
                self._check_lease(lease,now)
                self._owner_current();self._stop_open()
                now=self._now()
                self._lease_time(old,now);self._lease_time(lease,now)
                self._owner_current();self._fresh(doc,now,cameras)
                self._check_hold();self._lease=lease
            except PermissionError:
                if not self.hold_reason:self._fail('policy_renew_authority_closed')
                raise
            except Exception as exc:self._fail('policy_renew_validation:'+type(exc).__name__)
