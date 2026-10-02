"""Opt-in Cell goal ingress uses independent producer credentials."""

import hmac
from hashlib import sha256

from fastapi import Header, HTTPException

from core_common.protocol.schemas import CellGoalEvidenceSubmission
from .goal_evidence_service import GoalEvidenceSubmissionError


def assert_cell_producer_credentials_isolated(registry, *, console, principals,
                                              other_tokens=(), other_services=()):
    for producer in registry.producers:
        token = producer.token
        digest = sha256(token.encode()).hexdigest()
        if (any(other is not None and hmac.compare_digest(token.encode(), other.encode()) for other in other_tokens)
                or digest in principals or console.user_credential_overlaps_robot_secret((digest,))
                or any(service is not None and service.uses_token(token) for service in other_services)):
            raise ValueError("Cell producer credential must differ from every other site credential")


def install_cell_goal_evidence_routes(app, service):
    @app.post("/api/fleet/cell-goal-evidence", tags=["fleet-goal-evidence"])
    def submit_cell_goal(body: CellGoalEvidenceSubmission, x_goal_evidence_token: str | None = Header(default=None)):
        if not x_goal_evidence_token:
            raise HTTPException(status_code=401, detail={"code": "PRODUCER_UNAUTHORIZED"})
        try:
            return service.submit(token=x_goal_evidence_token, mission_id=body.mission_id,
                                  raw_evidence=body.evidence.model_dump(mode="json"))
        except GoalEvidenceSubmissionError as exc:
            raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)}) from exc
