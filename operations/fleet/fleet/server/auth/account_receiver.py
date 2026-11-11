"""Fleet consumes Account grants; its encrypted receiver DB contains no password authority."""
import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
import json
import re
from urllib.parse import parse_qsl, urlsplit

from cryptography.fernet import InvalidToken
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from core_common.protocol.account_client import AccountUnavailable, load_account_client
from fleet.server.site_auth import SitePrincipal

COOKIE = 'rosy_fleet_account'
FLOW_COOKIE = 'rosy_fleet_account_flow'
NO_STORE = {'Cache-Control': 'no-store', 'Pragma': 'no-cache', 'Referrer-Policy': 'no-referrer'}
DESTINATIONS = ('/console', '/console/cell', '/console/site-map', '/console/install', '/console/maintenance', '/console/policy',
                '/console/profile', '/console/accounts')


ANCHORS = {'/console/site-map': {'teach-heading'},
           '/console/install': {'robots', 'device-profiles', 'cameras', 'calibration', 'robot-enrollment', 'peer-picker',
                                'camera-link', 'camera-peer-panel', 'usb-camera-panel', 'camera-calibration',
                                'measured-calibration'}}


def fleet_return_allowed(target):
    if (not isinstance(target, str) or len(target) > 4096 or '\\' in target
            or any(ord(char) < 32 or ord(char) == 127 for char in target)):
        return False
    try:
        url = urlsplit(target)
        pairs = parse_qsl(url.query, keep_blank_values=True, strict_parsing=True, max_num_fields=5)
    except ValueError:
        return False
    if url.scheme or url.netloc or url.path not in DESTINATIONS:
        return False
    query = dict(pairs)
    allowed = ({'view', 'show', 'inbox', 'arm_transfer', 'robot'} if url.path == '/console' else
               {'robot'} if url.path == '/console/site-map' else set())
    if (len(query) != len(pairs) or set(query) - allowed
            or url.fragment and url.fragment not in ANCHORS.get(url.path, ())):
        return False
    if 'view' in query and query['view'] not in {'work', 'records'}:
        return False
    if 'show' in query and ('view' not in query or query['show'] not in {
            'pending', 'done', 'new', 'open', 'closed', 'facts', 'log'}):
        return False
    if 'inbox' in query and query['inbox'] != '1':
        return False
    if 'robot' in query and not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', query['robot']):
        return False
    if 'arm_transfer' in query and (query.get('view') != 'work'
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}', query['arm_transfer'])):
        return False
    return True


def principal_from_claims(claims):
    role = ('operator' if claims.permits(claims.aud, 'fleet.operate') else
            'policy-admin' if claims.permits(claims.aud, 'fleet.policy') else 'viewer')
    return SitePrincipal(claims.sub, role, account_id=claims.sub, site_resource=claims.aud,
                         grants=tuple((g.resource, tuple(g.capabilities)) for g in claims.grants))


class FleetAccountSessions:
    def __init__(self, client):
        if not client.resource.startswith('site:'):
            raise ValueError('Fleet Account receiver requires a site resource')
        self.client = client

    def same_origin(self, request):
        expected = urlsplit(self.client.callback)
        return request.headers.get('origin') == f'{expected.scheme}://{expected.netloc}'

    def migrated_principal(self, principal_id, *, db=None):
        return False  # app composition retains only machine credentials in receiver mode.

    def principal_by_id(self, principal_id, *, db=None):
        """Recovery needs a retained receiver session and a fresh online check, including historical actors."""
        try:
            with self.client.transaction() as connection:
                rows = connection.execute('SELECT id,tokens FROM app_account_sessions WHERE expires>?',
                                          (self.client.clock(),)).fetchall()
            for row in rows:
                tokens = json.loads(self.client.cipher.decrypt(row['tokens']))
                if tokens.get('_account_sub') != principal_id:
                    continue
                claims = self.client.resolve_session_id(row['id'])
                if claims is not None and claims.sub == principal_id:
                    with self.client.transaction() as connection:
                        current = connection.execute('SELECT tokens FROM app_account_sessions WHERE id=?',
                                                     (row['id'],)).fetchone()
                    if current is None:
                        continue
                    tokens = json.loads(self.client.cipher.decrypt(current['tokens']))
                    claims = self.client.verify_bearer(tokens['access_token'])
                    if (claims.sub == principal_id
                            and self.client.post('introspect', {'token': tokens['access_token']}).get('active') is True):
                        return principal_from_claims(claims)
        except (AccountUnavailable, InvalidToken, KeyError, TypeError):
            raise ValueError('Account proposer state unavailable') from None
        return None

    def authenticate_bearer(self, token, request):
        try:
            claims = self.client.verify_bearer(token)
        except AccountUnavailable:
            raise HTTPException(503, detail={'code': 'ACCOUNT_UNAVAILABLE'}, headers=NO_STORE) from None
        except ValueError:
            raise HTTPException(401, detail={'code': 'UNAUTHORIZED'}, headers=NO_STORE) from None
        request.state.site_auth_expires_at = datetime.fromtimestamp(claims.exp, timezone.utc).isoformat()
        return principal_from_claims(claims)

    def authenticate(self, request):
        cookie = request.cookies.get(COOKIE)
        if not cookie:
            return None
        if request.method not in {'GET', 'HEAD', 'OPTIONS'} and not self.same_origin(request):
            raise HTTPException(403, detail={'code': 'CSRF_REJECTED'}, headers=NO_STORE)
        try:
            claims = self.client.resolve(cookie)
        except AccountUnavailable:
            raise HTTPException(503, detail={'code': 'ACCOUNT_UNAVAILABLE'}, headers=NO_STORE) from None
        except ValueError:
            claims = None
        if claims is None:
            return None
        request.state.site_auth_expires_at = datetime.fromtimestamp(claims.exp, timezone.utc).isoformat()
        return principal_from_claims(claims)


