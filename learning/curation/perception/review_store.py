"""Persistent review records and explicit human decisions; no HTTP server."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path

import class_sets
import review_return
import review_evidence
import review_masks


class Conflict(ValueError):
    """The client must reload rather than overwrite a newer review."""


class ReviewStore:
    uri = None  # set only by read_only(): a SQLite mode=ro connection

    @classmethod
    def read_only(cls, state):
        """Readers outside the app: no mkdir, CREATE, migration or write on open."""
        store = cls.__new__(cls)
        store.state = Path(state)
        store.lock = threading.RLock()
        store.db = store.state / 'reviews.sqlite3'
        store.uri = store.db.as_uri() + '?mode=ro'
        return store

    def __init__(self, state, source=None, human=None, images=None, object_classes=None, *,
                 empty_eval=False, empty_training=False):
        self.state = Path(state).resolve()
        self.state.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = self.state / 'reviews.sqlite3'
        with self.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS frames (
                id INTEGER PRIMARY KEY, source TEXT NOT NULL, review TEXT NOT NULL,
                status TEXT NOT NULL, version INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, ts TEXT DEFAULT CURRENT_TIMESTAMP,
                frame INTEGER, action TEXT, version INTEGER, review TEXT);
                CREATE TABLE IF NOT EXISTS exports (id TEXT PRIMARY KEY, receipt TEXT);
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT);''')
            initialized = db.execute("SELECT value FROM metadata WHERE key='initialized'").fetchone()
            if initialized:
                if empty_eval or empty_training:
                    raise ValueError('existing workspace: reopen with --state only')
                if any(x is not None for x in (source, human, images)):
                    raise ValueError('existing workspace: restart with --state only; imports never overwrite reviews')
                if object_classes is not None and object_classes.get('sha256') != class_sets.object_set(self)['sha256']:
                    raise ValueError('workspace object classes differ; do not reinterpret labels')
                review_masks.configure(self)
                review_evidence.configure(self)
                return
            if empty_eval:
                if any(x is not None for x in (source, human, images)):
                    raise ValueError('empty evaluation workspace has no training inputs')
                if object_classes is not None:
                    class_sets.bind_object_set(self, object_classes, db)
                db.execute("INSERT INTO metadata VALUES ('initialized','true')")
                db.execute("INSERT INTO metadata VALUES ('workspace_kind','evaluation')")
                db.commit()
                review_masks.configure(self)
                review_evidence.configure(self)
                return
            if empty_training:
                if any(x is not None for x in (source, human, images)):
                    raise ValueError('empty training workspace has no initial inputs')
                class_sets.bind_object_set(self, object_classes or class_sets.legacy_object_set(), db)
                db.execute("INSERT INTO metadata VALUES ('initialized','true')")
                db.execute("INSERT INTO metadata VALUES ('workspace_kind','training')")
                db.commit()
                review_masks.configure(self)
                review_evidence.configure(self)
                return
            if source is None or human is None or images is None:
                raise ValueError('first start requires source, human and images')
            # Existing receiver validates hashes, dimensions, boxes and the complete import.
            validation = self.state / ('import-' + uuid.uuid4().hex)
            record = object_classes or class_sets.legacy_object_set()
            classes = tuple(c['name'] for c in record['classes'])
            review_return.receive_review(source, human, images, validation, classes=classes)
            # One transaction: the binding commits or rolls back with the frame rows.
            db.execute('BEGIN IMMEDIATE')
            class_sets.bind_object_set(self, record, db)
            originals = review_return._parse(Path(source).read_bytes())
            reviews = review_return._parse(Path(human).read_bytes())
            for index, row in originals.items():
                review = reviews.get(index, {'index': index, 'image_sha256': row['image_sha256'],
                    'boxes': row.get('objects', row.get('boxes', [])),
                    'review_status': 'pending_human', 'complete_frame_review': False})
                status = ('excluded' if review.get('disposition') == 'excluded_by_user' else
                          'approved' if review['review_status'] == 'approved' and
                          review['complete_frame_review'] is True else 'pending')
                if status == 'excluded':
                    review.update(review_status='pending_human', complete_frame_review=False)
                suffix = Path(row['image']).suffix.lower()
                frozen = validation / 'inputs' / 'images' / f'{index:06d}{suffix}'
                row = dict(row, image=frozen.relative_to(self.state).as_posix())
                self.validate_boxes(row, review['boxes'], classes=classes)
                db.execute('INSERT INTO frames VALUES (?,?,?,?,1)',
                           (index, json.dumps(row), json.dumps(review), status))
                db.execute('INSERT INTO events(frame,action,version,review) VALUES (?,?,?,?)',
                           (index, 'import', 1, json.dumps(review)))
            db.execute("INSERT INTO metadata VALUES ('initialized','true')")
        review_masks.configure(self)
        review_evidence.configure(self)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.uri or self.db, timeout=30, uri=self.uri is not None)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def object_classes(self):
        return tuple(c['name'] for c in class_sets.object_set(self)['classes'])

    @staticmethod
    def validate_boxes(source, boxes, *, classes, approved=False):
        if not isinstance(boxes, list):
            raise ValueError('boxes must be a list')
        for box in boxes:
            review_return.exporter._check_human_box(box)
            allowed = classes + (() if approved else (None,))
            if box.get('label') not in allowed:
                raise ValueError('known object class required')
            x0, y0, x1, y1 = box['bbox_xyxy']
            if not (0 <= x0 < x1 <= source['width'] and 0 <= y0 < y1 <= source['height']):
                raise ValueError('box outside original image')
            if box.get('signal_state', 'unknown') not in ('unknown', 'red', 'yellow', 'green', 'off'):
                raise ValueError('unknown signal state')

    @staticmethod
    def decoded(row):
        return {'index': row['id'], 'source': json.loads(row['source']),
                'review': json.loads(row['review']), 'status': row['status'], 'version': row['version']}

    def get(self, index):
        with self.connect() as db:
            row = db.execute('SELECT * FROM frames WHERE id=?', (index,)).fetchone()
        if row is None:
            raise KeyError(index)
        return self.decoded(row)

    def object_drafts(self, index):
        self.get(index)
        with self.connect() as db:
            return [dict(row, boxes=json.loads(row['boxes'])) for row in db.execute(
                'SELECT sha256,boxes,origin,catalog_sha256 FROM object_drafts '
                'WHERE frame=? ORDER BY rowid DESC', (index,))]

    def list_frames(self):
        with self.connect() as db:
            return [self.decoded(row) for row in db.execute('SELECT * FROM frames ORDER BY id')]

    def history(self, index):
        frame = self.get(index)
        with self.connect() as db:
            events = {}
            for lane, table in (('object', 'events'), ('pixel', 'pixel_events')):
                events[lane] = []
                for row in db.execute(f'SELECT ts,action,version,review FROM {table} '
                                      'WHERE frame=? ORDER BY id DESC LIMIT 20', (index,)):
                    event = dict(row)
                    detail = json.loads(event.pop('review'))
                    actor = detail.get('last_actor') if lane == 'object' else detail.get('actor')
                    if actor:
                        event['actor'] = actor
                    events[lane].append(event)
        return {'source': frame['source'].get('annotation_source'),
                'object_status': frame['status'],
                'pixel_status': review_masks.get(self, index)['status'],
                'events': events}

    def image(self, index):
        row = self.get(index)['source']
        path = (self.state / row['image']).resolve()
        if not path.is_relative_to(self.state):
            raise ValueError('image outside workspace')
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != row['image_sha256']:
            raise ValueError('image hash mismatch')
        return path

    def update(self, index, body, *, actor=None):
        classes = self.object_classes()
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            frame = self.get(index)
            if type(body.get('version')) is not int or body['version'] != frame['version']:
                raise Conflict('다른 탭에서 변경됐습니다. 최신 내용을 다시 불러오세요.')
            action = body.get('action')
            review, status = frame['review'], frame['status']
            if action == 'save':
                if status == 'excluded':
                    raise ValueError('제외 사진은 재검수로 돌린 후 수정하세요.')
                boxes = body.get('boxes')
                self.validate_boxes(frame['source'], boxes, classes=classes)
                review.update(boxes=boxes, review_status='pending_human', complete_frame_review=False,
                              review_origin='pinky_web_edit')
                review.pop('disposition', None)
                status = 'pending'
            elif action == 'approve':
                if status == 'excluded' or body.get('complete_frame_review') is not True:
                    raise ValueError('전체 프레임 확인과 재검수 상태가 필요합니다.')
                self.image(index)
                self.validate_boxes(frame['source'], review['boxes'], classes=classes, approved=True)
                review.update(review_status='approved', complete_frame_review=True,
                              review_origin='pinky_web_explicit_review')
                status = 'approved'
            elif action == 'candidates':
                if status == 'excluded':
                    raise ValueError('제외 사진은 재검수로 돌린 후 초안을 가져오세요.')
                boxes = frame['source'].get('objects', frame['source'].get('boxes', []))
                self.validate_boxes(frame['source'], boxes, classes=classes)
                review.update(boxes=boxes, review_status='pending_human', complete_frame_review=False,
                              review_origin='pinky_web_candidate_import')
                review.pop('disposition', None)
                status = 'pending'
            elif action == 'apply_object_draft':
                if status == 'excluded':
                    raise ValueError('제외 사진은 재검수로 돌린 후 초안을 가져오세요.')
                digest = body.get('draft_sha256')
                if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
                    raise ValueError('object draft SHA required')
                candidate = db.execute('SELECT boxes,origin,catalog_sha256 FROM object_drafts '
                                       'WHERE frame=? AND sha256=?', (index, digest)).fetchone()
                if candidate is None:
                    raise ValueError('selected object draft is unavailable')
                boxes = json.loads(candidate['boxes'])
                self.validate_boxes(frame['source'], boxes, classes=classes)
                review.update(boxes=boxes, review_status='pending_human', complete_frame_review=False,
                              review_origin='model_draft_pending_human', draft_origin=candidate['origin'],
                              draft_sha256=digest, draft_catalog_sha256=candidate['catalog_sha256'])
                review.pop('disposition', None)
                status = 'pending'
            elif action in ('exclude', 'reopen'):
                status = 'excluded' if action == 'exclude' else 'pending'
                review.update(review_status='pending_human', complete_frame_review=False,
                              review_origin='pinky_web_explicit_review')
                if action == 'exclude':
                    review['disposition'] = 'excluded_by_user'
                else:
                    review.pop('disposition', None)
            else:
                raise ValueError('unknown review action')
            review.pop('last_actor', None)
            if actor:
                review['last_actor'] = actor
                if action == 'approve':
                    review['reviewer'] = actor
                elif action == 'save':
                    review['author'] = actor
            version = frame['version'] + 1
            db.execute('UPDATE frames SET review=?,status=?,version=? WHERE id=?',
                       (json.dumps(review), status, version, index))
            db.execute('INSERT INTO events(frame,action,version,review) VALUES (?,?,?,?)',
                       (index, action, version, json.dumps(review)))
            db.execute("UPDATE metadata SET value=CAST(value AS INTEGER)+1 WHERE key='generation'")
        return self.get(index)

    def prepare(self):
        with self.connect() as db:
            kind = db.execute("SELECT value FROM metadata WHERE key='workspace_kind'").fetchone()
        if kind and kind[0] == 'evaluation':
            raise ValueError('evaluation workspace cannot export training reviews')
        with self.lock:
            captured = review_evidence.snapshot(self)
            frames = captured['frames']
            export_id = uuid.uuid4().hex
            inputs = self.state / 'exports' / (export_id + '-inputs')
            inputs.mkdir(parents=True)
            source, human = inputs / 'source.jsonl', inputs / 'human.jsonl'
            source.write_bytes(review_return._jsonl(f['source'] for f in frames))
            # Unclassified candidates are not valid human labels. Keep the complete
            # app snapshot; omit their pending human row from the training receiver.
            unclassified = [f['index'] for f in frames
                            if any(b.get('label') is None for b in f['review']['boxes'])]
            human.write_bytes(review_return._jsonl(review_evidence.human_review(f) for f in frames if f['index'] not in unclassified))
            (inputs / 'application-snapshot.json').write_text(json.dumps(frames, ensure_ascii=False, indent=2), encoding='utf-8')
            out = self.state / 'exports' / export_id
            receipt = review_return.receive_review(source, human, self.state, out, classes=self.object_classes())
            receipt.update(export_id=export_id, path=str(out),
                           frame_versions={str(f['index']): f['version'] for f in frames},
                           excluded_indices=[f['index'] for f in frames if f['status'] == 'excluded'],
                           unclassified_indices=unclassified,
                           segmentation_approved=False,
                           qualification='HOLD: learning owner must establish session mapping, session-disjoint splits and exclude every fixed eval set before training')
            receipt.update(review_contract_schema='rosy.pinky-review-export/2',
                           authority=captured['authority'],
                           current_decisions_required=True)
            (out / 'pinky-review-receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
            contract = review_evidence.seal_export(self, out, receipt, captured)
            receipt['pixel_approved_frames'] = contract['pixel_approved_frames']
            with self.connect() as db:
                db.execute('INSERT INTO exports VALUES (?,?)', (export_id, json.dumps(receipt)))
            return receipt

    def exports(self):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT receipt FROM exports ORDER BY rowid DESC LIMIT 10')]
