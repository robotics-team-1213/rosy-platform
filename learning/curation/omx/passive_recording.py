"""Observer-only causal recording; integrity seals confer no native device authority."""
import copy
from collections import deque
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import queue
import shutil
import sys
import threading
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'training/omx'))
from experiment_profile import validate_profile, profile_revision
from passive_recording_io import frames, verify, check_draft
from passive_recording_helpers import (  # noqa: F401
    DISK_RESERVE,
    MAX_BUFFER,
    MAX_BYTES,
    MAX_FRAMES,
    MAX_METADATA,
    canonical,
    check_config,
    check_grid,
    digest,
    hashes,
    image_valid,
    number,
    preflight,
    read_json,
    require_space,
    retained,
    text,
    validate_event,
    write_json,
)


class Recorder:
    @classmethod
    def resume(cls,root):
        root=Path(root)
        if not root.is_absolute() or root.is_symlink() or not root.is_dir():
            raise ValueError('existing absolute stopped passive episode required')
        try:
            summary=read_json(root/'episode.json')
        except OSError as exc:
            raise ValueError('stopped passive episode summary is unavailable') from exc
        if (root/'seal.json').exists():
            seal=verify(root,allow_pending=True)
            config=seal['config']
            summary=dict(summary,status='kept',task_outcome=seal['task_outcome'])
        else:
            summary,config=check_draft(root)
        recorder=cls.__new__(cls)
        recorder.root=root
        recorder.config=config
        recorder.id=summary['id']
        recorder.status=summary['status']
        recorder.count=summary['frames']
        recorder.error=summary['error']
        recorder.start_time=summary['start_time']
        recorder.last_grid_time=summary['last_grid_time']
        recorder.stop_time=summary['stop_time']
        recorder.task_outcome=summary['task_outcome']
        recorder.integrity_verified=True
        recorder.finished=threading.Event()
        recorder.finished.set()
        recorder.writer=None
        recorder.writer_error=None
        return recorder

    def __init__(self,root,config):
        check_config(config)
        self.root=Path(root)
        if not self.root.is_absolute() or self.root.exists() or self.root.is_symlink():
            raise ValueError('new absolute passive episode directory required')
        require_space(self.root)
        self.root.mkdir(parents=True)
        self.config=copy.deepcopy(config)
        self.id=str(uuid.uuid4())
        self.status='draft'
        self.count=0
        self.error=None
        self.start_time=self.last_grid_time=self.stop_time=None
        self.task_outcome='unknown'
        self.integrity_verified=False
        self.histories={kind:{key:deque() for key in config['producers'][kind]} for kind in ('arms','cameras')}
        self.last={}
        self.previous=None
        self.memory=0
        self.pending=queue.Queue(maxsize=32)
        self.pending_bytes=0
        self.pending_lock=threading.Lock()
        self.finished=threading.Event()
        self.writer_error=None
        self.writer=None
        try:
            write_json(self.root/'config.json',config)
            (self.root/'images').mkdir()
            self._save_summary()
        except OSError as exc:
            self._fail('Passive recording startup storage failed: '+type(exc).__name__)
        self.writer=threading.Thread(target=self._write,daemon=True,name='passive-recording-disk')
        try:
            self.writer.start()
        except (RuntimeError,OSError) as exc:
            self.writer=None
            self._fail('Passive recording writer startup failed: '+type(exc).__name__)

    def summary(self):
        return dict(id=self.id,status=self.status,frames=self.count,integrity_verified=self.integrity_verified,
            task_outcome=self.task_outcome,error=self.error,start_time=self.start_time,
            last_grid_time=self.last_grid_time,stop_time=self.stop_time)

    def _save_summary(self):
        write_json(self.root/'episode.json',self.summary())

    def _fail(self,message):
        self.invalidate(message)
        raise ValueError(self.error)

    def invalidate(self,reason):
        self.status='invalid'
        self.integrity_verified=False
        self.error=' '.join(str(reason).split())[:1024] or 'Recording provider invalidated capture'
        self.finished.set()
        if self.writer is not None and self.writer is not threading.current_thread():
            self.writer.join(timeout=10)
            if self.writer.is_alive():
                self.error+='; observer writer close timed out'
        if self.writer_error and self.writer_error not in self.error:
            self.error+='; '+self.writer_error
        try:
            self._save_summary()
        except OSError:
            self.error+='; terminal summary unavailable (OSError); durable invalid status not saved'
        return self.summary()

    def _push(self,kind,event,received_at,jpeg=None):
        if self.status not in ('draft','recording') or self.stop_time is not None:
            raise ValueError('episode no longer accepts inputs')
        try:
            source_id,stamp=validate_event(self.config,kind,event,received_at)
            prior=self.last.get((kind,source_id))
            if prior is not None:
                delta=event['sequence']-prior[0]
                rate=self.config['producers'][kind][source_id]['rate_hz']
                if (delta<=0 or stamp<prior[1] or received_at<prior[2]
                        or (kind=='arms' and event['state_timestamp']<prior[3])
                        or delta/rate>self.config['timing']['max_gap_s']+1e-9
                        or stamp-prior[1]>self.config['timing']['max_gap_s']+1e-9):
                    raise ValueError('producer reset/regression/sequence gap invalidates capture')
            if jpeg is not None and (not isinstance(jpeg,bytes) or not 0<len(jpeg)<=16*1024**2):
                raise ValueError('bounded raw camera JPEG bytes required')
            stored=copy.deepcopy(event)
            stored['received_at']=number(received_at)
            if jpeg is not None:
                stored['_jpeg']=jpeg
                self.memory+=len(jpeg)
            history=self.histories[kind][source_id]
            history.append(stored)
            horizon=max(self.config['timing']['max_gap_s'],self.config['timing']['max_camera_age_s'],
                        self.config['timing']['max_arm_age_s'])+2/self.config['timing']['fps']
            while len(history)>1 and history[0]['received_at']<received_at-horizon:
                self.memory-=len(history.popleft().get('_jpeg',b''))
            if len(history)>256 or self.memory>MAX_BUFFER:
                raise ValueError('bounded observer history overflow invalidates capture')
            self.last[kind,source_id]=(event['sequence'],stamp,received_at,
                event['state_timestamp'] if kind=='arms' else stamp)
        except (ValueError,KeyError,TypeError) as exc:
            self._fail(str(exc))

    def push_arm(self,event,*,received_at):
        self._push('arms',event,received_at)

    def push_camera(self,event,jpeg_bytes,*,received_at):
        self._push('cameras',event,received_at,jpeg_bytes)

    def _sample(self,tick,now):
        row=dict(frame_index=self.count,grid_time=tick,processed_at=now,arms={},cameras={})
        pictures={}
        for kind in ('arms','cameras'):
            for source_id,history in self.histories[kind].items():
                field='reference_timestamp' if kind=='arms' else 'timestamp'
                chosen=next((e for e in reversed(history) if e[field]<=tick+1e-9),None)
                if chosen is None:
                    raise ValueError('explicit complete-input warmup/grid sample required')
                event={k:v for k,v in chosen.items() if k!='_jpeg'}
                if kind=='cameras':
                    pictures[source_id]=chosen['_jpeg']
                row[kind][source_id]=event
        row['state']=[v for a in self.config['profile']['arms'] for v in row['arms'][a['id']]['state']]
        row['action']=[v for a in self.config['profile']['arms'] for v in row['arms'][a['id']]['accepted_reference']]
        check_grid(self.config,row,self.previous)
        if self.count>=MAX_FRAMES:
            raise ValueError('passive episode exceeds frame budget')
        size=sum(len(raw) for raw in pictures.values())
        with self.pending_lock:
            if self.pending_bytes+size>MAX_BUFFER:
                raise ValueError('bounded observer writer byte queue overflow')
            self.pending_bytes+=size
        try:
            self.pending.put_nowait((row,pictures))
        except queue.Full:
            with self.pending_lock:
                self.pending_bytes-=size
            raise
        self.previous=row
        self.last_grid_time=tick
        self.count+=1

    def start(self,start_time):
        if self.status!='draft' or self.start_time is not None:
            raise ValueError('new episode with explicit warmup required')
        try:
            self.start_time=number(start_time)
            self._sample(self.start_time,self.start_time)
            self.status='recording'
            self._save_summary()
            return self.summary()
        except (ValueError,queue.Full) as exc:
            self._fail(str(exc) or 'observer writer queue overflow')

    def advance(self,now):
        if self.status!='recording':
            raise ValueError('episode is not recording')
        try:
            now=number(now)
            if self.writer_error:
                raise ValueError(self.writer_error)
            if now<self.last_grid_time:
                raise ValueError('recording clock regressed')
            tick=self.start_time+self.count/self.config['timing']['fps']
            while tick<=now+1e-9:
                self._sample(tick,now)
                tick=self.start_time+self.count/self.config['timing']['fps']
            return self.summary()
        except (ValueError,queue.Full) as exc:
            self._fail(str(exc) or 'observer writer queue overflow')

    def _write(self):
        total=0
        try:
            with (self.root/'frames.jsonl').open('xb') as stream:
                while not self.finished.is_set() or not self.pending.empty():
                    try:
                        row,pictures=self.pending.get(timeout=.1)
                    except queue.Empty:
                        continue
                    require_space(self.root,sum(len(raw) for raw in pictures.values())+len(canonical(row))+len(pictures)*256)
                    for index,camera in enumerate(retained(self.config['profile'])):
                        raw=pictures[camera['id']]
                        image_valid(raw,camera['shape'])
                        name=f"images/{row['frame_index']:06d}-{index:02d}.jpg"
                        (self.root/name).write_bytes(raw)
                        row['cameras'][camera['id']].update(path=name,sha256=hashlib.sha256(raw).hexdigest())
                        total+=len(raw)
                    encoded=canonical(row)+b'\n'
                    stream.write(encoded)
                    stream.flush()
                    with self.pending_lock:
                        self.pending_bytes-=sum(len(raw) for raw in pictures.values())
                    total+=len(encoded)
                    if total>MAX_BYTES or stream.tell()>MAX_METADATA:
                        raise ValueError('passive raw recording exceeds storage budget')
        except Exception as exc:
            detail=str(exc) if isinstance(exc,ValueError) else type(exc).__name__
            self.writer_error='Passive writer failed: '+detail
            self.finished.set()

    def _close(self):
        self.finished.set()
        if self.writer is None:
            return
        self.writer.join(timeout=10)
        if self.writer.is_alive() or self.writer_error:
            self._fail(self.writer_error or 'passive disk writer did not finish')

    def stop(self,now):
        if self.status!='recording':
            raise ValueError('episode is not recording')
        now=number(now)
        if not self.last_grid_time<=now<=self.last_grid_time+1/self.config['timing']['fps']+self.config['timing']['max_gap_s']:
            self._fail('stop exceeded last complete recording boundary')
        self.stop_time=now
        self._close()
        self.status='draft'
        try:
            check_config(self.config)
            if read_json(self.root/'config.json')!=self.config:
                raise ValueError('frozen raw configuration changed')
            provisional=dict(config=self.config,frames=self.count,start_time=self.start_time,
                last_grid_time=self.last_grid_time,files=hashes(self.root))
            frames(self.root,provisional)
            draft=dict(schema='rosy.passive-recording-draft/1',id=self.id,frames=self.count,
                config_revision=self.config['revision'],start_time=self.start_time,
                last_grid_time=self.last_grid_time,stop_time=self.stop_time,files=provisional['files'])
            draft['revision']=digest(draft)
            write_json(self.root/'draft.json',draft)
            self.integrity_verified=True
        except (ValueError,OSError,KeyError,TypeError) as exc:
            self._fail('Stopped raw recording failed integrity validation: '+type(exc).__name__)
        self._save_summary()
        return self.summary()

    def keep(self,*,task_outcome='unknown',actor=None):
        if task_outcome not in ('unknown','success','failure'):
            raise ValueError('explicit task outcome required')
        if self.status=='kept':
            seal=verify(self.root,allow_pending=True)
            user=actor.get('user_id') if isinstance(actor,dict) else None
            if (seal['task_outcome']!=task_outcome or (task_outcome!='unknown'
                    and seal['human_label']['user_id']!=user)):
                raise ValueError('kept outcome/attributed human identity cannot change on retry')
            if read_json(self.root/'episode.json')['status']!='kept':
                self._save_summary()
            return seal
        if self.status!='draft' or self.stop_time is None or not self.count or not self.integrity_verified:
            raise ValueError('only a complete stopped draft can be kept')
        check_draft(self.root)
        human=None
        if task_outcome!='unknown':
            if not isinstance(actor,dict):
                raise ValueError('explicit authenticated human outcome attribution required')
            human=dict(user_id=text(actor.get('user_id')),outcome=task_outcome,
                labelled_at=datetime.now(timezone.utc).isoformat())
        self._close()
        seal=dict(schema='rosy.passive-recording-seal/1',id=self.id,status='kept',frames=self.count,
            task_outcome=task_outcome,human_label=human,config=self.config,start_time=self.start_time,
            last_grid_time=self.last_grid_time,stop_time=self.stop_time,files=hashes(self.root),
            content_integrity_only=True,physical_learning_verified=False,native_safe_end=False)
        seal['revision']=digest(seal)
        write_json(self.root/'seal.json',seal)
        self.status='kept'
        self.integrity_verified=True
        self.task_outcome=task_outcome
        self._save_summary()
        try:
            verify(self.root)
        except Exception:
            self._fail('passive raw evidence failed save verification')
        return seal

    def discard(self):
        try:
            self._close()
        except ValueError:
            pass
        self.status='discarded'
        self.integrity_verified=False
        self._save_summary()
        return self.summary()
