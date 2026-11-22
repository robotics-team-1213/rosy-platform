"""Stdlib-only host resource telemetry, external GPU lock visibility, and minimal AI PC peer server."""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import hmac
import http.server
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
import urllib.parse

_CONTRACTS_SRC = Path(__file__).resolve().parents[3] / "contracts" / "learning" / "src"
if str(_CONTRACTS_SRC) not in sys.path:
    sys.path.insert(0, str(_CONTRACTS_SRC))

from rosy.contracts.learning.omx_canonical import (  # noqa: E402
    AUTHORITY_STAMP,
    canonical_spec_sha256,
    default_canonical_spec,
)

PEER_MAX_BYTES = 262144
NVIDIA_CMD = (
    "nvidia-smi",
    "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
    "--format=csv,noheader,nounits",
)
_ID_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,63}")
_PRIVATE_NETS = tuple(ipaddress.ip_network(c) for c in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "100.64.0.0/10"))


def _empty_gpu() -> dict:
    return {
        "available": False, "name": None, "util_pct": None,
        "vram_used_mib": None, "vram_total_mib": None, "temp_c": None, "power_w": None,
    }


def _finite_float(raw: str) -> float | None:
    text = raw.strip()
    if not text or text.startswith("[") or text.upper() in ("N/A", "NA", "NONE", "UNKNOWN"):
        return None
    try:
        val = float(text)
    except ValueError:
        return None
    return val if math.isfinite(val) else None


def _parse_nvidia_csv(raw_text: str) -> dict:
    gpu = _empty_gpu()
    if not raw_text:
        return gpu
    names, utils, v_used, v_tot, temps, powers = [], [], [], [], [], []
    for row in csv.reader(raw_text.splitlines(), skipinitialspace=True):
        if len(row) < 6:
            continue
        name = "".join(ch for ch in row[0].strip() if ord(ch) >= 32)[:80]
        mtot = _finite_float(row[3])
        if not name or mtot is None or mtot <= 0:
            continue
        names.append(name)
        v_tot.append(int(round(mtot)))
        if (mu := _finite_float(row[2])) is not None and mu >= 0:
            v_used.append(int(round(mu)))
        if (u := _finite_float(row[1])) is not None and 0.0 <= u <= 100.0:
            utils.append(int(round(u)))
        if (t := _finite_float(row[4])) is not None and -20.0 <= t <= 150.0:
            temps.append(int(round(t)))
        if (pw := _finite_float(row[5])) is not None and pw >= 0.0:
            powers.append(pw)
    if not names:
        return gpu
    return {
        "available": True,
        "name": names[0],
        "util_pct": max(utils) if utils else None,
        "vram_used_mib": sum(v_used) if len(v_used) == len(names) else (v_used[0] if v_used else None),
        "vram_total_mib": sum(v_tot),
        "temp_c": max(temps) if temps else None,
        "power_w": round(sum(powers), 2) if powers else None,
    }


def _read_os_metrics(disk_probe: Path | None) -> dict:
    cores = os.cpu_count()
    l1 = l5 = None
    if hasattr(os, "getloadavg"):
        try:
            a, b, _ = os.getloadavg()
            if math.isfinite(a) and math.isfinite(b):
                l1, l5 = round(float(a), 2), round(float(b), 2)
        except OSError:
            pass
    mem = {"used_gib": None, "total_gib": None, "pct": None}
    meminfo = Path("/proc/meminfo")
    try:
        if meminfo.is_file() and not meminfo.is_symlink():
            vals = {}
            for line in meminfo.read_bytes()[:65536].decode("ascii", errors="ignore").splitlines():
                if ":" in line:
                    k, rest = line.split(":", 1)
                    parts = rest.strip().split()
                    if parts and parts[0].isdigit():
                        vals[k] = int(parts[0])
            tot_kb, avail_kb = vals.get("MemTotal"), vals.get("MemAvailable")
            if tot_kb and tot_kb > 0 and avail_kb is not None:
                used_kb = max(0, tot_kb - avail_kb)
                mem = {
                    "used_gib": round(used_kb / 1048576.0, 1),
                    "total_gib": round(tot_kb / 1048576.0, 1),
                    "pct": round(100.0 * used_kb / tot_kb, 1),
                }
    except OSError:
        pass
    disk = {"free_gib": None, "total_gib": None, "use_pct": None, "state": "unknown"}
    target = disk_probe
    try:
        while target is not None and not target.exists():
            parent = target.parent
            target = None if parent == target else parent
        if target is None:
            target = Path.home()
        u = shutil.disk_usage(target)
        if u.total > 0:
            free_g = round(u.free / 1024**3, 1)
            tot_g = round(u.total / 1024**3, 1)
            use_pct = round(100.0 * (u.total - u.free) / u.total, 1)
            state = "crit" if (use_pct >= 90.0 or free_g < 30.0) else "warn" if (use_pct >= 80.0 or free_g < 60.0) else "ok"
            disk = {"free_gib": free_g, "total_gib": tot_g, "use_pct": use_pct, "state": state}
    except OSError:
        pass
    return {"cpu": {"cores": cores, "load_1m": l1, "load_5m": l5}, "memory": mem, "disk": disk}


