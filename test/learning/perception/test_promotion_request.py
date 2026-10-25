"""D-874: Learning seals a human-truth evaluation into a write-once promotion request; it never approves."""
import hashlib
import json
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import promotion_request as pr
from store import content_sha
from learning_workspace import Workspace
from review_app import make_server
from test_review_app import open_store
from test_learning_collaboration import Accounts, request


def owner(tmp_path):
    """Stand-in for the bound learning control: its config names the store, its out holds the cycle ledger."""
    config, out = tmp_path / 'pipeline.json', tmp_path / 'cycle'
    if not config.exists():
        out.mkdir()
        config.write_text(json.dumps({'cycle': {'trainer': {'store': str(tmp_path / 'store')}}}))
        (out / 'state.json').write_text(json.dumps({'cycles': {}}))
    return SimpleNamespace(config=config, out=out, status=lambda: {'available': False})


def _fixed(stage, target_parent, doc, extra=None):
    stage.mkdir(parents=True)
    (stage / 'manifest.json').write_text(json.dumps(doc), encoding='utf-8')
    for name, raw in (extra or {}).items():
        (stage / name).write_bytes(raw)
    target = target_parent / content_sha(stage)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(stage), str(target))
    return target


def candidate(tmp_path, name='human', sources=('human_reviewed_eval',), source_kind='mcap', *,
              evalsets=None, share=None, ledger_eval=None, ledger_location=None, ledger_files=None):
    control = owner(tmp_path)
    store = tmp_path / 'store'
    frame = {'session': 's-eval', 'split': 'eval', 'sources': list(sources), 'source_kind': source_kind,
             'approval_sha256': 'e' * 64}
    evalset = _fixed(tmp_path / f'stage-eval-{name}', (evalsets or store / 'evalsets') / name,
                     {'purpose': 'eval', 'builder': pr.BOOTSTRAP, 'frames': [frame]}, {'0.png': name.encode()})
    dataset = _fixed(tmp_path / f'stage-data-{name}', store / 'datasets' / 'train',
                     {'schema': 'rosy.perception.dataset/1', 'name': name, 'frames': [],
                      'external_sources': share or {'huggingface_frames': 2, 'percent': 10.0,
                                                    'groups': ['hf:dataset/x@' + 'a' * 40],
                                                    'split': 'train_only', 'own_forced_train': 0}})
    root = tmp_path / f'result-{name}'
    root.mkdir()
    (root / 'model.onnx').write_bytes(b'onnx-' + name.encode())
    revision = f'lane-{name}'
    (root / 'model_manifest.json').write_text(json.dumps({'model_revision': revision,
                                                          'dataset': {'revision': dataset.name}}), encoding='utf-8')
    report = {'verdict': 'pass', 'model_revision': revision,
              'files': [{'name': 'model.onnx', 'sha256': hashlib.sha256((root / 'model.onnx').read_bytes()).hexdigest()}],
              'eval': {'set': {'path': str(evalset), 'content_sha': evalset.name}, 'disjoint': True,
                       'training_dataset': 'train@' + dataset.name, 'frames': 1, 'miou': 0.71,
                       'iou': {'road': 0.71}, 'source_groups': [{'sources': list(sources), 'frames': 1}]}}
    (root / 'intake_report.json').write_text(json.dumps(report), encoding='utf-8')
    ledger = json.loads((control.out / 'state.json').read_text())
    ledger['cycles'][name] = {'status': 'ready', 'result': {'revision': revision, 'location': str(ledger_location or root)},
                              'eval_set': ledger_eval or evalset.name, 'files': ledger_files or report['files'],
                              'provenance': {'source_commit': 'c' * 40, 'python': '3.12.3', 'torch': None}}
    (control.out / 'state.json').write_text(json.dumps(ledger))
    return root, control


def test_identical_content_gives_one_hash_written_once(tmp_path):
    root, control = candidate(tmp_path)
    first = pr.build(root, 'alice', control, now='2026-10-25T00:00:00+00:00')
    assert first == pr.build(root, 'alice', control, now='2026-10-25T00:00:00+00:00')
    assert first == pr.build(root, 'alice', control, fresh=False, now='2026-10-25T00:00:00+00:00')
    assert first['training'] == {'commit': 'c' * 40, 'python': '3.12.3', 'torch': None}
    state = tmp_path / 'state'
    state.mkdir()
    written = pr.write(state, first)
    assert pr.write(state, dict(first, created_at='2026-10-26T00:00:00+00:00')) == written  # same model, same request
    files = list((state / 'promotion-requests').iterdir())
    assert [f.name for f in files] == [written['sha256'] + '.json']
    assert hashlib.sha256(files[0].read_bytes()).hexdigest() == written['sha256']
    files[0].write_bytes(b'{}')
    with pytest.raises(ValueError, match='다른 내용'):
        pr.write(state, first)
    assert files[0].read_bytes() == b'{}'  # never overwritten


