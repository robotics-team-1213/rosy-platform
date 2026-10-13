"""Private owner-injected CORE trial restriction; never a safety approval.

Bounds require independently validated device evidence. No public API/config
arms this object. One canonical ledger covers the user's entire authorization.
Reopening that ledger consumes the trial; it never resumes interrupted motion.
"""
from dataclasses import asdict, dataclass
from contextlib import contextmanager
import json
import math
from pathlib import Path
import sqlite3
import threading
import time


@dataclass(frozen=True)
class Bounds:
    speed_max_mps: float
    angular_max_radps: float
    decel_min_mps2: float
    latency_max_s: float
    source_age_max_s: float
    sample_gap_max_s: float
    measurement_error_m: float
    path_scale_upper: float
    duration_s: float
    evidence_sha256: str

    def validate(self):
        for name, value in asdict(self).items():
            if name == 'evidence_sha256':
                if not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
                    raise ValueError('measured bounds evidence hash required')
            elif type(value) not in (int,float) or not math.isfinite(value) or value<=0:
                raise ValueError('finite positive measured bound required: '+name)
        if self.path_scale_upper<1:raise ValueError('path upper scale cannot underestimate')


class BoundedTrial:
    def __init__(self,path,*,trial_id,robot_id,boot_id,frame_id,bounds,now=None):
        if type(bounds) is not Bounds:raise ValueError('exact measured Bounds required')
        bounds.validate()
        if any(not isinstance(x,str) or not x for x in [trial_id,robot_id,boot_id,frame_id]):
            raise ValueError('trial/robot/boot/frame identity required')
        path=Path(path).absolute()
        if any(p.is_symlink() or (hasattr(p,'is_junction') and p.is_junction()) for p in [path,*path.parents]):
            raise ValueError('trial ledger links refused')
        self.bounds=bounds;self.frame_id=frame_id;self._lock=threading.RLock()
        self._db=sqlite3.connect(path,timeout=.05,check_same_thread=False)
        self._db.execute('PRAGMA synchronous=FULL')
        self._db.execute('CREATE TABLE IF NOT EXISTS trial (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL)')
        current=time.monotonic() if now is None else now
        if type(current) not in (int,float) or not math.isfinite(current):raise ValueError('finite clock required')
        self._identity=dict(trial_id=trial_id,robot_id=robot_id,boot_id=boot_id,frame_id=frame_id,
                            bounds=asdict(bounds),limit_m=.20)
        with self._db:
            self._db.execute('BEGIN IMMEDIATE')
            row=self._db.execute('SELECT body FROM trial WHERE id=1').fetchone()
            if row:
                state=json.loads(row[0])
                if state['identity']!=self._identity:raise ValueError('trial identity/envelope cannot change')
                state.update(reason='reopened_trial',halted=True)
            else:
                state=dict(identity=self._identity,issued=False,halted=False,reason='awaiting_pose',
                           path_upper_m=0.,pose=None,deadline=current+bounds.duration_s)
            self._write(state)

    def _read(self,*,check_owner=True):
        state=json.loads(self._db.execute('SELECT body FROM trial WHERE id=1').fetchone()[0])
        if state['identity']!=self._identity:raise ValueError('trial ledger identity differs')
        if check_owner and (type(self.bounds) is not Bounds or asdict(self.bounds)!=self._identity['bounds']
                            or self.frame_id!=self._identity['frame_id']):
            raise ValueError('bound trial envelope cannot change')
        return state

    def _write(self,state):
        self._db.execute('INSERT OR REPLACE INTO trial VALUES (1,?)',(json.dumps(state,sort_keys=True,allow_nan=False),))

    @contextmanager
    def _transaction(self):
        with self._lock,self._db:
            # sqlite connection context alone does NOT begin a read snapshot.
            # Serialize every read/modify/write with other ledger connections.
            self._db.execute('BEGIN IMMEDIATE')
            yield

    def status(self):
        with self._lock:return self._read()

    def stop(self,reason):
        with self._transaction():
            state=self._read(check_owner=False);state.update(halted=True,reason=reason);self._write(state)

    def close(self):
        self.stop('owner_closed');self._db.close()

    def observe(self,*,x,y,stamp_ns,source_now_ns,frame_id,now=None):
        current=time.monotonic() if now is None else now
        with self._transaction():
            state=self._read();old=state['pose'];reason=None
            valid=(all(type(v) in (int,float) and math.isfinite(v) for v in [x,y,current])
                   and type(stamp_ns) is int and type(source_now_ns) is int
                   and 0<stamp_ns<=source_now_ns and frame_id==self.frame_id)
            age=(source_now_ns-stamp_ns)/1e9 if valid else float('inf')
            if not valid or age>self.bounds.source_age_max_s:reason='invalid_source_pose'
            elif old is not None:
                dt=(stamp_ns-old['stamp_ns'])/1e9
                gap=current-old['received_at']
                distance=math.hypot(x-old['x'],y-old['y'])
                if dt<=0 or gap<0 or source_now_ns<=old['source_now_ns'] or max(dt,gap)>self.bounds.sample_gap_max_s:
                    reason='pose_clock_or_gap'
                elif distance>self.bounds.speed_max_mps*dt:
                    reason='pose_jump_or_speed'
                else:state['path_upper_m']+=distance*self.bounds.path_scale_upper
            if reason:state.update(halted=True,reason=reason)
            else:
                state['pose']=dict(x=x,y=y,stamp_ns=stamp_ns,source_now_ns=source_now_ns,
                                   received_at=current,source_age_s=age)
                if state['path_upper_m']+self.bounds.measurement_error_m>.20:
                    state.update(halted=True,reason='observed_overrun')
            self._write(state)

    def permits(self,linear,angular,*,now=None):
        current=time.monotonic() if now is None else now
        with self._transaction():
            state=self._read();pose=state['pose'];reason=None
            if state['halted']:return False
            if all(type(v) in (int,float) and math.isfinite(v) for v in [linear,angular,current]):
                zero=linear==0 and angular==0
            else:zero=False;reason='invalid_command_or_clock'
            if zero:
                if state['issued']:state.update(halted=True,reason='selected_zero_stop');self._write(state)
                return True
            if reason is None and (abs(linear)>self.bounds.speed_max_mps or abs(angular)>self.bounds.angular_max_radps):
                reason='command_envelope'
            if reason is None and (pose is None or current>=state['deadline']):reason='pose_missing_or_expired'
            if reason is None:
                age=pose['source_age_s']+current-pose['received_at']
                if current<pose['received_at'] or age>self.bounds.source_age_max_s:reason='pose_stale'
                reserve=(self.bounds.measurement_error_m+self.bounds.speed_max_mps*(age+self.bounds.latency_max_s)
                         +self.bounds.speed_max_mps**2/(2*self.bounds.decel_min_mps2))
                if reason is None and state['path_upper_m']+reserve>=.20:reason='distance_reserve'
            if reason:state.update(halted=True,reason=reason)
            else:state.update(issued=True,reason='unresolved_nonzero_send')
            # Durable unresolved send is committed BEFORE bridge can submit.
            self._write(state)
        if reason is not None:return False
        # This public predicate is not a submission capability. Production
        # must use submit_fenced so no STOP can commit before its writer call.
        with self._transaction():
            return self._fresh_for_submit(now=now)

    def _fresh_for_submit(self,*,now=None):
        # Caller owns both the process lock and SQLite write transaction.
        latest=self._read();tail=time.monotonic() if now is None else now
        if latest['halted']:return False
        pose=latest['pose']
        valid=type(tail) in (int,float) and math.isfinite(tail) and pose is not None
        if valid:
            age=pose['source_age_s']+tail-pose['received_at']
            reserve=(self.bounds.measurement_error_m+self.bounds.speed_max_mps*(age+self.bounds.latency_max_s)
                     +self.bounds.speed_max_mps**2/(2*self.bounds.decel_min_mps2))
            valid=(tail<latest['deadline'] and tail>=pose['received_at']
                   and age<=self.bounds.source_age_max_s and latest['path_upper_m']+reserve<.20)
        if not valid:
            latest.update(halted=True,reason='final_freshness_or_stop');self._write(latest)
        return valid

    def submit_fenced(self,linear,angular,submit,*,now=None):
        """Return the sole port decision, or None when the trial denies it.

        Durable unresolved intent precedes the callback. Final freshness and
        the actual writer share BEGIN IMMEDIATE and the owner RLock: other
        ledger STOP/reopen transactions commit before or after this send,
        never between its final check and callback. A busy fence fails closed.
        """
        if not self.permits(linear,angular,now=now):return None
        with self._transaction():
            # Zero remains safe even when permits latched selected_zero_stop.
            # Read again to retain immutable owner/envelope validation.
            self._read()
            if (linear!=0 or angular!=0) and not self._fresh_for_submit(now=now):return None
            return submit()
