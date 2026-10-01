#!/usr/bin/env python3
"""The robot-side auto-updater (D-406).

Runs from rosy-auto-update.timer as root. One ``run``:

1. stops if config.json says ``enabled: false``;
2. reads the GitHub Releases list with an ETag (a 304 reuses the cached list)
   and picks the highest ``payload-<id>`` above the current release that has
   its three assets, is not recorded as failed, and whose signed rollout.json
   verifies and is not withdrawn;
3. stages it (download to .part, sha256 against the rollout, the native unpack
   script, ``native_release.py verify``) even when the robot is busy; current
   is never moved by staging;
4. applies only when the rollout lets this host (canary, or ``canary_ok`` and
   the wave delay passed) and the robot is eligible: no hold, no sealed
   approval for the current release, CORE idle and still in two samples 10 s
   apart, battery >= 40 % or charging, no live /run/rosy-claim;
5. applies under the claim: activate, the core-release check, the new
   release's sync-image-layer.py, restarts, then health (CORE ready, core/io/
   camera active from the new release, no failed rosy-* unit, held 60 s);
6. on failure rolls back, syncs from the rolled-back release, and records the
   id as failed (never retried). status.json and history.jsonl record it all.

    rosy_auto_update.py run
    rosy_auto_update.py status [--json]
    rosy_auto_update.py hold --holder H --reason R --hours N     # 0 < N <= 168
    rosy_auto_update.py release-hold
    rosy_auto_update.py eligibility [--json]                       # read-only

Standard library only; signing.py and rosy_claim.py sit beside it on the device.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# The unit runs python3 -I (no script directory on sys.path): add it, and the
# repository's release tools as a fallback when run from a checkout.
sys.dont_write_bytecode = True
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
RELEASE_TOOLS = SCRIPT_DIR.parent / "release"
if RELEASE_TOOLS.is_dir() and str(RELEASE_TOOLS) not in sys.path:
    sys.path.append(str(RELEASE_TOOLS))

import rosy_claim  # noqa: E402
from signing import verify_signature  # noqa: E402


API_BASE = "https://api.github.com"
# config.json "api_base": another GitHub-compatible API (the device twin's fake
# GitHub). Content is still trusted only through the release key signatures.
API_BASE_URL = re.compile(r"^https?://[A-Za-z0-9.:\[\]-]+(/[A-Za-z0-9._~/-]*)?$")
USER_AGENT = "rosy-auto-update/1 (D-406)"
DEFAULT_REPO = "livsbittt/rosy-os"
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
RELEASE_ID = re.compile(r"^[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]{3}$")
TAG = re.compile(r"^payload-([0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]{3})$")
PHASES = ("idle", "staged", "waiting", "held", "ineligible", "applying", "committed",
          "rolled_back", "failed", "disabled", "error", "stuck")
# Re-review N3: the only native_release errors that say "this release can never work here".
DEFINITIVE = re.compile(
    r"^(NATIVE_MANIFEST_[A-Z_]+|NATIVE_TARGET_MISMATCH|NATIVE_RUNTIME_MISMATCH|NATIVE_PYTHON_RUNTIME"
    r"|SIGNATURE_(INVALID|MISSING|MALFORMED)|CHECKSUM_[A-Z_]+):"
    r"|candidate failed health check")
PRECHECK_REFUSED = "NATIVE_PRECHECK_REFUSED"  # only the precheck's busy exit; FAILED is transient
PRECHECK_BUSY_EXIT = 3
ESCALATED_REASON = ("repeated transient apply failures; operator action required: "
                    "rosy_auto_update.py release-hold (rosy-update-hold.ps1 -Release) after fixing the cause")
STUCK_REASON = ("CORE active but not writing status; operator action required: check rosy-core, "
                "or roll back with rosy-release-push.ps1 -Rollback")

# Device paths, relative to the root (tests pass a temporary one).
UPDATES = "var/lib/rosy/updates"
RELEASES = "opt/rosy/releases"
NATIVE_RUNTIME = "opt/rosy/native-runtime"
TRUSTED_KEY = "etc/rosy/trusted-release-keys/rosy-release-2026-01.pem"
APPROVALS = ("etc/rosy/approvals/hardware.approved", "etc/rosy/approvals/navigation.approved")
STATUS_INPUTS = "run/rosy/status-inputs.json"
RUNTIME_ENV = "etc/rosy/runtime.env"
NATIVE_JOURNAL = "var/lib/rosy/releases/native-activation.json"
RELEASE_SYNC = "deploy/robot/native/sync-image-layer.py"

# Status inputs (same reading rules as rosy-boot-status.py).
MAX_STATUS_INPUTS_BYTES = 16 * 1024
# Review M1: CORE rewrites the file every 10 s, so a sample older than 25 s means
# CORE missed two writes; 12 s between samples always spans a new write.
STATUS_INPUTS_FRESH_S = 25.0
SAMPLE_GAP_S = 12.0
REQUIRED_INPUTS = ("written_at", "robot_mode", "nav_state", "swarm_role", "velocity_linear",
                   "velocity_angular", "battery_percent", "battery_charging", "docking_state",
                   "line_follow_mode", "line_follow_state", "swarm_active", "estop", "activity_kind")
NOT_NULL_INPUTS = ("velocity_linear", "velocity_angular", "battery_percent", "line_follow_mode",
                   "line_follow_state", "swarm_active", "estop")
NAV_IDLE = frozenset({"IDLE", "ARRIVED", "CANCELED", "FAILED"})
# Review L2: allowlists. DockState (core_common schemas) and LineFollowStatus.state,
# which is "OFF" whenever the mode is OFF; anything else (or new) is not idle.
DOCKING_IDLE = frozenset({"UNDOCKED", "DOCKED", "CHARGING", None})
LINE_FOLLOW_IDLE = frozenset({"OFF"})
LINEAR_EPS = 0.01   # m/s
ANGULAR_EPS = 0.02  # rad/s
BATTERY_MIN = 40.0

MAX_HOLD_HOURS = 168.0
CLAIM_HOLDER = "rosy-auto-update"
# Review M8: longer than the unit's TimeoutStartSec=45min, and refreshed at every journal step.
CLAIM_TTL_S = 50 * 60
CORE_DOWN_NOTE = "core not running; idleness check waived"
HEALTH_UNITS = ("rosy-core.service", "rosy-io.service", "rosy-camera.service")
HEALTH_HOLD_S = 60.0
HEALTH_POLL_S = 5.0
SELF_UNIT = "rosy-auto-update.service"
UNIT_NAME = re.compile(r"^rosy-[A-Za-z0-9-]+\.(service|path|timer)$")

# Response size limits.
MAX_LIST_BYTES = 4 * 1024 * 1024
MAX_ROLLOUT_BYTES = 16 * 1024
MAX_SIG_BYTES = 1024
MAX_TARBALL_BYTES = 2 * 1024 * 1024 * 1024
HTTP_TIMEOUT_S = 20.0
DOWNLOAD_TIMEOUT_S = 60.0
BACKOFF_DEFAULT_S = 3600
BACKOFF_MIN_S = 60
BACKOFF_MAX_S = 6 * 3600
# Review M5: per-release staging errors back off; three definitive ones fail the id.
STAGE_BACKOFF_BASE_S = 600
STAGE_MAX_DEFINITIVE = 3
# Re-review N7, N12, N5, N6.
APPLY_MAX_TRANSIENT = 3
ROLLBACK_MAX_RETRIES = 5
STUCK_AFTER_S = 30 * 60
PRUNE_MIN_AGE_S = 3600
RELEASE_LOCK = "var/lib/rosy/releases/native-release.lock"
DISK_MARGIN_BYTES = 512 * 1024 * 1024
HISTORY_MAX_BYTES = 1024 * 1024

# Every subprocess is bounded (seconds).
UNPACK_TIMEOUT_S = 900
VERIFY_TIMEOUT_S = 600
ACTIVATE_TIMEOUT_S = 900
SYNC_TIMEOUT_S = 600
RESTART_TIMEOUT_S = 300
READY_TIMEOUT_S = 90
SYSTEMCTL_TIMEOUT_S = 30


class UpdateError(RuntimeError):
    """A refusal or failure with a reason for status.json; never a crash."""


class Definitive(UpdateError):
    """A problem that another attempt cannot change (signature, content, withdrawal)."""


class RunBusy(UpdateError):
    """Another run holds the run lock; this one writes nothing."""


class Deferred(UpdateError):
    """A resume must wait (the robot is not idle); the journal stays as it is."""


def _z(moment: _dt.datetime) -> str:
    return moment.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


parse_z = rosy_claim.parse_z


def _tail(text: str, limit: int = 300) -> str:
    text = " ".join((text or "").split())
    return text[-limit:]


def _last_json(text: str) -> dict | None:
    for line in reversed((text or "").strip().splitlines()):
        try:
            data = json.loads(line)
        except ValueError:
            continue
        return data if isinstance(data, dict) else None
    return None


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _finite(value: object) -> bool:
    try:
        return _number(value) and math.isfinite(value)
    except OverflowError:  # an int too large for a float
        return False


def _outcome(result: subprocess.CompletedProcess) -> tuple[str, str]:
    """("ok" | "busy" | "transient" | "definitive", error) for a native_release.py command.

    Only a JSON result naming an error is definitive. A timeout (124), a missing
    program (127) or output without a JSON result says nothing about the release.
    """
    data = _last_json(result.stdout)
    if result.returncode == 0 and data is not None and data.get("ok") is True:
        return "ok", ""
    error = data.get("error") if data is not None else None
    if result.returncode in (124, 127) or not isinstance(error, str) or not error:
        return "transient", _tail(result.stderr) or "no JSON result"
    if "NATIVE_RELEASE_BUSY" in error:
        return "busy", error
    if error.startswith(PRECHECK_REFUSED):
        return "refused", error
    return ("definitive" if DEFINITIVE.search(error) else "transient"), error


def _reason_class(reason: str) -> str:
    """The reason with its numbers blurred: '12 s old' and '73 s old' are one class."""
    return re.sub(r"[0-9]+", "#", reason or "")


# --- the device and the network ------------------------------------------------


class Host:
    """Everything outside the root's files: clock, commands, links, processes."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def now(self) -> _dt.datetime:
        return _dt.datetime.now(_dt.timezone.utc)

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def hostname(self) -> str:
        return socket.gethostname()

    def boot_id(self) -> str | None:
        return rosy_claim.boot_id(self.root)

    def current_release(self) -> str | None:
        link = self.root / "opt/rosy/current"
        try:
            name = Path(os.readlink(link)).name
        except OSError:
            return None
        return name if RELEASE_ID.fullmatch(name) else None

    def previous_release(self) -> str | None:
        try:
            name = Path(os.readlink(self.root / "opt/rosy/previous")).name
        except OSError:
            return None
        return name if RELEASE_ID.fullmatch(name) else None

    def free_bytes(self, path: Path) -> int:
        return shutil.disk_usage(path).free

    def process_cwd(self, pid: int) -> str | None:
        try:
            return os.readlink(self.root / "proc" / str(pid) / "cwd")
        except OSError:
            return None

    def run(self, argv: list[str], timeout: float) -> subprocess.CompletedProcess:
        """Run bounded; on timeout kill the whole process group, not just the child (review L6)."""
        posix = os.name == "posix"
        try:
            process = subprocess.Popen(
                argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                text=True, errors="replace", start_new_session=posix,
                creationflags=0 if posix else subprocess.CREATE_NEW_PROCESS_GROUP)
        except OSError as exc:
            return subprocess.CompletedProcess(argv, 127, "", f"cannot run {argv[0]}: {exc}")
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._kill_tree(process)
            try:
                stdout, stderr = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                stdout, stderr = "", ""
            return subprocess.CompletedProcess(argv, 124, stdout or "",
                                               f"{stderr or ''}\nTIMEOUT after {timeout:g}s")
        return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)

    @staticmethod
    def _kill_tree(process: subprocess.Popen) -> None:
        if os.name == "posix":
            import signal

            with contextlib.suppress(OSError):
                os.killpg(process.pid, signal.SIGKILL)
        else:
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)],
                               capture_output=True, timeout=10, check=False)
        with contextlib.suppress(OSError):
            process.kill()


