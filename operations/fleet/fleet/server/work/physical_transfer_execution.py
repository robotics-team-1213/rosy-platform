"""Durable physical preparation; no device submission or claim release."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from core_common.protocol.arm_transfer import FleetArmTransferGrant
from core_common.resource_keys import normalize_resources
from .mission_store import MissionConflict, _json
from .physical_transfer_evidence import TransferEvidenceContext, TransferOwnerTarget, validate_transfer_observations
from .physical_transfer_observations import record
from .physical_transfer_store import PhysicalTransferRequest
from .step_action_kinds import step_grant_digest


class PhysicalTransferExecution:
    def __init__(self, store, *, grant_ttl_s=15.0):
        if (isinstance(grant_ttl_s, bool) or not isinstance(grant_ttl_s, (int, float))
                or not 1.0 <= grant_ttl_s <= 60.0):
            raise ValueError("physical grant TTL must be between 1 and 60 seconds")
        policy = store.installation.policy
        if grant_ttl_s * 1e9 <= policy.min_separation_ns + policy.max_age_ns:
            raise ValueError("physical grant lifetime must exceed the installed observation window")
        self.store = store
        self.grant_ttl_s = float(grant_ttl_s)

    def _ready(self, connection, mission_id, capabilities, observed_at_ns, now_ns):
        store = self.store
        job = store._read(connection, mission_id)
        if job is None:
            raise KeyError(mission_id)
        request = PhysicalTransferRequest.model_validate(job["request"])
        if (job["status"] != "READY" or job["approved_by"] is None
                or job["approved_by"] == job["proposal_principal_id"]
                or now_ns < job["claims_acquired_at_ns"]
                or store._document(request) != _json({"request": job["request"], "installation": job["installation"]})):
            raise MissionConflict("physical preparation requires the exact approved READY snapshot")
        control = connection.execute("SELECT * FROM fleet_dispatch_control WHERE control_id=1").fetchone()
        if (control is None or not control["dispatch_enabled"] or control["authority_epoch"] != job["authority_epoch"]
                or control["generation"] != job["dispatch_generation"]):
            raise MissionConflict("physical preparation fence is closed or changed")
        store._check_capabilities(capabilities, observed_at_ns, now_ns)
        rows = connection.execute("SELECT resource_key,generation,phase FROM fleet_action_claims "
            "WHERE owner_kind='mission' AND owner_id=?", (mission_id,)).fetchall()
        expected = {key for _, _, key in normalize_resources(store.installation.policy.resources)}
        if ({row["resource_key"] for row in rows} != expected
                or any(row["generation"] != job["dispatch_generation"] or row["phase"] != "CLAIMED" for row in rows)):
            raise MissionConflict("physical preparation requires every current claim")
        return job

    def _grant(self, job, *, prepared_at_ns, identities):
        installed = self.store.installation
        policy = installed.policy
        cap = next(c for c in installed.capabilities if (c.workcell_id, c.instance_id) == policy.primary)
        issued = datetime.fromtimestamp(prepared_at_ns / 1e9, timezone.utc)
        grant = FleetArmTransferGrant(mission_id=job["mission_id"], step_id=identities[0], action_id=identities[1],
            attempt_id=identities[2], owner_journal_id=cap.journal_id, owner_session_id=cap.owner_session_id,
            request_digest="0" * 64, workcell_id=cap.workcell_id, instance_id=cap.instance_id,
            action_kind="ARM_TRANSFER", arm_transfer=dict(object_ref=policy.object_ref, source=installed.source,
                target=installed.target, catalog_digest=policy.catalog_digest, bindings_digest=policy.bindings_digest,
                resource_policy_digest=policy.digest), capability_revision=cap.capability_revision,
            config_revision=cap.config_revision, authority_epoch=job["authority_epoch"],
            dispatch_generation=job["dispatch_generation"], issued_at=issued,
            expires_at=issued + timedelta(seconds=self.grant_ttl_s))
        return FleetArmTransferGrant.model_validate({**grant.model_dump(), "request_digest": step_grant_digest(grant)})

    def _view(self, row, job):
        grant = FleetArmTransferGrant.model_validate_json(row["grant_json"])
        expected = self._grant(job, prepared_at_ns=row["prepared_at_ns"],
                               identities=(row["step_id"], row["action_id"], row["attempt_id"]))
        if (grant != expected or grant.request_digest != row["request_digest"]
                or row["prepared_at_ns"] < job["claims_acquired_at_ns"]):
            raise MissionConflict("physical attempt does not match the approved grant")
        context = TransferEvidenceContext(action_id=grant.action_id, attempt_id=grant.attempt_id,
            phase="PRE_DISPATCH", not_before_ns=row["prepared_at_ns"], owners=tuple(
                TransferOwnerTarget(workcell_id=c.workcell_id, instance_id=c.instance_id,
                    journal_id=c.journal_id, owner_session_id=c.owner_session_id) for c in self.store.installation.capabilities))
        return dict(status=row["status"], prepared_at_ns=row["prepared_at_ns"],
                    grant=grant.model_dump(mode="json"), context=context.model_dump(mode="json"))

    def prepare(self, mission_id, *, capabilities, capabilities_observed_at_ns):
        store = self.store
        with closing(store._journal._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            now_ns = store._now_ns()
            job = self._ready(connection, mission_id, capabilities, capabilities_observed_at_ns, now_ns)
            row = connection.execute("SELECT * FROM fleet_physical_transfer_attempts WHERE mission_id=?", (mission_id,)).fetchone()
            if row is not None:
                result = self._view(row, job)
                expires = datetime.fromisoformat(result["grant"]["expires_at"].replace("Z", "+00:00"))
                if (row["status"] != "PREPARED" or now_ns < row["prepared_at_ns"]
                        or expires <= datetime.fromtimestamp(now_ns / 1e9, timezone.utc)):
                    raise MissionConflict("physical preparation expired or already submitted")
                return result
            identifiers = tuple(prefix + uuid4().hex for prefix in ("physical-step-", "physical-action-", "physical-attempt-"))
            grant = self._grant(job, prepared_at_ns=now_ns, identities=identifiers)
            connection.execute("""INSERT INTO fleet_physical_transfer_attempts
                (mission_id,step_id,action_id,attempt_id,request_digest,grant_json,prepared_at_ns,status)
                VALUES(?,?,?,?,?,?,?,'PREPARED')""", (mission_id, *identifiers, grant.request_digest,
                _json(grant.model_dump(mode="json")), now_ns))
            store._journal._event(connection, mission_id, None, "PHYSICAL_TRANSFER_PREPARED", "fleet",
                dict(step_id=grant.step_id, action_id=grant.action_id, attempt_id=grant.attempt_id,
                     request_digest=grant.request_digest, prepared_at_ns=now_ns))
            row = connection.execute("SELECT * FROM fleet_physical_transfer_attempts WHERE mission_id=?", (mission_id,)).fetchone()
            result = self._view(row, job)
            connection.commit()
            return result

    def authorize_submission(self, mission_id, *, expected_request_digest, observations,
                             authenticated_producer_id, capabilities, capabilities_observed_at_ns):
        if not isinstance(observations, (tuple, list)):
            raise ValueError("physical observations require a bounded sample sequence")
        observations = tuple(observations)
        store = self.store
        with closing(store._journal._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            now_ns = store._now_ns()
            job = self._ready(connection, mission_id, capabilities, capabilities_observed_at_ns, now_ns)
            row = connection.execute("SELECT * FROM fleet_physical_transfer_attempts WHERE mission_id=?", (mission_id,)).fetchone()
            if row is None or row["status"] != "PREPARED":
                raise MissionConflict("first send requires the durable prepared attempt")
            result = self._view(row, job)
            grant = FleetArmTransferGrant.model_validate(result["grant"])
            if (expected_request_digest != grant.request_digest or now_ns < row["prepared_at_ns"]
                    or not grant.issued_at <= datetime.fromtimestamp(now_ns / 1e9, timezone.utc) < grant.expires_at):
                raise MissionConflict("physical first-send grant changed or expired")
            context = TransferEvidenceContext.model_validate_json(_json(result["context"]))
            validate_transfer_observations(store.installation.policy, context, observations,
                now_ns=now_ns, authenticated_producer_id=authenticated_producer_id)
            record(connection, mission_id=mission_id, grant=grant, context=context,
                   observations=observations, validated_at_ns=now_ns)
            final_ns = store._now_ns()
            if (final_ns < now_ns
                    or not grant.issued_at <= datetime.fromtimestamp(final_ns / 1e9, timezone.utc) < grant.expires_at):
                raise MissionConflict("physical first-send clock moved backwards or grant expired")
            store._check_capabilities(capabilities, capabilities_observed_at_ns, final_ns)
            validate_transfer_observations(store.installation.policy, context, observations,
                now_ns=final_ns, authenticated_producer_id=authenticated_producer_id)
            connection.execute("UPDATE fleet_physical_transfer_observations SET validated_at_ns=? "
                               "WHERE mission_id=? AND phase='PRE_DISPATCH'", (final_ns, mission_id))
            connection.execute("UPDATE fleet_physical_transfer_attempts SET status='SUBMITTING' WHERE mission_id=?", (mission_id,))
            connection.execute("UPDATE fleet_cell_jobs SET status='RUNNING',updated_at=? WHERE mission_id=?",
                (datetime.fromtimestamp(final_ns / 1e9, timezone.utc).isoformat(), mission_id))
            connection.execute("UPDATE fleet_action_claims SET phase='DISPATCHING' WHERE owner_kind='mission' AND owner_id=?", (mission_id,))
            store._journal._event(connection, mission_id, None, "PHYSICAL_TRANSFER_SUBMITTING", "fleet",
                dict(action_id=grant.action_id, attempt_id=grant.attempt_id, request_digest=grant.request_digest,
                     preconditions_validated_at_ns=final_ns))
            connection.commit()
            return {**result, "status": "SUBMITTING"}
