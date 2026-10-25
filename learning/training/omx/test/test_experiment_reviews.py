"""Immutable human decisions bind current source identity without changing original labels."""
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import threading
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_native_cycle import module, splits
from test_experiment_native import capture
from test_experiment_export import prepared as export_prepared


@pytest.fixture
def workspace(export_prepared, tmp_path):
    from experiment_reviews import Reviews
    _, prepared, row, _ = export_prepared
    inspection = json.loads((prepared / 'inspection.json').read_text())
    inspection.update(reader_verified=True, camera_keys=['observation.images.top', 'observation.images.wrist'])
    (prepared / 'inspection.json').write_text(json.dumps(inspection))
    decisions = json.loads((prepared / 'decisions.json').read_text())
    for decision in decisions:
        decision.update(outcome='unknown', split='exclude', reviewer='', reason='')
    (prepared / 'decisions.json').write_text(json.dumps(decisions))
    root = tmp_path / 'center'
    root.mkdir()
    connect = lambda: sqlite3.connect(root / 'center.sqlite')
    reviews = Reviews(root, connect, threading.RLock())
    with connect() as db:
        reviews.schema(db)
    return reviews, prepared, row


def body(view):
    return dict(prepared_id=view['prepared_id'], source_revision=view['source_revision'],
        decisions=[dict(episode_index=row['episode_index'], outcome='success', split=split,
                        object_result='moved_as_intended', reason='Observed complete placement')
                   for row, split in zip(view['inspection']['episodes'], ('train', 'eval', 'test'))],
        reviewer='Local operator', confirmed=True, request_id=str(uuid.uuid4()))


def test_unknown_originals_are_reviewable_and_saves_never_change_source(workspace):
    reviews, prepared, row = workspace
    original = (prepared / 'decisions.json').read_bytes()
    view = reviews.describe(row)
    assert view['latest_review_id'] is None and not view['trainable']['ok']
    assert view['reviewer_identity'] is None
    assert [decision['outcome'] for decision in view['decisions']] == ['unknown'] * 3
    saved = reviews.save(body(view), row)
    assert saved['trainable']['ok'] and saved['saved_review_id'] == saved['latest_review_id']
    assert (prepared / 'decisions.json').read_bytes() == original
    exported = reviews.for_export(saved['saved_review_id'], row)
    assert exported['reviewer_identity'] == {'kind': 'local_unverified', 'id': 'Local operator'}
    assert all(decision['reviewer'] == 'Local operator' for decision in exported['decisions'])
    folder = reviews.root / 'reviews' / saved['saved_review_id']
    assert exported['sha256'] == hashlib.sha256((folder / 'decisions.json').read_bytes()).hexdigest()
    assert (folder / 'review.json').is_file()


def test_authenticated_identity_wins_and_retry_is_bound_to_actor_and_exact_body(workspace):
    reviews, _, row = workspace
    request = body(reviews.describe(row))
    request['reviewer'] = 'Someone else'
    first = reviews.save(request, row, actor={'user_id': 'alice'})
    second = reviews.save(request, row, actor={'user_id': 'alice'})
    assert first['saved_review_id'] == second['saved_review_id']
    assert first['reviewer_identity'] == {'kind': 'authenticated', 'id': 'alice'}
    assert reviews.describe(row)['reviewer_identity'] == {'kind': 'authenticated', 'id': 'alice'}
    assert len(list((reviews.root / 'reviews').iterdir())) == 1
    exported = reviews.for_export(first['saved_review_id'], row)
    assert exported['reviewer_identity'] == {'kind': 'authenticated', 'id': 'alice'}
    assert all(decision['reviewer'] == 'alice' for decision in exported['decisions'])
    with pytest.raises(ValueError, match='request'):
        reviews.save(request, row, actor={'user_id': 'bob'})
    changed = copy.deepcopy(request)
    changed['decisions'][0]['reason'] = 'Different review'
    with pytest.raises(ValueError, match='request'):
        reviews.save(changed, row, actor={'user_id': 'alice'})


@pytest.mark.parametrize('fault', ['missing', 'reordered', 'identity_injection', 'not_confirmed',
                                  'bad_enum', 'missing_reason', 'unknown_included', 'stale'])
