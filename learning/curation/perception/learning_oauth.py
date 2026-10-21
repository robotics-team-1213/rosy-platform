"""Fixed-endpoint Hugging Face OIDC with PKCE and browser-bound one-time state."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
from pathlib import Path
import secrets
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener

from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes

from learning_accounts import AccountError, _NoRedirect, _digest, _json

ISSUER = 'https://huggingface.co'
AUTHORIZE = ISSUER + '/oauth/authorize'
TOKEN = ISSUER + '/oauth/token'
USERINFO = ISSUER + '/oauth/userinfo'
JWKS = ISSUER + '/oauth/jwks'


def _b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')


def _unb64(value):
    return base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)


def request_json(method, url, *, data=None, headers=None):
    if url not in (TOKEN, USERINFO, JWKS): raise AccountError('provider endpoint refused')
    headers = dict(headers or {})
    if data is not None: headers['Content-Type'] = 'application/x-www-form-urlencoded'
    request = Request(url, data=urlencode(data).encode() if data is not None else None, headers=headers, method=method)
    try:
        with build_opener(_NoRedirect()).open(request, timeout=15) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024: raise ValueError
        document = json.loads(raw)
        if not isinstance(document, dict): raise ValueError
        return document
    except Exception:
        raise AccountError('Hugging Face authorization request failed') from None


class OAuth:
    def __init__(self, accounts, *, transport=None):
        self.accounts = accounts
        self.transport = transport or request_json

    def validate_origin(self, origin):
        cfg = self._config()
        if not origin or cfg['redirect_uri'] != origin + '/oauth/huggingface/callback':
            raise AccountError('OAuth callback must match public_origin + /oauth/huggingface/callback')

    def _config(self):
        cfg = self.accounts.config().get('oauth', {})
        uri = cfg.get('redirect_uri', '')
        parsed = urlsplit(uri)
        if (not isinstance(cfg.get('client_id'), str) or not cfg['client_id'] or
                parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or parsed.query):
            raise AccountError('Hugging Face OAuth requires a registered HTTPS callback and client ID')
        return cfg

    def begin(self, purpose, *, session=None):
        cfg = self._config()
        requested = {'link': 'openid profile read-repos gated-repos',
                     'manage': 'openid profile read-repos write-repos manage-repos'}
        if purpose not in requested:
            raise AccountError('invalid authorization purpose')
        if purpose == 'link':
            principal = self.accounts.require(self.accounts.authenticate(session), 'import')
        elif purpose == 'manage':
            # Storing the credential still requires import. Publish alone cannot keep a token.
            principal = self.accounts.require(self.accounts.authenticate(session), 'publish')
            self.accounts.require(principal, 'import')
        state, binding, nonce, verifier = [secrets.token_urlsafe(32) for _ in range(4)]
        pending = {'purpose': purpose, 'nonce': nonce, 'verifier': verifier, 'config': _digest(_json(cfg)),
                   'project_id': self.accounts.project_id}
        with self.accounts._db() as db:
            db.execute('DELETE FROM learning_oauth_flows WHERE expires<=?', (self.accounts.clock(),))
            db.execute('INSERT INTO learning_oauth_flows VALUES(?,?,?,?,?)',
                       (_digest(state), _digest(binding), principal['_session_id'],
                        self.accounts.clock() + 600, self.accounts.cipher.encrypt(_json(pending).encode()).decode()))
        query = {'response_type': 'code', 'client_id': cfg['client_id'], 'redirect_uri': cfg['redirect_uri'],
                 'scope': requested[purpose], 'state': state, 'nonce': nonce, 'code_challenge_method': 'S256',
                 'code_challenge': _b64(hashlib.sha256(verifier.encode()).digest())}
        # Explicit account selection avoids silently linking whichever HF account was last used.
        query['prompt'] = 'select_account'
        return AUTHORIZE + '?' + urlencode(query), binding

    def _consume(self, query, binding, session):
        if not isinstance(query, dict) or not isinstance(binding, str): raise AccountError('invalid OAuth callback')
        state, code = query.get('state'), query.get('code')
        if not isinstance(state, str) or not 1 <= len(state) <= 256 or not isinstance(code, str) or not 1 <= len(code) <= 8192 or query.get('error'):
            raise AccountError('authorization was not completed')
        with self.accounts._db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM learning_oauth_flows WHERE state=?', (_digest(state),)).fetchone()
            if not row or row['expires'] <= self.accounts.clock() or not hmac.compare_digest(row['binding'], _digest(binding)):
                raise AccountError('OAuth state expired or browser binding mismatch')
            if row['session_id'] is not None and (not isinstance(session, str) or not hmac.compare_digest(row['session_id'], _digest(session))):
                raise AccountError('OAuth linking session mismatch')
            pending = json.loads(self.accounts.cipher.decrypt(row['secret'].encode()))
            if pending['project_id'] != self.accounts.project_id: raise AccountError('OAuth project mismatch')
            db.execute('DELETE FROM learning_oauth_flows WHERE state=?', (_digest(state),))
        return pending

    def _claims(self, token, cfg, nonce):
        try:
            if not isinstance(token, str) or len(token) > 32768: raise ValueError
            header64, payload64, signature64 = token.split('.')
            header, claims = json.loads(_unb64(header64)), json.loads(_unb64(payload64))
            if header.get('alg') != 'RS256' or not isinstance(header.get('kid'), str) or header.get('crit'):
                raise ValueError
            # Never follow jku/x5u supplied by an untrusted token.
            keys = self.transport('GET', JWKS)['keys']
            candidates = [key for key in keys if key.get('kid') == header['kid'] and key.get('kty') == 'RSA'
                          and key.get('alg', 'RS256') == 'RS256' and key.get('use', 'sig') == 'sig']
            if len(candidates) != 1: raise ValueError
            key = candidates[0]
            n, e = int.from_bytes(_unb64(key['n']), 'big'), int.from_bytes(_unb64(key['e']), 'big')
            if not 2048 <= n.bit_length() <= 8192 or e != 65537: raise ValueError
            rsa.RSAPublicNumbers(e, n).public_key().verify(_unb64(signature64), (header64 + '.' + payload64).encode(), padding.PKCS1v15(), hashes.SHA256())
            now = self.accounts.clock()
            if claims.get('iss') != ISSUER or not isinstance(claims.get('sub'), str) or not 1 <= len(claims['sub']) <= 256:
                raise ValueError
            audience = claims.get('aud')
            if isinstance(audience, str): audience = [audience]
            if not isinstance(audience, list) or cfg['client_id'] not in audience:
                raise ValueError
            if (len(audience) > 1 or 'azp' in claims) and claims.get('azp') != cfg['client_id']: raise ValueError
            for field in ('exp', 'iat'):
                if type(claims.get(field)) not in (float, int) or not math.isfinite(claims[field]): raise ValueError
            if claims['exp'] <= now or claims['iat'] > now + 60 or claims['iat'] < now - 660: raise ValueError
            if 'nbf' in claims and (type(claims['nbf']) not in (int, float) or not math.isfinite(claims['nbf']) or claims['nbf'] > now + 60): raise ValueError
            if not isinstance(claims.get('nonce'), str) or not hmac.compare_digest(claims['nonce'], nonce): raise ValueError
            return claims
        except Exception:
            raise AccountError('Hugging Face identity token validation failed') from None

    def complete(self, query, binding, *, session=None):
        cfg = self._config(); pending = self._consume(query, binding, session)
        if not hmac.compare_digest(pending['config'], _digest(_json(cfg))): raise AccountError('OAuth configuration changed')
        if pending['purpose'] not in ('link', 'manage'):
            raise AccountError('invalid authorization purpose')
        principal = self.accounts.authenticate(session)
        data = {'grant_type': 'authorization_code', 'code': query['code'], 'client_id': cfg['client_id'],
                'redirect_uri': cfg['redirect_uri'], 'code_verifier': pending['verifier']}
        headers = {}
        if cfg.get('client_secret_file'):
            try: client_material = Path(cfg['client_secret_file']).read_text(encoding='utf-8').strip()
            except OSError: raise AccountError('OAuth client secret unavailable') from None
            if not client_material: raise AccountError('OAuth client secret unavailable')
            headers['Authorization'] = 'Basic ' + base64.b64encode((cfg['client_id'] + ':' + client_material).encode()).decode()
        try:
            response = self.transport('POST', TOKEN, data=data, headers=headers)
            token = response['access_token']
            if not isinstance(token, str) or not 1 <= len(token) <= 8192 or any(c.isspace() for c in token) or response.get('token_type', '').lower() != 'bearer':
                raise ValueError
        except Exception:
            raise AccountError('Hugging Face authorization exchange failed') from None
        claims = self._claims(response.get('id_token'), cfg, pending['nonce'])
        if claims.get('at_hash') and not hmac.compare_digest(claims['at_hash'], _b64(hashlib.sha256(token.encode()).digest()[:16])):
            raise AccountError('Hugging Face access token binding failed')
        try: profile = self.transport('GET', USERINFO, headers={'Authorization': 'Bearer ' + token})
        except Exception: raise AccountError('Hugging Face profile verification failed') from None
        if profile.get('sub') != claims['sub']: raise AccountError('Hugging Face profile identity mismatch')
        granted = set(str(response.get('scope', '')).split())
        allowed = {'link': ('read-repos', 'gated-repos'),
                   'manage': ('read-repos', 'write-repos', 'manage-repos')}[pending['purpose']]
        # Keep only scopes this purpose requested. A read link cannot store write.
        scopes = [scope for scope in allowed if scope in granted]
        if pending['purpose'] == 'link' and 'read-repos' not in scopes:
            raise AccountError('repository read permission was not granted')
        if pending['purpose'] == 'manage' and not {'write-repos', 'manage-repos'} <= set(scopes):
            raise AccountError('repository management permission was not granted')
        expires = response.get('expires_in')
        if type(expires) not in (int, float) or not math.isfinite(expires) or not 0 < expires <= 366 * 86400:
            raise AccountError('provider credential expiry unavailable')
        username = profile.get('preferred_username') or profile.get('name')
        if not isinstance(username, str) or not username: raise AccountError('provider username unavailable')
        # No offline scope is requested: expired credentials require an explicit reconnect.
        return None, self.accounts.connect_oauth(principal, claims['sub'], username, token,
                                                  self.accounts.clock() + expires, scopes=scopes)
