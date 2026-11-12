"""Grant parsing/digest, driver/fence protocols, and owner-scoped phase lifecycle mixin for ActionRunner."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Callable, Mapping, Protocol

from core_common.protocol.schemas import FleetActionGrant, FleetArmTransferGrant, FleetCellTransferGrant

from .action_store import InvalidActionTransition
from .phase_recorder import ActionPhaseRecorder

# Kinds the ordered phase runner may execute, and the only kind the direct
# driver path admits. CELL_TRANSFER runs through the phase runner only (D-402 §3).
PHASE_RUNNER_KINDS = frozenset({"PICK_PLACE", "CELL_TRANSFER", "ARM_TRANSFER"})
DIRECT_DRIVER_KINDS = frozenset({"PICK_PLACE"})
ActionGrant = FleetActionGrant | FleetCellTransferGrant | FleetArmTransferGrant


def parse_action_grant(value: ActionGrant | Mapping[str, object]) -> ActionGrant:
    """Parse explicitly supported local Action grant variants; parsing grants no authority."""
    if isinstance(value, (FleetActionGrant, FleetCellTransferGrant, FleetArmTransferGrant)):
        return value
    if not isinstance(value, Mapping):
        raise ValueError("grant must be an object")
    action_kind = value.get("action_kind")
    if action_kind == "PICK_PLACE":
        return FleetActionGrant.model_validate(value)
    if action_kind == "CELL_TRANSFER":
        return FleetCellTransferGrant.model_validate(value)
    if action_kind == "ARM_TRANSFER":
        return FleetArmTransferGrant.model_validate(value)
    raise ValueError("grant action_kind is unsupported")


def action_grant_digest(value: ActionGrant | Mapping[str, object]) -> str:
    grant = parse_action_grant(value)
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

    def submit(self, grant: ActionGrant) -> DriverSubmission: ...

    def cancel(self, action: Mapping[str, object]) -> bool | None: ...


class StopFence(Protocol):
    def run_if_open(self, *, authority_epoch: int, dispatch_generation: int,
                    fleet_fence_current: Callable[[], bool],
                    operation: Callable[[], DriverSubmission]) -> DriverSubmission: ...

    def is_open(self, *, authority_epoch: int, dispatch_generation: int) -> bool: ...


class PhaseExecution(Protocol):
    """One grant-bound coordinator for exact phase submission and cancellation."""

    @property
    def active_phase_id(self) -> str | None: ...

    def start(self) -> object: ...

    def cancel_current(self) -> Mapping[str, object]: ...


class _ActionRunnerPhaseOps:
    """Owner-scoped phase lifecycle, phase recorder/policy parent minting, and unresolved cancel fanout."""

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
        phase_runner = self._phase_runners.get((action_id, attempt_id))
        if phase_runner is not None:
            active_phase_id = getattr(phase_runner, "active_phase_id", None)
            cancel_current = getattr(phase_runner, "cancel_current", None)
            if (active_phase_id != phase_id
                    or not callable(cancel_current)):
                raise InvalidActionTransition("phase is not the coordinator's active ROS goal")
            cancel_current()
            phase = next((row for row in self.store.action_phases(
                action_id, attempt_id=attempt_id,
            ) if row["phase_id"] == phase_id), None)
            if phase is None:
                raise RuntimeError("coordinator phase journal disappeared")
            return phase
        phase = self.store.request_phase_cancel(
            action_id, attempt_id, phase_id=phase_id,
        )
        cancel_phase = getattr(self.driver, "cancel_phase", None)
        if not callable(cancel_phase):
            return phase
        try:
            acknowledged = cancel_phase(action, phase)
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

    def _phase_recorder_for_validated_grant(
        self, grant: ActionGrant, *, peer_uid: int,
    ) -> ActionPhaseRecorder:
        """Mint an in-process, attempt-scoped phase journal after grant checks."""
        principal_id = self._principal(peer_uid)
        self._validate(grant)
        action = self.store.get_action(grant.action_id)
        if action is None or action["principal_id"] != principal_id:
            raise PermissionError("Fleet peer does not own this Action")
        request = action.get("request", {})
        payload = request.get("payload", {}) if isinstance(request, Mapping) else {}
        stored_grant_digest = payload.get("request_digest") if isinstance(payload, Mapping) else None
        if (action["attempt_id"] != grant.attempt_id
                or stored_grant_digest != grant.request_digest
                or action["workcell_id"] != grant.workcell_id
                or action["instance_id"] != grant.instance_id
                or action["owner_generation"] != grant.dispatch_generation):
            raise PermissionError("stored Action identity does not match the validated grant")
        if action["state"] not in {
            "SUBMITTING", "ACCEPTED", "RUNNING", "CANCEL_REQUESTED", "UNKNOWN", "HOLD",
        }:
            raise InvalidActionTransition("terminal Action cannot mint a phase recorder")
        return ActionPhaseRecorder(
            self.store, action_id=grant.action_id, attempt_id=grant.attempt_id,
        )

    def _policy_parent_for_validated_grant(self, grant: ActionGrant, *, peer_uid: int):
        """Mint read-only correlation capability, never a learned executor grant."""
        from .policy_parent import mint_parent
        return mint_parent(self, grant, peer_uid=peer_uid)

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
