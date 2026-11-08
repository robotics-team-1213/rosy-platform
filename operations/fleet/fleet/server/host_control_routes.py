"""Service Control routes. D-524.

The route validates a closed action and asks that host's helper to schedule a
reboot or to stop or restart one allowlisted unit. Only a named operator may
call it; the durable `fleet_api_audit` row comes from authorization, and the
log lines below add the action and unit. D-991 keeps each request's action, unit and answer in the
device care history, which stays optional: a failed write never changes the answer.
"""

import logging
from pathlib import Path
import sqlite3

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

import time

from fleet.host_control import HostControlError, catalogue, decide, read_json_object, update_summary

# D-530. The site guard and the site's own drift check write these. Fleet only reads them.
GUARD_STATUS = Path("/var/lib/rosy-host-guard/status.json")
DRIFT_STATUS = Path("/var/lib/rosy-host-state/status.json")

_LOG = logging.getLogger(__name__)

STATUS = {
    "CONFIRMATION_REQUIRED": 400,
    "UNKNOWN_ACTION": 400,
    "UNIT_NOT_ALLOWED": 400,
    "ACTION_NOT_ALLOWED": 400,
    "UNKNOWN_HOST": 404,
    "REBOOT_ALREADY_SCHEDULED": 409,
    "NO_HOST_CONTROL_REBOOT": 409,
    "NO_STORAGE_SERVICE": 409,
    "ARM_SESSION_ACTIVE": 409,
    "HOST_JOBS_ACTIVE": 409,
    "HOST_HELPER_UNAVAILABLE": 503,
    "HOST_HELPER_FAILED": 502,
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


def _remember(app, host, action, unit, code, actor) -> None:
    care = getattr(app.state, "device_care", None)
    if care is None:
        return
    try:
        care.add_host_event(host, " ".join(filter(None, (action, unit, code))), actor=actor)
    except sqlite3.Error:
        _LOG.warning("host control history not written host=%s action=%s", host, action)


def _history(app, hosts) -> dict:
    care = getattr(app.state, "device_care", None)
    if care is None:
        return {}
    try:
        return {host: care.host_events(host) for host in hosts}
    except sqlite3.Error:
        _LOG.warning("host control history not read")
        return {}


def install_host_control_routes(app, *, require_operator, require_named_operator, helper, require_viewer=None) -> None:
    @app.get("/api/fleet/hosts", tags=["fleet"])
    def host_catalogue(principal=Depends(require_operator)):
        body = catalogue()
        body["guard"] = read_json_object(GUARD_STATUS)
        body["drift"] = read_json_object(DRIFT_STATUS)
        body["requested_by"] = principal.principal_id
        body["history"] = _history(app, [row["host"] for row in body["hosts"]])
        return body

    if require_viewer is not None:
        @app.get("/api/fleet/updates", tags=["fleet"])
        def update_overview(principal=Depends(require_viewer)):
            # D-871: every role sees each PC's update state and release; reasons stay in /api/fleet/hosts
            return update_summary(read_json_object(GUARD_STATUS), time.time())

    @app.post("/api/fleet/hosts/{host_id}/control", tags=["fleet"])
    def control_host(host_id: str, body: HostControlRequest,
                     principal=Depends(require_named_operator)):
        try:
            command = decide(host_id, body.action, body.unit,
                             confirmed=body.operator_confirmed)
        except HostControlError as exc:
            raise _fail(exc.code) from None
        fields = (command["host"], body.action, command["unit"], principal.principal_id)
        _LOG.warning("host control request host=%s action=%s unit=%s principal=%s", *fields)
        result = helper.run(command["host"], command["argv"])
        _LOG.warning("host control result host=%s action=%s unit=%s principal=%s code=%s",
                     *fields, result.get("code"))
        _remember(app, host_id, body.action, body.unit, result.get("code", "HOST_HELPER_FAILED"), principal.principal_id)
        if not result.get("ok"):
            raise _fail(result.get("code", "HOST_HELPER_FAILED"))
        return {
            "host": command["host"],
            "action": body.action,
            "unit": command["unit"],
            "requested_by": principal.principal_id,
            "code": result["code"],
            "output": result.get("output", ""),
        }
