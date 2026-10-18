"""D-793 learned-policy governance routes: read for viewers, decisions for policy administrators.

Stage, window, confirmation and incident decisions need `fleet.policy`. Reporting an incident or
opening a confirmation needs a named operator, so whoever sees a problem can stop it. Leases go
to an operator or service caller. No route here sends a command to a device.
"""

from typing import Any, Literal, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator

from fleet.server.policy_governance import LEASE_DEFAULT_MS, GovernanceError, PolicyGovernanceStore

_TEXT = dict(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@/-]+$")


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _Confirmed(_Body):
    operator_confirmed: StrictBool

    @field_validator("operator_confirmed")
    @classmethod
    def require_confirmation(cls, value):
        if value is not True:
            raise ValueError("explicit operator confirmation required")
        return value


class StageProposal(_Confirmed):
    policy_revision: str = Field(**_TEXT)
    to_stage: Literal["L0", "L1", "L2", "L3", "LIMITED"]
    rig_revision: str = Field(**_TEXT)
    calibration_revision: str = Field(**_TEXT)
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    note: str = Field(min_length=1, max_length=500)


class Decision(_Confirmed):
    approve: StrictBool


class WindowRequest(_Confirmed):
    policy_revision: str = Field(**_TEXT)
    kind: Literal["shadow", "supervised", "limited"]
    minutes: Optional[StrictInt] = None
    scope: str = Field(min_length=1, max_length=500)
    rig_revision: str = Field(**_TEXT)
    calibration_revision: str = Field(**_TEXT)


class Close(_Confirmed):
    reason: str = Field(min_length=1, max_length=500)


class LeaseRequest(_Body):
    episode_id: str = Field(**_TEXT)
    owner_session_id: str = Field(**_TEXT)
    duration_ms: StrictInt = LEASE_DEFAULT_MS
    lease_id: Optional[str] = Field(default=None, **_TEXT)


class ConfirmationRequest(_Confirmed):
    reason: str = Field(min_length=1, max_length=64)
    policy_revision: Optional[str] = Field(default=None, **_TEXT)
    evidence: dict[str, Any] = Field(default_factory=dict)


class Resolution(_Confirmed):
    resolution: Literal["resume", "abort", "send_to_learning"]
    note: str = Field(min_length=1, max_length=500)
    demote_to: Optional[Literal["L0", "L1", "L2", "L3"]] = None


class IncidentReport(_Confirmed):
    description: str = Field(min_length=1, max_length=1000)


class IncidentClear(_Confirmed):
    note: str = Field(min_length=1, max_length=1000)


