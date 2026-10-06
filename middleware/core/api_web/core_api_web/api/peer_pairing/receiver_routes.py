"""Candidate actual routes: authenticated TLS only; existing owner authentication."""
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Path
from fastapi.responses import JSONResponse
from pydantic import ValidationError, TypeAdapter
from starlette.concurrency import run_in_threadpool

from core_api_web.api.deps import get_services
from core_api_web.api.v1.common import admin
from core_api_web.api.v1.auth import client_allowed
from core_common.protocol.peer_pairing import (ApprovalCodeConfirm, ReceiverDecision,SignedRequest, SignedSession, StateSnapshot, CreatedRequest,
    PendingRequest, IdentitySnapshot, ChallengeSnapshot, SessionSnapshot, RevokedSnapshot)

router = APIRouter(prefix="/api/v1/auth/peer-pairing", tags=["auth"])


def service(request):
    if request.url.scheme != "https":
        raise HTTPException(403, "authenticated HTTPS required")
    from .receiver_initializer import get_receiver
    try:
        return get_receiver(request)
    except (ValueError, OSError):
        raise HTTPException(503, "receiver pairing unavailable") from None


async def body(request, model):
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > 4096:
            raise HTTPException(413, "request too large")
        data.extend(chunk)
    try:
        return model.model_validate_json(data)
    except ValidationError:
        raise HTTPException(422, "invalid request") from None


async def call(function, *args, schema):
    try:
        result = await run_in_threadpool(function, *args)
        adapter = TypeAdapter(schema)
        result = adapter.dump_python(adapter.validate_python(result), mode='json')
        return JSONResponse(content=result, headers={"Cache-Control": "no-store"})
    except ValueError:
        raise HTTPException(409, "request unavailable or changed") from None


@router.get("/identity")
async def identity(request: Request):
    candidate = proof_service(request)
    return await call(candidate.identity, schema=IdentitySnapshot)


@router.post("/requests")
async def create(request: Request):
    candidate = service(request)
    if request.client is None or not client_allowed(request.client.host):
        raise HTTPException(403, "initial receiver approval requires LAN access")
    parsed = await body(request, SignedRequest)
    source = request.client.host if request.client else "unknown"
    return await call(candidate.request, parsed.fields.model_dump(), parsed.signature, source, schema=CreatedRequest)


@router.get("/pending")
async def pending(request: Request, owner=Depends(admin)):
    return await call(service(request).pending, owner.token_id, schema=list[PendingRequest])


@router.get("/requests/{request_id}")
async def status(request: Request, request_id: str = Path(pattern=r'^[A-Za-z0-9_-]{32}$'), x_request_secret: str = Header(max_length=128)):
    return await call(service(request).status, request_id, x_request_secret, schema=StateSnapshot)


@router.delete("/requests/{request_id}")
async def cancel(request: Request, request_id: str = Path(pattern=r'^[A-Za-z0-9_-]{32}$'), x_request_secret: str = Header(max_length=128)):
    return await call(service(request).cancel, request_id, x_request_secret, schema=StateSnapshot)


@router.post("/requests/{request_id}/decision")
async def decision(request: Request, request_id: str = Path(pattern=r'^[A-Za-z0-9_-]{32}$'), owner=Depends(admin)):
    candidate = service(request)
    parsed = await body(request, ReceiverDecision)
    return await call(candidate.decide, owner.token_id, request_id, parsed.action, parsed.revision, parsed.persist_requested, schema=StateSnapshot)


@router.post("/requests/{request_id}/confirm")
async def confirm(request: Request, request_id: str = Path(pattern=r'^[A-Za-z0-9_-]{32}$'), x_request_secret: str = Header(max_length=128)):
    """D-483 4: the requester enters the robot-screen approval code; no session, the request secret binds it."""
    from .receiver_service import RateLimited, RoleRefused, WrongCode
    candidate = service(request)
    parsed = await body(request, ApprovalCodeConfirm)
    source = request.client.host if request.client else "unknown"
    try:
        result = await run_in_threadpool(candidate.confirm, request_id, x_request_secret, parsed.approval_code, source)
    except WrongCode as exc:
        raise HTTPException(400, {"message": "wrong approval code", "remaining_attempts": exc.remaining}) from None
    except RoleRefused:
        raise HTTPException(403, "screen-code approval is limited to operator") from None
    except RateLimited:
        raise HTTPException(429, "source rate limit reached") from None
    except ValueError:
        raise HTTPException(409, "request unavailable or changed") from None
    return await call(lambda: result, schema=StateSnapshot)


@router.post("/relationships/{relationship_id}/challenge")
async def challenge(request: Request, relationship_id: str = Path(pattern=r'^[A-Za-z0-9_-]{32}$')):
    return await call(proof_service(request).challenge, relationship_id, schema=ChallengeSnapshot)


@router.post("/relationships/{relationship_id}/session")
async def session(request: Request, relationship_id: str = Path(pattern=r'^[A-Za-z0-9_-]{32}$')):
    candidate = service(request)
    parsed = await body(request, SignedSession)
    admit(request, candidate)
    return await call(candidate.session, relationship_id, parsed.fields.model_dump(), parsed.signature, schema=SessionSnapshot)


@router.delete("/relationships/{relationship_id}")
async def revoke(request: Request, relationship_id: str = Path(pattern=r'^[A-Za-z0-9_-]{32}$'), owner=Depends(admin)):
    return await call(service(request).revoke, owner.token_id, relationship_id, schema=RevokedSnapshot)


def admit(request, candidate):
    try:
        candidate.admit_proof(request.client.host if request.client else 'unknown')
    except ValueError:
        raise HTTPException(429, 'anonymous proof rate limit reached') from None


def proof_service(request):
    candidate = service(request)
    admit(request, candidate)
    return candidate
