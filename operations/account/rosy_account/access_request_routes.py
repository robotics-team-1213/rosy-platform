"""D-993 public sign-up / access request intake: same-origin, size-bounded, no enumeration, no grants."""
import json

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from rosy_account.access_requests import RequestsFull
from rosy_account.http import NO_STORE, client_address
from rosy_account.password_session import COOKIE, SessionStorageUnavailable, StalePasswordCheck, same_origin

MAX_BODY = 4096


def install_access_request_routes(app, *, sessions, trust_forwarded):
    def refuse(status, code, **headers):
        return HTTPException(status, detail={'code': code}, headers={**NO_STORE, **headers})

    @app.post('/api/fleet/auth/access-requests', status_code=202, tags=['fleet-auth'])
    async def submit(request: Request):
        if not same_origin(request):
            raise refuse(403, 'CSRF_REJECTED')
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_BODY:
                raise refuse(413, 'REQUEST_TOO_LARGE')
        try:
            payload = json.loads(body)
        except (ValueError, RecursionError):  # deeply nested JSON is just malformed
            payload = None
        if not isinstance(payload, dict) or set(payload) - {'name', 'username', 'resource', 'note'}:
            raise refuse(422, 'INVALID_REQUEST')
        try:
            account = await run_in_threadpool(sessions.account_context, request.cookies.get(COOKIE, ''))
        except StalePasswordCheck:
            account = None
        except SessionStorageUnavailable:
            raise refuse(503, 'SESSION_STORAGE_UNAVAILABLE') from None
        address = client_address(request, trust_forwarded=trust_forwarded)
        try:
            await run_in_threadpool(lambda: app.state.access_requests.submit(
                client=address, account=account, **payload))
        except ValueError:
            raise refuse(422, 'INVALID_REQUEST') from None
        except RequestsFull:
            raise refuse(429, 'REQUESTS_FULL', **{'Retry-After': '3600'}) from None
        except SessionStorageUnavailable:
            raise refuse(503, 'SESSION_STORAGE_UNAVAILABLE') from None
        # Identical for a new name, a repeat and an existing login: nothing here reveals who has an account.
        return JSONResponse({'status': 'received'}, status_code=202, headers=NO_STORE)