def test_invalid_or_stale_review_cannot_create_snapshot(workspace, fault):
    reviews, _, row = workspace
    request = body(reviews.describe(row))
    if fault == 'missing':
        request['decisions'].pop()
    elif fault == 'reordered':
        request['decisions'].reverse()
    elif fault == 'identity_injection':
        request['decisions'][0]['session_id'] = 'browser-forgery'
    elif fault == 'not_confirmed':
        request['confirmed'] = False
    elif fault == 'bad_enum':
        request['decisions'][0]['split'] = 'automatic'
    elif fault == 'missing_reason':
        request['decisions'][0]['reason'] = ''
    elif fault == 'unknown_included':
        request['decisions'][0]['outcome'] = 'unknown'
    elif fault == 'stale':
        request['source_revision'] = '0' * 64
    with pytest.raises(ValueError):
        reviews.save(request, row)
    assert not (reviews.root / 'reviews').exists() or not list((reviews.root / 'reviews').iterdir())


def test_incomplete_split_draft_is_saved_but_cannot_export(workspace):
    reviews, _, row = workspace
    request = body(reviews.describe(row))
    for decision in request['decisions']:
        decision['split'] = 'train'
    saved = reviews.save(request, row)
    assert not saved['trainable']['ok'] and saved['trainable']['reason']
    with pytest.raises(ValueError, match='trainable'):
        reviews.for_export(saved['saved_review_id'], row)


def test_fixture_is_reviewable_but_never_production_trainable(workspace):
    reviews, prepared, row = workspace
    (prepared / 'intake-receipt.json').write_text(json.dumps({'reader_verified': True, 'fixture_only': True}))
    view = reviews.describe(row)
    assert view['fixture_only'] is True
    saved = reviews.save(body(view), row)
    assert not saved['trainable']['ok']
    with pytest.raises(ValueError, match='trainable|production'):
        reviews.for_export(saved['saved_review_id'], row)


@pytest.mark.parametrize('tamper_final', [False, True])
def test_partial_snapshot_write_recovers_reserved_identity_without_replacing_final(workspace, monkeypatch, tamper_final):
    reviews, _, row = workspace
    request = body(reviews.describe(row))
    request['decisions'][0]['reason'] = 'Placement complete.\nNo slip observed.'
    original_open = Path.open
    failed = False

    def interrupted(path, mode='r', *args, **kwargs):
        stream = original_open(path, mode, *args, **kwargs)
        if 'review.json' not in path.name or mode != 'xb' or failed:
            return stream

        class PartialWrite:
            def __enter__(self):
                stream.__enter__()
                return self

            def __exit__(self, *error):
                return stream.__exit__(*error)

            def __getattr__(self, name):
                return getattr(stream, name)

            def write(self, raw):
                nonlocal failed
                stream.write(raw[:max(1, len(raw) // 3)])
                stream.flush()
                failed = True
                raise OSError('simulated interrupted snapshot write')

        return PartialWrite()

    monkeypatch.setattr(Path, 'open', interrupted)
    with pytest.raises(OSError, match='interrupted'):
        reviews.save(request, row)
    with reviews.connect() as db:
        reserved, committed = db.execute('SELECT id,committed FROM native_reviews').fetchone()
    assert committed == 0
    folder = reviews.root / 'reviews' / reserved
    assert not (folder / 'review.json').exists()
    partial = (folder / 'decisions.json').read_bytes()
    if tamper_final:
        corrupted = b'{"unknown": "partial or tampered final"'
        (folder / 'review.json').write_bytes(corrupted)
        with pytest.raises(ValueError, match='immutable'):
            reviews.save(request, row)
        assert (folder / 'review.json').read_bytes() == corrupted
        with reviews.connect() as db:
            assert db.execute('SELECT committed FROM native_reviews WHERE id=?', (reserved,)).fetchone() == (0,)
        return
    saved = reviews.save(request, row)
    assert saved['saved_review_id'] == reserved
    assert (reviews.root / 'reviews' / reserved / 'decisions.json').read_bytes() == partial
    assert saved['decisions'][0]['reason'] == request['decisions'][0]['reason']
    assert json.loads((folder / 'review.json').read_text())['id'] == reserved


@pytest.mark.parametrize('fault', ['source', 'snapshot', 'unverified', 'link'])
def test_export_rechecks_source_and_immutable_snapshot(workspace, fault):
    reviews, prepared, row = workspace
    saved = reviews.save(body(reviews.describe(row)), row)
    if fault == 'source':
        (prepared / 'decisions.json').write_text('[]')
    elif fault == 'snapshot':
        (reviews.root / 'reviews' / saved['saved_review_id'] / 'decisions.json').write_text('[]')
    elif fault == 'unverified':
        report = json.loads((prepared / 'inspection.json').read_text())
        report['reader_verified'] = False
        (prepared / 'inspection.json').write_text(json.dumps(report))
    elif fault == 'link':
        path = prepared / 'data/part.parquet'
        target = prepared / 'data/original.parquet'
        path.rename(target)
        path.symlink_to(target)
    with pytest.raises(ValueError):
        reviews.for_export(saved['saved_review_id'], row)
