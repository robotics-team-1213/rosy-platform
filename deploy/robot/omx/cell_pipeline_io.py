"""Native cell FIFO/camera transport and stage receipts; never opens the actuator bus."""
from __future__ import annotations

import errno
import http.client
import hashlib
import json
import math
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from cell_pipeline_liveness import drain_status, runner_liveness

_DEFAULT_URLOPEN = urllib.request.urlopen


def finite_stamp(val) -> float | None:
    """Return `val` as a finite float, safely rejecting bools, NaN/inf, and huge overflowing ints."""
    if not isinstance(val, (int, float)) or isinstance(val, bool):
        return None
    try:
        num = float(val)
    except (TypeError, ValueError, OverflowError):
        return None
    return num if math.isfinite(num) else None


def case(work: Path, row: dict) -> None:
    """One line per check that did not simply pass, and the outcome that followed: new failure cases to fix
    and turn into tests, and the decision model's training data (it learns before any VLA, D-872)."""
    work.mkdir(parents=True, exist_ok=True)
    with (work / "cases.jsonl").open("a") as f:
        f.write(json.dumps({"t": round(time.time(), 3), **row}, default=str) + "\n")


def limit_error(config: dict, library: dict) -> str | None:
    """The first way a planned library leaves this arm's joint window, else None. ``joint_min`` looks at every chunk;
    ``joint_max`` only at ``played_chunks`` when the caller lists them (the remap plays above_pick and the fold home)."""
    names, chunks = library["names"], library["chunks"]
    # arm_b's wrist roll holds at 9.89 in free air (2026-11-06): refuse the plan here, so every caller tries its next yaw
    for name, low in (config.get("joint_min") or {}).items():
        lowest = min(row[names.index(name)] for chunk in chunks.values() for row in chunk)
        if lowest < low:
            return f"{name} target {lowest:.1f} is under this arm's joint_min {low}"
    # 2026-11-14: arm_b's printed wrist holder touched link3/4 at wrist_flex 59.3, so its profile caps the wrist lower
    played = config.get("played_chunks")
    for name, high in (config.get("joint_max") or {}).items():
        highest = max(row[names.index(name)] for key, chunk in chunks.items() if played is None or key in played
                      for row in chunk)
        if highest > high:
            return f"{name} target {highest:.1f} is over this arm's joint_max {high}"
    return None


def plan_library(config: dict, pick: dict, place: dict, *, check: bool = True) -> dict:
    """The chunk library for a pick and place; refused (SystemExit) when it leaves the arm's joint window."""
    from grasp_planner import Planner
    import omx_tcp

    tcp_x_m = omx_tcp.config_tcp(config)
    library = Planner(dict(config["plan"], pick=pick, place=place, keep_out=config.get("keep_out"),
                           **({"tcp_x_m": tcp_x_m} if tcp_x_m is not None else {}))).library()
    error = limit_error(config, library) if check else None
    if error:
        raise SystemExit(error)
    return library


def write_library(config: dict, pick: dict, place: dict, path: Path) -> Path:
    library = plan_library(config, pick, place)
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


def park_succeeded(status) -> bool:
    return (isinstance(status, dict) and status.get("ok") is True and status.get("settled") is True
            and not any(status.get(key) for key in ("fault", "contact", "human_hold_latched")))


def fold_from_hold(cell, status: dict) -> dict:
    """Send the exact measured start and the session/library used to check its corridor."""
    session = (status.get("operating_context") or {}).get("session_id")
    revision = status.get("library_sha256")
    if not session or not revision:
        return {"ok": False, "error": "held runner has no session or library binding"}
    command = "fold-from-hold " + " ".join(map(str, status["state"][:6]))
    return cell.checked(command, {"session_id": session, "library_sha256": revision})


FIFO_WRITE_LOCK = threading.Lock()


