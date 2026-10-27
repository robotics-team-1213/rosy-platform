"""Private observation assessments and unreviewed export; no retry authority."""
from contextlib import closing
from dataclasses import asdict
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile

from core_common.protocol.arm_transfer import FleetArmTransferGrant
from .mission_store import MissionConflict, _json
from .physical_transfer_observations import evidence_document, validate_post_action_order
from .physical_transfer_outcome import assess_transfer_outcome
from .physical_transfer_review import assess_transfer_execution
from .physical_transfer_store import PhysicalTransferRequest

EVENT = "PHYSICAL_TRANSFER_ASSESSED"


def record_transfer_outcome(execution, mission_id, expected_request_digest, observations, *, authenticated_producer_id):
    store = execution.store
    with closing(store._journal._connect()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        job = store._read(connection, mission_id)
        state = execution._state(connection, mission_id)
        grant = FleetArmTransferGrant.model_validate(state["grant"])
        if (job["status"] != "ACTION_SUCCEEDED" or state["status"] != "ACTION_SUCCEEDED"
                or state["context"]["phase"] != "POST_ACTION" or state["action_succeeded_at_ns"] is None
                or grant.request_digest != expected_request_digest):
            raise MissionConflict("assessment requires the exact current successful Action")
        if store._document(PhysicalTransferRequest.model_validate(job["request"])) != _json(
                {"request": job["request"], "installation": job["installation"]}):
            raise PermissionError("assessment is outside the installed profile")
        from .physical_transfer_evidence import TransferEvidenceContext
        context = TransferEvidenceContext.model_validate_json(_json(state["context"]))
        outcome = assess_transfer_outcome(store.installation.policy, context, observations,
            action_state="SUCCEEDED", now_ns=store._now_ns(), authenticated_producer_id=authenticated_producer_id)
        validate_post_action_order(connection, mission_id, observations)
        document = evidence_document(context, observations)
        digest = sha256(document.encode()).hexdigest()
        detail = dict(schema="rosy.transfer-outcome/1", scope="observation_assessment_only",
            mission_id=mission_id, action_id=grant.action_id, attempt_id=grant.attempt_id,
            request_digest=grant.request_digest, policy_digest=store.installation.policy.digest,
            evaluator_revision=store.installation.policy.evaluator_revision,
            execution_authorized=False, evidence=json.loads(document), evidence_digest=digest,
            event_id=f"transfer-assessment:{grant.attempt_id}:{digest}", **asdict(outcome))
        store._journal._event(connection, mission_id, None, EVENT, authenticated_producer_id, detail)
        connection.commit()
        return detail


def export_transfer_outcomes(store, mission_id, output):
    """Export retained facts for review; not a demonstration or authenticated truth."""
    with closing(store._journal._connect()) as connection:
        connection.execute("BEGIN")
        job = store._read(connection, mission_id)
        if job is None:
            raise KeyError(mission_id)
        from .physical_transfer_execution import PhysicalTransferExecution
        attempt = connection.execute("SELECT grant_json FROM fleet_physical_transfer_attempts "
            "WHERE mission_id=?", (mission_id,)).fetchone()
        if attempt is None:
            raise ValueError("no recorded transfer attempt")
        recorded_grant = FleetArmTransferGrant.model_validate_json(attempt["grant_json"])
        lifetime = (recorded_grant.expires_at - recorded_grant.issued_at).total_seconds()
        execution = PhysicalTransferExecution(store, grant_ttl_s=lifetime)
        current = execution._state(connection, mission_id)
        grant = FleetArmTransferGrant.model_validate(current["grant"])
        prior = execution._last_receipt(connection, mission_id)
        rows = connection.execute("SELECT detail_json FROM fleet_cell_events WHERE mission_id=? "
            "AND event_type=? ORDER BY event_id", (mission_id, EVENT)).fetchall()
        outcomes = [json.loads(row[0]) for row in rows]
        if prior is None:
            raise ValueError("no recorded transfer owner receipt")
        for detail in outcomes:
            evidence = detail["evidence"]
            if (detail["schema"] != "rosy.transfer-outcome/1" or detail["mission_id"] != mission_id
                    or detail["action_id"] != grant.action_id or detail["attempt_id"] != grant.attempt_id
                    or detail["request_digest"] != grant.request_digest
                    or detail["policy_digest"] != store.installation.policy.digest
                    or sha256(_json(evidence).encode()).hexdigest() != detail["evidence_digest"]
                    or evidence["context"]["action_id"] != detail["action_id"]
                    or evidence["context"]["attempt_id"] != detail["attempt_id"]):
                raise ValueError("transfer outcome evidence changed")
        review = assess_transfer_execution(grant, prior["receipt"], job_status=job["status"],
            task_outcome=outcomes[-1]["task_outcome"] if outcomes else "unknown")
        review["receipt_digest"] = sha256(_json(prior["receipt"]).encode()).hexdigest()
        review["source_assessment_digests"] = [item["evidence_digest"] for item in outcomes]
        from .physical_transfer_recovery import recovery_lineage
        document = dict(schema="rosy.transfer-outcome-export/2", scope="unreviewed_metadata_only",
            mission_id=mission_id, raw_camera_bytes_available=False, behavior_training_eligible=False,
            outcomes=outcomes, execution_review=review,
            recovery_lineage=recovery_lineage(store, connection, mission_id))
    output = Path(output)
    fd, pending = tempfile.mkstemp(prefix=".transfer-outcomes-", dir=output.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write((_json(document) + "\n").encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.link(pending, output)
    finally:
        os.unlink(pending)
    return document
