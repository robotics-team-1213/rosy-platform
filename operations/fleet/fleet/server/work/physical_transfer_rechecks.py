"""D-930 recheck: fresh facts about an already confirmed attempt.

A recheck re-validates the original target pose and clearance with new measured samples.
It submits no Action, takes or releases no claim and never changes the job or its receipt.
"""
from contextlib import closing
from hashlib import sha256
import json

from core_common.protocol.arm_transfer_recheck import ArmTransferRecheck
from .mission_store import MissionConflict, _json
from .physical_transfer_evidence import PhysicalEvidenceRejected, TransferEvidenceContext, validate_transfer_observations
from .physical_transfer_io import physical_io
from .physical_transfer_observations import evidence_document


class PhysicalTransferRechecks:
    def __init__(self, service):
        self.service, self.store = service, service.store

    def _confirmed(self, connection, mission_id):
        job = self.service._job(connection, mission_id)
        closed = self.service._closed_proof(connection, mission_id)
        if job["status"] != "GOAL_CONFIRMED" or closed is None:
            raise MissionConflict("a recheck requires a confirmed physical attempt")
        return json.loads(closed[0]["evidence_json"])["context"]

    def _view(self, row, context):
        return ArmTransferRecheck.model_validate(dict(mission_id=row["mission_id"], recheck_key=row["recheck_key"],
            action_id=context["action_id"], attempt_id=context["attempt_id"], requested_at_ns=row["requested_at_ns"],
            status="WAITING_OBSERVATIONS" if row["evidence_json"] is None else "CONFIRMED",
            evidence_document=row["evidence_json"], evidence_digest=row["evidence_digest"],
            validated_at_ns=row["validated_at_ns"],
            zone_ids=self.store.installation.policy.zone_resource_ids)).model_dump(mode="json")

    def _row(self, connection, mission_id, recheck_key):
        return connection.execute("SELECT * FROM fleet_physical_transfer_rechecks WHERE mission_id=? AND recheck_key=?",
                                  (mission_id, recheck_key)).fetchone()

    def request(self, mission_id, recheck_key, *, principal_id):
        with physical_io(self.store._journal.path), closing(self.store._journal._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            context = self._confirmed(connection, mission_id)
            row = self._row(connection, mission_id, recheck_key)
            if row is None:
                # One open recheck per job keeps the observer's single context unambiguous.
                if connection.execute("SELECT 1 FROM fleet_physical_transfer_rechecks WHERE mission_id=? "
                                      "AND evidence_json IS NULL", (mission_id,)).fetchone() is not None:
                    raise MissionConflict("another recheck of this job is still waiting")
                connection.execute("INSERT INTO fleet_physical_transfer_rechecks"
                    "(mission_id,recheck_key,requested_by,requested_at_ns) VALUES(?,?,?,?)",
                    (mission_id, recheck_key, principal_id, self.store._now_ns()))
                row = self._row(connection, mission_id, recheck_key)
                self.store._journal._event(connection, mission_id, None, "PHYSICAL_TRANSFER_RECHECK_REQUESTED",
                    principal_id, {"recheck_key": recheck_key, "requested_at_ns": row["requested_at_ns"]})
            connection.commit()
            return self._view(row, context)

    def read(self, mission_id, recheck_key):
        with closing(self.store._journal._connect()) as connection:
            connection.execute("BEGIN")
            context = self._confirmed(connection, mission_id)
            row = self._row(connection, mission_id, recheck_key)
            if row is None:
                raise KeyError(recheck_key)
            if row["evidence_json"] is not None and (
                    sha256(row["evidence_json"].encode()).hexdigest() != row["evidence_digest"]):
                raise MissionConflict("stored recheck evidence changed")
            return self._view(row, context)

    def pending(self, connection):
        """Oldest waiting recheck as (mission_id, not_before_ns), or None."""
        row = connection.execute("SELECT mission_id,requested_at_ns FROM fleet_physical_transfer_rechecks "
            "WHERE evidence_json IS NULL ORDER BY requested_at_ns,mission_id LIMIT 1").fetchone()
        return None if row is None else (row["mission_id"], row["requested_at_ns"])

    def observe(self, mission_id, expected_request_digest, samples):
        policy = self.store.installation.policy
        with physical_io(self.store._journal.path), closing(self.store._journal._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            context = self._confirmed(connection, mission_id)
            if self.service.execution._state(connection, mission_id)["grant"]["request_digest"] != expected_request_digest:
                raise MissionConflict("recheck observation targets a different request")
            row = connection.execute("SELECT * FROM fleet_physical_transfer_rechecks WHERE mission_id=? "
                "AND evidence_json IS NULL ORDER BY requested_at_ns LIMIT 1", (mission_id,)).fetchone()
            if row is None:
                raise MissionConflict("no recheck of this job is waiting")
            if any(owner.joints is None for sample in samples for owner in sample.owners):
                raise PhysicalEvidenceRejected("PHYSICAL_JOINTS_REQUIRED")
            context = TransferEvidenceContext.model_validate_json(
                _json({**context, "phase": "RECHECK", "not_before_ns": row["requested_at_ns"]}))
            now_ns = self.store._now_ns()
            validate_transfer_observations(policy, context, samples, now_ns=now_ns,
                                           authenticated_producer_id=self.service.observer.producer_id)
            document = evidence_document(context, samples)
            digest = sha256(document.encode()).hexdigest()
            connection.execute("UPDATE fleet_physical_transfer_rechecks SET evidence_json=?,evidence_digest=?,"
                "validated_at_ns=? WHERE mission_id=? AND recheck_key=?",
                (document, digest, now_ns, mission_id, row["recheck_key"]))
            self.store._journal._event(connection, mission_id, None, "PHYSICAL_TRANSFER_RECHECKED", "fleet",
                {"recheck_key": row["recheck_key"], "evidence_digest": digest, "validated_at_ns": now_ns})
            connection.commit()
