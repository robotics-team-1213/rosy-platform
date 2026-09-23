"""core_api_web.api.errors — ERR-101 표준 에러 응답 + 도메인 예외 매핑."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from core_common.capability import CapabilityError
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
    "WAYPOINT_EXISTS": 409,
    "MAP_MISMATCH": 409,
    "MAPPING_ACTIVE": 409,
    "DOCKING_ACTIVE": 409,
    "IDEMPOTENCY_CONFLICT": 409,
    "IDENTITY_LOCKED": 409,
    "CAPABILITY_NOT_SUPPORTED": 501,
    "ROBOT_OFFLINE": 503,
    "HARDWARE_NOT_READY": 503,
    "COMMAND_TIMEOUT": 504,
    "INTERNAL_ERROR": 500,
}


def register_exception_handlers(app) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return JSONResponse(status_code=exc.http_status,
                            content=error_body(exc.code, exc.message, exc.detail))

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