def test_concurrent_identical_requests_make_one_file(tmp_path):
    root, control = candidate(tmp_path)
    bundles = [pr.build(root, 'alice', control, now=f'2026-10-25T00:00:{i:02d}+00:00') for i in range(8)]
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda bundle: pr.write(tmp_path, bundle), bundles))
    assert len({row['sha256'] for row in results}) == 1
    assert [p.suffix for p in (tmp_path / 'promotion-requests').iterdir()] == ['.json']


@pytest.mark.parametrize('key', ['approved', 'approval', 'stage', 'to_stage', 'authority', 'decision', 'promoted'])
def test_learning_cannot_write_approval_or_stage_keys(tmp_path, key):
    root, control = candidate(tmp_path)
    bundle = pr.build(root, 'alice', control)
    with pytest.raises(ValueError, match='승인'):
        pr.validate(dict(bundle, **{key: True}))
    with pytest.raises(ValueError, match='승인'):
        pr.validate(dict(bundle, model=dict(bundle['model'], **{key: 'L1'})))
    with pytest.raises(ValueError, match='requested'):
        pr.validate(dict(bundle, state='approved'))


@pytest.mark.parametrize('change', [
    lambda b: b['dataset']['external_sources'].update(state='approved'),
    lambda b: b['dataset']['external_sources'].update(split='val'),
    lambda b: b['dataset']['external_sources'].update(groups=[{'state': 'approved'}]),
    lambda b: b.update(training={'commit': None, 'python': '3.12', 'torch': None, 'state': 'approved'}),
    lambda b: b['training'].update(commit='not-a-commit'),
    lambda b: b['evaluation'].update(frames=True),
    lambda b: b['evaluation'].update(miou=float('nan')),
    lambda b: b['evaluation']['iou'][0].update(value=float('inf')),
    lambda b: b['evaluation']['iou'][0].update(note='x'),
    lambda b: b.update(extra=1)])
def test_nested_values_are_allowlisted(tmp_path, change):
    root, control = candidate(tmp_path)
    bundle = json.loads(json.dumps(pr.build(root, 'alice', control)))
    change(bundle)
    with pytest.raises(ValueError):
        pr.validate(bundle)
    with pytest.raises(ValueError):
        pr.write(tmp_path, bundle)
    assert not (tmp_path / 'promotion-requests').exists()


def test_injected_dataset_share_is_refused_at_build(tmp_path):
    share = {'huggingface_frames': 0, 'percent': 0.0, 'groups': [], 'split': 'train_only', 'own_forced_train': 0,
             'state': 'approved'}
    root, control = candidate(tmp_path, share=share)
    with pytest.raises(ValueError, match='목록'):
        pr.build(root, 'alice', control)


@pytest.mark.parametrize('sources, kind, reason', [
    (['lidar'], 'mcap', '자동 라벨'), (['trajectory', 'lidar'], 'mcap', '자동 라벨'),
    (['human_reviewed_eval'], 'huggingface', 'HF 사진'), ([], 'mcap', '사람 확정 정답 표시가 없는')])
def test_automatic_or_hf_eval_frames_are_refused(tmp_path, sources, kind, reason):
    root, control = candidate(tmp_path, sources=sources, source_kind=kind)
    with pytest.raises(ValueError, match=reason):
        pr.build(root, 'alice', control)


def test_crafted_human_eval_outside_the_owned_store_is_refused(tmp_path):
    root, control = candidate(tmp_path, evalsets=tmp_path / 'elsewhere' / 'evalsets')
    with pytest.raises(ValueError, match='저장소 밖'):
        pr.build(root, 'alice', control)


def test_eval_set_must_match_the_cycle_ledger_and_an_owned_cycle_must_exist(tmp_path):
    root, control = candidate(tmp_path, ledger_eval='f' * 64)
    with pytest.raises(ValueError, match='학습 기록의 평가셋 해시'):
        pr.build(root, 'alice', control)
    with pytest.raises(ValueError, match='소유 학습 실행기'):
        pr.build(root, 'alice', None)


def _eval_path(root, path):
    report = json.loads((root / 'intake_report.json').read_text())
    report['eval']['set']['path'] = str(path)
    (root / 'intake_report.json').write_text(json.dumps(report))


def test_symlink_or_dotdot_out_of_evalsets_is_refused(tmp_path):
    root, control = candidate(tmp_path, evalsets=tmp_path / 'elsewhere' / 'evalsets')
    outside = next((tmp_path / 'elsewhere' / 'evalsets' / 'human').iterdir())
    link = tmp_path / 'store' / 'evalsets' / 'human' / outside.name
    link.parent.mkdir(parents=True)
    link.symlink_to(outside, target_is_directory=True)
    for path in (link, tmp_path / 'store' / 'evalsets' / 'human' / '..' / '..' / '..' / 'elsewhere' / 'evalsets' / 'human' / outside.name):
        _eval_path(root, path)
        with pytest.raises(ValueError, match='저장소 밖'):
            pr.build(root, 'alice', control)


