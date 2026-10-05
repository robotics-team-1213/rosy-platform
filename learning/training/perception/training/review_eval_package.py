"""Package frozen D-379 evaluation lineage; never approval or admission.

All inputs carry caller-pinned raw hashes. Selection indices bind D-379 output
paths; original video ordinals are derived only by unique exact timestamp joins.
"""
import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dataset.build import read_eval_set
from review_eval_companion import capture_eval_companions
from review_provenance import _stable_bytes
from store import file_hashes


def _require(condition, message):
    if not condition:
        raise ValueError('eval package: ' + message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _json(raw):
    def pairs(items):
        result = {}
        for key,value in items:
            _require(key not in result,'duplicate JSON field')
            result[key]=value
        return result
    def constant(_):
        raise ValueError('eval package: finite JSON required')
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=constant)


def _relative(name):
    _require(isinstance(name,str) and name and ':' not in name and '\\' not in name
             and not PurePosixPath(name).is_absolute()
             and all(p not in ('','.','..') for p in name.split('/')),'relative path required')
    return name


def _output_path(value):
    path=Path(value)
    _require(path.is_absolute() and '..' not in path.parts,'absolute output without traversal required')
    for part in (path,*path.parents):
        _require(not part.is_symlink() and not (hasattr(part,'is_junction') and part.is_junction()),'output links refused')
    if os.name=='nt':
        _require(path.resolve().is_relative_to(Path('X:/DevTemp').resolve()),'output must remain within X:/DevTemp')
    _require(not path.exists(),'output already exists; immutable output never replaced')
    return path


