"""A competing import must not leave rejected class bytes in the review workspace."""
import hashlib
from pathlib import Path

import pytest

import review_ingest
from test_review_app import open_store
from test_review_cycle import catalog


def test_import_rechecks_class_binding_before_any_persistence(tmp_path, monkeypatch):
    store = open_store(tmp_path)
    pending_root, winner_root = tmp_path / 'pending', tmp_path / 'winner'
    pending_root.mkdir()
    winner_root.mkdir()
    pending, pending_classes, pending_rows = catalog(pending_root)
    winner, winner_classes, _ = catalog(winner_root)
    winner_classes.write_bytes(winner_classes.read_bytes() + b'\n# competing class file\n')
    rejected_sha = hashlib.sha256(pending_classes.read_bytes()).hexdigest()

    def snapshot():
        with store.connect() as db:
            tables = tuple(db.iterdump())
        files = {p.relative_to(store.state).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in store.state.rglob('*') if p.is_file() and not p.name.startswith(store.db.name)}
        return tables, files

    bounded = review_ingest.bounded
    settled = []

    def finish_competing_import(path, *args, **kwargs):
        raw = bounded(path, *args, **kwargs)
        if not settled and Path(path) == Path(pending_rows[0]['image']):
            review_ingest.import_frames(store, {'path': str(winner), 'classes': str(winner_classes)})
            settled.append(snapshot())
        return raw

    monkeypatch.setattr(review_ingest, 'bounded', finish_competing_import)
    with pytest.raises(ValueError, match='classes differ'):
        review_ingest.import_frames(store, {'path': str(pending), 'classes': str(pending_classes)})
    assert settled
    assert not (store.state / 'pixel' / (rejected_sha + '.yaml')).exists()
    assert snapshot() == settled[0]
