"""Single Fleet-owned dispatcher for approved OMX Mission Actions."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from core_common.protocol.schemas import (
    DeviceActionPhaseReceipt, DeviceActionReceipt, FleetActionGrant,
)

from .action_receipts import verify_phase_receipt
from .local_action_transport import (
    DeviceActionTransport,
    LocalActionRejected,
)
from .mission_service import MissionService
from .mission_store import MissionConflict
from .task_store import FleetTaskStore


_TERMINAL = {"SUCCEEDED", "FAILED", "UNKNOWN", "HOLD"}


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _grant_digest(grant: FleetActionGrant) -> str:
    document = grant.model_dump(mode="json", exclude={"request_digest"})
    return hashlib.sha256(_canonical(document)).hexdigest()


class MissionDispatcher:
    """Submit a READY Mission once, then reconcile its stable attempt via GetAction."""

    def __init__(self, mission_service: MissionService, task_store: FleetTaskStore,
                 transport: DeviceActionTransport,
                 omx_instances: Mapping[str, str], *,
                 now: Callable[[], datetime] | None = None,
                 grant_ttl_s: float = 15.0,
                 on_action_terminal: Callable[[str], object] | None = None) -> None:
        self.mission_service = mission_service
        self.task_store = task_store
        self.transport = transport
        self.omx_instances = dict(omx_instances)
        if not self.omx_instances:
            raise ValueError("Mission dispatcher requires configured OMX workcells")
        if (isinstance(grant_ttl_s, bool) or not isinstance(grant_ttl_s, (int, float))
                or not 1.0 <= float(grant_ttl_s) <= 60.0):
            raise ValueError("Action grant TTL must be between 1 and 60 seconds")
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.grant_ttl_s = float(grant_ttl_s)
        self.on_action_terminal = on_action_terminal

    def dispatch_next(self) -> dict[str, Any] | None:
        running = self.mission_service.next_running()
        if running is not None:
            return self._reconcile(running)
        pending = self.mission_service.next_reconciliation()
        if pending is not None:
            return self._reconcile(pending)

        mission = self.mission_service.next_ready()
        if mission is None:
            return None
        if self.omx_instances.get(mission["workcell_id"]) != mission["instance_id"]:
            return {"mission_id": mission["mission_id"], "state": "NOT_CONFIGURED"}
        if (type(mission.get("authority_epoch")) is not int
                or type(mission.get("dispatch_generation")) is not int):
            self.mission_service.store.hold_ready(
                mission["mission_id"], actor_id="mission-dispatcher",
                reason="MISSION_FENCE_MISSING",
            )
            return {"mission_id": mission["mission_id"], "state": "HOLD"}
        try:
            grant = self._grant(mission)
        except (KeyError, TypeError, ValueError):
            self.mission_service.store.hold_ready(
                mission["mission_id"], actor_id="mission-dispatcher",
                reason="ACTION_GRANT_INVALID",
            )
            return {"mission_id": mission["mission_id"], "state": "HOLD"}

        try:
            self.mission_service.start_step(
                mission["mission_id"], action_id=grant.action_id,
                attempt_id=grant.attempt_id,
                expected_authority_epoch=grant.authority_epoch,
                expected_generation=grant.dispatch_generation,
                action_grant=grant.model_dump(mode="json"),
            )
        except MissionConflict:
            current = self.mission_service.get(mission["mission_id"])
            return {"mission_id": mission["mission_id"],
                    "state": current["status"] if current else "HOLD"}

        current = self.task_store.dispatch_control()
        if (not current["dispatch_enabled"]
                or current["authority_epoch"] != grant.authority_epoch
                or current["generation"] != grant.dispatch_generation):
            return self._record_outcome(
                grant, "HOLD", {"reason": "FLEET_FENCE_CHANGED_BEFORE_LOCAL_SUBMIT"},
            )
        try:
            response = self.transport.submit(grant)
            receipt = self._verified_receipt(grant, response)
        except LocalActionRejected as exc:
            return self._record_outcome(
                grant, "FAILED", {"reason": "LOCAL_ACTION_REJECTED", "detail": str(exc)},
            )
        except Exception:
            return self._record_outcome(
                grant, "UNKNOWN", {"reason": "LOCAL_ACTION_SUBMIT_OUTCOME_UNKNOWN"},
            )
        return self._apply_receipt(grant, receipt)

    def _grant(self, mission: Mapping[str, Any]) -> FleetActionGrant:
        plan = mission["plan"]
        now = self.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Fleet clock must return timezone-aware time")
        document = {
            "mission_id": mission["mission_id"], "step_id": mission["step_id"],
            "action_id": str(uuid.uuid4()), "attempt_id": str(uuid.uuid4()),
            "request_digest": "0" * 64,
            "workcell_id": mission["workcell_id"], "instance_id": mission["instance_id"],
            "action_kind": mission["action_kind"],
            "source_evidence": plan["source_evidence"],
            "destination_evidence": plan["destination_evidence"],
            "capability_revision": plan["capability_revision"],
            "config_revision": plan["config_revision"],
            "observation_revision": plan["observation_revision"],
            "authority_epoch": mission["authority_epoch"],
            "dispatch_generation": mission["dispatch_generation"],
            "issued_at": now,
            "expires_at": now + timedelta(seconds=self.grant_ttl_s),
        }
        provisional = FleetActionGrant.model_validate(document)
        document["request_digest"] = _grant_digest(provisional)
        return FleetActionGrant.model_validate(document)

    @staticmethod
    def _verified_receipt(grant: FleetActionGrant,
                          response: object) -> DeviceActionReceipt:
        return verify_phase_receipt(grant, response)

    def _reconcile(self, mission: Mapping[str, Any]) -> dict[str, Any]:
        was_pending = bool(mission.get("reconciliation_pending"))
        try:
            grant = self._grant_from_mission(mission)
        except (KeyError, TypeError, ValueError):
            identity = "dispatch:missing-grant:" + hashlib.sha256(
                f"{mission['mission_id']}:{mission['action_id']}:{mission['attempt_id']}"
                .encode("utf-8")
            ).hexdigest()
            held = self.mission_service.record_action_result(
                mission["mission_id"], event_id=identity,
                action_id=mission["action_id"], attempt_id=mission["attempt_id"],
                outcome="UNKNOWN", result={"reason": "PERSISTED_ACTION_GRANT_MISSING"},
            )
            return {"mission_id": mission["mission_id"], "state": held["status"],
                    "reason": held["reason"]}
        try:
            receipt = self.transport.get(grant)
            if receipt is None:
                if was_pending:
                    self.mission_service.finish_reconciliation(
                        grant.mission_id, action_id=grant.action_id,
                        attempt_id=grant.attempt_id,
                    )
                    return {"mission_id": grant.mission_id, "action_id": grant.action_id,
                            "attempt_id": grant.attempt_id, "state": "HOLD",
                            "reason": "LOCAL_ACTION_NOT_FOUND_AFTER_SUBMIT"}
                return self._record_outcome(
                    grant, "UNKNOWN", {"reason": "LOCAL_ACTION_NOT_FOUND_AFTER_SUBMIT"},
                )
            verified = self._verified_receipt(grant, receipt)
        except Exception:
            return self._record_outcome(
                grant, "UNKNOWN", {"reason": "LOCAL_ACTION_READBACK_UNKNOWN"},
            )
        if was_pending and verified.state.value not in _TERMINAL:
            self.mission_service.finish_reconciliation(
                grant.mission_id, action_id=grant.action_id,
                attempt_id=grant.attempt_id,
            )
            return {"mission_id": grant.mission_id, "action_id": grant.action_id,
                    "attempt_id": grant.attempt_id, "state": "HOLD",
                    "reason": "LOCAL_ACTION_STILL_NONTERMINAL"}
        return self._apply_receipt(grant, verified)

    def _grant_from_mission(self, mission: Mapping[str, Any]) -> FleetActionGrant:
        raw = mission.get("action_grant")
        if not isinstance(raw, Mapping):
            raise ValueError("Mission has no persisted Action grant")
        grant = FleetActionGrant.model_validate(raw)
        if (grant.mission_id != mission["mission_id"]
                or grant.step_id != mission["step_id"]
                or grant.action_id != mission["action_id"]
                or grant.attempt_id != mission["attempt_id"]
                or grant.authority_epoch != mission["authority_epoch"]
                or grant.dispatch_generation != mission["dispatch_generation"]):
            raise ValueError("persisted Action grant does not match the Mission attempt")
        return grant

    def _apply_receipt(self, grant: FleetActionGrant,
                       receipt: DeviceActionReceipt) -> dict[str, Any]:
        try:
            phases = [DeviceActionPhaseReceipt.model_validate(phase).model_dump(mode="json")
                      for phase in (receipt.phase_summaries or ())]
            self.mission_service.store.record_action_phase_summaries(
                grant.mission_id, action_id=grant.action_id,
                attempt_id=grant.attempt_id, authority_epoch=grant.authority_epoch,
                dispatch_generation=grant.dispatch_generation, phases=phases,
            )
        except Exception:
            return self._record_outcome(
                grant, "UNKNOWN", {"reason": "LOCAL_ACTION_PHASE_READBACK_CONFLICT"},
            )
        state = receipt.state.value
        if state in _TERMINAL:
            outcome = "SUCCEEDED" if state == "SUCCEEDED" else state
            return self._record_outcome(grant, outcome, {
                "state": state, "driver_goal_id": receipt.driver_goal_id,
                "journal_event_id": receipt.journal_event_id,
                "observed_at": receipt.observed_at.isoformat(),
                "reason": receipt.reason,
            }, event_id=self._receipt_event_id(grant, receipt))
        return {
            "mission_id": grant.mission_id, "action_id": grant.action_id,
            "attempt_id": grant.attempt_id, "state": state,
            "journal_event_id": receipt.journal_event_id,
        }

    def _record_outcome(self, grant: FleetActionGrant, outcome: str,
                        result: Mapping[str, Any], *, event_id: str | None = None) -> dict[str, Any]:
        identity = event_id or "dispatch:" + hashlib.sha256(
            f"{grant.action_id}:{grant.attempt_id}:{outcome}".encode("utf-8")
        ).hexdigest()
        mission = self.mission_service.record_action_result(
            grant.mission_id, event_id=identity, action_id=grant.action_id,
            attempt_id=grant.attempt_id, outcome=outcome, result=result,
        )
        if outcome == "SUCCEEDED" and self.on_action_terminal is not None:
            self.on_action_terminal(grant.mission_id)
        return {"mission_id": grant.mission_id, "action_id": grant.action_id,
                "attempt_id": grant.attempt_id,
                "state": ("UNKNOWN" if outcome == "UNKNOWN" else mission["status"]),
                "reason": mission["reason"]}

    @staticmethod
    def _receipt_event_id(grant: FleetActionGrant,
                          receipt: DeviceActionReceipt) -> str:
        value = (f"{grant.instance_id}:{grant.action_id}:{grant.attempt_id}:"
                 f"{receipt.journal_event_id}")
        return "device:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = ["MissionDispatcher"]
