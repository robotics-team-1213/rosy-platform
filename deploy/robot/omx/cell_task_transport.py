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
    if lease is None or lease.get("owner") != expected_owner or lease.get("hold"):
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
