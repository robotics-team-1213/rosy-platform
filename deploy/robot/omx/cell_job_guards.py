"""Authentication, authorization, hardware/Fleet safety gates, dirty state, and idempotency for `cell_job_api`."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import ssl
import stat
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROLE_HUMAN = "cell-job-human"
ROLE_MACHINE = "cell-job-machine"
IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


@dataclass(frozen=True)
class Principal:
    role: str
    principal_id: str


def authenticate_bearer(
    auth_header: str,
    *,
    human_token: str | None,
    machine_token: str | None,
    human_id: str = ROLE_HUMAN,
    machine_id: str = ROLE_MACHINE,
) -> Principal | None:
    """Resolve `Authorization: Bearer ...` into a Principal using constant-time digest checks."""
    got = (auth_header or "").encode("utf-8")
    if machine_token and hmac.compare_digest(got, f"Bearer {machine_token}".encode("utf-8")):
        return Principal(ROLE_MACHINE, machine_id)
    if human_token and hmac.compare_digest(got, f"Bearer {human_token}".encode("utf-8")):
        return Principal(ROLE_HUMAN, human_id)
    return None


def authorize_principal(
    job_name: str,
    job: dict[str, Any],
    params: dict[str, Any],
    principal: Principal,
    *,
    moves_arm_fn: Callable[[dict[str, Any], dict[str, Any]], bool],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Enforce machine-token commissioning ban and server-bound proposer identity."""
    eff = dict(params)
    if principal.role == ROLE_HUMAN:
        return eff, None
    if principal.role != ROLE_MACHINE:
        return eff, {"code": 403, "error_code": "FORBIDDEN_ROLE", "error": f"unsupported principal role {principal.role}"}
    if eff.get("person_at_switch") is True:
        return eff, {
            "code": 403,
            "error_code": "MACHINE_COMMISSIONING_FORBIDDEN",
            "error": "cell-job-machine cannot assert person_at_switch or start commissioning motion",
        }
    opt = job.get("optional") or ()
    if moves_arm_fn(job, eff) and not (bool(job.get("reviewed_only")) or ("reviewed_auto" in opt and eff.get("reviewed_auto") is True)):
        return eff, {
            "code": 403,
            "error_code": "MACHINE_COMMISSIONING_FORBIDDEN",
            "error": f"cell-job-machine cannot start unreviewed moving job {job_name}",
        }
    allowed_keys = set(job.get("params") or ()) | set(job.get("optional") or ())
    if "proposer" in allowed_keys:
        if "proposer" in eff and str(eff["proposer"]) != principal.principal_id:
            return eff, {
                "code": 403,
                "error_code": "PROPOSER_MISMATCH",
                "error": "cell-job-machine proposer is server-bound",
            }
        if "operator" in eff or "proposer" in eff:
            eff["proposer"] = principal.principal_id
    return eff, None


def check_arm_incident_hold(arm: str | None) -> str | None:
    """Return hold reason when `omx_incident` reports local hold, Fleet hold, or unsent outbox."""
    if not arm:
        return None
    import omx_incident

    try:
        st = omx_incident.status(arm)
        if st.get("local_held") or st.get("fleet_held") or (st.get("unsent_outbox") or 0) > 0:
            return str(st.get("local_reason") or st.get("fleet_reason") or "arm incident hold or unsent outbox")
        return None
    except Exception:
        lf = omx_incident.hold_file(arm)
        return f"local hold {lf.name}" if lf is not None else None


def _live_folded(row: dict[str, Any]) -> bool | None:
    if isinstance(row.get("folded"), bool):
        return row["folded"]
    st = row.get("state")
    if isinstance(st, list) and len(st) >= 6 and all(
        isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v)) for v in st[:6]
    ):
        return float(st[1]) <= -50.0 and float(st[2]) >= 45.0
    return None


def _latest_status_row(status_path: Path) -> dict[str, Any] | None:
    try:
        lines = [ln.strip() for ln in status_path.read_text(encoding="utf-8", errors="replace").splitlines()[-25:] if ln.strip().startswith("{")]
    except OSError:
        return None
    for raw in reversed(lines):
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        if isinstance(row, dict) and isinstance(row.get("state"), list):
            return row
    return None


