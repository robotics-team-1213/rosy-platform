"""Registered learning data reaches the normal archive without changing its source."""
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading
from types import SimpleNamespace
import uuid

import pytest

from test_storage_setup import setup_case, accounts, pool_setup, jobs_setup  # noqa: F401

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'learning/training/omx'))


@pytest.fixture
def registered(tmp_path):
    from experiment_catalog import Catalog
    from experiment_smoke import generate
    root = tmp_path / 'center'
    (root / 'uploads').mkdir(parents=True)
    (root / 'datasets').mkdir()
    def connect(): return sqlite3.connect(root / 'center.sqlite')
    with connect() as db:
        db.execute('CREATE TABLE datasets (id TEXT PRIMARY KEY, document TEXT NOT NULL)')
        db.execute('CREATE TABLE workspace_binding (singleton INTEGER PRIMARY KEY, project_id TEXT)')
        db.execute("INSERT INTO workspace_binding VALUES (1, 'one')")
    catalog = Catalog(root, connect, threading.RLock())
    uid = str(uuid.uuid4())
    generate(root / 'uploads' / uid, arms=1, cameras=1)
    (root / 'uploads' / uid / 'conversion-receipt.json').write_text('{"fixture":true}')
    row = catalog.publish(dict(upload_id=uid, name='Registered fixture'))
    return SimpleNamespace(catalog=catalog), row, root / 'datasets' / uid


def preparation(setup_case, center, row, *, activate=True):
    from storage_prepare import StoragePrepare
    build, actor, body, now, artifact, remote = setup_case
    for quota in body['quotas'].values(): quota['remaining_bytes'] = 16 * 1024 ** 2
    build().save(actor, body)
    if activate:
        build().verify(actor, 1)
        build().activate(actor, 1)
    request = dict(kind='omx', dataset_id=row['id'], revision=row['revision'],
                   confirm_completed=True, archive=True)
    return StoragePrepare(build(), omx_center=center), actor, request, remote


def test_discovery_is_read_only_and_archive_retry_preserves_original(setup_case, registered):
    center, row, source = registered
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    prepare, actor, body, remote = preparation(setup_case, center, row)
    commits = remote.commits
    sources = prepare.sources(actor)
    assert sources['omx_configured'] and sources['datasets'] == [
        {key: row[key] for key in ('id', 'name', 'revision', 'source')}]
    assert str(source) not in json.dumps(sources)
    assert remote.commits == commits
    exports = Path(next(r['path'] for r in prepare.setup.configuration()[1]['roots'] if r['id'] == 'exports'))
    assert not list(exports.glob('omx-*'))
    first = prepare.prepare(actor, body)
    again = prepare.prepare(actor, body)
    assert first['id'] == again['id'] and first['bytes_verified']
    assert first['provenance']['dataset_id'] == row['id']
    assert first['provenance']['source_revision'] == row['revision']
    assert first['provenance']['format'] == 'rosy.omx.experiment-dataset'
    assert remote.commits == commits + 1
    assert before == {p.name: p.read_bytes() for p in source.iterdir()}


@pytest.mark.parametrize('change', ['unknown', 'revision', 'project', 'tamper', 'symlink', 'hardlink', 'extra'])
def test_source_refusals_preserve_original_and_never_upload(setup_case, registered, change):
    center, row, source = registered
    prepare, actor, body, remote = preparation(setup_case, center, row)
    if change == 'unknown': body['dataset_id'] = str(uuid.uuid4())
    elif change == 'revision': body['revision'] = '0' * 64
    elif change == 'project':
        with center.catalog.connect() as db: db.execute("UPDATE workspace_binding SET project_id='other'")
    elif change == 'tamper': (source / 'train.npz').write_bytes(b'changed')
    elif change in ('symlink', 'hardlink'):
        original = source / 'train.npz'
        outside = source.parent / 'outside.npz'
        original.rename(outside)
        if change == 'symlink': original.symlink_to(outside)
        else: os.link(outside, original)
    else: (source / 'unregistered.json').write_text('{}')
    commits = remote.commits
    with pytest.raises((ValueError, OSError)): prepare.prepare(actor, body)
    assert source.is_dir() and remote.commits == commits


def test_partial_copy_resumes_but_changed_partial_bytes_are_preserved(setup_case, registered, monkeypatch):
    import storage_source
    center, row, source = registered
    prepare, actor, body, remote = preparation(setup_case, center, row)
    original = storage_source._generated
    def interrupted(fd, name, raw, **kwargs):
        if name == 'train.npz': raise OSError('interrupted copy')
        return original(fd, name, raw, **kwargs)
    monkeypatch.setattr(storage_source, '_generated', interrupted)
    with pytest.raises(OSError): prepare.prepare(actor, body)
    exports = Path(next(r['path'] for r in prepare.setup.configuration()[1]['roots'] if r['id'] == 'exports'))
    folder = next(exports.glob('omx-*'))
    assert not (folder / 'storage-source.json').exists()
    changed = folder / 'dataset.json'
    changed.write_bytes(b'conflicting bytes')
    monkeypatch.setattr(storage_source, '_generated', original)
    commits = remote.commits
    with pytest.raises(ValueError): prepare.prepare(actor, body)
    assert changed.read_bytes() == b'conflicting bytes' and remote.commits == commits
    changed.write_bytes((source / 'dataset.json').read_bytes())
    assert prepare.prepare(actor, body)['bytes_verified']


def test_receipt_change_during_copy_cannot_be_sealed_or_uploaded(setup_case, registered, monkeypatch):
    import storage_source
    center, row, source = registered
    prepare, actor, body, remote = preparation(setup_case, center, row)
    original = storage_source._generated
    def changed(fd, name, raw, **kwargs):
        result = original(fd, name, raw, **kwargs)
        if name == 'train.npz': (source / 'conversion-receipt.json').write_text('{"changed":true}')
        return result
    monkeypatch.setattr(storage_source, '_generated', changed)
    commits = remote.commits
    with pytest.raises(ValueError): prepare.prepare(actor, body)
    assert remote.commits == commits
    exports = Path(next(r['path'] for r in prepare.setup.configuration()[1]['roots'] if r['id'] == 'exports'))
    assert not list(exports.glob('omx-*/storage-source.json'))


def test_destination_alias_is_refused_and_source_descriptor_is_closed(setup_case, registered, monkeypatch):
    import storage_omx
    center, row, source = registered
    prepare, actor, body, remote = preparation(setup_case, center, row)
    exports = Path(next(r['path'] for r in prepare.setup.configuration()[1]['roots'] if r['id'] == 'exports'))
    (exports / f'omx-{row["id"]}-{row["revision"]}').symlink_to(source, target_is_directory=True)
    opened, original = [], storage_omx.open_root
    def tracked(path):
        fd = original(path)
        opened.append(fd)
        return fd
    monkeypatch.setattr(storage_omx, 'open_root', tracked)
    commits = remote.commits
    with pytest.raises(OSError): prepare.prepare(actor, body)
    for fd in opened:
        with pytest.raises(OSError): os.fstat(fd)
    assert not (source / 'storage-source.json').exists() and remote.commits == commits


@pytest.mark.parametrize('field,value', [('confirm_completed', False), ('dataset_id', '../outside'),
    ('revision', 'main'), ('path', '/arbitrary/host/path')])
def test_preparation_requires_fixed_identity_and_consent(setup_case, registered, field, value):
    center, row, source = registered
    prepare, actor, body, remote = preparation(setup_case, center, row, activate=False)
    body[field] = value
    with pytest.raises(ValueError): prepare.prepare(actor, body)
    assert remote.commits == 0