def install_account_receiver(app, *, config):
    client = load_account_client(config, destinations=DESTINATIONS)
    sessions = FleetAccountSessions(client)
    app.state.account_client = client

    async def invoke(fn, *args, **kwargs):
        try:
            return await run_in_threadpool(fn, *args, **kwargs)
        except AccountUnavailable:
            raise HTTPException(503, detail={'code': 'ACCOUNT_UNAVAILABLE'}, headers=NO_STORE) from None
        except ValueError:
            raise HTTPException(401, detail={'code': 'ACCOUNT_SESSION_REFUSED'}, headers=NO_STORE) from None

    @app.get('/api/fleet/auth/login')
    @app.get('/console/login', include_in_schema=False)
    async def login(request: Request):
        flow, url = await invoke(client.start, request.query_params.get('return', '/console'),
                                 destination_allowed=fleet_return_allowed)
        response = RedirectResponse(url, status_code=303, headers=NO_STORE)
        response.set_cookie(FLOW_COOKIE, flow, secure=True, httponly=True, samesite='lax', max_age=600)
        return response

    @app.get('/api/fleet/auth/callback')
    async def callback(request: Request):
        if set(request.query_params) != {'code', 'state'} or len(request.query_params.multi_items()) != 2:
            raise HTTPException(401, detail={'code': 'INVALID_CALLBACK'}, headers=NO_STORE)
        try:
            cookie, target = await invoke(client.finish, request.cookies.get(FLOW_COOKIE, ''),
                                         request.query_params['state'], request.query_params['code'])
        except HTTPException:
            # A person gets the console and its login link, not a JSON dead end. No session is set either way.
            if 'text/html' in request.headers.get('accept', ''):
                return RedirectResponse('/console', status_code=303, headers=NO_STORE)
            raise
        response = RedirectResponse(target, status_code=303, headers=NO_STORE)
        response.delete_cookie(FLOW_COOKIE, secure=True, httponly=True, samesite='lax')
        response.set_cookie(COOKIE, cookie, secure=True, httponly=True, samesite='lax', max_age=2592000)
        return response

    @app.get('/api/fleet/auth/session')
    async def session(request: Request):
        cookie = request.cookies.get(COOKIE, '')
        authorization = request.headers.get('authorization')
        if authorization is not None:
            if not authorization.startswith('Bearer '):
                raise HTTPException(401, detail={'code': 'UNAUTHORIZED'}, headers=NO_STORE)
            claims = await invoke(client.verify_bearer, authorization[7:])
        else:
            claims = await invoke(client.resolve, cookie)
        common = {'via': 'bearer' if authorization else 'cookie'}
        if claims is None:
            return JSONResponse({**common, 'authenticated': False}, status_code=401, headers=NO_STORE)
        principal = principal_from_claims(claims)
        profile = await invoke(client.profile, cookie) if not authorization else None
        return JSONResponse({**common, 'authenticated': True, 'principal_id': principal.principal_id,
            'role': principal.role, 'account_id': claims.sub, 'site_resource': claims.aud,
            'session_family': claims.sid, 'revision': claims.rev, 'password_change_required': False,
            'expires_at': datetime.fromtimestamp(claims.exp, timezone.utc).isoformat(), 'profile': profile,
            'grants': [g.model_dump() for g in claims.grants]}, headers=NO_STORE)

    @app.post('/api/fleet/auth/login')
    def password_login():
        raise HTTPException(409, detail={'code': 'ACCOUNT_LOGIN_REDIRECT',
                                        'login_url': '/api/fleet/auth/login'}, headers=NO_STORE)

    @app.post('/api/fleet/auth/logout')
    async def logout(request: Request):
        if not sessions.same_origin(request):
            raise HTTPException(403, detail={'code': 'CSRF_REJECTED'}, headers=NO_STORE)
        pending = False
        try:
            await run_in_threadpool(client.logout, request.cookies.get(COOKIE, ''))
        except AccountUnavailable:
            pending = True
        except ValueError:
            raise HTTPException(401, detail={'code': 'ACCOUNT_SESSION_REFUSED'}, headers=NO_STORE) from None
        response = Response(status_code=503 if pending else 204, headers=NO_STORE)
        response.delete_cookie(COOKIE, secure=True, httponly=True, samesite='lax')
        return response

    @app.get('/console/profile', include_in_schema=False)
    def profile_redirect():
        return RedirectResponse(client.profile_url, status_code=303, headers=NO_STORE)

    @app.get('/console/accounts', include_in_schema=False)
    def accounts_redirect():
        return RedirectResponse(client.issuer + '/console/accounts', status_code=303, headers=NO_STORE)

    inner = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async def retry():
            while True:
                with suppress(AccountUnavailable, ValueError):
                    await run_in_threadpool(client.retry_revocations)
                await asyncio.sleep(20)
        task = asyncio.create_task(retry())
        try:
            async with inner(application) as state:
                yield state
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
    app.router.lifespan_context = lifespan
    return sessions
