"""D-801 site-issued READ-only robot media grants for the site console (amends D-789 Decision 3).

Fleet only signs short grants and answers the media authority's recheck; video never passes
through Fleet (MediaMTX serves WHEP directly). A grant is per robot, read-only, at most 60 s,
renewed every 20 s by the console, and rechecked by the media authority every second against
the same browser credential, so logout or a role change ends it within 5 s. Every grant is
audited in `fleet_media_audit`. Off unless ROSY_FLEET_MEDIA_CONFIG names a config file.
"""

import base64
from contextlib import closing
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time

from fastapi import Depends, Header, HTTPException, Path as PathParam, Request
from fastapi.responses import JSONResponse, Response
from starlette.requests import Request as StarletteRequest

from core_common.protocol.media_tokens import MediaTokenRejected, public_media_key, sign_media, verify_media
from fleet.server.site_auth import SitePrincipal

ROBOT, GRANT = r'^[A-Za-z0-9._-]{1,96}$', r'^[a-f0-9]{32}$'
TTL_S, IDLE_END_S = 60, 70
NO_STORE = {'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'}
# The browser's existing Fleet credential, kept in memory only, to rerun Fleet's own check.
_IDENTITY = ('authorization', 'cookie', 'host', 'origin', 'x-forwarded-for')


def load_config(path):
    config = json.loads(Path(path).read_text(encoding='utf-8'))
    site = config['site_url'].rstrip('/')
    if not site.startswith('https://') or any(char in site[8:] for char in '?#@/'):
        raise ValueError('media site_url must be a fixed https origin')
    key = Path(config['signing_key_file'])
    if key.is_symlink() or not key.is_file() or key.stat().st_size > 16384:
        raise ValueError('invalid media signing key file')
    private = key.read_bytes()
    public_media_key(private)  # an Ed25519 private key, or refuse
    if not config['audience'].startswith('site:'):
        raise ValueError('media audience must be site:<id>')
    return {'site_url': site, 'audience': config['audience'], 'key_id': config['key_id'],
            'private': private, 'audit_db': config['audit_db']}


class MediaGrantLedger:
    """Live grants in memory (with the credential to recheck); one audit row per grant on disk."""

    def __init__(self, audit_db, clock=time.time):
        self._db, self._clock, self._lock = audit_db, clock, threading.Lock()
        self._grants = {}
        with closing(sqlite3.connect(self._db)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS fleet_media_audit (grant_id TEXT PRIMARY KEY, '
                       'principal_id TEXT NOT NULL, role TEXT NOT NULL, robot_id TEXT NOT NULL, '
                       'started_at REAL NOT NULL, last_seen_at REAL NOT NULL, ended_at REAL, end_reason TEXT)')

    def _write(self, sql, params):
        with closing(sqlite3.connect(self._db)) as db, db:
            db.execute(sql, params)

    def start(self, principal, robot_id, headers):
        self.sweep()
        grant_id, now = secrets.token_hex(16), self._clock()
        self._write('INSERT INTO fleet_media_audit VALUES (?, ?, ?, ?, ?, ?, NULL, NULL)',
                    (grant_id, principal.principal_id, principal.role, robot_id, now, now))
        with self._lock:
            self._grants[grant_id] = {'principal_id': principal.principal_id, 'robot_id': robot_id,
                                      'headers': headers, 'seen': now}
        return grant_id

    def get(self, grant_id):
        with self._lock:
            return self._grants.get(grant_id)

    def seen(self, grant_id):
        now = self._clock()
        with self._lock:
            if grant_id in self._grants:
                self._grants[grant_id]['seen'] = now
        self._write('UPDATE fleet_media_audit SET last_seen_at = ? WHERE grant_id = ? AND ended_at IS NULL',
                    (now, grant_id))

    def end(self, grant_id, reason):
        with self._lock:
            found = self._grants.pop(grant_id, None)
        if found is not None:
            self._write('UPDATE fleet_media_audit SET ended_at = ?, end_reason = ? '
                        'WHERE grant_id = ? AND ended_at IS NULL', (self._clock(), reason, grant_id))
        return found is not None

    def sweep(self):
        """A console that vanished stops renewing; its grant ends (and is audited) after 70 s."""
        cutoff = self._clock() - IDLE_END_S
        with self._lock:
            idle = [grant_id for grant_id, entry in self._grants.items() if entry['seen'] < cutoff]
        for grant_id in idle:
            self.end(grant_id, 'expired')

    def rows(self):
        with closing(sqlite3.connect(self._db)) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute('SELECT * FROM fleet_media_audit ORDER BY started_at')]


def _payload(token):
    part = token.split('.')[1]
    return json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4)))


