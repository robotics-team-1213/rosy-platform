"""Immutable human review snapshots over registered native collection evidence."""
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

from experiment_io import identifier
from native_cycle import native

PREPARED_FILES = ('intake-receipt.json', 'inspection.json', 'capture.json', 'environment.json', 'decisions.json')
IDENTITY = ('episode_index', 'content_sha256', 'frames', 'session_id', 'cycle_id')
CONTROLS = ('episode_index', 'outcome', 'split', 'object_result', 'reason')
LIMIT = 8 * 1024 * 1024


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                       allow_nan=False) + '\n').encode('utf-8')


def source_revision(prepared_hashes, native_files):
    return hashlib.sha256(canonical({'prepared_files': prepared_hashes, 'native_files': native_files})).hexdigest()


def _bytes(path):
    if (any(part.is_symlink() for part in (path, *path.parents)) or not path.is_file()
            or path.stat().st_size > LIMIT):
        raise ValueError('bounded regular review evidence without links required')
    return path.read_bytes()


def _publish(path, raw):
    if path.exists() or path.is_symlink():
        if _bytes(path) != raw:
            raise ValueError('immutable review snapshot bytes changed')
    else:
        temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
        created = False
        try:
            with temporary.open('xb') as stream:
                created = True
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path, follow_symlinks=False)
            except FileExistsError:
                if _bytes(path) != raw:
                    raise ValueError('immutable review snapshot bytes changed') from None
        finally:
            if created and not temporary.is_symlink():
                temporary.unlink(missing_ok=True)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _text(value, maximum, *, empty=False, multiline=False):
    if (not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip())
            or any(ord(char) < 32 and not (multiline and char in '\n\r\t') for char in value)):
        raise ValueError('bounded explicit reviewer or reason text required')
    return value.strip()


def _decisions(inspection, values, *, reviewer=None):
    episodes = inspection['episodes']
    if not isinstance(values, list) or len(values) != len(episodes):
        raise ValueError('review must cover every episode exactly once')
    result = []
    for episode, value in zip(episodes, values):
        if not isinstance(value, dict) or (reviewer is not None and set(value) != set(CONTROLS)):
            raise ValueError('review decision fields differ from schema')
        if type(value.get('episode_index')) is not int or value['episode_index'] != episode['episode_index']:
            raise ValueError('review episode order differs from current inspection')
        if reviewer is None and any(key in value and value[key] != episode[key] for key in IDENTITY):
            raise ValueError('original review identity differs from current inspection')
        outcome, split = value.get('outcome'), value.get('split')
        effect = value.get('object_result', 'unknown')
        reason = _text(value.get('reason', ''), 1000, empty=True, multiline=True)
        if (outcome not in ('success', 'failure', 'unknown') or split not in ('train', 'eval', 'test', 'exclude')
                or effect not in native.OBJECT_RESULTS):
            raise ValueError('explicit valid review outcome, split and object result required')
        if reviewer is not None and split != 'exclude' and (outcome != 'success' or not reason):
            raise ValueError('included demonstrations require explicit success and nonempty reason')
        identity = {key: episode[key] for key in IDENTITY}
        result.append(dict(identity, outcome=outcome, split=split, object_result=effect, reason=reason,
                           reviewer=reviewer if reviewer is not None else _text(value.get('reviewer', ''), 128, empty=True)))
    return result