def test_post_rehashes_even_when_the_listing_cache_is_warm(tmp_path):
    import os
    root, control = candidate(tmp_path)
    item = {'kind': 'perception', 'id': 'x', 'name': 'm', 'path': str(root)}
    assert pr.listing(tmp_path, [item], control)['candidates'][0]['qualified'] is True
    model = root / 'model.onnx'
    before = model.stat()
    model.write_bytes(b'ONNX-' + b'human')  # same size
    os.utime(model, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert pr.listing(tmp_path, [item], control)['candidates'][0]['qualified'] is True  # GET trusts size+mtime
    with pytest.raises(ValueError, match='모델 파일 해시'):
        pr.build(root, 'alice', control)


def test_another_models_ledger_row_cannot_be_borrowed(tmp_path):
    root, control = candidate(tmp_path)
    copy = tmp_path / 'copy'
    shutil.copytree(root, copy)  # same revision string and files, but no cycle published this folder
    with pytest.raises(ValueError, match='학습 기록'):
        pr.build(copy, 'alice', control)
    other, control = candidate(tmp_path, 'other', ledger_files=[{'name': 'model.onnx', 'sha256': 'd' * 64}])
    with pytest.raises(ValueError, match='학습 기록'):
        pr.build(other, 'alice', control)
    moved, control = candidate(tmp_path, 'moved', ledger_location=tmp_path / 'somewhere')
    with pytest.raises(ValueError, match='학습 기록'):
        pr.build(moved, 'alice', control)


def test_no_confirmed_eval_is_refused_with_its_reason(tmp_path):
    root, control = candidate(tmp_path)
    report = json.loads((root / 'intake_report.json').read_text())
    report['eval'] = None
    (root / 'intake_report.json').write_text(json.dumps(report))
    item = {'kind': 'perception', 'id': 'x', 'name': 'm', 'path': str(root)}
    listed = pr.listing(tmp_path, [item, dict(item, kind='omx')], control)
    assert listed == {'candidates': [{'qualified': False, 'reason': listed['candidates'][0]['reason'],
                                      'id': 'x', 'name': 'm'}], 'requests': []}
    assert '평가 결과가 없습니다' in listed['candidates'][0]['reason']


def test_listing_reuses_hashes_until_a_file_changes(tmp_path, monkeypatch):
    root, control = candidate(tmp_path)
    item = {'kind': 'perception', 'id': 'x', 'name': 'm', 'path': str(root)}
    assert pr.listing(tmp_path, [item], control)['candidates'][0]['qualified'] is True
    calls = []
    monkeypatch.setattr(pr, 'content_sha', lambda folder: calls.append(folder) or folder.name)
    monkeypatch.setattr(pr, '_sha256', lambda path: calls.append(path))
    assert pr.listing(tmp_path, [item], control)['candidates'][0]['qualified'] is True
    assert calls == []
    (root / 'model.onnx').write_bytes(b'changed')
    assert pr.listing(tmp_path, [item], control)['candidates'][0]['qualified'] is False


@contextmanager
def running(tmp_path):
    store = open_store(tmp_path)
    root, control = candidate(tmp_path)
    link = Workspace(store.db).register({'kind': 'perception', 'name': 'lane', 'path': str(root)})
    server = make_server(store, 0, accounts=Accounts(), control=control)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', link['id']
    finally:
        server.shutdown(); server.server_close(); thread.join()


def test_request_route_needs_manage_and_csrf_and_only_an_id(tmp_path):
    with running(tmp_path) as (base, link):
        path = '/api/learning/promotion-requests'
        for session in ('reader', 'editor'):
            _, state = request(base, '/api/accounts/session', session)
            assert request(base, path, session, {'id': link}, state['token'])[0] == 403
        _, state = request(base, '/api/accounts/session', 'reviewer')
        assert request(base, path, 'reviewer', {'id': link}, 'bad-token')[0] == 403
        assert request(base, path, 'reviewer', {'id': link, 'approved': True}, state['token'])[0] == 400
        code, made = request(base, path, 'reviewer', {'id': link}, state['token'])
        assert code == 200 and len(made['sha256']) == 64
        assert request(base, path, 'reviewer', {'id': link}, state['token']) == (200, made)
        code, listed = request(base, path, 'reader')
        assert code == 200 and listed['candidates'][0]['qualified'] is True
        assert [(r['sha256'], r['requester']) for r in listed['requests']] == [(made['sha256'], 'reviewer')]
