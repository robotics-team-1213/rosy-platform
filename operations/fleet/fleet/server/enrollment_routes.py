"""Site API routes for robot enrollment (D-361 6): writes need a named operator."""

from __future__ import annotations

from typing import Callable, Optional

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from fleet.hub.hub import HubError
from fleet.server.enrollment import EnrollmentError, EnrollmentService


class MoveRequest(BaseModel):
    """Moving to a new address re-pairs there with the robot's screen code (D-361 3)."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=32)


class EnrollRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=32)
    discovery_name: Optional[str] = Field(default=None, max_length=96)
    address: Optional[str] = Field(default=None, max_length=64)


def _refusal(exc: Exception) -> HTTPException:
    if isinstance(exc, EnrollmentError):
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after is not None else None
        return HTTPException(status_code=exc.status, detail=exc.body(), headers=headers)
    if isinstance(exc, HubError):
        status = 404 if exc.code == "UNKNOWN_ROBOT" else 409
        detail = {"code": exc.code, "message": str(exc)}
        task_ids = getattr(exc, "task_ids", None)
        if task_ids:
            detail["task_ids"] = task_ids
        return HTTPException(status_code=status, detail=detail)
    raise exc


def install_enrollment_routes(app: FastAPI, enrollment: EnrollmentService, *,
                              require_viewer: Callable, require_operator: Callable,
                              named_identity: bool) -> None:
    def named_operator(action: str) -> Callable:
        def guard(principal=Depends(require_operator)):
            if not named_identity:
                raise HTTPException(status_code=403, detail={
                    "code": "OPERATOR_IDENTITY_REQUIRED",
                    "message": f"{action} requires a configured named operator credential",
                })
            return principal
        return guard

    enroll_guard = named_operator("robot enrollment")
    move_guard = named_operator("moving an enrolled robot to a new address")
    unenroll_guard = named_operator("robot unenrollment")

    @app.get("/api/fleet/enrollment/robots", dependencies=[Depends(require_viewer)],
             tags=["fleet-enrollment"])
    def enrollment_readback() -> dict:
        return enrollment.listing()

    @app.post("/api/fleet/enrollment/robots", status_code=201, tags=["fleet-enrollment"])
    async def enrollment_create(body: EnrollRequest, principal=Depends(enroll_guard)) -> dict:
        try:
            return await enrollment.enroll(code=body.code, principal_id=principal.principal_id,
                                           discovery_name=body.discovery_name,
                                           address=body.address)
        except (EnrollmentError, HubError) as exc:
            raise _refusal(exc) from None

    @app.post("/api/fleet/enrollment/robots/{robot_id}/move-address", tags=["fleet-enrollment"])
    async def enrollment_move(robot_id: str, body: MoveRequest,
                              principal=Depends(move_guard)) -> dict:
        try:
            result = await enrollment.move_address(robot_id, code=body.code,
                                                   principal_id=principal.principal_id)
        except (EnrollmentError, HubError) as exc:
            raise _refusal(exc) from None
        return result

    hub_guard = named_operator("linking a robot to the site hub")

    # D-555: one hub credential per enrolled robot, delivered only over a TLS-bound enrollment.
    @app.post("/api/fleet/robots/{robot_id}/hub-link", tags=["fleet-enrollment"])
    async def hub_link_create(robot_id: str, principal=Depends(hub_guard)) -> dict:
        try:
            return await enrollment.link_hub(robot_id, principal_id=principal.principal_id)
        except (EnrollmentError, HubError) as exc:
            raise _refusal(exc) from None

    @app.delete("/api/fleet/robots/{robot_id}/hub-link", tags=["fleet-enrollment"])
    async def hub_link_delete(robot_id: str, principal=Depends(hub_guard)) -> dict:
        try:
            return await enrollment.unlink_hub(robot_id, principal_id=principal.principal_id)
        except (EnrollmentError, HubError) as exc:
            raise _refusal(exc) from None

    @app.delete("/api/fleet/enrollment/robots/{robot_id}", tags=["fleet-enrollment"])
    async def enrollment_delete(robot_id: str, principal=Depends(unenroll_guard)) -> dict:
        try:
            return await enrollment.unenroll(robot_id, principal_id=principal.principal_id)
        except (EnrollmentError, HubError) as exc:
            raise _refusal(exc) from None
