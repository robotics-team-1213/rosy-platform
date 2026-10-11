"""Durable SIM demonstration source; radians and source clocks stay explicit."""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import threading
import time
from pathlib import Path
from uuid import UUID, uuid4

from PIL import Image

from core_common.protocol.omx_sim import GRIPPER_GOAL_MAX_DURATION_S


SCHEMA = "rosy.omx-demonstration.v1"
ROBOT_TYPE = "omx_sim_ros"
ACTION_SEMANTICS = "absolute_joint_position_target_rad"
MAX_SKEW_NS = 50_000_000
MAX_FRAMES = 3000
#: Goal duration bounds: a jog is 0.1-1.0 s (OmxSimJog), a gripper goal up to 2.0 s (D-411 C).
MIN_GOAL_DURATION_S = 0.1
MAX_GOAL_DURATION_S = GRIPPER_GOAL_MAX_DURATION_S


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")


def _provenance(source: dict) -> dict:
    value = json.loads(_json(source))
    if value.get("simulation") is not True or value.get("clock_domain") != "gazebo_sim":
        raise ValueError("explicit simulation and gazebo_sim clock provenance required")
    for field, length in (("source_revision", 40), ("vendor_revision", 40),
                          ("source_tree_sha256", 64), ("world_sha256", 64)):
        if not re.fullmatch(rf"[0-9a-f]{{{length}}}", value.get(field, "")):
            raise ValueError(f"invalid {field}")
    for field in ("instance_id", "calibration_revision"):
        if not isinstance(value.get(field), str) or not value[field].strip():
            raise ValueError(f"missing {field}")
    names = value.get("joint_names", [])
    if not names or len(set(names)) != len(names) or len(names) > 8:
        raise ValueError("invalid joint order")
    # Optional (D-411 C): episodes recorded before the gripper column have no gripper_joint.
    if value.get("gripper_joint") is not None and value["gripper_joint"] not in names:
        raise ValueError("gripper joint must be one of the joints")
    limits = value.get("position_limits_rad", {})
    if set(limits) != set(names):
        raise ValueError("joint limits must match explicit order")
    for limit in limits.values():
        if len(limit) != 2 or not all(_finite(x) for x in limit) or limit[0] >= limit[1]:
            raise ValueError("invalid radian joint limits")
    camera = value.get("camera", {})
    if camera.get("name") != "front" or not camera.get("identity"):
        raise ValueError("explicit front camera identity required")
    if not re.fullmatch(r"[0-9a-f]{64}", camera.get("camera_info_sha256", "")):
        raise ValueError("camera calibration fingerprint required")
    if any(type(camera.get(k)) is not int or not 1 <= camera[k] <= 1920 for k in ("width", "height")):
        raise ValueError("invalid camera dimensions")
    if type(value.get("fps")) is not int or not 1 <= value["fps"] <= 30:
        raise ValueError("invalid sampling fps")
    return value


def _finite(value) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _row_error(row: dict, source: dict, previous_ns: int | None) -> str | None:
    capture, state = row.get("capture_time_ns"), row.get("state_time_ns")
    if any(type(value) is not int or value < 0 for value in (capture, state)):
        return "source_clock"
    if previous_ns is not None and capture <= previous_ns:
        return "clock_not_advancing"
    if previous_ns is not None and abs(capture - previous_ns - 1_000_000_000 / source["fps"]) > 5_000_000:
        return "frame_gap"
    if state > capture:
        return "state_from_future"
    if capture - state > MAX_SKEW_NS:
        return "state_camera_skew"
    names = source["joint_names"]
    for field in ("observation.state", "action"):
        values = row.get(field, [])
        if len(values) != len(names):
            return "joint_map"
        if not all(_finite(value) for value in values):
            return "joint_value"
        if any(not source["position_limits_rad"][name][0] <= value <= source["position_limits_rad"][name][1]
               for name, value in zip(names, values)):
            return "joint_limit"
    try:
        goal = UUID(row.get("ros_goal_id") or "")
        if goal.int == 0 or str(goal) != row["ros_goal_id"] or not row.get("command_id"):
            return "goal_identity"
    except (ValueError, TypeError):
        return "goal_identity"
    if not _finite(row.get("duration_s")) or not MIN_GOAL_DURATION_S <= row["duration_s"] <= MAX_GOAL_DURATION_S:
        return "goal_duration"
    gripper = source.get("gripper_joint")
    if gripper is not None and row.get("action.gripper") != row["action"][names.index(gripper)]:
        return "gripper_action"
    if type(row.get("state_sequence")) is not int or row["state_sequence"] < 0:
        return "state_sequence"
    if type(row.get("received_at_ns")) is not int or row["received_at_ns"] < 0:
        return "receipt_clock"
    return None


