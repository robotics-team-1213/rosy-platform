"""Read-only watch-root scanner, path/text scrubber, and non-blocking peer client for canonical OMX runs."""
from __future__ import annotations

import http.client
import ipaddress
import json
import math
import os
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
LOG_TAIL_BYTES = 32768
EVAL_TAIL_BYTES = 16384
PEER_MAX_BYTES = 262144
PEER_TIMEOUT_S = 2.0
PEER_TTL_S = 5.0
PEER_REFRESH_MIN_INTERVAL_S = 5.0

_PART_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,99}")
_PATH_KEYS = frozenset({
    "path", "root", "src", "dst", "dataset_root", "source_path", "output_dir", "train_dir",
    "resume_train_dir", "checkpoint_dir", "bundle_dir", "frames_dir", "envelope_path", "jobs_dir",
    "python", "cmdline", "argv", "cmd", "env", "mount", "mountpoint", "device", "hostname",
    "fqdn", "user", "username", "secret", "authorization", "gpu_uuid", "pci_bus_id",
    "peer_token_file", "url", "token",
})
_PATH_SUFFIXES = ("_path", "_dir", "_root", "_file", "_url", "_ip", "_token")
_PRIVATE_NETS = [ipaddress.ip_network(cidr) for cidr in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "100.64.0.0/10")]

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]{0,32}[ -/]{0,4}[@-~]")
_POSIX_PATH_RE = re.compile(r"(?:^|(?<=[\s='\"(\[]))/(?:home|mnt|tmp|var|opt|usr|etc|root|srv|Users|private)/[^\s'\",);\]]+")
_WIN_PATH_RE = re.compile(r"[A-Za-z]:[\\/][^\s'\",);\]]+")
_TAILSCALE_IP_RE = re.compile(r"\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}(?::\d{1,5})?\b")
_BEARER_RE = re.compile(r"(?i)\bBearer\s+\S+")
_HF_TOKEN_RE = re.compile(r"\bhf_[A-Za-z0-9]{6,}\b")
_TQDM_RE = re.compile(
    r"(?P<pct>\d{1,3})%\|[^|]{1,40}\|\s*(?P<step>\d{1,9})/(?P<total>\d{1,9})\s*"
    r"\[(?P<elapsed>[0-9:]{3,16})<(?P<eta>[0-9:days,\s?]{1,24}),\s*"
    r"(?P<rate>[0-9]{1,8}(?:\.[0-9]{1,4})?)(?P<unit>(?:step|it)/s|s/(?:step|it))\]"
)
_STEP_RE = re.compile(r"\bstep:(?P<num>\d+(?:\.\d+)?)(?P<suf>[KMkm]?)\b")
_KV_FLOAT = {
    k: re.compile(rf"\b{k}:(?P<val>[0-9.eE+-]{{1,16}})\b")
    for k in ("loss", "grdn", "lr", "updt_s")
}
_ARM_NAME_RE = re.compile(r"(arm_[ab])", re.I)
_CKPT_STEP_RE = re.compile(r"(\d{4,7})")
_EP_PROG_RE = re.compile(r"(?:\b(?:ep|episode|seed)\b[^\d\n]{0,6}|\[)(?P<done>\d{1,6})/(?P<total>\d{1,6})")
_EVAL_LINE_RE = re.compile(r"\bEVAL\s+\S+\s+\S+\s+\S+\s+(?P<verdict>pass|fail)\b", re.I)