class Http:
    """urllib with size limits; HTTP errors come back as a status, never raise."""

    def __init__(self, schemes: tuple[str, ...] = ("https",)) -> None:
        self.schemes = schemes

    def _open(self, url: str, headers: dict, timeout: float):
        if urllib.parse.urlsplit(url).scheme not in self.schemes:
            raise UpdateError(f"URL_REFUSED: {url}")
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})
        try:
            return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 - scheme checked above
        except urllib.error.HTTPError as exc:
            return exc
        except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
            raise UpdateError(f"NETWORK: {exc}") from exc

    def get(self, url: str, headers: dict, limit: int,
            timeout: float = HTTP_TIMEOUT_S) -> tuple[int, dict, bytes]:
        response = self._open(url, headers, timeout)
        try:
            with response:
                status = getattr(response, "status", None) or response.code
                body = response.read(limit + 1) if status == 200 else b""
                found = {key.lower(): value for key, value in response.headers.items()}
        except (OSError, http.client.HTTPException) as exc:
            raise UpdateError(f"NETWORK: {exc}") from exc
        if len(body) > limit:
            raise UpdateError(f"RESPONSE_TOO_LARGE: {url}")
        return status, found, body

    def download(self, url: str, destination: Path, limit: int,
                 timeout: float = DOWNLOAD_TIMEOUT_S) -> str:
        """Stream to ``destination``; return the sha256 of what was written."""
        response = self._open(url, {"Accept": "application/octet-stream"}, timeout)
        digest = hashlib.sha256()
        size = 0
        try:
            with response, destination.open("wb") as handle:
                status = getattr(response, "status", None) or response.code
                if status != 200:
                    raise UpdateError(f"DOWNLOAD_HTTP: {status} for {url}")
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > limit:
                        raise UpdateError(f"DOWNLOAD_TOO_LARGE: {url}")
                    digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
        except (OSError, http.client.HTTPException) as exc:
            raise UpdateError(f"NETWORK: {exc}") from exc
        return digest.hexdigest()


# --- files ------------------------------------------------------------------------


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o644)
    os.replace(temporary, path)