def _prepare(eval_folder, source_records):
    """Validate/capture everything in memory before any artifact staging."""
    _require(Path(eval_folder).is_absolute() and '..' not in Path(eval_folder).parts,
             'absolute evaluation path without traversal required')
    root=Path(eval_folder).absolute()
    ref,_,manifest_raw=read_eval_set(root,with_manifest=True)
    inventory=file_hashes(root)
    observed={}
    def observe(path,raw):
        _require(path not in observed or observed[path]==raw,'inconsistent shared source snapshot')
        observed[path]=raw
    eval_bytes={}
    for name,digest in inventory.items():
        _relative(name);path=root/name;raw=_stable_bytes(path)
        _require(_sha(raw)==digest,'evaluation changed during capture')
        eval_bytes[name]=raw;observe(path,raw)
    _require(eval_bytes.get('manifest.json')==manifest_raw,'evaluation manifest changed')
    doc=_json(manifest_raw)
    _require(isinstance(doc,dict) and doc.get('purpose')=='eval'
             and doc.get('builder')=='build.py --auto-labels (D-379)','frozen D-379 evaluation required')
    _require(isinstance(doc.get('frames'),list) and doc['frames'],'evaluation frames required')
    rows={}
    for row in doc['frames']:
        _require(isinstance(row,dict) and isinstance(row.get('session'),str)
                 and re.fullmatch(r'[A-Za-z0-9_.-]+',row['session']) is not None,'canonical frame session required')
        identity=(row['session'],row.get('image'))
        _require(isinstance(identity[1],str) and identity not in rows,'unique evaluation image required')
        for kind in ('image','mask','conf'):
            _require(_relative(row.get(kind)) in eval_bytes,'complete evaluation file references required')
        rows[identity]=row
    _require(isinstance(source_records,list) and source_records,'original source records required')
    resources={};sources=[];frames=[];sessions=set();original_frames=set()
    def capture(binding):
        _require(isinstance(binding,dict) and set(binding)=={'path','sha256'},'pinned source path/hash pair required')
        _require(isinstance(binding['path'],str) and Path(binding['path']).is_absolute()
                 and '..' not in Path(binding['path']).parts,'absolute source path without traversal required')
        _require(isinstance(binding['sha256'],str) and re.fullmatch('[0-9a-f]{64}',binding['sha256']) is not None,'source raw SHA256 required')
        path=Path(binding['path']);raw=_stable_bytes(path)
        _require(_sha(raw)==binding['sha256'],'pinned original source hash differs')
        observe(path,raw);return raw
    for record in copy.deepcopy(source_records):
        _require(isinstance(record,dict) and set(record)=={'session','labels','meta','video','sidecar','pts','extractions'},'exact source fields required')
        session=record['session']
        _require(isinstance(session,str) and re.fullmatch(r'[A-Za-z0-9_.-]+',session) is not None
                 and session not in sessions,'unique canonical source session required')
        sessions.add(session)
        originals={kind:capture(record[kind]) for kind in ('labels','meta','video','sidecar','pts')}
        video_digest=_sha(originals['video'])
        labels=[_json(line) for line in originals['labels'].splitlines() if line.strip()]
        _require(labels and all(isinstance(r,dict) and r.get('session')==session
                 and type(r.get('index')) is int and r['index']>=0
                 and type(r.get('t')) in (int,float) and math.isfinite(r['t']) for r in labels),'canonical original labels required')
        _require(len({r['index'] for r in labels})==len(labels),'duplicate original label index')
        canonical=''.join(json.dumps(r,sort_keys=True,allow_nan=False)+'\n' for r in sorted(labels,key=lambda r:r['index'])).encode()
        digest=_sha(canonical)
        versions=[r for r in doc.get('labels',[]) if isinstance(r,dict) and r.get('session')==session]
        _require(len(versions)==1 and versions[0].get('labels_digest')==digest,'original full-row digest differs from evaluation')
        meta=_json(originals['meta'])
        _require(isinstance(meta,dict) and meta.get('session')==session and isinstance(meta.get('source'),dict)
                 and meta['source'].get('sha256')=={'video':video_digest,'sidecar':_sha(originals['sidecar'])},'original metadata video/sidecar hashes differ')
        side=[_json(line) for line in originals['sidecar'].splitlines() if line.strip()]
        _require(side and all(isinstance(r,dict) and type(r.get('index')) is int and r['index']==i
                 and type(r.get('t')) in (int,float) and math.isfinite(r['t']) for i,r in enumerate(side)),'explicit sequential sidecar indices required')
        pts=_json(originals['pts'])
        _require(isinstance(pts,list) and len(pts)==len(side) and all(isinstance(r,dict)
                 and type(r.get('video_frame')) is int and r['video_frame']==i
                 and type(r.get('pts')) is int and isinstance(r.get('time_base'),str) and r['time_base'].strip()
                 for i,r in enumerate(pts)),'complete original ordinal/PTS resource required')
        names={kind:f'sources/{session}/{kind}'+('.jsonl' if kind in ('labels','sidecar') else '.json' if kind in ('meta','pts') else '.bin') for kind in originals}
        resources.update({names[kind]:raw for kind,raw in originals.items()})
        sources.append(dict(session=session,labels_digest=digest,**names))
        selected={image:row for (owner,image),row in rows.items() if owner==session}
        _require(selected and isinstance(record['extractions'],dict) and set(record['extractions'])==set(selected),'exact per-session extraction coverage required')
        by_index={r['index']:r for r in labels}
        for image,row in sorted(selected.items()):
            match=re.fullmatch(re.escape(f'images/{session}/{session}__')+r'([0-9]{6,})\.jpg',image)
            _require(match is not None,'D-379 selected label image path required')
            index=int(match.group(1));_require(index in by_index,'selected original label missing')
            for kind,directory,suffix in [('image','images','jpg'),('mask','masks','png'),('conf','conf','png')]:
                _require(row[kind]==f'{directory}/{session}/{session}__{index:06d}.{suffix}','canonical selected index references differ')
            ordinal=[i for i,r in enumerate(side) if r['t']==by_index[index]['t']]
            _require(len(ordinal)==1,'unique exact label timestamp to sidecar required')
            original_identity=(video_digest,ordinal[0])
            _require(original_identity not in original_frames,'duplicate original frame mapping')
            original_frames.add(original_identity)
            extraction=record['extractions'][image]
            _require(isinstance(extraction,dict) and set(extraction)=={'image','mask','conf'},'all original extraction resources required')
            refs={}
            for kind,binding in extraction.items():
                raw=capture(binding)
                _require(raw==eval_bytes[row[kind]],'original extraction bytes differ from evaluation')
                name='extraction/'+row[kind];resources[name]=raw;refs[kind]=name
            frames.append(dict(session=session,image=image,sample_index=index,video_frame=ordinal[0],capture_group=None,
                               group_basis=None,decoded_video_pixels_verified=False,extraction=refs))
    _require(sessions=={session for session,_ in rows},'full evaluation source coverage required')
    _require(file_hashes(root)==inventory and read_eval_set(root,with_manifest=True)==(ref,set(r['session'] for r in doc['frames']),manifest_raw),'evaluation changed after preflight')
    _require(all(_stable_bytes(path)==raw for path,raw in observed.items()),'original inputs changed after preflight')
    manifest=dict(schema='rosy.pinky-fixed-eval-companion/1',eval_ref=ref,eval_manifest_sha256=_sha(manifest_raw),
                  eval_files=inventory,resources={name:_sha(raw) for name,raw in resources.items()},
                  sources=sorted(sources,key=lambda r:r['session']),frames=sorted(frames,key=lambda r:(r['session'],r['image'])))
    return root,manifest,resources,observed


