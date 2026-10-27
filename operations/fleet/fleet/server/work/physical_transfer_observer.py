"""One host-installed observer submits facts independently of applications and operators."""
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
import hmac

from core_common.protocol.arm_transfer import FleetArmTransferGrant
from .mission_store import MissionConflict, _json
from .physical_transfer_evidence import TransferEvidenceContext
from .physical_transfer_io import physical_io
from .physical_transfer_observations import evidence_document, world_observations
from .physical_transfer_outcomes import record_transfer_outcome
from .physical_transfer_recovery import CREATED
from .physical_transfer_store import PhysicalTransferRequest


@dataclass(frozen=True)
class PhysicalTransferObserver:
    producer_id: str
    token: str = field(repr=False)
    valid_until: datetime

    def __post_init__(self):
        for name, minimum, maximum in (("producer_id", 1, 96), ("token", 32, 512)):
            value = getattr(self, name)
            if (not isinstance(value, str) or not minimum <= len(value) <= maximum or value != value.strip()
                    or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value)):
                raise ValueError("invalid physical observer configuration")
        if not isinstance(self.valid_until, datetime) or self.valid_until.utcoffset() is None:
            raise ValueError("physical observer expiry must have a timezone")

    def authenticates(self, token, *, now):
        return (isinstance(token, str) and hmac.compare_digest(self.token.encode(), token.encode())
                and now < self.valid_until.timestamp())


def validate_observer(observer, installation, *, console, principals, other_tokens=(), other_services=(), registries=()):
    if not isinstance(observer, PhysicalTransferObserver) or installation is None:
        raise ValueError("physical observer requires an installed physical transfer profile")
    if observer.producer_id != installation.policy.producer_id:
        raise ValueError("physical observer must match the installed producer identity")
    reserved = tuple(other_tokens) + tuple(p.token for registry in registries if registry is not None
                                           for p in registry.producers)
    token, digest = observer.token, sha256(observer.token.encode()).hexdigest()
    if (any(other is not None and hmac.compare_digest(token.encode(), other.encode()) for other in reserved)
            or digest in principals or console.user_credential_overlaps_robot_secret((digest,))
            or any(p.principal_id == observer.producer_id for p in principals.values())
            or any(service is not None and service.uses_token(token) for service in other_services)):
        raise ValueError("physical observer credential and identity must be independent")


