"""Durable, fail-closed bridge from Fleet grants to an injected local driver."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping, Protocol

from core_common.protocol.schemas import FleetActionGrant

from .action_store import ActionStore, InvalidActionTransition
from .local_stop import LocalStopBlocked


def action_grant_digest(value: FleetActionGrant | Mapping[str, object]) -> str:
    grant = (value if isinstance(value, FleetActionGrant)
             else FleetActionGrant.model_validate(value))
    document = grant.model_dump(mode="json", exclude={"request_digest"})
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DriverSubmission:
    """Driver acceptance fact; acceptance is not task completion or stop proof."""

    accepted: bool | None
    driver_goal_id: str | None = None

    def __post_init__(self) -> None:
        if self.accepted is not True and self.accepted is not False and self.accepted is not None:
            raise ValueError("accepted must be true, false, or unknown")
        if self.driver_goal_id is not None and (
                not isinstance(self.driver_goal_id, str)
                or not self.driver_goal_id.strip()
                or self.driver_goal_id != self.driver_goal_id.strip()):
            raise ValueError("driver_goal_id must be a non-empty trimmed string")
        if self.accepted is True and self.driver_goal_id is None:
            raise ValueError("accepted driver submission requires driver_goal_id")


class LocalActionPort(Protocol):
    """One in-process ROS/device owner supplied by the selected workcell profile."""

    def submit(self, grant: FleetActionGrant) -> DriverSubmission: ...

    def cancel(self, action: Mapping[str, object]) -> bool | None: ...


class StopFence(Protocol):
    def run_if_open(self, *, authority_epoch: int, dispatch_generation: int,
                    fleet_fence_current: Callable[[], bool],
                    operation: Callable[[], DriverSubmission]) -> DriverSubmission: ...


class ActionRunner:
    """Journal before driver I/O; never retries an existing Fleet Action."""

    def __init__(self, store: ActionStore, driver: LocalActionPort, *,
                 workcell_id: str, instance_id: str,
                 principal_for_peer: Callable[[int], str],
                 allowed_peer_uids: set[int],
                 current_fence: Callable[[int, int], bool],
                 capability_current: Callable[[FleetActionGrant], bool],
                 submission_fence: StopFence | None = None,
                 enabled: bool = False,
                 now: Callable[[], datetime] | None = None) -> None:
        self.store = store
        self.driver = driver
        self.workcell_id = workcell_id
        self.instance_id = instance_id
        self.principal_for_peer = principal_for_peer
        self.allowed_peer_uids = frozenset(allowed_peer_uids)
        self.current_fence = current_fence
        self.capability_current = capability_current
        self.submission_fence = submission_fence
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be boolean")
        if enabled and submission_fence is None:
            raise ValueError("enabled runner requires a local stop/generation fence")
        self.enabled = enabled
        self.now = now or (lambda: datetime.now(timezone.utc))

    def _principal(self, peer_uid: int) -> str:
        if type(peer_uid) is not int or peer_uid not in self.allowed_peer_uids:
            raise PermissionError("peer UID is not allowed")
        principal = self.principal_for_peer(peer_uid)
        if not isinstance(principal, str) or not principal.strip():
            raise PermissionError("peer UID has no Fleet principal mapping")
        return principal

    def _validate(self, grant: FleetActionGrant) -> None:
        if action_grant_digest(grant) != grant.request_digest:
            raise PermissionError("grant request digest is invalid")
        now = self.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise RuntimeError("local clock must return an aware timestamp")
        current = now.astimezone(timezone.utc)
        if grant.expires_at.astimezone(timezone.utc) <= current:
            raise PermissionError("grant is expired")
        if grant.issued_at.astimezone(timezone.utc) > current:
            raise PermissionError("grant issuance time is in the future")
        if (grant.workcell_id != self.workcell_id
                or grant.instance_id != self.instance_id):
            raise PermissionError("grant targets another workcell instance")
        if not self.current_fence(grant.authority_epoch, grant.dispatch_generation):
            raise PermissionError("authority epoch or dispatch generation is stale")
        if not self.capability_current(grant):
            raise PermissionError("workcell capability or configuration is stale")

    def _receipt(self, action: Mapping[str, object], *, created: bool,
                 reason: str | None = None) -> dict[str, object]:
        request = action.get("request", {})
        payload = request.get("payload", {}) if isinstance(request, Mapping) else {}
        if not isinstance(payload, Mapping):
            payload = {}
        return {
            "mission_id": payload.get("mission_id"),
            "step_id": payload.get("step_id"),
            "action_id": action["action_id"], "attempt_id": action.get("attempt_id"),
            "workcell_id": action["workcell_id"], "instance_id": action["instance_id"],
            "request_digest": payload.get("request_digest"),
            "authority_epoch": payload.get("authority_epoch"),
            "dispatch_generation": payload.get("dispatch_generation"),
            "state": action["state"], "driver_goal_id": action.get("driver_goal_id"),
            "journal_event_id": action.get("journal_event_id")
            or self.store.latest_event_id(str(action["action_id"])),
            "observed_at": action["updated_at"],
            "reason": reason or action.get("reason"), "created": created,
        }

    def submit(self, grant: FleetActionGrant, *, peer_uid: int) -> dict[str, object]:
        principal_id = self._principal(peer_uid)
        if not self.enabled:
            raise PermissionError("local Action capability is disabled")
        self._validate(grant)
        request = grant.model_dump(mode="json")
        created = self.store.create_action(
            workcell_id=grant.workcell_id, instance_id=grant.instance_id,
            principal_id=principal_id, request_key=grant.action_id,
            action_id=grant.action_id, action_kind=grant.action_kind,
            configuration_revision=grant.config_revision,
            observation_id=grant.observation_revision,
            owner_generation=grant.dispatch_generation, payload=request,
        )
        action = created["action"]
        if not created["created"] and action["state"] != "PREPARED":
            return self._receipt(action, created=False)
        try:
            submitting = self.store.begin_submission(
                grant.action_id, expected_generation=grant.dispatch_generation,
                attempt_id=grant.attempt_id,
            )
        except InvalidActionTransition:
            current = self.store.get_action(grant.action_id)
            if current is None:
                raise
            return self._receipt(current, created=False)

        def _fenced_submission() -> dict[str, object]:
            # The driver call AND its ACCEPTED recording stay inside the
            # stop fence: a stop latched while the driver call blocks must
            # find this attempt in ACCEPTED (never a lost in-flight
            # submission), so the cancel fanout reaches the driver.
            driver_result = self.driver.submit(grant)
            if not isinstance(driver_result, DriverSubmission):
                raise TypeError("local driver returned an invalid submission receipt")
            return self.store.record_submission(
                grant.action_id, submitting["attempt_id"],
                accepted=driver_result.accepted,
                driver_goal_id=driver_result.driver_goal_id,
            )

        try:
            recorded = self.submission_fence.run_if_open(
                authority_epoch=grant.authority_epoch,
                dispatch_generation=grant.dispatch_generation,
                fleet_fence_current=lambda: self.current_fence(
                    grant.authority_epoch, grant.dispatch_generation,
                ),
                operation=_fenced_submission,
            )
        except LocalStopBlocked:
            held = self.store.hold_action(
                grant.action_id, submitting["attempt_id"],
                reason="STOP_GENERATION_FENCED",
            )
            return self._receipt(held, created=created["created"],
                                 reason="STOP_GENERATION_FENCED")
        except Exception:
            unknown = self.store.record_submission(
                grant.action_id, submitting["attempt_id"],
                accepted=None, driver_goal_id=None,
            )
            return self._receipt(unknown, created=created["created"],
                                 reason="DRIVER_ACCEPTANCE_UNKNOWN")
        return self._receipt(recorded, created=created["created"])

    def get(self, action_id: str, *, peer_uid: int) -> dict[str, object] | None:
        principal_id = self._principal(peer_uid)
        action = self.store.get_action(action_id)
        if action is None or action["principal_id"] != principal_id:
            return None
        return self._receipt(action, created=False)

    def cancel(self, action_id: str, attempt_id: str, *, peer_uid: int) -> dict[str, object]:
        principal_id = self._principal(peer_uid)
        action = self.store.get_action(action_id)
        if action is None or action["principal_id"] != principal_id:
            raise KeyError(action_id)
        if action["attempt_id"] != attempt_id:
            raise PermissionError("cancel attempt does not match current Action")
        requested = self.store.request_cancel(action_id, attempt_id)
        try:
            acknowledged = self.driver.cancel(requested)
        except Exception:
            return self._receipt(requested, created=False,
                                 reason="CANCEL_ACK_UNKNOWN")
        if type(acknowledged) is bool:
            requested = self.store.record_cancel_ack(
                action_id, attempt_id, acknowledged=acknowledged,
            )
        return self._receipt(requested, created=False,
                             reason=None if acknowledged is not None else "CANCEL_ACK_UNKNOWN")

    def record_running(self, action_id: str, attempt_id: str, *, driver_goal_id: str,
                       peer_uid: int) -> dict[str, object]:
        self._require_owner(action_id, peer_uid)
        updated = self.store.mark_running(
            action_id, attempt_id, driver_goal_id=driver_goal_id,
        )
        return self._receipt(updated, created=False)

    def record_terminal(self, action_id: str, attempt_id: str, *, driver_goal_id: str,
                        outcome: str, result_source: str, result_observed_at: str,
                        result: Mapping[str, object], peer_uid: int) -> dict[str, object]:
        self._require_owner(action_id, peer_uid)
        updated = self.store.record_terminal(
            action_id, attempt_id, driver_goal_id=driver_goal_id, outcome=outcome,
            result_source=result_source, result_observed_at=result_observed_at,
            result=result,
        )
        return self._receipt(updated, created=False)

    def begin_phase(self, action_id: str, attempt_id: str, *, phase_id: str,
                    ordinal: int, command_digest: str,
                    peer_uid: int) -> dict[str, object]:
        """Persist an ordered phase intent under the Fleet Action owner."""
        self._require_attempt_owner(action_id, attempt_id, peer_uid)
        return self.store.begin_phase(
            action_id, attempt_id, phase_id=phase_id, ordinal=ordinal,
            command_digest=command_digest,
        )

    def record_phase_submission(self, action_id: str, attempt_id: str, *,
                                phase_id: str, accepted: bool | None,
                                driver_goal_id: str | None,
                                peer_uid: int) -> dict[str, object]:
        self._require_attempt_owner(action_id, attempt_id, peer_uid)
        return self.store.record_phase_submission(
            action_id, attempt_id, phase_id=phase_id,
            accepted=accepted, driver_goal_id=driver_goal_id,
        )

    def record_phase_running(self, action_id: str, attempt_id: str, *,
                             phase_id: str, driver_goal_id: str,
                             peer_uid: int) -> dict[str, object]:
        self._require_attempt_owner(action_id, attempt_id, peer_uid)
        return self.store.mark_phase_running(
            action_id, attempt_id, phase_id=phase_id,
            driver_goal_id=driver_goal_id,
        )

    def cancel_phase(self, action_id: str, attempt_id: str, *,
                     phase_id: str, peer_uid: int) -> dict[str, object]:
        """Request cancel for one phase; an ACK remains separate from its result."""
        action = self._require_attempt_owner(action_id, attempt_id, peer_uid)
        phase = self.store.request_phase_cancel(
            action_id, attempt_id, phase_id=phase_id,
        )
        try:
            acknowledged = self.driver.cancel(action)
        except Exception:
            return phase
        if type(acknowledged) is bool:
            return self.store.record_phase_cancel_ack(
                action_id, attempt_id, phase_id=phase_id,
                acknowledged=acknowledged,
            )
        return phase

    def record_phase_terminal(self, action_id: str, attempt_id: str, *,
                              phase_id: str, driver_goal_id: str,
                              outcome: str, result_source: str,
                              result_observed_at: str,
                              result: Mapping[str, object],
                              peer_uid: int) -> dict[str, object]:
        self._require_attempt_owner(action_id, attempt_id, peer_uid)
        return self.store.record_phase_terminal(
            action_id, attempt_id, phase_id=phase_id,
            driver_goal_id=driver_goal_id, outcome=outcome,
            result_source=result_source, result_observed_at=result_observed_at,
            result=result,
        )

    def _require_owner(self, action_id: str, peer_uid: int) -> dict[str, object]:
        principal_id = self._principal(peer_uid)
        action = self.store.get_action(action_id)
        if action is None or action["principal_id"] != principal_id:
            raise KeyError(action_id)
        return action

    def _require_attempt_owner(self, action_id: str, attempt_id: str,
                               peer_uid: int) -> dict[str, object]:
        action = self._require_owner(action_id, peer_uid)
        if action["attempt_id"] != attempt_id:
            raise PermissionError("phase attempt does not match current Action")
        return action

    def cancel_unresolved(self, *, peer_uid: int) -> list[dict[str, object]]:
        """Best-effort cancel fanout after the persistent local stop latch is set."""
        principal_id = self._principal(peer_uid)
        receipts: list[dict[str, object]] = []
        for action in self.store.unresolved_actions(workcell_id=self.workcell_id):
            if action["principal_id"] != principal_id:
                continue
            if action["state"] not in {"ACCEPTED", "RUNNING"}:
                continue
            try:
                receipts.append(self.cancel(
                    action["action_id"], action["attempt_id"], peer_uid=peer_uid,
                ))
            except (KeyError, PermissionError, InvalidActionTransition):
                continue
        return receipts
