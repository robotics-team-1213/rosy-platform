"""Isolated composition; real user state, GPU and device control never touched."""
import copy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'training'))
import learning_cycle
import review_pipeline
from job_state import JobError
from test_review_admission import fixture
from test_review_dataset import delivery, digest


def setup(tmp_path):
    args, authority, built, trainer = fixture(tmp_path)
    receipt = delivery(authority)
    receipt['revision'] = {k: authority[k] for k in ('workspace_id','generation','decision_sha256')}
    current = tmp_path/'current.json'
    current.write_text(json.dumps(receipt))
    requests = tmp_path/'requests'; requests.mkdir()
    config = dict(trainer={k:v for k,v in trainer.items() if k not in ('dataset','training')},
                  recipes=[trainer['training']], requests_dir=str(requests),
                  reviews_dir=str(args['export_root'].parent), interval_s=1,max_attempts=1,
                  authority=dict(path=str(current),workspace_id=authority['workspace_id'],max_age_s=90))
    owner=review_pipeline.ReviewPipeline(source_proof_files=args['source_proof_files'],
        staging_parent=args['staging_parent'],dataset_name='indexed',now=lambda:100)
    return args,authority,built,config,owner,current,requests


def test_build_request_and_owner_admission_reach_isolated_trainer_once(tmp_path):
    args, authority, built, config, owner, current, requests=setup(tmp_path)
    calls=[]
    def train(cfg,out,*,indexed_review):
        dataset=args['store'].dataset_path(*cfg['dataset'].split('@'))
        with indexed_review.open(cfg,dataset,args['eval_folders'][0],[]) as admitted:
            calls.append(admitted.evidence)
        return {'scope':'synthetic trainer boundary only'}
    state=learning_cycle.run_once(config,tmp_path/'cycle',trainer_fn=train,review_pipeline=owner)
    assert len(list(requests.glob('*.json')))==1
    assert len(calls)==1 and calls[0]['dataset_sha']==built['dataset_revision']
    assert next(iter(state['cycles'].values()))['status']=='ready'
    learning_cycle.run_once(config,tmp_path/'cycle',trainer_fn=train,review_pipeline=owner)
    assert len(calls)==1
    assert not list(args['store'].root.rglob('READY'))


@pytest.mark.parametrize('cycle_ttl,owner_ttl', [(5, 90), (90, 5)])
@pytest.mark.parametrize('age', [2, 20])
def test_owner_composition_keeps_the_stricter_freshness_before_request_and_training(
        tmp_path, monkeypatch, cycle_ttl, owner_ttl, age):
    args, authority, built, config, owner, current, requests = setup(tmp_path)
    config['authority']['max_age_s'] = cycle_ttl
    owner = review_pipeline.ReviewPipeline(source_proof_files=args['source_proof_files'],
        staging_parent=args['staging_parent'], dataset_name='indexed',
        authority_max_age_s=owner_ttl, now=lambda: 100)
    envelope = json.loads(current.read_text())
    envelope['checked_at_unix'] = 100 - age
    current.write_text(json.dumps(envelope))
    monkeypatch.setattr(learning_cycle.time, 'time', lambda: 100)
    limits, trained = [], []
    original = review_pipeline.build_dataset
    def build(*a, **kw):
        limits.append(kw['authority_max_age_s'])
        return original(*a, **kw)
    monkeypatch.setattr(review_pipeline, 'build_dataset', build)
    def train(cfg, out, *, indexed_review):
        assert indexed_review.authority_max_age_s == 5
        with indexed_review.open(cfg, args['store'].dataset_path(*cfg['dataset'].split('@')),
                                 args['eval_folders'][0], []) as admitted:
            trained.append(admitted.evidence)
        return {'scope': 'synthetic; no GPU or READY'}
    state = learning_cycle.run_once(config, tmp_path / 'cycle', trainer_fn=train, review_pipeline=owner)
    if age == 20:
        assert not trained
        assert not list(requests.glob('*.json'))
        assert state['review_autobuild']['status'] == 'held'
    else:
        assert len(trained) == 1 and len(list(requests.glob('*.json'))) == 1
        assert limits == [5]
    assert not list(args['store'].root.rglob('READY'))


