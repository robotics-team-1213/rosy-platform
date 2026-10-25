"""D-874: Learning seals a human-truth evaluation into a write-once promotion request; it never approves."""
import hashlib
import json
import shutil
import threading
from contextlib import contextmanager

import pytest

import promotion_request as pr
from store import content_sha
from learning_workspace import Workspace
from review_app import make_server
from test_review_app import open_store
from test_learning_collaboration import Accounts, request


def _fixed(stage, target_parent, doc, extra=None):
    stage.mkdir(parents=True)
    (stage / 'manifest.json').write_text(json.dumps(doc), encoding='utf-8')
    for name, raw in (extra or {}).items():
        (stage / name).write_bytes(raw)
    target = target_parent / content_sha(stage)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(stage), str(target))
    return target


def candidate(tmp_path, name='human', sources=('human_reviewed_eval',), source_kind='mcap'):
    store = tmp_path / 'store'
    frame = {'session': 's-eval', 'split': 'eval', 'sources': list(sources), 'source_kind': source_kind}
    evalset = _fixed(tmp_path / f'stage-eval-{name}', store / 'evalsets' / name,
                     {'purpose': 'eval', 'frames': [frame]}, {'0.png': name.encode()})
    dataset = _fixed(tmp_path / f'stage-data-{name}', store / 'datasets' / 'train',
                     {'schema': 'rosy.perception.dataset/1', 'name': name, 'frames': [],
                      'external_sources': {'huggingface_frames': 2, 'percent': 10.0, 'groups': ['hf:dataset/x@' + 'a' * 40],
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
    return root


def test_identical_content_gives_one_hash_written_once(tmp_path):
    root = candidate(tmp_path)
    first = pr.build(root, 'alice', now='2026-10-25T00:00:00+00:00')
    assert first == pr.build(root, 'alice', now='2026-10-25T00:00:00+00:00')
    assert first['state'] == 'requested' and first['dataset']['external_sources']['split'] == 'train_only'
    state = tmp_path / 'state'
    state.mkdir()
    written = pr.write(state, first)
    assert pr.write(state, first) == written
    files = list((state / 'promotion-requests').iterdir())
    assert [f.name for f in files] == [written['sha256'] + '.json']
    assert hashlib.sha256(files[0].read_bytes()).hexdigest() == written['sha256']
    files[0].write_bytes(b'{}')
    with pytest.raises(ValueError, match='다른 내용'):
        pr.write(state, first)
    assert files[0].read_bytes() == b'{}'  # never overwritten


@pytest.mark.parametrize('key', ['approved', 'approval', 'stage', 'to_stage', 'authority', 'decision', 'promoted'])
def test_learning_cannot_write_approval_or_stage_keys(tmp_path, key):
    bundle = pr.build(candidate(tmp_path), 'alice')
    with pytest.raises(ValueError, match='승인'):
        pr.validate(dict(bundle, **{key: True}))
    with pytest.raises(ValueError, match='승인'):
        pr.validate(dict(bundle, model=dict(bundle['model'], **{key: 'L1'})))
    with pytest.raises(ValueError, match='requested'):
        pr.validate(dict(bundle, state='approved'))


@pytest.mark.parametrize('sources, kind, reason', [
    (['lidar'], 'mcap', '자동 라벨'), (['trajectory', 'lidar'], 'mcap', '자동 라벨'),
    (['human_reviewed_eval'], 'huggingface', 'HF 사진'), ([], 'mcap', '사람 확정 정답 표시가 없는')])
def test_automatic_or_hf_eval_frames_are_refused(tmp_path, sources, kind, reason):
    with pytest.raises(ValueError, match=reason):
        pr.build(candidate(tmp_path, sources=sources, source_kind=kind), 'alice')


def test_no_confirmed_eval_is_refused_with_its_reason(tmp_path):
    root = candidate(tmp_path)
    report = json.loads((root / 'intake_report.json').read_text())
    report['eval'] = None
    (root / 'intake_report.json').write_text(json.dumps(report))
    item = {'kind': 'perception', 'id': 'x', 'name': 'm', 'path': str(root)}
    listed = pr.listing(tmp_path, [item, dict(item, kind='omx')])
    assert listed == {'candidates': [{'qualified': False, 'reason': listed['candidates'][0]['reason'],
                                      'id': 'x', 'name': 'm'}], 'requests': []}
    assert '평가 결과가 없습니다' in listed['candidates'][0]['reason']


@contextmanager
def running(tmp_path):
    store = open_store(tmp_path)
    link = Workspace(store.db).register({'kind': 'perception', 'name': 'lane', 'path': str(candidate(tmp_path))})
    server = make_server(store, 0, accounts=Accounts())
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
        code, listed = request(base, path, 'reader')
        assert code == 200 and listed['candidates'][0]['qualified'] is True
        assert [(r['sha256'], r['requester']) for r in listed['requests']] == [(made['sha256'], 'reviewer')]