class HostTelemetry:
    """Lazy, lock-isolated host CPU/RAM/disk/GPU telemetry cache with D-state timeout circuit breaker."""

    def __init__(self, disk_probe_fn, *, ttl_s: float = 5.0, gpu_timeout_s: float = 2.0, runner=None, clock=time.time):
        self._disk_probe_fn = disk_probe_fn
        self._ttl_s = float(ttl_s)
        self._gpu_timeout_s = float(gpu_timeout_s)
        self._runner = runner
        self._clock = clock
        self._lock = threading.Lock()
        self._cache: dict | None = None
        self._cache_at: float = 0.0
        self._inflight = False
        self._ready = threading.Event()
        self._wedged_proc: subprocess.Popen | None = None
        self._gpu_cooldown_until: float = 0.0

    def _run_nvidia_smi(self, now: float) -> dict:
        with self._lock:
            if self._wedged_proc is not None:
                if self._wedged_proc.poll() is None:
                    return _empty_gpu()
                self._wedged_proc = None
            if now < self._gpu_cooldown_until:
                return _empty_gpu()
        if self._runner is not None:
            try:
                res = self._runner(list(NVIDIA_CMD), timeout=self._gpu_timeout_s)
                if isinstance(res, tuple):
                    rc, text = res
                else:
                    rc, text = getattr(res, "returncode", 1), getattr(res, "stdout", "")
                if rc != 0:
                    return _empty_gpu()
                return _parse_nvidia_csv(text.decode("utf-8", errors="replace") if isinstance(text, bytes) else str(text))
            except subprocess.TimeoutExpired:
                with self._lock:
                    self._gpu_cooldown_until = self._clock() + 60.0
                return _empty_gpu()
            except OSError:
                return _empty_gpu()

        proc = None
        try:
            proc = subprocess.Popen(
                list(NVIDIA_CMD),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=(os.name == "posix"),
            )
            chunks: list[bytes] = []

            def _read():
                try:
                    if proc.stdout is not None:
                        chunks.append(proc.stdout.read(16384))
                except OSError:
                    pass
                finally:
                    try:
                        if proc.stdout is not None:
                            proc.stdout.close()
                    except OSError:
                        pass

            rth = threading.Thread(target=_read, daemon=True)
            rth.start()
            rc = proc.wait(timeout=self._gpu_timeout_s)
            rth.join(timeout=0.2)
            if rc != 0:
                return _empty_gpu()
            return _parse_nvidia_csv(b"".join(chunks).decode("utf-8", errors="replace"))
        except subprocess.TimeoutExpired:
            if proc is not None:
                try:
                    if os.name == "posix":
                        os.killpg(proc.pid, signal.SIGKILL)
                    else:
                        proc.kill()
                except OSError:
                    pass
                try:
                    proc.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    pass
                with self._lock:
                    if proc.poll() is None:
                        self._wedged_proc = proc
                    self._gpu_cooldown_until = self._clock() + 60.0
            else:
                with self._lock:
                    self._gpu_cooldown_until = self._clock() + 60.0
            return _empty_gpu()
        except OSError:
            return _empty_gpu()

    def _collect(self) -> dict:
        now = self._clock()
        probe = self._disk_probe_fn() if callable(self._disk_probe_fn) else self._disk_probe_fn
        os_metrics = _read_os_metrics(Path(probe) if probe is not None else None)
        gpu = self._run_nvidia_smi(now)
        return {
            "gpu": gpu,
            **os_metrics,
            "collected_at": round(float(self._clock()), 1),
            "stale": False,
        }

    def _trigger_refresh(self) -> threading.Event:
        with self._lock:
            ev = self._ready
            if self._inflight:
                return ev
            self._inflight = True
            ev = threading.Event()
            self._ready = ev

        def _work():
            try:
                sample = self._collect()
                with self._lock:
                    self._cache = sample
                    self._cache_at = self._clock()
            finally:
                with self._lock:
                    self._inflight = False
                ev.set()

        threading.Thread(target=_work, name="canon-telemetry", daemon=True).start()
        return ev

    def snapshot(self) -> dict:
        now = self._clock()
        with self._lock:
            cached = self._cache
            age = now - self._cache_at if cached is not None else math.inf
        if cached is not None:
            if age <= self._ttl_s:
                return {**cached, "stale": False}
            self._trigger_refresh()
            return {**cached, "stale": True}
        ev = self._trigger_refresh()
        ev.wait(timeout=0.4)
        with self._lock:
            cached = self._cache
        if cached is not None:
            return {**cached, "stale": False}
        probe = self._disk_probe_fn() if callable(self._disk_probe_fn) else self._disk_probe_fn
        os_metrics = _read_os_metrics(Path(probe) if probe is not None else None)
        return {"gpu": _empty_gpu(), **os_metrics, "collected_at": round(float(self._clock()), 1), "stale": True}


