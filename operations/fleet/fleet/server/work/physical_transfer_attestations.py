"""D-977 5: single-use named-operator statements beside, never inside, the automatic physical evidence."""
from contextlib import closing
import sqlite3

from core_common.protocol.arm_transfer_attestation import (
    ArmTransferOperatorAttestation, OPERATOR_ATTESTATION_VALIDITY_NS)
from .mission_store import MissionConflict

# kind -> the only job status in which that statement is meaningful
_STATUS = {"SOURCE_CLEAR": "READY", "TARGET_PLACED": "ACTION_SUCCEEDED"}


class PhysicalOperatorAttestations:
    def __init__(self, store):
        self.store = store
        with closing(store._journal._connect()) as connection:
            # Own table, no FK: nothing here may change a job, claim or receipt.
            connection.execute("""CREATE TABLE IF NOT EXISTS fleet_physical_operator_attestations (
                mission_id TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('SOURCE_CLEAR','TARGET_PLACED')),
                attested_by TEXT NOT NULL, request_digest TEXT NOT NULL, proposal_digest TEXT NOT NULL,
                job_status TEXT NOT NULL, attested_at_ns INTEGER NOT NULL, expires_at_ns INTEGER NOT NULL,
                PRIMARY KEY(mission_id,kind))""")
            connection.commit()

    def record(self, mission_id, principal, body):
        with closing(self.store._journal._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = self.store._read(connection, mission_id)
            if job is None:
                raise KeyError(mission_id)
            if (body.expected_request_digest, body.expected_proposal_digest) != (job["request_digest"], job["proposal_digest"]):
                raise MissionConflict("attestation targets a different request")
            if job["status"] != _STATUS[body.kind] or job["approved_by"] is None:
                raise MissionConflict("attestation does not fit the job state")
            who = principal.principal_id
            if who in (job["proposal_principal_id"], job["approved_by"]):
                raise PermissionError("proposer and approver cannot attest")
            now = self.store._now_ns()
            try:
                connection.execute("INSERT INTO fleet_physical_operator_attestations VALUES(?,?,?,?,?,?,?,?)",
                    (mission_id, body.kind, who, job["request_digest"], job["proposal_digest"], job["status"],
                     now, now + OPERATOR_ATTESTATION_VALIDITY_NS))
            except sqlite3.IntegrityError:
                raise MissionConflict("this attestation is single-use and already recorded") from None
            connection.commit()
        return self._model(job, who, body.kind, now)

    @staticmethod
    def _model(job, who, kind, at):
        return ArmTransferOperatorAttestation(mission_id=job["mission_id"], kind=kind, evidence_source="operator_attested",
            attested_by=who, proposed_by=job["proposal_principal_id"], approved_by=job["approved_by"],
            request_digest=job["request_digest"], proposal_digest=job["proposal_digest"], job_status=job["status"],
            attested_at_ns=at, expires_at_ns=at + OPERATOR_ATTESTATION_VALIDITY_NS, goal_confirmed=False)

    def list(self, mission_id):
        with closing(self.store._journal._connect()) as connection:
            job = self.store._read(connection, mission_id)
            if job is None:
                raise KeyError(mission_id)
            rows = connection.execute("SELECT * FROM fleet_physical_operator_attestations WHERE mission_id=? "
                                      "ORDER BY attested_at_ns", (mission_id,)).fetchall()
        return [ArmTransferOperatorAttestation(mission_id=mission_id, kind=r["kind"], evidence_source="operator_attested",
            attested_by=r["attested_by"], proposed_by=job["proposal_principal_id"], approved_by=job["approved_by"],
            request_digest=r["request_digest"], proposal_digest=r["proposal_digest"], job_status=r["job_status"],
            attested_at_ns=r["attested_at_ns"], expires_at_ns=r["expires_at_ns"], goal_confirmed=False) for r in rows]
