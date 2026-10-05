"""ROS-free recording sessions: session.json, harvest-aware quota, bag command.

D-356. One session folder per recording run; only sessions whose frames were
harvested (and that have ended) may be deleted to satisfy the quota.

D-373 snapshot mode: `ros2 bag record --snapshot-mode` keeps the last ~60 s of
the compressed camera stream in memory. Each snapshot call makes rosbag2 write
the buffer and close that file (a split), so every file but the newest in the
cache folder is complete. The trigger node leaves a request file (reason and
values) before calling the service; record_session moves each closed file into
its own session folder and pairs it with the oldest pending request.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path


SCHEMA = "rosy.recording.session/1"

# Must equal control.sensing.perception.learned.shadow.TOPIC (not imported
# here: that package pulls numpy/cv2; a test asserts the two stay equal).
SHADOW_TOPIC = "perception/learned/shadow"
KEEP_DEBUG_TOPIC = "line/keep_debug"  # source-image diagnostics, never training labels
SHADOW_SCHEMA = "rosy.perception.learned_shadow/1"  # == shadow.SHADOW_SCHEMA

# camera/front is the raw sensor_msgs/Image published by
# control/camera_detect_node.py; camera/front/compressed is its JPEG copy of
# the same frame (D-373, on only with publish_compressed). camera/preview/
# compressed in road_observer_node.py is a 2 fps dashboard preview, not
# training data. cmd_vel is the CORE final command; line/observation comes
# from line_observer_node.py; odom from the product bringup package
# (ODOM_PUB_TOPIC_NAME).
CAMERA_TOPIC = "camera/front"
COMPRESSED_CAMERA_TOPIC = CAMERA_TOPIC + "/compressed"
# scan is the LiDAR sensor_msgs/LaserScan; extract.py attaches the latest scan
# logged at or before each frame (no future leakage, D-356 clock rule), the
# input of LiDAR-projected wall labels (D-373 decision 9, D-379): the LiDAR
# sees walls, never floor paint.
SCAN_TOPIC = "scan"
ODOM_TOPIC = "odom"
# Topics learning/training/perception/dataset/extract.py attaches to each frame as side
# data, keyed by these relative names (prelabel.py reads SHADOW_TOPIC).
SIDE_TOPICS = ("cmd_vel", "line/observation", SHADOW_TOPIC, SCAN_TOPIC, ODOM_TOPIC)

# The camera unit's StateDirectory (D-373 decision 1): no new write path.
DEFAULT_ROOT = "/var/lib/rosy/camera/recordings"

# Snapshot ring buffer, sized for SNAPSHOT_SECONDS of the compressed stream
# (D-136: 60 s, on the robot only). Per 125 ms camera period: a 320x240 JPEG at
# quality 85 is ~10-15 KB on a textured floor, budgeted at 20 KB; the side
# topics (shadow, line/observation, cmd_vel, odom) stay under 4 KB together;
# scan adds up to 8 KB (10 Hz, ~720 beams of float32 ranges and intensities).
# rosbag2 double-buffers the cache, so the resident cost is about twice this.
SNAPSHOT_FRAME_BUDGET_BYTES = 20_000
SNAPSHOT_SCAN_BUDGET_BYTES = 8_000
SNAPSHOT_SIDE_BUDGET_BYTES = 4_000 + SNAPSHOT_SCAN_BUDGET_BYTES
SNAPSHOT_FPS = 8
SNAPSHOT_SECONDS = 60
SNAPSHOT_CACHE_BYTES = ((SNAPSHOT_FRAME_BUDGET_BYTES + SNAPSHOT_SIDE_BUDGET_BYTES)
                        * SNAPSHOT_FPS * SNAPSHOT_SECONDS)  # 15,360,000 bytes
SNAPSHOT_REQUESTS = ".snapshot-requests"
SNAPSHOT_CACHE_PREFIX = ".snapshot-cache-"
SNAPSHOT_NODE_SUFFIX = "snapshot_recorder"


def snapshot_node_name(namespace: str = "") -> str:
    """Recorder node per robot namespace. `ros2 bag record` cannot be placed in
    a namespace (no --ros-args; checked on Jazzy), so the namespace goes into
    the node name: /rosy_01 -> /rosy_01_snapshot_recorder/snapshot."""
    ns = "_".join(p for p in namespace.strip("/").split("/") if p)
    return f"{ns or 'rosy'}_{SNAPSHOT_NODE_SUFFIX}"


def record_topics(camera_topic: str = CAMERA_TOPIC) -> tuple:
    return (camera_topic, *SIDE_TOPICS)


# The one topic list: raw camera by default; snapshot capture passes the
# compressed topic (D-373 decision 3).
RECORD_TOPICS = record_topics()


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
                task_id, reason, now, topics=RECORD_TOPICS, extra=None) -> Path:
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
        "topics": list(topics),
        **(extra or {}),
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


def _ns_topics(topics, namespace: str) -> list[str]:
    ns = namespace.strip("/")
    return [f"/{ns}/{t}" for t in topics] if ns else list(topics)


def bag_command(folder, namespace: str = "", camera_topic: str = CAMERA_TOPIC) -> list[str]:
    """namespace (e.g. "rosy_01") prefixes every recorded topic."""
    return ["ros2", "bag", "record", "--storage", "mcap",
            "--storage-preset-profile", "zstd_fast",
            "--max-bag-duration", "30",
            "-o", str(Path(folder) / "bag"),
            "--topics", *_ns_topics(record_topics(camera_topic), namespace)]


def snapshot_bag_command(cache_dir, namespace: str = "", node_name: str = "") -> list[str]:
    """Snapshot mode: nothing is written until /<node_name>/snapshot is called."""
    return ["ros2", "bag", "record", "--storage", "mcap",
            "--storage-preset-profile", "zstd_fast",
            "--snapshot-mode", "--max-cache-size", str(SNAPSHOT_CACHE_BYTES),
            "--node-name", node_name,
            "-o", str(cache_dir),
            "--topics", *_ns_topics(record_topics(COMPRESSED_CAMERA_TOPIC), namespace)]


def write_snapshot_request(root, reason: str, values: dict, now, *, seq: int | None = None) -> Path:
    """Leave the trigger's reason for record_session before the service call.

    File names sort by `seq` (default CLOCK_MONOTONIC ns, shared by all
    processes of one boot), so an NTP step cannot reorder the FIFO pairing;
    requests left from an earlier boot are dropped when the recorder starts."""
    folder = Path(root) / SNAPSHOT_REQUESTS
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{time.monotonic_ns() if seq is None else seq:020d}_{os.getpid()}"
    path, n = folder / f"{stem}.json", 1
    while path.exists():
        n += 1
        path = folder / f"{stem}_{n:03d}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"reason": reason, "values": values,
                               "requested_at": _iso(now)}), encoding="utf-8")
    os.replace(tmp, path)
    return path


def pending_snapshot_requests(root) -> list[tuple[Path, dict]]:
    """Oldest first; unreadable request files are skipped (and left in place)."""
    folder = Path(root) / SNAPSHOT_REQUESTS
    rows = []
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else ():
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict) and isinstance(doc.get("reason"), str):
            rows.append((path, doc))
    return rows


def _mcap_index(p: Path) -> tuple[int, str]:
    m = re.search(r"_(\d+)\.mcap$", p.name)
    return (int(m.group(1)) if m else -1, p.name)


def snapshot_files(cache_dir) -> list[Path]:
    cache = Path(cache_dir)
    return sorted(cache.glob("*.mcap"), key=_mcap_index) if cache.is_dir() else []


def mcap_message_count(path) -> int | None:
    """Messages in an MCAP file; None when unknown (no reader, unreadable)."""
    try:
        from mcap.reader import make_reader
    except ImportError:
        return None
    try:
        with open(path, "rb") as fh:
            reader = make_reader(fh)
            summary = reader.get_summary()
            if summary is not None and summary.statistics is not None:
                return int(summary.statistics.message_count)
            fh.seek(0)
            return sum(1 for _ in make_reader(fh).iter_messages())
    except Exception:
        return None


def closed_snapshot_files(cache_dir) -> list[Path]:
    """Every file but the newest: rosbag2 closes a file when a snapshot splits it."""
    return snapshot_files(cache_dir)[:-1]


def adopt_snapshot(root, mcap, request, *, device, camera_profile_revision,
                   model_revision, now) -> Path:
    """One snapshot file -> one ended, unharvested session with its trigger."""
    trigger = request or {"reason": "unrequested", "values": {}, "requested_at": None}
    folder = new_session(
        root, device=device, camera_profile_revision=camera_profile_revision,
        model_revision=model_revision, task_id="",
        reason=f"snapshot:{trigger['reason']}", now=now,
        topics=record_topics(COMPRESSED_CAMERA_TOPIC),
        extra={"mode": "snapshot", "trigger": trigger})
    (folder / "bag").mkdir()
    os.replace(mcap, folder / "bag" / Path(mcap).name)
    finish_session(folder, now)
    return folder
