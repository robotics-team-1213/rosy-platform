"""Synthetic boundary tests: no actual Job, GPU, request or READY is allowed."""
import copy
import json
from pathlib import Path

import pytest

from test_review_dataset import build_fixture, delivery, digest
import review_dataset
import train_job
from job_state import JobError


def fixture(tmp_path):
    args, authority = build_fixture(tmp_path)
    built = review_dataset.build_dataset(**args)
    assert built['status'] == 'PUBLISHED_CONTENT_NOT_ADMITTED', built
    evaluation = args['eval_folders'][0]
    gate = tmp_path / 'gate.json'
    gate.write_text(json.dumps({'require_eval': True, 'eval_set': str(evaluation),
                               'min_lane_marking_iou': 0.1}))
    profile = tmp_path / 'profile.json'; profile.write_text('{"accepted":false}')
    config = dict(store=str(args['store'].root), dataset='indexed@' + built['dataset_revision'],
                  gate=str(gate), replay_root=str(tmp_path), camera_profile=str(profile),
                  intake_out=str(tmp_path / 'intake'),
                  training=dict(seed=1, epochs=1, lr=0.001, batch_size=1, base=8, recipe='baseline'))
    return args, authority, built, config


def context(args, authority, **changes):
    from review_admission import IndexedReview
    values = dict(export_root=args['export_root'], fetch_current=args['fetch_current'],
                  workspace_id=args['workspace_id'], source_proof_files=args['source_proof_files'],
                  staging_parent=args['staging_parent'], previous_authority={key: authority[key]
                  for key in ('workspace_id', 'generation', 'decision_sha256')}, now=args['now'])
    return IndexedReview(**dict(values, **changes))


def test_independent_admission_reaches_only_fake_job_with_captured_dataset(tmp_path, monkeypatch):
    args, authority, built, config = fixture(tmp_path)
    class Boundary(Exception):
        pass
    def job(out, inputs):
        assert inputs['indexed_review']['dataset_sha'] == built['dataset_revision']
        assert inputs['indexed_review']['authority']['generation'] == authority['generation']
        raise Boundary
    monkeypatch.setattr(train_job, 'Job', job)
    monkeypatch.setattr(train_job, 'gpu_lease', lambda: pytest.fail('no real GPU'))
    with pytest.raises(Boundary):
        train_job.run(config, tmp_path / 'job', indexed_review=context(args, authority))
    assert not (tmp_path / 'job').exists()
    assert not list(args['store'].root.rglob('READY'))


@pytest.mark.parametrize('case', ['expired', 'workspace', 'rollback', 'revoked', 'video', 'eval'])
def test_negative_admission_creates_no_job_or_ready(tmp_path, monkeypatch, case):
    args, authority, _, config = fixture(tmp_path)
    changes = {}
    if case == 'expired': changes['now'] = lambda: 200
    if case == 'workspace': changes['workspace_id'] = 'wrong'
    if case == 'rollback':
        changes['previous_authority'] = {**{key: authority[key] for key in
            ('workspace_id', 'generation', 'decision_sha256')}, 'generation': 2}
    if case == 'revoked':
        changed = copy.deepcopy(authority); changed['generation'] += 1
        changed['frames'][0]['mask_decision'] = 'pending'; changed['frames'][0]['pixel_approval'] = None
        changes['fetch_current'] = lambda: delivery(digest(changed))
    if case == 'video': (tmp_path / 'video0.avi').write_bytes(b'changed')
    if case == 'eval': (args['eval_folders'][0] / 'image.png').write_bytes(b'changed')
    monkeypatch.setattr(train_job, 'Job', lambda *a: pytest.fail('denial before Job'))
    monkeypatch.setattr(train_job, 'gpu_lease', lambda: pytest.fail('denial before GPU'))
    with pytest.raises(JobError):
        train_job.run(config, tmp_path / 'job', indexed_review=context(args, authority, **changes))
    assert not (tmp_path / 'job').exists()
    assert not list(args['store'].root.rglob('READY'))


