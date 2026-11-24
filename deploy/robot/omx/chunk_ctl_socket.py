"""AF_UNIX command/status socket and non-blocking live.json writer for chunk_runner."""
from __future__ import annotations

import json
import os
import selectors
import socket
import stat
import threading
import time
from pathlib import Path

from cell_pipeline_liveness import cache_state_row, runner_liveness, status_row_outcome

CTL_SOCKET_NAME = "chunk-ctl.sock"


class AsyncLiveWriter:
    """Coalescing single-thread writer that keeps live.json writes off the 30 Hz servo tick."""

    def __init__(self, path: Path, *, suppress_io_error=None):
        self._path = Path(path)
        self._tmp = self._path.with_suffix(".tmp")
        self._suppress = suppress_io_error or (lambda: False)
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._flushed = threading.Event()
        self._flushed.set()
        self._pending: str | None = None
        self._has_pending = False
        self._closed = False
        self._last_error: OSError | None = None
        self._thread: threading.Thread | None = None

    def _ensure_started(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="omx-live-writer", daemon=True)
            self._thread.start()

    def start(self) -> None:
        """Start the writer thread explicitly (before main_thread_signals.unblock_main)."""
        with self._lock:
            if not self._closed:
                self._ensure_started()

    def publish(self, row: dict, *, sync: bool = False) -> None:
        """Queue the newest live.json snapshot; optionally wait until it lands on disk."""
        payload = json.dumps(row, default=str)
        with self._lock:
            err = self._last_error
            if err is not None:
                self._last_error = None
            self._pending = payload
            self._has_pending = True
            self._flushed.clear()
            self._ensure_started()
            self._wake.set()
        if sync:
            self.flush(timeout=0.5)
        if err is not None and not self._suppress():
            raise err

    def _write_payload(self, payload: str) -> None:
        try:
            self._tmp.write_text(payload, encoding="utf-8")
            os.replace(self._tmp, self._path)
        except OSError as exc:
            if not self._suppress():
                with self._lock:
                    self._last_error = exc

    def _run(self) -> None:
        while True:
            self._wake.wait()
            while True:
                with self._lock:
                    if not self._has_pending:
                        self._wake.clear()
                        closed = self._closed
                        self._flushed.set()
                        break
                    payload = self._pending
                    self._has_pending = False
                if payload is not None:
                    self._write_payload(payload)
            if closed:
                return

    def flush(self, timeout: float = 1.0) -> bool:
        """Wait for any queued snapshot to finish replacing live.json."""
        if self._thread is None:
            return True
        ok = self._flushed.wait(timeout)
        with self._lock:
            err = self._last_error
            self._last_error = None
        if err is not None:
            raise err
        return ok

    def close(self, timeout: float = 1.0) -> None:
        """Flush the latest pending snapshot and stop the background writer thread."""
        if self._thread is None:
            return
        with self._lock:
            self._closed = True
            self._wake.set()
        self._thread.join(timeout=timeout)


class RunnerCtlSession:
    """Bundles chunk-ctl.sock, FIFO source, status broadcast, and AsyncLiveWriter for chunk_runner.main."""

    def __init__(self, io_dir: Path, status_path: Path, write_status_fn, fifo_src, protect_fn):
        self.ctl_server = ChunkCtlServer(io_dir / CTL_SOCKET_NAME)
        self.fifo_src = fifo_src
        self.status_path = status_path
        self.write_status_fn = write_status_fn
        self.protect_fn = protect_fn
        self.live_writer = AsyncLiveWriter(io_dir / "live.json", suppress_io_error=protect_fn)
        self.live_writer.start()

    def status(self, row: dict) -> None:
        self.write_status_fn(self.status_path, row, protect=self.protect_fn())
        self.ctl_server.broadcast_status(row)

    def live(self, row: dict) -> None:
        urgent = isinstance(row, dict) and (row.get("interrupt") == "hold" or bool(row.get("human_hold_latched")))
        self.live_writer.publish(row, sync=urgent)

    def lines(self) -> list[str]:
        return self.fifo_src() + self.ctl_server.poll_commands()

    def close(self) -> None:
        self.fifo_src.close()
        self.live_writer.close()
        self.ctl_server.close()


