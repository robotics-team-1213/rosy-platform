"""D-411 A: the Pilot recording session. ROS-free; pilot_recorder_node is a thin wrapper.

One session at a time, at most MAX_DURATION_S, a dedicated quota. Stopping never blocks a
ROS callback: stop() sends SIGINT, tick() finishes the session once rosbag2 has exited.
Only fetched (fetched.json) finished sessions are ever evicted.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from core_common.protocol.recording import (
    FETCHED_NAME, MANIFEST_NAME, MANIFEST_SCHEMA, MAX_DURATION_S, SESSION_NAME, STATUS_SCHEMA,
    TELEOP_INTENT_TOPIC, recording_id_ok)
from control.recording import (
    COMPRESSED_CAMERA_TOPIC, ODOM_TOPIC, SCAN_TOPIC, _iso, _ns_topics, _read_meta, _sessions,
    _total_bytes, finish_session, new_session)

PILOT_TOPICS = (COMPRESSED_CAMERA_TOPIC, "cmd_vel", ODOM_TOPIC, SCAN_TOPIC, "line/observation",
                TELEOP_INTENT_TOPIC)
DEFAULT_QUOTA_BYTES = 4 * 1024 ** 3
STOP_TIMEOUT_S = 6.0
_HASH_CHUNK = 1 << 20
_SHUTDOWN_POLL_S = 0.1


def pilot_bag_command(folder, namespace: str = "") -> list[str]:
    return ["ros2", "bag", "record", "--storage", "mcap",
            "--storage-preset-profile", "zstd_fast", "--max-bag-duration", "30",
            "-o", str(Path(folder) / "bag"), "--topics", *_ns_topics(PILOT_TOPICS, namespace)]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(_HASH_CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def write_manifest(folder: Path, *, stop_reason: str, duration_s: float) -> Path:
    meta = _read_meta(folder)
    files = []
    for path in sorted(p for p in folder.rglob("*") if p.is_file() and not p.is_symlink()):
        rel = path.relative_to(folder).as_posix()
        if rel in (MANIFEST_NAME, FETCHED_NAME) or rel.endswith(".tmp") or rel.startswith("."):
            continue
        files.append({"path": rel, "bytes": path.stat().st_size, "sha256": _sha256(path)})
    body = {"schema": MANIFEST_SCHEMA, "id": folder.name, "started_at": meta["started_at"],
            "ended_at": meta["ended_at"], "duration_s": round(duration_s, 3),
            "topics": list(meta.get("topics", ())), "stop_reason": stop_reason, "files": files}
    tmp = folder / (MANIFEST_NAME + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(body, handle, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, folder / MANIFEST_NAME)
    return folder / MANIFEST_NAME


class PilotRecorder:
    def __init__(self, root, *, device: str, namespace: str = "",
                 quota_bytes: int = DEFAULT_QUOTA_BYTES, max_duration_s: int = MAX_DURATION_S,
                 popen=subprocess.Popen, clock=time.monotonic,
                 now=lambda: datetime.now(timezone.utc)) -> None:
        self._root = Path(root)
        self._device = device
        self._namespace = namespace
        self._quota = int(quota_bytes)
        self._max_duration_s = int(max_duration_s)
        self._popen = popen
        self._clock = clock
        self._now = now
        self._proc = None
        self._folder: Path | None = None
        self._started = 0.0
        self._stopping_since: float | None = None
        self._stop_reason = ""
        self._last_stop_reason = ""

    def _active(self) -> bool:
        return self._proc is not None

    def start(self) -> tuple[bool, str]:
        if self._active():
            return False, "RECORDING_BUSY"
        self._root.mkdir(parents=True, exist_ok=True)
        self._evict()
        if _total_bytes(self._root) >= self._quota:
            return False, "RECORDING_QUOTA_FULL"
        folder = new_session(self._root, device=self._device, camera_profile_revision="",
                             model_revision="", task_id=None, reason="pilot", now=self._now(),
                             topics=PILOT_TOPICS, extra={"mode": "pilot"})
        try:
            proc = self._popen(pilot_bag_command(folder, self._namespace),
                               stdin=subprocess.DEVNULL, start_new_session=True)
        except (OSError, ValueError):
            finish_session(folder, self._now())
            return False, "RECORDER_UNAVAILABLE"
        self._proc, self._folder = proc, folder
        self._started, self._stopping_since, self._stop_reason = self._clock(), None, ""
        return True, folder.name

    def stop(self, reason: str) -> tuple[bool, str]:
        if not self._active():
            return False, "RECORDING_NOT_ACTIVE"
        if self._stopping_since is None:
            self._proc.send_signal(signal.SIGINT)
            self._stopping_since = self._clock()
            self._stop_reason = reason
        return True, self._folder.name

    def tick(self) -> str | None:
        if not self._active():
            return None
        if self._proc.poll() is not None:
            return self._finish(self._stop_reason if self._stopping_since is not None
                                else "recorder_exit")
        if self._stopping_since is None:
            if self._clock() - self._started >= self._max_duration_s:
                self.stop("max_duration")
            elif _total_bytes(self._root) >= self._quota:
                self.stop("quota")
        elif self._clock() - self._stopping_since >= STOP_TIMEOUT_S:
            self._proc.kill()
        return None

    def _finish(self, reason: str) -> str:
        folder, duration = self._folder, self._clock() - self._started
        self._proc, self._folder, self._stopping_since = None, None, None
        finish_session(folder, self._now())
        write_manifest(folder, stop_reason=reason, duration_s=max(0.0, duration))
        self._last_stop_reason = reason
        return reason

    def status(self) -> dict:
        active = self._active()
        return {
            "schema": STATUS_SCHEMA,
            "state": ("stopping" if self._stopping_since is not None else "recording")
            if active else "idle",
            "id": self._folder.name if active else None,
            "elapsed_s": max(0.0, self._clock() - self._started) if active else 0.0,
            "bytes": _total_bytes(self._folder) if active else 0,
            "max_duration_s": self._max_duration_s,
            "quota_free_bytes": max(0, self._quota - _total_bytes(self._root)),
            "last_stop_reason": self._last_stop_reason,
        }

    def _evict(self) -> None:
        total = _total_bytes(self._root)
        for _, folder, meta in _sessions(self._root):
            if total < self._quota:
                break
            if meta.get("mode") == "pilot" and meta.get("ended_at") is not None \
                    and (folder / FETCHED_NAME).is_file():
                total -= _total_bytes(folder)
                shutil.rmtree(folder)

    def recover(self) -> list[str]:
        """Finish pilot sessions a crash left open (their rosbag2 process is gone)."""
        recovered = []
        for _, folder, meta in _sessions(self._root):
            if meta.get("mode") != "pilot" or meta.get("ended_at") is not None \
                    or folder == self._folder:
                continue
            finish_session(folder, self._now())
            write_manifest(folder, stop_reason="recovered", duration_s=0.0)
            recovered.append(folder.name)
        return recovered

    def mark_fetched(self, recording_id: str) -> bool:
        if not recording_id_ok(recording_id):
            return False
        folder = self._root / recording_id
        if folder == self._folder or not (folder / MANIFEST_NAME).is_file() \
                or not (folder / SESSION_NAME).is_file():
            return False
        tmp = folder / (FETCHED_NAME + ".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump({"fetched_at": _iso(self._now())}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, folder / FETCHED_NAME)
        return True

    def shutdown(self) -> None:
        """Stop and finish the running session; called once when the node is destroyed."""
        if not self._active():
            return
        self.stop("shutdown")
        for _ in range(int(STOP_TIMEOUT_S / _SHUTDOWN_POLL_S)):
            if self._proc.poll() is not None:
                break
            time.sleep(_SHUTDOWN_POLL_S)
        else:
            self._proc.kill()
            wait = getattr(self._proc, "wait", None)
            if wait is not None:
                try:
                    wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    pass
        self._finish(self._stop_reason or "shutdown")