class BusyConflict(ValueError):
    """Raised when GPU/CPU execution slots, locks, or rate limits are occupied (HTTP 409)."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _clean_chars(text: str, *, keep_newlines: bool) -> str:
    out = []
    for ch in _ANSI_RE.sub("", text):
        o = ord(ch)
        if ch == "\n" and keep_newlines:
            out.append("\n")
        elif o == 127 or 0x80 <= o <= 0x9F or 0x202A <= o <= 0x202E or 0x2066 <= o <= 0x2069 or o < 32:
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def scrub_text(text: str | None, max_chars: int = 256, *, keep_newlines: bool = False) -> str:
    if not text:
        return ""
    cleaned = _clean_chars(str(text), keep_newlines=keep_newlines)
    cleaned = _BEARER_RE.sub("Bearer <redacted>", cleaned)
    cleaned = _HF_TOKEN_RE.sub("<hf-token>", cleaned)
    cleaned = _TAILSCALE_IP_RE.sub("<tailscale-ip>", cleaned)
    cleaned = _POSIX_PATH_RE.sub("<path>", cleaned)
    cleaned = _WIN_PATH_RE.sub("<path>", cleaned)
    if not keep_newlines:
        cleaned = " ".join(cleaned.split())
    return cleaned[-max_chars:]


def _safe_under_root(root: Path, path: Path) -> bool:
    try:
        root_res = root.resolve()
        cur = path
        while True:
            if cur.is_symlink():
                return False
            if cur == root:
                break
            parent = cur.parent
            if parent == cur:
                break
            cur = parent
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            return False
        return path.resolve().is_relative_to(root_res)
    except OSError:
        return False


def _open_regular_bytes(path: Path, max_bytes: int, *, tail: bool = False) -> tuple[bytes, os.stat_result] | None:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    fd = None
    try:
        fd = os.open(path, flags)
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or (not tail and st.st_size > max_bytes):
            return None
        with os.fdopen(fd, "rb") as stream:
            fd = None
            if tail and st.st_size > max_bytes:
                stream.seek(st.st_size - max_bytes)
            return stream.read(max_bytes), st
    except OSError:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        return None


def _reject_non_finite(token: str):
    raise ValueError(f"non-finite JSON constant: {token}")


def read_bounded_json(path: Path, max_bytes: int = MAX_WATCH_FILE_BYTES, *, root: Path | None = None) -> dict | None:
    try:
        if root is not None:
            if not _safe_under_root(root, path):
                return None
        else:
            info = path.lstat()
            if path.is_symlink() or path.parent.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_size > max_bytes:
                return None
        loaded = _open_regular_bytes(path, max_bytes)
        if loaded is None:
            return None
        raw, _ = loaded
        doc = json.loads(raw.decode("utf-8"), parse_constant=_reject_non_finite)
        return doc if isinstance(doc, dict) else None
    except (OSError, ValueError):
        return None


def strip_paths(value):
    if isinstance(value, dict):
        return {
            k: strip_paths(v)
            for k, v in value.items()
            if k not in _PATH_KEYS and not k.endswith(_PATH_SUFFIXES)
        }
    if isinstance(value, list):
        return [strip_paths(item) for item in value]
    return value


def tail_log(run_root: Path, max_chars: int = 4096) -> str:
    log = run_root / "worker.log"
    if not _safe_under_root(run_root, log):
        return ""
    loaded = _open_regular_bytes(log, 8192, tail=True)
    if loaded is None:
        return ""
    raw, _ = loaded
    return scrub_text(raw.decode("utf-8", errors="replace"), max_chars=max_chars, keep_newlines=True)


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
        started = time.time()
        try:
            headers = {"Accept": "application/json", "Cache-Control": "no-cache"}
            token_file = cfg.get("peer_token_file")
            if token_file and token_file.is_file() and not token_file.is_symlink():
                tok = token_file.read_text(encoding="utf-8").strip()
                if tok:
                    headers["Authorization"] = f"Bearer {tok}"
            req = urllib.request.Request(cfg["url"] + "/api/learning/canonical/peer-summary", headers=headers)
            with self._opener.open(req, timeout=PEER_TIMEOUT_S) as resp:
                if resp.status != 200:
                    raise ValueError(f"HTTP {resp.status}")
                raw = resp.read(PEER_MAX_BYTES + 1)
            if len(raw) > PEER_MAX_BYTES:
                raise ValueError("peer summary exceeded 256 KiB cap")
            doc = strip_paths(json.loads(raw.decode("utf-8")))
            if not isinstance(doc, dict):
                raise ValueError("peer summary must be JSON object")
            doc = {**doc, **AUTHORITY_STAMP}
            if isinstance(doc.get("watched"), dict):
                doc["watched"] = {
                    k: ({**v, **AUTHORITY_STAMP} if isinstance(v, dict) else v)
                    for k, v in doc["watched"].items()
                }
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
            last = self._last_manual.get(peer_id, -math.inf)
            if now - last < PEER_REFRESH_MIN_INTERVAL_S:
                raise BusyConflict("peer refresh rate-limited (5s minimum interval)")
            self._last_manual[peer_id] = now
        return self._fetch_now(peer_id)

    def snapshot(self) -> dict[str, dict]:
        return {pid: self.get(pid) for pid in self._peers}


def _finite_float(raw: str | None) -> float | None:
    if not raw:
        return None
    try:
        v = float(raw)
        return v if math.isfinite(v) else None
    except ValueError:
        return None


def _parse_eta_s(raw: str) -> int | None:
    text = raw.strip()
    if not text or "?" in text:
        return None
    days = 0
    if "day" in text:
        head, _, text = text.partition(",")
        digits = "".join(ch for ch in head if ch.isdigit())
        days = int(digits) if digits else 0
    parts = [p.strip() for p in text.split(":") if p.strip().isdigit()]
    if len(parts) == 2:
        return days * 86400 + int(parts[0]) * 60 + int(parts[1])
    if len(parts) == 3:
        return days * 86400 + int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    return None


def _read_tail_lines(path: Path, max_bytes: int) -> tuple[list[str], float] | None:
    loaded = _open_regular_bytes(path, max_bytes, tail=True)
    if loaded is None:
        return None
    raw, st = loaded
    text = _clean_chars(raw.decode("utf-8", errors="replace"), keep_newlines=True)
    parts = re.split(r"[\r\n]+", text)
    if st.st_size > max_bytes and len(parts) > 1:
        parts = parts[1:]
    lines = [ln[:512] for ln in parts if ln.strip()]
    return lines[-200:], round(max(0.0, time.time() - st.st_mtime), 1)


def _scan_train_logs(root: Path) -> list[dict]:
    found: list[Path] = list(sorted(root.glob("*.train.log"))[:8])
    for arm in ARM_IDS:
        p = root / arm / "train.log"
        if p.exists() and p not in found:
            found.append(p)
    out = []
    for lp in found[:8]:
        if not _safe_under_root(root, lp):
            continue
        parsed_tail = _read_tail_lines(lp, LOG_TAIL_BYTES)
        if parsed_tail is None:
            continue
        lines, age_s = parsed_tail
        arm_match = _ARM_NAME_RE.search(lp.parent.name if lp.name == "train.log" else lp.stem)
        arm = arm_match.group(1).lower() if arm_match else None
        ended = any("End of training" in ln for ln in lines)
        tqdm_info = metrics = None
        for ln in reversed(lines):
            if tqdm_info is None and (m := _TQDM_RE.search(ln)):
                rate = _finite_float(m.group("rate"))
                if rate is not None and m.group("unit").startswith("s/") and rate > 0:
                    rate = 1.0 / rate
                tqdm_info = (int(m.group("step")), int(m.group("total")), round(rate, 3) if rate is not None else None, _parse_eta_s(m.group("eta")))
            if metrics is None and "step:" in ln and "loss:" in ln:
                sm = _STEP_RE.search(ln)
                istep = None
                if sm and (sv := _finite_float(sm.group("num"))) is not None:
                    mult = {"k": 1000, "m": 1000000}.get(sm.group("suf").lower(), 1)
                    istep = int(round(sv * mult))
                vals = {k: (_finite_float(rm.group("val")) if (rm := pat.search(ln)) else None) for k, pat in _KV_FLOAT.items()}
                metrics = (istep, vals["loss"], vals["grdn"], vals["lr"], vals["updt_s"])
            if tqdm_info is not None and metrics is not None:
                break
        step = tqdm_info[0] if tqdm_info else (metrics[0] if metrics else None)
        total = tqdm_info[1] if tqdm_info else None
        if metrics and metrics[0] is not None and (step is None or metrics[0] > step + 1000):
            step = metrics[0]
        rate = tqdm_info[2] if tqdm_info else (round(1.0 / metrics[4], 3) if metrics and metrics[4] and metrics[4] > 0 else None)
        eta_s = tqdm_info[3] if tqdm_info else None
        if ended and total:
            step, eta_s = total, 0
        pct = round(100.0 * step / total, 1) if (step is not None and total and total > 0) else None
        active = (not ended) and (age_s <= 180.0)
        out.append({
            "file": lp.name, "arm": arm, "status": "finished" if ended else ("running" if active else "stalled"),
            "active": active, "ended": ended, "step": step, "total_steps": total, "pct": pct,
            "rate_step_s": rate, "eta_s": eta_s,
            "loss": metrics[1] if metrics else None, "grdn": metrics[2] if metrics else None,
            "lr": metrics[3] if metrics else None, "log_age_s": age_s,
        })
    return out


def _scan_eval_logs(root: Path) -> list[dict]:
    out = []
    seen = set()
    for pat in ("arm_b_ladder/dev-*.log", "arm_a_ladder/dev-*.log", "ladder/dev-*.log", "ladder_a/dev-*.log", "eval_l1/dev-*.log"):
        for ep in sorted(root.glob(pat))[:8]:
            if len(out) >= 8:
                break
            if not _safe_under_root(root, ep):
                continue
            rel = ep.relative_to(root).as_posix()
            if rel in seen:
                continue
            seen.add(rel)
            tail_res = _read_tail_lines(ep, EVAL_TAIL_BYTES)
            if tail_res is None:
                continue
            lines, age_s = tail_res
            done = total = eta_s = successes = None
            passes = fails = 0
            for ln in lines:
                if em := _EVAL_LINE_RE.search(ln):
                    if em.group("verdict").lower() == "pass":
                        passes += 1
                    else:
                        fails += 1
            for ln in reversed(lines):
                if tm := _TQDM_RE.search(ln):
                    done, total, eta_s = int(tm.group("step")), int(tm.group("total")), _parse_eta_s(tm.group("eta"))
                    break
                if pm := _EP_PROG_RE.search(ln):
                    done, total = int(pm.group("done")), int(pm.group("total"))
                    break
            if passes or fails:
                successes = passes
                if done is None:
                    done = passes + fails
            cm = _CKPT_STEP_RE.search(ep.stem)
            pct = round(100.0 * done / total, 1) if (done is not None and total and total > 0) else None
            active = (done is None or total is None or done < total) and age_s <= 180.0
            out.append({
                "file": ep.name, "folder": ep.parent.name, "checkpoint": cm.group(1) if cm else ep.stem,
                "done": done, "total": total, "pct": pct, "successes": successes, "eta_s": eta_s,
                "active": active, "log_age_s": age_s, "last_line": scrub_text(lines[-1], max_chars=160) if lines else "",
            })
    return out


def scan_watch_dir(root: Path, meta: dict) -> dict:
    """Inspect a scratch/canonical run directory safely (no symlinks, <=1 MiB JSON, no host paths)."""
    if root.is_symlink() or not root.is_dir():
        return {"id": meta["id"], "label": meta["label"], "host_id": meta["host_id"],
                "available": False, "reason": "watch root missing or symlink", **AUTHORITY_STAMP}
    align_done = None
    align_file = root / "real_aligned" / "align.done"
    if _safe_under_root(root, align_file):
        loaded = _open_regular_bytes(align_file, 256, tail=False)
        if loaded is not None:
            align_done = scrub_text(loaded[0].decode("utf-8", errors="replace"), max_chars=128)

    receipts, seen = [], set()
    for pat in ("real_aligned/*/*/gate-receipt.json", "*/gate-receipt.json"):
        for rpath in sorted(root.glob(pat))[:32]:
            rel = rpath.relative_to(root).as_posix()
            if rel in seen:
                continue
            seen.add(rel)
            doc = read_bounded_json(rpath, root=root)
            if doc:
                receipts.append({
                    "name": rel[:-len("/gate-receipt.json")], "arm": doc.get("arm"),
                    "source": doc.get("source"), "counts": doc.get("counts"),
                    "dataset_reject": doc.get("dataset_reject"), "goals_passing": doc.get("goals_passing"),
                    "canonical_spec_sha256": doc.get("canonical_spec_sha256"),
                })

    seeds = {
        arm: len([p for p in root.glob(f"collect/dart-*/{arm}/meta/info.json") if _safe_under_root(root, p)])
        for arm in ARM_IDS
    }
    checkpoints = {}
    for arm in ARM_IDS:
        ck = {}
        for stage_dir in ("train", "train_stage2"):
            croot = root / arm / stage_dir / "checkpoints"
            if not croot.is_symlink() and croot.is_dir() and croot.resolve().is_relative_to(root.resolve()):
                names = [p.name for p in sorted(croot.iterdir()) if not p.is_symlink() and _PART_RE.fullmatch(p.name)]
                if names:
                    ck[stage_dir] = names[:64]
        if ck:
            checkpoints[arm] = ck

    eval_ladder, seen_evals = [], set()
    for pat in ("arm_b_ladder/*.json", "arm_a_ladder/*.json", "ladder/*.json", "ladder_a/*.json", "eval_l1/*.json"):
        for ep in sorted(root.glob(pat))[:48]:
            if len(eval_ladder) >= 48:
                break
            rel = ep.relative_to(root).as_posix()
            if rel in seen_evals:
                continue
            seen_evals.add(rel)
            doc = read_bounded_json(ep, root=root)
            if doc:
                eval_ladder.append({**strip_paths(doc), "file": ep.name, "folder": ep.parent.name, **AUTHORITY_STAMP})

    cell_checks, seen_checks = [], []
    for cname in ("arm_b_cell_live_check.json", "arm_a_cell_live_check.json"):
        if (root / cname).exists():
            seen_checks.append(root / cname)
    for ep in sorted(root.glob("cell_live_check*.json"))[:16]:
        if ep not in seen_checks:
            seen_checks.append(ep)
    for ep in seen_checks:
        doc = read_bounded_json(ep, root=root)
        if doc:
            cell_checks.append({**strip_paths(doc), "name": ep.name, **AUTHORITY_STAMP})

    markers = {}
    for mname in ("collect.done", "stage1-done", "stage2-done"):
        mp = root / mname
        if _safe_under_root(root, mp):
            try:
                markers[mname] = {"present": True, "mtime": round(mp.lstat().st_mtime, 1)}
            except OSError:
                pass
    prog = read_bounded_json(root / "progress.json", root=root)
    return {
        "id": meta["id"], "label": meta["label"], "host_id": meta["host_id"], "available": True,
        "align_done": align_done, "gate_receipts": receipts, "collect_seeds": seeds,
        "checkpoints": checkpoints, "training": _scan_train_logs(root), "eval_progress": _scan_eval_logs(root),
        "eval_ladder": eval_ladder, "cell_live_checks": cell_checks,
        "markers": markers, "progress": strip_paths(prog) if prog else None, **AUTHORITY_STAMP,
    }
