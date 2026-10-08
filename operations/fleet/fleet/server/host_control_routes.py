"""Service Control routes. D-524.

The route validates a closed action and, when a helper is configured, asks that
helper to schedule a reboot or to stop or restart one allowlisted unit.
"""

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from fleet.host_control import HostControlError, catalogue, decide

STATUS = {
    "CONFIRMATION_REQUIRED": 400,
    "UNKNOWN_ACTION": 400,
    "UNIT_NOT_ALLOWED": 400,
    "UNKNOWN_HOST": 404,
    "HOST_NOT_LOCAL": 409,
    "HOST_HELPER_UNAVAILABLE": 503,
    "HOST_HELPER_FAILED": 502,
    "HELPER_REFUSED": 503,
}


class HostControlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action: str = Field(min_length=1, max_length=32)
    unit: str | None = Field(default=None, max_length=80)
    operator_confirmed: StrictBool

    @field_validator("operator_confirmed")
    @classmethod
    def require_confirmation(cls, value):
        if value is not True:
            raise ValueError("explicit operator confirmation required")
        return value


def _fail(code: str) -> HTTPException:
    return HTTPException(status_code=STATUS.get(code, 400),
                         detail={"code": code})


def install_host_control_routes(app, *, require_operator, helper) -> None:
    @app.get("/api/fleet/hosts", tags=["fleet"])
    def host_catalogue(principal=Depends(require_operator)):
        body = catalogue()
        body["requested_by"] = principal.principal_id
        return body

    @app.post("/api/fleet/hosts/{host_id}/control", tags=["fleet"])
    def control_host(host_id: str, body: HostControlRequest,
                     principal=Depends(require_operator)):
        try:
            command = decide(host_id, body.action, body.unit,
                             confirmed=body.operator_confirmed)
        except HostControlError as exc:
            raise _fail(exc.code) from None
        result = helper.run(command["host"], command["argv"])
        if not result.get("ok"):
            raise _fail(result.get("code", "HOST_HELPER_FAILED"))
        return {
            "host": command["host"],
            "action": command["action"],
            "unit": command["unit"],
            "requested_by": principal.principal_id,
            "code": result["code"],
            "output": result.get("output", ""),
        }
