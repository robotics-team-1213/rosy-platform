"""HTTPS-only camera receiver consent; anonymous hints never authorize ingest or control."""
import json
from hashlib import sha256
from fastapi import Depends, HTTPException, Request, Response
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from core_common.protocol import camera_peer as wire
from .camera_peer_crypto import ProofDenied
from .camera_peer_store import CameraPeerDenied

BASE = '/api/fleet/pairing/v2'


async def body(request):
    declared = request.headers.get('content-length')
    if declared and (len(declared) > 10 or not declared.isdigit() or int(declared) > 4096):
        raise HTTPException(413, 'bounded camera pairing body required')
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > 4096:
            raise HTTPException(413, 'camera pairing body exceeds 4096 bytes')
        chunks.append(chunk)
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate field')
            result[key] = value
        return result
    def constant(_):
        raise ValueError('nonfinite JSON')
    try:
        return json.loads(b''.join(chunks), object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError) as exc:
        raise HTTPException(400, 'invalid camera pairing JSON') from exc


def configured_issuers(users):
    """Only exact trusted static site-users rows qualify; untyped expiry never disappears."""
    return [{'principal_id': row['principal_id'], 'role': 'operator',
             'token_sha256': digest, 'source': 'site-users'}
            for digest, row in users.items()
            if isinstance(row, dict) and set(row) == {'principal_id', 'role'}
            and row['role'] == 'operator']


def install_camera_peer_routes(app, service, *, require_named_operator, current_users):
    service.identity_snapshot()  # Do not mount partially configured or HTTP-only bootstrap.

    def secure(request: Request):
        if request.url.scheme != 'https':
            raise HTTPException(403, 'verified TLS required for camera pairing')

    def private(response: Response):
        response.headers['Cache-Control'] = 'no-store'

    def owner(request: Request, principal=Depends(require_named_operator)):
        authorization = request.headers.get('authorization', '')
        if not authorization.startswith('Bearer ') or len(authorization) > 4096:
            raise HTTPException(401, 'named operator credential required')
        digest = sha256(authorization[7:].encode()).hexdigest()
        for issuer in configured_issuers(current_users()):
            if issuer['token_sha256'] == digest and issuer['principal_id'] == principal.principal_id:
                return issuer
        raise HTTPException(403, 'current configured named operator required')

    async def invoke(method, *args, **kwargs):
        try:
            return await run_in_threadpool(method, *args, **kwargs)
        except (CameraPeerDenied, ProofDenied, ValidationError) as exc:
            # No key, digest, signature, token, request secret or database detail in errors.
            status = 429 if 'rate limit' in str(exc) else 409
            raise HTTPException(status, 'camera pairing request unavailable',
                                headers={'Retry-After': '2'} if status == 429 else None) from None

    def request_secret(request):
        value = request.headers.get('authorization', '')
        if not value.startswith('Bearer ') or len(value) != 50:
            raise HTTPException(401, 'camera request credential required')
        return value[7:]

    guards = [Depends(secure), Depends(private)]

    @app.get(BASE + '/identity', response_model=wire.IdentitySnapshot, dependencies=guards)
    async def identity():
        return await invoke(service.identity_snapshot)

    @app.post(BASE + '/requests', response_model=wire.CreatedRequest, status_code=201, dependencies=guards)
    async def request_create(request: Request):
        return await invoke(service.request, await body(request))

    @app.get(BASE + '/pending', response_model=list[wire.PendingRequest], dependencies=guards)
    async def pending(issuer=Depends(owner)):
        return await invoke(service.pending)

    @app.get(BASE + '/relationships', response_model=list[wire.RelationshipSnapshot], dependencies=guards)
    async def relationships(issuer=Depends(owner)):
        return await invoke(service.relationships)

    @app.get(BASE + '/requests/{request_id}', response_model=wire.StateSnapshot, dependencies=guards)
    async def status(request_id: str, request: Request):
        credential = request_secret(request)
        return await invoke(service.status, request_id, credential)

    @app.post(BASE + '/requests/{request_id}/cancel', response_model=wire.StateSnapshot, dependencies=guards)
    async def cancel(request_id: str, request: Request):
        credential = request_secret(request)
        return await invoke(service.cancel, request_id, credential)

    @app.post(BASE + '/requests/{request_id}/decision', response_model=wire.StateSnapshot, dependencies=guards)
    async def decision(request_id: str, request: Request, issuer=Depends(owner)):
        return await invoke(service.decide, request_id, await body(request), issuer=issuer)

    @app.post(BASE + '/challenge', response_model=wire.ChallengeSnapshot, dependencies=guards)
    async def challenge(request: Request):
        try:
            data = wire.ChallengeRequest.model_validate(await body(request))
        except ValidationError:
            raise HTTPException(400, 'invalid camera challenge request') from None
        return await invoke(service.challenge, data.relationship_id, generation=data.generation)

    @app.post(BASE + '/session', response_model=wire.SessionSnapshot, dependencies=guards)
    async def session(request: Request):
        return await invoke(service.session, await body(request))

    @app.post(BASE + '/relationships/{relationship_id}/revoke', dependencies=guards)
    async def revoke(relationship_id: str, issuer=Depends(owner)):
        await invoke(service.store.revoke, relationship_id, actor=issuer)
        return {'relationship_id': relationship_id, 'state': 'revoked'}
