"""Authenticated observation reads and source-bound ingestion, without commands."""
import hmac
from hashlib import sha256

from fastapi import Depends, Header, HTTPException, Request, Response
from pydantic import ValidationError

from core_common.protocol.workcell_observations import ArmObservation


def assert_workcell_observation_credentials_isolated(service, *, console, principals,
                                                      other_tokens=(), other_services=()):
    for token in service.credential_values():
        digest = sha256(token.encode()).hexdigest()
        if (any(other is not None and hmac.compare_digest(token.encode(), other.encode()) for other in other_tokens)
                or digest in principals or console.user_credential_overlaps_robot_secret((digest,))
                or any(other is not None and other.uses_token(token) for other in other_services)):
            raise ValueError("Workcell observation credential must differ from every other site credential")


def install_workcell_observation_routes(app, *, service, require_viewer):
    def available():
        if service is None:
            raise HTTPException(503, detail={"code": "WORKCELL_OBSERVATIONS_UNAVAILABLE"})
        return service

    @app.get("/api/fleet/workcell-observations", tags=["workcell-observations"])
    def observations(response: Response, _principal=Depends(require_viewer)):
        response.headers["Cache-Control"] = "no-store"
        return available().snapshot()

    @app.post("/api/fleet/workcell-observations/arms/{source_id}", status_code=202,
              tags=["workcell-observations"])
    async def ingest(source_id: str, request: Request,
                     token: str | None = Header(None, alias="X-Workcell-Observation-Token")):
        intake = available()
        try:
            intake.authorize(source_id, token)
        except PermissionError:
            raise HTTPException(401, detail={"code": "WORKCELL_OBSERVATION_UNAUTHORIZED"}) from None
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 16384:
                raise HTTPException(413, detail={"code": "WORKCELL_OBSERVATION_TOO_LARGE"})
            body.extend(chunk)
        try:
            observation = ArmObservation.model_validate_json(body)
        except ValidationError:
            raise HTTPException(422, detail={"code": "INVALID_ARM_OBSERVATION"}) from None
        try:
            intake.ingest(source_id, token, observation)
        except ValueError:
            raise HTTPException(409, detail={"code": "WORKCELL_OBSERVATION_CONFLICT"}) from None
        return {"accepted": True}