@pytest.mark.parametrize('change', ['config', 'authority', 'gate', 'source', 'snapshot', 'eval_snapshot'])
def test_admitted_session_rechecks_changes_and_uses_private_bytes(tmp_path, change):
    args, authority, built, config = fixture(tmp_path)
    ctx = context(args, authority)
    with ctx.open(config, Path(built['dataset_path']), args['eval_folders'][0], []) as admitted:
        assert admitted.dataset != Path(built['dataset_path'])
        assert (admitted.dataset / 'manifest.json').read_bytes() == (Path(built['dataset_path']) / 'manifest.json').read_bytes()
        assert not admitted.dataset.is_relative_to(args['store'].root)
        if change == 'config': config['training']['epochs'] += 1
        if change == 'gate': Path(config['gate']).write_text('{}')
        if change == 'source': (tmp_path / 'video0.avi').write_bytes(b'changed')
        if change == 'snapshot': (admitted.dataset / 'manifest.json').write_text('{}')
        if change == 'eval_snapshot':
            evaluation = Path(json.loads(admitted.gate_path.read_text())['eval_set'])
            (evaluation / 'image.png').write_bytes(b'changed')
        if change == 'authority':
            changed = copy.deepcopy(authority); changed['generation'] += 1
            args['fetch_current'] = lambda: delivery(digest(changed))
            ctx.fetch_current = args['fetch_current']
        with pytest.raises(JobError): admitted.check()


@pytest.mark.parametrize('case', ['expires', 'recipe', 'trainer_source'])
def test_change_after_slow_reconstruction_denied_before_job(tmp_path, monkeypatch, case):
    import review_admission
    args, authority, built, config = fixture(tmp_path)
    clock = [100]
    source = tmp_path / 'trainer.py'; source.write_text('original')
    original = review_admission.build_dataset
    def slow(*a, **kw):
        report = original(*a, **kw)
        if case == 'expires': clock[0] = 200
        if case == 'recipe': config['training']['recipe'] = 'enhanced'
        if case == 'trainer_source': source.write_text('changed')
        return report
    monkeypatch.setattr(review_admission, 'build_dataset', slow)
    ctx = context(args, authority, now=lambda: clock[0])
    with pytest.raises(JobError):
        with ctx.open(config, Path(built['dataset_path']), args['eval_folders'][0], [source]):
            pytest.fail('interleaving must deny before admitted session')


@pytest.mark.parametrize('case', ['revoke', 'expire'])
def test_new_decision_after_fake_job_entry_denied_before_training_import_or_gpu(tmp_path, monkeypatch, case):
    args, authority, _, config = fixture(tmp_path)
    clock = [100]
    ctx = context(args, authority, now=lambda: clock[0])
    class FakeJob:
        def __init__(self, *a): pass
        def __enter__(self):
            if case == 'expire': clock[0] = 200
            else:
                changed = copy.deepcopy(authority); changed['generation'] += 1
                ctx.fetch_current = lambda: delivery(digest(changed))
            return self
        def __exit__(self, *a): pass
        def step(self, name, callback):
            assert name == 'train'
            return callback(1)
    monkeypatch.setattr(train_job, 'Job', FakeJob)
    monkeypatch.setattr(train_job, 'gpu_lease', lambda: pytest.fail('no GPU after revocation'))
    with pytest.raises(JobError): train_job.run(config, tmp_path / 'job', indexed_review=ctx)
    assert not (tmp_path / 'job').exists()


@pytest.mark.parametrize('age', [True, 91, float('nan')])
def test_owner_context_does_not_relax_bounded_freshness(tmp_path, age):
    args, authority, built, config = fixture(tmp_path)
    with pytest.raises(JobError):
        with context(args, authority, authority_max_age_s=age).open(
                config, Path(built['dataset_path']), args['eval_folders'][0], []):
            pytest.fail('invalid TTL')


def test_new_job_cannot_start_without_persisted_owner_highwater(tmp_path):
    args, authority, built, config = fixture(tmp_path)
    with pytest.raises(JobError, match='highwater'):
        with context(args, authority, previous_authority=None).open(
                config, Path(built['dataset_path']), args['eval_folders'][0], []):
            pytest.fail('fresh job must not reset highwater')


