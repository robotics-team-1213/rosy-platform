"""Camera-only durable relationships; Fleet SQLite owns credential binding and replay fencing."""
from contextlib import closing
import math
import re
import secrets
import time

from core_common.protocol.device_kind import OVERHEAD_CAMERA
from .enrollment_store import append_device_pairing_audit
from .camera_peer_crypto import fingerprint, ProofDenied


class CameraPeerDenied(ValueError):
    """No camera authority or credential was issued."""


class CameraPeerStore:
    MAX_RELATIONSHIPS = 128
    MAX_CHALLENGES = 64
    CREDENTIAL_LIFETIME = 180 * 86400.
    ISSUER_FIELDS = frozenset({'principal_id', 'role', 'token_sha256', 'source'})

    def __init__(self, legacy, *, current_issuers, paired_sources, clock=time.time,
                 credential_lifetime_s=CREDENTIAL_LIFETIME):
        if not math.isfinite(credential_lifetime_s) or not 0 < credential_lifetime_s <= self.CREDENTIAL_LIFETIME:
            raise CameraPeerDenied('camera credential lifetime exceeds existing cap')
        self.credential_lifetime_s = credential_lifetime_s
        self.legacy = legacy
        self.current_issuers = current_issuers
        self.paired_sources = paired_sources
        self.clock = clock
        with closing(legacy._connect()) as connection, connection:
            columns = {row[1] for row in connection.execute('PRAGMA table_info(device_credentials)')}
            for column, kind in [('peer_relationship_id', 'TEXT'), ('peer_generation', 'INTEGER')]:
                if column not in columns:
                    connection.execute(f'ALTER TABLE device_credentials ADD COLUMN {column} {kind}')
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS camera_peer_relationships (
                    relationship_id TEXT PRIMARY KEY, source_id TEXT NOT NULL,
                    client_key TEXT NOT NULL, receiver_key TEXT NOT NULL, label TEXT NOT NULL,
                    client_id TEXT NOT NULL,
                    principal_id TEXT NOT NULL, issuer_digest TEXT NOT NULL,
                    generation INTEGER NOT NULL, expires_at REAL, state TEXT NOT NULL,
                    created_at REAL NOT NULL, request_secret_sha256 TEXT,
                    display_code TEXT, request_expires_at TEXT);
                CREATE UNIQUE INDEX IF NOT EXISTS camera_peer_source_owned
                    ON camera_peer_relationships(source_id) WHERE state='approved';
                CREATE TABLE IF NOT EXISTS camera_peer_challenges (
                    nonce TEXT PRIMARY KEY, relationship_id TEXT NOT NULL,
                    generation INTEGER NOT NULL, expires_at REAL NOT NULL);
            ''')

    def _issuer(self, issuer):
        if (not isinstance(issuer, dict) or set(issuer) != self.ISSUER_FIELDS
                or issuer.get('role') != 'operator' or issuer.get('source') != 'site-users'
                or not isinstance(issuer.get('principal_id'), str) or not issuer['principal_id']
                or not re.fullmatch('[0-9a-f]{64}', str(issuer.get('token_sha256')))):
            raise CameraPeerDenied('configured named operator required')
        current = tuple(self.current_issuers())
        if not any(set(row) == self.ISSUER_FIELDS and row == issuer for row in current):
            raise CameraPeerDenied('issuer withdrawn or metadata changed')

    def _usable(self, row):
        if row is None or row['state'] != 'approved' or row['source_id'] not in self.paired_sources():
            raise CameraPeerDenied('relationship unavailable')
        expiry = row['expires_at']
        if expiry is not None and (not isinstance(expiry,(int,float)) or not math.isfinite(expiry) or expiry <= self.clock()):
            raise CameraPeerDenied('relationship expired')
        if not isinstance(row['generation'], int) or row['generation'] < 0:
            raise CameraPeerDenied('invalid relationship generation')
        try:
            fingerprint(row['client_key'])
        except ProofDenied:
            raise CameraPeerDenied('stored camera key invalid') from None
        if not re.fullmatch('[0-9a-f]{64}',str(row['receiver_key'])):
            raise CameraPeerDenied('stored receiver key invalid')
        self._issuer({'principal_id': row['principal_id'], 'role': 'operator',
                      'token_sha256': row['issuer_digest'], 'source': 'site-users'})
        return row

    @staticmethod
    def _get(connection, relationship_id):
        return connection.execute('SELECT * FROM camera_peer_relationships WHERE relationship_id=?',
                                  (relationship_id,)).fetchone()

    def _audit(self, connection, action, principal_id, relationship_id):
        append_device_pairing_audit(connection, at=self.clock(), device_kind=OVERHEAD_CAMERA,
                                    action=action, outcome='accepted', principal_id=principal_id,
                                    target=relationship_id, limit=self.legacy._audit_limit)

    def approve(self, *, relationship_id, source_id, client_key, receiver_key, label, client_id='camera',
                issuer, persist_requested, request_secret_sha256=None, display_code=None,
                request_expires_at=None):
        if type(persist_requested) is not bool:
            raise CameraPeerDenied('explicit remember decision required')
        self._issuer(issuer)
        if source_id not in self.paired_sources():
            raise CameraPeerDenied('paired source required')
        with closing(self.legacy._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            self._issuer(issuer)
            if connection.execute('SELECT COUNT(*) FROM camera_peer_relationships').fetchone()[0] >= self.MAX_RELATIONSHIPS:
                raise CameraPeerDenied('relationship capacity reached')
            occupied = connection.execute(
                "SELECT 1 FROM camera_peer_relationships WHERE source_id=? AND state='approved'",
                (source_id,)).fetchone()
            legacy = connection.execute(
                "SELECT 1 FROM device_credentials WHERE source_id=? AND device_kind=? "
                "AND state IN ('active','pending_confirm') AND expires_at>?",
                (source_id, OVERHEAD_CAMERA, self.clock())).fetchone()
            if occupied or legacy:
                raise CameraPeerDenied('source already owned')
            expiry = None if persist_requested else self.clock() + self.credential_lifetime_s
            connection.execute('INSERT INTO camera_peer_relationships VALUES (?,?,?,?,?,?,?,?,0,?,?,?,?,?,?)',
                               (relationship_id, source_id, client_key, receiver_key, label,
                                client_id, issuer['principal_id'], issuer['token_sha256'], expiry, 'approved', self.clock(),
                                request_secret_sha256, display_code, request_expires_at))
            self._audit(connection, 'camera-peer-approved', issuer['principal_id'], relationship_id)

    def relationship(self, relationship_id):
        with closing(self.legacy._connect()) as connection:
            row = self._get(connection, relationship_id)
            if row is None:
                raise CameraPeerDenied('unknown relationship')
            output = dict(row)
            try:
                self._usable(row)
                output['authorization_available'] = True
            except CameraPeerDenied:
                output['authorization_available'] = False
            return output

    def put_challenge(self, relationship_id, nonce, *, expected_generation):
        with closing(self.legacy._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            row = self._usable(self._get(connection, relationship_id))
            if type(expected_generation) is not int or row['generation'] != expected_generation:
                raise CameraPeerDenied('relationship generation changed')
            connection.execute('DELETE FROM camera_peer_challenges WHERE expires_at<=?', (self.clock(),))
            if connection.execute('SELECT COUNT(*) FROM camera_peer_challenges').fetchone()[0] >= self.MAX_CHALLENGES:
                raise CameraPeerDenied('challenge capacity reached')
            connection.execute('INSERT INTO camera_peer_challenges VALUES (?,?,?,?)',
                               (nonce, relationship_id, row['generation'], self.clock() + 60.))

    def issue(self, relationship_id, nonce, token_sha256, *, expected_binding=None):
        if not re.fullmatch('[0-9a-f]{64}', token_sha256):
            raise CameraPeerDenied('invalid credential digest')
        with closing(self.legacy._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            row = self._usable(self._get(connection, relationship_id))
            if expected_binding is not None and any(row[name] != value for name,value in expected_binding.items()):
                raise CameraPeerDenied('relationship changed during proof verification')
            challenge = connection.execute('SELECT * FROM camera_peer_challenges WHERE nonce=?', (nonce,)).fetchone()
            if (challenge is None or challenge['relationship_id'] != relationship_id
                    or challenge['generation'] != row['generation'] or challenge['expires_at'] <= self.clock()):
                raise CameraPeerDenied('challenge expired or replayed')
            connection.execute('DELETE FROM camera_peer_challenges WHERE nonce=?', (nonce,))
            # A renewed credential replaces only this relationship's children.
            connection.execute("UPDATE device_credentials SET state='revoked', revoked_at=?, "
                               "revoke_reason='camera-peer-renewed' WHERE peer_relationship_id=? AND state!='revoked'",
                               (self.clock(), relationship_id))
            expiry = self.clock() + self.credential_lifetime_s
            if row['expires_at'] is not None:
                expiry = min(expiry, row['expires_at'])
            credential_id = 'cam-peer-' + secrets.token_urlsafe(18)
            connection.execute(
                "INSERT INTO device_credentials(credential_id,device_kind,source_id,token_sha256,state,device_label,"
                "principal_id,created_at,confirmed_at,expires_at,peer_relationship_id,peer_generation) "
                "VALUES (?,?,?,?,'active',?,?,?,?,?,?,?)",
                (credential_id, OVERHEAD_CAMERA, row['source_id'], token_sha256, row['label'], row['principal_id'],
                 self.clock(), self.clock(), expiry, relationship_id, row['generation']))
            connection.execute('DELETE FROM device_credentials WHERE peer_relationship_id=? '
                               'AND rowid NOT IN (SELECT rowid FROM device_credentials '
                               'WHERE peer_relationship_id=? ORDER BY rowid DESC LIMIT 4)',
                               (relationship_id, relationship_id))
            self._audit(connection, 'camera-peer-credential-issued', row['principal_id'], relationship_id)
            return {'credential_id': credential_id, 'expires_at': expiry, 'source_id': row['source_id']}

    def allowed_credential(self, credential):
        if credential is None or credential['state'] != 'active' or credential['expires_at'] <= self.clock():
            return False
        binding = credential.get('peer_relationship_id')
        generation = credential.get('peer_generation')
        if binding is None and generation is None and not credential['credential_id'].startswith('cam-peer-'):
            return True
        if not isinstance(binding, str) or type(generation) is not int:
            return False
        try:
            row = self.relationship(binding)
            return (row['authorization_available'] and row['generation'] == generation
                    and row['source_id'] == credential['source_id']
                    and credential['device_kind'] == OVERHEAD_CAMERA)
        except (CameraPeerDenied, TypeError, ValueError):
            return False

    def revoke(self, relationship_id, *, actor):
        self._issuer(actor)
        with closing(self.legacy._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            self._issuer(actor)
            row = self._get(connection, relationship_id)
            if row is None:
                raise CameraPeerDenied('unknown relationship')
            connection.execute("UPDATE camera_peer_relationships SET state='revoked', generation=generation+1 "
                               "WHERE relationship_id=?", (relationship_id,))
            connection.execute('DELETE FROM camera_peer_challenges WHERE relationship_id=?', (relationship_id,))
            connection.execute("UPDATE device_credentials SET state='revoked', revoked_at=?, revoked_by=?, "
                               "revoke_reason='camera-peer-revoked' WHERE peer_relationship_id=?",
                               (self.clock(), actor['principal_id'], relationship_id))
            self._audit(connection, 'camera-peer-revoked', actor['principal_id'], relationship_id)

    def source_owned(self, source_id):
        with closing(self.legacy._connect()) as connection:
            return connection.execute("SELECT 1 FROM camera_peer_relationships WHERE source_id=? "
                                      "AND state='approved'", (source_id,)).fetchone() is not None
