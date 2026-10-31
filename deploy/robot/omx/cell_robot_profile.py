"""Local per-device operating profile; a Fleet device_id association is never motion authority."""
from __future__ import annotations

import json
from pathlib import Path
import re

from collection_profile import digest

SCHEMA = "rosy.omx-cell-robot-profile.v1"
FIELDS = {"schema", "device_id", "instance_id", "robot_config_sha256", "operating_envelope_path", "work_dir"}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate operating profile field")
        result[key] = value
    return result


def load(path, *, robot_config=None) -> dict:
    path = Path(path).expanduser().resolve()
    document = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique)
    if not isinstance(document, dict) or set(document) != FIELDS or document["schema"] != SCHEMA:
        raise ValueError("expected a per-device operating profile without authority fields")
    device_id, instance = document["device_id"], document["instance_id"]
    if not isinstance(device_id, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", device_id) is None:
        raise ValueError("device_id must identify its descriptive Fleet device profile")
    if not isinstance(instance, str) or not instance.strip() or instance != instance.strip() or "<" in instance:
        raise ValueError("instance_id must name the native follower")
    revision = document["robot_config_sha256"]
    if not isinstance(revision, str) or re.fullmatch(r"[0-9a-f]{64}", revision) is None:
        raise ValueError("robot_config_sha256 must pin the recorder's robot configuration")
    if robot_config is not None and (not isinstance(robot_config, dict)
            or robot_config.get("type") != "omx_follower" or robot_config.get("id") != instance
            or digest(robot_config) != revision):
        raise ValueError("operating profile belongs to another follower or robot configuration")
    paths = {}
    for key in ("operating_envelope_path", "work_dir"):
        value = document[key]
        if not isinstance(value, str) or not value.strip() or value != value.strip() or "<" in value:
            raise ValueError(f"profile {key} must be explicitly configured")
        target = Path(value).expanduser()
        paths[key] = str((target if target.is_absolute() else path.parent / target).resolve())
    return {**paths, "binding": {"device_id": device_id, "instance_id": instance,
            "robot_config_sha256": revision, "profile_sha256": digest({**document, **paths})}}


def bind_pipeline(config: dict, profile_path=None) -> dict:
    selected = Path(profile_path or config["operating_profile_path"]).expanduser().resolve()
    profile = load(selected)
    return {**config, "operating_profile_path": str(selected), "work_dir": profile["work_dir"],
            "operating_envelope_path": profile["operating_envelope_path"],
            "_operating_profile_binding": profile["binding"]}


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="Inspect robot-config pins or validate a profile; never connects hardware")
    parser.add_argument("record_config", type=Path)
    parser.add_argument("--profile", type=Path)
    args = parser.parse_args(argv)
    robot = json.loads(args.record_config.read_text(encoding="utf-8-sig"))["robot"]
    facts = (load(args.profile, robot_config=robot)["binding"] if args.profile else
             {"instance_id": robot["id"], "robot_config_sha256": digest(robot)})
    print(json.dumps({**facts, "motion_admitted": False}))


if __name__ == "__main__":
    main()
