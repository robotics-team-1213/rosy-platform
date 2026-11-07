"""D-990: people read through Rosy Account; reader keys stay for machines and emergencies."""

import asyncio
from contextlib import suppress
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from core_common.protocol.account_client import AccountDenied, AccountUnavailable, browser_session, load_account_client

from .config import ReadPrincipal

CAPABILITY = 'monitoring.read'
COOKIE, FLOW_COOKIE = 'rosy_monitoring_account', 'rosy_monitoring_flow'
COOKIE_PATH = '/api/monitoring'
ROUTES = COOKIE_PATH + '/v1/account'
HOME = '/monitoring/'
_COOKIE = {'path': COOKIE_PATH, 'secure': True, 'httponly': True, 'samesite': 'lax'}


def load_receiver(path, site_id):
    client = load_account_client(path, destinations=(HOME,))
    if client.resource != f'site:{site_id}':
        raise ValueError('Monitoring Account resource must be its own site')
    return client


async def account_reader(client, site_id, cookie):
    """The cookie's reader, or None. An account without the capability reads no site (403, not 401)."""
    try:
        claims = await run_in_threadpool(client.resolve, cookie)
    except ValueError:
        return None
    if claims is None:
        return None
    # shortcut: a token names one site, so aggregate views across sites still need a key; upgrade with a multi-site grant.
    sites = frozenset({site_id}) if claims.permits(client.resource, CAPABILITY) else frozenset()
    return ReadPrincipal(f'account:{claims.sub}', sites)


async def retry_revocations(client):
    while True:
        with suppress(AccountUnavailable, AccountDenied, ValueError):
            await run_in_threadpool(client.retry_revocations)
        await asyncio.sleep(20)


def install_account_routes(app, client):
    @app.get(ROUTES + '/login')
    async def login():
        flow, url = await run_in_threadpool(client.start, HOME)
        response = RedirectResponse(url, status_code=303)
        response.set_cookie(FLOW_COOKIE, flow, max_age=600, **_COOKIE)
        return response

    @app.get(ROUTES + '/callback')
    async def callback(request: Request):
        if set(request.query_params) != {'code', 'state'} or len(request.query_params.multi_items()) != 2:
            return JSONResponse({'error': {'code': 'MONITORING_AUTH'}}, status_code=401)
        try:
            cookie, target = await run_in_threadpool(client.finish, request.cookies.get(FLOW_COOKIE, ''),
                                                     request.query_params['state'], request.query_params['code'])
        except ValueError:
            return JSONResponse({'error': {'code': 'MONITORING_AUTH'}}, status_code=401)
        response = RedirectResponse(target, status_code=303)
        response.delete_cookie(FLOW_COOKIE, **_COOKIE)
        response.set_cookie(COOKIE, cookie, max_age=2592000, **_COOKIE)
        return response

    @app.get(ROUTES + '/session')
    async def session(request: Request):
        try:
            body, claims = await run_in_threadpool(browser_session, client, request.cookies.get(COOKIE, ''))
        except ValueError:
            return JSONResponse({'error': {'code': 'MONITORING_AUTH'}}, status_code=401)
        body['can_read'] = bool(claims and claims.permits(client.resource, CAPABILITY))
        return JSONResponse(body)

    @app.post(ROUTES + '/logout')
    async def logout(request: Request):
        expected = urlsplit(client.callback)
        if request.headers.get('origin') != f'{expected.scheme}://{expected.netloc}':
            return JSONResponse({'error': {'code': 'MONITORING_SCOPE'}}, status_code=403)
        pending = False
        try:
            await run_in_threadpool(client.logout, request.cookies.get(COOKIE, ''))
        except AccountUnavailable:
            pending = True
        response = JSONResponse({'authenticated': False, 'revocation_pending': pending},
                                status_code=503 if pending else 200)
        response.delete_cookie(COOKIE, **_COOKIE)
        return response
