"""Pair Gazebo camera samples with past source-stamped states and ROS goals."""

from __future__ import annotations

import io
import json
import threading
import time
from collections import deque
from pathlib import Path
from uuid import UUID

from PIL import Image

from .demonstration import DemonstrationRecorder, MAX_FRAMES


class PilotSimCapture:
    def __init__(self, runtime, root: Path, source: dict, *, sim_time_ns) -> None:
        self.runtime = runtime
        self.root = Path(root).resolve()
        self.source = source
        self.sim_time_ns = sim_time_ns
        self.camera = None
        self.recorder = None
        self._lock = threading.RLock()
        self._states = deque(maxlen=1000)
        self._state_sequence = 0
        self._pending = {}
        self._action = None
        self._last_frame_sequence = None
        self._events = deque(maxlen=1000)
        self._interrupt_reason = None
        self._sealed_recorder = None
        self._episode_id = None

    def observe_joint_state(self, message) -> None:
        stamp = message.header.stamp
        source_ns = int(stamp.sec) * 1_000_000_000 + int(stamp.nanosec)
        positions = dict(zip(message.name, message.position))
        names = self.runtime.arm.owner.config.joint_names
        if any(name not in positions for name in names):
            self.request_interrupt("joint_map")
            return
        with self._lock:
            self._state_sequence += 1
            self._states.append((source_ns, self._state_sequence, {name: positions[name] for name in names},
                                 time.monotonic()))

    def camera_status(self) -> dict:
        frame = self.camera.latest_frame if self.camera is not None else None
        return {"available": self.camera is not None,
                "sim_time_ns": self.sim_time_ns(),
                "fresh": bool(frame and self.camera.is_fresh()),
                "capture_time_ns": frame[0].capture_time_ns if frame else None,
                "age_ms": round((time.monotonic() - frame[0].received_at) * 1000) if frame else None,
                "camera_identity": frame[0].camera_identity if frame else None,
                "width": frame[0].width if frame else None, "height": frame[0].height if frame else None}

    def _image(self) -> Image.Image:
        if not self.camera_status()["fresh"]:
            raise ValueError("camera unavailable or stale")
        _, raw, _ = self.camera.latest_frame
        if raw.encoding not in {"rgb8", "bgr8"}:
            raise ValueError("RGB camera encoding required")
        return Image.frombytes("RGB", (raw.width, raw.height), bytes(raw.data),
                               "raw", "RGB" if raw.encoding == "rgb8" else "BGR", raw.step)

    def camera_jpeg(self) -> bytes:
        output = io.BytesIO()
        self._image().save(output, format="JPEG", quality=85)
        return output.getvalue()

    def start(self, task: str) -> dict:
        if not self.runtime.snapshot()["ready"] or not self.camera_status()["fresh"]:
            raise ValueError("fresh camera, joint readback and idle command owner required")
        with self._lock:
            if self.recorder is not None and self.recorder.active:
                raise ValueError("episode already active")
            config = self.runtime.arm.owner.config
            metadata = self.camera.latest_frame[0]
            provenance = {**self.source, "simulation": True, "clock_domain": "gazebo_sim", "fps": 10,
                          "instance_id": self.runtime.instance_id, "joint_names": list(config.joint_names),
                          "position_limits_rad": dict(config.position_limits),
                          # D-411 C: the gripper takes absolute goals, recorded as action.gripper.
                          "gripper_joint": getattr(self.runtime, "gripper_joint_for_goals", None),
                          "calibration_revision": config.calibration_revision,
                          "camera": {"name": "front", "identity": metadata.camera_identity,
                                     "width": metadata.width, "height": metadata.height,
                                     "camera_info_sha256": self.camera.gate.config.camera_info_sha256}}
            self.recorder = DemonstrationRecorder(self.root, provenance)
            self._action = None
            self._pending.clear()
            self._events.clear()
            self._interrupt_reason = None
            self._sealed_recorder = None
            self._last_frame_sequence = metadata.sequence
            result = self.recorder.start(task)
            self._episode_id = result["episode_id"]
            return result

    def status(self) -> dict:
        with self._lock:
            recorder = self.recorder
        return recorder.status() if recorder else {"status": "idle", "frame_count": 0, "issues": []}

    def stop(self, episode_id: str, outcome: str) -> dict:
        with self._lock:
            if not self.recorder or self._episode_id != episode_id:
                raise ValueError("episode unknown")
            recorder, events, reason = self.recorder, list(self._events), self._interrupt_reason
            self._events.clear()
        for event in events:
            recorder.event(event)
        return recorder.stop(outcome, reason=reason, finalize_reason=lambda: self._seal_episode(recorder))

    def _seal_episode(self, recorder) -> str | None:
        with self._lock:
            if self.recorder is not recorder:
                return None
            self._sealed_recorder = recorder
            return self._interrupt_reason

    def manifest(self, episode_id: str) -> dict:
        if str(UUID(episode_id)) != episode_id:
            raise ValueError("invalid episode identity")
        path = self.root / episode_id / "manifest.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def interrupt(self, reason: str, *, recorder=None) -> None:
        with self._lock:
            recorder = recorder or self.recorder
        if recorder is not None and recorder.active:
            try:
                recorder.stop(reason=reason, finalize_reason=lambda: self._seal_episode(recorder))
            except ValueError:
                if recorder.active:
                    raise

    def request_interrupt(self, reason: str) -> None:
        """ROS/control callbacks enqueue closure; the writer owns disk I/O."""
        with self._lock:
            if self.recorder is not None and self.recorder is not self._sealed_recorder:
                self._interrupt_reason = self._interrupt_reason or reason

    def prepare(self, command) -> None:
        with self._lock:
            if self.recorder is not None and self.recorder.active:
                self._pending[command.command_id] = command

    def discard(self, command_id: str) -> None:
        with self._lock:
            self._pending.pop(command_id, None)

    def on_goal_event(self, event) -> None:
        with self._lock:
            if (self.recorder is None or not self.recorder.active
                    or self.recorder is self._sealed_recorder):
                return
            if event.kind != "RUNNING_FEEDBACK":
                if len(self._events) == self._events.maxlen:
                    self._interrupt_reason = "event_buffer_full"
                self._events.append({name: getattr(event, name) for name in (
                    "kind", "command_id", "goal_id", "sequence", "status", "result_code")})
            command = self._pending.get(event.command_id)
            if event.kind == "GOAL_ACCEPTED" and command is not None:
                self._action = {"command_id": command.command_id, "ros_goal_id": event.goal_id,
                                "target": dict(command.positions), "duration_s": command.duration_s,
                                "accepted_sim_time_ns": self.sim_time_ns()}
                self._events[-1].update(accepted_sim_time_ns=self._action["accepted_sim_time_ns"],
                                        target=dict(command.positions), duration_s=command.duration_s)
            if event.kind == "TERMINAL_RESULT":
                self._pending.pop(event.command_id, None)
                if event.status != 4 or event.result_code != 0:
                    self._interrupt_reason = "goal_terminal_unsuccessful"
            elif event.kind in {"GOAL_REJECTED", "GOAL_ACCEPTANCE_UNKNOWN", "TERMINAL_UNKNOWN"}:
                self._interrupt_reason = "goal_acceptance_or_result_unknown"

    def tick(self) -> None:
        owner_state = self.runtime.arm.owner.state
        with self._lock:
            if self.recorder is None or not self.recorder.active:
                return
            recorder = self.recorder
            events = list(self._events)
            self._events.clear()
            reason = self._interrupt_reason
            if owner_state == "hold":
                reason = reason or "owner_hold"
            if not self.camera_status()["fresh"]:
                reason = reason or "camera_stale"
            frame = self.camera.latest_frame if self.camera else None
            action = dict(self._action) if self._action else None
            states = list(self._states)
        # Disk/encoding work runs outside the capture lock and ROS executor.
        for event in events:
            recorder.event(event)
        if reason:
            self.interrupt(reason, recorder=recorder)
            return
        if frame is not None:
            metadata, raw, _ = frame
            if metadata.sequence == self._last_frame_sequence or action is None:
                return
            if metadata.capture_time_ns < action["accepted_sim_time_ns"]:
                return
            self._last_frame_sequence = metadata.sequence
            past = [s for s in states if s[0] <= metadata.capture_time_ns]
            if not past:
                recorder.issue("state_camera_skew")
                return
            source_ns, sequence, positions, received_at = max(past, key=lambda s: s[0])
            # A delayed camera must pair with historical state, while the live
            # state stream itself must still satisfy the command freshness gate.
            if time.monotonic() - states[-1][3] > self.runtime.arm.owner.config.max_joint_state_age_s:
                self.interrupt("joint_readback_stale", recorder=recorder)
                return
            output = io.BytesIO()
            if raw.encoding not in {"rgb8", "bgr8"}:
                self.interrupt("image_encoding", recorder=recorder)
                return
            Image.frombytes("RGB", (raw.width, raw.height), bytes(raw.data),
                            "raw", "RGB" if raw.encoding == "rgb8" else "BGR", raw.step).save(output, "PNG")
            action.pop("accepted_sim_time_ns")
            recorder.sample(capture_time_ns=metadata.capture_time_ns, state_time_ns=source_ns,
                            positions=positions, state_sequence=sequence, image_png=output.getvalue(),
                            received_at_ns=time.time_ns(), **action)
            if recorder.status()["frame_count"] >= MAX_FRAMES:
                self.interrupt("frame_limit", recorder=recorder)