def check_peer_ab_folded(
    arm: str | None,
    workdir: Path,
    lease_dir: Path,
    lock_dir: Path | None,
    *,
    session_lock_held_fn: Callable[[str, Path | None], bool],
    read_json_fn: Callable[[Path], dict[str, Any] | None],
    live_max_age_s: float,
    incident_check_fn: Callable[[str], str | None] = check_arm_incident_hold,
) -> str | None:
    """For cell_ab moving jobs, ensure the peer arm is not active, held, or unfolded."""
    if arm not in ("arm_a", "arm_b"):
        return None
    peer = "arm_b" if arm == "arm_a" else "arm_a"
    if inc_err := incident_check_fn(peer):
        return f"peer {peer} incident hold: {inc_err}"
    import cell_arm_lease

    suffix = peer.split("_")[-1]
    io_dir = workdir / f"chunk-io-{suffix}"
    live = read_json_fn(io_dir / "live.json")
    lease_path = lease_dir / f"{peer}.json"
    lease = read_json_fn(lease_path)
    if live is not None:
        if live.get("chunk") is not None or live.get("human_hold_latched") or live.get("fault") or live.get("interrupt"):
            return f"peer {peer} is active or latched"
        if _live_folded(live) is False:
            return f"peer {peer} is not folded at home"
    elif (st_row := _latest_status_row(io_dir / "chunk-status.jsonl")) is not None and _live_folded(st_row) is False:
        return f"peer {peer} is not folded at home"
    peer_locked = bool(session_lock_held_fn(peer, lock_dir))
    peer_lease = True if (lease is None and lease_path.is_file()) else bool(lease and cell_arm_lease.live(lease))
    if peer_locked or peer_lease:
        if live is None or _live_folded(live) is not True:
            return f"peer {peer} has an active session or lease without confirmed folded state"
        ts = live.get("t")
        if isinstance(ts, bool) or not isinstance(ts, (int, float)) or not math.isfinite(float(ts)):
            return f"peer {peer} live fold timestamp missing or invalid"
        age = time.time() - float(ts)
        if age > live_max_age_s or age < -2.0:
            return f"peer {peer} live fold state is stale"
    return None


def check_two_arm_ab_ready(workdir: Path, lease_dir: Path, lock_dir: Path | None, **kw) -> str | None:
    """Ensure both arm_a and arm_b are idle and folded for D-1073 two-arm runs."""
    return check_peer_ab_folded("arm_b", workdir, lease_dir, lock_dir, **kw) or check_peer_ab_folded("arm_a", workdir, lease_dir, lock_dir, **kw)


def check_fleet_safety_online(
    arm: str | None,
    *,
    fleet_r_url: str | None = None,
    fleet_token_file: Path | None = None,
    ca_file: Path | None = None,
    timeout_s: float = 1.5,
) -> dict[str, Any]:
    """Query Fleet safety when online; fail open only when Fleet is unreachable, block on E-stop/human/ABORTED/errors."""
    if not arm or not fleet_r_url or not fleet_token_file:
        return {"online": False, "blocked": False, "reason": None}
    tpath = Path(fleet_token_file).expanduser()
    if not tpath.is_file():
        return {"online": False, "blocked": False, "reason": None}
    cpath = Path(ca_file).expanduser() if ca_file else None
    if cpath is not None and not cpath.is_file():
        return {"online": True, "blocked": True, "reason": "Fleet CA file missing"}
    base = fleet_r_url.rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme != "https" or not parsed.hostname:
        return {"online": True, "blocked": True, "reason": "invalid Fleet HTTPS URL"}
    try:
        token = tpath.read_text(encoding="utf-8").strip()
        ctx = ssl.create_default_context(cafile=str(cpath) if cpath else None)
        req = Request(f"{base}/api/fleet/pipeline/cell-tasks?status=QUEUED", headers={"Authorization": f"Bearer {token}"})
        with urlopen(req, context=ctx, timeout=timeout_s) as resp:
            listing = json.load(resp)
    except HTTPError as exc:
        return {"online": True, "blocked": True, "reason": f"Fleet HTTP {exc.code}"}
    except ssl.SSLError as exc:
        return {"online": True, "blocked": True, "reason": f"Fleet TLS error: {exc}"}
    except URLError as exc:
        if isinstance(exc.reason, ssl.SSLError):
            return {"online": True, "blocked": True, "reason": f"Fleet TLS error: {exc.reason}"}
        return {"online": False, "blocked": False, "reason": None}
    except (TimeoutError, OSError):
        return {"online": False, "blocked": False, "reason": None}
    except Exception as exc:
        return {"online": True, "blocked": True, "reason": f"Fleet safety payload error: {exc}"}
    if not isinstance(listing, dict) or not isinstance(listing.get("human_safety"), dict):
        return {"online": True, "blocked": True, "reason": "malformed Fleet human_safety payload"}
    safety = listing["human_safety"]
    if safety.get("active_estop") is not False:
        return {"online": True, "blocked": True, "reason": "Fleet active_estop is asserted"}
    detected = safety.get("human_detected")
    if not isinstance(detected, dict):
        return {"online": True, "blocked": True, "reason": "malformed Fleet human_detected payload"}
    cell_id = "cell_s" if arm == "arm_s" else "cell_ab"
    if detected.get("all") or detected.get(cell_id):
        return {"online": True, "blocked": True, "reason": f"Fleet human_detected active for {cell_id}"}
    cells = listing.get("cells")
    if cells is not None and not isinstance(cells, dict):
        return {"online": True, "blocked": True, "reason": "malformed Fleet cells payload"}
    cell = (cells or {}).get(cell_id)
    if isinstance(cell, dict) and (cell.get("phase") in ("ABORTED", "HUMAN_HOLD") or cell.get("prev_phase") == "ABORTED"):
        return {"online": True, "blocked": True, "reason": f"Fleet cell {cell_id} safety phase {cell.get('phase')}/{cell.get('prev_phase')}"}
    return {"online": True, "blocked": False, "reason": None}


