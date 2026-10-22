"""HTTP boundaries for the D-757 Account authorization service."""
import sqlite3
from urllib.parse import urlencode

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from fleet.server.account_authority import NO_STORE, _form
from fleet.server.password_session import COOKIE, SessionStorageUnavailable, StalePasswordCheck


def install_account_authority_routes(app, *, sessions, authority):
    async def call(fn, *args):
        try:
            return await run_in_threadpool(fn, *args)
        except (sqlite3.Error, SessionStorageUnavailable):
            raise HTTPException(503, 'Account service unavailable', headers=NO_STORE) from None

    def protocol(result):
        headers, body, status = result
        return Response(body, status_code=status, headers={**headers, **NO_STORE})

    def recovery(error, target='/console'):
        return RedirectResponse('/console/login?' + urlencode({'error': error, 'return': target}),
                                status_code=303, headers=NO_STORE)

    async def form(request):
        if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/x-www-form-urlencoded':
            raise HTTPException(415, 'Form content required', headers=NO_STORE)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 8192:
                raise HTTPException(413, 'Request too large', headers=NO_STORE)
        try:
            return body.decode('utf-8')
        except UnicodeDecodeError:
            raise HTTPException(400, 'Invalid form', headers=NO_STORE) from None

    @app.get('/api/fleet/auth/authorize')
    async def authorize(request: Request):
        query = request.url.query
        browser = 'text/html' in request.headers.get('accept', '').lower()
        try:
            authority.authorization_fields(query)
        except ValueError:
            return recovery('invalid_request') if browser else protocol(authority.error())
        target = '/api/fleet/auth/authorize?' + query
        try:
            try:
                context = await call(sessions.account_context, request.cookies.get(COOKIE, ''))
            except StalePasswordCheck:
                context = None
            if context is None:
                return RedirectResponse('/console/login?' + urlencode({'return': target}),
                                        status_code=303, headers=NO_STORE)
            result = await call(authority.authorize, query, context)
        except HTTPException as error:
            if browser and error.status_code == 503:
                return recovery('service_unavailable', target)
            raise
        if browser and result[2] in (400, 403):
            return recovery('access_denied' if result[2] == 403 else 'invalid_request', target)
        return protocol(result)

    @app.post('/api/fleet/auth/token')
    async def token(request: Request):
        return protocol(await call(authority.token, await form(request)))

    async def token_field(request):
        try:
            fields = _form(await form(request))
            if set(fields) != {'token'} or not fields['token']:
                raise ValueError()
            return fields['token']
        except ValueError:
            raise HTTPException(400, 'Invalid form', headers=NO_STORE) from None

    @app.post('/api/fleet/auth/introspect')
    async def introspect(request: Request):
        return JSONResponse(await call(authority.introspect, await token_field(request)), headers=NO_STORE)

    @app.post('/api/fleet/auth/userinfo')
    async def userinfo(request: Request):
        profile = await call(authority.userinfo, await token_field(request))
        if profile is None:
            raise HTTPException(401, 'Account session refused', headers=NO_STORE)
        return JSONResponse(profile, headers=NO_STORE)

    @app.post('/api/fleet/auth/revoke')
    async def revoke(request: Request):
        await call(authority.revoke, await token_field(request))
        return Response(status_code=200, headers=NO_STORE)

    @app.get('/api/fleet/auth/keys')
    def keys():
        return JSONResponse(authority.jwks, headers=NO_STORE)
