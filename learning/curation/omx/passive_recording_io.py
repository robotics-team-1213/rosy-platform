"""Replay and immutable evidence checks for stopped passive recordings."""
import hashlib
import json
from pathlib import Path


def iter_frames(root,seal,*,cancelled=lambda:False):
    import passive_recording as recording
    root=Path(root)
    path=root/'frames.jsonl'
    if path.is_symlink() or path.stat().st_size>recording.MAX_METADATA:
        raise ValueError('bounded regular raw frame evidence required')
    count=0
    previous=None
    with path.open('rb') as stream:
        while line:=stream.readline(1024**2+1):
            if cancelled():
                raise ValueError('passive evidence verification cancelled')
            if len(line)>1024**2 or count>=recording.MAX_FRAMES:
                raise ValueError('bounded raw grid frame required')
            row=json.loads(line)
            index=count
            expected=seal['start_time']+index/seal['config']['timing']['fps']
            if row['frame_index']!=index or abs(row['grid_time']-expected)>1e-9:
                raise ValueError('raw grid has missing/reordered/interior frames')
            recording.check_grid(seal['config'],row,previous)
            for camera in recording.retained(seal['config']['profile']):
                if cancelled():
                    raise ValueError('passive evidence verification cancelled')
                event=row['cameras'][camera['id']]
                name=event['path']
                if (not isinstance(name,str) or name not in seal['files'] or '\\' in name
                        or ':' in name or not name.startswith('images/') or '..' in Path(name).parts):
                    raise ValueError('raw frame path escaped sealed evidence')
                image=root/name
                if (image.is_symlink() or not image.resolve().is_relative_to(root.resolve())
                        or not image.is_file() or image.stat().st_size>16*1024**2):
                    raise ValueError('bounded owned regular raw JPEG required')
                raw=image.read_bytes()
                if hashlib.sha256(raw).hexdigest()!=event['sha256'] or event['sha256']!=seal['files'][name]:
                    raise ValueError('raw image identity/hash changed')
                recording.image_valid(raw,camera['shape'])
            previous=row
            count+=1
            yield row
    if count!=seal['frames'] or previous is None or previous['grid_time']!=seal['last_grid_time']:
        raise ValueError('complete raw grid count/boundary differs')


def frames(root,seal):
    return list(iter_frames(root,seal))


def check_draft(root,*,on_frame=None,cancelled=lambda:False):
    import passive_recording as recording
    try:
        root=Path(root)
        if root.is_symlink() or not root.is_dir():
            raise ValueError('regular stopped passive recording directory required')
        summary=recording.read_json(root/'episode.json')
        draft=recording.read_json(root/'draft.json')
        config=recording.read_json(root/'config.json')
        recording.check_config(config)
        if (summary.get('status')!='draft' or summary.get('integrity_verified') is not True
                or summary.get('error') is not None or summary.get('stop_time') is None
                or draft.get('schema')!='rosy.passive-recording-draft/1'
                or draft.get('revision')!=recording.digest({k:v for k,v in draft.items() if k!='revision'})
                or draft.get('config_revision')!=config['revision']):
            raise ValueError('verified stopped draft receipt required')
        for key in ('id','frames','start_time','last_grid_time','stop_time'):
            if summary.get(key)!=draft[key]:
                raise ValueError('stopped draft identity/boundary changed')
        current=recording.hashes(root,cancelled=cancelled)
        current.pop('draft.json',None)
        if current!=draft['files']:
            raise ValueError('stopped draft raw bytes changed')
        if not draft['last_grid_time']<=draft['stop_time']<=draft['last_grid_time']+1/config['timing']['fps']+config['timing']['max_gap_s']:
            raise ValueError('stopped draft boundary differs')
        for row in iter_frames(root,dict(draft,config=config),cancelled=cancelled):
            if on_frame is not None:
                on_frame(row)
        return summary,config
    except (OSError,KeyError,TypeError,IndexError) as exc:
        raise ValueError('incomplete stopped passive draft evidence') from exc


def verify(root,*,allow_pending=False,on_frame=None,cancelled=lambda:False):
    import passive_recording as recording
    try:
        root=Path(root)
        if root.is_symlink() or not root.is_dir():
            raise ValueError('regular passive recording directory required')
        seal=recording.read_json(root/'seal.json')
        if (seal.get('schema')!='rosy.passive-recording-seal/1' or seal.get('status')!='kept'
                or seal.get('revision')!=recording.digest({k:v for k,v in seal.items() if k!='revision'})
                or seal.get('content_integrity_only') is not True or seal.get('physical_learning_verified') is not False
                or seal.get('native_safe_end') is not False):
            raise ValueError('passive content-integrity seal differs')
        recording.check_config(seal['config'])
        summary=recording.read_json(root/'episode.json')
        pending=allow_pending and summary.get('status')=='draft'
        if pending:
            check_draft(root,cancelled=cancelled)
        for key in ('id','status','frames','task_outcome','start_time','last_grid_time','stop_time'):
            if pending and key in ('status','task_outcome'):
                continue
            if summary.get(key)!=seal[key]:
                raise ValueError('passive episode was discarded or its boundary/status changed')
        if summary.get('integrity_verified') is not True or summary.get('error') is not None:
            raise ValueError('invalid passive episode cannot be exported')
        if recording.read_json(root/'config.json')!=seal['config'] or recording.hashes(root,cancelled=cancelled)!=seal['files']:
            raise ValueError('passive raw file bytes/configuration changed')
        if seal['task_outcome'] not in ('unknown','success','failure') or (
                seal['task_outcome']=='unknown' and seal.get('human_label') is not None):
            raise ValueError('task outcome attribution differs')
        if seal['task_outcome']!='unknown':
            label=seal.get('human_label')
            if not isinstance(label,dict) or label.get('outcome')!=seal['task_outcome']:
                raise ValueError('human outcome attribution differs')
            recording.text(label.get('user_id'))
            recording.text(label.get('labelled_at'))
        if not seal['last_grid_time']<=seal['stop_time']<=seal['last_grid_time']+1/seal['config']['timing']['fps']+seal['config']['timing']['max_gap_s']:
            raise ValueError('saved stop boundary differs')
        for row in iter_frames(root,seal,cancelled=cancelled):
            if on_frame is not None:
                on_frame(row)
        return seal
    except (OSError,KeyError,TypeError,IndexError) as exc:
        raise ValueError('incomplete passive recording evidence') from exc
