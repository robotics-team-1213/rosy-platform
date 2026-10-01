"""D-341 ``/api/fleet/pairing/v1`` routes: phone, console and Vision surfaces.

Phone routes (request, reveal, poll, confirm) take no site credential: the request is
the only unauthenticated Fleet write and only creates one bounded in-memory entry; the
others need the request's poll secret. Console writes need a named operator (D-276):
a single console-token site answers 403 with the reason. Vision reads digests with
its own ``pairing_sync_token`` through a dedicated dependency, never ``authorize``
(which refuses every non-user bearer once site users exist). The camera role stays in
bodies and queries; no path names it (test_no_video_relay).
"""

from __future__ import annotations

import hmac
from collections.abc import Callable
from hashlib import sha256

from core_common.protocol import pairing as pairing_protocol
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .pairing import PairingError, PairingService

BASE = "/api/fleet/pairing/v1"
NAMED_OPERATOR_MESSAGE = "named operator required (site-users.yaml)"


class ApproveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^[0-9]{6}$")
    source_id: str = Field(min_length=1, max_length=32)


class ConfirmBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credential_id: str = Field(min_length=1, max_length=64)


def _refusal(exc: PairingError) -> HTTPException:
    headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after is not None else None
    return HTTPException(status_code=exc.status, detail=exc.body(), headers=headers)


async def _capped_body(request: Request) -> bytes:
    """Read at most MAX_REQUEST_BYTES + 1 so an oversized phone body is refused unread."""
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > pairing_protocol.MAX_REQUEST_BYTES:
        return b"\0" * (pairing_protocol.MAX_REQUEST_BYTES + 1)
    chunks, size = [], 0
    async for chunk in request.stream():
        chunks.append(chunk)
        size += len(chunk)
        if size > pairing_protocol.MAX_REQUEST_BYTES:
            break
    return b"".join(chunks)


def install_pairing_routes(app: FastAPI, service: PairingService, *, sync_token: str | None,
                           require_viewer: Callable, require_operator: Callable,
                           named_identity: bool) -> None:
    def named_operator(principal=Depends(require_operator)):
        if not named_identity:
            raise HTTPException(status_code=403, detail={
                "code": "OPERATOR_IDENTITY_REQUIRED", "message": NAMED_OPERATOR_MESSAGE})
        return principal

    sync_digest = sha256(sync_token.encode("utf-8")).digest() if sync_token else None

    def require_pairing_sync(authorization: str | None = Header(default=None)) -> None:
        if sync_digest is None:
            raise HTTPException(status_code=503, detail={
                "code": "PAIRING_SYNC_DISABLED", "message": "no pairing sync credential configured"})
        supplied = (authorization[len("Bearer "):]
                    if authorization and authorization.startswith("Bearer ") else "")
        if not hmac.compare_digest(sha256(supplied.encode("utf-8")).digest(), sync_digest):
            raise HTTPException(status_code=401, detail={
                "code": "UNAUTHORIZED", "message": "pairing sync credential required"})

    # -- phone -----------------------------------------------------------

    @app.post(f"{BASE}/requests", status_code=201, tags=["fleet-pairing"])
    async def pairing_request(request: Request) -> dict:
        try:
            return service.create(await _capped_body(request))
        except PairingError as exc:
            raise _refusal(exc) from None

    @app.post(f"{BASE}/requests/{{request_id}}/reveal", tags=["fleet-pairing"])
    async def pairing_reveal(request_id: str, request: Request,
                             authorization: str | None = Header(default=None)) -> dict:
        try:
            return service.reveal(request_id, authorization, await _capped_body(request))
        except PairingError as exc:
            raise _refusal(exc) from None

    @app.get(f"{BASE}/requests/{{request_id}}", tags=["fleet-pairing"])
    def pairing_poll(request_id: str, authorization: str | None = Header(default=None)):
        try:
            body = service.poll(request_id, authorization)
        except PairingError as exc:
            raise _refusal(exc) from None
        # The one response that carries the token: never cached by anything in between.
        return JSONResponse(body, headers={"Cache-Control": "no-store"})

    @app.post(f"{BASE}/requests/{{request_id}}/confirm", tags=["fleet-pairing"])
    async def pairing_confirm(request_id: str, request: Request,
                              authorization: str | None = Header(default=None)) -> dict:
        raw = await _capped_body(request)
        try:
            if len(raw) > pairing_protocol.MAX_REQUEST_BYTES:
                raise ValueError("too large")
            body = ConfirmBody.model_validate_json(raw)
        except ValueError:
            raise HTTPException(status_code=400, detail={
                "code": "PAIRING_CONFIRM_INVALID", "message": "confirm body is {credential_id}"})
        try:
            return service.confirm(request_id, authorization, body.credential_id)
        except PairingError as exc:
            raise _refusal(exc) from None

    # -- console ---------------------------------------------------------

    @app.get(f"{BASE}/pending", dependencies=[Depends(require_viewer)], tags=["fleet-pairing"])
    def pairing_pending() -> dict:
        return service.pending_listing()

    @app.get(f"{BASE}/credentials/summary", dependencies=[Depends(require_viewer)],
             tags=["fleet-pairing"])
    def pairing_credentials_summary() -> dict:
        return service.credentials_summary()

    @app.post(f"{BASE}/requests/{{request_id}}/approve", tags=["fleet-pairing"])
    def pairing_approve(request_id: str, body: ApproveBody, principal=Depends(named_operator)) -> dict:
        try:
            return service.approve(request_id, code=body.code, source_id=body.source_id,
                                   principal_id=principal.principal_id)
        except PairingError as exc:
            raise _refusal(exc) from None

    @app.post(f"{BASE}/requests/{{request_id}}/reject", tags=["fleet-pairing"])
    def pairing_reject(request_id: str, principal=Depends(named_operator)) -> dict:
        try:
            return service.reject(request_id, principal_id=principal.principal_id)
        except PairingError as exc:
            raise _refusal(exc) from None

    @app.post(f"{BASE}/credentials/{{credential_id}}/revoke", tags=["fleet-pairing"])
    def pairing_revoke(credential_id: str, principal=Depends(named_operator)) -> dict:
        try:
            return service.revoke(credential_id, principal_id=principal.principal_id)
        except PairingError as exc:
            raise _refusal(exc) from None

    # -- Vision ----------------------------------------------------------

    @app.get(f"{BASE}/credentials", dependencies=[Depends(require_pairing_sync)],
             tags=["fleet-pairing"])
    def pairing_credentials(role: str):
        if role != pairing_protocol.ROLE:
            raise HTTPException(status_code=400, detail={
                "code": "UNKNOWN_ROLE", "message": "only overhead-camera credentials exist"})
        return JSONResponse({"role": role, "credentials": service.sync_listing()},
                            headers={"Cache-Control": "no-store"})