@pytest.mark.parametrize('case', ['recipe', 'snapshot', 'expiry', 'evalbytes', 'evalinventory', 'source_metadata', 'source_video'])
def test_final_current_callback_cannot_mutate_verified_inputs(tmp_path, monkeypatch, case):
    import review_admission
    args, authority, built, config = fixture(tmp_path)
    clock = [100]
    ctx = context(args, authority, now=lambda: clock[0])
    with ctx.open(config, Path(built['dataset_path']), args['eval_folders'][0], []) as admitted:
        calls = [0]
        def fetch():
            calls[0] += 1
            # initial delivery + builder initial/pre/post + final delivery
            if calls[0] == 5:
                if case == 'recipe': config['training']['epochs'] += 1
                if case == 'snapshot': (admitted.dataset / 'manifest.json').write_text('{}')
                if case == 'evalbytes': (args['eval_folders'][0] / 'image.png').write_bytes(b'changed')
                if case == 'evalinventory':
                    import shutil
                    root = args['eval_folders'][0]
                    shutil.copytree(root, args['store'].evalsets_dir / 'added' / root.name)
                if case == 'source_metadata':
                    proof=Path(args['source_proof_files'][0]); value=json.loads(proof.read_text())
                    value['operator_note']='changed after reconstruction'
                    proof.write_text(json.dumps(value))
                if case == 'source_video':
                    (tmp_path/'video0.avi').write_bytes(b'changed after reconstruction')
            return delivery(authority)
        ctx.fetch_current = fetch
        if case == 'expiry':
            original = admitted._check_inputs
            checks = [0]
            def slow_inputs():
                original(); checks[0] += 1
                if checks[0] == 2: clock[0] = 200
            monkeypatch.setattr(admitted, '_check_inputs', slow_inputs)
        with pytest.raises(JobError): admitted.check()


@pytest.mark.parametrize('case', ['revocation', 'expiry'])
def test_resumed_fake_job_denies_before_ready_publication(tmp_path, monkeypatch, case):
    args, authority, _, config = fixture(tmp_path)
    clock = [100]
    ctx = context(args, authority, now=lambda: clock[0])
    class FakeResume:
        def __init__(self, *a): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def step(self, name, callback):
            if name in ('train', 'export', 'intake'):
                return {'artifact': 'unused', 'revision': 'unused'}
            assert name == 'ready'
            if case == 'expiry': clock[0] = 200
            else:
                changed = copy.deepcopy(authority); changed['generation'] += 1
                ctx.fetch_current = lambda: delivery(digest(changed))
            return callback(1)
    monkeypatch.setattr(train_job, 'Job', FakeResume)
    monkeypatch.setattr(train_job, 'publish_ready', lambda *a: pytest.fail('no READY after revoked admission'))
    monkeypatch.setattr(train_job, 'gpu_lease', lambda: pytest.fail('no real GPU'))
    with pytest.raises(JobError): train_job.run(config, tmp_path / 'job', indexed_review=ctx)
    assert not list(args['store'].root.rglob('READY'))


@pytest.mark.parametrize('case', ['gate', 'camera'])
def test_validated_trainer_bytes_cannot_change_before_admission_capture(tmp_path, monkeypatch, case):
    from review_admission import IndexedReview
    args, authority, _, config = fixture(tmp_path)
    original = IndexedReview.open
    def changed(self, *a, **kw):
        if case == 'gate':
            value = json.loads(Path(config['gate']).read_text())
            value['min_lane_marking_iou'] = 0.01
            Path(config['gate']).write_text(json.dumps(value))
        else: Path(config['camera_profile']).write_text('{"accepted":true}')
        return original(self, *a, **kw)
    monkeypatch.setattr(IndexedReview, 'open', changed)
    monkeypatch.setattr(train_job, 'Job', lambda *a: pytest.fail('changed validated inputs before Job'))
    with pytest.raises(JobError, match='validated gate/camera/trainer'):
        train_job.run(config, tmp_path / 'job', indexed_review=context(args, authority))


@pytest.mark.parametrize('case', ['revocation', 'expiry'])
def test_slow_artifact_copy_cannot_publish_ready_after_authority_loss(tmp_path, monkeypatch, case):
    from test_training_job import model
    args, authority, built, config = fixture(tmp_path)
    clock = [100]
    ctx = context(args, authority, now=lambda: clock[0])
    artifact = tmp_path / 'synthetic-artifact'; model(artifact)
    with ctx.open(config, Path(built['dataset_path']), args['eval_folders'][0], []) as admitted:
        original = train_job.shutil.copyfileobj
        def slow(*a, **kw):
            result = original(*a, **kw)
            if case == 'expiry': clock[0] = 200
            else:
                changed = copy.deepcopy(authority); changed['generation'] += 1
                ctx.fetch_current = lambda: delivery(digest(changed))
            return result
        monkeypatch.setattr(train_job.shutil, 'copyfileobj', slow)
        with pytest.raises(JobError):
            train_job.publish_ready(artifact, args['store'].root, 'isolated', before_ready=admitted.check)
        assert not list(args['store'].root.rglob('READY'))
