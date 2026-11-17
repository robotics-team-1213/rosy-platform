"""Mission HTTP 경로의 요청 모델·후보 판정(`_resolve_candidate`)·Cell Job 마스킹 보조 함수."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Mapping

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, ValidationError

from core_common.protocol.schemas import ResolvedTargetEvidence
from fleet.server.proposal_store import ProposalRejected
from fleet.server.site_auth import SitePrincipal


class MissionCandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_key: str
    workcell_id: str
    instance_id: str
    candidate: dict[str, object]


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
    if not isinstance(resolution, Mapping) or set(resolution) != {"plan", "goal_predicate", "resources"}:
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
    try:
        source_evidence = ResolvedTargetEvidence.model_validate(resolution["plan"].get("source_evidence"))
        destination_evidence = ResolvedTargetEvidence.model_validate(resolution["plan"].get("destination_evidence"))
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


def redact_cell_job(job: dict | None, principal: SitePrincipal) -> dict | None:
    """A Cell Job as this reader sees it: only the proposer sees the proposer's identity (D-763 4 / rev 2 Q6)."""
    if job is None or job["proposal_principal_id"] == principal.principal_id:
        return job
    proposer = job["proposal_principal_id"]
    return {**{key: value for key, value in job.items() if key != "proposal_principal_id"}, "events": [
        {**e, "actor_id": "proposer"} if e["actor_id"] == proposer else e for e in job.get("events", [])]}


def _require_cell_role(candidate: Mapping, principal: SitePrincipal) -> bool:
    """Only the service principal proposes a Cell Job, and it proposes nothing else."""
    cell = candidate.get("kind") == "cell_job"
    if cell != (principal.role == "service"):
        raise HTTPException(status_code=403, detail={"code": "CELL_JOB_SERVICE_PRINCIPAL_REQUIRED" if cell
                                                     else "SERVICE_PRINCIPAL_CELL_JOB_ONLY"})
    return cell