def install_robot_media_routes(app, *, require_camera_viewer, config_path=None, clock=time.time):
    path = config_path or os.environ.get('ROSY_FLEET_MEDIA_CONFIG')
    app.state.robot_media = None
    if not path:
        return None
    config = load_config(path)
    ledger = MediaGrantLedger(config['audit_db'], clock)
    public = {config['key_id']: public_media_key(config['private'])}
    app.state.robot_media = ledger
    app.state.robot_media_origin = config['site_url']

    def viewer(request: Request) -> SitePrincipal:
        principal = require_camera_viewer(request)
        # The tokenless LAN camera proxy reads site cameras only, never robot video.
        if principal.principal_id == 'lan-camera' or not principal.permits_site('fleet.read'):
            raise HTTPException(403, detail={'code': 'FORBIDDEN', 'message': 'fleet.read required'})
        return principal

    def recheck(entry):
        """Rerun Fleet's authorization on the stored browser credential (logout, role change)."""
        scope = {'type': 'http', 'method': 'GET', 'path': '/api/fleet/auth/session', 'query_string': b'',
                 'headers': [(name.encode('latin-1'), value.encode('latin-1')) for name, value in entry['headers']],
                 'client': ('127.0.0.1', 0), 'server': ('fleet', 443), 'scheme': 'https'}
        try:
            return viewer(StarletteRequest(scope)).principal_id == entry['principal_id']
        except HTTPException:
            return False

    def sign(grant_id, principal_id, robot_id):
        now = int(clock())
        front = f'robots/{robot_id}/front'
        token = sign_media(dict(iss=config['audience'], aud=config['audience'], sub=principal_id, jti=grant_id,
                                robot_id=robot_id, path=front, action='read', iat=now, exp=now + TTL_S),
                           config['private'], config['key_id'])
        return JSONResponse({'grant_id': grant_id, 'token': token, 'expires_at': now + TTL_S,
                             'audience': config['audience'], 'robot_id': robot_id, 'path': front,
                             'action': 'read', 'site_url': config['site_url']}, headers=NO_STORE)

    def owned(grant_id, robot_id, principal):
        entry = ledger.get(grant_id)
        if entry is not None and (entry['robot_id'] != robot_id or entry['principal_id'] != principal.principal_id):
            raise HTTPException(403, detail={'code': 'FORBIDDEN', 'message': 'media grant owner mismatch'})
        return entry

    @app.post('/api/fleet/robots/{robot_id}/media-grant', status_code=201, tags=['robot-media'])
    def issue_robot_media_grant(request: Request, robot_id: str = PathParam(pattern=ROBOT),
                                principal: SitePrincipal = Depends(viewer)):
        if robot_id not in app.state.console.clients():
            raise HTTPException(404, detail={'code': 'UNKNOWN_ROBOT', 'message': robot_id})
        headers = [(name, value) for name, value in request.headers.items() if name.lower() in _IDENTITY]
        response = sign(ledger.start(principal, robot_id, headers), principal.principal_id, robot_id)
        response.status_code = 201
        return response

    @app.post('/api/fleet/robots/{robot_id}/media-grant/{grant_id}/renew', tags=['robot-media'])
    def renew_robot_media_grant(robot_id: str = PathParam(pattern=ROBOT), grant_id: str = PathParam(pattern=GRANT),
                                principal: SitePrincipal = Depends(viewer)):
        if owned(grant_id, robot_id, principal) is None:
            raise HTTPException(403, detail={'code': 'FORBIDDEN', 'message': 'media grant ended'})
        ledger.seen(grant_id)
        return sign(grant_id, principal.principal_id, robot_id)

    @app.delete('/api/fleet/robots/{robot_id}/media-grant/{grant_id}', status_code=204, tags=['robot-media'])
    def end_robot_media_grant(robot_id: str = PathParam(pattern=ROBOT), grant_id: str = PathParam(pattern=GRANT),
                              principal: SitePrincipal = Depends(viewer)):
        owned(grant_id, robot_id, principal)
        ledger.end(grant_id, 'closed')
        return Response(status_code=204, headers=NO_STORE)

    @app.post('/api/fleet/media/validate', tags=['robot-media'])
    def validate_robot_media_grant(authorization: str | None = Header(default=None)):
        """The media authority's one-second recheck; the grant itself is the credential."""
        inactive = JSONResponse({'active': False}, headers=NO_STORE)
        token = authorization[7:] if authorization and authorization.startswith('Bearer ') else ''
        try:
            claims = verify_media(token, public, robot_id=_payload(token)['robot_id'],
                                  audience=config['audience'], now=clock())
        except (MediaTokenRejected, ValueError, KeyError, TypeError, IndexError):
            return inactive
        ledger.sweep()
        entry = ledger.get(claims.jti)
        if (claims.iss != config['audience'] or entry is None or entry['robot_id'] != claims.robot_id
                or entry['principal_id'] != claims.sub):
            return inactive
        if not recheck(entry):
            ledger.end(claims.jti, 'credential_revoked')
            return inactive
        return JSONResponse({'active': True, 'grant_id': claims.jti, 'robot_id': claims.robot_id,
                             'path': claims.path, 'action': 'read', 'audience': claims.aud,
                             'expires_at': claims.exp}, headers=NO_STORE)

    @app.middleware('http')
    async def robot_media_console_csp(request, call_next):
        # The console page may call exactly the configured site media origin (WHEP signaling).
        response = await call_next(request)
        policy = response.headers.get('content-security-policy')
        if policy and "connect-src 'self';" in policy:
            response.headers['content-security-policy'] = policy.replace(
                "connect-src 'self';", f"connect-src 'self' {config['site_url']};")
        return response

    return ledger
