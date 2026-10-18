"""Local media authority HTTP adapter. TLS routing is owned by site deployment."""

import asyncio
from contextlib import asynccontextmanager, suppress
import hmac
import time

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response


NO_STORE = {'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'}


def _token(authorization):
    if (not isinstance(authorization, str) or not authorization.startswith('Bearer ')
            or not 1 <= len(authorization[7:]) <= 4096):
        raise HTTPException(401, 'Missing media delegation')
    return authorization[7:]


def create_app(authority, *, admin_token, clock=time.time, heartbeat_clock=time.monotonic):
    if not isinstance(admin_token, str) or not admin_token:
        raise ValueError('a separate local media management credential is required')
    heartbeat = [heartbeat_clock()]

    async def ticker():
        while True:
            try:
                await asyncio.to_thread(authority.tick, now=clock())
                heartbeat[0] = heartbeat_clock()
            except Exception:
                # Failed kicks retain their records and suppress a healthy heartbeat.
                pass
            await asyncio.sleep(.5)

    @asynccontextmanager
    async def lifespan(app):
        worker = asyncio.create_task(ticker())
        try:
            yield
        finally:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware('http')
    async def no_store(request, call_next):
        response = await call_next(request)
        response.headers.update(NO_STORE)
        return response

    @app.get('/health')
    async def health():
        fresh = 0 <= heartbeat_clock() - heartbeat[0] < 1
        return JSONResponse({'heartbeat_at': heartbeat[0], 'ok': fresh}, status_code=200 if fresh else 503)

    @app.post('/auth')
    async def callback(request: Request):
        # MediaMTX callback errors never echo the supplied token or JSON body.
        try:
            raw = await request.body()
            if len(raw) > 16384:
                return Response(status_code=403)
            import json
            body = json.loads(raw)
            token = body.get('token', '')
            if not isinstance(token, str) or not 1 <= len(token) <= 4096:
                return Response(status_code=403)
            if body.get('action') == 'api':
                allowed = hmac.compare_digest(token, admin_token)
            else:
                allowed = body.get('protocol') == 'webrtc' and await asyncio.to_thread(
                    authority.authorize, token, body.get('action'), body.get('path'), body.get('id'), now=clock())
            return Response(status_code=200 if allowed else 403)
        except (ValueError, TypeError, AttributeError):
            return Response(status_code=403)

    @app.post('/v1/intents', status_code=201)
    def intent(authorization: str | None = Header(default=None)):
        grant_id = authority.intent(_token(authorization), now=clock())
        if grant_id is None:
            raise HTTPException(403, 'Media intent refused')
        return {'grant_id': grant_id}

    @app.delete('/v1/intents/{grant_id}', status_code=204)
    def cancel(grant_id: str, authorization: str | None = Header(default=None)):
        if not authority.cancel_intent(grant_id, _token(authorization), now=clock()):
            raise HTTPException(403, 'Media intent owner refused')
        return Response(status_code=204)

    @app.get('/v1/sources/{robot_id}/demand')
    def demand(robot_id: str, authorization: str | None = Header(default=None)):
        value = authority.source_demand(robot_id, _token(authorization), now=clock())
        if value is None:
            raise HTTPException(403, 'Media source authority refused')
        return value

    @app.post('/v1/sessions/{session_id}/renew')
    def renew(session_id: str, authorization: str | None = Header(default=None)):
        if not authority.renew(session_id, _token(authorization), now=clock()):
            raise HTTPException(403, 'Media session renewal refused')
        return {'active': True}

    @app.get('/v1/session')
    def bound(authorization: str | None = Header(default=None)):
        result = authority.bound_session(_token(authorization), now=clock())
        if result is None:
            raise HTTPException(404, 'Media session is not ready')
        return result

    @app.post('/v1/session/renew')
    def renew_bound(authorization: str | None = Header(default=None)):
        token = _token(authorization)
        current = authority.bound_session(token, now=clock())
        if current is None or not authority.renew(current['session_id'], token, now=clock()):
            raise HTTPException(403, 'Media session renewal refused')
        return {'active': True, 'session_id': current['session_id']}

    @app.delete('/v1/session', status_code=204)
    def close_bound(authorization: str | None = Header(default=None)):
        token = _token(authorization)
        current = authority.bound_session(token, now=clock())
        if current is None or not authority.close_session(current['session_id'], token, now=clock()):
            raise HTTPException(403, 'Media session owner refused')
        return Response(status_code=204)

    @app.delete('/v1/sessions/{session_id}', status_code=204)
    def close(session_id: str, authorization: str | None = Header(default=None)):
        if not authority.close_session(session_id, _token(authorization), now=clock()):
            raise HTTPException(403, 'Media session owner refused')
        return Response(status_code=204)

    return app