def external_gpu_locks(jobs_dir: Path | None) -> list[str]:
    """Return active external ~/rosy-jobs/train-<pid>.lock and gpu*.lock names without host paths."""
    if jobs_dir is None or jobs_dir.is_symlink() or not jobs_dir.is_dir():
        return []
    holders, paths = [], []
    for pat in ("train-*.lock", "gpu*.lock"):
        for lp in sorted(jobs_dir.glob(pat)):
            if lp not in paths:
                paths.append(lp)
    for lp in paths[:16]:
        if lp.is_symlink() or not lp.is_file():
            continue
        try:
            pid = int(lp.read_bytes()[:32].decode("ascii", errors="ignore").strip().splitlines()[0])
        except (OSError, IndexError, ValueError):
            continue
        if pid <= 0:
            continue
        if Path("/proc").is_dir():
            pdir = Path(f"/proc/{pid}")
            alive = pdir.is_dir()
            if alive:
                try:
                    stat_txt = (pdir / "stat").read_text(encoding="ascii", errors="ignore")
                    if stat_txt.rsplit(")", 1)[1].lstrip().startswith("Z"):
                        alive = False
                except OSError:
                    alive = False
        else:
            try:
                os.kill(pid, 0)
                alive = True
            except PermissionError:
                alive = True
            except OSError:
                alive = False
        if alive:
            holders.append(f"external:{lp.stem}")
    return holders