@pytest.mark.parametrize('cycle_ttl,owner_ttl', [(5, 90), (90, 5)])
def test_slow_build_cannot_widen_pinned_ttl_before_request(tmp_path, monkeypatch, cycle_ttl, owner_ttl):
    args, authority, built, config, old_owner, current, requests = setup(tmp_path)
    config['authority']['max_age_s'] = cycle_ttl
    clock = [100]
    owner = review_pipeline.ReviewPipeline(source_proof_files=args['source_proof_files'],
        staging_parent=args['staging_parent'], dataset_name='indexed',
        authority_max_age_s=owner_ttl, now=lambda: clock[0])
    monkeypatch.setattr(learning_cycle.time, 'time', lambda: clock[0])
    original = review_pipeline.build_dataset
    def slow(*a, **kw):
        report = original(*a, **kw)
        clock[0] = 120
        return report
    monkeypatch.setattr(review_pipeline, 'build_dataset', slow)
    state = learning_cycle.run_once(config, tmp_path / 'cycle', review_pipeline=owner,
        trainer_fn=lambda *a, **kw: pytest.fail('expired approval cannot enter trainer'))
    assert state['review_autobuild']['status'] == 'held'
    assert not list(requests.glob('*.json'))
    assert not list(args['store'].root.rglob('READY'))


@pytest.mark.parametrize('failure',['expired','workspace','missing_highwater','revoked'])
def test_current_failure_creates_no_request_or_trainer(tmp_path,failure):
    args,authority,built,config,owner,current,requests=setup(tmp_path)
    receipt=json.loads(current.read_text())
    if failure=='expired':receipt['checked_at_unix']=1
    if failure=='workspace':receipt['workspace_id']='different'
    if failure=='missing_highwater':receipt.pop('revision')
    if failure=='revoked':
        changed=copy.deepcopy(authority);changed['generation']+=1
        receipt['authority']=digest(changed)
        receipt['revision']={k:receipt['authority'][k] for k in ('workspace_id','generation','decision_sha256')}
    current.write_text(json.dumps(receipt))
    state=learning_cycle.run_once(config,tmp_path/'cycle',trainer_fn=lambda *a,**kw:pytest.fail('no trainer'),review_pipeline=owner)
    assert not list(requests.glob('*.json'))
    assert state['review_autobuild']['status']=='held'


def test_indexed_manual_request_without_owner_cannot_reach_trainer(tmp_path):
    args,authority,built,config,owner,current,requests=setup(tmp_path)
    (requests/'manual.json').write_text(json.dumps({'purpose':'research','dataset':'indexed@'+built['dataset_revision']}))
    state=learning_cycle.run_once(config,tmp_path/'cycle',trainer_fn=lambda *a,**kw:pytest.fail('owner missing'))
    assert state['requests'][str(requests/'manual.json')]['status']=='blocked'


def test_postbuild_revocation_leaves_content_without_request(tmp_path,monkeypatch):
    args,authority,built,config,owner,current,requests=setup(tmp_path)
    original=review_pipeline.build_dataset
    def revoke(*a,**kw):
        result=original(*a,**kw)
        receipt=json.loads(current.read_text());receipt['available']=False
        current.write_text(json.dumps(receipt))
        return result
    monkeypatch.setattr(review_pipeline,'build_dataset',revoke)
    learning_cycle.run_once(config,tmp_path/'cycle',trainer_fn=lambda *a,**kw:pytest.fail('revoked'),review_pipeline=owner)
    assert not list(requests.glob('*.json'))
    assert Path(built['dataset_path']).exists()


def test_owner_policy_mutation_denied_before_gpu_or_request(tmp_path):
    args,authority,built,config,owner,current,requests=setup(tmp_path)
    owner.dataset_name='modified'
    with pytest.raises(JobError):
        learning_cycle.run_once(config,tmp_path/'cycle',trainer_fn=lambda *a,**kw:pytest.fail('mutated'),review_pipeline=owner)
    assert not list(requests.glob('*.json'))


@pytest.mark.parametrize('change',['gate','config'])
def test_build_callback_cannot_lower_gate_or_replace_recipe(tmp_path,monkeypatch,change):
    args,authority,built,config,owner,current,requests=setup(tmp_path)
    original=review_pipeline.build_dataset
    def changed(*a,**kw):
        result=original(*a,**kw)
        if change=='gate':
            path=Path(config['trainer']['gate']);doc=json.loads(path.read_text())
            doc['min_lane_marking_iou']=0.001;path.write_text(json.dumps(doc))
        else:config['recipes'][0]['epochs']+=1
        return result
    monkeypatch.setattr(review_pipeline,'build_dataset',changed)
    learning_cycle.run_once(config,tmp_path/'cycle',trainer_fn=lambda *a,**kw:pytest.fail('mutated'),review_pipeline=owner)
    assert not list(requests.glob('*.json'))


