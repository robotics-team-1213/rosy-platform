"""Durable SIM demonstration source; radians and source clocks stay explicit."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from uuid import UUID

from .png import verify_rgb_png
from .artifacts import validate_episode


SCHEMA = "rosy.omx-demonstration.v1"
ROBOT_TYPE = "omx_sim_ros"
ACTION_SEMANTICS = "absolute_joint_position_target_rad"
MAX_SKEW_NS = 50_000_000
MAX_FRAMES = 3000
#: Goal duration bounds: a jog is 0.1-1.0 s (OmxSimJog), a gripper goal up to 2.0 s (D-411 C).
MIN_GOAL_DURATION_S = 0.1
MAX_GOAL_DURATION_S = 2.0  # OMX demonstration v1 (D-411 C), radians and seconds.


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
    if (not isinstance(names, list) or not names or len(names) > 8
            or any(not isinstance(name, str) or not name.strip() for name in names)
            or len(set(names)) != len(names)):
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
        if (goal.int == 0 or str(goal) != row["ros_goal_id"]
                or not isinstance(row.get("command_id"), str) or not row["command_id"].strip()):
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
    verify_rgb_png(data, source["camera"]["width"], source["camera"]["height"])


def _validate_demonstration(path: Path) -> dict:
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
        if error or type(row.get("frame_index")) is not int or row["frame_index"] != index:
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


def validate_demonstration(path: Path) -> dict:
    """Validate complete OMX v1 source, including clocks, radian targets and PNG bytes."""
    try:
        return _validate_demonstration(path)
    except (KeyError, TypeError, AttributeError, IndexError, OverflowError) as error:
        raise ValueError('malformed OMX demonstration') from error


def validate_profile(doc, *, root):
    """Bind common OMX Episode metadata and references to its validated original."""
    value = validate_episode(doc, root=root)
    if value['profile'] != 'omx_demonstration_v1':
        raise ValueError('OMX Episode profile required')
    root = Path(root).resolve()
    candidates = []
    refs = {ref['path']: ref for ref in value['sources']}
    for name in refs:
        if Path(name).name != 'manifest.json':
            continue
        manifest = json.loads((root / name).read_text(encoding='utf-8'))
        if isinstance(manifest, dict) and manifest.get('schema') == SCHEMA:
            candidates.append(name)
    if len(candidates) != 1:
        raise ValueError('exactly one original OMX manifest required')
    name = candidates[0]
    original = root / name
    validated = validate_demonstration(original.parent)
    manifest = validated['manifest']
    provenance = manifest['provenance']
    expected = {'episode_id': manifest['episode_id'], 'device': provenance['instance_id'],
                'robot_type': ROBOT_TYPE, 'environment': 'sim', 'clock_domain': 'gazebo_sim',
                'task': manifest['task'], 'status': 'complete'}
    if any(value[key] != item for key, item in expected.items()):
        raise ValueError('OMX Episode metadata binding differs')
    if (value['revisions']['calibration'] != provenance['calibration_revision']
            or value['outcome'] != {'task': manifest['task_outcome'], 'action': 'unknown',
                                    'judge': 'operator', 'evidence': [refs[name]]}):
        raise ValueError('OMX Episode outcome/calibration binding differs')
    required = ['samples.jsonl', 'events.jsonl'] + [row['image_path'] for row in validated['samples']]
    for relative in required:
        path = (original.parent / relative).relative_to(root).as_posix()
        if path not in refs:
            raise ValueError('original OMX file absent from Episode sources')
    for stream, filename in (('observation', 'samples.jsonl'), ('action', 'samples.jsonl'),
                             ('events', 'events.jsonl')):
        path = (original.parent / filename).relative_to(root).as_posix()
        if value['streams'][stream] != refs[path]:
            raise ValueError('OMX Episode stream binding differs')
    return validated
