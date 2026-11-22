"""The operator's way out of a named-stop custody claim that CORE cannot prove stopped (or when isolated)."""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from fleet.server.goal_lease import CustodyReleaseRefused


class PhysicalIsolation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: Literal["power_off", "hardware_estop_latched", "removed_from_site"]
    robot_physically_isolated: Literal[True]
    evidence: str = Field(min_length=3, max_length=500)

    @field_validator("robot_physically_isolated", mode="before")
    @classmethod
    def _require_bool_true(cls, value):
        if value is not True:
            raise ValueError("robot_physically_isolated must be boolean true")
        return value

    @field_validator("evidence")
    @classmethod
    def _strip_evidence(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 3:
            raise ValueError("evidence must contain at least 3 non-whitespace characters")
        return stripped


class ReleaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reservation_id: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=3, max_length=500)
    physical_isolation: Optional[PhysicalIsolation] = None

    @field_validator("reason")
    @classmethod
    def _strip_reason(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 3:
            raise ValueError("reason must contain at least 3 non-whitespace characters")
        return stripped


def install_named_stop_custody_route(app, *, console, require_named_operator, record_event) -> None:
    """`POST /api/fleet/robots/{robot_id}/named-stop-custody/release`: named operator, audited, fail-closed."""

    @app.post("/api/fleet/robots/{robot_id}/named-stop-custody/release", tags=["fleet"])
    async def release_named_stop_custody(robot_id: str, body: ReleaseRequest,
                                         principal=Depends(require_named_operator)) -> dict:
        def audit(stop, proof):
            detail = {
                "robot_id": robot_id, "reservation_id": body.reservation_id, "reason": body.reason,
                "stop": stop, "proof": proof,
            }
            if body.physical_isolation is not None:
                detail["physical_isolation"] = body.physical_isolation.model_dump(mode="json")
            record_event("named_stop_custody_release", principal.principal_id, detail)

        try:  # console.cancel is the operator's cancel: it also ends the robot's trip (trip_guard.py guarded_cancel)
            return await console.goal_leases.release_by_operator(
                robot_id, body.reservation_id, principal.principal_id, body.reason,
                stop=console.cancel, audit=audit, physical_isolation=body.physical_isolation)
        except CustodyReleaseRefused as exc:
            status = 503 if exc.code == "AUDIT_UNAVAILABLE" else 409
            raise HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)}) from exc
