"""D-1024 3 / D-793 2: named-operator routes for the learned-policy approval window. Proposer != approver is enforced
by authenticated principal ids, not by names in the body. No route starts motion; leases come from PolicyApprovals.tick
only when a delivery port is installed."""

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field


class PolicyApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    workcell_id: str = Field(min_length=1, max_length=128)
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    rig_revision: str = Field(min_length=1, max_length=128)
    calibration_revision: str = Field(min_length=1, max_length=128)
    scope: str = Field(min_length=1, max_length=256)
    window_minutes: int = Field(default=15, ge=1, le=30, strict=True)


def install_policy_approval_routes(app, *, approvals, configured_omx, require_viewer, require_named_operator):
    def call(operation, *args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except KeyError:
            raise HTTPException(status_code=404, detail={"code": "APPROVAL_NOT_FOUND"}) from None
        except PermissionError:
            raise HTTPException(status_code=403, detail={"code": "PROPOSER_APPROVER_MUST_DIFFER"}) from None
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={"code": "APPROVAL_STATE_CONFLICT", "reason": str(exc)}) from None

    @app.get("/api/fleet/policy-approvals", tags=["fleet"])
    def list_policy_approvals(principal=Depends(require_viewer)):
        return {"approvals": approvals.listing(), "lease_delivery_connected": approvals.delivery_connected}

    @app.post("/api/fleet/policy-approvals", tags=["fleet"], status_code=201)
    def propose_policy_approval(body: PolicyApprovalRequest, principal=Depends(require_named_operator)):
        if body.workcell_id not in configured_omx:
            raise HTTPException(status_code=404, detail={"code": "WORKCELL_NOT_FOUND"})
        return call(approvals.propose, workcell_id=body.workcell_id, proposer=principal.principal_id,
                    policy_digest=body.policy_digest, rig_revision=body.rig_revision,
                    calibration_revision=body.calibration_revision, scope=body.scope,
                    window_s=body.window_minutes * 60)

    @app.post("/api/fleet/policy-approvals/{approval_id}/approve", tags=["fleet"])
    def approve_policy_approval(approval_id: str, principal=Depends(require_named_operator)):
        return call(approvals.approve, approval_id, principal.principal_id)

    @app.post("/api/fleet/policy-approvals/{approval_id}/abort", tags=["fleet"])
    def abort_policy_approval(approval_id: str, principal=Depends(require_named_operator)):
        return call(approvals.abort, approval_id, principal.principal_id)
