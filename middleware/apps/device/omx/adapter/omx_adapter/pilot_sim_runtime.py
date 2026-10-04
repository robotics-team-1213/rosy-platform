"""SIM-only Pilot facade over the single OMX FollowJointTrajectory owner."""

from __future__ import annotations

import collections
import math
import threading
import time
from pathlib import Path
from typing import Callable, Mapping

import yaml

from core_common.protocol.controls import (
    BOUNDED_JOG_MAX_STEP_RAD, ControlsDescriptor, GripperControl, GripperPresets, JointJogControl,
    JointRange,
)
from core_common.protocol.omx_sim import (
    GRIPPER_GOAL_MAX_DURATION_S, GRIPPER_GOAL_MIN_DURATION_S, OmxSimGripperGoal, OmxSimJog,
)

from .command_owner import TrajectoryCommand
from .kinematics import DEFAULT_KINEMATICS_PATH
from .pilot_sim_gripper import GRIPPER_TOLERANCE_RAD, STILL_RAD, STILL_WINDOW_S, gripper_state

JOG_MAX_STEP_RAD = BOUNDED_JOG_MAX_STEP_RAD
JOG_DURATION_S = 0.4


def _urdf_joints(path: Path | str) -> list[dict]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return [joint for joint in [*document["joints"], *document.get("gripper_joints", ())] if "urdf_limit" in joint]


def urdf_position_limits(path: Path | str = DEFAULT_KINEMATICS_PATH) -> dict[str, tuple[float, float]]:
    """Joint ranges of the pinned vendor URDF, as recorded in ``omx_f_kinematics.yaml``."""
    return {str(joint["name"]): (float(joint["urdf_limit"]["lower"]), float(joint["urdf_limit"]["upper"]))
            for joint in _urdf_joints(path)}


def urdf_velocity_limits(path: Path | str = DEFAULT_KINEMATICS_PATH) -> dict[str, float]:
    """Joint speed limits (rad/s) of the pinned vendor URDF."""
    return {str(joint["name"]): float(joint["urdf_limit"]["velocity"])
            for joint in _urdf_joints(path) if "velocity" in joint["urdf_limit"]}


def sim_admission_limits(cell_limits: Mapping[str, tuple[float, float]],
                         urdf_limits: Mapping[str, tuple[float, float]]) -> dict[str, tuple[float, float]]:
    """SIM owner admission range per joint: the cell profile range within the URDF range (D-411 C).

    Every cell joint must have a URDF range: a joint the URDF does not bound is a profile error.
    """
    limits = {}
    for name, (lower, upper) in cell_limits.items():
        if name not in urdf_limits:
            raise ValueError(f"{name}: no URDF range for this cell profile joint")
        urdf_lower, urdf_upper = urdf_limits[name]
        lower, upper = max(lower, urdf_lower), min(upper, urdf_upper)
        if not lower < upper:
            raise ValueError(f"{name}: cell profile range lies outside the URDF range")
        limits[name] = (lower, upper)
    return limits


def _outside(value: float, lower: float, upper: float) -> float:
    return max(lower - value, 0.0, value - upper)


