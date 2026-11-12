"""Durable, fail-closed bridge from Fleet grants to an injected local driver."""

from __future__ import annotations

import hashlib  # noqa: F401
import json  # noqa: F401
import logging
from dataclasses import dataclass  # noqa: F401
from datetime import datetime, timezone
from typing import Callable, Mapping, Protocol  # noqa: F401

from core_common.protocol.schemas import FleetActionGrant, FleetArmTransferGrant, FleetCellTransferGrant  # noqa: F401

from .action_runner_helpers import (  # noqa: F401
    DIRECT_DRIVER_KINDS,
    PHASE_RUNNER_KINDS,
    ActionGrant,
    DriverSubmission,
    LocalActionPort,
    PhaseExecution,
    StopFence,
    _ActionRunnerPhaseOps,
    action_grant_digest,
    parse_action_grant,
)
from .action_store import ActionStore, InvalidActionTransition
from .local_stop import LocalStopBlocked
from .managed_transfer_scope import validate_transfer_owner
from .phase_recorder import ActionPhaseRecorder

_LOG = logging.getLogger(__name__)
_SHARED_ADMISSION_KINDS = frozenset({"CELL_TRANSFER", "ARM_TRANSFER"})
_HOLD_ON_START_FAILURE_STATES = frozenset({
    "SUBMITTING", "ACCEPTED", "RUNNING", "CANCEL_REQUESTED", "UNKNOWN",
})
_ACTIVE_PHASE_STATES = frozenset({"ACCEPTED", "RUNNING"})
_HOLD_ON_CANCEL_STATES = frozenset({"ACCEPTED", "RUNNING", "CANCEL_REQUESTED"})


