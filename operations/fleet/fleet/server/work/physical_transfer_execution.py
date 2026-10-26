"""Durable physical preparation; no device submission or claim release."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from uuid import uuid4

from core_common.protocol.arm_transfer import FleetArmTransferGrant
from core_common.protocol.device_actions import DeviceActionReceipt
from core_common.resource_keys import normalize_resources
from rosy.world.state.projections.physical_transfer import TransferObservation
from .mission_store import MissionConflict, _json
from .action_receipts import verify_phase_receipt
from .dispatch_admission import release
from .physical_transfer_evidence import TransferEvidenceContext, TransferOwnerTarget, validate_transfer_observations
from .physical_transfer_observations import evidence_document, record, validate_post_action_order
from .physical_transfer_store import PhysicalTransferRequest
from .step_action_kinds import step_grant_digest


def _timestamp_ns(value):
    delta = value - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (delta.days * 86400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000


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
        if not self._owns_claims(connection, job, phases={"CLAIMED"}):
            raise MissionConflict("physical preparation requires every current claim")
        return job

    def _owns_claims(self, connection, job, *, phases):
        rows = connection.execute("SELECT resource_key,generation,phase FROM fleet_action_claims "
            "WHERE owner_kind='mission' AND owner_id=?", (job["mission_id"],)).fetchall()
        expected = {key for _, _, key in normalize_resources(self.store.installation.policy.resources)}
        return ({row["resource_key"] for row in rows} == expected
                and all(row["generation"] == job["dispatch_generation"] and row["phase"] in phases for row in rows))

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

    def _physical_receipt(self, row, grant):
        policy = self.store.installation.policy
        return dict(receipt_id=row["record_id"], mission_id=grant.mission_id, action_id=grant.action_id,
            attempt_id=grant.attempt_id, request_digest=grant.request_digest, workcell_id=grant.workcell_id,
            instance_id=grant.instance_id, policy_digest=policy.digest, evidence_digest=row["evidence_digest"],
            object_ref=policy.object_ref, source=grant.arm_transfer.source, target=grant.arm_transfer.target,
            authority_epoch=grant.authority_epoch, dispatch_generation=grant.dispatch_generation,
            validated_at_ns=row["validated_at_ns"], physical_status="AT_TARGET_AND_CLEAR")

    def confirm_physical(self, mission_id, *, expected_request_digest, observations,
                         authenticated_producer_id, capabilities, capabilities_observed_at_ns):
        if not isinstance(observations, (tuple, list)):
            raise ValueError("physical observations require a bounded sample sequence")
        observations = tuple(observations)
        if len(observations) != 2 or any(not isinstance(sample, TransferObservation) for sample in observations):
            raise ValueError("physical closure requires two immutable World observations")
        store = self.store
        policy = store.installation.policy
        if authenticated_producer_id != policy.producer_id:
            raise ValueError("physical producer does not match the installed policy")
        with closing(store._journal._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = self._state(connection, mission_id)
            grant = FleetArmTransferGrant.model_validate(current["grant"])
            if expected_request_digest != grant.request_digest:
                raise MissionConflict("physical receipt targets a different request")
            job = store._read(connection, mission_id)
            context = TransferEvidenceContext.model_validate_json(_json(current["context"]))
            prior = connection.execute("SELECT * FROM fleet_physical_transfer_observations "
                "WHERE mission_id=? AND phase='POST_ACTION'", (mission_id,)).fetchone()
            document = evidence_document(context, observations)
            if prior is not None:
                if (job["status"] != "GOAL_CONFIRMED" or prior["request_digest"] != grant.request_digest
                        or prior["evidence_json"] != document
                        or prior["evidence_digest"] != sha256(document.encode()).hexdigest()):
                    raise MissionConflict("confirmed physical evidence cannot be replaced")
                return self._physical_receipt(prior, grant)
            if (job["status"] != "ACTION_SUCCEEDED" or current["status"] != "ACTION_SUCCEEDED"
                    or current["action_succeeded_at_ns"] is None or context.phase != "POST_ACTION"
                    or store._document(PhysicalTransferRequest.model_validate(job["request"]))
                       != _json({"request": job["request"], "installation": job["installation"]})):
                raise MissionConflict("physical closure requires the exact successful Action and installation")
            control = connection.execute("SELECT * FROM fleet_dispatch_control WHERE control_id=1").fetchone()
            if (control is None or not control["dispatch_enabled"] or control["authority_epoch"] != grant.authority_epoch
                    or control["generation"] != grant.dispatch_generation
                    or not self._owns_claims(connection, job, phases={"HELD"})):
                raise MissionConflict("physical closure requires the current fence and every original claim")
            now_ns = store._now_ns()
            store._check_capabilities(capabilities, capabilities_observed_at_ns, now_ns)
            validate_transfer_observations(policy, context, observations, now_ns=now_ns,
                                           authenticated_producer_id=authenticated_producer_id)
            validate_post_action_order(connection, mission_id, observations)
            record(connection, mission_id=mission_id, grant=grant, context=context,
                   observations=observations, validated_at_ns=now_ns)
            final_ns = store._now_ns()
            if final_ns < now_ns:
                raise MissionConflict("physical closure clock moved backwards")
            store._check_capabilities(capabilities, capabilities_observed_at_ns, final_ns)
            validate_transfer_observations(policy, context, observations, now_ns=final_ns,
                                           authenticated_producer_id=authenticated_producer_id)
            connection.execute("UPDATE fleet_physical_transfer_observations SET validated_at_ns=? "
                               "WHERE mission_id=? AND phase='POST_ACTION'", (final_ns, mission_id))
            if release(connection, owner_kind="mission", owner_id=mission_id,
                       generation=grant.dispatch_generation) != len(policy.resources):
                raise MissionConflict("physical closure did not release exactly the approved claim set")
            connection.execute("UPDATE fleet_cell_jobs SET status='GOAL_CONFIRMED',reason=NULL,updated_at=? WHERE mission_id=?",
                (datetime.fromtimestamp(final_ns / 1e9, timezone.utc).isoformat(), mission_id))
            row = connection.execute("SELECT * FROM fleet_physical_transfer_observations "
                "WHERE mission_id=? AND phase='POST_ACTION'", (mission_id,)).fetchone()
            result = self._physical_receipt(row, grant)
            store._journal._event(connection, mission_id, None, "PHYSICAL_TRANSFER_CONFIRMED", "fleet", result)
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

    @staticmethod
    def _last_receipt(connection, mission_id):
        row = connection.execute("SELECT detail_json FROM fleet_cell_events WHERE mission_id=? "
            "AND event_type='PHYSICAL_TRANSFER_RECEIPT' ORDER BY event_id DESC LIMIT 1", (mission_id,)).fetchone()
        return None if row is None else json.loads(row[0])

    def _state(self, connection, mission_id):
        job = self.store._read(connection, mission_id)
        row = connection.execute("SELECT * FROM fleet_physical_transfer_attempts WHERE mission_id=?", (mission_id,)).fetchone()
        if job is None or row is None:
            raise KeyError(mission_id)
        result = self._view(row, job)
        result["first_send_committed"] = connection.execute("SELECT 1 FROM fleet_physical_transfer_observations "
            "WHERE mission_id=? AND phase='PRE_DISPATCH'", (mission_id,)).fetchone() is not None
        latest = self._last_receipt(connection, mission_id)
        boundary = None if latest is None else latest.get("action_succeeded_at_ns")
        result["action_succeeded_at_ns"] = boundary
        if row["status"] == "ACTION_SUCCEEDED" and boundary is not None:
            result["context"] = {**result["context"], "phase": "POST_ACTION", "not_before_ns": boundary}
        return result

    def snapshot(self, mission_id):
        with closing(self.store._journal._connect()) as connection:
            return self._state(connection, mission_id)

    def hold(self, mission_id, *, reason):
        store = self.store
        with closing(store._journal._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = store._read(connection, mission_id)
            if job is None:
                raise KeyError(mission_id)
            row = connection.execute("SELECT * FROM fleet_physical_transfer_attempts WHERE mission_id=?", (mission_id,)).fetchone()
            if job["status"] not in {"READY", "RUNNING"}:
                return None if row is None else self._state(connection, mission_id)
            in_flight = row is not None and row["status"] == "SUBMITTING"
            connection.execute("UPDATE fleet_cell_jobs SET status='HOLD',reason=?,updated_at=? WHERE mission_id=?",
                (reason, datetime.fromtimestamp(store._now_ns() / 1e9, timezone.utc).isoformat(), mission_id))
            if row is not None:
                connection.execute("UPDATE fleet_physical_transfer_attempts SET status=? WHERE mission_id=?",
                                   ("UNKNOWN" if in_flight else "HOLD", mission_id))
            connection.execute("UPDATE fleet_action_claims SET phase=?,lease_until=NULL WHERE owner_kind='mission' AND owner_id=?",
                               ("UNKNOWN" if in_flight else "HELD", mission_id))
            store._journal._event(connection, mission_id, None, "PHYSICAL_TRANSFER_HELD", "fleet",
                dict(reason=reason, action_id=None if row is None else row["action_id"],
                     attempt_id=None if row is None else row["attempt_id"]))
            result = None if row is None else self._state(connection, mission_id)
            connection.commit()
            return result

    def validate_send(self, mission_id, *, expected_request_digest, observations,
                      authenticated_producer_id, capabilities, capabilities_observed_at_ns):
        store = self.store
        with closing(store._journal._connect()) as connection:
            connection.execute("BEGIN")
            current = self._state(connection, mission_id)
            job = store._read(connection, mission_id)
            grant = FleetArmTransferGrant.model_validate(current["grant"])
            control = connection.execute("SELECT * FROM fleet_dispatch_control WHERE control_id=1").fetchone()
            if (current["status"] != "SUBMITTING" or job["status"] != "RUNNING"
                    or expected_request_digest != grant.request_digest or control is None
                    or not control["dispatch_enabled"] or control["authority_epoch"] != grant.authority_epoch
                    or control["generation"] != grant.dispatch_generation
                    or not self._owns_claims(connection, job, phases={"DISPATCHING"})):
                raise MissionConflict("physical send intent is held or its fence/claims changed")
            context = TransferEvidenceContext.model_validate_json(_json(current["context"]))
            proof = connection.execute("SELECT * FROM fleet_physical_transfer_observations "
                "WHERE mission_id=? AND phase='PRE_DISPATCH'", (mission_id,)).fetchone()
            document = evidence_document(context, observations)
            if (proof is None or proof["request_digest"] != grant.request_digest
                    or proof["evidence_json"] != document or proof["evidence_digest"] != sha256(document.encode()).hexdigest()):
                raise MissionConflict("physical send facts differ from the committed intent")
            now_ns = store._now_ns()
            if (now_ns < proof["validated_at_ns"]
                    or not grant.issued_at <= datetime.fromtimestamp(now_ns / 1e9, timezone.utc) < grant.expires_at):
                raise MissionConflict("physical send clock regressed or grant expired")
            store._check_capabilities(capabilities, capabilities_observed_at_ns, now_ns)
            validate_transfer_observations(store.installation.policy, context, observations,
                now_ns=now_ns, authenticated_producer_id=authenticated_producer_id)

    def record_receipt(self, mission_id, response):
        store = self.store
        with closing(store._journal._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = self._state(connection, mission_id)
            grant = FleetArmTransferGrant.model_validate(current["grant"])
            raw = response.model_dump(mode="json") if isinstance(response, DeviceActionReceipt) else response
            parsed = DeviceActionReceipt.model_validate(raw)
            receipt = verify_phase_receipt(grant, parsed, phase_ids=("approach", "grasp", "transfer", "release"))
            canonical = receipt.model_dump(mode="json", exclude={"created"})
            prior = self._last_receipt(connection, mission_id)
            if prior is not None:
                old = prior["receipt"]
                if receipt.journal_event_id < old["journal_event_id"]:
                    return current
                if receipt.journal_event_id == old["journal_event_id"]:
                    if canonical != old:
                        raise MissionConflict("physical receipt watermark was reused with different evidence")
                    return current
                if old["state"] in {"SUCCEEDED", "FAILED", "HOLD"}:
                    raise MissionConflict("a terminal physical owner receipt cannot be replaced")
            proof = connection.execute("SELECT request_digest,validated_at_ns FROM fleet_physical_transfer_observations "
                "WHERE mission_id=? AND phase='PRE_DISPATCH'", (mission_id,)).fetchone()
            if proof is None or proof[0] != grant.request_digest or current["status"] == "PREPARED":
                raise MissionConflict("physical owner receipt requires a committed first-send intent")
            now_ns = store._now_ns()
            now = datetime.fromtimestamp(now_ns / 1e9, timezone.utc)
            if (now_ns < current["prepared_at_ns"] or not grant.issued_at <= receipt.observed_at <= now
                    or _timestamp_ns(receipt.observed_at) <= proof["validated_at_ns"]
                    or any(_timestamp_ns(phase.observed_at) <= proof["validated_at_ns"] for phase in receipt.phase_summaries)
                    or any(not grant.issued_at <= phase.observed_at <= receipt.observed_at for phase in receipt.phase_summaries)
                    or (prior is not None and now_ns < prior["received_at_ns"])):
                raise MissionConflict("physical owner receipt clock is future or regressed")
            job = store._read(connection, mission_id)
            control = connection.execute("SELECT * FROM fleet_dispatch_control WHERE control_id=1").fetchone()
            authority = (control is not None and control["dispatch_enabled"]
                and job["status"] == "RUNNING" and current["status"] == "SUBMITTING"
                and control["authority_epoch"] == grant.authority_epoch and control["generation"] == grant.dispatch_generation
                and self._owns_claims(connection, job, phases={"CLAIMED", "DISPATCHING", "HELD", "UNKNOWN"}))
            state = receipt.state.value
            succeeded = state == "SUCCEEDED" and authority
            active = state in {"PREPARED", "SUBMITTING", "ACCEPTED", "RUNNING"} and authority
            parent_status = "ACTION_SUCCEEDED" if succeeded else "RUNNING" if active else "HOLD"
            attempt_status = "ACTION_SUCCEEDED" if succeeded else "SUBMITTING" if active else "UNKNOWN"
            phase = "HELD" if succeeded else "DISPATCHING" if active else "UNKNOWN"
            reason = None if succeeded or active else "PHYSICAL_ACTION_REQUIRES_RECONCILIATION"
            store._journal._event(connection, mission_id, None, "PHYSICAL_TRANSFER_RECEIPT", "fleet",
                dict(event_id=f"physical-receipt:{receipt.journal_event_id}", receipt=canonical, received_at_ns=now_ns,
                     action_succeeded_at_ns=now_ns if succeeded else None))
            connection.execute("UPDATE fleet_cell_jobs SET status=?,reason=?,updated_at=? WHERE mission_id=?",
                               (parent_status, reason, now.isoformat(), mission_id))
            connection.execute("UPDATE fleet_physical_transfer_attempts SET status=? WHERE mission_id=?", (attempt_status, mission_id))
            connection.execute("UPDATE fleet_action_claims SET phase=? WHERE owner_kind='mission' AND owner_id=?", (phase, mission_id))
            result = self._state(connection, mission_id)
            connection.commit()
            return result
