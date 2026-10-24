"""Internal ARM factory port: durable phase intent precedes a short owner capability."""
from contextlib import contextmanager
from datetime import datetime

from core_common.protocol.schemas import FleetArmTransferGrant

from .managed_transfer_scope import validate_transfer_owner
from .phase_recorder import ActionPhaseRecorder
from .pick_place_runner import PickPlaceRunner


class _ManagedTransferPort:
    def __init__(self, admission, delegate, grant, recorder):
        if (not isinstance(grant, FleetArmTransferGrant) or not isinstance(recorder, ActionPhaseRecorder)
                or recorder._store is not admission.store
                or (recorder.action_id, recorder.attempt_id) != (grant.action_id, grant.attempt_id)
                or admission.owner._control_admission is not admission
                or getattr(delegate, "command_owner", None) is not admission.owner
                or (grant.workcell_id, grant.instance_id) != (
                    admission.owner.config.workcell_id, admission.owner.config.instance_id)
                or admission.managed_transfer_policy_digest != grant.arm_transfer.resource_policy_digest):
            raise PermissionError("managed transfer must share the installed owner, journal and policy")
        self.admission, self.delegate = admission, delegate
        self.grant, self.recorder = grant, recorder
        self.executor = None
        self.scope = admission._managed_scope

    def bind_executor(self, executor):
        if (self.executor is not None or not isinstance(executor, PickPlaceRunner)
                or executor.goal_port is not self or executor.recorder is not self.recorder
                or executor.grant is not self.grant):
            raise PermissionError("managed port requires its exact validated phase coordinator")
        self.executor = executor

    def _current_time(self):
        now = self.executor.now()
        if (not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None
                or not self.grant.issued_at <= now < self.grant.expires_at):
            raise PermissionError("managed transfer grant is not current")

    @contextmanager
    def _command_scope(self, command):
        admission = self.admission
        with admission.owner.command_transaction():
            with admission._lock:
                admission._session()
                self._current_time()
                if command.session_id != self.grant.owner_session_id:
                    raise PermissionError("managed command targets another owner session")
                if (getattr(admission._managed_command, "command", None) is not None
                        or admission._managed_scope != self.scope):
                    raise PermissionError("managed command context is already occupied or changed")
                admission._managed_command.command = command
                admission._managed_command.validate = self._current_time
            try:
                yield
            finally:
                del admission._managed_command.command
                del admission._managed_command.validate

    def submit(self, command, *, on_goal_event):
        if self.executor is None:
            raise PermissionError("managed coordinator is not bound")
        digest = self.executor.current_submission_digest(command)
        if digest is None:
            raise PermissionError("command is outside the validated phase submission")
        validate_transfer_owner(self.admission, self.grant)
        parent = self.recorder.parent()
        phase = next((p for p in self.recorder.phases() if p["phase_id"] == command.phase_id), None)
        if (parent is None or parent["state"] not in {"SUBMITTING", "ACCEPTED", "RUNNING"}
                or parent["attempt_id"] != self.grant.attempt_id
                or parent["request"]["payload"] != self.grant.model_dump(mode="json")
                or phase is None or phase["state"] != "SUBMITTING" or phase["command_digest"] != digest):
            raise PermissionError("managed command has no matching durable grant and phase intent")
        with self._command_scope(command):
            return self.delegate.submit(command, on_goal_event=on_goal_event)

    def cancel_goal(self, driver_goal_id):
        return self.delegate.cancel_goal(driver_goal_id)
