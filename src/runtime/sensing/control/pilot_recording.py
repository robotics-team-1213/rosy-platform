"""D-411 A: the Pilot recording session. ROS-free; pilot_recorder_node is a thin wrapper.

One session at a time, at most MAX_DURATION_S, a dedicated quota with a reserve, a free-disk
floor. A session is `starting` until rosbag2 opened its first file (writer_ready), then
`recording`; elapsed time and duration count from that moment, and a writer that opens no
file within START_TIMEOUT_S is stopped. Nothing here blocks a ROS callback for long: stop() sends SIGINT, tick() ends the
session once rosbag2 has exited and hashes the manifest on one worker thread. shutdown()
only ends the session (it must fit the launch SIGTERM window); recover() at the next start
stops a writer that outlived its node and writes every missing manifest. Only fetched
(fetched.json) finished sessions are ever evicted.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import re
import shutil
import signal
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from core_common.protocol.recording import (
    FETCHED_NAME, MANIFEST_NAME, MANIFEST_SCHEMA, MAX_DURATION_S, SESSION_NAME, STATUS_SCHEMA,
    TELEOP_INTENT_TOPIC, recording_id_ok)
from control.recording import (
    COMPRESSED_CAMERA_TOPIC, ODOM_TOPIC, SCAN_TOPIC, _iso, _ns_topics, _read_meta, _sessions,
    _total_bytes, _write_meta, new_session)

PILOT_TOPICS = (COMPRESSED_CAMERA_TOPIC, "cmd_vel", ODOM_TOPIC, SCAN_TOPIC, "line/observation",
                TELEOP_INTENT_TOPIC)
DEFAULT_QUOTA_BYTES = 4 * 1024 ** 3
# Headroom kept free inside the quota so a started session can run its full length.
DEFAULT_RESERVE_BYTES = 1024 ** 3
DEFAULT_MIN_FREE_BYTES = 512 * 1024 ** 2
STOP_TIMEOUT_S = 6.0          # SIGINT -> SIGKILL, inside the camera unit's TimeoutStopSec=10
SHUTDOWN_WAIT_S = 3.5         # node shutdown, inside launch's 5 s SIGINT -> SIGTERM window
# `starting` -> stop("writer_start_timeout") when rosbag2 opened no file by then. The Gazebo
# run took 4.0 s from popen to the file (the ros2 CLI's Python start-up is most of it).
START_TIMEOUT_S = 15.0
START_TIMEOUT_REASON = "writer_start_timeout"
WRITER_PID_NAME = ".writer.pid"   # dotfile: never in a manifest
SIGKILL = getattr(signal, "SIGKILL", 9)
_POLL_S = 0.1
_HASH_CHUNK = 1 << 20
_DEVICE_MAX = 48              # leaves room for new_session's "_<n>" suffix inside the id


def pilot_bag_command(folder, namespace: str = "") -> list[str]:
    # pdeathsig: rosbag2 gets SIGINT (and closes its file) if the node dies hard, so a
    # SIGKILLed or crashed node never leaves a writer filling the disk.
    return ["setpriv", "--pdeathsig", "INT", "--",
            "ros2", "bag", "record", "--storage", "mcap",
            "--storage-preset-profile", "zstd_fast", "--max-bag-duration", "30",
            "-o", str(Path(folder) / "bag"), "--topics", *_ns_topics(PILOT_TOPICS, namespace)]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(_HASH_CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def _duration(meta: dict) -> float:
    try:
        started = datetime.fromisoformat(meta["started_at"])
        ended = datetime.fromisoformat(meta["ended_at"])
    except (KeyError, TypeError, ValueError):
        return 0.0
    return max(0.0, (ended - started).total_seconds())


def write_manifest(folder: Path, *, duration_s: float | None = None) -> Path:
    """Hash every file of an ended session. The stop facts come from session.json."""
    meta = _read_meta(folder)
    if not isinstance(meta.get("ended_at"), str):
        raise ValueError(f"session {folder.name} has not ended; recover() finishes it")
    files = []
    for path in sorted(p for p in folder.rglob("*") if p.is_file() and not p.is_symlink()):
        rel = path.relative_to(folder).as_posix()
        if rel in (MANIFEST_NAME, FETCHED_NAME) or rel.endswith(".tmp") or rel.startswith("."):
            continue
        files.append({"path": rel, "bytes": path.stat().st_size, "sha256": _sha256(path)})
    body = {"schema": MANIFEST_SCHEMA, "id": folder.name, "started_at": meta["started_at"],
            "ended_at": meta["ended_at"],
            "duration_s": round(_duration(meta) if duration_s is None else duration_s, 3),
            "topics": list(meta.get("topics", ())),
            "stop_reason": meta.get("stop_reason") or "recovered",
            "bag_returncode": meta.get("bag_returncode"),
            "writer_killed": bool(meta.get("writer_killed", False)), "files": files}
    tmp = folder / (MANIFEST_NAME + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(body, handle, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, folder / MANIFEST_NAME)
    return folder / MANIFEST_NAME


def _writer_alive(pid: int, folder: Path, proc_root: Path = Path("/proc")) -> bool:
    """A live rosbag2 writing into `folder` (pid reuse safe: one argv element is exactly
    the session's bag path, so `<folder>_2/bag` or a longer path never matches)."""
    try:
        cmdline = (Path(proc_root) / str(pid) / "cmdline").read_bytes()
    except OSError:
        return False
    return (b"\0" + cmdline).find(b"\0" + str(Path(folder) / "bag").encode() + b"\0") >= 0


def _disk_free(root: Path) -> int:
    return shutil.disk_usage(root).free


def _safe_device(device: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", (device or "").strip())[:_DEVICE_MAX].rstrip("_")
    return safe or "rosy"


def recording_device(param: str, namespace: str, hostname: str) -> str:
    """session.device: the robot, not the host. An explicit `device` parameter wins, then
    the node namespace (ROSY_NAMESPACE = rosy_NN on a provisioned robot, CORE's robot id);
    the hostname only when neither is set (an un-namespaced bench)."""
    for candidate in (param, (namespace or "").strip("/"), hostname):
        if (candidate or "").strip():
            return _safe_device(candidate)
    return _safe_device("")


def writer_ready(folder: Path) -> bool:
    """rosbag2 has opened its first storage file: `<folder>/bag/*.mcap` exists.

    Not its size: MCAP buffers whole chunks (zstd_fast) and the writer caches messages, so
    the file stays 0 bytes for many seconds (a 20 s Gazebo session never grew on disk before
    close). rosbag2 opens the file right before it subscribes ("Starting recording to" then
    "Subscribed to topic" within ~0.4 s; first message 0.2 s after the open)."""
    try:
        return any(path.is_file() for path in (Path(folder) / "bag").glob("*.mcap"))
    except OSError:
        return False


class PilotRecorder:
    def __init__(self, root, *, device: str, namespace: str = "",
                 quota_bytes: int = DEFAULT_QUOTA_BYTES,
                 reserve_bytes: int = DEFAULT_RESERVE_BYTES,
                 min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
                 max_duration_s: int = MAX_DURATION_S,
                 popen=subprocess.Popen, clock=time.monotonic,
                 now=lambda: datetime.now(timezone.utc), executor=None,
                 disk_free=_disk_free, sleep=time.sleep,
                 killpg=getattr(os, "killpg", None), signal_pid=os.kill,
                 writer_alive=_writer_alive, log=lambda message: None) -> None:
        if not 0 <= int(reserve_bytes) < int(quota_bytes):
            raise ValueError("reserve_bytes must be >= 0 and below quota_bytes")
        self._root = Path(root)
        self._device = _safe_device(device)
        self._namespace = namespace
        self._quota = int(quota_bytes)
        self._reserve = int(reserve_bytes)
        self._min_free = int(min_free_bytes)
        self._max_duration_s = int(max_duration_s)
        self._popen, self._clock, self._now = popen, clock, now
        self._executor = executor or ThreadPoolExecutor(max_workers=1,
                                                        thread_name_prefix="pilot_manifest")
        self._disk_free, self._sleep = disk_free, sleep
        self._killpg, self._signal_pid, self._writer_alive = killpg, signal_pid, writer_alive
        self._log = log
        self._proc = None
        self._folder: Path | None = None
        self._finalizing = None       # (future, reason) while the worker hashes
        self._started = 0.0           # popen
        self._recording_since: float | None = None   # writer_ready(); None while `starting`
        self._stopping_since: float | None = None
        self._stop_reason = ""
        self._killed = False
        self._last_stop_reason = ""
        self._boot_id = uuid.uuid4().hex
        self._seqs = itertools.count(1)   # next() is atomic: any thread may build a status

    # ------------------------------------------------------------------ state
    def _busy(self) -> bool:
        return self._proc is not None or self._finalizing is not None

    def start(self) -> tuple[bool, str]:
        if self._busy():
            return False, "RECORDING_BUSY"
        try:
            if not self._root.is_dir() or not os.access(self._root, os.W_OK):
                self._log(f"pilot recording root {self._root} is missing or not writable")
                return False, "RECORDER_UNAVAILABLE"
            self._evict()
            if self._quota - _total_bytes(self._root) <= self._reserve:
                return False, "RECORDING_QUOTA_FULL"
            if self._disk_free(self._root) <= self._min_free:
                return False, "RECORDING_DISK_FULL"
            folder = new_session(self._root, device=self._device, camera_profile_revision="",
                                 model_revision="", task_id=None, reason="pilot",
                                 now=self._now(), topics=PILOT_TOPICS, extra={"mode": "pilot"})
        except OSError as exc:
            self._log(f"pilot recording cannot start: {exc}")
            return False, "RECORDER_UNAVAILABLE"
        if not recording_id_ok(folder.name):
            self._log(f"pilot recording id {folder.name!r} is not a valid id")
            shutil.rmtree(folder, ignore_errors=True)
            return False, "RECORDER_UNAVAILABLE"
        try:
            proc = self._popen(pilot_bag_command(folder, self._namespace),
                               stdin=subprocess.DEVNULL, start_new_session=True)
        except (OSError, ValueError) as exc:
            self._log(f"pilot recording: rosbag2 did not start: {exc}")
            shutil.rmtree(folder, ignore_errors=True)   # only session.json: nothing recorded
            return False, "RECORDER_UNAVAILABLE"
        try:
            (folder / WRITER_PID_NAME).write_text(f"{proc.pid}\n", encoding="utf-8")
        except (OSError, TypeError) as exc:
            self._log(f"pilot recording: writer pid not kept: {exc}")
        self._proc, self._folder, self._killed = proc, folder, False
        self._started, self._stopping_since, self._stop_reason = self._clock(), None, ""
        self._recording_since = None
        return True, folder.name

    def poll_start(self) -> bool:
        """`starting` -> `recording` once rosbag2 opened its first file. True on that change.
        session.json's started_at becomes that moment (the first request stays requested_at),
        so the listing, the manifest and recover() all count from when data began."""
        if self._proc is None or self._stopping_since is not None \
                or self._recording_since is not None or not writer_ready(self._folder):
            return False
        self._recording_since = self._clock()
        try:
            meta = _read_meta(self._folder)
            meta.update(requested_at=meta.get("started_at"), started_at=_iso(self._now()))
            _write_meta(self._folder, meta)
        except (OSError, ValueError) as exc:
            self._log(f"pilot recording: started_at of {self._folder.name} not updated: {exc}")
        return True

    def stop(self, reason: str) -> tuple[bool, str]:
        if self._proc is None:
            if self._finalizing is not None:
                return True, self._folder.name
            return False, "RECORDING_NOT_ACTIVE"
        if self._stopping_since is None:
            self._proc.send_signal(signal.SIGINT)
            self._stopping_since = self._clock()
            self._stop_reason = reason
        return True, self._folder.name

    def tick(self) -> str | None:
        """1 Hz. Returns the stop reason once a session's manifest is written."""
        if self._finalizing is not None:
            return self._collect()
        if self._proc is None:
            return None
        code = self._proc.poll()
        if code is not None:
            reason = self._stop_reason if self._stopping_since is not None else "recorder_exit"
            since = self._recording_since
            duration = 0.0 if since is None else max(0.0, self._clock() - since)
            folder = self._folder
            self._proc = None
            self._end(folder, reason, code, self._killed)
            self._finalizing = (self._executor.submit(write_manifest, folder, duration_s=duration),
                                reason)
            return self._collect()
        if self._stopping_since is None:
            self.poll_start()
            if self._recording_since is None and self._clock() - self._started >= START_TIMEOUT_S:
                self._log(f"pilot recording {self._folder.name}: rosbag2 opened no file in "
                          f"{START_TIMEOUT_S:.0f} s; stopping ({START_TIMEOUT_REASON})")
                self.stop(START_TIMEOUT_REASON)
                return None
            self._check_limits()
        elif self._clock() - self._stopping_since >= STOP_TIMEOUT_S:
            self._kill(self._proc)
        return None

    def _check_limits(self) -> None:
        since = self._recording_since
        if since is not None and self._clock() - since >= self._max_duration_s:
            self.stop("max_duration")
            return
        try:
            if _total_bytes(self._root) >= self._quota:
                self._evict()
                if _total_bytes(self._root) >= self._quota:
                    self.stop("quota")
                    return
            if self._disk_free(self._root) < self._min_free:
                self.stop("disk_full")
        except OSError as exc:
            self._log(f"pilot recording: limit check failed: {exc}")

    def _collect(self) -> str | None:
        future, reason = self._finalizing
        if not future.done():
            return None
        self._finalizing, self._folder, self._stopping_since = None, None, None
        self._recording_since = None
        error = future.exception()
        if error is not None:
            # The session stays without a manifest; recover() writes it at the next start.
            self._log(f"pilot recording manifest failed: {error}")
        self._last_stop_reason = reason
        return reason

    def _kill(self, proc) -> None:
        self._killed = True
        pid = getattr(proc, "pid", None)
        if self._killpg is not None and isinstance(pid, int):
            try:
                self._killpg(pid, SIGKILL)   # the whole group: setpriv execs into ros2
                return
            except OSError:
                pass
        proc.kill()

    def _end(self, folder: Path, reason: str, returncode, killed: bool) -> None:
        """Mark session.json ended with the stop facts; session.json is final after this."""
        try:
            meta = _read_meta(folder)
            meta.update(ended_at=_iso(self._now()), stop_reason=reason,
                        bag_returncode=returncode, writer_killed=bool(killed))
            _write_meta(folder, meta)
            (folder / WRITER_PID_NAME).unlink(missing_ok=True)
        except (OSError, ValueError) as exc:
            self._log(f"pilot recording: session {folder.name} not ended cleanly: {exc}")

    def status(self) -> dict:
        busy = self._busy()
        stopping = self._finalizing is not None or self._stopping_since is not None
        since = self._recording_since
        try:
            used = _total_bytes(self._root)
            folder_bytes = _total_bytes(self._folder) if busy else 0
        except OSError:
            used, folder_bytes = self._quota, 0
        if not busy:
            state = "idle"
        elif stopping:
            state = "stopping"
        else:
            state = "starting" if since is None else "recording"
        return {
            "schema": STATUS_SCHEMA,
            "state": state,
            "id": self._folder.name if busy else None,
            "elapsed_s": max(0.0, self._clock() - since) if busy and since is not None else 0.0,
            "bytes": folder_bytes,
            "max_duration_s": self._max_duration_s,
            "quota_free_bytes": max(0, self._quota - used),
            "last_stop_reason": self._last_stop_reason,
            "boot_id": self._boot_id,
            "seq": next(self._seqs),
        }

    # ------------------------------------------------------------ disk upkeep
    def _evict(self) -> None:
        target = self._quota - self._reserve
        total = _total_bytes(self._root)
        for _, folder, meta in _sessions(self._root):
            if total < target:
                break
            if meta.get("mode") == "pilot" and meta.get("ended_at") is not None \
                    and folder != self._folder and (folder / FETCHED_NAME).is_file():
                total -= _total_bytes(folder)
                shutil.rmtree(folder)

    def recover(self) -> list[str]:
        """Finish every pilot session without a manifest (crash, kill, interrupted hashing)."""
        recovered = []
        try:
            sessions = _sessions(self._root)
        except OSError as exc:
            self._log(f"pilot recording recover skipped: {exc}")
            return recovered
        for _, folder, meta in sessions:
            if meta.get("mode") != "pilot" or folder == self._folder \
                    or (folder / MANIFEST_NAME).is_file():
                continue
            try:
                killed = self._stop_orphan_writer(folder)
                if meta.get("ended_at") is None:
                    self._end(folder, "recovered", None, killed)
                elif killed:
                    self._end(folder, meta.get("stop_reason") or "recovered",
                              meta.get("bag_returncode"), True)
                write_manifest(folder)
                (folder / WRITER_PID_NAME).unlink(missing_ok=True)
                recovered.append(folder.name)
            except (OSError, ValueError, KeyError) as exc:
                self._log(f"pilot recording {folder.name} not recovered: {exc}")
        return recovered

    def _stop_orphan_writer(self, folder: Path) -> bool:
        """SIGINT a writer that outlived its node, SIGKILL after STOP_TIMEOUT_S. True if killed."""
        try:
            pid = int((folder / WRITER_PID_NAME).read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return False
        if not self._writer_alive(pid, folder):
            return False
        self._log(f"pilot recording {folder.name}: stopping orphan writer {pid}")
        self._signal_pid(pid, signal.SIGINT)
        for _ in range(round(STOP_TIMEOUT_S / _POLL_S)):
            if not self._writer_alive(pid, folder):
                return False
            self._sleep(_POLL_S)
        self._signal_pid(pid, SIGKILL)
        return True

    def mark_fetched(self, recording_id: str) -> bool:
        if not recording_id_ok(recording_id):
            return False
        folder = self._root / recording_id
        if folder == self._folder or not (folder / MANIFEST_NAME).is_file() \
                or not (folder / SESSION_NAME).is_file():
            return False
        try:
            tmp = folder / (FETCHED_NAME + ".tmp")
            with tmp.open("w", encoding="utf-8") as handle:
                json.dump({"fetched_at": _iso(self._now())}, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, folder / FETCHED_NAME)
        except OSError as exc:
            self._log(f"pilot recording {recording_id}: fetched mark not written: {exc}")
            return False
        return True

    def shutdown(self) -> None:
        """Node teardown: end the session within SHUTDOWN_WAIT_S; no hashing (recover() does it)."""
        if self._proc is not None:
            proc, folder = self._proc, self._folder
            self.stop("shutdown")
            for _ in range(round(SHUTDOWN_WAIT_S / _POLL_S)):
                if proc.poll() is not None:
                    break
                self._sleep(_POLL_S)
            else:
                self._kill(proc)
                try:
                    proc.wait(timeout=0.3)
                except subprocess.TimeoutExpired:
                    pass
            self._end(folder, self._stop_reason or "shutdown", proc.poll(), self._killed)
            self._proc, self._folder, self._stopping_since = None, None, None
            self._recording_since = None
        self._finalizing = None
        # A hash still running is abandoned here; recover() rewrites that manifest.
        self._executor.shutdown(wait=False, cancel_futures=True)