def _verify_png(data: bytes, source: dict) -> None:
    with Image.open(io.BytesIO(data)) as image:
        if image.format != "PNG" or image.mode != "RGB" or image.size != (
                source["camera"]["width"], source["camera"]["height"]):
            raise ValueError("PNG dimensions or RGB encoding differ")
        image.verify()


class DemonstrationRecorder:
    """One bounded episode; invalid source data leaves an incomplete manifest."""

    def __init__(self, root: Path, provenance: dict) -> None:
        self.root = Path(root).resolve()
        if self.root.drive.upper() == "F:":
            raise ValueError("recording output belongs on X:, not the source drive")
        self.source = _provenance(provenance)
        self._lock = threading.RLock()
        self._manifest: dict | None = None
        self._path: Path | None = None
        self._samples = None
        self._events = None
        self._previous_ns: int | None = None
        self._frames = 0
        self._issues: list[str] = []

    @property
    def active(self) -> bool:
        return self._samples is not None

    def _write_manifest(self) -> None:
        temporary = self._path / "manifest.json.tmp"
        with temporary.open("wb") as stream:
            stream.write(_json(self._manifest))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self._path / "manifest.json")

    def start(self, task: str) -> dict:
        with self._lock:
            if self.active:
                raise ValueError("episode already active")
            if not isinstance(task, str) or not task.strip() or len(task) > 300:
                raise ValueError("task must be a non-empty description")
            episode_id = str(uuid4())
            self._path = self.root / episode_id
            (self._path / "images/front").mkdir(parents=True, exist_ok=False)
            self._manifest = {"schema": SCHEMA, "episode_id": episode_id, "robot_type": ROBOT_TYPE,
                              "action_semantics": ACTION_SEMANTICS, "provenance": self.source,
                              "task": task.strip(), "status": "recording", "frame_count": 0,
                              "started_wall_time_ns": time.time_ns(), "task_outcome": "unspecified"}
            self._previous_ns, self._frames, self._issues = None, 0, []
            self._samples = (self._path / "samples.jsonl").open("wb")
            self._events = (self._path / "events.jsonl").open("wb")
            self._write_manifest()
            return self.status()

    def issue(self, reason: str) -> None:
        with self._lock:
            if self.active and reason not in self._issues:
                self._issues.append(reason)

    def event(self, event: dict) -> None:
        with self._lock:
            if self.active:
                allowed = {key: value for key, value in event.items() if key in {
                    "kind", "command_id", "goal_id", "sequence", "status", "result_code",
                    "accepted_sim_time_ns", "target", "duration_s"}}
                allowed["received_wall_time_ns"] = time.time_ns()
                self._events.write(_json(allowed) + b"\n")
                self._events.flush()

    def sample(self, *, capture_time_ns: int, state_time_ns: int, positions: dict, target: dict,
               state_sequence: int, command_id: str, ros_goal_id: str | None, duration_s: float,
               image_png: bytes, received_at_ns: int) -> None:
        with self._lock:
            if not self.active:
                return
            if self._frames >= MAX_FRAMES:
                self.issue("frame_limit")
                return
            names = self.source["joint_names"]
            if set(positions) != set(names) or set(target) != set(names):
                self.issue("joint_map")
                return
            row = {"capture_time_ns": capture_time_ns, "state_time_ns": state_time_ns,
                   "received_at_ns": received_at_ns, "state_sequence": state_sequence,
                   "observation.state": [positions[n] for n in names], "action": [target[n] for n in names],
                   "command_id": command_id, "ros_goal_id": ros_goal_id, "duration_s": duration_s}
            if self.source.get("gripper_joint") is not None:
                row["action.gripper"] = target[self.source["gripper_joint"]]
            error = _row_error(row, self.source, self._previous_ns)
            if error:
                self.issue(error)
                return
            try:
                _verify_png(image_png, self.source)
            except Exception:
                self.issue("image_invalid")
                return
            row.update(frame_index=self._frames, image_path=f"images/front/{self._frames:06d}.png",
                       image_sha256=_sha(image_png))
            (self._path / row["image_path"]).write_bytes(image_png)
            self._samples.write(_json(row) + b"\n")
            self._samples.flush()
            self._previous_ns = capture_time_ns
            self._frames += 1

    def status(self) -> dict:
        with self._lock:
            if self._manifest is None:
                return {"status": "idle", "frame_count": 0, "issues": []}
            return {**self._manifest, "frame_count": self._frames, "issues": list(self._issues)}

    def stop(self, outcome: str = "unspecified", *, reason: str | None = None, finalize_reason=None) -> dict:
        with self._lock:
            if not self.active:
                raise ValueError("no active episode")
            if outcome not in {"success", "failure", "unspecified"}:
                raise ValueError("invalid task outcome")
            if reason:
                self.issue(reason)
            if outcome == "unspecified":
                self.issue("outcome_unspecified")
            if self._frames < 2:
                self.issue("insufficient_frames")
            for stream in (self._samples, self._events):
                stream.flush()
                os.fsync(stream.fileno())
                stream.close()
            # The producer fences the episode after draining storage work, so
            # interruptions admitted during closure cannot be lost.
            if finalize_reason is not None:
                final_reason = finalize_reason()
                if final_reason:
                    self.issue(final_reason)
            self._samples = self._events = None
            self._manifest.update(status="incomplete" if self._issues else "complete", task_outcome=outcome,
                                  frame_count=self._frames, issues=list(self._issues),
                                  closed_wall_time_ns=time.time_ns(),
                                  samples_sha256=_sha((self._path / "samples.jsonl").read_bytes()),
                                  events_sha256=_sha((self._path / "events.jsonl").read_bytes()))
            self._write_manifest()
            return self.status()


