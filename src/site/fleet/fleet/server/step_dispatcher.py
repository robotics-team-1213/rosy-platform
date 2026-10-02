"""Fleet dispatcher for the ordered step ledger: one local Action per step (D-403 §5, §7).

Step k is submitted only when the ledger has made it the current READY step, which happens only
after step k-1 is GOAL_CONFIRMED. A RUNNING step is reconciled with GetAction and never
resubmitted. A device refusal, failure or unknown outcome HOLDs the Job with a reason (D-403 §9:
not FAILED); the operator reconciles it. Everything that differs by Action kind comes from
``step_action_kinds``; this module holds no kind-specific rule.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from core_common.protocol.schemas import DeviceActionReceipt

from .cell_job_store import CellJobStore
from .local_action_transport import DeviceActionTransport, LocalActionRejected
from .mission_store import MissionConflict
from .step_action_kinds import dispatch_open, open_kinds, rejection_reason, step_action_kind, step_grant_digest
from .task_store import FleetTaskStore

_IN_FLIGHT = {"PREPARED", "SUBMITTING", "ACCEPTED", "RUNNING", "CANCEL_REQUESTED"}
_ACTOR = "mission-dispatcher"
_LOG = logging.getLogger(__name__)
# GetAction readback (1b A3). A transport failure is retried with backoff before the outcome is
# called UNKNOWN. Basis: one UDS exchange is bounded at 0.25 s (D-336 client) and the grant TTL is
# 15 s; 5 failures spaced 0.5+1+2+4 s span ~8 s plus the reads themselves, so a briefly busy or
# restarting owner is not declared UNKNOWN, while a dead owner is within about one grant lifetime.
READBACK_FAILURE_LIMIT = 5
READBACK_BACKOFF_S = (0.5, 1.0, 2.0, 4.0)


class StepJobDispatcher:
    """Single Fleet-owned submitter for admitted step-ledger Jobs on configured instances."""

    def __init__(self, store: CellJobStore, task_store: FleetTaskStore,
                 transport: DeviceActionTransport, omx_instances: Mapping[str, str],
                 grant_revisions: Mapping[str, Mapping[str, str]], *, deployment_profile: str,
                 now: Callable[[], datetime] | None = None, grant_ttl_s: float = 15.0,
                 on_step_action_succeeded: Callable[[Mapping[str, Any], int], object] | None = None,
                 monotonic: Callable[[], float] = time.monotonic,
                 ) -> None:
        if not open_kinds(deployment_profile):
            raise ValueError(f"step-ledger dispatch is closed for profile {deployment_profile!r} (D-403 §7)")
        self.omx_instances = dict(omx_instances)
        if not self.omx_instances:
            raise ValueError("step-ledger dispatcher requires configured OMX workcells")
        missing = [instance for instance in self.omx_instances.values()
                   if set(grant_revisions.get(instance, {})) != {"capability_revision", "config_revision"}]
        if missing:
            raise ValueError(f"simulation grant revisions are missing for instances {missing}")
        if (isinstance(grant_ttl_s, bool) or not isinstance(grant_ttl_s, (int, float))
                or not 1.0 <= float(grant_ttl_s) <= 60.0):
            raise ValueError("Action grant TTL must be between 1 and 60 seconds")
        self.store, self.task_store, self.transport = store, task_store, transport
        self.grant_revisions = {key: dict(value) for key, value in grant_revisions.items()}
        self.deployment_profile = deployment_profile
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.grant_ttl_s = float(grant_ttl_s)
        self.on_step_action_succeeded = on_step_action_succeeded
        self.monotonic = monotonic
        self._readback: dict[str, tuple[int, float]] = {}  # action_id -> (failures, next read at)

    def dispatch_next(self) -> dict[str, Any] | None:
        """One cycle over every Job (1b B1): read back each in-flight or unresolved Job under its
        own backoff, then submit every actionable READY Job. No Job blocks another; a READY Job on
        an unconfigured instance or a closed kind is skipped and left untouched."""
        outcomes = [self._reconcile(job) for job in
                    self.store.jobs("RUNNING") + self.store.next_unresolved() if self._due(job)]
        outcomes += [self._submit(job) for job in self.store.jobs("READY")]
        acted = [item for item in outcomes if item is not None and item["state"] not in _SKIPPED]
        skipped = [item for item in outcomes if item is not None]
        return acted[0] if acted else (skipped[0] if skipped else None)

    def reconcile(self, mission_id: str) -> dict[str, Any]:
        """Operator readback of one Job now, ignoring the backoff window."""
        job = self.store.get(mission_id)
        if job is None:
            raise KeyError(mission_id)
        step = job["steps"][job["current_step_index"]] if job["current_step_index"] < len(job["steps"]) else None
        if step is None or step["grant"] is None or job["status"] not in {"RUNNING", "HOLD"}:
            return self._view(job, job["current_step_index"], job["status"])
        self._readback.pop(step["action_id"], None)
        return self._reconcile(job)

    def _due(self, job: Mapping[str, Any]) -> bool:
        action_id = job["steps"][job["current_step_index"]]["action_id"]
        return self._readback.get(action_id, (0, 0.0))[1] <= self.monotonic()

    def _submit(self, job: Mapping[str, Any]) -> dict[str, Any] | None:
        index = job["current_step_index"]
        step = job["steps"][index]
        if not dispatch_open(self.deployment_profile, step["action_kind"]):
            return self._view(job, index, "NOT_OPEN")
        if (self.omx_instances.get(job["workcell_id"]) != job["instance_id"]
                or job["instance_id"] not in self.grant_revisions):
            return self._view(job, index, "NOT_CONFIGURED")
        try:
            grant = self._grant(job, step)
            started = self.store.start_step(job["mission_id"], step_index=index, action_id=grant.action_id,
                                            attempt_id=grant.attempt_id, grant=grant.model_dump(mode="json"),
                                            now=self.now())
        except MissionConflict:
            return self._view(self.store.get(job["mission_id"]), index, None)
        except (KeyError, TypeError, ValueError):
            # Nothing was started or sent (1b B3): release the claims with the reason.
            held = self.store.hold(job["mission_id"], reason="ACTION_GRANT_INVALID", claim_phase=None,
                                   actor_id=_ACTOR, event_key=f"grant-invalid:{index}", not_submitted=True)
            return self._view(held, index, "HOLD")
        if started["status"] != "RUNNING":
            return self._view(started, index, started["status"])
        control = self.task_store.dispatch_control()
        if (not control["dispatch_enabled"] or control["authority_epoch"] != grant.authority_epoch
                or control["generation"] != grant.dispatch_generation):
            # Pre-send hold: nothing was sent, so the claims are released (D-420 §4.5 row 1).
            held = self.store.hold(job["mission_id"], reason="FLEET_FENCE_CHANGED_BEFORE_LOCAL_SUBMIT",
                                   claim_phase=None, actor_id=_ACTOR,
                                   event_key=f"fence-before-send:{grant.action_id}", not_submitted=True)
            return self._view(held, index, "HOLD")
        try:
            receipt = self.transport.submit(grant)
        except LocalActionRejected as exc:
            code = str(exc).split(":", 1)[0]
            return self._outcome(job, index, grant, "REJECTED", rejection_reason(grant.action_kind, code),
                                 {"detail": str(exc)[:256]})
        except Exception:
            return self._outcome(job, index, grant, "UNKNOWN", "LOCAL_ACTION_SUBMIT_OUTCOME_UNKNOWN", {})
        return self._apply(job, index, grant, receipt)

    def _grant(self, job: Mapping[str, Any], step: Mapping[str, Any]):
        kind = step_action_kind(step["action_kind"])
        now = self.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Fleet clock must return timezone-aware time")
        revisions = self.grant_revisions[job["instance_id"]]
        document = {
            "mission_id": job["mission_id"], "step_id": step["step_id"],
            "action_id": str(uuid.uuid4()), "attempt_id": str(uuid.uuid4()),
            "request_digest": "0" * 64, "workcell_id": job["workcell_id"],
            "instance_id": job["instance_id"], "action_kind": kind.action_kind,
            kind.body_field: kind.body(job, step["step_index"], step["step"]["inputs"]),
            "capability_revision": revisions["capability_revision"],
            "config_revision": revisions["config_revision"],
            "authority_epoch": job["authority_epoch"],
            "dispatch_generation": job["dispatch_generation"],
            "issued_at": now, "expires_at": now + timedelta(seconds=self.grant_ttl_s),
        }
        document["request_digest"] = step_grant_digest(kind.grant_model.model_validate(document))
        return kind.grant_model.model_validate(document)

    def _reconcile(self, job: Mapping[str, Any]) -> dict[str, Any]:
        index = job["current_step_index"]
        try:
            grant = step_action_kind(job["steps"][index]["action_kind"]).grant_model.model_validate(
                job["steps"][index]["grant"])
        except (KeyError, TypeError, ValueError):
            return self._outcome(job, index, None, "UNKNOWN", "PERSISTED_ACTION_GRANT_MISSING", {})
        try:
            receipt = self.transport.get(grant)
        except Exception:
            failures = self._readback.get(grant.action_id, (0, 0.0))[0] + 1
            if failures < READBACK_FAILURE_LIMIT:
                delay = READBACK_BACKOFF_S[min(failures, len(READBACK_BACKOFF_S)) - 1]
                self._readback[grant.action_id] = (failures, self.monotonic() + delay)
                return self._view(job, index, "READBACK_RETRY", grant)
            self._readback.pop(grant.action_id, None)
            return self._outcome(job, index, grant, "UNKNOWN", "LOCAL_ACTION_READBACK_UNKNOWN", {})
        self._readback.pop(grant.action_id, None)
        if receipt is None:
            # GetAction 404: the owner never journaled this attempt, so nothing ran.
            return self._outcome(job, index, grant, "NOT_FOUND", "LOCAL_ACTION_NOT_FOUND_AFTER_SUBMIT", {})
        return self._apply(job, index, grant, receipt)

    def _apply(self, job: Mapping[str, Any], index: int, grant, receipt: object) -> dict[str, Any]:
        try:
            verified = self._verified(grant, receipt)
        except (TypeError, ValueError):
            return self._outcome(job, index, grant, "UNKNOWN", "LOCAL_ACTION_RECEIPT_INVALID", {})
        state = verified.state.value
        if state in _IN_FLIGHT:
            return self._view(job, index, state, grant)
        facts = {"state": state, "journal_event_id": verified.journal_event_id,
                 "observed_at": verified.observed_at.isoformat(), "device_reason": verified.reason}
        event_id = "device:" + hashlib.sha256(
            f"{grant.instance_id}:{grant.action_id}:{grant.attempt_id}:{verified.journal_event_id}"
            .encode("utf-8")).hexdigest()
        if state == "SUCCEEDED":
            return self._outcome(job, index, grant, "SUCCEEDED", None, facts, event_id=event_id)
        if state == "FAILED":
            return self._outcome(job, index, grant, "FAILED", "LOCAL_ACTION_FAILED", facts, event_id=event_id)
        # A device HOLD or UNKNOWN may leave an object held: the claims stay pinned (D-403 §6).
        return self._outcome(job, index, grant, "UNKNOWN", f"LOCAL_ACTION_{state}", facts, event_id=event_id)

    @staticmethod
    def _verified(grant, receipt: object) -> DeviceActionReceipt:
        verified = receipt if isinstance(receipt, DeviceActionReceipt) else DeviceActionReceipt.model_validate(
            receipt["receipt"] if isinstance(receipt, Mapping) and "receipt" in receipt else receipt)
        identity = ("mission_id", "step_id", "action_id", "attempt_id", "workcell_id", "instance_id",
                    "request_digest", "authority_epoch", "dispatch_generation")
        if any(getattr(verified, name) != getattr(grant, name) for name in identity):
            raise ValueError("local Action receipt does not match its Fleet grant")
        if verified.phase_summaries is None:
            raise ValueError("step-ledger receipts must carry phase summaries")
        phases = step_action_kind(grant.action_kind).phase_ids
        if verified.state.value == "SUCCEEDED" and (
                tuple(phase.phase_id for phase in verified.phase_summaries) != phases
                or any(phase.state != "SUCCEEDED" for phase in verified.phase_summaries)):
            raise ValueError("a successful receipt requires every phase to succeed in order")
        return verified

    def _outcome(self, job: Mapping[str, Any], index: int, grant, outcome: str, reason: str | None,
                 result: Mapping[str, Any], *, event_id: str | None = None) -> dict[str, Any]:
        step = job["steps"][index]
        action_id = grant.action_id if grant is not None else step["action_id"]
        attempt_id = grant.attempt_id if grant is not None else step["attempt_id"]
        if job["status"] == "HOLD" and outcome == "UNKNOWN":
            return self._view(job, index, "HOLD", grant)  # still unresolved; keep reading back
        event_id = event_id or "dispatch:" + hashlib.sha256(
            f"{action_id}:{attempt_id}:{outcome}:{reason}".encode("utf-8")).hexdigest()
        try:
            recorded = self.store.record_action_result(
                job["mission_id"], step_index=index, event_id=event_id, action_id=action_id,
                attempt_id=attempt_id, outcome=outcome, reason=reason, result=result,
            )
        except MissionConflict:
            # 1b B6: a reused event id or a moved attempt is not retried forever; an operator looks.
            _LOG.exception("Cell Job %s step %s result could not be recorded", job["mission_id"], index)
            return self._view(self.store.get(job["mission_id"]), index, "RESULT_CONFLICT", grant)
        if outcome == "SUCCEEDED" and self.on_step_action_succeeded is not None:
            self.on_step_action_succeeded(recorded, index)
        return self._view(recorded, index, recorded["status"], grant)

    @staticmethod
    def _view(job: Mapping[str, Any] | None, index: int, state: str | None, grant=None) -> dict[str, Any]:
        if job is None:
            return {"state": state or "HOLD", "step_index": index}
        return {"mission_id": job["mission_id"], "step_index": index,
                "state": state or job["status"], "reason": job.get("reason"),
                "action_id": grant.action_id if grant is not None else None}


_SKIPPED = {"NOT_OPEN", "NOT_CONFIGURED"}

__all__ = ["READBACK_FAILURE_LIMIT", "StepJobDispatcher"]