def package_eval_companion(eval_folder, source_records, output, *, _descriptor_binding=None):
    """Create a new sealed lineage bundle; invalid preflight creates no staging.

    Existing destinations are never replaced. A failure after exclusive output
    reservation may leave an unsealed folder, which is not an admitted artifact.
    """
    output=_output_path(output)
    root,manifest,resources,observed=_prepare(eval_folder,source_records)
    if _descriptor_binding is not None:
        path,data=_descriptor_binding
        _require(_stable_bytes(path)==data,'CLI source descriptor changed before staging')
        observed[path]=data
    def recheck():
        _require(file_hashes(root)==manifest['eval_files'],'evaluation inventory changed before publication')
        _require(all(_stable_bytes(path)==data for path,data in observed.items()),'original inputs changed before publication')
    raw=json.dumps(manifest,sort_keys=True,allow_nan=False).encode();seal=_sha(raw)
    recheck();_output_path(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='eval-package-',dir=output.parent) as temp:
        stage=Path(temp)
        for name,data in resources.items():
            path=stage/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        (stage/'manifest.json').write_bytes(raw)
        (stage/'COMPLETE').write_text(seal,encoding='ascii') # last in stage
        captured=capture_eval_companions([root],[stage],read_bytes=_stable_bytes)
        _require(captured['captured_files']=={seal:{'manifest.json':raw,'COMPLETE':seal.encode(),**resources}},'staged bytes differ from captured snapshot')
        recheck()
        _output_path(output);output.mkdir(exist_ok=False) # exclusive output reservation
        for child in stage.iterdir():
            if child.name!='COMPLETE':shutil.move(str(child),str(output/child.name))
        _require(file_hashes(output)=={'manifest.json':seal,**manifest['resources']},'output resources changed before seal')
        recheck()
        # COMPLETE is the final write in the exclusively reserved destination.
        with (output/'COMPLETE').open('xb') as stream:stream.write(seal.encode('ascii'))
    return dict(output=str(output),manifest_sha256=seal,eval_ref=manifest['eval_ref'],frames=len(manifest['frames']),
                training_admission=False,training_dataset_qualified=False,decoded_video_pixels_verified=False,
                operator_collection_assertion_verified=False)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--eval-folder',required=True)
    parser.add_argument('--sources',required=True,help='JSON array of absolute raw-hash-pinned source descriptors')
    parser.add_argument('--out',required=True,help='new absolute output directory; Windows X:/DevTemp only')
    args=parser.parse_args(argv)
    try:
        source_path=Path(args.sources);raw=_stable_bytes(source_path)
        result=package_eval_companion(args.eval_folder,_json(raw),args.out,
                                      _descriptor_binding=(source_path,raw))
        _require(_stable_bytes(source_path)==raw,'CLI source descriptor changed; artifact is not admission')
        print(json.dumps(result,sort_keys=True));return 0
    except (ValueError,OSError,KeyError,TypeError) as error:
        print(json.dumps({'status':'HOLD','error':str(error),'training_admission':False}));return 2


if __name__=='__main__':
    raise SystemExit(main())