class ActionRunner(_ActionRunnerPhaseOps):
    """Journal before driver I/O; never retries an existing Fleet Action."""

    def __init__(self, store: ActionStore, driver: LocalActionPort, *,
                 workcell_id: str, instance_id: str,
                 principal_for_peer: Callable[[int], str],
                 allowed_peer_uids: set[int],
                 current_fence: Callable[[int, int], bool],
                 capability_current: Callable[[ActionGrant], bool],
                 submission_fence: StopFence | None = None,
                 phase_runner_factory: Callable[
                     [ActionGrant, ActionPhaseRecorder], PhaseExecution
                 ] | None = None,
                 phase_runner_factories: Mapping[str, Callable[
                     [ActionGrant, ActionPhaseRecorder], PhaseExecution
                 ]] | None = None,
                 control_admission=None,
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
        self.control_admission = control_admission
        if control_admission is not None and (
                control_admission.store is not store
                or control_admission.owner.config.workcell_id != workcell_id
                or control_admission.owner.config.instance_id != instance_id):
            raise ValueError("control admission must share the owner identity and Action store")
        # One factory per kind: the PICK_PLACE runner never executes CELL_TRANSFER.
        # ``phase_runner_factory`` is the existing PICK_PLACE factory.
        factories = dict(phase_runner_factories or {})
        if not set(factories) <= PHASE_RUNNER_KINDS:
            raise ValueError("phase_runner_factories keys must be phase runner kinds")
        if phase_runner_factory is not None:
            if "PICK_PLACE" in factories:
                raise ValueError("PICK_PLACE phase runner factory is given twice")
            factories["PICK_PLACE"] = phase_runner_factory
        if any(not callable(factory) for factory in factories.values()):
            raise ValueError("phase runner factories must be callable")
        self.phase_runner_factories = factories
        self._phase_runners: dict[tuple[str, str], object] = {}
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

    def _validate(self, grant: ActionGrant) -> None:
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
        # Provider callbacks may block. They cannot extend the original lease.
        self._validate_time(grant)

    def _validate_time(self, grant: ActionGrant) -> None:
        final_now = self.now()
        if final_now.tzinfo is None or final_now.utcoffset() is None:
            raise RuntimeError("local clock must return an aware timestamp")
        final_current = final_now.astimezone(timezone.utc)
        if grant.expires_at.astimezone(timezone.utc) <= final_current:
            raise PermissionError("grant is expired")
        if grant.issued_at.astimezone(timezone.utc) > final_current:
            raise PermissionError("grant issuance time is in the future")

    def _receipt(self, action: Mapping[str, object], *, created: bool,
                 reason: str | None = None) -> dict[str, object]:
        from .policy_parent import projection
        snapshot = self.store.attempt_snapshot(str(action['action_id']), action.get('attempt_id'))
        action = snapshot['action']
        request = action.get("request", {})
        payload = request.get("payload", {}) if isinstance(request, Mapping) else {}
        if not isinstance(payload, Mapping):
            payload = {}
        projected = projection(snapshot) if action.get('attempt_id') else None
        return {
            "mission_id": payload.get("mission_id"),
            "step_id": payload.get("step_id"),
            "action_id": action["action_id"], "attempt_id": action.get("attempt_id"),
            "workcell_id": action["workcell_id"], "instance_id": action["instance_id"],
            "request_digest": payload.get("request_digest"),
            "authority_epoch": payload.get("authority_epoch"),
            "dispatch_generation": payload.get("dispatch_generation"),
            "state": action["state"], "driver_goal_id": action.get("driver_goal_id"),
            "journal_event_id": action["journal_event_id"],
            "observed_at": projected["observed_at"] if projected else action["updated_at"],
            "reason": reason or action.get("reason"), "created": created,
            "phase_summaries": projected["phase_summaries"] if projected else [],
            **({"journal_id": snapshot["journal_id"]} if action["action_kind"] == "ARM_TRANSFER" else {}),
        }

    def submit(self, grant: ActionGrant, *, peer_uid: int) -> dict[str, object]:
        principal_id = self._principal(peer_uid)
        if not self.enabled:
            raise PermissionError("local Action capability is disabled")
        phase_runner_factory = self.phase_runner_factories.get(grant.action_kind)
        use_phase_runner = phase_runner_factory is not None
        if not use_phase_runner and grant.action_kind not in DIRECT_DRIVER_KINDS:
            # Fail closed before any journal row: unknown kinds never reach the driver.
            raise PermissionError(f"action kind {grant.action_kind!r} has no admitted executor")
        self._validate(grant)
        if grant.action_kind in _SHARED_ADMISSION_KINDS and self.control_admission is None:
            raise PermissionError(f"{grant.action_kind} requires shared control admission")
        if isinstance(grant, FleetArmTransferGrant):
            validate_transfer_owner(self.control_admission, grant)
        request = grant.model_dump(mode="json")
        def create_action():
            return self.store.create_action(
                workcell_id=grant.workcell_id, instance_id=grant.instance_id,
                principal_id=principal_id, request_key=grant.action_id,
                action_id=grant.action_id, action_kind=grant.action_kind,
                configuration_revision=grant.config_revision,
                # Cell Transfer is recipe/cell bound and deliberately camera blind.
                # Empty is a truthful no-observation value; PICK_PLACE remains nonempty.
                observation_id=(grant.observation_revision
                                if isinstance(grant, FleetActionGrant) else ""),
                owner_generation=grant.dispatch_generation, payload=request,
            )
        if self.control_admission is None:
            created = create_action()
        elif isinstance(grant, FleetArmTransferGrant):
            created = self.control_admission.run_action_admission(
                create_action, action_kind=grant.action_kind,
                resource_policy_digest=grant.arm_transfer.resource_policy_digest)
        else:
            created = self.control_admission.run_action_admission(create_action)
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

        if use_phase_runner:
            identity = (grant.action_id, grant.attempt_id)
            try:
                recorder = self._phase_recorder_for_validated_grant(
                    grant, peer_uid=peer_uid,
                )
                phase_runner = phase_runner_factory(grant, recorder)
                start = getattr(phase_runner, "start", None)
                cancel_current = getattr(phase_runner, "cancel_current", None)
                if not callable(start) or not callable(cancel_current):
                    raise TypeError("phase runner must support start and exact-goal cancel")
                self._phase_runners[identity] = phase_runner
                start()
            except Exception:
                # The receipt says only START_UNKNOWN; the cause must still reach the owner's log.
                _LOG.exception("phase runner start failed for %s", grant.action_id)
                current = self.store.get_action(grant.action_id)
                if current is not None and current["state"] in _HOLD_ON_START_FAILURE_STATES:
                    self.store.hold_action(
                        grant.action_id, grant.attempt_id,
                        reason="PHASE_RUNNER_START_UNKNOWN",
                    )
                current = self.store.get_action(grant.action_id)
                if current is None:
                    raise
                return self._receipt(current, created=created["created"],
                                     reason="PHASE_RUNNER_START_UNKNOWN")
            current = self.store.get_action(grant.action_id)
            if current is None:
                raise RuntimeError("phase runner removed its Action journal")
            return self._receipt(current, created=created["created"])

        submission_fence = self.submission_fence

        def _fenced_submission() -> dict[str, object]:
            # Durable preparation may outlive the checked authority. Recheck
            # under the same fence that protects driver submission/recording.
            providers = (self.principal_for_peer, self.current_fence,
                         self.capability_current, self.now)
            if self._principal(peer_uid) != principal_id:
                raise PermissionError("peer principal changed during preparation")
            self._validate(grant)
            if not self.current_fence(grant.authority_epoch, grant.dispatch_generation):
                raise PermissionError("authority epoch or dispatch generation is stale")
            if self._principal(peer_uid) != principal_id:
                raise PermissionError("peer principal changed during validation")
            if not self.enabled:
                raise PermissionError("local Action capability is disabled")
            self._validate_time(grant)
            if any(before is not after for before, after in zip(
                    providers, (self.principal_for_peer, self.current_fence,
                                self.capability_current, self.now))):
                raise PermissionError("authority providers changed during validation")
            # Providers can reenter the owner lock and latch STOP. Read the
            # same local fence after every provider, immediately before submit.
            if self.submission_fence is not submission_fence or not submission_fence.is_open(
                    authority_epoch=grant.authority_epoch,
                    dispatch_generation=grant.dispatch_generation):
                raise LocalStopBlocked("local stop latch or generation changed during validation")
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
            recorded = submission_fence.run_if_open(
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
        if action is None:
            return None
        if action["principal_id"] != principal_id:
            # Not "absent": Fleet must not read another principal's Action as never journaled.
            raise PermissionError("peer UID does not own this Action")
        return self._receipt(action, created=False)

    def read_receipt(self, action_id: str) -> dict[str, object] | None:
        """Principal-free read for an already-authenticated read-only peer (D-780 1)."""
        action = self.store.get_action(action_id)
        return None if action is None else self._receipt(action, created=False)

    def cancel(self, action_id: str, attempt_id: str, *, peer_uid: int) -> dict[str, object]:
        principal_id = self._principal(peer_uid)
        action = self.store.get_action(action_id)
        if action is None or action["principal_id"] != principal_id:
            raise KeyError(action_id)
        if action["attempt_id"] != attempt_id:
            raise PermissionError("cancel attempt does not match current Action")
        phases = self.store.action_phases(action_id, attempt_id=attempt_id)
        if phases:
            if action["state"] == "SUBMITTING":
                held = self.store.hold_action(
                    action_id, attempt_id, reason="PHASE_CANCEL_DURING_SUBMISSION",
                )
                return self._receipt(held, created=False,
                                     reason="PHASE_CANCEL_DURING_SUBMISSION")
            active = next((phase for phase in reversed(phases)
                           if phase["state"] in _ACTIVE_PHASE_STATES), None)
            if active is not None:
                self.cancel_phase(
                    action_id, attempt_id, phase_id=active["phase_id"], peer_uid=peer_uid,
                )
                current = self.store.get_action(action_id)
                return self._receipt(current or action, created=False)
            if action["state"] in _HOLD_ON_CANCEL_STATES:
                held = self.store.hold_action(
                    action_id, attempt_id, reason="PHASE_CANCEL_TARGET_UNAVAILABLE",
                )
                return self._receipt(held, created=False,
                                     reason="PHASE_CANCEL_TARGET_UNAVAILABLE")
            return self._receipt(action, created=False)
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
