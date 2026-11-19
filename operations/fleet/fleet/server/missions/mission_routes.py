"""Mission HTTP 표면 — 제안·판정·승인·진행 (mission/proposal/goal-evidence 저장소 소유).

`create_app` 이 검증만 하고, 경로는 이 모듈이 단다. 후보 판정(`resolve_candidate`)의
증명·민감 필드 거절·자원 클레임 검사가 여기 산다 — 판정은 라우트가 아니라 저장소와
같은 주인에게 붙어 있어야 한다(D-12, D-357/D-358).
"""

from __future__ import annotations

import time
from functools import partial
from typing import Optional

from fastapi import Depends, Header, HTTPException, Query

from core_common.protocol.schemas import (
    FleetWorkDecisionRequest as MissionAdmitRequest,
    MissionCursorExpiredError,
    MissionCursorResetError,
    MissionProgressEventPage,
    MissionProgressReadResponse,
    ResolvedTargetEvidence,  # noqa: F401
)
from fleet.server.goal_evidence_service import GoalEvidenceSubmissionError
from fleet.server.mission_routes_helpers import (
    MissionCandidateRequest,
    _mission_candidate_result,
    _mission_snapshot_response,
    _require_cell_role,
    _resolve_candidate,
    _stable_resolution,
    redact_cell_job,
)
from fleet.server.mission_store import MissionConflict
from fleet.server.proposal_store import ProposalConflict, ProposalRejected
from fleet.server.site_auth import SitePrincipal
from fleet.server.step_action_kinds import required_approval