def test_expiry_during_request_staging_creates_no_request(tmp_path,monkeypatch):
    args,authority,built,config,owner,current,requests=setup(tmp_path)
    original=review_pipeline.os.fsync
    def expired(fd):
        original(fd)
        doc=json.loads(current.read_text());doc['checked_at_unix']=1
        current.write_text(json.dumps(doc))
    # Only stage request publication; cycle Job uses the same os module.
    original_temp=review_pipeline.tempfile.NamedTemporaryFile
    def temp(*a,**kw):
        if str(kw.get('prefix','')).startswith('.request-'):
            monkeypatch.setattr(review_pipeline.os,'fsync',expired)
        return original_temp(*a,**kw)
    monkeypatch.setattr(review_pipeline.tempfile,'NamedTemporaryFile',temp)
    learning_cycle.run_once(config,tmp_path/'cycle',trainer_fn=lambda *a,**kw:pytest.fail('expired'),review_pipeline=owner)
    assert not list(requests.glob('*.json'))


def test_request_then_current_revocation_blocks_restart_even_with_new_owner(tmp_path):
    args,authority,built,config,owner,current,requests=setup(tmp_path)
    learning_cycle.run_once(config,tmp_path/'cycle',trainer_fn=lambda *a,**kw:{},review_pipeline=owner)
    receipt=json.loads(current.read_text());receipt['available']=False
    current.write_text(json.dumps(receipt))
    fresh=review_pipeline.ReviewPipeline(source_proof_files=args['source_proof_files'],
        staging_parent=args['staging_parent'],dataset_name='indexed',now=lambda:100)
    state=learning_cycle.run_once(config,tmp_path/'cycle',trainer_fn=lambda *a,**kw:pytest.fail('revoked'),review_pipeline=fresh)
    assert all(row['status']=='blocked' for row in state['requests'].values())
    assert state['review_pipeline_highwater']['generation']==authority['generation']


@pytest.mark.parametrize('quality',['pass','reject'])
def test_cycle_real_admission_and_ready_composition_uses_synthetic_stages_only(tmp_path,monkeypatch,quality):
    import train_job
    from job_state import Rejected
    from test_training_job import model
    args,authority,built,config,owner,current,requests=setup(tmp_path)
    artifact=tmp_path/'synthetic-artifact';manifest=model(artifact)
    stages=[]
    class FakeTrainingStages:
        def __init__(self,folder,inputs):
            assert inputs['indexed_review']['dataset_sha']==built['dataset_revision']
            Path(folder).mkdir(parents=True,exist_ok=True)
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def step(self,name,callback):
            stages.append(name)
            if name=='train':return {'scope':'synthetic; no GPU/checkpoint computation'}
            if name=='export':return {'artifact':str(artifact),'revision':manifest['model_revision']}
            if name=='intake':
                if quality=='reject':raise Rejected('synthetic existing-model regression')
                return {'artifact':str(artifact),'scope':'synthetic eval receipt, not accuracy evidence'}
            return callback(1)
        def finish(self):pass
    monkeypatch.setattr(train_job,'Job',FakeTrainingStages)
    monkeypatch.setattr(train_job,'gpu_lease',lambda:pytest.fail('no actualGPU'))
    state=learning_cycle.run_once(config,tmp_path/'cycle',review_pipeline=owner)
    row=next(iter(state['cycles'].values()))
    assert row['status']==('ready' if quality=='pass' else 'rejected'),row
    ready=list(args['store'].root.rglob('READY'))
    assert bool(ready)==(quality=='pass')
    assert stages==(['train','export','intake','ready'] if quality=='pass' else ['train','export','intake'])


def test_request_is_one_captured_body_not_hash_then_a_different_body(tmp_path,monkeypatch):
    import test_learning_cycle
    cfg,out,requests=test_learning_cycle.setup.__wrapped__(tmp_path)
    original=learning_cycle.sha
    def swapped(path):
        value=original(path)
        if Path(path).parent==requests:
            Path(path).write_text('{"purpose":"not-the-research-request"}')
        return value
    monkeypatch.setattr(learning_cycle,'sha',swapped)
    calls=[]
    learning_cycle.run_once(cfg,out,trainer_fn=lambda config,path:calls.append(config) or {})
    assert len(calls)==2


def test_same_companion_is_required_by_build_and_private_admission(tmp_path):
    from test_review_dataset import attach_build_companion
    import review_dataset
    args,authority,built,config,owner,current,requests=setup(tmp_path)
    companion,_=attach_build_companion(args,tmp_path)
    gate=Path(config['trainer']['gate']);doc=json.loads(gate.read_text())
    doc['eval_set']=str(args['eval_folders'][0]);gate.write_text(json.dumps(doc))
    owner=review_pipeline.ReviewPipeline(source_proof_files=args['source_proof_files'],
        staging_parent=args['staging_parent'],dataset_name='indexed',eval_companion_files=[companion],now=lambda:100)
    calls=[]
    def train(cfg,out,*,indexed_review):
        assert indexed_review.eval_companion_files==(str(companion.absolute()),)
        dataset=args['store'].dataset_path(*cfg['dataset'].split('@'))
        with indexed_review.open(cfg,dataset,args['eval_folders'][0],[]) as admitted:
            calls.append(admitted.evidence)
        return {'scope':'synthetic companion composition'}
    state=learning_cycle.run_once(config,tmp_path/'cycle',trainer_fn=train,review_pipeline=owner)
    assert len(calls)==1 and next(iter(state['cycles'].values()))['status']=='ready'
    assert not list(args['store'].root.rglob('READY'))


