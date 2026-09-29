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

from control.sensing.perception.learned.shadow import TOPIC as SHADOW_TOPIC

SCHEMA = "rosy.recording.session/1"

# camera/front is the raw sensor_msgs/Image published by
# control/camera_detect_node.py (no compressed front-camera topic exists in
# src/; camera/preview/compressed in road_observer_node.py is a 2 fps
# dashboard preview, not training data). cmd_vel is the CORE final command;
# line/observation comes from line_observer_node.py; odom from
# products/pinky_pro/bringup/bringup/bringup.py (ODOM_PUB_TOPIC_NAME).
RECORD_TOPICS = (
    "camera/front",
    "cmd_vel",
    "line/observation",
    SHADOW_TOPIC,
    "odom",
)


def _iso(now: datetime) -> str:
    return now.astimezone(timezone.utc).isoformat()


def _write_meta(folder: Path, meta: dict) -> None:
    tmp = folder / "session.json.tmp"
    tmp.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    os.replace(tmp, folder / "session.json")


def _read_meta(folder: Path) -> dict:
    return json.loads((folder / "session.json").read_text(encoding="utf-8"))


def new_session(root, *, device, camera_profile_revision, model_revision,
                task_id, reason, now) -> Path:
    if not device or not reason:
        raise ValueError("device and reason must be non-empty")
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", device)
    stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = Path(root) / f"{stamp}_{safe}"
    folder.mkdir(parents=True, exist_ok=True)
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
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file())


def _sessions(root: Path) -> list[tuple[str, Path, dict]]:
    rows = []
    for folder in root.iterdir() if root.is_dir() else ():
        if (folder / "session.json").is_file():
            meta = _read_meta(folder)
            rows.append((meta["started_at"], folder, meta))
    return sorted(rows, key=lambda r: (r[0], r[1].name))


def enforce_quota(root, quota_bytes) -> list[Path]:
    root = Path(root)
    deleted: list[Path] = []
    for _, folder, meta in _sessions(root):
        if _total_bytes(root) <= quota_bytes:
            break
        if meta.get("harvested") and meta.get("ended_at") is not None:
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
