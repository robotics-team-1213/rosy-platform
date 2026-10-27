"""Single installed simulation profile: persisted first send, then SDK lookup only."""
import asyncio
from contextlib import closing
from datetime import datetime, timezone
import logging

from core_common.protocol.arm_transfer import ArmTransferCapability, FleetArmTransferGrant
from .physical_transfer_store import PhysicalTransferRequest
from .local_action_transport import LocalActionUnavailable
from .physical_transfer_io import physical_io
from .physical_transfer_recovery import find_recovery, recover_transfer, retained_snapshot

_LOG = logging.getLogger(__name__)


class PhysicalTransferDispatcher:
    def __init__(self, execution, transport, task_store, *, deployment_profile):
        if deployment_profile != "simulation":
            raise ValueError("physical SDK dispatch requires the simulation profile")
        if execution.store._journal.path.resolve() != task_store.path.resolve():
            raise ValueError("physical SDK dispatch requires the shared Fleet journal")
        if any(not callable(getattr(transport, name, None)) for name in (
                "owner_identity", "transfer_capability", "submit", "get", "cancel")):
            raise ValueError("physical SDK dispatch requires the complete owner SDK")
        self.execution, self.transport, self.task_store = execution, transport, task_store
        self._journal_path = execution.store._journal.path.resolve()

    def _capabilities(self):
        store = self.execution.store
        observed_at_ns = store._now_ns()
        capabilities = []
        for participant in store.installation.policy.participants:
            identity = self.transport.owner_identity(participant.instance_id)
            cap = ArmTransferCapability.model_validate(self.transport.transfer_capability(
                participant.instance_id, workcell_id=participant.workcell_id))
            if (identity.get("simulation") is not True
                    or (identity.get("workcell_id"), identity.get("instance_id"), identity.get("journal_id"))
                       != (participant.workcell_id, participant.instance_id, cap.journal_id)
                    or (cap.workcell_id, cap.instance_id) != (participant.workcell_id, participant.instance_id)):
                raise LocalActionUnavailable("physical owner simulation identity changed")
            capabilities.append(cap)
        store._check_capabilities(capabilities, observed_at_ns, store._now_ns())
        return tuple(capabilities), observed_at_ns

    def prepare(self, mission_id):
        with physical_io(self._journal_path):
            try:
                capabilities, observed_at_ns = self._capabilities()
                return self.execution.prepare(mission_id, capabilities=capabilities,
                    capabilities_observed_at_ns=observed_at_ns)
            except Exception:
                self.execution.hold(mission_id, reason="PHYSICAL_PREPARATION_UNAVAILABLE")
                raise

    def recover(self, mission_id, *, proposer, principal, expected_request_digest,
                expected_receipt_event_id, expected_assessment_digest, expected_generation,
                observations, authenticated_producer_id):
        request = dict(proposer=proposer, principal=principal, expected_request_digest=expected_request_digest,
            expected_receipt_event_id=expected_receipt_event_id, expected_assessment_digest=expected_assessment_digest,
            expected_generation=expected_generation, observations=observations,
            authenticated_producer_id=authenticated_producer_id)
        with physical_io(self._journal_path):
            child = find_recovery(self.execution, mission_id, **request)
            if child is None:
                capabilities, observed_at_ns = self._capabilities()
                child = recover_transfer(self.execution, mission_id, **request,
                    capabilities=capabilities, capabilities_observed_at_ns=observed_at_ns)
            prepared = retained_snapshot(self.execution, child["mission_id"])
            if prepared is None and child["status"] == "READY":
                self.prepare(child["mission_id"])
                prepared = retained_snapshot(self.execution, child["mission_id"])
            return dict(job=child, execution=prepared)

    def submit(self, mission_id, *, observations, authenticated_producer_id):
        if not isinstance(observations, (tuple, list)):
            raise ValueError("physical observations require a bounded sample sequence")
        observations = tuple(observations)
        with physical_io(self._journal_path):
            current = self.execution.snapshot(mission_id)
            if current["status"] != "PREPARED":
                return current
            try:
                capabilities, observed_at_ns = self._capabilities()
            except Exception:
                return self.execution.hold(mission_id, reason="PHYSICAL_OWNER_UNAVAILABLE_BEFORE_SEND")
            intent = self.execution.authorize_submission(mission_id,
                expected_request_digest=current["grant"]["request_digest"], observations=observations,
                authenticated_producer_id=authenticated_producer_id, capabilities=capabilities,
                capabilities_observed_at_ns=observed_at_ns)
            grant = FleetArmTransferGrant.model_validate(intent["grant"])
            try:
                control = self.task_store.dispatch_control()
                if (not control["dispatch_enabled"] or control["authority_epoch"] != grant.authority_epoch
                        or control["generation"] != grant.dispatch_generation):
                    return self.execution.hold(mission_id, reason="PHYSICAL_FENCE_CHANGED_BEFORE_SEND")
                self.execution.validate_send(mission_id, expected_request_digest=grant.request_digest,
                    observations=observations, authenticated_producer_id=authenticated_producer_id,
                    capabilities=capabilities, capabilities_observed_at_ns=observed_at_ns)
                return self.execution.record_receipt(mission_id, self.transport.submit(grant))
            except Exception:
                return self.execution.hold(mission_id, reason="PHYSICAL_SUBMIT_OUTCOME_UNKNOWN")

    def refresh(self, mission_id):
        with physical_io(self._journal_path):
            current = self.execution.snapshot(mission_id)
            if not current["first_send_committed"] or current["status"] == "ACTION_SUCCEEDED":
                return current
            try:
                self._capabilities()
                response = self.transport.get(FleetArmTransferGrant.model_validate(current["grant"]))
                if response is None:
                    raise LocalActionUnavailable("physical action absence is not clearance proof")
                return self.execution.record_receipt(mission_id, response)
            except Exception:
                return self.execution.hold(mission_id, reason="PHYSICAL_LOOKUP_OUTCOME_UNKNOWN")

    def cancel(self, mission_id, *, reason):
        with physical_io(self._journal_path):
            current = self.execution.snapshot(mission_id)
            if current["status"] == "ACTION_SUCCEEDED":
                return current
            held = self.execution.hold(mission_id, reason="PHYSICAL_CANCEL_REQUESTED")
            if not current["first_send_committed"]:
                return held
            try:
                self._capabilities()
                response = self.transport.cancel(FleetArmTransferGrant.model_validate(current["grant"]), reason=reason)
                return self.execution.record_receipt(mission_id, response)
            except Exception:
                return held

    def tick(self):
        store = self.execution.store
        installed, policy = store.installation, store.installation.policy
        document = store._document(PhysicalTransferRequest(workcell_id=policy.primary[0], instance_id=policy.primary[1],
            object_ref=policy.object_ref, source=installed.source, target=installed.target))
        with physical_io(self._journal_path):
            with closing(store._journal._connect()) as connection:
                rows = connection.execute("SELECT a.mission_id FROM fleet_physical_transfer_attempts a "
                    "JOIN fleet_cell_jobs j ON j.mission_id=a.mission_id WHERE j.provenance_kind='physical' "
                    "AND j.job_json=? AND j.status IN ('READY','RUNNING','HOLD') "
                    "AND a.status IN ('PREPARED','SUBMITTING','UNKNOWN') ORDER BY a.prepared_at_ns", (document,)).fetchall()
                candidates = [(row["mission_id"], self.execution._last_receipt(connection, row["mission_id"])) for row in rows]
            for mission_id, latest in candidates:
                if latest is not None and latest["receipt"]["state"] in {"SUCCEEDED", "FAILED", "HOLD"}:
                    continue
                current = self.execution.snapshot(mission_id)
                if current["status"] == "PREPARED":
                    grant = FleetArmTransferGrant.model_validate(current["grant"])
                    now_ns = store._now_ns()
                    if (now_ns < current["prepared_at_ns"]
                            or datetime.fromtimestamp(now_ns / 1e9, timezone.utc) >= grant.expires_at):
                        return self.execution.hold(mission_id, reason="PHYSICAL_OBSERVATION_WINDOW_EXPIRED")
                    return current
                return self.refresh(mission_id)
        return None

    async def run(self):
        while True:
            try:
                await asyncio.to_thread(self.tick)
            except Exception:
                _LOG.exception("Physical receipt monitor failed")
            await asyncio.sleep(.25)
