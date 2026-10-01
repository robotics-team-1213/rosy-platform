"""core_api_web.api.v1.localization — D-395 P2-4 Fleet-assisted localization routes.

Contract: docs/plans/2026-10-01-d395-phase2-interfaces.md §2, API Ref §5.3/§7.9.
CORE relays; the robot's sensing node decides. Every write here is fenced by the
D-321 calibration lease (423 on these routes) and needs `LOCALIZE_ASSIST`.
The legacy `POST /localization/initialpose` stays in navigation.py.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from core_api_web.api.deps import AuthContext, CoreServicesLike, get_services
from core_api_web.api.errors import ApiError
from core_api_web.api.grants import LOCALIZE_ASSIST, NAVIGATE, check_grant, require_grant
from core_common.protocol.localization import DecisionSource, LocalizationDecision

localization_router = APIRouter(prefix="/api/v1/localization", tags=["localization"])

assist = require_grant(LOCALIZE_ASSIST)


class SuspectRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=64)


def reporting_assist(svc: CoreServicesLike):
    """The robot's D-395 node, or 501 for a robot that predates it."""
    loc = getattr(svc, "localization", None)
    if loc is None or not loc.reporting:
        raise ApiError("CAPABILITY_NOT_SUPPORTED", 501,
                       "this robot does not report D-395 localization state")
    return loc


def _lease(svc: CoreServicesLike, auth: AuthContext, action: str) -> None:
    """D-321 addendum, answered 423 on the D-395 routes (contract §2)."""
    session = svc.calibration.blocking(auth.token_id)
    if session is not None:
        raise ApiError("CALIBRATION_ACTIVE", 423,
                       f"{action} refused: calibration '{session['label']}' is in progress",
                       detail={"session": session})


def send_decision(loc, decision: LocalizationDecision) -> None:
    try:
        loc.decide(decision)
    except RuntimeError as exc:
        raise ApiError("CAPABILITY_NOT_SUPPORTED", 501, str(exc)) from exc


@localization_router.get("/candidates")
def candidates(_: AuthContext = Depends(assist), svc: CoreServicesLike = Depends(get_services)):
    loc = getattr(svc, "localization", None)
    report = loc.candidates() if loc is not None else None
    if report is None:
        raise ApiError("NO_CANDIDATES", 404, "the robot is not in CANDIDATES")
    return report.model_dump(mode="json")


@localization_router.post("/decision", status_code=202)
def decision(body: Any = Body(...), auth: AuthContext = Depends(assist),
             svc: CoreServicesLike = Depends(get_services)):
    try:
        parsed = LocalizationDecision.model_validate(body)
    except ValidationError as exc:
        raise ApiError("VALIDATION_ERROR", 400, "invalid localization decision",
                       detail={"errors": exc.errors(include_url=False, include_context=False,
                                                    include_input=False)}) from exc
    if parsed.source is DecisionSource.HUMAN:
        check_grant(auth, NAVIGATE)
    _lease(svc, auth, "localization decision")
    loc = reporting_assist(svc)
    if loc.is_stale(parsed):
        raise ApiError("STALE_REQUEST", 409, f"request {parsed.request_id} is not the open one",
                       detail={"request_id": parsed.request_id})
    send_decision(loc, parsed)
    if parsed.source is DecisionSource.HUMAN:
        svc.events.publish("localization.initialpose", source=f"api:{auth.role}", data={
            "x": parsed.pose.x, "y": parsed.pose.y, "yaw": parsed.pose.yaw, "source": "human"})
    return JSONResponse(status_code=202, content={"request_id": parsed.request_id})


@localization_router.post("/suspect", status_code=202)
def suspect(body: SuspectRequest, auth: AuthContext = Depends(assist),
            svc: CoreServicesLike = Depends(get_services)):
    _lease(svc, auth, "localization suspect")
    loc = reporting_assist(svc)
    try:
        loc.suspect(body.reason)
    except RuntimeError as exc:
        raise ApiError("CAPABILITY_NOT_SUPPORTED", 501, str(exc)) from exc
    return JSONResponse(status_code=202, content={"accepted": True})
