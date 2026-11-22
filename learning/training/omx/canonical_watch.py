"""Read-only watch-root scanner, path stripper, and non-blocking peer client for canonical OMX runs."""
from __future__ import annotations

import http.client
import ipaddress
import json
from pathlib import Path
import re
import stat
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

_CONTRACTS_SRC = Path(__file__).resolve().parents[3] / "contracts" / "learning" / "src"
if str(_CONTRACTS_SRC) not in sys.path:
    sys.path.insert(0, str(_CONTRACTS_SRC))

from rosy.contracts.learning.omx_canonical import AUTHORITY_STAMP, ARM_IDS  # noqa: E402

MAX_WATCH_FILE_BYTES = 1048576
PEER_MAX_BYTES = 262144
PEER_TIMEOUT_S = 2.0
PEER_TTL_S = 15.0
PEER_REFRESH_MIN_INTERVAL_S = 5.0

_PART_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,99}")
_PATH_KEYS = frozenset({
    "path", "root", "src", "dst", "dataset_root", "source_path", "output_dir", "train_dir",
    "checkpoint_dir", "bundle_dir", "frames_dir", "envelope_path", "jobs_dir", "python",
})
_PRIVATE_NETS = [ipaddress.ip_network(cidr) for cidr in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "100.64.0.0/10")]


