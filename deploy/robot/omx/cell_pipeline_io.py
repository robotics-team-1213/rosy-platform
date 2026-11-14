"""Native cell FIFO/camera transport and stage receipts; never opens the actuator bus."""
from __future__ import annotations

import http.client
import hashlib
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

_DEFAULT_URLOPEN = urllib.request.urlopen


def case(work: Path, row: dict) -> None:
    """One line per check that did not simply pass, and the outcome that followed: new failure cases to fix
    and turn into tests, and the decision model's training data (it learns before any VLA, D-872)."""
    work.mkdir(parents=True, exist_ok=True)
    with (work / "cases.jsonl").open("a") as f:
        f.write(json.dumps({"t": round(time.time(), 3), **row}, default=str) + "\n")


def write_library(config: dict, pick: dict, place: dict, path: Path) -> Path:
    from grasp_planner import Planner

    library = Planner(dict(config["plan"], pick=pick, place=place, keep_out=config.get("keep_out"),
                           **({"tcp_x_m": config["tcp_x_m"]} if "tcp_x_m" in config else {}))).library()
    # arm_b's wrist roll holds at 9.89 in free air (2026-11-06): refuse the plan here, so every caller tries its next yaw
    for name, low in (config.get("joint_min") or {}).items():
        column = library["names"].index(name)
        lowest = min(row[column] for chunk in library["chunks"].values() for row in chunk)
        if lowest < low:
            raise SystemExit(f"{name} target {lowest:.1f} is under this arm's joint_min {low}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({k: v for k, v in library.items() if v is not None}))
    return path


def fold(cell, sleep=time.sleep, wait_s: float = 2.0) -> dict:
    """Park; once more after a pause when the first one held on a contact or while the runner sheds an overload-hold."""
    status = cell.act("park")
    if status.get("ok") or (not status.get("contact") and "shedding its load" not in (status.get("error") or "")):
        return status
    sleep(wait_s)
    return cell.act("park")


class FifoCell:
    """The running chunk_runner (command FIFO + status file) and the read-only camera viewer."""

    def __init__(self, io: Path, cameras: dict, timeout_s: float = 300, *, operating_profile=None):
        self.io, self.cameras, self.timeout_s = io, cameras, timeout_s
        self.operating_profile = operating_profile
        self._http_conns: dict[tuple[str, int], http.client.HTTPConnection] = {}
        self._frame_cache: dict[str, tuple[str, np.ndarray]] = {}
        self._file_digest_cache: dict[tuple[str, int, int], str] = {}
        self._cached_state: dict | None = None
        self._cached_state_mono: float = 0.0
        self.state_cache_ttl_s: float = 0.35

    def _cached_library_digest(self, path_str: str) -> str:
        from cell_envelope import digest

        p = Path(path_str)
        st = p.stat()
        key = (str(p), st.st_mtime_ns, st.st_size)
        cached = self._file_digest_cache.get(key)
        if cached is None:
            cached = digest(json.loads(p.read_text()))
            self._file_digest_cache[key] = cached
        return cached

    def checked(self, command: str, assessment: dict, timeout: float | None = None) -> dict:
        return self._send(f"checked {assessment['session_id']} {assessment['library_sha256']} {command}", timeout)

    def act(self, command: str, timeout: float | None = None) -> dict:
        if (self.operating_profile is not None and command != "state"
                and not command.startswith(("stop", "checked "))):
            from cell_envelope import _state_current

            if command.startswith("load "):
                self._cached_state = None
            state = (self._cached_state if self._cached_state is not None
                     and time.monotonic() - self._cached_state_mono <= self.state_cache_ttl_s
                     else self.act("state", timeout=min(timeout or self.timeout_s, 5.0)))
            context = state.get("operating_context") or {}
            if not _state_current(state, time.time()) or context.get("operating_profile") != self.operating_profile:
                self._cached_state = None
                return {"ok": False, "fault": "profile_mismatch", "error": "live follower differs from selected profile"}
            try:
                revision = (self._cached_library_digest(command.split(" ", 1)[1])
                            if command.startswith("load ") else state["library_sha256"])
            except (OSError, ValueError, KeyError):
                self._cached_state = None
                return {"ok": False, "fault": "profile_library_unavailable", "error": "cannot bind this command library"}
            self._cached_state = state
            self._cached_state_mono = time.monotonic()
            result = self.checked(command, {"session_id": context["session_id"], "library_sha256": revision}, timeout)
            if not result.get("ok") or result.get("fault"):
                self._cached_state = None
            elif result.get("operating_context") and result.get("library_sha256"):
                self._cached_state = result
                self._cached_state_mono = time.monotonic()
            elif command.startswith("load "):
                self._cached_state = None
            return result
        return self._send(command, timeout)

    def _send(self, command: str, timeout: float | None = None) -> dict:
        expected = command.split(" ", 3)[-1] if command.startswith("checked ") else command
        status_path = self.io / "chunk-status.jsonl"
        start = status_path.stat().st_size if status_path.exists() else 0
        try:  # non-blocking: never hand a command to a later runner
            fd = os.open(self.io / "chunk-cmd", os.O_WRONLY | getattr(os, "O_NONBLOCK", 0))
        except OSError:
            return {"ok": False, "error": "chunk_runner is not running", "fault": "no runner"}
        os.write(fd, (command + "\n").encode())
        os.close(fd)
        deadline = time.monotonic() + (self.timeout_s if timeout is None else timeout)
        while time.monotonic() < deadline:
            if status_path.exists():
                with status_path.open() as stream:
                    stream.seek(start)
                    while line := stream.readline():
                        if not line.endswith("\n"):
                            break
                        start = stream.tell()
                        row = json.loads(line)
                        if row.get("command") in (expected, "run " + expected) or row.get("fault"):
                            if (row.get("ok") and not row.get("fault")
                                    and row.get("operating_context") and row.get("library_sha256")):
                                self._cached_state = row
                                self._cached_state_mono = time.monotonic()
                            return row
            time.sleep(0.005)
        return {"ok": False, "error": f"no status within {self.timeout_s} s"}

    def frame(self, camera: str):
        import cv2

        spec = self.cameras[camera]
        url = spec["url"] if isinstance(spec, dict) else spec
        parsed = urllib.parse.urlsplit(url)
        if urllib.request.urlopen is _DEFAULT_URLOPEN and parsed.scheme == "http" and parsed.hostname:
            key = (parsed.hostname, parsed.port or 80)
            path = parsed.path or "/"
            if parsed.query:
                path = f"{path}?{parsed.query}"
            cached = self._frame_cache.get(camera)
            headers = {"Connection": "keep-alive"}
            if cached is not None:
                headers["If-None-Match"] = cached[0]
            for attempt in range(2):
                conn = self._http_conns.get(key)
                try:
                    if conn is None:
                        conn = http.client.HTTPConnection(key[0], key[1], timeout=10)
                        self._http_conns[key] = conn
                    conn.request("GET", path, headers=headers)
                    resp = conn.getresponse()
                    raw = resp.read()
                    if resp.status == 304 and cached is not None:
                        return cached[1].copy()
                    if resp.status == 200:
                        decoded = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
                        etag = resp.getheader("ETag")
                        if etag and decoded is not None:
                            self._frame_cache[camera] = (etag, decoded)
                        return decoded.copy() if decoded is not None else decoded
                    break
                except (OSError, http.client.HTTPException):
                    try:
                        if conn is not None:
                            conn.close()
                    except Exception:
                        pass
                    self._http_conns.pop(key, None)
                    if attempt == 1:
                        break
        with urllib.request.urlopen(url, timeout=10) as reply:
            return cv2.imdecode(np.frombuffer(reply.read(), np.uint8), cv2.IMREAD_COLOR)

    def frame_receipt(self, camera: str, *, previous: dict | None = None,
                      max_age_s: float = 2.0) -> dict:
        """Read one source frame; reject stale or non-advancing evidence rather than reusing a cached image."""
        import cv2

        if max_age_s <= 0:
            raise ValueError("max_age_s must be positive")
        if previous is not None and previous.get("camera") != camera:
            raise ValueError("previous frame belongs to another camera")
        spec = self.cameras[camera]
        url = spec["url"] if isinstance(spec, dict) else spec
        headers = {"Cache-Control": "no-cache"}
        if previous is not None and previous.get("etag"):
            headers["If-None-Match"] = previous["etag"]
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=10) as reply:
                if reply.status != 200:
                    raise ValueError(f"camera frame HTTP {reply.status}; no fresh JPEG")
                sequence_text = reply.headers.get("X-Frame-Seq")
                stamp_text = reply.headers.get("X-Source-Stamp")
                etag = reply.headers.get("ETag")
                raw = reply.read()
        except urllib.error.HTTPError as exc:
            raise ValueError(f"camera frame HTTP {exc.code}; no fresh JPEG") from exc
        captured_at = time.time()
        try:
            sequence = int(sequence_text)
            source_stamp = float(stamp_text)
        except (TypeError, ValueError) as exc:
            raise ValueError("camera frame lacks source sequence or stamp") from exc
        if (sequence < 0 or not math.isfinite(source_stamp) or source_stamp <= 0
                or source_stamp > captured_at + 0.5 or captured_at - source_stamp > max_age_s):
            raise ValueError("camera frame source metadata is stale or invalid")
        if previous is not None:
            try:
                advanced = sequence > int(previous["source_seq"]) and source_stamp > float(previous["source_stamp"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("previous frame lacks source metadata") from exc
            if not advanced:
                raise ValueError("camera frame source has not advanced")
        if not raw.startswith(b"\xff\xd8"):
            raise ValueError("camera frame is not a JPEG")
        image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("camera frame is not a decodable JPEG")
        return {"image": image, "jpeg_sha256": hashlib.sha256(raw).hexdigest(),
                "source_seq": sequence, "source_stamp": source_stamp,
                "camera": camera, "captured_at": captured_at, "etag": etag}


def write_receipt(directory: Path, stage: str, payload: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{stage}.json"
    path.write_text(json.dumps({"stage": stage, **payload}, indent=1, default=str))
    return path