def validate_episode(path: Path) -> dict:
    """Revalidate source bytes before any LeRobot writer is created."""
    root = Path(path).resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != SCHEMA or manifest.get("robot_type") != ROBOT_TYPE:
        raise ValueError("unsupported demonstration schema or robot type")
    if manifest.get("status") != "complete" or manifest.get("issues"):
        raise ValueError("incomplete demonstration cannot be exported")
    if manifest.get("action_semantics") != ACTION_SEMANTICS:
        raise ValueError("unsupported action semantics")
    if manifest.get("task_outcome") not in {"success", "failure"} or not manifest.get("task", "").strip():
        raise ValueError("explicit task and operator outcome required")
    source = _provenance(manifest["provenance"])
    for file in ("samples", "events"):
        payload = (root / f"{file}.jsonl").read_bytes()
        if _sha(payload) != manifest.get(f"{file}_sha256"):
            raise ValueError(f"{file} hash mismatch")
    samples = [json.loads(line) for line in (root / "samples.jsonl").read_text(encoding="utf-8").splitlines()]
    if not 2 <= len(samples) == manifest.get("frame_count") <= MAX_FRAMES:
        raise ValueError("sample count mismatch")
    previous = None
    for index, row in enumerate(samples):
        error = _row_error(row, source, previous)
        if error or row.get("frame_index") != index:
            raise ValueError(error or "frame index mismatch")
        relative = Path(row.get("image_path", ""))
        image = (root / relative).resolve()
        if (relative.is_absolute() or not image.is_relative_to(root)
                or image.parent != root / "images/front" or (root / relative).is_symlink()):
            raise ValueError("image path escapes episode")
        data = image.read_bytes()
        if _sha(data) != row.get("image_sha256"):
            raise ValueError("image hash mismatch")
        _verify_png(data, source)
        previous = row["capture_time_ns"]
    return {"manifest": manifest, "samples": samples}