def install_mission_routes(app, *, mission_service, proposal_store, goal_evidence_service,
                           mission_progress, candidate_resolver, cell_job_store,
                           cell_job_resolver, require_viewer, require_operator,
                           require_named_operator, require_proposer,
                           read_guard, operator_guard, policy_admission_core=None):
    if goal_evidence_service is not None:
        @app.post("/api/fleet/goal-evidence", tags=["fleet-goal-evidence"])
        def fleet_goal_evidence(
            body: dict,
            x_goal_evidence_token: Optional[str] = Header(default=None),
        ) -> dict:
            if not isinstance(body, dict) or set(body) != {"mission_id", "evidence"}:
                raise HTTPException(status_code=422, detail={
                    "code": "INVALID_GOAL_EVIDENCE_ENVELOPE",
                    "message": "body requires mission_id and evidence",
                })
            if not isinstance(body["mission_id"], str) or not isinstance(body["evidence"], dict):
                raise HTTPException(status_code=422, detail={
                    "code": "INVALID_GOAL_EVIDENCE_ENVELOPE",
                })
            if not x_goal_evidence_token:
                raise HTTPException(status_code=401, detail={"code": "PRODUCER_UNAUTHORIZED"})
            try:
                return goal_evidence_service.submit(
                    token=x_goal_evidence_token, mission_id=body["mission_id"],
                    raw_evidence=body["evidence"],
                )
            except GoalEvidenceSubmissionError as exc:
                raise HTTPException(status_code=exc.status_code, detail={
                    "code": exc.code, "message": str(exc),
                }) from exc

    @app.post("/api/fleet/proposals", dependencies=[Depends(require_proposer)], tags=["fleet-missions"])
    def fleet_proposal_create(body: MissionCandidateRequest,
                              principal: SitePrincipal = Depends(require_proposer)) -> dict:
        _require_cell_role(body.candidate, principal)
        try:
            saved = proposal_store.create(
                principal_id=principal.principal_id, request_key=body.request_key,
                workcell_id=body.workcell_id, instance_id=body.instance_id,
                candidate=body.candidate,
            )
        except ProposalConflict as exc:
            raise HTTPException(status_code=409, detail={"code": "REQUEST_CONFLICT",
                                                         "message": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "INVALID_CANDIDATE",
                                                         "message": str(exc)}) from exc
        proposal = saved["proposal"]
        return {"created": saved["created"], "proposal": {
            "proposal_id": proposal["proposal_id"], "request_key": proposal["request_key"],
            "state": proposal["state"], "candidate": proposal["candidate"],
            "reason": proposal["reason"], "expires_at": proposal["expires_at"],
        }, "physical_submission": "NOT_CONNECTED"}

    def cell_job_view(proposal: dict, principal: SitePrincipal) -> tuple[bool, dict | None]:
        """Whether this reader may see a Cell Job proposal, and its job as that reader sees it (None before resolve)."""
        job = cell_job_store.get(proposal["proposal_id"]) if cell_job_store is not None else None
        if proposal["principal_id"] == principal.principal_id:
            return True, job
        try:  # D-763 4 / rev 2 Q6: the work list's scope; another's PROPOSED job only to a named operator
            seen = principal.permits_site("fleet.operate", {"operator"}) and (
                job is not None and job["status"] != "PROPOSED" or bool(require_named_operator(principal)))
        except HTTPException:
            seen = False
        return seen, redact_cell_job(job, principal) if seen else job

    @app.get("/api/fleet/proposals/{proposal_id}", dependencies=read_guard,
             tags=["fleet-missions"])
    def fleet_proposal_read(proposal_id: str,
                            principal: SitePrincipal = Depends(require_viewer)) -> dict:
        proposal = proposal_store.get(proposal_id)
        if proposal is not None and proposal["candidate"].get("kind") == "cell_job":
            seen, job = cell_job_view(proposal, principal)  # the Cell Job detail's scope, not a second door
            if seen:
                return _mission_candidate_result(proposal, job)
        elif proposal is not None and proposal["principal_id"] == principal.principal_id:
            return _mission_candidate_result(proposal, mission_service.get(proposal_id))
        raise HTTPException(status_code=404, detail={"code": "PROPOSAL_NOT_FOUND"})

    @app.post("/api/fleet/proposals/{proposal_id}/resolve",
              dependencies=[Depends(require_proposer)],
              tags=["fleet-missions"])
    def fleet_proposal_resolve(proposal_id: str,
                               principal: SitePrincipal = Depends(require_proposer)) -> dict:
        proposal = proposal_store.get(proposal_id, principal_id=principal.principal_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail={"code": "PROPOSAL_NOT_FOUND"})
        cell_candidate = _require_cell_role(proposal["candidate"], principal)
        if proposal["state"] == "RESOLVED":
            if cell_candidate:
                return {"created": False, **_mission_candidate_result(
                    proposal, cell_job_store.get(proposal_id))}
            return {"created": False,
                    **_mission_candidate_result(proposal, mission_service.get(proposal_id))}
        if proposal["state"] != "PROPOSED":
            raise HTTPException(status_code=409, detail={
                "code": proposal["reason"] or "PROPOSAL_RESOLUTION_NOT_AVAILABLE",
            })
        try:
            if cell_candidate:
                if cell_job_resolver is None or cell_job_store is None:
                    raise HTTPException(status_code=503, detail={
                        "code": "CELL_JOB_COMPILER_UNAVAILABLE",
                    })
                submission = cell_job_resolver(
                    proposal["candidate"], workcell_id=proposal["workcell_id"],
                    instance_id=proposal["instance_id"],
                )
                resolved, mission, created = proposal_store.finalize_cell_job(
                    cell_job_store, proposal_id=proposal["proposal_id"],
                    principal_id=principal.principal_id, submission=submission,
                )
            else:
                if candidate_resolver is None:
                    raise HTTPException(status_code=503, detail={
                        "code": "MISSION_RESOLVER_UNAVAILABLE",
                    })
                resolution = _resolve_candidate(
                    candidate_resolver,
                    proposal["candidate"], workcell_id=proposal["workcell_id"],
                    instance_id=proposal["instance_id"], now=time.time(),
                )
                resolved, mission, created = proposal_store.finalize_resolution(
                    mission_service.store, proposal_id=proposal["proposal_id"],
                    principal_id=principal.principal_id, resolution=resolution,
                    mission_request=resolution,
                )
        except ProposalRejected as exc:
            rejected = proposal_store.set_resolution(
                proposal["proposal_id"], state="REJECTED", reason=exc.code,
            )
            raise HTTPException(status_code=409, detail={
                "code": exc.code, "proposal_id": rejected["proposal_id"],
            }) from exc
        except (MissionConflict, ProposalConflict) as exc:
            raise HTTPException(status_code=409, detail={"code": "MISSION_CONFLICT",
                                                         "message": str(exc)}) from exc
        return {"created": created, **_mission_candidate_result(resolved, mission)}

    @app.get("/api/fleet/cell-jobs/{mission_id}", dependencies=read_guard,
             tags=["fleet-cell-jobs"])
    def fleet_cell_job_read(mission_id: str,
                            principal: SitePrincipal = Depends(require_viewer)) -> dict:
        proposal = proposal_store.get(mission_id)
        if proposal is None or proposal["candidate"].get("kind") != "cell_job" or proposal["state"] != "RESOLVED":
            raise HTTPException(status_code=404, detail={"code": "CELL_JOB_NOT_FOUND"})
        seen, job = cell_job_view(proposal, principal)
        if not seen or job is None:
            raise HTTPException(status_code=404, detail={"code": "CELL_JOB_NOT_FOUND"})
        return {"proposal_id": mission_id, "proposal_state": proposal["state"], "job": job}

    @app.get("/api/fleet/missions/{mission_id}", dependencies=read_guard,
             response_model=MissionProgressReadResponse,
             tags=["fleet-missions"])
    def fleet_mission_read(mission_id: str,
                           principal: SitePrincipal = Depends(require_viewer)) -> dict:
        proposal = proposal_store.get(mission_id, principal_id=principal.principal_id)
        if proposal is None or proposal["state"] != "RESOLVED":
            raise HTTPException(status_code=404, detail={"code": "MISSION_NOT_FOUND"})
        snapshot = mission_progress.snapshot(mission_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail={"code": "MISSION_NOT_FOUND"})
        return _mission_snapshot_response(proposal, snapshot)

    @app.get("/api/fleet/missions/{mission_id}/events", dependencies=read_guard,
             response_model=MissionProgressEventPage,
             responses={
                 409: {"model": MissionCursorResetError},
                 410: {"model": MissionCursorExpiredError},
             }, tags=["fleet-missions"])
    def fleet_mission_events(
        mission_id: str,
        after_event_id: int = Query(default=0, ge=0),
        limit: int = Query(default=50, ge=1, le=200),
        principal: SitePrincipal = Depends(require_viewer),
    ) -> dict:
        proposal = proposal_store.get(mission_id, principal_id=principal.principal_id)
        if proposal is None or proposal["state"] != "RESOLVED":
            raise HTTPException(status_code=404, detail={"code": "MISSION_NOT_FOUND"})
        page = mission_progress.events(
            mission_id, after_event_id=after_event_id, limit=limit,
        )
        if page is None:
            raise HTTPException(status_code=404, detail={"code": "MISSION_NOT_FOUND"})
        if page["cursor_state"] != "OK":
            snapshot = mission_progress.snapshot(mission_id)
            status = 410 if page["cursor_state"] == "EXPIRED" else 409
            code = ("MISSION_CURSOR_EXPIRED" if status == 410 else
                    "MISSION_CURSOR_RESET_REQUIRED")
            raise HTTPException(status_code=status, detail={
                "code": code, "snapshot_restart_required": True,
                "cursor_floor": page["cursor_floor"],
                "snapshot": _mission_snapshot_response(proposal, snapshot),
            })
        contract_page = {key: value for key, value in page.items()
                         if key != "cursor_state"}
        return MissionProgressEventPage.model_validate(contract_page).model_dump(mode="json")

    def decidable(mission_id: str, principal: SitePrincipal) -> tuple[dict, str, dict]:
        """The resolved proposal a named operator may decide, its ledger row and registry approval."""
        proposal = proposal_store.get(mission_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail={"code": "MISSION_NOT_FOUND"})
        cell, own = (proposal["candidate"].get("kind") == "cell_job",
                     proposal["principal_id"] == principal.principal_id)
        if cell and cell_job_store is None:
            raise HTTPException(status_code=503, detail={"code": "CELL_JOB_JOURNAL_UNAVAILABLE"})
        record = (cell_job_store if cell else mission_service).get(mission_id)
        if proposal["state"] != "RESOLVED" or record is None:  # no ledger steps yet: as before
            raise HTTPException(status_code=409 if cell or own else 404, detail={
                "code": "PROPOSAL_NOT_RESOLVED" if cell or own else "MISSION_NOT_FOUND"})
        try:  # D-763 item 7: the strictest approval over the resolved ledger steps' kinds
            rule = required_approval([step["action_kind"] for step in record["steps"]] if cell
                                     else [record["action_kind"]])
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={"code": "APPROVAL_RULE_UNREGISTERED"}) from exc
        if rule == "proposer_only" and not own:
            raise HTTPException(status_code=404, detail={"code": "MISSION_NOT_FOUND"})
        return proposal, rule, record

    @app.post("/api/fleet/missions/{mission_id}/admit", dependencies=operator_guard,
              tags=["fleet-missions"])
    def fleet_mission_admit(mission_id: str, body: MissionAdmitRequest,
                            principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        proposal, rule, mission = decidable(mission_id, principal)
        if rule == "two_person" and proposal["principal_id"] == principal.principal_id:
            raise HTTPException(status_code=403, detail={"code": "CELL_JOB_APPROVER_MUST_DIFFER_FROM_PROPOSER"})
        cell = proposal["candidate"].get("kind") == "cell_job"
        try:
            if cell:
                if cell_job_resolver is None:
                    raise HTTPException(status_code=503, detail={"code": "CELL_JOB_COMPILER_UNAVAILABLE"})
                current = cell_job_resolver(proposal["candidate"], workcell_id=proposal["workcell_id"],
                                            instance_id=proposal["instance_id"])
                admit = cell_job_store.admit
            else:
                current = _resolve_candidate(candidate_resolver, proposal["candidate"], now=time.time(),
                                             workcell_id=mission["workcell_id"],
                                             instance_id=mission["instance_id"])
                admit = partial(mission_service.admit, resources=[
                    tuple(item) for item in proposal["resolution"]["resources"]])
            if _stable_resolution(current) != _stable_resolution(proposal.get("resolution", {})):
                raise ProposalRejected("CELL_JOB_CHANGED_SINCE_RESOLUTION" if cell
                                       else "EVIDENCE_OR_CAPABILITY_CHANGED")
            admitted = admit(mission_id, actor_id=principal.principal_id,
                             expected_generation=body.expected_generation)
        except ProposalRejected as exc:
            raise HTTPException(status_code=409, detail={"code": exc.code}) from exc
        except (MissionConflict, ValueError) as exc:
            raise HTTPException(status_code=409, detail={
                "code": "CELL_JOB_ADMISSION_REFUSED" if cell else "MISSION_ADMISSION_REFUSED",
                "message": str(exc)}) from exc
        return {"proposal": _mission_candidate_result(proposal, admitted)["proposal"],
                "mission": redact_cell_job(admitted, principal) if cell else admitted,
                "physical_submission": "NOT_CONNECTED"}

    @app.post("/api/fleet/missions/{mission_id}/reject", dependencies=operator_guard,
              tags=["fleet-missions"])
    def fleet_mission_reject(mission_id: str, body: MissionAdmitRequest,
                             principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        """D-763 5b: the proposer withdraws, another operator rejects; nothing is claimed."""
        proposal, _, _ = decidable(mission_id, principal)
        cell = proposal["candidate"].get("kind") == "cell_job"
        reject = (cell_job_store.cancel if cell
                  else mission_service.store.reject)
        decision = ("WITHDRAWN_BY_PROPOSER" if proposal["principal_id"] == principal.principal_id
                    else "REJECTED_BY_OPERATOR")
        try:
            rejected = reject(mission_id, actor_id=principal.principal_id, decision=decision,
                              expected_generation=body.expected_generation)
        except (KeyError, MissionConflict, ValueError) as exc:
            raise HTTPException(status_code=409, detail={"code": "MISSION_REJECT_REFUSED",
                                                         "message": str(exc)}) from exc
        return {"proposal": _mission_candidate_result(proposal, rejected)["proposal"],
                "mission": redact_cell_job(rejected, principal) if cell else rejected, "decision": decision}

    if policy_admission_core is not None:  # D-865 P2b/P2c: surface + auto-admit loop
        from fleet.server.missions.policy_admission_routes import (
            install_policy_admission_routes)
        install_policy_admission_routes(
            app, core=policy_admission_core, require_viewer=require_viewer,
            require_named_operator=require_named_operator,
            read_guard=read_guard, operator_guard=operator_guard,
            proposal_store=proposal_store, mission_service=mission_service,
            audit_log=getattr(policy_admission_core, "audit_log", None))
    return fleet_proposal_create, fleet_proposal_resolve, fleet_mission_admit