def _read_json(path: Path, limit: int = 1024 * 1024) -> object:
    """Parsed JSON, or raise ValueError/OSError. No symlink, regular file, bounded."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError(f"{path.name} is not a small regular file")
        raw = os.read(descriptor, limit + 1)
    finally:
        os.close(descriptor)
    return json.loads(raw.decode("utf-8"))


# --- the updater ----------------------------------------------------------------------


class Updater:
    def __init__(self, host: Host, *, api_base: str | None = None, http: Http | None = None) -> None:
        self.host = host
        self.root = host.root
        self._own_http = http is None
        self.http = http
        self._use_api_base(api_base or API_BASE)
        self.updates = self.root / UPDATES

    def _use_api_base(self, api_base: str) -> None:
        self.api_base = api_base.rstrip("/")
        # Plain http only when the API itself is (a local test server).
        if self._own_http:
            self.http = Http(("https", "http") if self.api_base.startswith("http://") else ("https",))

    # paths and commands -------------------------------------------------------

    def _dev(self, relative: str) -> str:
        return str(self.root / relative)

    def release_path(self, release_id: str) -> str:
        return str(self.root / RELEASES / release_id)

    def _native(self, name: str) -> str:
        return self._dev(f"{NATIVE_RUNTIME}/{name}")

    def _ready_command(self) -> list[str]:
        env = shlex.quote(self._dev(RUNTIME_ENV))
        probe = shlex.quote(self._native("wait-core-ready.py"))
        return ["bash", "-c", f"set -a; [ -f {env} ] && . {env}; set +a; exec python3 -B {probe}"]

    # records --------------------------------------------------------------------

    def _load_state(self) -> dict:
        try:
            data = _read_json(self.updates / "state.json")
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_state(self, state: dict) -> None:
        _write_json(self.updates / "state.json", state)

    def _history(self, event: str, release_id: str | None, detail: str) -> None:
        self.updates.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"at": _z(self.host.now()), "event": event, "release_id": release_id,
                           "detail": detail, "boot_id": self.host.boot_id()}, sort_keys=True)
        path = self.updates / "history.jsonl"
        # Review L4: one generation of history is kept beside the live file.
        with contextlib.suppress(OSError):
            if path.stat().st_size >= HISTORY_MAX_BYTES:
                os.replace(path, path.with_name("history.jsonl.1"))
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        with contextlib.suppress(OSError):
            os.chmod(path, 0o644)

    def _finish(self, state: dict, phase: str, reason: str, candidate: str | None = None) -> dict:
        """Write status.json; add a history line when the phase or its reason changed."""
        assert phase in PHASES, phase
        current = self.host.current_release()
        status = {
            "schema": 1, "updated_at": _z(self.host.now()), "hostname": self.host.hostname(),
            "current_release": current, "candidate": candidate, "phase": phase, "reason": reason,
            "last_result": state.get("last_result"),
        }
        signature = [phase, candidate, _reason_class(reason)]
        if state.get("last_status") != signature:
            self._history(phase, candidate, reason)
            state["last_status"] = signature
        self._save_state(state)
        _write_json(self.updates / "status.json", status)
        return status

    def _result(self, state: dict, release_id: str, outcome: str, detail: str) -> None:
        state["last_result"] = {"release_id": release_id, "outcome": outcome,
                                "at": _z(self.host.now()), "detail": detail}

    def _mark_failed(self, state: dict, release_id: str, detail: str) -> None:
        state.setdefault("failed", {})[release_id] = {"at": _z(self.host.now()), "detail": detail}
        if state.get("staged") == release_id:
            state["staged"] = None
        (state.get("stage_errors") or {}).pop(release_id, None)

    # config and hold ---------------------------------------------------------------

    def _config(self) -> dict:
        path = self.updates / "config.json"
        if not path.exists() and not path.is_symlink():
            return {"enabled": True, "repo": DEFAULT_REPO, "api_base": None}
        try:
            data = _read_json(path, 64 * 1024)
        except (OSError, ValueError) as exc:
            raise UpdateError(f"CONFIG_INVALID: {exc}") from exc
        if not isinstance(data, dict):
            raise UpdateError("CONFIG_INVALID: not an object")
        enabled = data.get("enabled", True)
        repo = data.get("repo", DEFAULT_REPO)
        if not isinstance(enabled, bool) or not isinstance(repo, str) or not REPO.fullmatch(repo):
            raise UpdateError("CONFIG_INVALID: enabled must be a bool and repo owner/name")
        api_base = data.get("api_base")
        if api_base is not None and not (isinstance(api_base, str) and API_BASE_URL.fullmatch(api_base)):
            raise UpdateError("CONFIG_INVALID: api_base must be an http(s)://host[:port][/path] URL")
        return {"enabled": enabled, "repo": repo, "api_base": api_base}

    def _hold(self) -> tuple[str, str]:
        """("none" | "active" | "expired" | "invalid", detail). Read-only."""
        path = self.updates / "hold.json"
        if not path.exists() and not path.is_symlink():
            return "none", ""
        try:
            data = _read_json(path, 64 * 1024)
        except (OSError, ValueError) as exc:
            return "invalid", f"hold.json unreadable ({exc}); release it with release-hold"
        created = parse_z(data.get("created_at")) if isinstance(data, dict) else None
        expires = parse_z(data.get("expires_at")) if isinstance(data, dict) else None
        if (created is None or expires is None or not expires > created
                or (expires - created) > _dt.timedelta(hours=MAX_HOLD_HOURS)):
            return "invalid", "hold.json has no valid expires_at within 7 days; release it with release-hold"
        detail = f"hold by {data.get('holder')}: {data.get('reason')} (until {_z(expires)})"
        if self.host.now() >= expires:
            return "expired", detail
        return "active", detail

    def hold(self, holder: str, reason: str, hours: float) -> dict:
        if not _number(hours) or not 0 < hours <= MAX_HOLD_HOURS:
            raise UpdateError(f"HOLD_HOURS_INVALID: hours must be in (0, {MAX_HOLD_HOURS:g}]")
        for name, value in (("holder", holder), ("reason", reason)):
            if not isinstance(value, str) or not value.strip() or len(value) > 200 \
                    or re.search(r"[\x00-\x1f\x7f]", value):
                raise UpdateError(f"HOLD_{name.upper()}_INVALID: 1-200 printable characters")
        now = self.host.now()
        payload = {"holder": holder, "reason": reason, "created_at": _z(now),
                   "expires_at": _z(now + _dt.timedelta(hours=hours))}
        _write_json(self.updates / "hold.json", payload)
        self._history("hold_set", None, f"{holder}: {reason} until {payload['expires_at']}")
        return payload

    def release_hold(self) -> bool:
        path = self.updates / "hold.json"
        existed = path.exists() or path.is_symlink()
        path.unlink(missing_ok=True)
        state = self._load_state()
        if state.get("apply_errors"):
            state["apply_errors"] = {}
            self._save_state(state)
        self._history("hold_released", None, "hold removed" if existed else "no hold was set")
        return existed

    def _expire_hold(self) -> None:
        kind, detail = self._hold()
        if kind == "expired":
            (self.updates / "hold.json").unlink(missing_ok=True)
            self._history("hold_expired", None, detail)

    # eligibility ---------------------------------------------------------------------

    def _sealed(self, current: str | None) -> list[str]:
        # Review M6: a marker that exists but cannot be read as {"release_id": str}
        # might be a seal; it holds like one.
        reasons = []
        for marker in APPROVALS:
            path = self.root / marker
            name = Path(marker).name
            if path.is_symlink():
                reasons.append(f"approval marker {name} is a symlink")
                continue
            if not path.exists():
                continue
            try:
                data = _read_json(path, 64 * 1024)
            except (OSError, ValueError):
                reasons.append(f"approval marker {name} is unreadable or oversize")
                continue
            if not isinstance(data, dict) or not isinstance(data.get("release_id"), str):
                reasons.append(f"approval marker {name} is corrupt")
            elif current is not None and data["release_id"] == current:
                reasons.append(f"sealed approval {name} names the current release {current}")
        return reasons

    def _inputs_problems(self) -> list[str]:
        return self._sample()[0]

    def _sample(self) -> tuple[list[str], _dt.datetime | None]:
        """(problems, written_at) for one read of status-inputs.json."""
        try:
            data = _read_json(self.root / STATUS_INPUTS, MAX_STATUS_INPUTS_BYTES)
        except (OSError, ValueError, UnicodeDecodeError):
            return ["status-inputs.json missing, unreadable or over 16 KiB"], None
        problems = self._judge_inputs(data)
        return problems, (parse_z(data["written_at"]) if not problems else None)

    def _judge_inputs(self, data: object) -> list[str]:
        if not isinstance(data, dict):
            return ["status-inputs.json is not an object"]
        schema = data.get("schema")
        if not isinstance(schema, int) or isinstance(schema, bool) or schema < 2:
            return [f"status-inputs schema {schema!r} is not >= 2"]
        missing = [key for key in REQUIRED_INPUTS if key not in data]
        if missing:
            return [f"status-inputs lacks {', '.join(missing)}"]
        written = parse_z(data["written_at"])
        if written is None:
            return ["status-inputs written_at is invalid"]
        age = (self.host.now() - written).total_seconds()
        if not -5.0 <= age <= STATUS_INPUTS_FRESH_S:
            return [f"status-inputs is stale ({age:.0f} s old)"]
        # Contract amendment (b63cb7f2): an added key may be null, null is unknown and
        # unknown is ineligible, decided before any value is interpreted. A null
        # battery_percent blocks even while charging. docking_state and activity_kind
        # are typed "null or string": there null means none, as before.
        unknown = [key for key in NOT_NULL_INPUTS
                   if data[key] is None or (isinstance(data[key], float) and not math.isfinite(data[key]))]
        if unknown:
            return [f"status-inputs does not know {', '.join(unknown)}"]
        problems = []
        if data["swarm_role"] not in (None, "none"):
            problems.append(f"swarm role is {data['swarm_role']}")
        if data["robot_mode"] != "IDLE":
            problems.append(f"robot mode is {data['robot_mode']}")
        if data["nav_state"] not in NAV_IDLE:
            problems.append(f"navigation is {data['nav_state']}")
        if data["line_follow_mode"] != "OFF":
            problems.append(f"line follow is {data['line_follow_mode']}")
        if data["line_follow_state"] not in LINE_FOLLOW_IDLE:
            problems.append(f"line follow state is {data['line_follow_state']}")
        if data["docking_state"] not in DOCKING_IDLE:
            problems.append(f"docking is {data['docking_state']}")
        if data["swarm_active"] is not False:
            problems.append("swarm is active")
        if data["estop"] is not False:
            problems.append("E-stop is engaged")
        if data["activity_kind"] is not None:
            problems.append(f"activity {data['activity_kind']} is running")
        linear, angular = data["velocity_linear"], data["velocity_angular"]
        # Finite numbers inside the band, written so a NaN can never pass.
        if not (_finite(linear) and _finite(angular) and abs(linear) < LINEAR_EPS and abs(angular) < ANGULAR_EPS):
            problems.append(f"robot is moving or its velocity is invalid (v={linear!r}, w={angular!r})")
        percent, charging = data["battery_percent"], data["battery_charging"]
        if not _finite(percent):
            problems.append(f"battery percent {percent!r} is invalid")
        elif charging is not True and not percent >= BATTERY_MIN:
            problems.append(f"battery {percent!r}% is below {BATTERY_MIN:g}% and not charging")
        return problems

    def precheck(self) -> list[str]:
        """What native_release runs right before it stops the runtime: hold, seal, one fresh sample."""
        reasons = []
        kind, detail = self._hold()
        if kind in {"active", "invalid"}:
            reasons.append(detail)
        reasons += self._sealed(self.host.current_release())
        claim = rosy_claim.check(self.root, now=self.host.now())
        if claim is not None and claim.get("holder") != CLAIM_HOLDER:
            reasons.append(f"claim held by {claim.get('holder')}")
        return reasons + self._inputs_problems()

    def eligibility(self, *, own_claim_ok: bool = False, waive_inputs: bool = False) -> dict:
        """Read-only: may this robot apply now? Two status samples, two different writes."""
        current = self.host.current_release()
        reasons: list[str] = []
        kind, detail = self._hold()
        if kind in {"active", "invalid"}:
            reasons.append(detail)
        reasons += self._sealed(current)
        held = bool(reasons)
        claim = rosy_claim.check(self.root, now=self.host.now())
        if claim is not None and not (own_claim_ok and claim.get("holder") == CLAIM_HOLDER):
            reasons.append(f"claim held by {claim.get('holder')} ({claim.get('purpose')})")
        if not held and not waive_inputs:
            problems, first = self._sample()
            if not problems:
                self.host.sleep(SAMPLE_GAP_S)
                problems, second = self._sample()
                problems = [f"second sample: {item}" for item in problems]
                if not problems and not (second is not None and first is not None and second > first):
                    problems = ["second sample: status-inputs was not rewritten (CORE is not updating it)"]
            reasons += problems
        return {"eligible": not reasons, "held": held, "reasons": reasons,
                "current_release": current, "checked_at": _z(self.host.now())}

    # GitHub --------------------------------------------------------------------------

    def _backoff(self, state: dict, headers: dict) -> _dt.datetime:
        now = self.host.now()
        delay = BACKOFF_DEFAULT_S
        retry = headers.get("retry-after", "")
        reset = headers.get("x-ratelimit-reset", "")
        if retry.isdigit():
            delay = int(retry)
        elif reset.isdigit() and headers.get("x-ratelimit-remaining") == "0":
            delay = int(reset) - int(now.timestamp())
        until = now + _dt.timedelta(seconds=min(max(delay, BACKOFF_MIN_S), BACKOFF_MAX_S))
        state["backoff_until"] = _z(until)
        return until

    def _releases(self, state: dict, repo: str) -> list[dict]:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if state.get("etag") and isinstance(state.get("releases"), list):
            headers["If-None-Match"] = state["etag"]
        status, found, body = self.http.get(
            f"{self.api_base}/repos/{repo}/releases?per_page=20", headers, MAX_LIST_BYTES)
        if status == 304:
            return state["releases"]
        if status in (403, 429):
            until = self._backoff(state, found)
            raise UpdateError(f"GITHUB_RATE_LIMITED: HTTP {status}; backing off until {_z(until)}")
        if status != 200:
            raise UpdateError(f"GITHUB_HTTP: HTTP {status}")
        try:
            listed = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise UpdateError("GITHUB_RESPONSE: not JSON") from exc
        if not isinstance(listed, list):
            raise UpdateError("GITHUB_RESPONSE: not a list")
        releases = []
        for item in listed:
            if not isinstance(item, dict) or item.get("draft") is not False or item.get("prerelease") is not False:
                continue
            match = TAG.fullmatch(str(item.get("tag_name", "")))
            if not match:
                continue
            release_id = match.group(1)
            urls = {asset.get("name"): asset.get("browser_download_url")
                    for asset in item.get("assets") or [] if isinstance(asset, dict)}
            wanted = {"tarball": f"{release_id}.tar.gz", "rollout": "rollout.json", "sig": "rollout.json.sig"}
            if not all(isinstance(urls.get(name), str) for name in wanted.values()):
                continue
            size = next((asset.get("size") for asset in item.get("assets") or []
                         if isinstance(asset, dict) and asset.get("name") == wanted["tarball"]), None)
            releases.append({"release_id": release_id, **{key: urls[name] for key, name in wanted.items()},
                             "size": size if _number(size) and size >= 0 else None})
        state["etag"] = found.get("etag")
        state["releases"] = releases
        return releases

    def _rollout(self, release: dict) -> dict:
        release_id = release["release_id"]
        status, _found, raw = self.http.get(release["rollout"], {"Accept": "application/octet-stream"},
                                            MAX_ROLLOUT_BYTES)
        sig_status, _found, signature = self.http.get(release["sig"], {"Accept": "application/octet-stream"},
                                                      MAX_SIG_BYTES)
        if status != 200 or sig_status != 200:
            raise UpdateError(f"ROLLOUT_HTTP: rollout {status}, signature {sig_status}")
        try:
            text = signature.decode("ascii")
        except UnicodeDecodeError as exc:
            raise Definitive("ROLLOUT_SIGNATURE: not ASCII") from exc
        rejections = verify_signature(raw, text, self.root / TRUSTED_KEY)
        if rejections:
            raise Definitive(f"ROLLOUT_SIGNATURE: {rejections[0].code}")
        try:
            rollout = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise Definitive("ROLLOUT_INVALID: not JSON") from exc
        if not isinstance(rollout, dict) or rollout.get("schema") != 1:
            raise Definitive("ROLLOUT_INVALID: schema 1 object required")
        canary = rollout.get("canary")
        checks = (
            rollout.get("release_id") == release_id,
            rollout.get("tarball") == f"{release_id}.tar.gz",
            isinstance(rollout.get("tarball_sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", rollout["tarball_sha256"]) is not None,
            parse_z(rollout.get("published_at")) is not None,
            isinstance(canary, list) and all(isinstance(name, str) for name in canary),
            isinstance(rollout.get("canary_ok"), bool),
            isinstance(rollout.get("withdrawn"), bool),
            isinstance(rollout.get("wave_delay_s"), int) and not isinstance(rollout.get("wave_delay_s"), bool)
            and rollout["wave_delay_s"] >= 0,
        )
        if not all(checks):
            raise Definitive("ROLLOUT_INVALID: fields do not match the contract or this release")
        return rollout

    # staging --------------------------------------------------------------------------

    def _stage(self, state: dict, release: dict, rollout: dict) -> None:
        """Stage with per-release backoff; three definitive failures fail the id (review M5)."""
        release_id = release["release_id"]
        if state.get("staged") == release_id and Path(self.release_path(release_id)).is_dir():
            return
        errors = state.setdefault("stage_errors", {})
        record = errors.get(release_id)
        retry = parse_z((record or {}).get("retry_after"))
        if retry is not None and self.host.now() < retry:
            raise UpdateError(f"STAGE_BACKOFF: {release_id} last failed ({record.get('last')}); "
                              f"next attempt after {_z(retry)}")
        try:
            self._stage_once(state, release, rollout)
        except UpdateError as exc:
            if release_id not in (state.get("failed") or {}):
                self._stage_error(state, release_id, str(exc), isinstance(exc, Definitive))
            raise
        errors.pop(release_id, None)
        state["staged"] = release_id
        self._save_state(state)
        self._history("staged", release_id, "downloaded, unpacked and verified")

    def _stage_error(self, state: dict, release_id: str, message: str, definitive: bool) -> None:
        record = state.setdefault("stage_errors", {}).setdefault(release_id, {"attempts": 0, "definitive": 0})
        record["attempts"] += 1
        record["definitive"] += int(definitive)
        record["last"] = message
        delay = min(STAGE_BACKOFF_BASE_S * 2 ** (record["attempts"] - 1), BACKOFF_MAX_S)
        record["retry_after"] = _z(self.host.now() + _dt.timedelta(seconds=delay))
        if record["definitive"] >= STAGE_MAX_DEFINITIVE:
            self._mark_failed(state, release_id, f"staging failed {STAGE_MAX_DEFINITIVE} times: {message}")

    def _clean_downloads(self) -> Path:
        downloads = self.updates / "downloads"
        try:
            downloads.mkdir(parents=True, exist_ok=True)
            for leftover in downloads.iterdir():
                if leftover.is_dir() and not leftover.is_symlink():
                    shutil.rmtree(leftover)
                else:
                    leftover.unlink()
        except OSError as exc:
            raise UpdateError(f"DOWNLOADS_UNCLEAN: cannot clear {downloads}: {exc}") from exc
        return downloads

    def _stage_once(self, state: dict, release: dict, rollout: dict) -> None:
        release_id = release["release_id"]
        if not Path(self.release_path(release_id)).is_dir():
            size = release.get("size") or 0
            need = 2 * size + DISK_MARGIN_BYTES
            free = self.host.free_bytes(self.root / RELEASES)
            if free < need:
                raise UpdateError(f"DISK_LOW: {free} bytes free, {need} needed for {release_id}")
            downloads = self._clean_downloads()
            part = downloads / f"{release_id}.tar.gz.part"
            tarball = downloads / f"{release_id}.tar.gz"
            try:
                digest = self.http.download(release["tarball"], part, MAX_TARBALL_BYTES)
            except UpdateError:
                part.unlink(missing_ok=True)
                raise
            if digest != rollout["tarball_sha256"]:
                part.unlink(missing_ok=True)
                raise Definitive(f"TARBALL_SHA256_MISMATCH: {release_id} got {digest}")
            os.replace(part, tarball)
            unpacked = self.host.run(["bash", self._native("rosy-release-unpack.sh"), release_id,
                                      str(tarball), self._dev(RELEASES)], UNPACK_TIMEOUT_S)
            tarball.unlink(missing_ok=True)  # the script removes it on success
            if unpacked.returncode != 0:
                error = f"UNPACK_FAILED: {_tail(unpacked.stderr or unpacked.stdout)}"
                raise UpdateError(error) if unpacked.returncode in (124, 127) else Definitive(error)
        verified = self.host.run(["python3", "-B", self._native("native_release.py"), "--root", str(self.root),
                                  "--public-key", self._dev(TRUSTED_KEY), "verify", "--release-id", release_id],
                                 VERIFY_TIMEOUT_S)
        kind, error = _outcome(verified)
        if kind == "definitive":
            # Review H3: only a JSON verdict from the verifier fails the release.
            self._mark_failed(state, release_id, f"verify: {error}")
            raise UpdateError(f"VERIFY_FAILED: {release_id}: {error}")
        if kind != "ok":
            raise UpdateError(f"VERIFY_TRANSIENT: {release_id}: {error}")

    def _gate(self, rollout: dict) -> str | None:
        if self.host.hostname() in rollout["canary"]:
            return None
        if not rollout["canary_ok"]:
            return "waiting for the canary (canary_ok is false)"
        due = parse_z(rollout["published_at"]) + _dt.timedelta(seconds=rollout["wave_delay_s"])
        if self.host.now() < due:
            return f"wave delay until {_z(due)}"
        return None

    # apply --------------------------------------------------------------------------

    def _systemctl(self, *args: str, timeout: float = SYSTEMCTL_TIMEOUT_S) -> subprocess.CompletedProcess:
        return self.host.run(["systemctl", *args], timeout)

    def _main_pid(self, unit: str) -> int:
        shown = self._systemctl("show", "-p", "MainPID", "--value", unit)
        text = shown.stdout.strip()
        return int(text) if shown.returncode == 0 and text.isdigit() else 0

    def _core_release_check(self) -> None:
        """CORE's main process must run from current, else restart rosy-core (push parity)."""
        current = self.host.current_release()
        pid = self._main_pid("rosy-core.service")
        if pid and current and self.host.process_cwd(pid) == self.release_path(current):
            return
        restarted = self._systemctl("restart", "rosy-core.service", timeout=RESTART_TIMEOUT_S)
        if restarted.returncode != 0:
            raise UpdateError(f"CORE_RESTART_FAILED: {_tail(restarted.stderr)}")

    def _sync(self, script: str) -> dict:
        synced = self.host.run(["python3", "-B", script], SYNC_TIMEOUT_S)
        result = _last_json(synced.stdout)
        if synced.returncode != 0 or not result or result.get("ok") is not True:
            raise UpdateError(f"IMAGE_LAYER_SYNC_FAILED: {_tail(synced.stderr or synced.stdout)}")
        return result

    def _restart(self, sync_result: dict) -> list[str]:
        # Never restart this unit: it is the process running the update.
        units = [unit for unit in sync_result.get("restart_units") or []
                 if isinstance(unit, str) and UNIT_NAME.fullmatch(unit) and unit != SELF_UNIT]
        if units:
            restarted = self._systemctl("restart", *units, timeout=RESTART_TIMEOUT_S)
            if restarted.returncode != 0:
                raise UpdateError(f"RESTART_FAILED: {' '.join(units)}: {_tail(restarted.stderr)}")
        return units

    def _ready(self) -> None:
        ready = self.host.run(self._ready_command(), READY_TIMEOUT_S)
        if ready.returncode != 0:
            raise UpdateError(f"CORE_NOT_READY: {_tail(ready.stderr)}")

    def _failed_units(self) -> list[str] | None:
        """Failed rosy-* units (never this one), or None when systemctl cannot say."""
        listed = self._systemctl("list-units", "--state=failed", "--plain", "--no-legend", "--all", "rosy-*")
        if listed.returncode != 0:
            return None
        failed = [line.split()[0] for line in listed.stdout.splitlines() if line.split()]
        return sorted(unit for unit in failed if unit != SELF_UNIT)

    def _baseline(self) -> dict:
        """Which health units ran (and from where) and which rosy-* units had failed, before activation."""
        active = {}
        for unit in HEALTH_UNITS:
            if self._systemctl("is-active", "--quiet", unit).returncode == 0:
                pid = self._main_pid(unit)
                active[unit] = self.host.process_cwd(pid) if pid else None
        return {"active": active, "failed": self._failed_units() or []}

    @staticmethod
    def _baseline_notes(baseline: dict) -> list[str]:
        notes = [f"{unit} was not active before the apply; not checked"
                 for unit in HEALTH_UNITS[1:] if unit not in baseline.get("active", {})]
        if baseline.get("failed"):
            notes.append(f"already failed before the apply: {' '.join(baseline['failed'])}")
        return notes

    def _unit_problems(self, release_id: str, baseline: dict) -> list[str]:
        """rosy-core always; io/camera only if they ran before; only newly failed units count."""
        problems = []
        want = self.release_path(release_id)
        required = [unit for unit in HEALTH_UNITS
                    if unit == "rosy-core.service" or unit in baseline.get("active", {})]
        for unit in required:
            if self._systemctl("is-active", "--quiet", unit).returncode != 0:
                problems.append(f"{unit} is not active")
                continue
            pid = self._main_pid(unit)
            cwd = self.host.process_cwd(pid) if pid else None
            if cwd != want:
                problems.append(f"{unit} runs from {cwd}, not {want}")
        failed = self._failed_units()
        if failed is None:
            problems.append("cannot list failed units")
        else:
            new = [unit for unit in failed if unit not in baseline.get("failed", [])]
            if new:
                problems.append(f"failed units: {' '.join(new)}")
        return problems

    def _health(self, release_id: str, baseline: dict) -> None:
        self._ready()
        deadline = self.host.now() + _dt.timedelta(seconds=HEALTH_HOLD_S)
        while True:
            problems = self._unit_problems(release_id, baseline)
            if problems:
                raise UpdateError(f"HEALTH: {'; '.join(problems)}")
            if self.host.now() >= deadline:
                return
            self.host.sleep(HEALTH_POLL_S)

    def _journal(self, state: dict, step: str) -> None:
        """Record the step before doing it, and keep the claim alive for the next one (review M8)."""
        state["applying"]["step"] = step
        self._save_state(state)
        with contextlib.suppress(OSError, ValueError, rosy_claim.ClaimBusy):
            rosy_claim.refresh(self.root, CLAIM_HOLDER, CLAIM_TTL_S, now=self.host.now())

    def _settle(self, state: dict, release_id: str) -> dict:
        """Everything after activation; commit, or roll back on any failure."""
        # A journal without a baseline (none is written that way) checks CORE only.
        baseline = state["applying"].get("baseline") or {"active": {}, "failed": []}
        notes = self._baseline_notes(baseline) + ([state["applying"]["note"]] if state["applying"].get("note") else [])
        try:
            self._journal(state, "core-release-check")
            self._recheck_waived(state)
            self._core_release_check()
            self._journal(state, "image-layer-sync")
            result = self._sync(str(Path(self.release_path(release_id)) / RELEASE_SYNC))
            self._journal(state, "restart")
            self._recheck_waived(state)
            self._restart(result)
            self._journal(state, "health")
            self._health(release_id, baseline)
        except Deferred as exc:
            return self._finish(state, "ineligible", f"finishing {release_id} deferred: {exc}", release_id)
        except UpdateError as exc:
            return self._roll_back(state, release_id, "; ".join([str(exc), *notes]))
        except Exception as exc:  # noqa: BLE001 - a bug after activation must still roll back
            return self._roll_back(state, release_id, "; ".join([f"UNEXPECTED: {exc!r}", *notes]))
        state["applying"] = None
        state["staged"] = None
        (state.get("apply_errors") or {}).pop(release_id, None)
        (state.get("self_rolled_back") or {}).pop(release_id, None)
        committed = [item for item in state.get("committed") or [] if item != release_id]
        state["committed"] = (committed + [release_id])[-20:]
        self._result(state, release_id, "committed", "; ".join(["healthy for 60 s", *notes]))
        self._prune(state)
        return self._finish(state, "committed", f"{release_id} is healthy", release_id)

    def _recheck_waived(self, state: dict) -> None:
        """Re-review N4: a waived resume whose CORE is back needs the normal idleness check."""
        if state["applying"].get("note") != CORE_DOWN_NOTE or self._core_down():
            return
        report = self.eligibility(own_claim_ok=True)
        if not report["eligible"]:
            raise Deferred("; ".join(report["reasons"]))
        state["applying"].pop("note", None)

    def _rollback_tail(self, release_id: str) -> list[str]:
        """Bring the image layer and CORE back to whatever release is current now."""
        # The release now current may predate D-388; fall back to the copy in the
        # release rolled away from (it syncs from current all the same).
        current = self.host.current_release() or ""
        script = Path(self.release_path(current)) / RELEASE_SYNC
        if not script.is_file():
            script = Path(self.release_path(release_id)) / RELEASE_SYNC
        problems = []
        for step in (lambda: self._restart(self._sync(str(script))), self._core_release_check, self._ready):
            try:
                step()
            except UpdateError as exc:
                problems.append(str(exc))
            except Exception as exc:  # noqa: BLE001 - finish the other steps
                problems.append(f"UNEXPECTED: {exc!r}")
        return problems

    def _roll_back(self, state: dict, release_id: str, why: str, mark_failed: bool = True) -> dict:
        """Roll back. A rollback that cannot run now stays journaled and is retried (review M7)."""
        applying = state["applying"]
        first = applying.get("step") != "rollback"
        applying.update(why=why, mark_failed=mark_failed)
        self._journal(state, "rollback")
        if first:
            self._history("rollback_started", release_id, why)
        if mark_failed:
            self._mark_failed(state, release_id, why)  # recorded now: never retried, even mid-rollback
        problems = []
        gave_up = False
        if self.host.current_release() == release_id:
            rolled = self.host.run(["bash", self._native("rollback-release.sh")], ACTIVATE_TIMEOUT_S)
            kind, error = _outcome(rolled)
            if kind != "ok":
                self._recover_native()  # re-review N8: a dead rollback may leave the journal too
            if kind in ("busy", "transient", "refused"):
                applying["rollback_attempts"] = applying.get("rollback_attempts", 0) + 1
                if applying["rollback_attempts"] <= ROLLBACK_MAX_RETRIES:  # the first try + 5 retries
                    self._save_state(state)
                    return self._finish(state, "error", f"ROLLBACK_PENDING: {error}; retrying on the next run",
                                        release_id)
                # Re-review N12: stop retrying and ask a person.
                gave_up = True
                problems.append(f"rollback could not run after {ROLLBACK_MAX_RETRIES} retries ({error}); operator "
                                "action required: rosy-release-push.ps1 -Rollback")
            elif kind == "definitive":
                problems.append(f"rollback: {error}")
        if not problems:
            problems = self._rollback_tail(release_id)
        if not mark_failed:
            # Verification review HIGH: our own rollback leaves previous above current;
            # that is not an operator rollback (N9) and the release stays retryable (N7).
            state.setdefault("self_rolled_back", {})[release_id] = _z(self.host.now())
            if not problems:
                self._apply_error(state, release_id, why)
        note = applying.get("note")
        state["applying"] = None
        detail = why if not problems else f"{why}; rollback incomplete: {'; '.join(problems)}"
        if note and note not in detail:
            detail = f"{detail}; {note}"
        self._result(state, release_id, "rollback_failed" if gave_up else "rolled_back", detail)
        self._prune(state)
        return self._finish(state, "rolled_back" if not problems else "failed", detail, release_id)

    def _recover_native(self) -> None:
        """An activation that died mid-way left native_release's journal: recover, restart the runtime."""
        if not (self.root / NATIVE_JOURNAL).exists():
            return
        recovered = self.host.run(["python3", "-B", self._native("native_release.py"), "--root", str(self.root),
                                   "--public-key", self._dev(TRUSTED_KEY), "recover"], ACTIVATE_TIMEOUT_S)
        kind, error = _outcome(recovered)
        if kind != "ok":
            self._history("native_recover_failed", None, error)
            return
        started = self._systemctl("start", "rosy-runtime.target", timeout=RESTART_TIMEOUT_S)
        self._history("native_recovered", None, f"runtime start exit {started.returncode}")

    def _release_claim(self) -> None:
        try:
            rosy_claim.release(self.root, CLAIM_HOLDER)
        except (rosy_claim.ClaimBusy, OSError) as exc:
            self._history("claim_release_failed", None, str(exc))

    def _apply_error(self, state: dict, release_id: str, message: str) -> None:
        """Re-review N7: transient apply failures back off like staging errors."""
        record = state.setdefault("apply_errors", {}).setdefault(release_id, {"attempts": 0})
        record["attempts"] += 1
        record["last"] = message
        delay = min(STAGE_BACKOFF_BASE_S * 2 ** (record["attempts"] - 1), BACKOFF_MAX_S)
        record["retry_after"] = _z(self.host.now() + _dt.timedelta(seconds=delay))

    def _prune(self, state: dict) -> None:
        """Keep current, previous and the staged release; drop every other release directory (review M5)."""
        current = self.host.current_release()
        if current is None:
            return
        keep = {current, self.host.previous_release(), state.get("staged")} - {None}
        pruned = []
        try:
            with self._locked_file(self.root / RELEASE_LOCK):
                cutoff = self.host.now().timestamp() - PRUNE_MIN_AGE_S
                for path in sorted((self.root / RELEASES).iterdir()):
                    if (path.name in keep or not RELEASE_ID.fullmatch(path.name) or path.is_symlink()
                            or not path.is_dir() or path.stat().st_mtime > cutoff):
                        continue
                    shutil.rmtree(path, ignore_errors=True)
                    pruned.append(path.name)
        except OSError:
            return  # native_release is busy: prune next time
        if pruned:
            self._history("pruned", None, " ".join(pruned))

    def apply(self, release_id: str, state: dict) -> dict:
        """Activate ``release_id`` under the claim. Refuses anything not newer than current."""
        current = self.host.current_release()
        if current is None or not RELEASE_ID.fullmatch(release_id) or not release_id > current:
            raise UpdateError(f"NOT_NEWER: {release_id} is not above the current release {current}")
        try:
            rosy_claim.acquire(self.root, CLAIM_HOLDER, f"auto-update to {release_id}", CLAIM_TTL_S,
                               now=self.host.now())
        except rosy_claim.ClaimBusy as exc:
            holder = (exc.claim or {}).get("holder")
            return self._finish(state, "ineligible", f"claim held by {holder}", release_id)
        try:
            state["applying"] = {"release_id": release_id, "previous": current, "step": "activate",
                                 "started_at": _z(self.host.now()), "boot_id": self.host.boot_id(),
                                 "baseline": self._baseline()}
            # Review M2: one more look right before anything stops. What is left is the
            # moment between this read and the activator stopping the runtime (ADR R4).
            busy = self._inputs_problems()
            if busy:
                state["applying"] = None
                return self._finish(state, "ineligible", f"robot became busy: {'; '.join(busy)}", release_id)
            self._save_state(state)
            self._finish(state, "applying", f"activating {release_id} (from {current})", release_id)
            # Re-review N1: native_release runs our precheck after its verify and right
            # before it stops the runtime, so hold/seal/idleness are judged at that moment.
            precheck = f"python3 -B {shlex.quote(self._native('rosy_auto_update.py'))} --root " \
                       f"{shlex.quote(str(self.root))} precheck"
            activated = self.host.run(["env", f"ROSY_ACTIVATE_PRECHECK={precheck}", "bash",
                                       self._native("activate-release.sh"), release_id], ACTIVATE_TIMEOUT_S)
            kind, error = _outcome(activated)
            if kind == "ok":
                return self._settle(state, release_id)
            if kind == "busy":
                state["applying"] = None
                return self._finish(state, "waiting", f"{error}; retrying on the next run", release_id)
            if kind == "refused":
                state["applying"] = None
                return self._finish(state, "ineligible", f"robot became busy: {error}", release_id)
            # Review H3: a dead activation may have left native_release's journal.
            self._recover_native()
            definitive = kind == "definitive"
            if self.host.current_release() == release_id:
                return self._roll_back(state, release_id, f"activation: {error}", mark_failed=definitive)
            state["applying"] = None
            if not definitive:
                self._apply_error(state, release_id, f"activation: {error}")
                return self._finish(state, "error", f"ACTIVATION_TRANSIENT: {error}; retrying on the next run",
                                    release_id)
            self._mark_failed(state, release_id, f"activation: {error}")
            self._result(state, release_id, "refused", f"activation: {error}")
            return self._finish(state, "failed", f"activation refused: {error}", release_id)
        finally:
            self._release_claim()

    def _core_down(self) -> bool:
        """True only when systemd says CORE is stopped (or crash-looping) with no main process.

        Re-review N2: fail closed. A failed call or an unreadable answer means running.
        """
        shown = self._systemctl("show", "-p", "ActiveState,SubState,MainPID", "rosy-core.service")
        if shown.returncode != 0:
            return False
        values = dict(line.split("=", 1) for line in shown.stdout.splitlines() if "=" in line)
        active, sub, pid = values.get("ActiveState"), values.get("SubState"), values.get("MainPID")
        stopped = active in ("inactive", "failed") or (active == "activating" and sub == "auto-restart")
        return stopped and pid == "0"

    def _resume(self, state: dict) -> dict:
        """A run died mid-apply (power loss, kill): finish it, once the robot is free again."""
        applying = state["applying"]
        release_id = str(applying.get("release_id"))
        step = applying.get("step")
        if not applying.get("interrupted_logged"):
            applying["interrupted_logged"] = True
            self._history("apply_interrupted", release_id, f"step {step}")
        # Review H1: nothing restarts while the robot is held, sealed or busy. Coordinator
        # decision: with rosy-core not running nothing can command motion (CORE is the only
        # cmd_vel publisher, D-2), so idleness is waived; hold, seal and claim still apply.
        core_down = self._core_down()
        report = self.eligibility(own_claim_ok=True, waive_inputs=core_down)
        if not report["eligible"]:
            silent = (not report["held"] and not core_down
                      and any(("stale" in reason or "missing" in reason or "not rewritten" in reason)
                              for reason in report["reasons"]))
            if not silent:
                applying.pop("silent_since", None)
            else:
                # Verification review M1: measured from the first resume that saw the silence.
                applying.setdefault("silent_since", _z(self.host.now()))
                since = parse_z(applying["silent_since"])
                if since is not None and (self.host.now() - since).total_seconds() > STUCK_AFTER_S:
                    # Re-review N5: no automatic rollback; a person has to look.
                    return self._finish(state, "stuck", STUCK_REASON, release_id)
            phase = "held" if report["held"] else "ineligible"
            return self._finish(state, phase, f"finishing {release_id} (step {step}) waits: "
                                + "; ".join(report["reasons"]), release_id)
        applying.pop("silent_since", None)
        # Re-review N15: the note describes this resume only.
        if core_down:
            applying["note"] = CORE_DOWN_NOTE
            self._history("idleness_waived", release_id, CORE_DOWN_NOTE)
        else:
            applying.pop("note", None)
        self._release_claim()  # our own claim from the dead run
        try:
            rosy_claim.acquire(self.root, CLAIM_HOLDER, f"finish auto-update to {release_id}", CLAIM_TTL_S,
                               now=self.host.now())
        except rosy_claim.ClaimBusy as exc:
            return self._finish(state, "ineligible", f"claim held by {(exc.claim or {}).get('holder')}",
                                release_id)
        try:
            # Review H2: a journal that reached rollback is only ever rolled back further.
            if step == "rollback":
                return self._roll_back(state, release_id, applying.get("why") or "interrupted rollback",
                                       mark_failed=applying.get("mark_failed", True))
            if step == "activate":
                self._recover_native()
            current = self.host.current_release()
            if current == release_id:
                return self._settle(state, release_id)
            if step == "activate" and current == applying.get("previous"):
                # Re-review N11: the switch never happened; nothing to blame on the release.
                state["applying"] = None
                self._apply_error(state, release_id, "activation interrupted before the switch")
                return self._finish(state, "waiting", f"an interrupted activation of {release_id} never "
                                    "switched; retrying after a backoff", release_id)
            # Boot recovery (or the activator) already restored the old release.
            problems = self._rollback_tail(release_id) if step != "activate" else []
            why = "; ".join(filter(None, ["interrupted; the previous release is current", applying.get("note")]))
            state["applying"] = None
            self._mark_failed(state, release_id, why)
            detail = why if not problems else f"{why}; rollback incomplete: {'; '.join(problems)}"
            self._result(state, release_id, "rolled_back", detail)
            return self._finish(state, "rolled_back" if not problems else "failed", detail, release_id)
        finally:
            self._release_claim()

    # the timer entry -----------------------------------------------------------------

    @staticmethod
    @contextlib.contextmanager
    def _locked_file(path: Path):
        """Non-blocking exclusive lock (flock; msvcrt on a Windows test host). OSError when busy."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+b") as handle:
            handle.seek(0)
            if os.name == "posix":
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == "posix":
                    import fcntl

                    fcntl.flock(handle, fcntl.LOCK_UN)
                else:
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

    @contextlib.contextmanager
    def _run_lock(self):
        try:
            lock = self._locked_file(self.updates / ".run.lock")
            lock.__enter__()
        except OSError as exc:
            raise RunBusy("RUN_BUSY: another updater run is active") from exc
        try:
            yield
        finally:
            lock.__exit__(None, None, None)

    def run(self) -> dict:
        try:
            with self._run_lock():
                # Review M3: state is read only under the lock, and a busy run writes nothing.
                state = self._load_state()
                try:
                    return self._run(state)
                except UpdateError as exc:
                    return self._finish(state, "error", str(exc), state.get("candidate"))
                except Exception as exc:  # noqa: BLE001 - the oneshot must record, not crash
                    return self._finish(state, "error", f"UNEXPECTED: {exc!r}", state.get("candidate"))
        except RunBusy as exc:
            return {"schema": 1, "updated_at": _z(self.host.now()), "hostname": self.host.hostname(),
                    "current_release": self.host.current_release(), "candidate": None, "phase": "error",
                    "reason": str(exc), "last_result": None}

    def _run(self, state: dict) -> dict:
        # Review L9: an apply in flight is finished (or rolled back) even when disabled.
        if state.get("applying"):
            return self._resume(state)
        state["candidate"] = None
        config = self._config()
        if not config["enabled"]:
            return self._finish(state, "disabled", "config.json has enabled=false")
        if config.get("api_base"):
            self._use_api_base(config["api_base"])
        current = self.host.current_release()
        if current is None:
            raise UpdateError("CURRENT_UNKNOWN: /opt/rosy/current does not name a release")
        last = state.get("last_result") or {}
        if last.get("outcome") == "rollback_failed" and last.get("release_id") == current:
            # Verification review L2: still on the release that could not be rolled back;
            # say so on every run until a person changes current.
            return self._finish(state, "failed", f"{current} could not be rolled back; operator action required: "
                                "rosy-release-push.ps1 -Rollback", current)
        failed = state.setdefault("failed", {})
        # Review H4: a release we committed that is now above current was rolled back
        # on purpose by an operator; never apply it again.
        previous = self.host.previous_release()
        rolled_back = [item for item in state.get("committed") or [] if item > current]
        if previous is not None and previous > current and previous not in (state.get("self_rolled_back") or {}):
            rolled_back.append(previous)  # re-review N9: previous above current was rolled away from
        for item in rolled_back:
            if item not in failed:
                self._mark_failed(state, item, "operator rolled back")
                self._history("operator_rolled_back", item, f"current is {current}")
        self._expire_hold()
        backoff = parse_z(state.get("backoff_until"))
        if backoff is not None and self.host.now() < backoff:
            raise UpdateError(f"GITHUB_BACKOFF: not asking GitHub until {_z(backoff)}")
        state["backoff_until"] = None
        try:
            releases = self._releases(state, config["repo"])
        finally:
            self._save_state(state)
        withdrawn = state.setdefault("withdrawn", {})
        candidates = sorted((item for item in releases
                             if item["release_id"] > current and item["release_id"] not in failed
                             and item["release_id"] not in withdrawn),
                            key=lambda item: item["release_id"], reverse=True)
        skipped = []
        for release in candidates:
            try:
                rollout = self._rollout(release)
            except Definitive as exc:
                # Review L1: only a definitive problem lets a lower release go first.
                skipped.append(f"{release['release_id']}: {exc}")
                continue
            except UpdateError as exc:
                state["candidate"] = release["release_id"]
                return self._finish(state, "error", str(exc), release["release_id"])
            if rollout["withdrawn"]:
                # Review M4: a withdrawal is permanent on this robot.
                withdrawn[release["release_id"]] = {"at": _z(self.host.now()), "reason": rollout.get("reason")}
                skipped.append(f"{release['release_id']}: withdrawn ({rollout.get('reason')})")
                continue
            break
        else:
            reason = "no newer release" + (f"; skipped {'; '.join(skipped)}" if skipped else "")
            return self._finish(state, "idle", reason)
        release_id = release["release_id"]
        state["candidate"] = release_id
        self._stage(state, release, rollout)
        waiting = self._gate(rollout)
        if waiting:
            return self._finish(state, "waiting", waiting, release_id)
        attempts = (state.get("apply_errors") or {}).get(release_id) or {}
        if attempts.get("attempts", 0) >= APPLY_MAX_TRANSIENT:
            return self._finish(state, "held", ESCALATED_REASON, release_id)
        retry = parse_z(attempts.get("retry_after"))
        if retry is not None and self.host.now() < retry:
            return self._finish(state, "waiting", f"apply backoff after {attempts.get('last')}; "
                                f"next attempt after {_z(retry)}", release_id)
        report = self.eligibility()
        if not report["eligible"]:
            phase = "held" if report["held"] else "ineligible"
            return self._finish(state, phase, "; ".join(report["reasons"]), release_id)
        return self.apply(release_id, state)


# --- CLI --------------------------------------------------------------------------------


def _print_status(status: dict) -> None:
    for key in ("phase", "reason", "current_release", "candidate", "updated_at"):
        print(f"{key}: {status.get(key)}")
    last = status.get("last_result")
    if last:
        print(f"last_result: {last.get('outcome')} {last.get('release_id')} at {last.get('at')} ({last.get('detail')})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=Path("/"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run")
    show = sub.add_parser("status")
    show.add_argument("--json", action="store_true")
    hold = sub.add_parser("hold")
    hold.add_argument("--holder", required=True)
    hold.add_argument("--reason", required=True)
    hold.add_argument("--hours", type=float, required=True)
    sub.add_parser("release-hold")
    sub.add_parser("precheck")
    check = sub.add_parser("eligibility")
    check.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    updater = Updater(Host(args.root), api_base=API_BASE)
    if args.command == "run":
        print(json.dumps(updater.run(), sort_keys=True))
        return 0  # every outcome is in status.json; a failed oneshot would only add noise
    if args.command == "status":
        try:
            status = _read_json(updater.updates / "status.json")
        except (OSError, ValueError):
            status = {"phase": None, "reason": "the updater has not run yet"}
        if args.json:
            print(json.dumps(status, sort_keys=True))
        else:
            _print_status(status if isinstance(status, dict) else {})
        return 0
    if args.command == "hold":
        try:
            print(json.dumps(updater.hold(args.holder, args.reason, args.hours), sort_keys=True))
        except UpdateError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        return 0
    if args.command == "precheck":
        reasons = updater.precheck()
        print("; ".join(reasons) if reasons else "ok")
        return PRECHECK_BUSY_EXIT if reasons else 0
    if args.command == "release-hold":
        print(json.dumps({"ok": True, "released": updater.release_hold()}))
        return 0
    report = updater.eligibility()
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print("eligible" if report["eligible"] else "not eligible")
        for reason in report["reasons"]:
            print(f"- {reason}")
    return 0 if report["eligible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
