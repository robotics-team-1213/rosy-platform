"""Fleet HTTP routes for OMX arm incidents (D-971)."""
import asyncio

from fastapi import Depends, Header, HTTPException, Request, Response
from fastapi.responses import Response as RawResponse
from pydantic import ValidationError

from core_common.protocol.arm_incident.arm_incidents import (
    ARM_INCIDENT_BODY_BYTES, ARM_INCIDENT_FRAME_BYTES, ArmIncidentClear, ArmIncidentEvidenceFrame,
    ArmIncidentExplanation, ArmIncidentReport,
)
from fleet.server.camera_peer_routes import body as bounded_json
from fleet.server.site_auth import assessor_arms, build_incident_clearer
from .arm_incident_store import (  # noqa: F401  (existing Fleet exports)
    MACHINE_CLEARS_PER_WINDOW, REPEAT_WINDOW_S, ROLES, SHOWN_CLEARED, ArmIncidentStore, MachineClearRefused,
)


EVIDENCE_BODY_BYTES = ARM_INCIDENT_FRAME_BYTES * 4 // 3 + 4096


def install_arm_incident_routes(app, *, service, store, require_viewer, require_named_operator, authorize=None):
    base = "/api/fleet/workcell-observations"
    # D-1039: a named operator or a configured AI assessor; without authorize only a named operator
    clearer = require_named_operator if authorize is None else build_incident_clearer(authorize, require_named_operator)

    def source(source_id, token):
        try:
            service.authorize(source_id, token or "")
        except PermissionError:
            raise HTTPException(401, detail={"code": "WORKCELL_OBSERVATION_UNAUTHORIZED"}) from None

    @app.post(base + "/arms/{source_id}/incidents", tags=["workcell-observations"])
    async def report(source_id: str, request: Request, response: Response,
                     token: str | None = Header(None, alias="X-Workcell-Observation-Token")):
        response.headers["Cache-Control"] = "no-store"
        source(source_id, token)
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > ARM_INCIDENT_BODY_BYTES:
                raise HTTPException(413, detail={"code": "WORKCELL_OBSERVATION_TOO_LARGE"})
            data.extend(chunk)
        try:
            parsed = ArmIncidentReport.model_validate_json(data)
        except ValidationError:
            raise HTTPException(422, detail={"code": "INVALID_ARM_INCIDENT"}) from None
        if parsed.source_id != source_id:
            raise HTTPException(422, detail={"code": "INVALID_ARM_INCIDENT"})
        # a blocked loop holds every robot's heartbeat reply: store waits run off the loop
        accepted = await asyncio.to_thread(lambda: store.accepted(source_id, store.report(parsed)))
        return accepted.model_dump()

    @app.get(base + "/arms/{source_id}/hold", tags=["workcell-observations"])
    def hold(source_id: str, response: Response,
             token: str | None = Header(None, alias="X-Workcell-Observation-Token")):
        response.headers["Cache-Control"] = "no-store"
        source(source_id, token)
        return store.hold(source_id).model_dump()

    @app.post(base + "/arms/{source_id}/incidents/{incident_id}/clear", tags=["workcell-observations"])
    async def clear(source_id: str, incident_id: str, request: Request, response: Response,
                    principal=Depends(clearer)):
        response.headers["Cache-Control"] = "no-store"
        try:
            note = ArmIncidentClear.model_validate(await bounded_json(request))
        except ValidationError:
            raise HTTPException(422, detail={"code": "INVALID_ARM_INCIDENT_CLEAR"}) from None
        arms = assessor_arms(principal)  # D-1039: None for a person, who clears every kind
        if arms is not None and source_id not in arms:
            raise HTTPException(403, detail={"code": "AI_CLEAR_ARM_NOT_ASSIGNED"})
        if arms is not None and (note.cause is None or note.basis is None):
            raise HTTPException(422, detail={"code": "AI_CLEAR_CAUSE_REQUIRED"})
        try:
            await asyncio.to_thread(store.clear, source_id, incident_id, note.note, principal.principal_id, note.cause,
                                    note.basis, arms is not None,
                                    None if note.remeasured is None else note.remeasured.model_dump(exclude_none=True),
                                    service.arm_board(source_id),
                                    note.recovery if arms is not None else None)
        except KeyError:
            raise HTTPException(404, detail={"code": "ARM_INCIDENT_UNKNOWN"}) from None
        except ValueError:
            raise HTTPException(409, detail={"code": "ARM_INCIDENT_ALREADY_CLEARED"}) from None
        except MachineClearRefused as refused:
            raise HTTPException(403, detail={"code": refused.code, "message": str(refused)}) from None
        return (await asyncio.to_thread(store.hold, source_id)).model_dump()

    @app.post(base + "/arms/{source_id}/incidents/{incident_id}/evidence", tags=["workcell-observations"])
    async def evidence(source_id: str, incident_id: str, request: Request, response: Response,
                       token: str | None = Header(None, alias="X-Workcell-Observation-Token")):
        response.headers["Cache-Control"] = "no-store"
        source(source_id, token)
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > EVIDENCE_BODY_BYTES:
                raise HTTPException(413, detail={"code": "WORKCELL_OBSERVATION_TOO_LARGE"})
            data.extend(chunk)
        try:
            parsed = ArmIncidentEvidenceFrame.model_validate_json(data)
        except ValidationError:
            raise HTTPException(422, detail={"code": "INVALID_ARM_INCIDENT_EVIDENCE"}) from None
        try:
            seq = await asyncio.to_thread(store.add_evidence, source_id, incident_id, parsed)
        except KeyError:
            raise HTTPException(404, detail={"code": "ARM_INCIDENT_UNKNOWN"}) from None
        except OverflowError:
            raise HTTPException(409, detail={"code": "ARM_INCIDENT_EVIDENCE_FULL"}) from None
        return {"incident_id": incident_id, "seq": seq}

    @app.get(base + "/arms/{source_id}/incidents/{incident_id}/evidence/{seq}", tags=["workcell-observations"])
    def evidence_frame(source_id: str, incident_id: str, seq: int, _principal=Depends(require_viewer)):
        jpeg = store.evidence_frame(source_id, incident_id, seq)
        if jpeg is None:
            raise HTTPException(404, detail={"code": "ARM_INCIDENT_FRAME_UNKNOWN"})
        return RawResponse(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.get(base + "/arms/{source_id}/incidents/{incident_id}/frames/{role}", tags=["workcell-observations"])
    def frame(source_id: str, incident_id: str, role: str, _principal=Depends(require_viewer)):
        jpeg = store.frame(source_id, incident_id, role) if role in ROLES else None
        if jpeg is None:
            raise HTTPException(404, detail={"code": "ARM_INCIDENT_FRAME_UNKNOWN"})
        return RawResponse(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    if authorize is None:
        return

    def require_ai_observer(principal=Depends(authorize)):
        if principal.role != "ai_observer":
            raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "ai_observer role required"})
        return principal

    @app.get(base + "/arm-incidents/unexplained", tags=["workcell-observations"])
    def unexplained(response: Response, _principal=Depends(require_ai_observer)):
        response.headers["Cache-Control"] = "no-store"
        return {"incidents": store.unexplained()}

    @app.get(base + "/arm-incidents/labelled", tags=["workcell-observations"])
    def labelled(response: Response, _principal=Depends(require_ai_observer)):
        # learning reads what people cleared with a cause; the model PC pulls it through the same observer seat (D-516)
        response.headers["Cache-Control"] = "no-store"
        return {"incidents": store.labelled()}

    @app.post(base + "/arms/{source_id}/incidents/{incident_id}/explanation", tags=["workcell-observations"])
    async def explanation(source_id: str, incident_id: str, request: Request, response: Response,
                          _principal=Depends(require_ai_observer)):
        response.headers["Cache-Control"] = "no-store"
        try:
            parsed = ArmIncidentExplanation.model_validate(await bounded_json(request))
        except ValidationError:
            raise HTTPException(422, detail={"code": "INVALID_ARM_INCIDENT_EXPLANATION"}) from None
        try:
            await asyncio.to_thread(store.explain, source_id, incident_id, parsed)
        except KeyError:
            raise HTTPException(404, detail={"code": "ARM_INCIDENT_UNKNOWN"}) from None
        except ValueError:
            raise HTTPException(409, detail={"code": "ARM_INCIDENT_NOT_OPEN_FOR_EXPLANATION"}) from None
        return {"incident_id": incident_id, "explained": True}
