"""The operator's way out of a named-stop custody claim that CORE cannot prove stopped (dead robot, lost zero write)."""

from __future__ import annotations

from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from fleet.server.goal_lease import CustodyReleaseRefused


class ReleaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reservation_id: str = Field(min_length=1, max_length=64)
    operator_saw_robot_standing_still: Literal[True]
    reason: str = Field(min_length=3, max_length=500)


def install_named_stop_custody_route(app, *, console, require_named_operator, record_event) -> None:
    """`POST /api/fleet/robots/{robot_id}/named-stop-custody/release`: named operator, audited like the step and pin routes."""

    @app.post("/api/fleet/robots/{robot_id}/named-stop-custody/release", tags=["fleet"])
    async def release_named_stop_custody(robot_id: str, body: ReleaseRequest,
                                         principal=Depends(require_named_operator)) -> dict:
        def audit(stop):
            record_event("named_stop_custody_release", principal.principal_id, {
                "robot_id": robot_id, "reservation_id": body.reservation_id, "reason": body.reason,
                "operator_saw_robot_standing_still": True, "stop": stop})

        try:  # console.cancel is the operator's cancel: it also ends the robot's trip (trip_guard.py guarded_cancel)
            return await console.goal_leases.release_by_operator(
                robot_id, body.reservation_id, principal.principal_id, body.reason, stop=console.cancel, audit=audit)
        except CustodyReleaseRefused as exc:
            status = 503 if exc.code == "AUDIT_UNAVAILABLE" else 409
            raise HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)}) from exc
