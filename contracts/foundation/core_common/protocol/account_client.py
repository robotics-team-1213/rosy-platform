"""D-757 browser receiver: bound PKCE, encrypted credentials, online revocation."""
from base64 import urlsafe_b64encode
from contextlib import contextmanager
from hashlib import sha256
import hmac
import json
from pathlib import Path
import re
import secrets
import sqlite3
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from cryptography.fernet import Fernet, InvalidToken
from core_common.protocol.account_access import verify_access


class AccountDenied(ValueError):
    pass


class AccountUnavailable(Exception):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _digest(value):
    return sha256(value.encode()).hexdigest()


class AccountClient:
    def __init__(self, path, *, issuer, client_id, resource, callback, public_keys,
                 encryption_key, clock=time.time, post=None,
                 destinations=('/pilot', '/dashboard', '/')):
        for url in (issuer, callback):
            parsed = urlsplit(url)
            if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
                    or parsed.password or parsed.query or parsed.fragment):
                raise ValueError('Account URLs must be fixed HTTPS URLs')
        if (not re.fullmatch(r'[A-Za-z0-9._-]{1,96}', client_id)
                or not re.fullmatch(r'(site|robot|project):[A-Za-z0-9._-]{1,96}', resource)
                or not public_keys):
            raise ValueError('Invalid Account client registration')
        self.path, self.issuer = Path(path), issuer.rstrip('/')
        self.client_id, self.resource, self.callback = client_id, resource, callback
        self.public_keys, self.clock = public_keys, clock
        self.cipher, self.post = Fernet(encryption_key), post or self._post
        self.destinations = frozenset(destinations)
        with self.transaction() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS app_account_flows (
                    id TEXT PRIMARY KEY,state TEXT,verifier BLOB,target TEXT,expires REAL);
                CREATE TABLE IF NOT EXISTS app_account_sessions (
                    id TEXT PRIMARY KEY,tokens BLOB,checked REAL,expires REAL);
                CREATE TABLE IF NOT EXISTS app_account_revocations (
                    id TEXT PRIMARY KEY,tokens BLOB);
            ''')

    @contextmanager
    def transaction(self):
        try:
            db = sqlite3.connect(self.path, timeout=10)
            db.row_factory = sqlite3.Row
            try:
                with db:
                    db.execute('BEGIN IMMEDIATE')
                    yield db
            finally:
                db.close()
        except sqlite3.Error:
            raise AccountUnavailable() from None

    def _post(self, endpoint, fields):
        request = Request(self.issuer + '/api/fleet/auth/' + endpoint,
                          data=urlencode(fields).encode(),
                          headers={'Content-Type': 'application/x-www-form-urlencoded',
                                   'Accept': 'application/json'})
        try:
            with build_opener(_NoRedirect()).open(request, timeout=3) as response:
                body = response.read(65537)
                if len(body) > 65536:
                    raise AccountDenied('Oversized Account response')
                result = json.loads(body) if body else {}
                if not isinstance(result, dict):
                    raise AccountDenied('Invalid Account response')
                return result
        except HTTPError as exc:
            if exc.code >= 500:
                raise AccountUnavailable() from None
            raise AccountDenied('Account request refused') from None
        except (URLError, TimeoutError, OSError):
            raise AccountUnavailable() from None
        except (ValueError, UnicodeDecodeError):
            raise AccountDenied('Invalid Account response') from None

    def _claims(self, token):
        return verify_access(token, self.public_keys, issuer=self.issuer,
                             audience=self.resource, now=self.clock())

    def start(self, target):
        if target not in self.destinations:
            raise ValueError('Invalid local return destination')
        cookie, state, verifier = (secrets.token_urlsafe(32) for _ in range(3))
        with self.transaction() as db:
            db.execute('DELETE FROM app_account_flows WHERE expires<=?', (self.clock(),))
            if db.execute('SELECT count(*) FROM app_account_flows').fetchone()[0] >= 1024:
                raise AccountUnavailable()
            db.execute('INSERT INTO app_account_flows VALUES(?,?,?,?,?)',
                       (_digest(cookie), _digest(state), self.cipher.encrypt(verifier.encode()), target, self.clock()+600))
        challenge = urlsafe_b64encode(sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        return cookie, self.issuer + '/api/fleet/auth/authorize?' + urlencode({
            'response_type': 'code', 'client_id': self.client_id, 'redirect_uri': self.callback,
            'scope': self.resource, 'state': state, 'code_challenge': challenge, 'code_challenge_method': 'S256'})

    def finish(self, cookie, state, code):
        if any(not isinstance(v, str) or not 1 <= len(v) <= 512 for v in (cookie, state, code)):
            raise AccountDenied('Invalid callback')
        with self.transaction() as db:
            row = db.execute('SELECT * FROM app_account_flows WHERE id=?', (_digest(cookie),)).fetchone()
            if row is None or row['expires'] <= self.clock() or not hmac.compare_digest(row['state'], _digest(state)):
                raise AccountDenied('Invalid callback')
            # Consume before the network request: a timed-out exchange must start a new flow.
            db.execute('DELETE FROM app_account_flows WHERE id=?', (_digest(cookie),))
        try:
            verifier = self.cipher.decrypt(row['verifier']).decode()
        except InvalidToken:
            raise AccountDenied('Invalid flow encryption key') from None
        tokens = self.post('token', {'grant_type': 'authorization_code', 'client_id': self.client_id,
            'code': code, 'redirect_uri': self.callback, 'code_verifier': verifier})
        self._validate_tokens(tokens)
        self._active(tokens['access_token'])
        session = secrets.token_urlsafe(32)
        with self.transaction() as db:
            db.execute('DELETE FROM app_account_sessions WHERE expires<=?', (self.clock(),))
            db.execute('INSERT INTO app_account_sessions VALUES(?,?,?,?)',
                (_digest(session), self.cipher.encrypt(json.dumps(tokens).encode()), self.clock(), self.clock()+2592000))
        return session, row['target']

    def _validate_tokens(self, tokens):
        if (tokens.get('token_type', '').lower() != 'bearer'
                or not isinstance(tokens.get('refresh_token'), str)
                or not 16 <= len(tokens['refresh_token']) <= 512):
            raise AccountDenied('Invalid token response')
        return self._claims(tokens.get('access_token'))

    def _active(self, token):
        if self.post('introspect', {'token': token}).get('active') is not True:
            raise AccountDenied('Account session revoked')

    def resolve(self, cookie):
        if not isinstance(cookie, str) or not 1 <= len(cookie) <= 128:
            return None
        with self.transaction() as db:
            row = db.execute('SELECT * FROM app_account_sessions WHERE id=?', (_digest(cookie),)).fetchone()
            if row is None:
                return None
            try:
                if row['expires'] <= self.clock():
                    raise AccountDenied('Session expired')
                tokens = json.loads(self.cipher.decrypt(row['tokens']))
                try:
                    claims = self._claims(tokens['access_token'])
                except ValueError:
                    claims = None
                if claims is None or claims.exp - self.clock() < 40:
                    try:
                        renewed = self.post('token', {'grant_type': 'refresh_token', 'client_id': self.client_id,
                                                     'refresh_token': tokens['refresh_token']})
                    except AccountUnavailable:
                        # The authority may have consumed refresh before the connection failed.
                        db.execute('DELETE FROM app_account_sessions WHERE id=?', (row['id'],))
                        return None
                    current = self._validate_tokens(renewed)
                    if claims and (current.sub, current.sid) != (claims.sub, claims.sid):
                        raise AccountDenied('Renewal changed identity')
                    db.execute('UPDATE app_account_sessions SET tokens=?,checked=0 WHERE id=?',
                        (self.cipher.encrypt(json.dumps(renewed).encode()), row['id']))
                    try:
                        self._active(renewed['access_token'])
                        db.execute('UPDATE app_account_sessions SET tokens=?,checked=? WHERE id=?',
                            (self.cipher.encrypt(json.dumps(renewed).encode()), self.clock(), row['id']))
                        return current if current.exp > self.clock() else None
                    except AccountUnavailable:
                        return claims if claims and row['checked'] and claims.exp > self.clock() else None
                if not row['checked'] or self.clock() - row['checked'] >= 20:
                    try:
                        self._active(tokens['access_token'])
                        db.execute('UPDATE app_account_sessions SET checked=? WHERE id=?', (self.clock(), row['id']))
                    except AccountUnavailable:
                        if not row['checked']:
                            return None
                return claims if claims.exp > self.clock() else None
            except (ValueError, InvalidToken, KeyError, TypeError):
                db.execute('DELETE FROM app_account_sessions WHERE id=?', (row['id'],))
                return None

    def logout(self, cookie):
        if not isinstance(cookie, str) or len(cookie) > 128:
            return
        with self.transaction() as db:
            row = db.execute('SELECT tokens FROM app_account_sessions WHERE id=?', (_digest(cookie),)).fetchone()
            if row:
                db.execute('INSERT OR REPLACE INTO app_account_revocations VALUES(?,?)', (_digest(cookie), row['tokens']))
            db.execute('DELETE FROM app_account_sessions WHERE id=?', (_digest(cookie),))
        self.retry_revocations()

    def retry_revocations(self):
        with self.transaction() as db:
            rows = db.execute('SELECT * FROM app_account_revocations LIMIT 16').fetchall()
        for row in rows:
            try:
                tokens = json.loads(self.cipher.decrypt(row['tokens']))
                self.post('revoke', {'token': tokens['refresh_token']})
            except (InvalidToken, ValueError, KeyError):
                raise AccountDenied('Invalid local session') from None
            with self.transaction() as db:
                db.execute('DELETE FROM app_account_revocations WHERE id=?', (row['id'],))
