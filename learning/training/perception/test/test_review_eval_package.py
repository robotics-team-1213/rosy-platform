"""Synthetic sealed-package roundtrip and denial boundaries; never human GT."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'training'))
from test_review_dataset import companion_fixture
import review_dataset


def package_inputs(tmp_path):
    root,bundle,doc=companion_fixture(tmp_path)
    def pinned(name):
        path=bundle/name
        return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    original=doc['sources'][0]
    source={'session':original['session'],**{kind:pinned(original[kind]) for kind in ('labels','meta','video','sidecar','pts')},
            'extractions':{row['image']:{kind:pinned(row['extraction'][kind]) for kind in ('image','mask','conf')} for row in doc['frames']}}
    return root,[source],tmp_path/'packaged'


def test_package_roundtrip_deterministic_and_unknowns_preserved(tmp_path):
    import review_eval_package as target
    root,sources,out=package_inputs(tmp_path)
    before={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
    result=target.package_eval_companion(root,sources,out)
    another=target.package_eval_companion(root,sources,tmp_path/'second')
    assert result['manifest_sha256']==another['manifest_sha256']
    captured=review_dataset.validate_eval_companions([root],[out])
    assert captured['training_admission'] is False
    assert captured['frames'][0]['sample_index']==1 and captured['frames'][0]['video_frame']==0
    assert captured['frames'][0]['capture_group'] is None
    assert captured['frames'][0]['decoded_video_pixels_verified'] is False
    assert result['training_admission'] is False
    assert before=={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
    assert (out/'COMPLETE').read_text()==result['manifest_sha256']


@pytest.mark.parametrize('bad',['source_hash','label_digest','extraction','missing','extra','group','ordinal','eval_version'])
def test_invalid_inputs_never_stage_or_create_output(tmp_path,monkeypatch,bad):
    import review_eval_package as target
    root,sources,out=package_inputs(tmp_path)
    if bad=='source_hash':sources[0]['video']['sha256']='0'*64
    elif bad=='label_digest':
        p=Path(sources[0]['labels']['path']);p.write_text('{"index":1,"t":11,"session":"session-eval"}\n');sources[0]['labels']['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
    elif bad=='extraction':sources[0]['extractions'][next(iter(sources[0]['extractions']))]['mask']=sources[0]['video']
    elif bad=='missing':sources[0].pop('pts')
    elif bad=='extra':sources.append(copy.deepcopy(sources[0]))
    elif bad=='group':sources[0]['capture_group']='invented'
    elif bad=='ordinal':
        p=Path(sources[0]['pts']['path']);p.write_bytes(b'[{"video_frame":true,"pts":0,"time_base":"1/5"}]');sources[0]['pts']['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
    elif bad=='eval_version':(root/'manifest.json').write_bytes(b'{}')
    def no_stage(*args,**kwargs):pytest.fail('invalid inputs reached artifact staging')
    monkeypatch.setattr(target.tempfile,'TemporaryDirectory',no_stage)
    with pytest.raises((ValueError,OSError)):target.package_eval_companion(root,sources,out)
    assert not out.exists()


def test_existing_output_refused_and_no_overwrite(tmp_path):
    import review_eval_package as target
    root,sources,out=package_inputs(tmp_path);out.mkdir();(out/'operator-wip').write_bytes(b'preserve')
    with pytest.raises((ValueError,FileExistsError)):target.package_eval_companion(root,sources,out)
    assert (out/'operator-wip').read_bytes()==b'preserve'


def test_concurrent_same_output_has_one_exclusive_seal(tmp_path,monkeypatch):
    import review_eval_package as target
    from concurrent.futures import ThreadPoolExecutor
    import threading
    root,sources,out=package_inputs(tmp_path)
    barrier=threading.Barrier(2);original=target.capture_eval_companions
    def joined(*args,**kwargs):
        result=original(*args,**kwargs);barrier.wait(timeout=10);return result
    monkeypatch.setattr(target,'capture_eval_companions',joined)
    def invoke():
        try:return target.package_eval_companion(root,sources,out)
        except (ValueError,OSError) as error:return error
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:invoke(),range(2)))
    assert sum(isinstance(r,dict) for r in results)==1
    assert (out/'COMPLETE').is_file()
    review_dataset.validate_eval_companions([root],[out])


@pytest.mark.parametrize('changed',['source','eval_extra','descriptor'])
def test_changes_after_stage_validation_never_publish_seal(tmp_path,monkeypatch,changed):
    import review_eval_package as target
    root,sources,out=package_inputs(tmp_path);original=target.capture_eval_companions
    descriptor=tmp_path/'sources.json';descriptor.write_text(json.dumps(sources));descriptor_raw=descriptor.read_bytes()
    def mutate(*args,**kwargs):
        result=original(*args,**kwargs)
        if changed=='source':Path(sources[0]['video']['path']).write_bytes(b'changed')
        elif changed=='eval_extra':(root/'unexpected').write_bytes(b'changed')
        else:descriptor.write_bytes(b'[]')
        return result
    monkeypatch.setattr(target,'capture_eval_companions',mutate)
    with pytest.raises(ValueError,match='changed'):
        target.package_eval_companion(root,sources,out,_descriptor_binding=(descriptor,descriptor_raw))
    assert not out.exists()


def test_changed_source_stat_during_capture_is_rejected_before_stage(tmp_path,monkeypatch):
    import review_eval_package as target
    import os
    root,sources,out=package_inputs(tmp_path);path=Path(sources[0]['video']['path']);original=Path.read_bytes
    used=False
    def mutate(self):
        nonlocal used
        raw=original(self)
        if self==path and not used:
            used=True;before=self.stat();self.write_bytes(b'poison')
            os.utime(self,ns=(before.st_atime_ns,before.st_mtime_ns+2_000_000_000))
        return raw
    monkeypatch.setattr(Path,'read_bytes',mutate)
    with pytest.raises(ValueError,match='changed while captured'):target.package_eval_companion(root,sources,out)
    assert not out.exists()


def test_source_aba_does_not_replace_captured_snapshot_bytes(tmp_path,monkeypatch):
    import review_eval_package as target
    root,sources,out=package_inputs(tmp_path);path=Path(sources[0]['video']['path']);original=target._stable_bytes
    raw=path.read_bytes();once=False
    def captured(value):
        nonlocal once
        data=original(value)
        if Path(value)==path and not once:
            once=True;path.write_bytes(b'poison');path.write_bytes(raw)
        return data
    monkeypatch.setattr(target,'_stable_bytes',captured)
    result=target.package_eval_companion(root,sources,out)
    assert (out/'sources'/'session-eval'/'video.bin').read_bytes()==raw
    assert result['training_admission'] is False


@pytest.mark.parametrize('tamper',['reference','resource'])
def test_resealed_stage_tampering_never_publishes(tmp_path,monkeypatch,tamper):
    import review_eval_package as target
    root,sources,out=package_inputs(tmp_path);original=target.capture_eval_companions
    def corrupt(roots,folders,**kwargs):
        stage=Path(folders[0]);manifest=stage/'manifest.json';doc=json.loads(manifest.read_bytes())
        image=doc['frames'][0]['extraction']['image']
        if tamper=='reference':doc['frames'][0]['extraction']['image']='../outside.jpg'
        else:
            (stage/image).write_bytes(b'poison')
            doc['resources'][image]=hashlib.sha256(b'poison').hexdigest()
        raw=json.dumps(doc,sort_keys=True).encode();manifest.write_bytes(raw)
        (stage/'COMPLETE').write_text(hashlib.sha256(raw).hexdigest())
        return original(roots,folders,**kwargs)
    monkeypatch.setattr(target,'capture_eval_companions',corrupt)
    with pytest.raises(ValueError):target.package_eval_companion(root,sources,out)
    assert not out.exists()


def test_source_traversal_and_link_refused(tmp_path):
    import review_eval_package as target
    root,sources,out=package_inputs(tmp_path);binding=sources[0]['labels'];source=Path(binding['path'])
    binding['path']=str(source.parent/'..'/source.parent.name/source.name)
    with pytest.raises(ValueError,match='traversal'):target.package_eval_companion(root,sources,out)
    binding['path']=str(source)
    link=tmp_path/'link.jsonl'
    try:link.symlink_to(source)
    except OSError:pytest.skip('host symlink creation unavailable')
    binding['path']=str(link)
    with pytest.raises(ValueError,match='links'):target.package_eval_companion(root,sources,out)
    assert not out.exists()


def test_cli_roundtrip_and_failed_input_exit(tmp_path):
    import review_eval_package as target
    root,sources,out=package_inputs(tmp_path);config=tmp_path/'sources.json';config.write_text(json.dumps(sources))
    argv=[sys.executable,str(Path(target.__file__)), '--eval-folder',str(root),'--sources',str(config),'--out',str(out)]
    result=subprocess.run(argv,capture_output=True,text=True,check=False)
    assert result.returncode==0,result.stdout+result.stderr
    assert json.loads(result.stdout)['training_admission'] is False
    config.write_text('[]');argv[-1]=str(tmp_path/'invalid')
    result=subprocess.run(argv,capture_output=True,text=True,check=False)
    assert result.returncode==2 and json.loads(result.stdout)['status']=='HOLD'
    assert not Path(argv[-1]).exists()
