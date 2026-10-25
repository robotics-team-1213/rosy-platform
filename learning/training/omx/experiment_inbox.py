"""Durable registered experience inputs for one owned continuous learner."""
import json

import numpy as np

from experiment_dataset import load_dataset
from experiment_io import identifier, read_json, write_json
from experiment_profile import action_bounds, profile_revision
from experiment_scope import select_dataset


def check_action_space(dataset):
    bounds = np.asarray(action_bounds(dataset.profile), dtype=np.float32)
    for episode in dataset.split('train'):
        values = episode.arrays['action']
        if np.any(values < bounds[:, 0]) or np.any(values > bounds[:, 1]):
            raise ValueError('experience action outside declared action range')


class Inbox:
    def __init__(self, root):
        self.root = root

    @staticmethod
    def schema(db):
        db.execute('CREATE TABLE IF NOT EXISTS inputs (id TEXT PRIMARY KEY, run_id TEXT NOT NULL,'
                   ' dataset_id TEXT NOT NULL, sequence INTEGER NOT NULL, document TEXT NOT NULL,'
                   ' UNIQUE(run_id,sequence), UNIQUE(run_id,dataset_id))')

    def materialize(self, db, row):
        if row.get('execution_mode') != 'online_experience':
            return
        folder = self.root / 'runs' / row['id'] / 'inbox'
        folder.mkdir(exist_ok=True)
        for raw, in db.execute('SELECT document FROM inputs WHERE run_id=? ORDER BY sequence', (row['id'],)):
            item = json.loads(raw)
            descriptor = {'id': item['id'], 'dataset_root': str(self.root / 'datasets' / item['dataset_id']),
                          'dataset_revision': item['dataset_revision']}
            file = folder / f"{item['sequence']:06}.json"
            if file.exists() or file.is_symlink():
                if read_json(file) != descriptor:
                    raise ValueError('owned immutable experience descriptor changed')
            else:
                write_json(file, descriptor)

    def decorate(self, db, row):
        if row.get('execution_mode') != 'online_experience':
            return row
        progress = row.get('progress', {})
        consumed = {entry.get('id') if isinstance(entry, dict) else entry
                    for entry in progress.get('consumed_inputs', [])}
        errors = progress.get('input_errors', [])
        entries = []
        for raw, in db.execute('SELECT document FROM inputs WHERE run_id=? ORDER BY sequence', (row['id'],)):
            item = json.loads(raw)
            error = next((e for e in errors if e.get('id') == item['id']
                          or e.get('sequence') == f"{item['sequence']:06}.json"), None)
            item['status'] = 'consumed' if item['id'] in consumed else 'rejected' if error else 'queued'
            if error:
                item['error'] = error.get('reason', error.get('error'))
            entries.append(item)
        return dict(row, inputs=entries)

    def add(self, db, body):
        if set(body) != {'id', 'dataset_id', 'request_id'}:
            raise ValueError('experience accepts registered dataset and run identities only')
        rid, did, request_id = (identifier(body[key]) for key in ('id', 'dataset_id', 'request_id'))
        old = db.execute('SELECT run_id,dataset_id,document FROM inputs WHERE id=?', (request_id,)).fetchone()
        if old:
            if (old[0], old[1]) != (rid, did):
                raise ValueError('experience request already used with different inputs')
            return json.loads(old[2])
        found = db.execute('SELECT document FROM runs WHERE id=?', (rid,)).fetchone()
        row = json.loads(found[0]) if found else {}
        if row.get('execution_mode') != 'online_experience' or row.get('status') != 'running':
            raise ValueError('active continuous learning run required')
        initial = db.execute('SELECT document FROM datasets WHERE id=?', (row['dataset_id'],)).fetchone()
        source = db.execute('SELECT document FROM datasets WHERE id=?', (did,)).fetchone()
        if not source or not initial:
            raise ValueError('unknown registered dataset')
        initial, source = json.loads(initial[0]), json.loads(source[0])
        if (did == row['dataset_id'] or source['revision'] == initial['revision']
                or db.execute('SELECT 1 FROM inputs WHERE run_id=? AND dataset_id=?', (rid, did)).fetchone()):
            raise ValueError('experience dataset already submitted')
        previous = [json.loads(raw) for raw, in db.execute('SELECT document FROM inputs WHERE run_id=?', (rid,))]
        if any(p['dataset_revision'] == source['revision'] for p in previous):
            raise ValueError('experience revision already submitted')
        if len(previous) >= 127:
            raise ValueError('continuous learner input capacity reached')
        if profile_revision(source['profile']) != profile_revision(initial['profile']):
            raise ValueError('experience profile differs from initial learning profile')
        dataset = load_dataset(self.root / 'datasets' / did, method='hilserl')
        if dataset.revision != source['revision']:
            raise ValueError('registered experience dataset changed')
        select_dataset(dataset, row.get('arm_id'), method='hilserl')
        check_action_space(dataset)
        sequence = len(previous) + 1
        item = dict(id=request_id, dataset_id=did, sequence=sequence,
                    dataset_revision=dataset.revision, status='queued')
        db.execute('INSERT INTO inputs VALUES (?,?,?,?,?)', (request_id, rid, did, sequence, json.dumps(item)))
        db.commit()
        self.materialize(db, row)
        return item
