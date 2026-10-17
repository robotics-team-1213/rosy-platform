"""Explicit simulation startup admission through the existing local stop fence."""
from hashlib import sha256
import json
import math
import secrets
import threading


class StartupCommandGate:
    def __init__(self, owner, *, target, expected_actor, fleet_fence_current, record):
        if owner.settings.coordinator_peer_uids:
            raise ValueError("startup fixture supports only the single-arm simulation owner")
        config = owner.runtime.owner.config
        if set(target) != set(config.joint_names) or any(not math.isfinite(q) for q in target.values()):
            raise ValueError("startup target must match the simulation joint map")
        self.owner, self.target = owner, dict(target)
        self.expected_actor, self.fleet_fence_current, self.record = expected_actor, fleet_fence_current, record
        self._lock = threading.RLock()
        self._authorized = self._used = self._stopped = self._cancel_sent = False
        self._command_id = None
        self._epoch = self._generation = None
        self.challenge = {
            "operation": "SIM_STARTUP_HOME", "workcell_id": config.workcell_id,
            "instance_id": config.instance_id, "owner_session_id": owner.runtime.owner.session_id,
            "nonce": secrets.token_urlsafe(24), "profile_revision": owner.profile.revision,
            "target_sha256": sha256(json.dumps(target, sort_keys=True, separators=(",", ":"),
                                               allow_nan=False).encode()).hexdigest(),
        }
        previous = owner.action_api.stop_api.cancel_active

        def cancel_active(uid):
            # A failed startup cancel must never skip the existing Fleet cancel fanout.
            outcome = None
            try:
                outcome = self._cancel_exact()
            finally:
                results = previous(uid) if previous is not None else []
            self._record_cancel(outcome)
            return results

        owner.action_api.stop_api.cancel_active = cancel_active

    def authorize(self, request):
        expected = {**self.challenge, "actor_id": self.expected_actor}
        if (not isinstance(request, dict)
                or set(request) != set(expected) | {"authority_epoch", "dispatch_generation"}
                or any(request.get(key) != value for key, value in expected.items())):
            raise PermissionError("explicit startup authorization does not match this owner/target")
        epoch, generation = request["authority_epoch"], request["dispatch_generation"]
        if any(type(value) is not int or value < 1 for value in (epoch, generation)):
            raise ValueError("startup authority and generation must be positive integers")

        def accept():
            with self._lock:
                if self._authorized or self._stopped:
                    raise PermissionError("startup authorization was already used or stopped")
                self.record("startup-authorization", dict(request))
                self._epoch, self._generation, self._authorized = epoch, generation, True

        self.owner.stop.run_if_open(authority_epoch=epoch, dispatch_generation=generation,
            fleet_fence_current=lambda: self.fleet_fence_current(epoch, generation), operation=accept)

    def _allowed(self):
        with self._lock:
            if not self._authorized or self._stopped:
                raise PermissionError("startup has no live explicit authorization")

    def _fenced(self, operation):
        self._allowed()

        def final():
            self._allowed()
            return operation()

        return self.owner.stop.run_if_open(
            authority_epoch=self._epoch, dispatch_generation=self._generation,
            fleet_fence_current=lambda: self.fleet_fence_current(self._epoch, self._generation), operation=final)

    def submit(self, command):
        self._allowed()
        with self._lock:
            if self._used:
                raise PermissionError("startup submission is one-shot; reconcile instead of retrying")
            if (command.owner != "pilot_sim" or command.positions != self.target
                    or command.session_id != self.challenge["owner_session_id"]
                    or command.workcell_id != self.challenge["workcell_id"]
                    or command.instance_id != self.challenge["instance_id"]):
                raise PermissionError("startup command differs from the authorized target/owner")
            self._used, self._command_id = True, command.command_id
            # Identity and durable intent precede the final fence and a pending ROS acceptance.
            self.record("startup-submit-intent", {**self.challenge, "command_id": command.command_id,
                "authority_epoch": self._epoch, "dispatch_generation": self._generation})
        return self._fenced(lambda: self.owner.runtime.submit(command))

    def assert_current(self):
        try:
            self._fenced(lambda: None)
        except Exception:
            self.cancel()
            raise

    def complete(self, operation):
        """Seat release and runner enable each retain the same final stop/generation fence."""
        return self._fenced(operation)

    def _cancel_exact(self):
        with self._lock:
            self._stopped = True
            if self._command_id is None or self._cancel_sent:
                return
            command_id, self._cancel_sent = self._command_id, True
        # The submit identity and stop latch are already durable. No diagnostic I/O
        # may delay this request or the existing Fleet cancellation fanout.
        result = self.owner.runtime.cancel(command_id=command_id, owner="pilot_sim")
        return {"command_id": command_id,
            "reason": result.reason, "cancel_outcome": result.cancel_outcome,
            "terminal_or_standstill_proven": False}

    def _record_cancel(self, outcome):
        if outcome is not None:
            self.record("startup-cancel-result", outcome)

    def cancel(self):
        self._record_cancel(self._cancel_exact())
