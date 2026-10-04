"""Mission HTTP 표면 — 제안·판정·승인·진행 (mission/proposal/goal-evidence 저장소 소유).

`create_app` 이 검증만 하고, 경로는 이 모듈이 단다. 후보 판정(`resolve_candidate`)의
증명·민감 필드 거절·자원 클레임 검사가 여기 산다 — 판정은 라우트가 아니라 저장소와
같은 주인에게 붙어 있어야 한다(D-12, D-357/D-358).
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Mapping, Optional

from fastapi import Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from core_common.protocol.schemas import (
    MissionCursorExpiredError,
    MissionCursorResetError,
    MissionProgressEventPage,
    MissionProgressReadResponse,
    ResolvedTargetEvidence,
)
from fleet.server.goal_evidence_service import GoalEvidenceSubmissionError
from fleet.server.mission_store import MissionConflict
from fleet.server.proposal_store import ProposalConflict, ProposalRejected
from fleet.server.site_auth import SitePrincipal


class MissionCandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_key: str
    workcell_id: str
    instance_id: str
    candidate: dict[str, object]


class MissionAdmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expected_generation: int

    @field_validator("expected_generation", mode="before")
    @classmethod
    def _non_negative_generation(cls, value):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("expected_generation must be a non-negative integer")
        return value


def _mission_candidate_result(proposal: dict, mission: dict | None) -> dict:
    return {
        "proposal": {
            "proposal_id": proposal["proposal_id"],
            "request_key": proposal["request_key"],
            "state": proposal["state"],
            "candidate": proposal["candidate"],
            "source_mission_id": proposal.get("source_mission_id"),
            "source_action_id": proposal.get("source_action_id"),
            "source_attempt_id": proposal.get("source_attempt_id"),
            "source_dispatch_generation": proposal.get("source_dispatch_generation"),
            "source_event_watermark": proposal.get("source_event_watermark"),
            "source_observation_id": proposal.get("source_observation_id"),
            "supersedes_mission_id": proposal.get("supersedes_mission_id"),
            "reason": proposal["reason"],
            "expires_at": proposal["expires_at"],
        },
        "mission": mission,
    }


def _mission_snapshot_response(proposal: dict, snapshot: dict) -> dict:
    return {
        **_mission_candidate_result(proposal, snapshot["mission"]),
        "history": snapshot["history"],
        "history_truncated": snapshot["history_truncated"],
        "progress": snapshot["progress"],
    }


def _resolve_candidate(candidate_resolver, candidate: Mapping, *, workcell_id: str,
                       instance_id: str, now: float) -> dict:
    try:
        resolution = candidate_resolver(
            candidate, workcell_id=workcell_id, instance_id=instance_id, now=now,
        )
    except ProposalRejected:
        raise
    except (ValueError, KeyError, TypeError) as exc:
        raise ProposalRejected("CANDIDATE_UNRESOLVED") from exc
    if not isinstance(resolution, Mapping):
        raise ProposalRejected("CANDIDATE_UNRESOLVED")
    if set(resolution) != {"plan", "goal_predicate", "resources"}:
        raise ProposalRejected("CANDIDATE_UNRESOLVED")
    if not isinstance(resolution["plan"], Mapping) or not isinstance(
            resolution["goal_predicate"], Mapping):
        raise ProposalRejected("CANDIDATE_UNRESOLVED")
    try:
        encoded = json.dumps(dict(resolution), sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProposalRejected("INVALID_RESOLUTION_METADATA") from exc
    if len(encoded) > 64 * 1024:
        raise ProposalRejected("RESOLUTION_METADATA_TOO_LARGE")

    def reject_sensitive_fields(item):
        if isinstance(item, Mapping):
            for key, nested in item.items():
                if not isinstance(key, str):
                    raise ProposalRejected("INVALID_RESOLUTION_METADATA")
                if key.casefold() in {
                        "principal_id", "actor_id", "image_bytes", "image_data",
                        "raw_image", "frame_bytes", "api_key", "authorization",
                        "access_token", "bearer_token"}:
                    raise ProposalRejected("RESOLUTION_CONTAINS_FORBIDDEN_DATA")
                reject_sensitive_fields(nested)
        elif isinstance(item, list):
            for nested in item:
                reject_sensitive_fields(nested)

    reject_sensitive_fields(resolution)
    source_raw = resolution["plan"].get("source_evidence")
    destination_raw = resolution["plan"].get("destination_evidence")
    try:
        source_evidence = ResolvedTargetEvidence.model_validate(source_raw)
        destination_evidence = ResolvedTargetEvidence.model_validate(destination_raw)
    except (ValidationError, TypeError) as exc:
        raise ProposalRejected("TARGET_EVIDENCE_INVALID") from exc
    candidate_observation = candidate.get("source_observation")
    if not isinstance(candidate_observation, Mapping):
        raise ProposalRejected("OBSERVATION_PROVENANCE_INVALID")
    try:
        observed = datetime.fromisoformat(
            str(candidate_observation["observed_at"]).replace("Z", "+00:00"))
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError("timezone required")
        elapsed = observed.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
        capture_time_ns = ((elapsed.days * 86_400 + elapsed.seconds) * 1_000_000_000
                           + elapsed.microseconds * 1_000)
        expected_identity = (
            candidate_observation["observation_id"],
            candidate_observation["image_sha256"],
            candidate_observation["camera_id"],
            candidate_observation["frame_id"],
            candidate_observation["calibration_revision"],
            candidate_observation["transform_revision"],
            capture_time_ns,
        )
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ProposalRejected("OBSERVATION_PROVENANCE_INVALID") from exc
    for evidence in (source_evidence, destination_evidence):
        actual_identity = (
            evidence.observation_id, evidence.frame_sha256,
            evidence.camera_identity, evidence.optical_frame_id,
            evidence.calibration_revision, evidence.transform_revision,
            evidence.capture_time_ns,
        )
        if actual_identity != expected_identity:
            raise ProposalRejected("OBSERVATION_PROVENANCE_MISMATCH")
    resources = resolution["resources"]
    if (not isinstance(resources, list) or not resources
            or any(not isinstance(item, (tuple, list)) or len(item) != 2
                   or any(not isinstance(part, str) or not part.strip() for part in item)
                   for item in resources)):
        raise ProposalRejected("CANDIDATE_UNRESOLVED")
    goal = resolution["goal_predicate"]
    object_id, destination_id = goal.get("object_id"), goal.get("destination_id")
    if (source_evidence.object_id != object_id
            or destination_evidence.object_id != destination_id
            or source_evidence.object_id == destination_evidence.object_id):
        raise ProposalRejected("TARGET_GOAL_MISMATCH")
    required_claims = {
        ("workcell", workcell_id), ("object", object_id),
        ("object", destination_id),
    }
    if (not all(isinstance(value, str) and value.strip()
                for value in (object_id, destination_id))
            or not required_claims.issubset({tuple(item) for item in resources})):
        raise ProposalRejected("CANDIDATE_RESOURCES_INCOMPLETE")
    plan = dict(resolution["plan"])
    plan["source_evidence"] = source_evidence.model_dump(mode="json")
    plan["destination_evidence"] = destination_evidence.model_dump(mode="json")
    plan["observation_revision"] = plan.get(
        "observation_revision", source_evidence.observation_id,
    )
    for revision_name in ("capability_revision", "config_revision",
                          "observation_revision"):
        revision = plan.get(revision_name)
        if (not isinstance(revision, str) or not revision.strip()
                or revision != revision.strip() or len(revision) > 128):
            raise ProposalRejected(f"{revision_name.upper()}_MISSING")
    if plan["observation_revision"] != source_evidence.observation_id:
        raise ProposalRejected("OBSERVATION_REVISION_MISMATCH")
    return {"plan": plan,
            "goal_predicate": dict(resolution["goal_predicate"]),
            "resources": [list(item) for item in resources]}


def _stable_resolution(value: Mapping) -> str:
    def strip_transient(item):
        if isinstance(item, Mapping):
            return {key: strip_transient(nested) for key, nested in item.items()
                    if key not in {"resolved_at", "validated_at", "age_ms"}}
        if isinstance(item, list):
            return [strip_transient(nested) for nested in item]
        return item
    return json.dumps(strip_transient(value), sort_keys=True, separators=(",", ":"),
                      allow_nan=False)


def install_mission_routes(app, *, mission_service, proposal_store, goal_evidence_service,
                           mission_progress, candidate_resolver, cell_job_store,
                           cell_job_resolver, require_viewer, require_operator,
                           require_named_operator, require_proposer,
                           read_guard, operator_guard):
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
        cell_candidate = body.candidate.get("kind") == "cell_job"
        if cell_candidate != (principal.role == "service"):
            raise HTTPException(status_code=403, detail={
                "code": "CELL_JOB_SERVICE_PRINCIPAL_REQUIRED" if cell_candidate
                else "SERVICE_PRINCIPAL_CELL_JOB_ONLY",
            })
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

    @app.get("/api/fleet/proposals/{proposal_id}", dependencies=read_guard,
             tags=["fleet-missions"])
    def fleet_proposal_read(proposal_id: str,
                            principal: SitePrincipal = Depends(require_viewer)) -> dict:
        proposal = proposal_store.get(proposal_id, principal_id=principal.principal_id)
        if proposal is None and principal.role == "operator":
            candidate_proposal = proposal_store.get(proposal_id)
            if (candidate_proposal is not None
                    and candidate_proposal["candidate"].get("kind") == "cell_job"):
                proposal = candidate_proposal
        if proposal is None:
            raise HTTPException(status_code=404, detail={"code": "PROPOSAL_NOT_FOUND"})
        if proposal["candidate"].get("kind") == "cell_job":
            return _mission_candidate_result(proposal, cell_job_store.get(proposal_id))
        mission = mission_service.get(proposal_id)
        return _mission_candidate_result(proposal, mission)

    @app.post("/api/fleet/proposals/{proposal_id}/resolve",
              dependencies=[Depends(require_proposer)],
              tags=["fleet-missions"])
    def fleet_proposal_resolve(proposal_id: str,
                               principal: SitePrincipal = Depends(require_proposer)) -> dict:
        proposal = proposal_store.get(proposal_id, principal_id=principal.principal_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail={"code": "PROPOSAL_NOT_FOUND"})
        cell_candidate = proposal["candidate"].get("kind") == "cell_job"
        if cell_candidate != (principal.role == "service"):
            raise HTTPException(status_code=403, detail={
                "code": "CELL_JOB_SERVICE_PRINCIPAL_REQUIRED" if cell_candidate
                else "SERVICE_PRINCIPAL_CELL_JOB_ONLY",
            })
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
        proposal = proposal_store.get(mission_id, principal_id=principal.principal_id)
        if proposal is None and principal.role == "operator":
            proposal = proposal_store.get(mission_id)
        if (proposal is None or proposal["candidate"].get("kind") != "cell_job"
                or proposal["state"] != "RESOLVED"):
            raise HTTPException(status_code=404, detail={"code": "CELL_JOB_NOT_FOUND"})
        job = cell_job_store.get(mission_id) if cell_job_store is not None else None
        if job is None:
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

    @app.post("/api/fleet/missions/{mission_id}/admit", dependencies=operator_guard,
              tags=["fleet-missions"])
    def fleet_mission_admit(mission_id: str, body: MissionAdmitRequest,
                            principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        proposal = proposal_store.get(mission_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail={"code": "MISSION_NOT_FOUND"})
        if proposal["candidate"].get("kind") == "cell_job":
            if proposal["state"] != "RESOLVED":
                raise HTTPException(status_code=409, detail={"code": "PROPOSAL_NOT_RESOLVED"})
            if proposal["principal_id"] == principal.principal_id:
                raise HTTPException(status_code=403, detail={
                    "code": "CELL_JOB_APPROVER_MUST_DIFFER_FROM_PROPOSER",
                })
            if cell_job_store is None:
                raise HTTPException(status_code=503, detail={"code": "CELL_JOB_JOURNAL_UNAVAILABLE"})
            try:
                if cell_job_resolver is None:
                    raise HTTPException(status_code=503, detail={
                        "code": "CELL_JOB_COMPILER_UNAVAILABLE",
                    })
                current = cell_job_resolver(
                    proposal["candidate"], workcell_id=proposal["workcell_id"],
                    instance_id=proposal["instance_id"],
                )
                if _stable_resolution(current) != _stable_resolution(proposal.get("resolution", {})):
                    raise ProposalRejected("CELL_JOB_CHANGED_SINCE_RESOLUTION")
                admitted = cell_job_store.admit(
                    mission_id, actor_id=principal.principal_id,
                    expected_generation=body.expected_generation,
                )
            except ProposalRejected as exc:
                raise HTTPException(status_code=409, detail={"code": exc.code}) from exc
            except (MissionConflict, ValueError) as exc:
                raise HTTPException(status_code=409, detail={
                    "code": "CELL_JOB_ADMISSION_REFUSED", "message": str(exc),
                }) from exc
            return {"proposal": _mission_candidate_result(proposal, admitted)["proposal"],
                    "mission": admitted, "physical_submission": "NOT_CONNECTED"}

        if proposal["principal_id"] != principal.principal_id:
            raise HTTPException(status_code=404, detail={"code": "MISSION_NOT_FOUND"})
        mission = mission_service.get(mission_id)
        if mission is None or proposal["state"] != "RESOLVED":
            raise HTTPException(status_code=409, detail={"code": "PROPOSAL_NOT_RESOLVED"})
        try:
            current = _resolve_candidate(
                candidate_resolver,
                proposal["candidate"], workcell_id=mission["workcell_id"],
                instance_id=mission["instance_id"], now=time.time(),
            )
            if _stable_resolution(current) != _stable_resolution(proposal["resolution"]):
                raise ProposalRejected("EVIDENCE_OR_CAPABILITY_CHANGED")
            admitted = mission_service.admit(
                mission_id, actor_id=principal.principal_id,
                expected_generation=body.expected_generation,
                resources=[tuple(item) for item in proposal["resolution"]["resources"]],
            )
        except ProposalRejected as exc:
            raise HTTPException(status_code=409, detail={"code": exc.code}) from exc
        except (MissionConflict, ValueError) as exc:
            raise HTTPException(status_code=409, detail={"code": "MISSION_ADMISSION_REFUSED",
                                                         "message": str(exc)}) from exc
        return {"proposal": _mission_candidate_result(proposal, admitted)["proposal"],
                "mission": admitted, "physical_submission": "NOT_CONNECTED"}

    return fleet_proposal_create, fleet_proposal_resolve