@pytest.mark.parametrize('outcome',['ready','gave_up'])
def test_generation_only_refresh_never_retrains_or_resets_attempt_budget(tmp_path,outcome):
    from test_review_authority import encoded,reseal
    import hashlib
    args,authority,built,config,owner,current,requests=setup(tmp_path)
    calls=[]
    def train(*a,**kw):
        calls.append(True)
        if outcome=='gave_up':raise OSError('synthetic unavailableGPU')
        return {'scope':'synthetic'}
    learning_cycle.run_once(config,tmp_path/'cycle',trainer_fn=train,review_pipeline=owner)
    updated=copy.deepcopy(authority);updated['generation']+=1;updated=digest(updated)
    root=args['export_root'];contract=json.loads((root/'review-contract.json').read_bytes())
    receipt=json.loads((root/'pinky-review-receipt.json').read_bytes());receipt['authority']=updated
    (root/'pinky-review-receipt.json').write_bytes(encoded(receipt))
    legacy=json.loads((root/'manifest.json').read_bytes())
    for row in legacy['files']:
        data=(root/row['path']).read_bytes();row.update(bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
    raw=encoded(legacy);(root/'manifest.json').write_bytes(raw)
    (root/'COMPLETE').write_text(hashlib.sha256(raw).hexdigest()+'\n')
    contract['authority']=updated
    for row in contract['files']:
        data=(root/row['path']).read_bytes();row.update(bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
    reseal(root,contract)
    transfer=delivery(updated);transfer['revision']={k:updated[k] for k in ('workspace_id','generation','decision_sha256')}
    current.write_text(json.dumps(transfer))
    state=learning_cycle.run_once(config,tmp_path/'cycle',trainer_fn=train,review_pipeline=owner)
    assert len(calls)==1
    assert len(list(requests.glob('*.json')))==1
    assert next(iter(state['cycles'].values()))['attempts']==1


def test_no_actual_mask_approval_holds_before_source_or_companion_reads(tmp_path):
    from test_review_authority import current as pending,seal_bundle
    args,authority,built,config,owner,current,requests=setup(tmp_path)
    value=pending();bundle=args['export_root'].parent/'pending';seal_bundle(bundle,value)
    receipt=delivery(value);receipt['revision']={k:value[k] for k in ('workspace_id','generation','decision_sha256')}
    current.write_text(json.dumps(receipt));config['authority']['workspace_id']=value['workspace_id']
    owner=review_pipeline.ReviewPipeline(source_proof_files=[tmp_path/'unread-source'],
        staging_parent=args['staging_parent'],dataset_name='indexed',
        eval_companion_files=[tmp_path/'unread-companion'],now=lambda:100)
    state=learning_cycle.run_once(config,tmp_path/'cycle',trainer_fn=lambda *a,**kw:pytest.fail('no GT'),review_pipeline=owner)
    assert state['review_autobuild']['blockers']==['no_approved_masks']
    assert not list(requests.glob('*.json'))


def test_build_cannot_change_valid_proof_bytes_under_old_logical_budget(tmp_path,monkeypatch):
    args,authority,built,config,owner,current,requests=setup(tmp_path)
    original=review_pipeline.build_dataset
    changed=[False]
    def build(*a,**kw):
        if not changed[0]:
            proof=Path(args['source_proof_files'][0]);value=json.loads(proof.read_text())
            value['operator_note']='valid but different raw source proof binding'
            proof.write_text(json.dumps(value));changed[0]=True
        return original(*a,**kw)
    monkeypatch.setattr(review_pipeline,'build_dataset',build)
    learning_cycle.run_once(config,tmp_path/'cycle',trainer_fn=lambda *a,**kw:pytest.fail('logical source changed'),review_pipeline=owner)
    assert not list(requests.glob('*.json'))


def test_expiry_during_final_logical_recapture_cannot_publish_request(tmp_path,monkeypatch):
    args,authority,built,config,owner,current,requests=setup(tmp_path)
    clock=[100];owner.now=lambda:clock[0]
    original=owner._logical_key;calls=[0]
    def slow(*a,**kw):
        result=original(*a,**kw);calls[0]+=1
        if calls[0]==3:clock[0]=200
        return result
    monkeypatch.setattr(owner,'_logical_key',slow)
    learning_cycle.run_once(config,tmp_path/'cycle',trainer_fn=lambda *a,**kw:pytest.fail('expired'),review_pipeline=owner)
    assert not list(requests.glob('*.json'))