class PilotSimRuntime:
    """``position_limits`` of the owner config are the admission ranges (already within the URDF).

    Pilot is offered each range inset by ``range_inset_rad`` (the start-state tolerance), so an
    overshoot past an offered bound still reads back inside admission and never latches HOLD.
    Gripper mode (D-411 C, all of ``gripper_open``/``gripper_closed``/``gripper_velocity``/
    ``gripper_preload``): the gripper takes absolute goals and leaves joint_jog. Without it the
    gripper stays a jog joint (servers before D-411 C).
    """

    def __init__(self, arm, *, gripper: str = "gripper_joint_1", range_inset_rad: float = 0.0,
                 gripper_open: float | None = None, gripper_closed: float | None = None,
                 gripper_velocity: float | None = None, gripper_preload: float | None = None) -> None:
        self.arm = arm
        self.instance_id = arm.owner.config.instance_id
        self.joint_names = arm.owner.config.joint_names
        self.gripper = gripper
        self.range_inset_rad = float(range_inset_rad)
        self._offered = {}
        for name, (lower, upper) in arm.owner.config.position_limits.items():
            offered = (lower + self.range_inset_rad, upper - self.range_inset_rad)
            if not (self.range_inset_rad >= 0 and offered[0] < offered[1]):
                raise ValueError(f"{name}: range inset leaves no range")
            self._offered[name] = offered
        spec = (gripper_open, gripper_closed, gripper_velocity, gripper_preload)
        if any(value is not None for value in spec) and any(value is None for value in spec):
            raise ValueError("gripper mode needs open, closed, velocity and preload together")
        self._gripper_spec = None if gripper_open is None else (float(gripper_open), float(gripper_closed))
        if self._gripper_spec is not None:
            if not (math.isfinite(gripper_velocity) and gripper_velocity > 0):
                raise ValueError("gripper velocity must be finite and positive")
            if not 0 <= gripper_preload < abs(self._gripper_spec[0] - self._gripper_spec[1]):
                raise ValueError("gripper preload must be within the stroke")
        self.gripper_velocity = None if gripper_velocity is None else float(gripper_velocity)
        self.gripper_preload = None if gripper_preload is None else float(gripper_preload)
        self._gripper_goal: tuple[str, float] | None = None   # (command_id, target)
        self._gripper_stall: float | None = None              # readback when that goal SUCCEEDED
        self._hold_pending = False                            # re-issue the squeeze after a holding close
        self._gripper_samples: collections.deque = collections.deque(maxlen=32)
        self.camera_available = False
        self.capture = None
        self._lock = threading.RLock()
        self._goals: dict[str, dict] = {}
        self._active: str | None = None
        self._last_event_sequence: dict[str, int] = {}
        self._served_sequences: dict[int, float] = {}

    @property
    def gripper_joint_for_goals(self) -> str | None:
        """The joint that takes absolute gripper goals (recorded as ``action.gripper``), else None."""
        return self.gripper if self._gripper_spec is not None else None

    def offered_range(self, name: str) -> tuple[float, float]:
        return self._offered[name]

    def snapshot(self) -> dict:
        state = self.arm.latest_joint_state
        age = None if state is None else time.monotonic() - state.received_at
        action_server_ready = self.arm.action_port.server_is_ready()
        fresh = state is not None and 0 <= age <= self.arm.owner.config.max_joint_state_age_s
        ready = fresh and self.arm.owner.state == "ready" and action_server_ready
        if ready:
            with self._lock:
                now = time.monotonic()
                self._served_sequences = {seq: issued for seq, issued in self._served_sequences.items()
                                          if now - issued <= 5.0}
                self._served_sequences[state.sequence] = now
        snapshot = {"instance_id": self.instance_id, "ready": ready,
                    "owner_state": self.arm.owner.state,
                    "owner_reason": (getattr(getattr(self.arm, "last_terminal_decision", None), "reason", "")
                                     if self.arm.owner.state == "hold" else ""),
                    "action_server_ready": action_server_ready,
                    "state_sequence": state.sequence if state else None,
                    "joint_age_ms": round(age * 1000) if age is not None else None,
                    "positions": dict(state.positions) if state else {},
                    "active_goal": self._active}
        if self._gripper_spec is not None:
            self._sample_gripper()
            snapshot["gripper"] = self._gripper_snapshot(
                state if fresh and self.arm.owner.state != "hold" else None)
        return snapshot

    def _sample_gripper(self) -> None:
        """Record gripper readback per joint_states sequence (watchdog 10 Hz and every /state)."""
        state = self.arm.latest_joint_state
        if self._gripper_spec is None or state is None or self.gripper not in state.positions:
            return
        with self._lock:
            if not self._gripper_samples or self._gripper_samples[-1][0] != state.sequence:
                self._gripper_samples.append((state.sequence, state.received_at, state.positions[self.gripper]))
            # No readback at the terminal callback: the first fresh one afterwards is the stall.
            if (self._gripper_stall is None and self._gripper_goal is not None
                    and self._goals.get(self._gripper_goal[0], {}).get("state") == "SUCCEEDED"
                    and 0 <= time.monotonic() - state.received_at <= self.arm.owner.config.max_joint_state_age_s):
                self._record_stall(state.positions[self.gripper])

    def _record_stall(self, position: float | None) -> None:
        self._gripper_stall = position
        closed = self._gripper_spec[1]
        # After SUCCEEDED the controller keeps commanding the close goal's own last point (JTC
        # set_success_trajectory_point), i.e. the full stall error. A holding close is re-issued
        # once at stall + preload so the idle squeeze equals the bounded squeeze of later arm goals.
        self._hold_pending = (position is not None and self._gripper_goal is not None
                              and abs(self._gripper_goal[1] - closed) <= GRIPPER_TOLERANCE_RAD
                              and abs(position - closed) > GRIPPER_TOLERANCE_RAD)

    def _gripper_snapshot(self, state) -> dict:
        open_, closed = self._gripper_spec
        position = None if state is None else state.positions.get(self.gripper)
        with self._lock:
            now = time.monotonic()
            moved = position is not None and any(
                abs(sample - position) > STILL_RAD for _, received, sample in self._gripper_samples
                if now - received <= STILL_WINDOW_S)
            goal = None
            if self._gripper_goal is not None and self._gripper_goal[0] in self._goals:
                command_id, target = self._gripper_goal
                goal = {"target": target, "state": self._goals[command_id]["state"]}
            hold_target = self._held_gripper_target()
        return {"joint": self.gripper, "position": position, "open": open_, "closed": closed,
                "state": gripper_state(position=position, fresh=position is not None, closed=closed,
                                       goal=goal, moved_recently=moved),
                "hold_target": hold_target}

    def controls(self) -> dict:
        """rosy.controls/1 for this SIM workcell (D-411 B, C). Bounded goals only (D-390 §2).

        Each published range is the owner's admission range (cell profile within URDF) inset by
        ``range_inset_rad``, so Pilot never offers a target the owner would reject or HOLD on.
        """
        jog = JointJogControl(
            id="arm", label="팔", max_step_rad=JOG_MAX_STEP_RAD, duration_s=JOG_DURATION_S,
            joints=tuple(JointRange(name=name, lower=self._offered[name][0], upper=self._offered[name][1])
                         for name in self._jog_joints()))
        items: list = [jog]
        if self._gripper_spec is not None:
            open_, closed = self._gripper_spec
            items.append(GripperControl(
                id="gripper", label="그리퍼", joint=self.gripper, closed=closed, open=open_,
                presets=GripperPresets(open=open_, half=(open_ + closed) / 2, close=closed),
                max_velocity=self.gripper_velocity))
        return ControlsDescriptor(items=tuple(items)).model_dump(by_alias=True, mode="json")

    def _jog_joints(self) -> tuple[str, ...]:
        if self._gripper_spec is None:
            return tuple(self.joint_names)
        return tuple(name for name in self.joint_names if name != self.gripper)

    def _held_gripper_target(self) -> float | None:
        """Gripper target for an arm goal after a finished gripper goal (None = keep readback).

        A close that stopped short of closed (holding) is squeezed by a bounded preload past the
        stall position, never commanded all the way to closed; otherwise the goal target is kept.
        """
        if self._gripper_goal is None or self._goals.get(self._gripper_goal[0], {}).get("state") != "SUCCEEDED":
            return None
        target = self._gripper_goal[1]
        closed = self._gripper_spec[1]
        stall = self._gripper_stall
        if (stall is None or abs(target - closed) > GRIPPER_TOLERANCE_RAD
                or abs(stall - closed) <= GRIPPER_TOLERANCE_RAD):
            return target
        direction = math.copysign(1.0, closed - stall)
        squeezed = stall + direction * self.gripper_preload
        return closed if (closed - squeezed) * direction < 0 else squeezed

    def submit(self, jog: OmxSimJog) -> dict:
        def place(target: dict, limits: Mapping) -> str:
            held = self._held_gripper_target()
            if held is not None:
                target[self.gripper] = held
            current = target[jog.joint]
            target[jog.joint] = current + jog.delta_rad
            lower, upper = limits[jog.joint]
            offered_lower, offered_upper = self._offered[jog.joint]
            # Within admission, and never further outside the offered range than the readback is.
            if not lower <= target[jog.joint] <= upper or (
                    _outside(target[jog.joint], offered_lower, offered_upper)
                    > _outside(current, offered_lower, offered_upper)):
                return "joint_limit"
            return ""

        admitted = "" if jog.joint in self._jog_joints() else "joint_not_admitted"
        return self._dispatch(jog.request_id, jog.instance_id, jog.state_sequence, jog.duration_s,
                              place, admitted)

    def submit_gripper(self, goal: OmxSimGripperGoal) -> dict:
        """One absolute gripper goal; the arm joints keep their readback (D-411 C)."""
        def place(target: dict, limits: Mapping) -> str:
            readback = target[self.gripper]
            offered_lower, offered_upper = self._offered[self.gripper]
            if not offered_lower <= goal.position <= offered_upper:
                return "gripper_limit"
            # Bounded slack: the readback the client sized the goal from may have drifted a little.
            if abs(goal.position - readback) - GRIPPER_TOLERANCE_RAD > self.gripper_velocity * goal.duration_s:
                return "gripper_velocity_limit"
            target[self.gripper] = goal.position
            return ""

        configured = "" if self._gripper_spec is not None else "gripper_not_configured"
        with self._lock:
            result = self._dispatch(goal.request_id, goal.instance_id, goal.state_sequence,
                                    goal.duration_s, place, configured)
            if result["state"] != "REJECTED":
                self._gripper_goal = (goal.request_id, goal.position)
                self._gripper_stall = None
                self._hold_pending = False
            return result

    def _dispatch(self, request_id: str, instance_id: str, state_sequence: int, duration_s: float,
                  place: Callable[[dict, Mapping], str], not_admitted: str) -> dict:
        """Shared checks (instance, admission, single active goal, ready, served readback) and dispatch."""
        with self._lock:
            state = self.arm.latest_joint_state
            config = self.arm.owner.config
            reason = ""
            if instance_id != self.instance_id:
                reason = "instance_mismatch"
            elif not_admitted:
                reason = not_admitted
            elif self._active is not None:
                reason = "goal_active"
            elif not self.snapshot()["ready"]:
                reason = "readback_or_controller_not_ready"
            elif (state_sequence > state.sequence
                  or time.monotonic() - self._served_sequences.get(state_sequence, float("-inf")) > 5.0):
                reason = "readback_not_recently_served"
            if reason:
                return {"command_id": request_id, "state": "REJECTED", "reason": reason}
            target = dict(state.positions)
            reason = place(target, config.position_limits)
            if reason:
                return {"command_id": request_id, "state": "REJECTED", "reason": reason}
            return self._send(request_id, state, target, duration_s)

    def _send(self, request_id: str, state, target: dict, duration_s: float) -> dict:
        with self._lock:
            config = self.arm.owner.config
            command = TrajectoryCommand(
                workcell_id=config.workcell_id, instance_id=config.instance_id,
                command_id=request_id, session_id=self.arm.owner.session_id,
                owner="pilot_sim", positions=target, duration_s=duration_s,
                source_state_sequence=state.sequence,
                calibration_revision=config.calibration_revision,
                joint_names=config.joint_names,
            )
            # Register before dispatch: a local ActionServer may respond synchronously.
            receipt = {"command_id": request_id, "state": "LOCAL_ACCEPTED", "reason": ""}
            self._goals[request_id] = receipt
            self._active = request_id
            if self.capture is not None:
                self.capture.prepare(command)
            decision = self.arm.submit(command)
            if not decision.accepted:
                self._goals.pop(request_id, None)
                self._active = None
                if self.capture is not None:
                    self.capture.discard(request_id)
                return {"command_id": request_id, "state": "REJECTED", "reason": decision.reason}
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
                    if self._gripper_goal is not None and self._gripper_goal[0] == event.command_id:
                        # The stall position a holding squeeze is bounded from (never closed itself).
                        state = self.arm.latest_joint_state
                        self._record_stall(None if state is None else state.positions.get(self.gripper))
                elif event.status == 5:
                    receipt.update(state="CANCELED", ros_goal_id=event.goal_id)
                else:
                    # A failed or timed-out goal is never holding: it is HOLD evidence, kept verbatim.
                    receipt.update(state="UNKNOWN_HOLD",
                                   reason=f"terminal_status_{event.status}_result_{event.result_code}")
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

    def _issue_hold(self) -> None:
        """One goal that moves only the gripper target to stall + preload (D-411 C review L1)."""
        with self._lock:
            if not self._hold_pending or self._active is not None or self.arm.owner.state != "ready":
                return
            state = self.arm.latest_joint_state
            if state is None or not 0 <= time.monotonic() - state.received_at <= self.arm.owner.config.max_joint_state_age_s:
                return
            self._hold_pending = False
            held = self._held_gripper_target()
            if held is None:
                return
            target = dict(state.positions)
            target[self.gripper] = held
            duration = min(max(abs(held - state.positions[self.gripper]) / self.gripper_velocity,
                               GRIPPER_GOAL_MIN_DURATION_S), GRIPPER_GOAL_MAX_DURATION_S)
            self._send(f"hold-{self._gripper_goal[0]}", state, target, duration)

    def on_watchdog(self) -> None:
        self._sample_gripper()
        self._issue_hold()
        with self._lock:
            if self._active and self.arm.owner.state == "hold":
                reason = getattr(getattr(self.arm, "last_terminal_decision", None), "reason", "owner_hold")
                self._goals[self._active].update(state="UNKNOWN_HOLD", reason=reason)
                self._active = None
                self._interrupt_capture("owner_hold")
