"""Persistent Fleet HTTPS requester and `cell_ab` session-lock helpers for `cell_task_worker.py`."""
from __future__ import annotations

try:
    import fcntl
except ImportError:  # Windows unit tests
    fcntl = None  # type: ignore[assignment]
import http.client
import io
import json
import os
from pathlib import Path
import ssl
import threading
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit

import cell_arm_lease
from cell_camera_telemetry_sync import DEFAULT_PREP_DIR
from joint_tune_lock import lock_root

_REUSE_DROP = (http.client.RemoteDisconnected, BrokenPipeError, ConnectionResetError, ConnectionAbortedError)
WORKER_LEASE_PREFIX = "cell-task-worker:"
LIVE_MAX_AGE_S = 15.0
SAFETY_OK = "OK"
SAFETY_EXPLICIT_STOP = "EXPLICIT_STOP"
SAFETY_FEED_UNAVAILABLE = "FEED_UNAVAILABLE"


def make_keepalive_https_request(base_url: str, token: str, ctx: ssl.SSLContext, *, timeout_s: float = 20.0):
    """Return a thread-safe persistent HTTPS JSON requester; stalls never block parallel safety polls."""
    base = base_url.rstrip("/")
    parsed = urlsplit(base)
    host, port, prefix = parsed.hostname or "", parsed.port or 443, parsed.path.rstrip("/")
    pool_lock = threading.Lock()
    idle: list[http.client.HTTPSConnection | None] = [None]

    def _close_quiet(conn) -> None:
        try:
            conn.close()
        except Exception:
            pass

    def _req(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        req_path = f"{prefix}{path}" if path.startswith("/") else f"{prefix}/{path}"
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Authorization": f"Bearer {token}", "Connection": "keep-alive"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        idempotent = method in ("GET", "HEAD")
        for attempt in (0, 1):
            with pool_lock:
                conn = idle[0]
                idle[0] = None
            reused = conn is not None
            if conn is None:
                conn = http.client.HTTPSConnection(host, port, timeout=timeout_s, context=ctx)
            try:
                conn.request(method, req_path, body=payload, headers=headers)
                resp = conn.getresponse()
            except ssl.SSLError:
                _close_quiet(conn)
                raise
            except _REUSE_DROP:
                _close_quiet(conn)
                if attempt == 0 and (reused or idempotent):
                    continue
                raise
            except (http.client.HTTPException, OSError) as exc:
                _close_quiet(conn)
                if attempt == 0 and idempotent and not isinstance(exc, TimeoutError):
                    continue
                raise
            try:
                raw = resp.read()
            except (ssl.SSLError, http.client.HTTPException, OSError):
                _close_quiet(conn)
                raise
            conn_hdr = (getattr(resp, "headers", None) or {}).get("Connection", "")
            reusable = resp.status < 500 and not getattr(resp, "will_close", False) and str(conn_hdr).lower() != "close"
            if reusable:
                with pool_lock:
                    if idle[0] is None:
                        idle[0] = conn
                        conn = None
            if conn is not None:
                _close_quiet(conn)
            if resp.status >= 400:
                raise HTTPError(f"{base}{path}", resp.status, getattr(resp, "reason", "") or "", getattr(resp, "headers", None), io.BytesIO(raw))
            return json.loads(raw.decode("utf-8"))
        raise RuntimeError("unreachable")

    return _req


def _read_json_dict(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _can_reuse_worker_arm_session(
    arm_id: str,
    *,
    prep_dir: Path,
    lease_dir: Path | None,
    expected_owner: str,
) -> bool:
    """True only when this worker owns the warm idle arm session and live state is clean."""
    lease = cell_arm_lease._read(arm_id, cell_arm_lease.lease_root(lease_dir))
    if not isinstance(lease, dict) or lease.get("owner") != expected_owner or lease.get("hold"):
        return False
    if not cell_arm_lease.live(lease):
        return False
    live = _read_json_dict(prep_dir / f"chunk-io-{arm_id.split('_')[-1]}" / "live.json")
    if live is None or live.get("chunk") is not None or live.get("human_hold_latched") or live.get("fault") or live.get("interrupt"):
        return False
    ts = live.get("t")
    if isinstance(ts, bool) or not isinstance(ts, (int, float)) or (time.time() - float(ts)) > LIVE_MAX_AGE_S:
        return False
    return True


def peer_ab_session_locked(
    arm_id: str,
    lock_dir: Path | None = None,
    *,
    prep_dir: Path | None = None,
    lease_dir: Path | None = None,
    expected_owner: str | None = None,
) -> bool:
    """True when `session.lock` or an un-reusable `arm_a`/`arm_b` session lock is held."""
    if fcntl is None or arm_id not in ("arm_a", "arm_b"):
        return False
    root = lock_dir or lock_root()
    whole = root / "session.lock"
    if whole.exists():
        with open(whole, "a+") as fh:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    effective_prep = prep_dir or DEFAULT_PREP_DIR
    owner = expected_owner or f"{WORKER_LEASE_PREFIX}{os.getpid()}"
    for check_arm in ("arm_a", "arm_b"):
        lock_path = root / f"session-{check_arm}.lock"
        if not lock_path.exists():
            continue
        with open(lock_path, "a+") as fh:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except BlockingIOError:
                if not _can_reuse_worker_arm_session(
                    check_arm,
                    prep_dir=effective_prep,
                    lease_dir=lease_dir,
                    expected_owner=owner,
                ):
                    return True
    return False


def classify_safety_listing(
    listing: Any,
    *,
    cell_id: str | None = None,
    task_id: str | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Classify Fleet safety poll into OK, EXPLICIT_STOP, or FEED_UNAVAILABLE."""
    if not isinstance(listing, dict) or not isinstance(listing.get("human_safety"), dict):
        return SAFETY_FEED_UNAVAILABLE, None
    safety = listing["human_safety"]
    if safety.get("active_estop") is True:
        return SAFETY_EXPLICIT_STOP, None
    if safety.get("active_estop") is not False or not isinstance(safety.get("human_detected"), dict):
        return SAFETY_FEED_UNAVAILABLE, None
    if cell_id is not None:
        if safety["human_detected"].get("all") or safety["human_detected"].get(cell_id):
            return SAFETY_EXPLICIT_STOP, None
        cells = listing.get("cells")
        if not isinstance(cells, dict) or not isinstance(cells.get(cell_id), dict):
            return SAFETY_FEED_UNAVAILABLE, None
        cell = cells[cell_id]
        if cell.get("phase") != "ARM_IN_BED_ZONE" or cell.get("active_task_id") != task_id:
            return SAFETY_EXPLICIT_STOP, None
    return SAFETY_OK, listing


def select_arms_for_feed_loss(
    prep_dir: Path,
    arm_wrappers: dict[str, tuple[str, str, float]],
    *,
    lease_dir: Path | None = None,
) -> set[str]:
    """Select only worker-leased or unleased active-chunk arms when Fleet safety feed is lost."""
    root = cell_arm_lease.lease_root(lease_dir)
    selected: set[str] = set()
    for arm_id, (suffix, _, _) in arm_wrappers.items():
        lease = cell_arm_lease._read(arm_id, root)
        if lease is None and (root / f"{arm_id}.json").is_file():
            selected.add(arm_id)
            continue
        if isinstance(lease, dict) and cell_arm_lease.live(lease):
            if str(lease.get("owner") or "").startswith(WORKER_LEASE_PREFIX):
                selected.add(arm_id)
            continue
        for io_name in (f"chunk-io-{suffix}", f"chunk-io-{suffix}-r2s"):
            live = _read_json_dict(prep_dir / io_name / "live.json")
            if isinstance(live, dict) and live.get("chunk") is not None:
                selected.add(arm_id)
                break
    return selected


def send_human_hold_to_arms(
    prep_dir: Path,
    arm_wrappers: dict[str, tuple[str, str, float]],
    poll_ack_fn,
    *,
    arms: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Send `human-hold\\n` to selected (or all) active arm chunk FIFOs and await ack."""
    acknowledgements: dict[str, dict[str, Any]] = {}
    pending: list[tuple[str, Path, int]] = []
    for arm_id, (suffix, _, _) in arm_wrappers.items():
        if arms is not None and arm_id not in arms:
            continue
        for io_name in (f"chunk-io-{suffix}", f"chunk-io-{suffix}-r2s"):
            io_dir = prep_dir / io_name
            cmd_fifo = io_dir / "chunk-cmd"
            if cmd_fifo.exists():
                status_file = io_dir / "chunk-status.jsonl"
                try:
                    cursor = len(status_file.read_text(errors="replace").splitlines()) if status_file.exists() else 0
                    fd = os.open(str(cmd_fifo), os.O_WRONLY | os.O_NONBLOCK)
                    try:
                        os.write(fd, b"human-hold\n")
                    finally:
                        os.close(fd)
                    pending.append((io_name, status_file, cursor))
                except (OSError, ValueError):
                    acknowledgements[io_name] = {"ok": False, "error": "human_hold_command_failed"}
    for io_name, status_file, cursor in pending:
        try:
            ack, _ = poll_ack_fn(status_file, cursor, "human-hold", 2.0)
            acknowledgements[io_name] = ack if (
                ack.get("command") == "human-hold"
                and ack.get("ok") is True
                and ack.get("human_hold_latched") is True
                and ack.get("torque_hold_commanded") is True
            ) else {"ok": False, "error": "human_hold_ack_missing"}
        except (OSError, ValueError):
            acknowledgements[io_name] = {"ok": False, "error": "human_hold_ack_missing"}
    return acknowledgements