class Reviews:
    def __init__(self, root, connect, lock):
        self.root, self.connect, self.lock = Path(root), connect, lock

    def schema(self, db):
        db.execute('CREATE TABLE IF NOT EXISTS native_reviews ('
                   'id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, prepared_id TEXT NOT NULL,'
                   'source_revision TEXT NOT NULL, binding TEXT NOT NULL, document TEXT NOT NULL,'
                   'committed INTEGER NOT NULL DEFAULT 0)')

    def source(self, prepared_row):
        if (not isinstance(prepared_row, dict) or prepared_row.get('kind') != 'omx'
                or not isinstance(prepared_row.get('id'), str)
                or not re.fullmatch('[0-9a-f]{32}', prepared_row['id'])):
            raise ValueError('registered OMX preparation required')
        raw = prepared_row.get('path')
        if not isinstance(raw, str) or len(raw) > 2048 or not Path(raw).is_absolute():
            raise ValueError('registered absolute native preparation required')
        root = Path(raw)
        if (any(part.is_symlink() for part in (root, *root.parents)) or native._in_checkout(root)):
            raise ValueError('native preparation must be outside source checkouts without links')
        root = root.resolve(strict=True)
        originals = {name: _bytes(root / name) for name in PREPARED_FILES}
        intake, inspection = [json.loads(originals[name]) for name in ('intake-receipt.json', 'inspection.json')]
        if (not isinstance(intake, dict) or not isinstance(inspection, dict)
                or intake.get('reader_verified') is not True or inspection.get('reader_verified') is not True):
            raise ValueError('reader-verified native intake and inspection required')
        episodes = inspection.get('episodes')
        if not isinstance(episodes, list) or not 1 <= len(episodes) <= 10000:
            raise ValueError('bounded inspected episodes required')
        for index, episode in enumerate(episodes):
            if (not isinstance(episode, dict) or any(key not in episode for key in IDENTITY)
                    or type(episode['episode_index']) is not int or episode['episode_index'] != index
                    or type(episode['frames']) is not int or episode['frames'] < 1
                    or not isinstance(episode['content_sha256'], str)
                    or not re.fullmatch('[0-9a-f]{64}', episode['content_sha256'])):
                raise ValueError('complete original episode/session/cycle identity required')
            for key in ('session_id', 'cycle_id'):
                _text(episode[key], 256)
        for folder in ('meta', 'data', 'videos'):
            if (root / folder).is_symlink():
                raise ValueError('native source links are not accepted')
            for current, directories, files in os.walk(root / folder, followlinks=False):
                if any((Path(current) / name).is_symlink() for name in (*directories, *files)):
                    raise ValueError('native source links are not accepted')
        files = native.dataset_files(root)
        if files != inspection.get('files'):
            raise ValueError('native source files differ from inspected bytes')
        hashes = {name: hashlib.sha256(raw).hexdigest() for name, raw in originals.items()}
        return dict(root=root, inspection=inspection,
                    decisions=_decisions(inspection, json.loads(originals['decisions.json'])),
                    prepared_files=hashes, native_files=files,
                    source_revision=source_revision(hashes, files),
                    fixture_only=intake.get('fixture_only') is True or inspection.get('fixture_only') is True)

    @staticmethod
    def _trainable(source, decisions):
        if source['fixture_only']:
            return {'ok': False, 'reason': 'fixture-only intake cannot be exported as production training data'}
        try:
            splits = native.reviewed_splits(source['inspection'], decisions)
        except (ValueError, KeyError, TypeError) as exc:
            return {'ok': False, 'reason': str(exc)}
        return {'ok': True, 'counts': {key: len(value) for key, value in splits.items()}}

    def _snapshot(self, document):
        review = document['review']
        folder = self.root / 'reviews' / identifier(review['id'])
        if set(document['files']) != {'decisions.json', 'review.json'}:
            raise ValueError('immutable review file manifest changed')
        for name, digest in document['files'].items():
            if name not in ('decisions.json', 'review.json') or hashlib.sha256(_bytes(folder / name)).hexdigest() != digest:
                raise ValueError('immutable review snapshot bytes changed')
        metadata = json.loads(_bytes(folder / 'review.json'))
        if metadata != review:
            raise ValueError('immutable review metadata changed')
        decisions = json.loads(_bytes(folder / 'decisions.json'))
        if hashlib.sha256(canonical(decisions)).hexdigest() != review['sha256']:
            raise ValueError('immutable review canonical decisions changed')
        return review, decisions

    def describe(self, prepared_row):
        with self.lock:
            source = self.source(prepared_row)
            with self.connect() as db:
                prior = db.execute('SELECT document FROM native_reviews WHERE prepared_id=? '
                                   'AND source_revision=? AND committed=1 ORDER BY rowid DESC LIMIT 1',
                                   (prepared_row['id'], source['source_revision'])).fetchone()
            latest, decisions, reviewer_identity = None, source['decisions'], None
            if prior:
                review, decisions = self._snapshot(json.loads(prior[0]))
                latest = review['id']
                reviewer_identity = review['reviewer_identity']
            report = source['inspection']
            return dict(prepared_id=prepared_row['id'], name=prepared_row.get('name', ''),
                source_revision=source['source_revision'],
                inspection={**{key: report.get(key) for key in ('rig_revision', 'calibration_revision', 'source_mode', 'camera_keys')},
                            'episodes': [{key: row[key] for key in IDENTITY} for row in report['episodes']]},
                decisions=decisions, latest_review_id=latest, reviewer_identity=reviewer_identity,
                trainable=self._trainable(source, decisions), fixture_only=source['fixture_only'])

    def save(self, body, prepared_row, actor=None):
        if (not isinstance(body, dict) or set(body) != {'prepared_id', 'source_revision', 'decisions', 'reviewer', 'confirmed', 'request_id'}
                or body['confirmed'] is not True or body['prepared_id'] != prepared_row.get('id')):
            raise ValueError('confirmed review of registered preparation required')
        request_id = identifier(body['request_id'])
        identity = ({'kind': 'authenticated', 'id': _text(actor.get('user_id'), 128)} if actor is not None
                    else {'kind': 'local_unverified', 'id': _text(body['reviewer'], 128)})
        binding = hashlib.sha256(canonical({'body': body, 'actor': identity})).hexdigest()
        with self.lock:
            source = self.source(prepared_row)
            if body['source_revision'] != source['source_revision']:
                raise ValueError('source revision changed; reload the current preparation')
            decisions = _decisions(source['inspection'], body['decisions'], reviewer=identity['id'])
            decision_bytes = canonical(decisions)
            if len(decision_bytes) > LIMIT:
                raise ValueError('review decisions exceed bounded snapshot size')
            with self.connect() as db:
                prior = db.execute('SELECT id,binding,document,committed FROM native_reviews WHERE request_id=?',
                                   (request_id,)).fetchone()
                if prior and prior[1] != binding:
                    raise ValueError('review request identity was reused with changed body or actor')
                if prior:
                    uid, document = prior[0], json.loads(prior[2])
                else:
                    uid = str(uuid.uuid4())
                    review = dict(schema='rosy.omx.review/1', id=uid, prepared_id=prepared_row['id'],
                        source_revision=source['source_revision'], request_id=request_id,
                        reviewer_identity=identity, sha256=hashlib.sha256(decision_bytes).hexdigest(),
                        prepared_files=source['prepared_files'], native_files=source['native_files'],
                        trainable=self._trainable(source, decisions))
                    document = {'review': review, 'files': {'decisions.json': review['sha256'],
                                'review.json': hashlib.sha256(canonical(review)).hexdigest()}}
                    if len(canonical(review)) > LIMIT:
                        raise ValueError('review metadata exceeds bounded snapshot size')
                    db.execute('INSERT INTO native_reviews VALUES (?,?,?,?,?,?,0)',
                        (uid, request_id, prepared_row['id'], source['source_revision'], binding,
                         canonical(document).decode()))
                    db.commit()  # Reserve identity before file creation so retries recover the same snapshot.
                folder = self.root / 'reviews' / uid
                if any(part.is_symlink() for part in (folder, *folder.parents)):
                    raise ValueError('review snapshot links are not accepted')
                folder.mkdir(parents=True, exist_ok=True)
                for name, raw in [('decisions.json', decision_bytes), ('review.json', canonical(document['review']))]:
                    _publish(folder / name, raw)
                self._snapshot(document)
                if self.source(prepared_row)['source_revision'] != source['source_revision']:
                    raise ValueError('source revision changed while saving human review')
                db.execute('UPDATE native_reviews SET committed=1 WHERE id=?', (uid,))
            view = self.describe(prepared_row)
            return dict(view, saved_review_id=uid)

    def for_export(self, review_id, prepared_row):
        uid = identifier(review_id)
        with self.lock:
            source = self.source(prepared_row)
            with self.connect() as db:
                row = db.execute('SELECT prepared_id,source_revision,document FROM native_reviews '
                                 'WHERE id=? AND committed=1', (uid,)).fetchone()
            if row is None or (row[0], row[1]) != (prepared_row['id'], source['source_revision']):
                raise ValueError('review snapshot does not match current source revision')
            review, decisions = self._snapshot(json.loads(row[2]))
            if not self._trainable(source, decisions)['ok']:
                raise ValueError('review snapshot is not production trainable')
            return {key: review[key] for key in ('id', 'source_revision', 'sha256', 'reviewer_identity')} | {'decisions': decisions}
