"""D-757 shared Robot/Pilot browser session endpoints."""
import asyncio
from datetime import datetime, timezone
from contextlib import asynccontextmanager, suppress
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from core_common.protocol.account_client import AccountDenied, AccountUnavailable
from .errors import ApiError

COOKIE = 'rosy_app_account'
FLOW_COOKIE = 'rosy_account_flow'
NO_STORE = {'Cache-Control': 'no-store', 'Pragma': 'no-cache', 'Referrer-Policy': 'no-referrer'}


def same_origin(connection):
    expected = urlsplit(connection.app.state.account_client.callback)
    return connection.headers.get('origin') == f'{expected.scheme}://{expected.netloc}'


def account_context(claims):
    from .deps import AuthContext
    role = next((role for role, cap in [('administrator', 'robot.admin'), ('operator', 'robot.operate'),
                                       ('viewer', 'robot.read')] if claims.permits(claims.aud, cap)), 'viewer')
    return AuthContext('account:' + claims.sid, role, source='account', principal_ref=claims.sub,
                       expires_at=datetime.fromtimestamp(claims.exp, timezone.utc).isoformat(), account=claims)


def authenticate_account(connection, authorization=None):
    receiver = getattr(connection.app.state, 'account_client', None)
    if receiver is None:
        return None
    cookie = connection.cookies.get(COOKIE)
    try:
        if authorization and authorization.startswith('Bearer ') and authorization.count('.') == 2:
            claims = receiver.verify_bearer(authorization[7:])
        elif cookie and not authorization:
            if (connection.scope['type'] == 'websocket' or connection.method not in {'GET', 'HEAD', 'OPTIONS'}) and not same_origin(connection):
                raise ApiError('FORBIDDEN', 403, 'Account session requires same origin')
            claims = receiver.resolve(cookie)
        else:
            return None
    except AccountUnavailable:
        raise ApiError('UNAVAILABLE', 503, 'Account service unavailable') from None
    except ValueError:
        claims = None
    if claims is None:
        raise ApiError('UNAUTHORIZED', 401, 'Account session expired')
    return account_context(claims)


def install_account_sessions(app):
    def receiver():
        value = getattr(app.state, 'account_client', None)
        if value is None:
            raise ApiError('UNAVAILABLE', 503, 'Rosy Account is not configured')
        return value

    async def invoke(fn, *args):
        try:
            return await run_in_threadpool(fn, *args)
        except AccountUnavailable:
            raise ApiError('UNAVAILABLE', 503, 'Account service unavailable') from None
        except ValueError:
            raise ApiError('UNAUTHORIZED', 401, 'Account session refused') from None

    @app.get('/api/account/login')
    async def login(request: Request):
        flow, url = await invoke(receiver().start, request.query_params.get('return', '/dashboard'))
        response = RedirectResponse(url, status_code=303, headers=NO_STORE)
        response.set_cookie(FLOW_COOKIE, flow, secure=True, httponly=True, samesite='lax', max_age=600)
        return response

    @app.get('/api/account/callback')
    async def callback(request: Request):
        if set(request.query_params) != {'code', 'state'} or len(request.query_params.multi_items()) != 2:
            raise ApiError('UNAUTHORIZED', 401, 'Invalid Account callback')
        cookie, target = await invoke(receiver().finish, request.cookies.get(FLOW_COOKIE, ''),
                                     request.query_params['state'], request.query_params['code'])
        response = RedirectResponse(target, status_code=303, headers=NO_STORE)
        response.delete_cookie(FLOW_COOKIE, secure=True, httponly=True, samesite='lax')
        response.set_cookie(COOKIE, cookie, secure=True, httponly=True, samesite='lax', max_age=2592000)
        return response

    @app.get('/api/account/session')
    async def session(request: Request):
        client = getattr(app.state, 'account_client', None)
        body = (await invoke(client.browser_session, request.cookies.get(COOKIE, '')))[0] if client else             {'enabled': False, 'authenticated': False, 'profile': None, 'profile_url': None}
        return JSONResponse(body, headers=NO_STORE)

    @app.post('/api/account/logout')
    async def logout(request: Request):
        client = receiver()
        if not same_origin(request):
            raise ApiError('FORBIDDEN', 403, 'Account session requires same origin')
        pending = False
        try:
            await run_in_threadpool(client.logout, request.cookies.get(COOKIE, ''))
        except AccountUnavailable:
            pending = True
        response = JSONResponse({'authenticated': False, 'revocation_pending': pending},
                                status_code=503 if pending else 200, headers=NO_STORE)
        response.delete_cookie(COOKIE, secure=True, httponly=True, samesite='lax')
        return response

    inner = app.router.lifespan_context
    @asynccontextmanager
    async def lifespan(application):
        async def retry():
            while True:
                client = getattr(app.state, 'account_client', None)
                if client:
                    with suppress(AccountUnavailable, AccountDenied):
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
