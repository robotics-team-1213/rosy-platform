"""Canonical artifact metadata and file verification, with no runtime dependencies."""
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re


def _json(doc):
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def seal(doc):
    result = json.loads(_json(doc))
    result.pop("revision", None)
    result["revision"] = hashlib.sha256(_json(result)).hexdigest()
    return result


def _fields(doc, fields):
    if not isinstance(doc, dict) or set(doc) != set(fields.split()):
        raise ValueError(f"exact fields required: {fields}")


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("nonempty identifier required")


def _hash(value):
    if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{64}", value):
        raise ValueError("sha256 revision required")


def _base(doc, schema, fields):
    _fields(doc, "schema revision " + fields)
    if doc["schema"] != schema:
        raise ValueError("unsupported artifact schema")
    _hash(doc["revision"])
    result = seal(doc)
    if result["revision"] != doc["revision"]:
        raise ValueError("canonical revision differs")
    return result


def _ref(ref, root):
    _fields(ref, "path sha256 bytes")
    _text(ref["path"])
    _hash(ref["sha256"])
    relative = PurePosixPath(ref["path"])
    if (relative.is_absolute() or ".." in relative.parts or ":" in ref["path"]
            or "\\" in ref["path"] or str(relative) != ref["path"] or str(relative) == "."):
        raise ValueError("unsafe artifact file path")
    if type(ref["bytes"]) is not int or ref["bytes"] < 0:
        raise ValueError("nonnegative file bytes required")
    if root is not None:
        base = Path(root).resolve()
        file = (base / ref["path"]).resolve()
        if not file.is_relative_to(base) or not file.is_file():
            raise ValueError("artifact file path escapes root or is missing")
        digest = hashlib.sha256()
        with file.open("rb") as stream:
            for block in iter(lambda: stream.read(1 << 20), b""):
                digest.update(block)
        if file.stat().st_size != ref["bytes"] or digest.hexdigest() != ref["sha256"]:
            raise ValueError("artifact file hash/size differs")


def _refs(refs, root, *, empty=False):
    if not isinstance(refs, list) or (not refs and not empty):
        raise ValueError("artifact file references required")
    seen = {}
    for ref in refs:
        _ref(ref, root)
        if ref["path"] in seen and seen[ref["path"]] != ref:
            raise ValueError("same file path has conflicting hashes")
        seen[ref["path"]] = ref


def validate_episode(doc, *, root=None):
    value = _base(doc, "rosy.episode/1", "episode_id profile device robot_type environment clock_domain "
                  "task skill revisions sources streams correlations status outcome")
    for field in ("episode_id", "device", "robot_type", "clock_domain", "task"):
        _text(value[field])
    if value["profile"] not in {"omx_demonstration_v1", "pinky_recording_session_v1", "pilot_recording_v1"}:
        raise ValueError("unknown Episode profile")
    if value["environment"] not in {"sim", "real"}:
        raise ValueError("explicit sim/real environment required")
    if value["environment"] == "real" and value["clock_domain"] in {"gazebo_sim", "isaac_sim"}:
        raise ValueError("real Episode cannot use simulation clock")
    if value["skill"] is not None:
        _text(value["skill"])
    _fields(value["revisions"], "policy model calibration camera_profile")
    for revision in value["revisions"].values():
        if revision is not None:
            _text(revision)
    _refs(value["sources"], root)
    _fields(value["streams"], "observation action events")
    for ref in value["streams"].values():
        _ref(ref, root)
    _fields(value["correlations"], "action_ids attempt_ids")
    for ids in value["correlations"].values():
        if not isinstance(ids, list) or len(ids) != len(set(ids)):
            raise ValueError("unique device correlation identifiers required")
        for identity in ids:
            _text(identity)
    if value["status"] not in {"complete", "incomplete"}:
        raise ValueError("explicit recording completion status required")
    outcome = value["outcome"]
    _fields(outcome, "task action judge evidence")
    if outcome["task"] not in {"success", "failure", "unknown"} or outcome["action"] not in {
            "succeeded", "failed", "cancelled", "unknown"}:
        raise ValueError("task and Action outcomes must be separate")
    if outcome["judge"] not in {"operator", "sim_ground_truth", "verifier", "unknown"}:
        raise ValueError("explicit outcome judge required")
    _refs(outcome["evidence"], root, empty=True)
    if outcome["task"] != "unknown" and (outcome["judge"] == "unknown" or not outcome["evidence"]):
        raise ValueError("known task outcome needs judge evidence")
    return value


def validate_dataset(doc, *, root=None):
    value = _base(doc, "rosy.dataset-manifest/1", "episodes transformation files")
    episodes = value["episodes"]
    if not isinstance(episodes, list) or not episodes or len(set(episodes)) != len(episodes):
        raise ValueError("unique immutable Episode revisions required")
    for episode in episodes:
        _hash(episode)
    _fields(value["transformation"], "tool_revision config_sha256")
    _text(value["transformation"]["tool_revision"])
    _hash(value["transformation"]["config_sha256"])
    _refs(value["files"], root)
    return value