def write_cell_state_dirty(
    workdir: Path,
    arm: str,
    *,
    job_id: str,
    job: str,
    start: float,
    end: float | None,
    exit_code: int | None,
    fleet_online: bool,
    principal: Principal,
) -> Path:
    """Atomically record cell-state dirty marker after offline/direct physical moves."""
    target = workdir / f"cell-state-dirty-{arm}.json"
    tmp = workdir / f".cell-state-dirty-{arm}.{os.getpid()}.tmp"
    payload = {
        "schema": "rosy.cell-state-dirty.v1",
        "arm_id": arm,
        "job_id": job_id,
        "job": job,
        "started_at": start,
        "ended_at": end,
        "exit_code": exit_code,
        "fleet_online": fleet_online,
        "principal_role": principal.role,
        "principal_id": principal.principal_id,
        "updated_at": time.time(),
    }
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, target)
    return target


class IdempotencyStore:
    """Bounded persistent `Idempotency-Key` map backed by `<workdir>/cell-job-api/idempotency.json`."""

    def __init__(self, path: Path, cap: int = 500):
        self.path = path
        self.cap = cap
        self._rows: dict[str, dict[str, Any]] = {}
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self._rows = loaded
            except (OSError, ValueError):
                pass

    @staticmethod
    def payload_sha256(job: str, params: dict[str, Any]) -> str:
        raw = json.dumps({"job": job, "params": params}, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def lookup(self, key: str, digest: str) -> tuple[str, str | None]:
        row = self._rows.get(key)
        if row is None:
            return "miss", None
        if row.get("digest") == digest:
            return "replay", str(row["job_id"])
        return "conflict", str(row["job_id"])

    def record(self, key: str, digest: str, job_id: str, job: str) -> None:
        self._rows[key] = {"digest": digest, "job_id": job_id, "job": job, "at": time.time()}
        if len(self._rows) > self.cap:
            oldest = sorted(self._rows.items(), key=lambda kv: float(kv[1].get("at", 0.0)))
            for k, _ in oldest[: len(self._rows) - self.cap]:
                self._rows.pop(k, None)
        tmp = self.path.with_name(f".idempotency.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(self._rows, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)


def tools_tree_name(workdir: Path) -> str | None:
    """Resolve active `omx-tools-*` release name from `<workdir>/tools-env-current.sh`."""
    env_file = workdir / "tools-env-current.sh"
    if not env_file.is_file():
        return None
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        code = line.split("#", 1)[0]
        if "omx-tools-" not in code:
            continue
        m = re.search(r"([^\s\"':;=]*omx-tools-[A-Za-z0-9_-]+)", code)
        if m:
            p = Path(os.path.expandvars(m.group(1))).expanduser()
            p = p if p.is_absolute() else workdir / p
            if p.is_symlink() or p.exists():
                try:
                    return p.resolve().name
                except (OSError, RuntimeError):
                    return p.name
            return p.name
    return None


def session_reuse_live_ok(
    arm: str,
    workdir: Path,
    lease_dir: Path,
    runs: dict[str, dict[str, Any]],
    *,
    lease_owner: str,
    live_max_age_s: float,
    read_json_fn: Callable[[Path], dict[str, Any] | None],
    pid_alive_fn: Callable[[int], bool],
) -> bool:
    """True only when runner owns warm idle arm session and live state is clean and fresh."""
    lease = read_json_fn(lease_dir / f"{arm}.json")
    if lease is None or lease.get("owner") != lease_owner or lease.get("hold"):
        return False
    if "pid" in lease:
        pid = lease["pid"]
        if isinstance(pid, bool) or not isinstance(pid, int) or not pid_alive_fn(pid):
            return False
    last_run = next((r for r in reversed(list(runs.values())) if r["moving"] and r["arm"] == arm), None)
    if last_run is None or last_run["proc"].poll() != 0:
        return False
    live = read_json_fn(workdir / f"chunk-io-{arm.split('_')[-1]}" / "live.json")
    if live is None or live.get("chunk") is not None or live.get("human_hold_latched") or live.get("fault") or live.get("interrupt"):
        return False
    if "t" in live:
        ts = live["t"]
        if isinstance(ts, bool) or not isinstance(ts, (int, float)) or not math.isfinite(float(ts)) or (time.time() - float(ts)) > live_max_age_s:
            return False
    return True


def read_token_file(path: Path) -> str:
    path = Path(path).expanduser()
    st = path.stat()
    if os.name != "nt" and st.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise SystemExit(f"{path}: readable by group or others; chmod 600 it")
    token = path.read_text(encoding="utf-8").strip()
    if len(token) < 24:
        raise SystemExit(f"{path}: token missing or shorter than 24 characters")
    return token


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_json_dict(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None
