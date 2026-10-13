"""Attempt-scoped internal phase journal handle; no peer identity is accepted."""

from __future__ import annotations

from typing import Any, Mapping

from .action_store import ActionStore


class ActionPhaseRecorder:
    """Restrict phase writes to one Action attempt after runner validation.

    The recorder is minted by ActionRunner only after it authenticates the
    Fleet peer, validates the grant, and confirms the stored request/attempt.
    It is an in-process callback capability and is not a UDS operation.
    """

    def __init__(self, store: ActionStore, *, action_id: str, attempt_id: str) -> None:
        self._store = store
        self.action_id = action_id
        self.attempt_id = attempt_id

    def begin_phase(self, *, phase_id: str, ordinal: int,
                    command_digest: str) -> dict[str, Any]:
        return self._store.begin_phase(
            self.action_id, self.attempt_id, phase_id=phase_id,
            ordinal=ordinal, command_digest=command_digest,
        )

    def record_first_submission(self, *, phase_id: str, accepted: bool | None,
                                driver_goal_id: str | None) -> dict[str, Any]:
        return self._store.record_first_phase_submission(
            self.action_id, self.attempt_id, phase_id=phase_id,
            accepted=accepted, driver_goal_id=driver_goal_id,
        )

    def record_late_acceptance(self, *, phase_id: str,
                               driver_goal_id: str) -> dict[str, Any]:
        return self._store.record_late_phase_acceptance(
            self.action_id, self.attempt_id, phase_id=phase_id,
            driver_goal_id=driver_goal_id,
        )

    def record_late_cancel_request(self, *, phase_id: str,
                                   driver_goal_id: str) -> dict[str, Any]:
        return self._store.record_late_phase_cancel_request(
            self.action_id, self.attempt_id, phase_id=phase_id,
            driver_goal_id=driver_goal_id,
        )

    def record_submission(self, *, phase_id: str, accepted: bool | None,
                          driver_goal_id: str | None) -> dict[str, Any]:
        return self._store.record_phase_submission(
            self.action_id, self.attempt_id, phase_id=phase_id,
            accepted=accepted, driver_goal_id=driver_goal_id,
        )

    def mark_running(self, *, phase_id: str, driver_goal_id: str) -> dict[str, Any]:
        return self._store.mark_phase_running(
            self.action_id, self.attempt_id, phase_id=phase_id,
            driver_goal_id=driver_goal_id,
        )

    def request_cancel(self, *, phase_id: str) -> dict[str, Any]:
        return self._store.request_phase_cancel(
            self.action_id, self.attempt_id, phase_id=phase_id,
        )

    def record_cancel_ack(self, *, phase_id: str,
                          acknowledged: bool) -> dict[str, Any]:
        return self._store.record_phase_cancel_ack(
            self.action_id, self.attempt_id, phase_id=phase_id,
            acknowledged=acknowledged,
        )

    def record_terminal(self, *, phase_id: str, driver_goal_id: str,
                        outcome: str, result_source: str,
                        result_observed_at: str,
                        result: Mapping[str, object]) -> dict[str, Any]:
        return self._store.record_phase_terminal(
            self.action_id, self.attempt_id, phase_id=phase_id,
            driver_goal_id=driver_goal_id, outcome=outcome,
            result_source=result_source, result_observed_at=result_observed_at,
            result=result,
        )

    def hold(self, *, reason: str) -> dict[str, Any]:
        return self._store.hold_action(
            self.action_id, self.attempt_id, reason=reason,
        )

    def record_workflow_state(self, *, workflow_state: str,
                              object_may_be_held: bool,
                              evidence_refs: Mapping[str, object]) -> dict[str, Any]:
        return self._store.record_workflow_state(
            self.action_id, self.attempt_id, workflow_state=workflow_state,
            object_may_be_held=object_may_be_held, evidence_refs=evidence_refs,
        )

    def complete_pick_place(self, *, result_observed_at: str,
                            result: Mapping[str, object]) -> dict[str, Any]:
        return self._store.complete_pick_place(
            self.action_id, self.attempt_id,
            result_observed_at=result_observed_at, result=result,
        )

    def latest_workflow_state(self) -> str | None:
        return self._store.latest_workflow_state(self.action_id, self.attempt_id)

    def parent(self) -> dict[str, Any] | None:
        return self._store.get_action(self.action_id)

    def mark_action_running(self, *, driver_goal_id: str) -> dict[str, Any]:
        return self._store.mark_running(
            self.action_id, self.attempt_id, driver_goal_id=driver_goal_id,
        )

    def phases(self) -> list[dict[str, Any]]:
        return self._store.action_phases(self.action_id, attempt_id=self.attempt_id)