def install_policy_governance_routes(app, *, store: PolicyGovernanceStore, configured_omx, stop_transport,
                                     require_viewer, require_named_operator):
    base = "/api/fleet/workcells/{workcell_id}/policy"

    def workcell(workcell_id):
        if workcell_id not in configured_omx:
            raise HTTPException(status_code=404, detail={"code": "WORKCELL_NOT_FOUND"})
        return workcell_id

    def policy_admin(principal):
        if not principal.permits_site("fleet.policy", {"policy-admin"}):
            raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "policy-admin only"})
        return principal

    def executor(principal):
        if not principal.permits_site("fleet.operate", {"operator", "service"}):
            raise HTTPException(status_code=403, detail={"code": "FORBIDDEN",
                                                         "message": "operator or service role required"})
        return principal

    def call(fn, **kwargs):
        try:
            return fn(**kwargs)
        except GovernanceError as exc:
            raise HTTPException(status_code=exc.status, detail={"code": exc.code}) from None

    def owned(workcell_id, table, key, value):
        if not store.belongs(table, key, value, workcell(workcell_id)):
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})

    @app.get(base, tags=["fleet-policy"])
    def policy_state(workcell_id: str, principal=Depends(require_viewer)) -> dict:
        return store.snapshot(workcell(workcell_id))

    @app.get("/api/fleet/policy-governance/workcells", tags=["fleet-policy"])
    def policy_workcells(principal=Depends(require_viewer)) -> dict:
        return {"workcells": sorted(configured_omx)}

    @app.post(base + "/proposals", tags=["fleet-policy"])
    def propose(workcell_id: str, body: StageProposal, principal=Depends(require_viewer)) -> dict:
        policy_admin(principal)
        return call(store.propose, workcell_id=workcell(workcell_id), policy_revision=body.policy_revision,
                    to_stage=body.to_stage, rig_revision=body.rig_revision,
                    calibration_revision=body.calibration_revision, evidence_sha256=body.evidence_sha256,
                    note=body.note, principal_id=principal.principal_id)

    @app.post(base + "/proposals/{proposal_id}/decision", tags=["fleet-policy"])
    def decide(workcell_id: str, proposal_id: str, body: Decision, principal=Depends(require_viewer)) -> dict:
        policy_admin(principal)
        owned(workcell_id, "proposals", "proposal_id", proposal_id)
        return call(store.decide, proposal_id=proposal_id, approve=body.approve,
                    principal_id=principal.principal_id)

    @app.post(base + "/windows", tags=["fleet-policy"])
    def request_window(workcell_id: str, body: WindowRequest, principal=Depends(require_viewer)) -> dict:
        policy_admin(principal)
        return call(store.request_window, workcell_id=workcell(workcell_id), policy_revision=body.policy_revision,
                    kind=body.kind, minutes=body.minutes, scope=body.scope, rig_revision=body.rig_revision,
                    calibration_revision=body.calibration_revision, principal_id=principal.principal_id)

    @app.post(base + "/windows/{window_id}/approve", tags=["fleet-policy"])
    def approve_window(workcell_id: str, window_id: str, body: _Confirmed, principal=Depends(require_viewer)):
        policy_admin(principal)
        owned(workcell_id, "windows", "window_id", window_id)
        return call(store.approve_window, window_id=window_id, principal_id=principal.principal_id)

    @app.post(base + "/windows/{window_id}/close", tags=["fleet-policy"])
    def close_window(workcell_id: str, window_id: str, body: Close, principal=Depends(require_named_operator)):
        # Any named operator may close a window: stopping never needs the stronger role.
        owned(workcell_id, "windows", "window_id", window_id)
        return call(store.close_window, window_id=window_id, reason=body.reason,
                    principal_id=principal.principal_id)

    @app.post(base + "/lease", tags=["fleet-policy"])
    def lease(workcell_id: str, body: LeaseRequest, principal=Depends(require_viewer)) -> dict:
        executor(principal)
        return call(store.issue_lease, workcell_id=workcell(workcell_id), episode_id=body.episode_id,
                    owner_session_id=body.owner_session_id, duration_ms=body.duration_ms, lease_id=body.lease_id)

    @app.post(base + "/confirmations", tags=["fleet-policy"])
    def open_confirmation(workcell_id: str, body: ConfirmationRequest,
                          principal=Depends(require_named_operator)) -> dict:
        return call(store.open_confirmation, workcell_id=workcell(workcell_id), reason=body.reason,
                    policy_revision=body.policy_revision, evidence=body.evidence,
                    principal_id=principal.principal_id)

    @app.post(base + "/confirmations/sync-owner", tags=["fleet-policy"])
    def sync_owner(workcell_id: str, principal=Depends(require_named_operator)) -> dict:
        instance_id = configured_omx.get(workcell(workcell_id))
        if stop_transport is None:
            raise HTTPException(status_code=503, detail={"code": "OWNER_TRANSPORT_UNAVAILABLE"})
        state = stop_transport.owner_state(workcell_id=workcell_id, instance_id=instance_id)
        if state.get("status") != 200:
            raise HTTPException(status_code=503, detail={"code": "OWNER_READBACK_UNAVAILABLE"})
        created = store.sync_owner_hold(workcell_id=workcell_id, owner_state=state,
                                        principal_id=principal.principal_id)
        return {"owner": state.get("owner"), "created": created}

    @app.post(base + "/confirmations/{confirmation_id}/resolve", tags=["fleet-policy"])
    def resolve(workcell_id: str, confirmation_id: str, body: Resolution, principal=Depends(require_viewer)):
        policy_admin(principal)
        owned(workcell_id, "confirmations", "confirmation_id", confirmation_id)
        return call(store.resolve_confirmation, confirmation_id=confirmation_id, resolution=body.resolution,
                    note=body.note, demote_to=body.demote_to, principal_id=principal.principal_id)

    @app.post(base + "/incidents", tags=["fleet-policy"])
    def report(workcell_id: str, body: IncidentReport, principal=Depends(require_named_operator)) -> dict:
        return call(store.report_incident, workcell_id=workcell(workcell_id), description=body.description,
                    principal_id=principal.principal_id)

    @app.post(base + "/incidents/{incident_id}/clear", tags=["fleet-policy"])
    def clear(workcell_id: str, incident_id: str, body: IncidentClear, principal=Depends(require_viewer)):
        policy_admin(principal)
        owned(workcell_id, "incidents", "incident_id", incident_id)
        return call(store.clear_incident, incident_id=incident_id, note=body.note,
                    principal_id=principal.principal_id)
