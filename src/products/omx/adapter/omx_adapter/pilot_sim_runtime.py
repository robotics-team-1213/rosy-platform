"""SIM-only Pilot facade over the single OMX FollowJointTrajectory owner."""

from __future__ import annotations

import threading
import time

from core_common.protocol.controls import ControlsDescriptor, JointJogControl, JointRange
from core_common.protocol.omx_sim import OmxSimJog

from .command_owner import TrajectoryCommand

JOG_MAX_STEP_RAD = 0.05
JOG_DURATION_S = 0.4


class PilotSimRuntime:
    def __init__(self, arm, *, gripper: str = "gripper_joint_1") -> None:
        self.arm = arm
        self.instance_id = arm.owner.config.instance_id
        self.joint_names = arm.owner.config.joint_names
        self.gripper = gripper
        self.camera_available = False
        self.capture = None
        self._lock = threading.RLock()
        self._goals: dict[str, dict] = {}
        self._active: str | None = None
        self._last_event_sequence: dict[str, int] = {}
        self._served_sequences: dict[int, float] = {}

    def snapshot(self) -> dict:
        state = self.arm.latest_joint_state
        age = None if state is None else time.monotonic() - state.received_at
        action_server_ready = self.arm.action_port.server_is_ready()
        ready = (state is not None and 0 <= age <= self.arm.owner.config.max_joint_state_age_s
                 and self.arm.owner.state == "ready" and action_server_ready)
        if ready:
            with self._lock:
                now = time.monotonic()
                self._served_sequences = {seq: issued for seq, issued in self._served_sequences.items()
                                          if now - issued <= 5.0}
                self._served_sequences[state.sequence] = now
        return {"instance_id": self.instance_id, "ready": ready,
                "owner_state": self.arm.owner.state,
                "owner_reason": (getattr(getattr(self.arm, "last_terminal_decision", None), "reason", "")
                                 if self.arm.owner.state == "hold" else ""),
                "action_server_ready": action_server_ready,
                "state_sequence": state.sequence if state else None,
                "joint_age_ms": round(age * 1000) if age is not None else None,
                "positions": dict(state.positions) if state else {},
                "active_goal": self._active}

    def controls(self) -> dict:
        """rosy.controls/1 for this SIM workcell (D-411 B). Bounded goals only (D-390 §2)."""
        limits = self.arm.owner.config.position_limits
        jog = JointJogControl(id="arm", label="팔", max_step_rad=JOG_MAX_STEP_RAD, duration_s=JOG_DURATION_S,
                              joints=tuple(JointRange(name=n, lower=limits[n][0], upper=limits[n][1])
                                           for n in self.joint_names))
        return ControlsDescriptor(items=(jog,)).model_dump(by_alias=True, mode="json")

    def submit(self, jog: OmxSimJog) -> dict:
        with self._lock:
            state = self.arm.latest_joint_state
            config = self.arm.owner.config
            reason = ""
            if jog.instance_id != self.instance_id:
                reason = "instance_mismatch"
            elif jog.joint not in self.joint_names:
                reason = "joint_not_admitted"
            elif self._active is not None:
                reason = "goal_active"
            elif not self.snapshot()["ready"]:
                reason = "readback_or_controller_not_ready"
            elif (jog.state_sequence > state.sequence
                  or time.monotonic() - self._served_sequences.get(jog.state_sequence, float("-inf")) > 5.0):
                reason = "readback_not_recently_served"
            if reason:
                return {"command_id": jog.request_id, "state": "REJECTED", "reason": reason}
            target = dict(state.positions)
            target[jog.joint] += jog.delta_rad
            lower, upper = config.position_limits[jog.joint]
            if not lower <= target[jog.joint] <= upper:
                return {"command_id": jog.request_id, "state": "REJECTED", "reason": "joint_limit"}
            command = TrajectoryCommand(
                workcell_id=config.workcell_id, instance_id=config.instance_id,
                command_id=jog.request_id, session_id=self.arm.owner.session_id,
                owner="pilot_sim", positions=target, duration_s=jog.duration_s,
                source_state_sequence=state.sequence,
                calibration_revision=config.calibration_revision,
                joint_names=config.joint_names,
            )
            # Register before dispatch: a local ActionServer may respond synchronously.
            receipt = {"command_id": jog.request_id, "state": "LOCAL_ACCEPTED", "reason": ""}
            self._goals[jog.request_id] = receipt
            self._active = jog.request_id
            if self.capture is not None:
                self.capture.prepare(command)
            decision = self.arm.submit(command)
            if not decision.accepted:
                self._goals.pop(jog.request_id, None)
                self._active = None
                if self.capture is not None:
                    self.capture.discard(jog.request_id)
                return {"command_id": jog.request_id, "state": "REJECTED", "reason": decision.reason}
            return dict(receipt)

    def goal(self, command_id: str) -> dict:
        with self._lock:
            return dict(self._goals[command_id])

    def cancel(self, command_id: str) -> dict:
        with self._lock:
            if command_id != self._active:
                return self.goal(command_id)
            decision = self.arm.cancel(command_id=command_id, owner="pilot_sim")
            receipt = self._goals[command_id]
            receipt["state"] = "CANCEL_REQUESTED" if decision.reason == "cancel_requested" else "UNKNOWN_HOLD"
            receipt["reason"] = decision.reason
            self._interrupt_capture("goal_cancel_requested")
            # Cancellation is asynchronous: no further goal may be admitted until explicit recovery.
            self._active = None
            return dict(receipt)

    def cancel_active(self) -> None:
        with self._lock:
            if self._active:
                self.cancel(self._active)
            self._interrupt_capture("control_released")

    def _interrupt_capture(self, reason: str) -> None:
        if self.capture is not None:
            try:
                callback = getattr(self.capture, "request_interrupt", self.capture.interrupt)
                callback(reason)
            except Exception:
                # Recording cannot disable command cancellation or lease expiry.
                pass

    def on_goal_event(self, event) -> None:
        with self._lock:
            receipt = self._goals.get(event.command_id)
            if receipt is None:
                return
            last = self._last_event_sequence.get(event.command_id, 0)
            if event.sequence <= last:
                return
            self._last_event_sequence[event.command_id] = event.sequence
            if event.kind == "GOAL_ACCEPTED":
                receipt.update(state="ROS_ACCEPTED", ros_goal_id=event.goal_id)
            elif event.kind == "RUNNING_FEEDBACK":
                receipt.update(state="RUNNING", ros_goal_id=event.goal_id)
            elif event.kind == "TERMINAL_RESULT":
                if event.status == 4 and event.result_code == 0:
                    receipt.update(state="SUCCEEDED", ros_goal_id=event.goal_id)
                elif event.status == 5:
                    receipt.update(state="CANCELED", ros_goal_id=event.goal_id)
                else:
                    receipt.update(state="UNKNOWN_HOLD", reason=f"terminal_status_{event.status}")
                if self._active == event.command_id:
                    self._active = None
            elif event.kind in {"GOAL_REJECTED", "GOAL_ACCEPTANCE_UNKNOWN", "TERMINAL_UNKNOWN"}:
                receipt.update(state="UNKNOWN_HOLD", reason=event.kind.lower())
                if self._active == event.command_id:
                    self._active = None
            elif event.kind == "CANCEL_ACK" and not event.cancel_acknowledged:
                receipt.update(state="UNKNOWN_HOLD", reason="cancel_not_acknowledged")
            if self.capture is not None:
                try:
                    self.capture.on_goal_event(event)
                except Exception:
                    # Storage failures must never erase the controller's outcome.
                    self._interrupt_capture("capture_io_or_source_error")

    def on_watchdog(self) -> None:
        with self._lock:
            if self._active and self.arm.owner.state == "hold":
                reason = getattr(getattr(self.arm, "last_terminal_decision", None), "reason", "owner_hold")
                self._goals[self._active].update(state="UNKNOWN_HOLD", reason=reason)
                self._active = None
                self._interrupt_capture("owner_hold")