class ChunkCtlServer:
    """Single-threaded non-blocking AF_UNIX server polled inside chunk_runner's main loop."""

    def __init__(self, sock_path: Path):
        self.sock_path = Path(sock_path)
        self._sock: socket.socket | None = None
        self._clients: list[socket.socket] = []
        self._bufs: dict[int, bytearray] = {}
        if not hasattr(socket, "AF_UNIX"):
            return
        try:
            st = os.lstat(self.sock_path)
        except FileNotFoundError:
            st = None
        if st is not None:
            if not stat.S_ISSOCK(st.st_mode):
                return
            self.sock_path.unlink(missing_ok=True)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            srv.bind(str(self.sock_path))
            os.chmod(self.sock_path, 0o600)
            srv.listen(8)
            srv.setblocking(False)
        except OSError:
            srv.close()
            self.sock_path.unlink(missing_ok=True)
            return  # degrade cleanly to FIFO-only if sun_path > 108B or socket dir is read-only
        self._sock = srv

    @property
    def enabled(self) -> bool:
        return self._sock is not None

    def _drop_client(self, client: socket.socket) -> None:
        self._bufs.pop(id(client), None)
        if client in self._clients:
            self._clients.remove(client)
        try:
            client.close()
        except OSError:
            pass

    def poll_commands(self) -> list[str]:
        """Accept waiting clients and return all complete newline-delimited commands."""
        if self._sock is None:
            return []
        while True:
            try:
                conn, _ = self._sock.accept()
            except BlockingIOError:
                break
            except OSError:
                break
            conn.setblocking(False)
            self._clients.append(conn)
            self._bufs[id(conn)] = bytearray()
        commands: list[str] = []
        for client in list(self._clients):
            buf = self._bufs.setdefault(id(client), bytearray())
            closed = False
            while True:
                try:
                    chunk = client.recv(4096)
                except BlockingIOError:
                    break
                except OSError:
                    closed = True
                    break
                if not chunk:
                    closed = True
                    break
                buf.extend(chunk)
            while True:
                nl = buf.find(b"\n")
                if nl < 0:
                    break
                line = bytes(buf[:nl]).decode("utf-8", errors="replace").strip()
                del buf[: nl + 1]
                if line:
                    commands.append(line)
            if closed:
                self._drop_client(client)
        return commands

    def broadcast_status(self, row: dict) -> None:
        """Push a status row to connected socket clients without blocking the runner tick."""
        if not self._clients:
            return
        raw = (json.dumps(row, default=str) + "\n").encode("utf-8")
        for client in list(self._clients):
            try:
                view = memoryview(raw)
                sent = 0
                while sent < len(view):
                    n = client.send(view[sent:])
                    if n <= 0:
                        raise BrokenPipeError("socket send stalled")
                    sent += n
            except OSError:
                # Non-blocking send failure or saturated client buffer: drop client cleanly.
                self._drop_client(client)

    def close(self) -> None:
        """Close all client connections (triggering immediate EOF/POLLHUP) and unlink socket."""
        for client in list(self._clients):
            self._drop_client(client)
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        try:
            self.sock_path.unlink(missing_ok=True)
        except OSError:
            pass


def send_unix_command(
    cell,
    sock_path: Path,
    *,
    wire_cmd: str,
    command: str,
    expected: str,
    verb: str,
    recovery: bool,
    is_hold: bool,
    hold_req: str | None,
    eff_timeout: float,
    finite_stamp,
    stall_timeout_s: float = 0.0,
) -> tuple[dict | None, str | None]:
    """Send one command over chunk-ctl.sock and await its status row or immediate EOF/stall.

    Returns ``(result_dict, None)`` when handled on the Unix socket, or
    ``(None, "fallback")`` when the socket does not exist / is not listening yet.
    """
    if not hasattr(socket, "AF_UNIX") or not Path(sock_path).is_socket():
        return None, "fallback"
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(min(1.0, max(0.05, eff_timeout)))
        try:
            sock.connect(str(sock_path))
        except (FileNotFoundError, ConnectionRefusedError, PermissionError, OSError):
            return None, "fallback"
        sent_at = time.time()
        try:
            sock.sendall((wire_cmd + "\n").encode("utf-8"))
        except OSError as exc:
            return {"ok": False, "fault": "runner_dead", "error": f"chunk_runner socket write failed: {exc}"}, None
        deadline = time.monotonic() + eff_timeout
        last_live_t = last_live_mono = None
        next_liveness = 0.0
        check_liveness = (not is_hold) and stall_timeout_s > 0
        sock.setblocking(False)
        buf = bytearray()
        with selectors.DefaultSelector() as sel:
            sel.register(sock, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                wait_s = min(remaining, 0.25) if check_liveness else remaining
                events = sel.select(timeout=wait_s)
                if events:
                    while True:
                        try:
                            chunk = sock.recv(4096)
                        except BlockingIOError:
                            break
                        except OSError:
                            chunk = b""
                        if not chunk:
                            return {
                                "ok": False,
                                "fault": "runner_dead",
                                "error": "chunk_runner closed control socket while awaiting status",
                            }, None
                        buf.extend(chunk)
                        while True:
                            nl = buf.find(b"\n")
                            if nl < 0:
                                break
                            raw_line = bytes(buf[:nl])
                            del buf[: nl + 1]
                            try:
                                row = json.loads(raw_line.decode("utf-8"))
                            except (ValueError, RecursionError):
                                if not is_hold:
                                    raise
                                continue
                            outcome = status_row_outcome(
                                row, command=command, expected=expected, verb=verb, recovery=recovery,
                                is_hold=is_hold, hold_req=hold_req, sent_at=sent_at, finite_stamp=finite_stamp,
                            )
                            if outcome == "hold":
                                return row, None
                            if outcome == "match":
                                cache_state_row(cell, row)
                                return row, None
                if check_liveness and (now_mono := time.monotonic()) >= next_liveness:
                    next_liveness = now_mono + 0.05
                    issue, last_live_t, last_live_mono = runner_liveness(
                        cell.policy_state(), last_t=last_live_t, last_mono=last_live_mono,
                        stall_timeout_s=stall_timeout_s, now_mono=now_mono, finite_stamp=finite_stamp, kill=os.kill,
                    )
                    if issue is not None:
                        return {"ok": False, "fault": issue[0], "error": issue[1]}, None
        return {"ok": False, **({"command": "human-hold"} if is_hold else {}), "error": f"no status within {eff_timeout} s"}, None
    finally:
        sock.close()
