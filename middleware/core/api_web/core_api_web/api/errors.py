"""core_api_web.api.errors — ERR-101 표준 에러 응답 + 도메인 예외 매핑."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from core_common.capability import CapabilityError
from core_common.protocol.connect_reason import body as reason_body
from core_features.navigation.manager import NavigationError
from core_features.waypoints.manager import WaypointError


class ApiError(Exception):
    def __init__(self, code: str, http_status: int = 400, message: str = "",
                 detail: Optional[dict] = None) -> None:
        super().__init__(message or code)
        self.code = code
        self.http_status = http_status
        self.message = message or code
        self.detail = detail


class ReasonError(HTTPException):
    """D-535: a connection or pairing refusal. The body keeps the route's older ``detail``
    beside the ERR-101 ``error`` whose code, message and action come from connect_reason.
    An app without the handler below still answers the older ``{"detail": ...}``."""

    def __init__(self, http_status: int, code: str, legacy: Any, detail: Optional[dict] = None,
                 headers: Optional[dict] = None) -> None:
        super().__init__(http_status, legacy, headers)
        self.http_status, self.code, self.legacy, self.reason_detail = http_status, code, legacy, detail


def error_body(code: str, message: str, detail: Any = None) -> dict:
    return {"error": {"code": code, "message": message, "detail": detail}}


_HTTP_BY_CODE = {
    "VALIDATION_ERROR": 400,
    "UNAUTHORIZED": 401,
    "FORBIDDEN": 403,
    "NOT_FOUND": 404,
    "MODE_CONFLICT": 409,
    "EMERGENCY_ACTIVE": 409,
    "NAVIGATION_ACTIVE": 409,
    # D-550 10: a lease renewal for a goal that is no longer the active leased goal.
    "GOAL_LEASE_NOT_ACTIVE": 409,
    "WAYPOINT_EXISTS": 409,
    "MAP_MISMATCH": 409,
    "MAPPING_ACTIVE": 409,
    "DOCKING_ACTIVE": 409,
    "IDEMPOTENCY_CONFLICT": 409,
    "IDENTITY_LOCKED": 409,
    "CAPABILITY_WITHHELD": 409,
    # D-321 addendum: another token holds the calibration session lease.
    "CALIBRATION_ACTIVE": 409,
    # D-407: a stuck answer for another (or no) stuck, or one the robot refuses now.
    "STUCK_ID_MISMATCH": 409,
    "STUCK_DECISION_REFUSED": 409,
    "CAPABILITY_NOT_SUPPORTED": 501,
    "ROBOT_OFFLINE": 503,
    "HARDWARE_NOT_READY": 503,
    # D-247: CORE could not hand rosy-hw-probe a refresh request (not a D-58 hardware gate).
    "HW_PROBE_UNAVAILABLE": 503,
    # D-247 6: a buzzer/lamp test inside the 10 s cool-down, or its request / the
    # person's answer could not be written. Not D-58 hardware gates either.
    "HW_TEST_COOLDOWN": 429,
    "HW_TEST_UNAVAILABLE": 503,
    "HW_CONFIRM_UNAVAILABLE": 503,
    # D-247 6: an answer with no finished (done, < 5 min) test of that device to judge.
    "HW_CONFIRM_NO_TEST": 409,
    # D-418: SSH access. A key, label, days or minutes off the contract; a label or key
    # already enrolled, or 32 managed keys; an unknown label; the root helper did not
    # answer in 10 s or could not apply it.
    "SSH_INVALID": 422,
    "SSH_LABEL_EXISTS": 409,
    "SSH_KEY_EXISTS": 409,
    "SSH_KEYS_FULL": 409,
    "SSH_KEY_NOT_FOUND": 404,
    "SSH_ACCESS_UNAVAILABLE": 503,
    # D-411 A: Pilot robot recording (core_common.domain.pilot_recording, v1.recordings).
    "RECORDING_BUSY": 409,
    "RECORDING_NOT_ACTIVE": 409,
    "ROBOT_MOVING": 409,
    "RECORDING_NOT_FOUND": 404,
    "RECORDING_QUOTA_FULL": 507,
    "RECORDING_DISK_FULL": 507,
    "RECORDER_UNAVAILABLE": 503,
    "COMMAND_TIMEOUT": 504,
    "INTERNAL_ERROR": 500,
}


def register_exception_handlers(app) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return JSONResponse(status_code=exc.http_status,
                            content=error_body(exc.code, exc.message, exc.detail))

    @app.exception_handler(ReasonError)
    async def _reason_error(_: Request, exc: ReasonError):
        return JSONResponse(status_code=exc.http_status,
                            content={"detail": exc.legacy, **reason_body(exc.code, exc.reason_detail)},
                            headers={"Cache-Control": "no-store", **(exc.headers or {})})

    @app.exception_handler(NavigationError)
    async def _nav_error(_: Request, exc: NavigationError):
        status = _HTTP_BY_CODE.get(exc.code, 400)
        return JSONResponse(status_code=status, content=error_body(exc.code, str(exc)))

    @app.exception_handler(WaypointError)
    async def _wp_error(_: Request, exc: WaypointError):
        status = _HTTP_BY_CODE.get(exc.code, 400)
        return JSONResponse(status_code=status, content=error_body(exc.code, str(exc)))

    @app.exception_handler(CapabilityError)
    async def _cap_error(_: Request, exc: CapabilityError):
        detail = {"capability": exc.feature}
        if exc.concept_id:
            detail["concept_id"] = exc.concept_id
        return JSONResponse(
            status_code=501,
            content=error_body("CAPABILITY_NOT_SUPPORTED", str(exc), detail),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        return JSONResponse(status_code=400,
                            content=error_body("VALIDATION_ERROR", "invalid request", exc.errors()))