def load_peer_token(token_file: Path) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(token_file, flags)
    except OSError as exc:
        raise ValueError("peer token file must be a readable regular non-symlink file") from exc
    with os.fdopen(fd, "rb") as stream:
        st = os.fstat(stream.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_size > 4096:
            raise ValueError("peer token file must be a bounded regular file")
        if os.name == "posix":
            if (st.st_mode & 0o077) != 0:
                raise ValueError("peer token file must not allow group/world permissions")
            if hasattr(os, "getuid") and st.st_uid != os.getuid():
                raise ValueError("peer token file must be owned by service user")
        raw = stream.read(4097)
    if len(raw) > 4096:
        raise ValueError("peer token file exceeds 4096 bytes")
    try:
        tok = raw.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise ValueError("peer token file must be valid UTF-8") from exc
    if len(tok) < 16 or any(ord(c) < 32 for c in tok):
        raise ValueError("peer token must be at least 16 printable chars")
    return tok


_load_peer_token = load_peer_token


def _validate_bind_host(raw: str) -> str:
    try:
        addr = ipaddress.IPv4Address(raw)
    except ValueError as exc:
        raise ValueError("peer server requires literal IPv4 bind address") from exc
    if addr.is_unspecified or not any(addr in net for net in _PRIVATE_NETS):
        raise ValueError("peer bind IPv4 must be loopback, RFC1918, or Tailscale 100.64.0.0/10")
    return raw


@dataclass(frozen=True)
class PeerServerConfig:
    host: str
    port: int
    host_id: str
    token: str
    jobs_dir: Path | None
    watch_roots: dict[str, dict]


def create_peer_server(cfg: PeerServerConfig, *, telemetry: HostTelemetry | None = None):
    """Build a bounded, read-only, single-route HTTP server for /api/learning/canonical/peer-summary."""
    from canonical_watch import scan_watch_dir

    spec = default_canonical_spec()
    spec_sha = canonical_spec_sha256(spec)
    first_watch = next((m["path"] for m in cfg.watch_roots.values()), None)
    tel = telemetry or HostTelemetry(lambda: first_watch or Path.home())
    sem = threading.BoundedSemaphore(4)

    class PeerHandler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def setup(self):
            super().setup()
            self.request.settimeout(5.0)

        def log_message(self, format, *args):  # noqa: A002
            return

        def _send_json(self, payload: dict, status: int = 200, extra_headers: dict | None = None):
            raw = json.dumps(payload, allow_nan=False, ensure_ascii=False).encode("utf-8")
            if len(raw) > PEER_MAX_BYTES:
                status = 500
                raw = json.dumps({"error": "peer summary exceeded size budget"}).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            for hk, hv in (extra_headers or {}).items():
                self.send_header(hk, hv)
            self.end_headers()
            self.wfile.write(raw)

        def _check_host(self) -> bool:
            expected = f"{self.server.bind_host}:{self.server.server_port}"
            return (self.headers.get("Host") or "").strip() == expected

        def _method_not_allowed(self):
            if not self._check_host():
                self._send_json({"error": "invalid host"}, 403)
                return
            self._send_json({"error": "method not allowed"}, 405, {"Allow": "GET"})

        do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _method_not_allowed

        def do_GET(self):
            if not self._check_host():
                self._send_json({"error": "invalid host"}, 403)
                return
            auth = self.headers.get("Authorization") or ""
            if not auth.startswith("Bearer ") or not hmac.compare_digest(auth[7:].strip(), cfg.token):
                self._send_json({"error": "unauthorized"}, 403)
                return
            if not sem.acquire(blocking=False):
                self._send_json({"error": "peer busy"}, 503)
                return
            try:
                parsed = urllib.parse.urlsplit(self.path)
                if parsed.query:
                    self._send_json({"error": "query parameters disallowed"}, 400)
                    return
                if parsed.path != "/api/learning/canonical/peer-summary":
                    self._send_json({"error": "not found"}, 404)
                    return
                holders = external_gpu_locks(cfg.jobs_dir)
                watched = {wid: scan_watch_dir(m["path"], m) for wid, m in cfg.watch_roots.items()}
                body = {
                    "host_id": cfg.host_id, "configured": True, "writable": False,
                    "spec_sha256": spec_sha, "gpu_lock": {"busy": bool(holders), "holders": holders},
                    "runs": [], "watched": watched, "host_telemetry": tel.snapshot(),
                    **AUTHORITY_STAMP,
                }
                self._send_json(body, 200)
            finally:
                sem.release()

    class Server(http.server.ThreadingHTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    srv = Server((cfg.host, cfg.port), PeerHandler)
    srv.bind_host = cfg.host
    return srv


def _parse_watch_arg(raw: str, host_id: str) -> tuple[str, dict]:
    if "=" not in raw:
        raise ValueError("--watch expects id=path[:label]")
    wid, rest = raw.split("=", 1)
    if not _ID_RE.fullmatch(wid):
        raise ValueError(f"invalid watch id: {wid}")
    split_at = rest.find(":", 2 if len(rest) >= 2 and rest[1] == ":" else 0)
    path_str, label = (rest[:split_at], rest[split_at + 1:]) if split_at != -1 else (rest, wid)
    path = Path(path_str)
    if not path.is_absolute() or path.is_symlink():
        raise ValueError(f"watch root must be absolute non-symlink: {wid}")
    return wid, {"id": wid, "label": (label or wid)[:120], "host_id": host_id, "path": path.resolve()}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("serve-peer")
    sp.add_argument("--host", required=True)
    sp.add_argument("--port", type=int, default=8770)
    sp.add_argument("--host-id", required=True, choices=("ai", "model"))
    sp.add_argument("--token-file", type=Path, required=True)
    sp.add_argument("--jobs-dir", type=Path, default=None)
    sp.add_argument("--watch", action="append", default=[])
    args = parser.parse_args(argv)
    watches = dict(_parse_watch_arg(item, args.host_id) for item in args.watch)
    if args.jobs_dir and args.jobs_dir.is_symlink():
        raise ValueError("jobs_dir must not be a symlink")
    jobs_dir = args.jobs_dir.resolve() if args.jobs_dir else None
    cfg = PeerServerConfig(
        host=_validate_bind_host(args.host), port=args.port, host_id=args.host_id,
        token=load_peer_token(args.token_file), jobs_dir=jobs_dir, watch_roots=watches,
    )
    srv = create_peer_server(cfg)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.shutdown()
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
