"""D-755 project accounts and encrypted HF connections, independent of Fleet roles.

Provision private files with ``python learning_accounts.py hash-password`` or
``python learning_accounts.py generate-key /private/learning.key``.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
import getpass
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
from urllib.request import Request, build_opener, HTTPRedirectHandler

from cryptography.fernet import Fernet, InvalidToken

CAPABILITIES = {'view', 'edit', 'approve', 'manage', 'import', 'publish'}
REPO_SCOPES = ('read-repos', 'gated-repos', 'write-repos', 'manage-repos')
_PASSWORD_SLOTS = threading.BoundedSemaphore(2)


class AccountError(PermissionError):
    """Safe public reason; credentials and provider response bodies stay private."""


def _digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _password_parts(encoded):
    try:
        scheme, n, r, p, salt, expected = encoded.split('$')
        n, r, p = int(n), int(r), int(p)
        salt, expected = base64.b64decode(salt, validate=True), base64.b64decode(expected, validate=True)
        if scheme != 'scrypt' or (n, r, p) != (32768, 8, 1) or len(salt) != 16 or len(expected) != 32:
            raise ValueError
        return salt, expected
    except (ValueError, TypeError, AttributeError):
        raise AccountError('invalid password hash configuration') from None


def _scrypt(password, salt):
    with _PASSWORD_SLOTS:
        return hashlib.scrypt(password.encode('utf-8'), salt=salt, n=32768, r=8, p=1,
                              maxmem=40 * 1024 * 1024, dklen=32)


def hash_password(password):
    if not isinstance(password, str) or not 12 <= len(password) <= 1024:
        raise AccountError('password must contain 12 to 1024 characters')
    salt = secrets.token_bytes(16)
    return 'scrypt$32768$8$1$' + base64.b64encode(salt).decode() + '$' + base64.b64encode(_scrypt(password, salt)).decode()


def public_principal(principal):
    return {key: value for key, value in principal.items() if not key.startswith('_')}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AccountError('provider redirect refused')


def token_scopes(identity):
    """Map a verified whoami document to repository scopes. Missing proof grants none."""
    auth = identity.get('auth') if isinstance(identity, dict) else None
    access = auth.get('accessToken') if isinstance(auth, dict) else None
    if not isinstance(access, dict):
        return []
    role = access.get('role')
    if role == 'read':
        scopes = ['read-repos']
        if access.get('canReadGatedRepos') is True:
            scopes.append('gated-repos')
        return scopes
    if role == 'write':
        # A classic write token can create and delete repos the user can write.
        return ['read-repos', 'gated-repos', 'write-repos', 'manage-repos']
    if role == 'fineGrained' and isinstance(access.get('scopes'), list):
        return [scope for scope in REPO_SCOPES if scope in access['scopes']]
    return []


def whoami(token):
    request = Request('https://huggingface.co/api/whoami-v2', headers={'Authorization': 'Bearer ' + token})
    try:
        with build_opener(_NoRedirect()).open(request, timeout=15) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError
        return json.loads(raw)
    except Exception:
        raise AccountError('Hugging Face credential could not be verified') from None


class Accounts:
    central_account = False
    def __init__(self, db_path, key_path, config, *, clock=time.time):
        self.db_path, self.key_path = Path(db_path), Path(key_path)
        self.config_path = Path(config) if isinstance(config, (str, Path)) else None
        self._config = config if self.config_path is None else None
        self.clock = clock
        if self.key_path.is_symlink() or self.db_path.is_symlink():
            raise AccountError('account files must not be symlinks')
        try:
            if os.name != 'nt' and self.key_path.stat().st_mode & 0o077:
                raise AccountError('account key requires owner-only permissions')
            self.cipher = Fernet(self.key_path.read_bytes().strip())
        except (OSError, ValueError):
            raise AccountError('account encryption key unavailable') from None
        self.project_id = self.config()['project_id']
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS learning_sessions (
                    id TEXT PRIMARY KEY,user_id TEXT,project_id TEXT,fingerprint TEXT,
                    expires REAL,csrf TEXT,subject TEXT);
                CREATE TABLE IF NOT EXISTS learning_identities (
                    subject TEXT PRIMARY KEY,user_id TEXT,active INTEGER);
                CREATE TABLE IF NOT EXISTS learning_connections (
                    id TEXT PRIMARY KEY,project_id TEXT,owner TEXT,subject TEXT,username TEXT,
                    sharing TEXT,resources TEXT,secret TEXT,generation INTEGER,active INTEGER,expires REAL,
                    scopes TEXT);
                CREATE TABLE IF NOT EXISTS learning_audit (
                    id INTEGER PRIMARY KEY,created REAL,project_id TEXT,user_id TEXT,action TEXT,object_id TEXT);
                CREATE TABLE IF NOT EXISTS learning_login_attempts (key TEXT,created REAL);
                CREATE TABLE IF NOT EXISTS learning_oauth_flows (
                    state TEXT PRIMARY KEY,binding TEXT,session_id TEXT,expires REAL,secret TEXT);
            ''')
            columns = {row[1] for row in db.execute('PRAGMA table_info(learning_connections)')}
            if 'scopes' not in columns:
                db.execute('ALTER TABLE learning_connections ADD COLUMN scopes TEXT')
        if os.name != 'nt':
            self.db_path.chmod(0o600)
        self._dummy = hash_password(secrets.token_urlsafe(24))
        self._legacy_authority()

    def _legacy_authority(self):
        if not self.central_account:
            with self._db() as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='rosy_account_owners'").fetchone():
                    raise AccountError('Rosy Account configuration is required for this project')

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.db_path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def config(self):
        try:
            cfg = json.loads(self.config_path.read_text(encoding='utf-8')) if self.config_path else json.loads(_json(self._config))
            project = cfg['project_id']; users = cfg['users']
            if (not isinstance(project, str) or not project or not isinstance(users, list)
                    or not (users or self.central_account)):
                raise ValueError
            if hasattr(self, 'project_id') and project != self.project_id:
                raise ValueError
            ids, names, subjects = set(), set(), set()
            for user in users:
                uid, username = user['user_id'], user['username']
                if any(not isinstance(v, str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,80}', v) for v in (uid, username)):
                    raise ValueError
                if uid in ids or username in names or 'password' in user:
                    raise ValueError
                ids.add(uid); names.add(username)
                if user.get('password_hash'): _password_parts(user['password_hash'])
                for subject in user.get('hf_subjects', []):
                    if not isinstance(subject, str) or not subject or subject in subjects:
                        raise ValueError
                    subjects.add(subject)
                for project_id, caps in user['memberships'].items():
                    if not isinstance(project_id, str) or not isinstance(caps, list) or not set(caps) <= CAPABILITIES:
                        raise ValueError
            return cfg
        except (OSError, ValueError, TypeError, KeyError):
            raise AccountError('invalid or unavailable account configuration') from None

    def _user(self, user_id):
        user = next((u for u in self.config()['users'] if u['user_id'] == user_id), None)
        if not user or 'view' not in user['memberships'].get(self.project_id, []):
            raise AccountError('project access denied')
        return user

    def _audit(self, db, user_id, action, object_id=''):
        db.execute('INSERT INTO learning_audit(created,project_id,user_id,action,object_id) VALUES(?,?,?,?,?)',
                   (self.clock(), self.project_id, user_id, action, object_id))

    def _session(self, user, subject=None):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self._db() as db:
            db.execute('DELETE FROM learning_sessions WHERE expires<=?', (self.clock(),))
            db.execute('INSERT INTO learning_sessions VALUES(?,?,?,?,?,?,?)',
                       (_digest(token), user['user_id'], self.project_id, _digest(_json(user)), self.clock() + 12 * 3600, csrf, subject))
            self._audit(db, user['user_id'], 'login')
        return token, self.authenticate(token)

    def login(self, username, password, *, address='local'):
        self._legacy_authority()
        if not isinstance(username, str) or not isinstance(password, str) or len(username) > 80 or len(password) > 1024:
            raise AccountError('invalid login')
        # Count attempted checks before scrypt so concurrent failures cannot bypass the bound.
        keys = (_digest('address:' + address), _digest('username:' + username))
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM learning_login_attempts WHERE created<?', (self.clock() - 60,))
            for key in keys:
                if db.execute('SELECT COUNT(*) FROM learning_login_attempts WHERE key=?', (key,)).fetchone()[0] >= 5:
                    raise AccountError('login rate limit; wait one minute')
            db.executemany('INSERT INTO learning_login_attempts VALUES(?,?)', [(key, self.clock()) for key in keys])
        user = next((u for u in self.config()['users'] if u['username'] == username), None)
        salt, expected = _password_parts((user or {}).get('password_hash') or self._dummy)
        matched = hmac.compare_digest(_scrypt(password, salt), expected)
        if not matched or not user or not user.get('password_hash'):
            raise AccountError('invalid login')
        current = self._user(user['user_id'])
        if current != user: raise AccountError('login configuration changed')
        with self._db() as db:
            db.executemany('DELETE FROM learning_login_attempts WHERE key=?', [(key,) for key in keys])
        return self._session(current)

    def authenticate(self, token):
        if not isinstance(token, str) or len(token) > 256: raise AccountError('login required')
        return self._authenticate_id(_digest(token))

    def _authenticate_id(self, session_id):
        self._legacy_authority()
        with self._db() as db:
            row = db.execute('SELECT * FROM learning_sessions WHERE id=?', (session_id,)).fetchone()
        if not row or row['expires'] <= self.clock() or row['project_id'] != self.project_id:
            raise AccountError('login required')
        user = self._user(row['user_id'])
        if not hmac.compare_digest(row['fingerprint'], _digest(_json(user))):
            raise AccountError('account changed; login again')
        if row['subject'] and self._subject_owner(row['subject']) != user['user_id']:
            raise AccountError('login identity revoked')
        return {'user_id': user['user_id'], 'username': user['username'],
                'display_name': user.get('display_name', user['username']), 'project_id': self.project_id,
                'capabilities': list(user['memberships'][self.project_id]), 'csrf_token': row['csrf'], '_session_id': row['id']}

    def require(self, principal, capability):
        if capability not in CAPABILITIES or not isinstance(principal, dict): raise AccountError('access denied')
        current = self._authenticate_id(principal.get('_session_id', ''))
        if current['user_id'] != principal.get('user_id') or capability not in current['capabilities']:
            raise AccountError('capability denied')
        return current

    def authorize(self, principal, project_id, capability):
        if project_id != self.project_id: raise AccountError('project access denied')
        return self.require(principal, capability)

    def logout(self, token):
        with self._db() as db:
            db.execute('DELETE FROM learning_sessions WHERE id=? AND project_id=?', (_digest(token), self.project_id))

    def _subject_owner(self, subject, db=None):
        invited = next((u['user_id'] for u in self.config()['users'] if subject in u.get('hf_subjects', [])), None)
        if db is None:
            with self._db() as connection:
                row = connection.execute('SELECT * FROM learning_identities WHERE subject=?', (subject,)).fetchone()
        else:
            row = db.execute('SELECT * FROM learning_identities WHERE subject=?', (subject,)).fetchone()
        if row:
            if not row['active']: return None
            if invited and invited != row['user_id']: raise AccountError('provider identity conflict')
            return row['user_id']
        return invited

    def login_subject(self, subject):
        self._legacy_authority()
        owner = self._subject_owner(subject)
        if not owner: raise AccountError('Hugging Face account has not been invited')
        return self._session(self._user(owner), subject)

    def _link(self, db, principal, subject):
        if not isinstance(subject, str) or not 1 <= len(subject) <= 256: raise AccountError('invalid provider subject')
        owner = self._subject_owner(subject, db)
        if owner and owner != principal['user_id']: raise AccountError('provider identity already linked')
        # Revoked identities also retain ownership; removal cannot transfer an identity to another person.
        old = db.execute('SELECT user_id FROM learning_identities WHERE subject=?', (subject,)).fetchone()
        if old and old['user_id'] != principal['user_id']: raise AccountError('provider identity already linked')
        db.execute('INSERT INTO learning_identities VALUES(?,?,1) ON CONFLICT(subject) DO UPDATE SET active=1',
                   (subject, principal['user_id']))
        self._audit(db, principal['user_id'], 'identity_link', subject)

    def link_subject(self, principal, subject):
        principal = self.require(principal, 'view')
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            self.require(principal, 'view'); self._link(db, principal, subject)

    def unlink_subject(self, principal, subject):
        principal = self.require(principal, 'view'); user = self._user(principal['user_id'])
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            self.require(principal, 'view')
            if self._subject_owner(subject, db) != principal['user_id']: raise AccountError('identity access denied')
            others = [s for s in user.get('hf_subjects', []) if s != subject and self._subject_owner(s, db) == user['user_id']]
            others += [r[0] for r in db.execute('SELECT subject FROM learning_identities WHERE user_id=? AND active=1 AND subject!=?', (user['user_id'], subject))]
            if not user.get('password_hash') and not others: raise AccountError('cannot remove the last login method')
            db.execute('INSERT INTO learning_identities VALUES(?,?,0) ON CONFLICT(subject) DO UPDATE SET active=0', (subject, user['user_id']))
            db.execute('DELETE FROM learning_sessions WHERE user_id=? AND subject=?', (user['user_id'], subject))
            self._audit(db, user['user_id'], 'identity_unlink', subject)

    def _save_connection(self, db, principal, subject, username, token, *, subject_kind, sharing, resources, expires=None, scopes):
        # whoami IDs and OIDC subjects are different identity namespaces, even when their text matches.
        scopes = sorted(set(scopes))
        if any(scope not in REPO_SCOPES for scope in scopes):
            raise AccountError('invalid connection scope')
        subject = subject_kind + ':' + subject
        row = db.execute('SELECT * FROM learning_connections WHERE project_id=? AND owner=? AND subject=? AND sharing=?',
                         (self.project_id, principal['user_id'], subject, sharing)).fetchone()
        connection_id = row['id'] if row else secrets.token_hex(16)
        generation = row['generation'] + 1 if row else 1
        ciphertext = self.cipher.encrypt(_json({'token': token, 'id': connection_id, 'project': self.project_id,
                                           'owner': principal['user_id'], 'generation': generation}).encode()).decode()
        db.execute('''INSERT OR REPLACE INTO learning_connections
                       (id,project_id,owner,subject,username,sharing,resources,secret,generation,active,expires,scopes)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                   (connection_id, self.project_id, principal['user_id'], subject, username, sharing,
                    _json(resources), ciphertext, generation, 1, expires, _json(scopes)))
        self._audit(db, principal['user_id'], 'connection_link', connection_id)
        return connection_id

    def connect_token(self, principal, token, *, transport=None, sharing='personal', resources=None):
        principal = self.require(principal, 'import')
        if not isinstance(token, str) or not 1 <= len(token) <= 8192 or any(c.isspace() for c in token):
            raise AccountError('invalid credential')
        if sharing not in ('personal', 'project'): raise AccountError('invalid connection sharing')
        resources = resources or []
        if not isinstance(resources, list) or any(not isinstance(r, str) or not re.fullmatch(r'(dataset|model):[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', r) for r in resources):
            raise AccountError('invalid repository allowlist')
        if sharing == 'project':
            self.require(principal, 'manage')
            if not resources: raise AccountError('project connection requires allowed repositories')
        try: identity = (transport or whoami)(token)
        except Exception: raise AccountError('Hugging Face credential could not be verified') from None
        subject, username = identity.get('id'), identity.get('name')
        if identity.get('type') != 'user' or not isinstance(subject, str) or not subject or not isinstance(username, str) or not username:
            raise AccountError('provider user identity unavailable')
        self.require(principal, 'manage' if sharing == 'project' else 'import')
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            self.require(principal, 'manage' if sharing == 'project' else 'import')
            cid = self._save_connection(db, principal, subject, username, token, subject_kind='pat', sharing=sharing,
                                        resources=resources, scopes=token_scopes(identity))
        return next(c for c in self.connections(principal) if c['connection_id'] == cid)

    def connect_oauth(self, principal, subject, username, token, expires, scopes=()):
        principal = self.require(principal, 'import')
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            self.require(principal, 'import'); self._link(db, principal, subject)
            cid = self._save_connection(db, principal, subject, username, token, subject_kind='oidc', sharing='personal',
                                        resources=[], expires=expires, scopes=scopes)
        return next(c for c in self.connections(principal) if c['connection_id'] == cid)

    @staticmethod
    def _stored_scopes(row):
        raw = row['scopes'] if 'scopes' in row.keys() else None
        if not raw:
            return []
        try:
            scopes = json.loads(raw)
        except (TypeError, ValueError):
            return []
        if not isinstance(scopes, list) or any(scope not in REPO_SCOPES for scope in scopes):
            return []
        return scopes

    def _connection_public(self, row):
        kind, separator, subject = row['subject'].partition(':')
        if not separator or kind not in ('pat', 'oidc') or not subject:
            raise AccountError('connection identity namespace unavailable; reconnect')
        return {'connection_id': row['id'], 'provider': 'huggingface', 'owner_id': row['owner'],
                'subject': subject, 'subject_kind': kind, 'username': row['username'], 'sharing': row['sharing'],
                'resources': json.loads(row['resources']), 'scopes': self._stored_scopes(row),
                'generation': row['generation'], 'expires_at': row['expires'], 'active': bool(row['active'])}

    def connections(self, principal):
        principal = self.require(principal, 'view')
        with self._db() as db:
            rows = db.execute("SELECT * FROM learning_connections WHERE project_id=? AND active=1 AND (owner=? OR sharing='project') ORDER BY id",
                              (self.project_id, principal['user_id'])).fetchall()
        return [self._connection_public(row) for row in rows]

    def _owner_capabilities(self, row, principal):
        return self._user(row['owner'])['memberships'][self.project_id]

    def credential(self, principal, connection_id, generation=None, *, resource=None):
        principal = self.require(principal, 'import')
        with self._db() as db:
            row = db.execute('SELECT * FROM learning_connections WHERE id=? AND project_id=?', (connection_id, self.project_id)).fetchone()
        if not row or not row['active'] or (row['sharing'] == 'personal' and row['owner'] != principal['user_id']):
            raise AccountError('connection access denied')
        owner_capabilities = self._owner_capabilities(row, principal)
        if 'import' not in owner_capabilities or (row['sharing'] == 'project' and 'manage' not in owner_capabilities):
            raise AccountError('connection owner permission revoked')
        if generation is not None and generation != row['generation']: raise AccountError('connection generation changed')
        if row['expires'] is not None and row['expires'] <= self.clock(): raise AccountError('connection expired; reconnect')
        if resource is not None and row['sharing'] == 'project' and resource not in json.loads(row['resources']):
            raise AccountError('repository not allowed for project connection')
        try:
            secret = json.loads(self.cipher.decrypt(row['secret'].encode()))
            if any(secret[key] != value for key, value in [('id', row['id']), ('project', self.project_id), ('owner', row['owner']), ('generation', row['generation'])]):
                raise ValueError
        except (InvalidToken, ValueError, KeyError):
            raise AccountError('connection secret unavailable') from None
        return dict(self._connection_public(row), token=secret['token'])

    def management_credential(self, principal, connection_id, *, scope, resource=None):
        """Publish permission plus a recorded repository scope. Import does not imply this."""
        if scope not in ('read-repos', 'write-repos', 'manage-repos'):
            raise AccountError('invalid management scope')
        principal = self.require(principal, 'publish')
        with self._db() as db:
            row = db.execute('SELECT * FROM learning_connections WHERE id=? AND project_id=?', (connection_id, self.project_id)).fetchone()
        if not row or not row['active'] or (row['sharing'] == 'personal' and row['owner'] != principal['user_id']):
            raise AccountError('connection access denied')
        owner_capabilities = self._owner_capabilities(row, principal)
        if 'publish' not in owner_capabilities or (row['sharing'] == 'project' and 'manage' not in owner_capabilities):
            raise AccountError('connection owner permission revoked')
        if row['expires'] is not None and row['expires'] <= self.clock():
            raise AccountError('connection expired; reconnect')
        if scope not in self._stored_scopes(row):
            raise AccountError('connection scope denied')
        if resource is not None and row['sharing'] == 'project' and resource not in json.loads(row['resources']):
            raise AccountError('repository not allowed for project connection')
        try:
            secret = json.loads(self.cipher.decrypt(row['secret'].encode()))
            if any(secret[key] != value for key, value in [('id', row['id']), ('project', self.project_id), ('owner', row['owner']), ('generation', row['generation'])]):
                raise ValueError
        except (InvalidToken, ValueError, KeyError):
            raise AccountError('connection secret unavailable') from None
        return dict(self._connection_public(row), token=secret['token'])

    def audit_publish(self, principal, action, object_id):
        if action not in ('repo_create', 'repo_delete'):
            raise AccountError('invalid audit action')
        principal = self.require(principal, 'publish')
        with self._db() as db:
            self._audit(db, principal['user_id'], action, object_id)

    def assert_connection(self, principal, connection_id, generation):
        self.credential(principal, connection_id, generation)

    def disconnect(self, principal, connection_id):
        principal = self.require(principal, 'view')
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            self.require(principal, 'view')
            row = db.execute('SELECT * FROM learning_connections WHERE id=? AND project_id=?', (connection_id, self.project_id)).fetchone()
            if not row: raise AccountError('connection access denied')
            if row['sharing'] == 'project': self.require(principal, 'manage')
            elif row['owner'] != principal['user_id']: raise AccountError('connection access denied')
            db.execute("UPDATE learning_connections SET active=0,generation=generation+1,secret='' WHERE id=?", (connection_id,))
            self._audit(db, principal['user_id'], 'connection_unlink', connection_id)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['hash-password', 'generate-key'])
    parser.add_argument('path', nargs='?')
    args = parser.parse_args()
    if args.command == 'hash-password':
        entered = getpass.getpass('Password: ')
        if entered != getpass.getpass('Repeat password: '):
            parser.error('passwords do not match')
        print(hash_password(entered))
    else:
        if not args.path: parser.error('key path required')
        fd = os.open(args.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as output: output.write(Fernet.generate_key())