class PhysicalObservationService:
    def __init__(self, dispatcher, observer):
        self.dispatcher, self.observer = dispatcher, observer
        self.execution, self.store = dispatcher.execution, dispatcher.execution.store

    def _job(self, connection, mission_id):
        job = self.store._read(connection, mission_id)
        if job is None:
            raise KeyError(mission_id)
        request = PhysicalTransferRequest.model_validate(job["request"])
        if self.store._document(request) != _json({"request": job["request"], "installation": job["installation"]}):
            raise PermissionError("physical job is outside the installed observer scope")
        return job

    def context(self):
        with closing(self.store._journal._connect()) as connection:
            rows = connection.execute("SELECT a.mission_id FROM fleet_physical_transfer_attempts a "
                "JOIN fleet_cell_jobs j ON j.mission_id=a.mission_id "
                "WHERE j.provenance_kind='physical' AND j.status!='GOAL_CONFIRMED' ORDER BY a.prepared_at_ns DESC").fetchall()
            for row in rows:
                if connection.execute("SELECT 1 FROM fleet_cell_events WHERE mission_id=? AND event_type=?",
                                      (row["mission_id"], CREATED)).fetchone() is not None:
                    continue
                try:
                    self._job(connection, row["mission_id"])
                except PermissionError:
                    continue
                state = self.execution._state(connection, row["mission_id"])
                grant = FleetArmTransferGrant.model_validate(state["grant"])
                policy = self.store.installation.policy
                caps = {(c.workcell_id, c.instance_id): c for c in self.store.installation.capabilities}
                owners = [dict(workcell_id=p.workcell_id, instance_id=p.instance_id,
                    journal_id=caps[p.workcell_id, p.instance_id].journal_id,
                    owner_session_id=caps[p.workcell_id, p.instance_id].owner_session_id,
                    model_digest=p.geometry.model_digest, calibration_revision=p.calibration_revision,
                    transform_revision=p.transform_revision) for p in policy.participants]
                return dict(mission_id=row["mission_id"], request_digest=grant.request_digest,
                    action_id=grant.action_id, attempt_id=grant.attempt_id, status=state["status"],
                    phase=state["context"]["phase"], not_before_ns=state["context"]["not_before_ns"],
                    capture_deadline=grant.expires_at if state["context"]["phase"] == "PRE_DISPATCH" else None,
                    producer_id=policy.producer_id, evaluator_revision=policy.evaluator_revision, frame_id=policy.frame_id,
                    policy_digest=policy.digest, catalog_digest=policy.catalog_digest, bindings_digest=policy.bindings_digest,
                    object_ref=policy.object_ref, object_origin_id=policy.object_origin_id,
                    min_separation_ns=policy.min_separation_ns, max_age_ns=policy.max_age_ns, owners=owners)
        return None

    def receipt(self, mission_id):
        with closing(self.store._journal._connect()) as connection:
            job = self._job(connection, mission_id)
            proof = connection.execute("SELECT * FROM fleet_physical_transfer_observations "
                "WHERE mission_id=? AND phase='POST_ACTION'", (mission_id,)).fetchone()
            if proof is None or job["status"] != "GOAL_CONFIRMED":
                return None
            state = self.execution._state(connection, mission_id)
            grant = FleetArmTransferGrant.model_validate(state["grant"])
            if (proof["request_digest"] != grant.request_digest
                    or sha256(proof["evidence_json"].encode()).hexdigest() != proof["evidence_digest"]):
                raise MissionConflict("physical receipt evidence changed")
            return self.execution._physical_receipt(proof, grant)

    def observe(self, mission_id, body):
        samples = world_observations(body.observations)
        if any(s.producer_id != self.observer.producer_id for s in samples):
            raise PermissionError("physical sample producer is outside the authenticated scope")
        with physical_io(self.store._journal.path):
            with closing(self.store._journal._connect()) as connection:
                self._job(connection, mission_id)
                state = self.execution._state(connection, mission_id)
                if state["grant"]["request_digest"] != body.expected_request_digest:
                    raise MissionConflict("physical observation targets a different request")
                prior = connection.execute("SELECT * FROM fleet_physical_transfer_observations "
                    "WHERE mission_id=? AND phase=?", (mission_id, body.phase)).fetchone()
                if body.phase == "PRE_DISPATCH" and prior is not None:
                    context = TransferEvidenceContext.model_validate_json(_json({**state["context"],
                        "phase": "PRE_DISPATCH", "not_before_ns": state["prepared_at_ns"]}))
                    document = evidence_document(context, samples)
                    if (prior["evidence_json"] != document or prior["request_digest"] != body.expected_request_digest
                            or prior["evidence_digest"] != sha256(document.encode()).hexdigest()):
                        raise MissionConflict("committed physical evidence cannot be replaced")
                    return
            if body.phase == "PRE_DISPATCH":
                self.dispatcher.submit(mission_id, observations=samples,
                    authenticated_producer_id=self.observer.producer_id)
            else:
                capabilities, at = ((), self.store._now_ns()) if prior is not None else self.dispatcher._capabilities()
                if prior is None:
                    record_transfer_outcome(self.execution, mission_id, body.expected_request_digest, samples,
                                            authenticated_producer_id=self.observer.producer_id)
                self.execution.confirm_physical(mission_id, expected_request_digest=body.expected_request_digest,
                    observations=samples, authenticated_producer_id=self.observer.producer_id,
                    capabilities=capabilities, capabilities_observed_at_ns=at)
