"""Immutable workspace learning profiles; setup descriptions confer no device authority."""
from datetime import datetime, timezone
import hashlib
import json
import uuid

from experiment_io import identifier
from experiment_profile import profile_revision, validate_profile


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


class Profiles:
    def __init__(self, connect, lock):
        self.connect, self.lock = connect, lock

    def schema(self, db):
        db.execute('CREATE TABLE IF NOT EXISTS learning_profiles ('
                   'id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL,'
                   'binding TEXT NOT NULL, document TEXT NOT NULL)')

    @staticmethod
    def _record(row):
        if row is None:
            raise ValueError('learning profile does not exist')
        record = json.loads(row[1])
        if (not isinstance(record, dict) or set(record) != {'id', 'revision', 'profile', 'parent_id',
                'created_at', 'created_by', 'physical_setup_verified', 'policy_activation'}
                or record['id'] != row[0] or record['physical_setup_verified'] is not False
                or record['policy_activation'] is not False):
            raise ValueError('immutable learning profile record changed')
        identifier(record['id'])
        if record['parent_id'] is not None:
            identifier(record['parent_id'])
        profile = validate_profile(record['profile'])
        if profile_revision(profile) != record['revision']:
            raise ValueError('stored learning profile revision differs from its content')
        record['profile'] = profile
        return record

    def list(self):
        with self.lock, self.connect() as db:
            return [self._record(row) for row in db.execute(
                'SELECT id,document FROM learning_profiles ORDER BY rowid DESC').fetchall()]

    def get(self, profile_id):
        uid = identifier(profile_id)
        with self.lock, self.connect() as db:
            return self._record(db.execute('SELECT id,document FROM learning_profiles WHERE id=?',
                                           (uid,)).fetchone())

    def resolve(self, profile_id, profile):
        record = self.get(profile_id)
        if validate_profile(profile) != record['profile']:
            raise ValueError('selected learning profile differs from stored profile')
        return record

    def save(self, body, actor=None):
        if (not isinstance(body, dict) or set(body) not in (
                {'profile', 'request_id'}, {'profile', 'request_id', 'parent_id'})):
            raise ValueError('fixed learning profile request fields required')
        encoded = _canonical(body)
        if len(encoded) > 1024 * 1024:
            raise ValueError('bounded learning profile request must not exceed 1 MiB')
        request_id = identifier(body['request_id'])
        parent = body.get('parent_id')
        if parent is not None:
            identifier(parent)
        profile = validate_profile(body['profile'])
        if actor is None:
            creator = {'kind': 'local_unverified', 'id': 'local'}
        else:
            user = actor.get('user_id') if isinstance(actor, dict) else None
            if (not isinstance(user, str) or not 1 <= len(user) <= 128 or user != user.strip()
                    or any(ord(char) < 32 for char in user)):
                raise ValueError('authenticated profile creator identity required')
            creator = {'kind': 'authenticated', 'id': user}
        binding = hashlib.sha256(encoded + b'\n' + _canonical(creator)).hexdigest()
        with self.lock, self.connect() as db:
            prior = db.execute('SELECT id,binding,document FROM learning_profiles WHERE request_id=?',
                               (request_id,)).fetchone()
            if prior:
                if prior[1] != binding:
                    raise ValueError('profile request identity reused with changed body or actor')
                return self._record((prior[0], prior[2]))
            if parent is not None:
                row = db.execute('SELECT id,document FROM learning_profiles WHERE id=?', (parent,)).fetchone()
                if row is None:
                    raise ValueError('parent learning profile does not exist')
                self._record(row)
            uid = str(uuid.uuid4())
            record = dict(id=uid, revision=profile_revision(profile), profile=profile, parent_id=parent,
                created_at=datetime.now(timezone.utc).isoformat(), created_by=creator,
                physical_setup_verified=False, policy_activation=False)
            db.execute('INSERT INTO learning_profiles VALUES (?,?,?,?)',
                       (uid, request_id, binding, _canonical(record).decode('utf-8')))
            return record
