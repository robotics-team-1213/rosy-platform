"""D-789 narrow media grants; media bytes never enter these routes."""

from dataclasses import asdict
import hashlib
import hmac
import time

from fastapi import APIRouter, Depends, Header, Request, Response, Path

from core_api_web.api.deps import (
    AuthContext, MediaGrantRefused, MediaGrantRequest, MediaGrantResponse, MediaSourceGrantRequest)
from core_api_web.api.errors import ApiError
from core_api_web.api.media_binding import owner_id
from core_api_web.api.v1.common import viewer


media_router = APIRouter(prefix='/media', tags=['vision'])
NO_STORE = {'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer', 'Pragma': 'no-cache'}


def _service(request):
    service = getattr(request.app.state, 'media_grants', None)
    if service is None:
        raise ApiError('MEDIA_UNAVAILABLE', 503, 'Media authority is not configured')
    return service


def _receipt(request, grant, response):
    response.headers.update(NO_STORE)
    return {**asdict(grant), 'site_url': request.app.state.media_site_url}


@media_router.post('/grants', status_code=201, response_model=MediaGrantResponse)
def issue_media_grant(body: MediaGrantRequest, request: Request, response: Response,
                      auth: AuthContext = Depends(viewer)):
    service = _service(request)
    try:
        grant = service.issue(owner_id(request, auth), body.robot_id, 'read', now=time.time())
    except MediaGrantRefused:
        raise ApiError('FORBIDDEN', 403, 'Media scope or original authority refused') from None
    return _receipt(request, grant, response)


@media_router.post('/grants/{grant_id}/renew', response_model=MediaGrantResponse)
def renew_media_grant(request: Request, response: Response,
                      grant_id: str = Path(pattern=r'^[a-f0-9]{32}$'),
                      auth: AuthContext = Depends(viewer)):
    try:
        grant = _service(request).renew(grant_id, owner_id(request, auth), now=time.time())
    except MediaGrantRefused:
        raise ApiError('FORBIDDEN', 403, 'Media grant renewal refused') from None
    return _receipt(request, grant, response)


@media_router.delete('/grants/{grant_id}', status_code=204)
def revoke_media_grant(request: Request, grant_id: str = Path(pattern=r'^[a-f0-9]{32}$'),
                       auth: AuthContext = Depends(viewer)):
    try:
        _service(request).revoke(grant_id, owner_id(request, auth))
    except MediaGrantRefused:
        raise ApiError('FORBIDDEN', 403, 'Media grant owner mismatch') from None
    return Response(status_code=204, headers=NO_STORE)


@media_router.post('/validate')
def validate_media_grant(request: Request, response: Response, authorization: str | None = Header(default=None)):
    service = _service(request)
    response.headers.update(NO_STORE)
    if not authorization or not authorization.startswith('Bearer '):
        raise ApiError('UNAUTHORIZED', 401, 'Missing media delegation')
    return service.check(authorization[7:], now=time.time())


@media_router.post('/source-grant', status_code=201, response_model=MediaGrantResponse)
def issue_source_grant(body: MediaSourceGrantRequest, request: Request, response: Response,
                       authorization: str | None = Header(default=None)):
    service = _service(request)
    expected = getattr(request.app.state, 'media_source_digest', None)
    token = authorization[7:] if authorization and authorization.startswith('Bearer ') else ''
    if expected is None or not token or not hmac.compare_digest(hashlib.sha256(token.encode()).digest(), expected):
        raise ApiError('FORBIDDEN', 403, 'Media source credential refused')
    try:
        if body.robot_id != service.robot_id:
            raise MediaGrantRefused('media source robot mismatch')
        if body.grant_id:
            grant = service.renew(body.grant_id, 'source:' + body.robot_id, now=time.time())
        else:
            grant = service.issue('source:' + body.robot_id, body.robot_id, 'publish', now=time.time())
    except MediaGrantRefused:
        raise ApiError('FORBIDDEN', 403, 'Media source scope refused') from None
    return _receipt(request, grant, response)
