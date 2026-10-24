"""The updater's constants, errors, device and network access (D-412; moved out of
rosy_auto_update.py, D-798). Standard library only, like the rest of the updater.

rosy_auto_update.py puts this folder on sys.path before importing it (the unit runs python3 -I).
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

import rosy_claim
import rosy_transfer  # network load: paced tarball download


API_BASE = "https://api.github.com"
# config.json "api_base": another GitHub-compatible API (the device twin's fake
# GitHub). Content is still trusted only through the release key signatures.
API_BASE_URL = re.compile(r"^https?://[A-Za-z0-9.:\[\]-]+(/[A-Za-z0-9._~/-]*)?$")
USER_AGENT = "rosy-auto-update/1 (D-412)"
DEFAULT_REPO = "robotics-team-1213/rosy-platform"
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
RELEASE_ID = re.compile(r"^[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]{3}$")
TAG = re.compile(r"^payload-(?:v2-)?([0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]{3})$")
PHASES = ("idle", "staged", "waiting", "held", "ineligible", "applying", "committed",
          "rolled_back", "failed", "disabled", "error", "stuck", "image_required")
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
# D-433 row 3: rosy-face shows "Updating" while this marker exists (two lines:
# step, candidate release id; nothing secret, root 0644).
UPDATE_DISPLAY = "run/rosy-boot/update-display.txt"
# D-433 Q5: after a rollback to a release older than rosy-face, its sync restores
# the retired display unit but does not start it; this updater starts it once.
FACE_UNIT = "rosy-face.service"
RETIRED_DISPLAY_UNIT = "rosy-boot-display.service"
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
        try:
            with response, destination.open("wb") as handle:
                status = getattr(response, "status", None) or response.code
                if status != 200:
                    raise UpdateError(f"DOWNLOAD_HTTP: {status} for {url}")
                for size, chunk in rosy_transfer.paced(response):
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