class FifoCell:
    """The running chunk_runner (command FIFO + status file) and the read-only camera viewer."""

    def __init__(self, io: Path, cameras: dict, timeout_s: float = 300, *, operating_profile=None, stall_timeout_s: float = 3.0):
        self.io, self.cameras, self.timeout_s = io, cameras, timeout_s
        self.operating_profile, self.stall_timeout_s = operating_profile, stall_timeout_s
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
        if (self.operating_profile is not None and command not in ("state", "human-hold")
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
        is_hold = command == "human-hold"
        hold_req = uuid.uuid4().hex[:12] if is_hold else None
        wire_cmd = f"human-hold {hold_req}" if hold_req else command
        expected = command.split(" ", 3)[-1] if command.startswith("checked ") else command
        verb = expected.split(" ", 1)[0]
        recovery = verb in ("fold-from-hold", "park-slow", "recover-unlatch")
        status_path = self.io / "chunk-status.jsonl"
        with FIFO_WRITE_LOCK:  # the hardware owner's cancel fold writes `park` from another thread (D-977 4)
            if is_hold:
                try:
                    start: int | None = status_path.stat().st_size if status_path.exists() else 0
                except OSError:
                    start = None
                pre_live = self.policy_state()
                pre_t = finite_stamp(pre_live.get("t")) if isinstance(pre_live, dict) else None
            else:
                start = status_path.stat().st_size if status_path.exists() else 0
                pre_t = None
            try:  # non-blocking: never hand a command to a later runner
                fd = os.open(self.io / "chunk-cmd", os.O_WRONLY | getattr(os, "O_NONBLOCK", 0))
            except OSError as exc:
                if exc.errno in (errno.ENOENT, errno.ENXIO):
                    return {"ok": False, "error": "chunk_runner is not running", "fault": "no runner"}
                return {"ok": False, "error": f"chunk-cmd open failed: {exc.strerror or type(exc).__name__}", "fault": "fifo io error"}
            try:
                os.write(fd, (wire_cmd + "\n").encode())
                sent_at = time.time()
            finally:
                os.close(fd)
        if timeout is None:
            cap = 1.0 if is_hold else (3.0 if expected == "state" or expected.startswith("load ") else self.timeout_s)
            eff_timeout = min(self.timeout_s, cap)
        else:
            eff_timeout = timeout
        deadline = time.monotonic() + eff_timeout
        last_live_t = last_live_mono = None
        next_liveness = 0.0
        while time.monotonic() < deadline:
            if start is not None:
                row, start = drain_status(self, status_path, start, command, expected, verb, recovery, is_hold, hold_req, sent_at, finite_stamp)
                if row is not None:
                    return row
            if is_hold:
                live = self.policy_state()
                lt = finite_stamp(live.get("t")) if isinstance(live, dict) else None
                if (isinstance(live, dict) and live.get("human_hold_latched") is True
                        and live.get("torque_hold_commanded") is True
                        and live.get("hold_req") == hold_req
                        and lt is not None
                        and sent_at + 0.001 <= lt <= time.time() + 1.0
                        and (pre_t is None or lt > pre_t)):
                    return {"command": "human-hold", "ok": True, "human_hold_latched": True,
                            "torque_hold_commanded": True, "hold_req": hold_req, "t": lt, "state": live.get("state")}
            elif (now_mono := time.monotonic()) >= next_liveness:
                next_liveness = now_mono + 0.05
                issue, last_live_t, last_live_mono = runner_liveness(
                    self.policy_state(), last_t=last_live_t, last_mono=last_live_mono,
                    stall_timeout_s=self.stall_timeout_s, now_mono=now_mono, finite_stamp=finite_stamp, kill=os.kill)
                if issue is not None:
                    if issue[0] == "runner_dead" and start is not None:
                        row, start = drain_status(self, status_path, start, command, expected, verb, recovery, False, None, sent_at, finite_stamp)
                        if row is not None:
                            return row
                    return {"ok": False, "fault": issue[0], "error": issue[1]}
            time.sleep(0.005)
        return {"ok": False, **({"command": "human-hold"} if is_hold else {}), "error": f"no status within {eff_timeout} s"}

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
                except (OSError, http.client.HTTPException, AttributeError):  # 3.12 http.client: a closed keep-alive read
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

    def policy_state(self):
        """Read the latest encoder sample without sending a FIFO command during playback."""
        try:
            return json.loads((self.io / "live.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, RecursionError):
            return None

    def frame_receipt(self, camera: str, *, previous: dict | None = None,
                      max_age_s: float = 2.0, timeout_s: float = 10.0) -> dict:
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
            with urllib.request.urlopen(request, timeout=timeout_s) as reply:
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
        return {"image": image, "jpeg_bytes": raw, "jpeg_sha256": hashlib.sha256(raw).hexdigest(),
                "source_seq": sequence, "source_stamp": source_stamp,
                "camera": camera, "captured_at": captured_at, "etag": etag}


def write_receipt(directory: Path, stage: str, payload: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{stage}.json"
    path.write_text(json.dumps({"stage": stage, **payload}, indent=1, default=str))
    return path
