"""D-757 OAuthlib code/PKCE authority with transactional one-use credentials."""
from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
import json
import logging
import re
import secrets
import sqlite3
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from oauthlib.oauth2 import RequestValidator, WebApplicationServer, OAuth2Error
from core_common.protocol.account_access import sign_access, verify_access

NO_STORE = {'Cache-Control': 'no-store', 'Pragma': 'no-cache'}
# OAuthlib's debug messages contain raw grant/refresh credentials.
logging.getLogger('oauthlib').setLevel(logging.WARNING)


def digest(value):
    return sha256(value.encode()).hexdigest()


def _form(body):
    if not isinstance(body, str) or len(body) > 8192:
        raise ValueError('invalid request')
    fields = parse_qs(body, keep_blank_values=True, strict_parsing=True, max_num_fields=12)
    if any(len(values) != 1 for values in fields.values()):
        raise ValueError('duplicate parameters')
    return {key: values[0] for key, values in fields.items()}


def _https(value):
    parsed = urlsplit(value)
    return (parsed.scheme == 'https' and bool(parsed.hostname) and not parsed.username
            and not parsed.password and not parsed.fragment)


class AccountAuthority:
    def __init__(self, path, *, issuer, private_key, key_id, clients,
                 resolve_family, revoke_family, clock=time.time, trusted_public_keys=None):
        from joserfc.jwk import OKPKey
        if not _https(issuer) or urlsplit(issuer).query:
            raise ValueError('invalid account issuer')
        for client, settings in clients.items():
            if (not re.fullmatch(r'[A-Za-z0-9._-]{1,96}', client)
                    or set(settings) != {'redirect_uris', 'resources'}
                    or not settings['redirect_uris'] or not settings['resources']
                    or any(not _https(uri) or urlsplit(uri).query for uri in settings['redirect_uris'])
                    or any(not re.fullmatch(r'(site|robot|project):[A-Za-z0-9._-]{1,96}', resource)
                           for resource in settings['resources'])):
                raise ValueError('invalid account client registration')
        self.path, self.issuer, self.private_key, self.key_id = path, issuer.rstrip('/'), private_key, key_id
        self.clients, self.resolve_family, self.revoke_family = clients, resolve_family, revoke_family
        self.clock = clock
        key = OKPKey.import_key(private_key)
        self.public_keys = dict(trusted_public_keys or {})
        public = key.as_pem(private=False)
        if key_id in self.public_keys and self.public_keys[key_id] != public:
            raise ValueError('signing key id conflicts with trusted key')
        self.public_keys[key_id] = public
        self.jwks = {'keys': [OKPKey.import_key(pem).as_dict(private=False, kid=kid)
                              for kid, pem in self.public_keys.items()]}
        with self.transaction() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS account_oauth_codes (
                    digest TEXT PRIMARY KEY,client TEXT,redirect TEXT,family TEXT,revision INTEGER,
                    resource TEXT,challenge TEXT,expires REAL);
                CREATE TABLE IF NOT EXISTS account_oauth_refresh (
                    digest TEXT PRIMARY KEY,client TEXT,family TEXT,revision INTEGER,
                    resource TEXT,expires REAL,spent INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS account_oauth_access (
                    digest TEXT PRIMARY KEY,client TEXT,family TEXT,revision INTEGER,
                    resource TEXT,expires REAL);
            ''')

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=1)
        db.row_factory = sqlite3.Row
        try:
            with db:
                db.execute('BEGIN IMMEDIATE')
                yield db
        finally:
            db.close()

    @staticmethod
    def error(code='invalid_request', status=400):
        return {**NO_STORE, 'Content-Type': 'application/json'}, json.dumps({'error': code}), status

    def server(self, db):
        for table in ('account_oauth_codes', 'account_oauth_access', 'account_oauth_refresh'):
            db.execute(f'DELETE FROM {table} WHERE expires<=?', (self.clock(),))
        validator = _Validator(self, db)
        return WebApplicationServer(validator, token_generator=validator.access_token,
                                    token_expires_in=300,
                                    refresh_token_generator=lambda request: secrets.token_urlsafe(32))

    def authorization_fields(self, query):
        fields = _form(query)
        if (set(fields) != {'response_type', 'client_id', 'redirect_uri', 'scope', 'state',
                            'code_challenge', 'code_challenge_method'}
                or fields['response_type'] != 'code' or fields['code_challenge_method'] != 'S256'
                or not re.fullmatch(r'[A-Za-z0-9_-]{43}', fields['code_challenge'])
                or not 1 <= len(fields['state']) <= 512):
            raise ValueError('invalid authorization request')
        client = self.clients.get(fields['client_id'])
        if (client is None or fields['redirect_uri'] not in client['redirect_uris']
                or fields['scope'] not in client['resources']):
            raise ValueError('unregistered authorization request')
        return fields

    def authorize(self, query, context):
        try:
            fields = self.authorization_fields(query)
            with self.transaction() as db:
                current = self.resolve_family(db, context['session_family'])
                if (current is None or current['account_id'] != context['account_id']
                        or not any(g['resource'] == fields['scope'] for g in current['grants'])):
                    return self.error('access_denied', 403)
                return self.server(db).create_authorization_response(
                    self.issuer + '/api/fleet/auth/authorize?' + query,
                    scopes=[fields['scope']], credentials={'user': current})
        except (ValueError, KeyError, OAuth2Error):
            return self.error()

    def token(self, body):
        try:
            fields = _form(body)
            allowed = ({'grant_type', 'client_id', 'code', 'redirect_uri', 'code_verifier'}
                       if fields.get('grant_type') == 'authorization_code'
                       else {'grant_type', 'client_id', 'refresh_token'})
            if set(fields) != allowed:
                return self.error()
            if 'code_verifier' in fields and not re.fullmatch(r'[A-Za-z0-9._~-]{43,128}', fields['code_verifier']):
                return self.error()
            with self.transaction() as db:
                # OAuth error tuples still commit: replay-triggered family revocation must survive.
                return self.server(db).create_token_response(self.issuer + '/api/fleet/auth/token',
                    http_method='POST', body=body,
                    headers={'Content-Type': 'application/x-www-form-urlencoded'})
        except (ValueError, OAuth2Error):
            return self.error()

    def introspect(self, token):
        if not isinstance(token, str) or len(token) > 16384:
            return {'active': False}
        with self.transaction() as db:
            row = db.execute('SELECT * FROM account_oauth_access WHERE digest=?', (digest(token),)).fetchone()
            if (row is None or row['expires'] <= self.clock()
                    or row['resource'] not in self.clients.get(row['client'], {}).get('resources', [])):
                return {'active': False}
            context = self.resolve_family(db, row['family'])
            if context is None or context['revision'] != row['revision']:
                return {'active': False}
            try:
                record = verify_access(token, self.public_keys, issuer=self.issuer,
                                       audience=row['resource'], now=self.clock())
            except ValueError:
                return {'active': False}
            return {'active': True, 'sub': record.sub, 'sid': record.sid, 'rev': record.rev,
                    'aud': record.aud, 'exp': record.exp}

    def revoke(self, token):
        if not isinstance(token, str) or len(token) > 16384:
            return
        with self.transaction() as db:
            row = db.execute('SELECT family FROM account_oauth_access WHERE digest=? UNION '
                             'SELECT family FROM account_oauth_refresh WHERE digest=?',
                             (digest(token), digest(token))).fetchone()
            if row:
                self.revoke_family(db, row['family'])


class _Validator(RequestValidator):
    def __init__(self, authority, db):
        self.a, self.db = authority, db

    def validate_client_id(self, client_id, request, *args, **kwargs):
        if client_id not in self.a.clients:
            return False
        request.client = SimpleNamespace(client_id=client_id)
        return True

    authenticate_client_id = validate_client_id

    def client_authentication_required(self, request, *args, **kwargs):
        return False  # Only explicitly registered first-party public clients are supported.

    def validate_redirect_uri(self, client_id, redirect_uri, request, *args, **kwargs):
        return redirect_uri in self.a.clients[client_id]['redirect_uris']

    def get_default_redirect_uri(self, client_id, request, *args, **kwargs):
        return None

    def validate_response_type(self, client_id, response_type, client, request, *args, **kwargs):
        return response_type == 'code'

    def validate_grant_type(self, client_id, grant_type, client, request, *args, **kwargs):
        return grant_type in {'authorization_code', 'refresh_token'}

    def validate_scopes(self, client_id, scopes, client, request, *args, **kwargs):
        return (len(scopes) == 1 and scopes[0] in self.a.clients[client_id]['resources']
                and any(g['resource'] == scopes[0] for g in request.user['grants']))

    def get_default_scopes(self, client_id, request, *args, **kwargs):
        return []

    def is_pkce_required(self, client_id, request):
        return True

    def save_authorization_code(self, client_id, code, request, *args, **kwargs):
        self.db.execute('INSERT INTO account_oauth_codes VALUES(?,?,?,?,?,?,?,?)',
            (digest(code['code']), client_id, request.redirect_uri, request.user['session_family'],
             request.user['revision'], request.scopes[0], request.code_challenge, self.a.clock() + 60))

    def _valid_context(self, row, request):
        if (row is None or row['expires'] <= self.a.clock()
                or row['resource'] not in self.a.clients.get(row['client'], {}).get('resources', [])):
            return False
        context = self.a.resolve_family(self.db, row['family'])
        if context is None or context['revision'] != row['revision']:
            return False
        if not any(g['resource'] == row['resource'] for g in context['grants']):
            return False
        request.user, request.scopes, request.account_grant = context, [row['resource']], row
        return True

    def validate_code(self, client_id, code, client, request, *args, **kwargs):
        row = self.db.execute('SELECT * FROM account_oauth_codes WHERE digest=? AND client=?',
                              (digest(code), client_id)).fetchone()
        return self._valid_context(row, request)

    def get_code_challenge(self, code, request):
        return request.account_grant['challenge']

    def get_code_challenge_method(self, code, request):
        return 'S256'

    def confirm_redirect_uri(self, client_id, code, redirect_uri, client, request, *args, **kwargs):
        return request.account_grant['redirect'] == redirect_uri

    def invalidate_authorization_code(self, client_id, code, request, *args, **kwargs):
        self.db.execute('DELETE FROM account_oauth_codes WHERE digest=? AND client=?', (digest(code), client_id))

    def validate_refresh_token(self, refresh_token, client, request, *args, **kwargs):
        row = self.db.execute('SELECT * FROM account_oauth_refresh WHERE digest=? AND client=?',
                             (digest(refresh_token), client.client_id)).fetchone()
        if row is not None and row['spent']:
            self.a.revoke_family(self.db, row['family'])
            return False
        return self._valid_context(row, request)

    def get_original_scopes(self, refresh_token, request, *args, **kwargs):
        return [request.account_grant['resource']]

    def rotate_refresh_token(self, request):
        return True

    def access_token(self, request):
        context, resource = request.user, request.scopes[0]
        now = int(self.a.clock())
        return sign_access({'iss': self.a.issuer, 'aud': resource, 'sub': context['account_id'],
            'sid': context['session_family'], 'jti': secrets.token_urlsafe(24), 'rev': context['revision'], 'iat': now, 'exp': now + 300,
            'grants': [g for g in context['grants'] if g['resource'] == resource]},
            self.a.private_key, key_id=self.a.key_id)

    def save_bearer_token(self, token, request, *args, **kwargs):
        user, client, resource = request.user, request.client.client_id, request.scopes[0]
        now = self.a.clock()
        if request.grant_type == 'refresh_token':
            self.db.execute('UPDATE account_oauth_refresh SET spent=1 WHERE digest=?',
                            (digest(request.refresh_token),))
        self.db.execute('INSERT INTO account_oauth_refresh VALUES(?,?,?,?,?,?,0)',
            (digest(token['refresh_token']), client, user['session_family'], user['revision'], resource, now + 2592000))
        self.db.execute('INSERT INTO account_oauth_access VALUES(?,?,?,?,?,?)',
            (digest(token['access_token']), client, user['session_family'], user['revision'], resource, now + 300))