class BusyConflict(ValueError):
    """Raised when GPU/CPU execution slots, locks, or rate limits are occupied (HTTP 409)."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_bounded_json(path: Path, max_bytes: int = MAX_WATCH_FILE_BYTES) -> dict | None:
    try:
        info = path.lstat()
        if path.is_symlink() or path.parent.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_size > max_bytes:
            return None
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except (OSError, ValueError):
        return None


def strip_paths(value):
    if isinstance(value, dict):
        return {k: strip_paths(v) for k, v in value.items() if k not in _PATH_KEYS}
    if isinstance(value, list):
        return [strip_paths(item) for item in value]
    return value


def tail_log(run_root: Path, max_chars: int = 4096) -> str:
    log = run_root / "worker.log"
    if log.is_symlink() or not log.is_file():
        return ""
    try:
        size = log.stat().st_size
        with log.open("rb") as stream:
            if size > 8192:
                stream.seek(size - 8192)
            raw = stream.read(8192)
    except OSError:
        return ""
    cleaned = "".join(ch if ch == "\n" or ord(ch) >= 32 else " " for ch in raw.decode("utf-8", errors="replace"))
    return cleaned[-max_chars:]


def validate_peer_url(raw: str) -> str:
    if not isinstance(raw, str) or not 1 <= len(raw) <= 256:
        raise ValueError("bounded peer URL required")
    parsed = urllib.parse.urlsplit(raw)
    if (parsed.username is not None or parsed.password is not None
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment or not parsed.hostname):
        raise ValueError("peer URL must be an origin without credentials, path, query, or fragment")
    if parsed.scheme == "https":
        return raw.rstrip("/")
    if parsed.scheme != "http" or not parsed.port:
        raise ValueError("http peer URL requires literal private/Tailscale IPv4 and port")
    try:
        addr = ipaddress.IPv4Address(parsed.hostname)
    except ValueError as exc:
        raise ValueError("http peer URL requires literal IPv4 address") from exc
    if not any(addr in net for net in _PRIVATE_NETS):
        raise ValueError("peer IPv4 outside loopback/RFC1918/Tailscale range")
    return raw.rstrip("/")


class PeerClient:
    """Server-configured read-only peer snapshot poller with short timeout, cache, and no redirects."""

    def __init__(self, peers: dict[str, dict]):
        self._peers = peers
        self._cache: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._inflight: set[str] = set()
        self._last_manual: dict[str, float] = {}
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def _fetch_now(self, peer_id: str) -> dict:
        cfg = self._peers[peer_id]
        headers = {"Accept": "application/json", "Cache-Control": "no-cache"}
        token_file = cfg.get("peer_token_file")
        if token_file and token_file.is_file() and not token_file.is_symlink():
            tok = token_file.read_text(encoding="utf-8").strip()
            if tok:
                headers["Authorization"] = f"Bearer {tok}"
        req = urllib.request.Request(cfg["url"] + "/api/learning/canonical/peer-summary", headers=headers)
        started = time.time()
        try:
            with self._opener.open(req, timeout=PEER_TIMEOUT_S) as resp:
                if resp.status != 200:
                    raise ValueError(f"HTTP {resp.status}")
                raw = resp.read(PEER_MAX_BYTES + 1)
            if len(raw) > PEER_MAX_BYTES:
                raise ValueError("peer summary exceeded 256 KiB cap")
            doc = strip_paths(json.loads(raw.decode("utf-8")))
            if not isinstance(doc, dict):
                raise ValueError("peer summary must be JSON object")
            entry = {
                "peer_id": peer_id, "label": cfg["label"], "status": "ok",
                "fetched_at": started, "error": None, "summary": doc, **AUTHORITY_STAMP,
            }
        except (OSError, ValueError, urllib.error.URLError, http.client.HTTPException) as exc:
            entry = {
                "peer_id": peer_id, "label": cfg["label"], "status": "unavailable",
                "fetched_at": started, "error": f"peer unavailable ({type(exc).__name__})",
                "summary": None, **AUTHORITY_STAMP,
            }
        with self._lock:
            self._cache[peer_id] = entry
        return entry

    def _refresh_async(self, peer_id: str) -> None:
        with self._lock:
            if peer_id in self._inflight:
                return
            self._inflight.add(peer_id)

        def run():
            try:
                self._fetch_now(peer_id)
            finally:
                with self._lock:
                    self._inflight.discard(peer_id)

        threading.Thread(target=run, name=f"canon-peer-{peer_id}", daemon=True).start()

    def get(self, peer_id: str) -> dict:
        if peer_id not in self._peers:
            raise KeyError("unknown peer")
        now = time.time()
        with self._lock:
            cached = self._cache.get(peer_id)
        if cached is None:
            self._refresh_async(peer_id)
            return {
                "peer_id": peer_id, "label": self._peers[peer_id]["label"],
                "status": "stale", "fetched_at": None, "error": None, "summary": None, **AUTHORITY_STAMP,
            }
        if now - cached["fetched_at"] > PEER_TTL_S:
            self._refresh_async(peer_id)
            return dict(cached, status="stale" if cached["status"] == "ok" else cached["status"])
        return dict(cached)

    def refresh(self, peer_id: str) -> dict:
        if peer_id not in self._peers:
            raise KeyError("unknown peer")
        now = time.monotonic()
        with self._lock:
            last = self._last_manual.get(peer_id, 0.0)
            if now - last < PEER_REFRESH_MIN_INTERVAL_S:
                raise BusyConflict("peer refresh rate-limited (5s minimum interval)")
            self._last_manual[peer_id] = now
        return self._fetch_now(peer_id)

    def snapshot(self) -> dict[str, dict]:
        return {pid: self.get(pid) for pid in self._peers}


def scan_watch_dir(root: Path, meta: dict) -> dict:
    """Inspect a scratch/canonical run directory safely (no symlinks, <=1 MiB JSON, no host paths)."""
    if root.is_symlink() or not root.is_dir():
        return {"id": meta["id"], "label": meta["label"], "host_id": meta["host_id"],
                "available": False, "reason": "watch root missing or symlink", **AUTHORITY_STAMP}
    align_done = None
    align_file = root / "real_aligned" / "align.done"
    if not align_file.is_symlink() and align_file.is_file():
        try:
            align_done = align_file.read_bytes()[:256].decode("utf-8", errors="replace").strip()
        except OSError:
            align_done = None

    receipts, seen = [], set()
    for pat in ("real_aligned/*/*/gate-receipt.json", "*/gate-receipt.json"):
        for rpath in sorted(root.glob(pat))[:32]:
            rel = rpath.relative_to(root).as_posix()
            if rel in seen:
                continue
            seen.add(rel)
            doc = read_bounded_json(rpath)
            if doc:
                receipts.append({
                    "name": rel[:-len("/gate-receipt.json")], "arm": doc.get("arm"),
                    "source": doc.get("source"), "counts": doc.get("counts"),
                    "dataset_reject": doc.get("dataset_reject"), "goals_passing": doc.get("goals_passing"),
                    "canonical_spec_sha256": doc.get("canonical_spec_sha256"),
                })

    seeds = {
        arm: len([p for p in root.glob(f"collect/dart-*/{arm}/meta/info.json") if not p.is_symlink() and p.is_file()])
        for arm in ARM_IDS
    }
    checkpoints = {}
    for arm in ARM_IDS:
        ck = {}
        for stage_dir in ("train", "train_stage2"):
            croot = root / arm / stage_dir / "checkpoints"
            if not croot.is_symlink() and croot.is_dir():
                names = [p.name for p in sorted(croot.iterdir()) if not p.is_symlink() and _PART_RE.fullmatch(p.name)]
                if names:
                    ck[stage_dir] = names[:64]
        if ck:
            checkpoints[arm] = ck

    eval_ladder = []
    for pat in ("ladder_a/*.json", "eval_l1/*.json"):
        for ep in sorted(root.glob(pat))[:40]:
            doc = read_bounded_json(ep)
            if doc:
                eval_ladder.append({**strip_paths(doc), "file": ep.name})

    cell_checks = []
    seen_checks = []
    for cname in ("arm_b_cell_live_check.json", "arm_a_cell_live_check.json"):
        if (root / cname).exists():
            seen_checks.append(root / cname)
    for ep in sorted(root.glob("cell_live_check*.json"))[:16]:
        if ep not in seen_checks:
            seen_checks.append(ep)
    for ep in seen_checks:
        doc = read_bounded_json(ep)
        if doc:
            cell_checks.append({**strip_paths(doc), "name": ep.name})

    markers = {}
    for mname in ("stage1-done", "stage2-done"):
        mp = root / mname
        if not mp.is_symlink() and mp.exists():
            try:
                markers[mname] = {"present": True, "mtime": round(mp.stat().st_mtime, 1)}
            except OSError:
                pass
    prog = read_bounded_json(root / "progress.json")
    return {
        "id": meta["id"], "label": meta["label"], "host_id": meta["host_id"], "available": True,
        "align_done": align_done, "gate_receipts": receipts, "collect_seeds": seeds,
        "checkpoints": checkpoints, "eval_ladder": eval_ladder, "cell_live_checks": cell_checks,
        "markers": markers, "progress": strip_paths(prog) if prog else None, **AUTHORITY_STAMP,
    }
