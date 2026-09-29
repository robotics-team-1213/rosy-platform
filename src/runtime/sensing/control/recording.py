"""ROS-free recording sessions: session.json, harvest-aware quota, bag command.

D-356. One session folder per recording run; only sessions whose frames were
harvested (and that have ended) may be deleted to satisfy the quota.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path


SCHEMA = "rosy.recording.session/1"

# Must equal control.sensing.perception.learned.shadow.TOPIC (not imported
# here: that package pulls numpy/cv2; a test asserts the two stay equal).
SHADOW_TOPIC = "perception/learned/shadow"

# camera/front is the raw sensor_msgs/Image published by
# control/camera_detect_node.py (no compressed front-camera topic exists in
# src/; camera/preview/compressed in road_observer_node.py is a 2 fps
# dashboard preview, not training data). cmd_vel is the CORE final command;
# line/observation comes from line_observer_node.py; odom from
# products/pinky_pro/bringup/bringup/bringup.py (ODOM_PUB_TOPIC_NAME).
CAMERA_TOPIC = "camera/front"
# Topics tools/perception/dataset/extract.py attaches to each frame as side
# data, keyed by these relative names (prelabel.py reads SHADOW_TOPIC).
SIDE_TOPICS = ("cmd_vel", "line/observation", SHADOW_TOPIC)
RECORD_TOPICS = (CAMERA_TOPIC, *SIDE_TOPICS, "odom")


def _iso(now: datetime) -> str:
    return now.astimezone(timezone.utc).isoformat()


def _write_meta(folder: Path, meta: dict) -> None:
    tmp = folder / "session.json.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(meta, indent=2))
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, folder / "session.json")


def _read_meta(folder: Path) -> dict:
    return json.loads((folder / "session.json").read_text(encoding="utf-8"))


def new_session(root, *, device, camera_profile_revision, model_revision,
                task_id, reason, now) -> Path:
    if not device or not reason:
        raise ValueError("device and reason must be non-empty")
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", device)
    stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = Path(root) / f"{stamp}_{safe}"
    folder, n = base, 1
    while True:
        try:
            folder.mkdir(parents=True)
            break
        except FileExistsError:
            n += 1
            folder = base.with_name(f"{base.name}_{n}")
    _write_meta(folder, {
        "schema": SCHEMA,
        "device": safe,
        "camera_profile_revision": camera_profile_revision,
        "model_revision": model_revision,
        "task_id": task_id,
        "reason": reason,
        "started_at": _iso(now),
        "ended_at": None,
        "harvested": False,
        "topics": list(RECORD_TOPICS),
    })
    return folder


def finish_session(folder, now) -> None:
    folder = Path(folder)
    meta = _read_meta(folder)
    meta["ended_at"] = _iso(now)
    _write_meta(folder, meta)


def mark_harvested(folder) -> None:
    folder = Path(folder)
    meta = _read_meta(folder)
    meta["harvested"] = True
    _write_meta(folder, meta)


def _total_bytes(root: Path) -> int:
    total = 0
    for p in root.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:  # vanished mid-scan
            continue
    return total


def _sessions(root: Path) -> list[tuple[str, Path, dict]]:
    rows = []
    for folder in root.iterdir() if root.is_dir() else ():
        if (folder / "session.json").is_file():
            try:
                meta = _read_meta(folder)
            except (OSError, ValueError):
                continue
            if isinstance(meta, dict) and isinstance(
                    meta.get("started_at"), str):
                rows.append((meta["started_at"], folder, meta))
    return sorted(rows, key=lambda r: (r[0], r[1].name))


def enforce_quota(root, quota_bytes) -> list[Path]:
    root = Path(root)
    deleted: list[Path] = []
    total = _total_bytes(root)
    for _, folder, meta in _sessions(root):
        if total <= quota_bytes:
            break
        if meta.get("harvested") is True and meta.get("ended_at") is not None:
            total -= _total_bytes(folder)
            shutil.rmtree(folder)
            deleted.append(folder)
    return deleted


def can_record(root, quota_bytes) -> bool:
    enforce_quota(root, quota_bytes)
    return _total_bytes(Path(root)) < quota_bytes


def bag_command(folder) -> list[str]:
    return ["ros2", "bag", "record", "--storage", "mcap",
            "--storage-preset-profile", "zstd_fast",
            "--max-bag-duration", "30",
            "-o", str(Path(folder) / "bag"), *RECORD_TOPICS]
