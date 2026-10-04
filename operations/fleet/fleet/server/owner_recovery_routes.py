"""Named operator recovery of OMX owner HOLD, without dispatch or stop rearm."""

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator


class OwnerRecoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    operator_confirmed: StrictBool
    observed_sequence: StrictInt = Field(ge=0)
    expected_generation: StrictInt = Field(ge=0)

    @field_validator("operator_confirmed")
    @classmethod
    def require_confirmation(cls, value):
        if value is not True:
            raise ValueError("explicit operator confirmation required")
        return value


def install_owner_recovery_routes(app, *, configured_omx, stop_transport, task_service,
                                  require_viewer, require_named_operator):
    def target(workcell_id):
        if workcell_id not in configured_omx:
            raise HTTPException(status_code=404, detail={"code": "WORKCELL_NOT_FOUND"})
        if stop_transport is None:
            raise HTTPException(status_code=503, detail={"code": "OWNER_TRANSPORT_UNAVAILABLE"})
        return configured_omx[workcell_id]

    @app.get("/api/fleet/workcells/{workcell_id}/owner", tags=["fleet"])
    def owner_state(workcell_id: str, principal=Depends(require_viewer)):
        result = stop_transport.owner_state(workcell_id=workcell_id, instance_id=target(workcell_id))
        if result.get("status") != 200:
            raise HTTPException(status_code=503, detail={"code": "OWNER_READBACK_UNAVAILABLE"})
        return result

    @app.post("/api/fleet/workcells/{workcell_id}/owner/recover", tags=["fleet"])
    def recover_owner(workcell_id: str, body: OwnerRecoveryRequest,
                      principal=Depends(require_named_operator)):
        instance_id = target(workcell_id)
        if task_service is None:
            raise HTTPException(status_code=503, detail={"code": "AUDIT_STORAGE_UNAVAILABLE"})
        control = task_service.store.dispatch_control()
        if (not control["dispatch_enabled"] or control["unresolved_actions"] != 0
                or control["generation"] != body.expected_generation):
            raise HTTPException(status_code=409, detail={"code": "RECOVERY_FENCE_CLOSED"})
        result = stop_transport.recover_owner(
            workcell_id=workcell_id, instance_id=instance_id, actor_id=principal.principal_id,
            authority_epoch=control["authority_epoch"], dispatch_generation=control["generation"],
            operator_confirmed=True, observed_sequence=body.observed_sequence,
        )
        if result.get("status") != 200:
            raise HTTPException(status_code=result.get("status", 503), detail=result)
        return result
