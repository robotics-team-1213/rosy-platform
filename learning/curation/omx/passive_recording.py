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

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'training/omx'))
from experiment_profile import validate_profile, profile_revision
from passive_recording_io import frames, verify, check_draft

MAX_BYTES = 2*1024**3
MAX_METADATA = 64*1024**2
MAX_BUFFER = 64*1024**2
MAX_FRAMES = 200000
DISK_RESERVE = 1024**3


def require_space(root,needed=0):
    probe=Path(root)
    while not probe.exists():
        probe=probe.parent
    try:
        if shutil.disk_usage(probe).free<DISK_RESERVE+needed:
            raise ValueError('insufficient recording disk space: 1 GiB reserve required')
    except OSError as exc:
        raise ValueError('recording disk reserve could not be checked') from exc


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def write_json(path,value):
    temporary=path.with_suffix('.tmp')
    temporary.write_bytes(canonical(value))
    temporary.replace(path)


def read_json(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size>MAX_METADATA:
        raise ValueError('bounded regular passive recording JSON required')
    return json.loads(path.read_bytes())


def number(value):
    if type(value) not in (int,float) or value<0 or value>1e12 or not math.isfinite(value):
        raise ValueError('finite nonnegative recording timestamp/limit required')
    return float(value)


def text(value):
    if not isinstance(value,str) or not 1<=len(value)<=2048 or any(ord(c)<32 for c in value):
        raise ValueError('explicit bounded producer identity required')
    return value


def retained(profile):
    return [c for c in profile['cameras'] if set(c['purposes'])-{'monitor'}]


def preflight(profile,producers,timing,*,now,clock_domain):
    profile=validate_profile(profile)
    text(clock_domain)
    number(now)
    fields={'fps','max_camera_age_s','max_arm_age_s','max_camera_skew_s','max_arm_skew_s','max_gap_s'}
    if not isinstance(timing,dict) or set(timing)!=fields or type(timing['fps']) is not int or not 1<=timing['fps']<=240:
        raise ValueError('explicit bounded recording grid recipe required')
    for key in fields-{'fps'}:
        if not 0<number(timing[key])<=5:
            raise ValueError('timing bounds must be positive and at most five seconds')
    if not isinstance(producers,dict) or set(producers)!={'arms','cameras'}:
        raise ValueError('explicit arm and camera producer descriptors required')
    if set(producers['arms'])!={a['id'] for a in profile['arms']}:
        raise ValueError('every selected working arm requires a producer')
    cameras=retained(profile)
    if set(producers['cameras'])!={c['id'] for c in cameras}:
        raise ValueError('every retained camera requires a producer; monitor is preview only')
    policy=[c for c in cameras if 'policy' in c['purposes']]
    if len(policy)>8 or sum(len(a['joint_names']) for a in profile['arms'])>64:
        raise ValueError('ACT supports at most eight policy views and 64 action dimensions')
    if sum(c['shape'][1]*c['shape'][2] for c in cameras)>16000000:
        raise ValueError('raw recording resource budget exceeds 16M pixels per grid')
    for arm in profile['arms']:
        descriptor=producers['arms'][arm['id']]
        for key in ('owner_id','source_identity','session_epoch','calibration_revision','profile_revision',
                    'state_producer','reference_producer'):
            text(descriptor.get(key))
        if (descriptor.get('kind')!='arm' or descriptor.get('reference_stage')!='post_guard_accepted'
                or descriptor.get('joint_names')!=arm['joint_names']
                or descriptor.get('state_units')!=arm['units'] or descriptor.get('action_units')!=arm['units']):
            raise ValueError('measured prestate and complete post-guard accepted reference required')
    identities=[descriptor['source_identity'] for descriptor in producers['arms'].values()]
    if len(set(identities))!=len(identities):
        raise ValueError('working arms must have distinct physical producer identities')
    for camera in cameras:
        descriptor=producers['cameras'][camera['id']]
        text(descriptor.get('session_epoch'))
        if (descriptor.get('kind')!='camera' or descriptor.get('source_identity')!=camera['source_identity']
                or descriptor.get('shape')!=camera['shape'] or descriptor.get('timestamp_semantics')!='host_receive'):
            raise ValueError('exact physical camera identity and host-receive shape required')
    for descriptor in [*producers['arms'].values(),*producers['cameras'].values()]:
        if descriptor.get('clock_domain')!=clock_domain or number(descriptor.get('rate_hz'))<timing['fps']:
            raise ValueError('common clock and sufficient measured/declared producer rate required')
    config=dict(profile=profile,profile_revision=profile_revision(profile),producers=copy.deepcopy(producers),
                timing=copy.deepcopy(timing),clock_domain=clock_domain,preflight_at=now)
    config['revision']=digest(config)
    return config


def check_config(config):
    expected=preflight(config['profile'],config['producers'],config['timing'],
        now=config['preflight_at'],clock_domain=config['clock_domain'])
    if expected!=config:
        raise ValueError('frozen recording profile/configuration revision changed')


def validate_event(config,kind,event,received_at):
    if not isinstance(event,dict):
        raise ValueError('explicit passive producer envelope required')
    identity='arm_id' if kind=='arms' else 'camera_id'
    source_id=event.get(identity)
    descriptor=config['producers'][kind].get(source_id)
    if descriptor is None:
        raise ValueError('unselected recording source')
    expected_schema='rosy.passive-owner-sample/1' if kind=='arms' else 'rosy.passive-camera-sample/1'
    if (event.get('schema')!=expected_schema or type(event.get('sequence')) is not int
            or not 0<=event['sequence']<2**63):
        raise ValueError('producer schema and monotonic integer sequence required')
    frozen=('owner_id','source_identity','session_epoch','clock_domain','joint_names','state_units',
        'action_units','calibration_revision','profile_revision','reference_stage') if kind=='arms' else (
        'source_identity','session_epoch','clock_domain','shape','timestamp_semantics')
    fields={'schema',identity,'sequence',*frozen}
    fields|={'state_timestamp','reference_timestamp','state','accepted_reference','reference_id'} if kind=='arms' else {'timestamp'}
    if set(event)-fields-{'received_at','path','sha256'}:
        raise ValueError('passive sample envelope fields differ')
    for key in frozen:
        if event.get(key)!=descriptor[key]:
            raise ValueError('recording producer identity/layout changed: '+key)
    if kind=='arms':
        state=number(event.get('state_timestamp'))
        reference=number(event.get('reference_timestamp'))
        if not state<=reference<=number(received_at):
            raise ValueError('prestate <= accepted reference <= receipt required')
        text(event.get('reference_id'))
        for key in ('state','accepted_reference'):
            value=event.get(key)
            if (not isinstance(value,list) or len(value)!=len(descriptor['joint_names'])
                    or any(type(v) not in (int,float) or abs(v)>3.4e38 or not math.isfinite(v) for v in value)):
                raise ValueError('complete finite ordered measured state and accepted reference required')
        import struct
        for key in ('state','accepted_reference'):
            if any(not math.isfinite(struct.unpack('f',struct.pack('f',v))[0]) for v in event[key]):
                raise ValueError('recorded vectors must have finite float32 encoding')
        stamp=reference
    else:
        stamp=number(event.get('timestamp'))
        if stamp>number(received_at):
            raise ValueError('camera timestamp cannot follow receipt')
    return source_id,stamp


def check_grid(config,row,previous=None):
    timing=config['timing']
    tick=number(row['grid_time'])
    if tick>number(row['processed_at']):
        raise ValueError('grid cannot precede processing availability')
    expected_ids={'arms':{a['id'] for a in config['profile']['arms']},
                  'cameras':{c['id'] for c in retained(config['profile'])}}
    for kind in ('arms','cameras'):
        if set(row[kind])!=expected_ids[kind]:
            raise ValueError('complete selected arm/camera inputs required at every grid')
        stamps=[]
        state_stamps=[]
        for source_id,event in row[kind].items():
            _,stamp=validate_event(config,kind,event,event['received_at'])
            if event['received_at']>row['processed_at']:
                raise ValueError('source receipt follows grid processing')
            oldest=event['state_timestamp'] if kind=='arms' else stamp
            maximum=timing['max_arm_age_s' if kind=='arms' else 'max_camera_age_s']
            if stamp>tick+1e-9 or tick-oldest>maximum+1e-9:
                raise ValueError('missing causal/fresh source at recording grid')
            stamps.append(stamp)
            if kind=='arms':
                state_stamps.append(event['state_timestamp'])
            if previous is not None:
                prior=previous[kind][source_id]
                delta=event['sequence']-prior['sequence']
                descriptor=config['producers'][kind][source_id]
                if (delta<=0 or stamp<(prior['reference_timestamp'] if kind=='arms' else prior['timestamp'])
                        or (kind=='arms' and event['state_timestamp']<prior['state_timestamp'])
                        or delta/descriptor['rate_hz']>timing['max_gap_s']+1e-9
                        or stamp-(prior['reference_timestamp'] if kind=='arms' else prior['timestamp'])>timing['max_gap_s']+1e-9):
                    raise ValueError('reused/regressed frame or producer gap exceeds recording budget')
        if max(stamps)-min(stamps)>timing['max_arm_skew_s' if kind=='arms' else 'max_camera_skew_s']+1e-9:
            raise ValueError('cross-source skew exceeds frozen recording limits')
        if state_stamps and max(state_stamps)-min(state_stamps)>timing['max_arm_skew_s']+1e-9:
            raise ValueError('inter-arm measured state skew exceeds frozen limits')
    state=[v for a in config['profile']['arms'] for v in row['arms'][a['id']]['state']]
    action=[v for a in config['profile']['arms'] for v in row['arms'][a['id']]['accepted_reference']]
    if row['state']!=state or row['action']!=action:
        raise ValueError('ordered recording vectors differ from measured/accepted envelopes')


def hashes(root,*,cancelled=lambda:False):
    result={}
    for path in sorted(root.rglob('*')):
        if cancelled():
            raise ValueError('passive evidence verification cancelled')
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('passive recording links are forbidden')
        if path.is_file() and path.relative_to(root).as_posix() not in ('episode.json','seal.json'):
            with path.open('rb') as stream:
                result[path.relative_to(root).as_posix()]=hashlib.file_digest(stream,'sha256').hexdigest()
        elif not path.is_file() and not path.is_dir():
            raise ValueError('regular passive recording files required')
    return result


def image_valid(raw,shape):
    from PIL import Image
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format!='JPEG' or image.mode!='RGB' or image.size!=(shape[2],shape[1]):
                raise ValueError('raw RGB JPEG dimensions differ from frozen camera profile')
            image.load()
    except (OSError,Image.DecompressionBombError) as exc:
        raise ValueError('invalid bounded raw JPEG evidence') from exc


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
