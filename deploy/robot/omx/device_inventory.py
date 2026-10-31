#!/usr/bin/env python3
"""Read-only bench inventory and a Learning profile draft (D-943 §2). Opens no serial or camera device.

Boards come from /dev/serial/by-id. A board gets an arm only when an observer env already names it
(ROSY_OBSERVER_DEVICE in omx-observer-<arm>.env); every other board stays unassigned for a person to
name. Cameras come from omx-cameras.json; calibration ids from the LeRobot calibration cache.

  device_inventory.py [--config-dir ~/.config/rosy] > inventory.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

JOINTS = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
DEFAULT_SHAPE = [3, 480, 640]  # LeRobot record default; the person confirms it in the draft


def _env(path: Path) -> dict:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and re.fullmatch(r"[A-Z_][A-Z0-9_]*", key):
            values[key] = value.strip().strip('"')
    return values


def inventory(config_dir: Path, by_id: Path, calibration: Path) -> dict:
    observers = {}
    for env in sorted(config_dir.glob("omx-observer-*.env")):
        device = _env(env).get("ROSY_OBSERVER_DEVICE")
        if device:
            observers[Path(device).name] = env.name[len("omx-observer-"):-len(".env")]
    boards = [{"by_id": p.name, "arm_id": observers.get(p.name), "role": "follower" if p.name in observers else None}
              for p in sorted(by_id.glob("usb-ROBOTIS_*"))] if by_id.is_dir() else []
    calibrations = {kind: sorted(p.stem for p in (calibration / kind).glob("*/*.json"))
                    for kind in ("robots", "teleoperators")}
    cameras_file = config_dir / "omx-cameras.json"
    cameras = json.loads(cameras_file.read_text(encoding="utf-8")).get("cameras", []) if cameras_file.is_file() else []
    arms = sorted({b["arm_id"] for b in boards if b["arm_id"]})
    draft = {"schema": "rosy.omx.learning-profile/1", "name": "", "task": "", "mode": "",
             "arms": [{"id": arm, "joint_names": list(JOINTS), "units": "normalized_-100_100"} for arm in arms],
             "cameras": []}
    for camera in cameras:
        role = camera["role"]
        arm = next((a for a in arms if role.startswith(a + "_")), None)
        draft["cameras"].append({"id": role, "input_key": f"observation.images.{role}", "arm_id": arm,
                                 "role": "wrist" if arm else role, "source_identity": camera["device"],
                                 "placement": "arm_mounted" if arm else "fixed", "shape": list(DEFAULT_SHAPE),
                                 "purposes": ["policy", "record"]})
    return {"schema": "rosy.omx-bench-inventory/1", "boards": boards, "calibrations": calibrations,
            "cameras": [{k: c.get(k) for k in ("role", "device", "topic")} for c in cameras],
            "unassigned_boards": [b["by_id"] for b in boards if not b["arm_id"]], "draft": draft}


def local_inventory() -> dict:
    return inventory(Path("~/.config/rosy").expanduser(), Path("/dev/serial/by-id"),
                     Path("~/.cache/huggingface/lerobot/calibration").expanduser())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--config-dir", type=Path, default=Path("~/.config/rosy").expanduser())
    parser.add_argument("--by-id", type=Path, default=Path("/dev/serial/by-id"))
    parser.add_argument("--calibration", type=Path,
                        default=Path("~/.cache/huggingface/lerobot/calibration").expanduser())
    args = parser.parse_args(argv)
    print(json.dumps(inventory(args.config_dir, args.by_id, args.calibration), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