def _names(names):
    if not isinstance(names, list) or not names or len(set(names)) != len(names):
        raise ValueError("nonempty unique channel order required")
    for name in names:
        _text(name)


def validate_policy(doc, *, root=None):
    value = _base(doc, "rosy.policy-artifact/1", "profile robot_type environment files "
                  "device_profile_revision camera_profile_revision joint_names normalization observation action "
                  "owner timing failure_mode reset_events dataset_revisions evaluations tool_revision")
    for field in ("robot_type", "device_profile_revision", "camera_profile_revision", "tool_revision"):
        _text(value[field])
    if value["environment"] not in {"sim", "real"}:
        raise ValueError("explicit policy environment required")
    _refs(value["files"], root)
    _ref(value["normalization"], root)
    observation, action = value["observation"], value["action"]
    _fields(observation, "names units shape")
    _names(observation["names"])
    if (not isinstance(observation["units"], list) or len(observation["units"]) != len(observation["names"])
            or not isinstance(observation["shape"], list) or not observation["shape"]
            or any(type(n) is not int or not 1 <= n <= 4096 for n in observation["shape"])):
        raise ValueError("explicit observation shape/units required")
    for unit in observation["units"]:
        _text(unit)
    _fields(action, "names units semantics limits")
    _names(action["names"])
    n = len(action["names"])
    if len(action["units"]) != n or len(action["limits"]) != n:
        raise ValueError("action channel units/limits differ")
    for limits in action["limits"]:
        if (not isinstance(limits, list) or len(limits) != 2
                or any(type(x) not in (int, float) or not math.isfinite(x) for x in limits)
                or limits[0] >= limits[1]):
            raise ValueError("finite ordered action limits required")
    _fields(value["owner"], "kind controller_revision envelope_revision")
    for field in ("controller_revision", "envelope_revision"):
        _text(value["owner"][field])
    if value["profile"] == "omx_joint_target_v1":
        if (action["semantics"] != "absolute_joint_position_target_rad" or action["units"] != ["rad"] * n
                or value["joint_names"] != action["names"] or n > 8
                or value["owner"]["kind"] != "omx_local_controller"):
            raise ValueError("OMX action/owner/joint order binding differs")
    elif value["profile"] == "pinky_base_velocity_v1":
        if (action["semantics"] != "base_velocity_candidate" or action["units"] != ["m/s", "rad/s"]
                or action["names"] != ["linear_x", "angular_z"] or value["joint_names"] != []
                or value["owner"]["kind"] != "pinky_core_command_manager"):
            raise ValueError("Pinky velocity action/owner binding differs")
    else:
        raise ValueError("unknown behavior policy profile")
    _fields(value["timing"], "period_ns max_observation_age_ns max_action_age_ns")
    if any(type(t) is not int or t <= 0 for t in value["timing"].values()):
        raise ValueError("positive integer timing budgets required")
    if value["failure_mode"] != "hold" or set(value["reset_events"]) != {
            "stop", "hold", "lease_change", "episode_change"} or len(value["reset_events"]) != 4:
        raise ValueError("HOLD failure and explicit reset events required")
    revisions = value["dataset_revisions"]
    if not isinstance(revisions, list) or not revisions or len(set(revisions)) != len(revisions):
        raise ValueError("unique training dataset revisions required")
    for revision in revisions:
        _hash(revision)
    _refs(value["evaluations"], root)
    return value


def validate_promotion(doc, policy, *, root=None):
    policy = validate_policy(policy)
    value = _base(doc, "rosy.promotion-record/1", "policy_revision from_stage to_stage checks authority")
    if value["policy_revision"] != policy["revision"]:
        raise ValueError("promotion policy revision differs")
    stages = ["unregistered", "L0", "L1", "L2", "L3"]
    if (value["from_stage"] not in stages[:-1] or value["to_stage"] not in stages[1:]
            or stages.index(value["to_stage"]) != stages.index(value["from_stage"]) + 1):
        raise ValueError("promotion must advance one stage")
    required = {"offline_eval", "sim_eval", "owner_contract", "independent_task_outcome"}
    level = stages.index(value["to_stage"])
    if level >= 2:
        required |= {"shadow_eval", "stop_readback"}
    if level >= 3:
        required.add("restricted_use_eval")
    if level >= 4:
        required.add("registered_scope_eval")
    if not isinstance(value["checks"], list):
        raise ValueError("promotion checks required")
    kinds = []
    for check in value["checks"]:
        _fields(check, "kind verdict report")
        _text(check["kind"])
        if check["verdict"] != "pass":
            raise ValueError("promotion cannot accept failed/unknown evidence")
        _ref(check["report"], root)
        kinds.append(check["kind"])
    if not required <= set(kinds) or len(kinds) != len(set(kinds)):
        raise ValueError("missing or duplicate promotion checks")
    authority = value["authority"]
    if level >= 3 or authority is not None:
        _fields(authority, "adr scope approval")
        _text(authority["adr"])
        _text(authority["scope"])
        _ref(authority["approval"], root)
    return value
