"""D-721 Amendment (v1.372): the person request a robot holds for its dashboard and its face.

`PUT /person-request` puts Fleet's request on this robot (one at a time, with an expiry); `DELETE` is the owner's
end of it; `GET` shows what is held. Nothing here carries motion authority: it sets no mode, releases no stop and
satisfies no safety check. An answer is a person's statement recorded in Fleet, never a command to CORE.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from core_api_web.api.deps import AuthContext, CoreServicesLike, get_services
from core_api_web.api.errors import ApiError
from core_api_web.api.v1.common import operator, viewer
from core_common.protocol.person_request import PersonRequestAnswerBody, PersonRequestBody

person_request_router = APIRouter(prefix="/api/v1/person-request", tags=["person-request"])


@person_request_router.get("")
def read_person_request(auth: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    # Only a person logged in with an account may answer here; a machine or shared token only reads.
    return {"person_request": svc.person_request.view(), "can_answer": auth.source == "account", "motion": False}


@person_request_router.put("")
def hold_person_request(body: PersonRequestBody, auth: AuthContext = Depends(operator),
                        svc: CoreServicesLike = Depends(get_services)):
    try:
        view, renewed = svc.person_request.put(
            request_id=body.request_id, kind=body.kind, text=body.text, why=body.why, ttl_s=body.ttl_s,
            owner_id=auth.token_id)
    except PermissionError as exc:
        raise ApiError("FORBIDDEN", 403, str(exc)) from exc
    return {"person_request": view, "renewed": renewed, "motion": False}


@person_request_router.delete("/{request_id}")
def end_person_request(request_id: str, auth: AuthContext = Depends(operator),
                       svc: CoreServicesLike = Depends(get_services)):
    try:
        return {"cleared": svc.person_request.clear(request_id, auth.token_id), "motion": False}
    except PermissionError as exc:
        raise ApiError("FORBIDDEN", 403, str(exc)) from exc


@person_request_router.post("/{request_id}/answer")
def answer_person_request(request_id: str, body: PersonRequestAnswerBody, auth: AuthContext = Depends(viewer),
                          svc: CoreServicesLike = Depends(get_services)):
    """A logged-in person's statement, held for Fleet to read back and record. It moves nothing."""
    if auth.source != "account":
        raise ApiError("PERSON_LOGIN_REQUIRED", 403, "log in with your account to answer")
    if not svc.person_request.answer(request_id, body.answer, auth.principal_ref):
        raise ApiError("PERSON_REQUEST_NOT_HELD", 409, "this request is not on this robot")
    return {"person_request": svc.person_request.view(), "motion": False}
