#!/usr/bin/env python3
"""Manage the robot's SSH access as root, on an administrator's request through CORE (D-418).

CORE stays unprivileged (D-161). An administrator calls /api/v1/host/ssh/...,
CORE writes /run/rosy/ssh-access.request, and rosy-ssh-access.path starts this
program. It reads the request strictly, consumes it, validates everything again
on its own, applies it and writes /run/rosy/ssh-access.response
(root:rosy-core 0640), which CORE reads once and deletes.

* Keys: /var/lib/rosy/ssh/keys.json (root 0600) is the record; the managed
  authorized_keys beside it (0644, sshd reads it as rosy) is rebuilt from it,
  one `expiry-time="YYYYMMDDHHMMZ" <type> <base64> rosy-managed:<label>` line
  per key, so sshd itself refuses a key after its expiry. The drop-in
  50-rosy-managed-keys.conf makes sshd read the file for rosy only. /etc/ssh is
  outside the D-388 image layer, so this program installs and keeps it.
* Temporary password: generated here, set with chpasswd (stdin), allowed only
  from private networks by 60-rosy-temp-password.conf, and turned off (shadow
  field `*`, drop-in removed, sshd reloaded) when it expires
  (rosy-ssh-password-expire.timer runs --expire while it is on), when asked,
  and at every boot (--boot, rosy-ssh-access-boot.service).
* Fail closed: every run turns an expired password off first, each housekeeping
  step on its own (a corrupt keys.json never keeps a password on). If usermod
  cannot lock it, a `Match User rosy` / `PasswordAuthentication no` drop-in
  replaces the password block and the expiry timer retries the lock. A password
  CORE would get after its answer_by is rolled back, never written to /run/rosy.
* Time: the temporary password expires by the wall clock or by a CLOCK_BOOTTIME
  deadline of the boot it was issued in, whichever comes first. Key expiry counts
  from max(clock, newest time seen) in clock.json (the Pi has no RTC), but a mark
  more than 2 days ahead of the clock is dropped, and once timedated reports NTP
  sync (chrony or timesyncd alike) the mark is the clock.
* Audit: /var/lib/rosy/ssh/history.jsonl (root 0600, newest 1 MiB): add, revoke, expire,
  password_on, password_off. The password itself goes to chpasswd and to the
  response CORE reads, nowhere else: not the history, the journal or a state file.

Standard library only; run as `python3 -I -B`.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterator, Optional

sys.dont_write_bytecode = True

SCHEMA = 1
USER = "rosy"
#: CORE's side of the hand-over, in its own RuntimeDirectory (/run/rosy).
REQUEST = "run/rosy/ssh-access.request"
#: The request is renamed here before it is read, so one CORE writes meanwhile is never removed unread.
CLAIMED = "run/rosy/.ssh-access.request.claimed"
RESPONSE = "run/rosy/ssh-access.response"
STATE_DIR = "var/lib/rosy/ssh"
AUTHORIZED = STATE_DIR + "/authorized_keys"
KEYS = STATE_DIR + "/keys.json"
HISTORY = STATE_DIR + "/history.jsonl"
PASSWORD_STATE = STATE_DIR + "/password.json"
#: The newest time this program has seen (the Pi has no RTC: an offline boot may start in the past).
CLOCK = STATE_DIR + "/clock.json"
HISTORY_MAX_BYTES = 1 << 20
#: A mark further ahead of the clock than this is a clock that ran ahead, not time that passed.
MARK_AHEAD_LIMIT = timedelta(days=2)
#: The mark is rewritten only when it rises this much (SD card wear).
MARK_STEP = timedelta(seconds=60)
BOOT_ID = "proc/sys/kernel/random/boot_id"
LOCK = STATE_DIR + "/.lock"
KEYS_DROPIN = "etc/ssh/sshd_config.d/50-rosy-managed-keys.conf"
PASSWORD_DROPIN = "etc/ssh/sshd_config.d/60-rosy-temp-password.conf"
CORE_GROUP = "rosy-core"
SSH_UNIT = "ssh.service"  # Ubuntu 24.04: ssh.service (sshd.service is only an alias)
EXPIRE_TIMER = "rosy-ssh-password-expire.timer"
CHPASSWD = "/usr/sbin/chpasswd"
USERMOD = "/usr/sbin/usermod"
SSHD = "/usr/sbin/sshd"
SYSTEMCTL = "/usr/bin/systemctl"
TIMEDATECTL = "/usr/bin/timedatectl"
COMMAND_TIMEOUT_S = 15.0
COMMAND_ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"}

#: The card operator allowlist (personalization.OPERATOR_KEY_TYPES), checked by a parity test.
KEY_TYPES = ("ssh-ed25519", "sk-ssh-ed25519@openssh.com",
             "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521")
#: An uncompressed point (0x04 || X || Y) per curve.
ECDSA_COORDINATE_BYTES = {"nistp256": 32, "nistp384": 48, "nistp521": 66}
PUBLIC_KEY = re.compile(r"(?P<type>[a-z0-9@.-]+) (?P<blob>[A-Za-z0-9+/]+={0,2})(?: (?P<comment>[!-~ ]{1,100}))?")
LABEL = re.compile(r"[a-z0-9][a-z0-9._:-]{0,47}")
MAX_KEYS = 32
EXPIRES_DAYS = (1, 365)
PASSWORD_MINUTES = (1, 60)
#: The AP password alphabet (release/network.py READABLE_ALPHABET): no 0/o, 1/l/i.
PASSWORD_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
PRIVATE_NETWORKS = "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"

REQUEST_ID = re.compile(r"[0-9a-f]{16,64}")
MAX_REQUEST_BYTES = 4096
MAX_BY = 128
#: A request older than this (a path unit started late, a leftover file) does nothing.
REQUEST_MAX_AGE_S = 30.0
REQUEST_FUTURE_SKEW_S = 5.0
#: CORE waits at most this long (ssh_handoff.WAIT_S) and writes when it stops waiting as
#: `answer_by` (epoch seconds). A password answered later than answer_by - ANSWER_MARGIN_S would
#: only sit in /run/rosy, so it is rolled back instead; the margin covers writing the answer.
CORE_WAIT_S = 10.0
ANSWER_MARGIN_S = 1.0
#: Requests written while this run works (CORE's password_off after a timeout) are answered before it exits.
MAX_REQUESTS_PER_RUN = 8
HEADER_KEYS = {"schema", "request_id", "action", "requested_at", "answer_by", "by"}
ACTIONS = {
    "list": set(),
    "add": {"public_key", "label", "expires_days"},
    "revoke": {"label"},
    "password_on": {"minutes"},
    "password_off": set(),
    "password_status": set(),
}

KEYS_DROPIN_TEXT = (
    "# D-418: managed by rosy-ssh-access (root). Keys enrolled through CORE for rosy,\n"
    "# each with its own expiry-time. Rewritten when it differs; do not edit.\n"
    f"Match User {USER}\n"
    "    AuthorizedKeysFile .ssh/authorized_keys /var/lib/rosy/ssh/authorized_keys\n"
)
PASSWORD_DROPIN_TEXT = (
    "# D-418: temporary password for rosy from private networks only. rosy-ssh-access\n"
    "# removes it when the password expires, when it is turned off, and at every boot.\n"
    f"Match User {USER} Address {PRIVATE_NETWORKS}\n"
    "    PasswordAuthentication yes\n"
    "    MaxAuthTries 3\n"
    f"Match User {USER}\n"
    "    PasswordAuthentication no\n"
)
#: In place of the block above when usermod cannot lock the password: sshd refuses it until a retry locks it.
PASSWORD_DENY_TEXT = (
    "# D-418: rosy-ssh-access could not lock rosy's password; sshd refuses it until\n"
    "# rosy-ssh-password-expire.timer retries the lock and removes this file.\n"
    f"Match User {USER}\n"
    "    PasswordAuthentication no\n"
)


class Invalid(ValueError):
    """A value the contract does not allow (422)."""


class Refusal(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class HelperError(RuntimeError):
    """The machine refused (a command failed, a state file is unreadable): 503."""


# --- validation ---------------------------------------------------------------


def _ssh_strings(blob: bytes) -> list[bytes]:
    """RFC 4253 strings, consuming the whole blob, or Invalid."""
    parts, offset = [], 0
    while offset < len(blob):
        if offset + 4 > len(blob):
            raise Invalid("공개키 본문이 잘렸습니다")
        size = int.from_bytes(blob[offset:offset + 4], "big")
        offset += 4
        if size > len(blob) - offset:
            raise Invalid("공개키 본문이 잘렸습니다")
        parts.append(blob[offset:offset + size])
        offset += size
    return parts


def validate_public_key(text: Any) -> tuple[str, str]:
    """(type, base64) of a single-line OpenSSH public key of an allowed type, or Invalid."""
    if not isinstance(text, str):
        raise Invalid("공개키는 문자열이어야 합니다")
    match = PUBLIC_KEY.fullmatch(text.strip())
    if match is None or match["type"] not in KEY_TYPES:
        raise Invalid(f"공개키 형식이 아니거나 허용되지 않은 종류입니다 (허용: {', '.join(KEY_TYPES)})")
    try:
        blob = base64.b64decode(match["blob"], validate=True)
    except ValueError as exc:
        raise Invalid("공개키 본문이 base64가 아닙니다") from exc
    kind = match["type"]
    parts = _ssh_strings(blob)
    if not parts or parts[0] != kind.encode("ascii"):
        raise Invalid("공개키 본문이 종류와 맞지 않습니다")
    body = parts[1:]
    if kind == "ssh-ed25519":
        shaped = len(body) == 1 and len(body[0]) == 32
    elif kind == "sk-ssh-ed25519@openssh.com":
        shaped = len(body) == 2 and len(body[0]) == 32 and 0 < len(body[1]) <= 255
    else:
        curve = kind.rsplit("-", 1)[1]
        shaped = len(body) == 2 and body[0] == curve.encode("ascii") \
            and len(body[1]) == 1 + 2 * ECDSA_COORDINATE_BYTES[curve] and body[1][:1] == b"\x04"
    if not shaped:
        raise Invalid("공개키 본문이 종류와 맞지 않습니다")
    return kind, match["blob"]


def validate_label(label: Any) -> str:
    if not isinstance(label, str) or not LABEL.fullmatch(label):
        raise Invalid("라벨은 ^[a-z0-9][a-z0-9._:-]{0,47}$ 이어야 합니다")
    return label


def bounded_int(value: Any, low: int, high: int, name: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise Invalid(f"{name}는 {low}..{high} 정수여야 합니다")
    return value


def fingerprint(blob_b64: str) -> str:
    digest = hashlib.sha256(base64.b64decode(blob_b64)).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


def generate_password() -> str:
    groups = ("".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(4)) for _ in range(3))
    return "rosy-" + "-".join(groups)


def stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_stamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("not a time")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _printable(value: Any, limit: int) -> bool:
    return isinstance(value, str) and len(value) <= limit and value.isprintable()


# --- files -----------------------------------------------------------------------


def write_atomic(path: Path, content: str, mode: int, group: Optional[int] = None) -> None:
    """Mode and group on the empty temporary file, fsync, then rename over the target."""
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            if group is not None and hasattr(os, "fchown"):
                os.fchown(handle.fileno(), -1, group)
            if hasattr(os, "fchmod"):
                os.fchmod(handle.fileno(), mode)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _read_bytes(path: Path, limit: int) -> Optional[bytes]:
    """A regular file's content, never through a link or a FIFO; None when absent or too big."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) \
        | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            return None
        raw = os.read(descriptor, limit + 1)
    finally:
        os.close(descriptor)
    return raw if len(raw) <= limit else None


def read_request(path: Path, now: float) -> Optional[dict]:
    """CORE's request, validated, or None."""
    raw = _read_bytes(path, MAX_REQUEST_BYTES)
    if raw is None:
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or data.get("action") not in ACTIONS:
        return None
    if set(data) != HEADER_KEYS | ACTIONS[data["action"]]:
        return None
    if not isinstance(data["request_id"], str) or not REQUEST_ID.fullmatch(data["request_id"]):
        return None
    if not _printable(data["by"], MAX_BY):
        return None
    try:
        requested = datetime.fromisoformat(str(data["requested_at"]).replace("Z", "+00:00"))
    except ValueError:
        return None
    if requested.tzinfo is None:
        return None
    age = now - requested.timestamp()
    if not -REQUEST_FUTURE_SKEW_S <= age <= REQUEST_MAX_AGE_S:
        return None
    answer_by = data["answer_by"]
    if type(answer_by) not in (int, float) or not math.isfinite(answer_by) \
            or not 0 <= answer_by - requested.timestamp() <= CORE_WAIT_S + 2:
        return None
    return data


class System:
    """Everything that touches the machine. Tests replace it; paths are under `root`."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, relative: str) -> Path:
        return self.root / relative

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def boot_time(self) -> float:
        """Seconds since boot, suspend included; NTP never steps it."""
        clock = getattr(time, "CLOCK_BOOTTIME", None)
        return time.clock_gettime(clock) if clock is not None else time.monotonic()

    def boot_id(self) -> str:
        raw = _read_bytes(self.path(BOOT_ID), 128)
        return (raw or b"").decode("ascii", "replace").strip()

    def ntp_synced(self) -> bool:
        """timedated's NTPSynchronized: the kernel's STA_UNSYNC flag, whichever daemon (the image's
        chrony, or timesyncd) disciplines the clock. Never adjtimex here: the units' seccomp
        filter kills the process with SIGSYS on it. Any failure means not synced."""
        try:
            done = self._run([TIMEDATECTL, "show", "-p", "NTPSynchronized", "--value"])
        except HelperError:
            return False
        return done.returncode == 0 and done.stdout.strip() == "yes"

    def _run(self, argv: list[str], stdin: Optional[str] = None) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=COMMAND_TIMEOUT_S,
                                  check=False, env=COMMAND_ENV)
        except (OSError, subprocess.SubprocessError) as exc:
            raise HelperError(f"{Path(argv[0]).name}: {type(exc).__name__}") from exc

    def set_password(self, user: str, password: str) -> None:
        # stdin, never argv: a command line is readable by every process.
        done = self._run([CHPASSWD, "-c", "SHA512"], stdin=f"{user}:{password}\n")
        if done.returncode != 0:
            raise HelperError(f"chpasswd 종료 {done.returncode}: {done.stderr.strip()[:160]}")

    def lock_password(self, user: str) -> None:
        """Shadow field `*`: no password matches, keys still work."""
        done = self._run([USERMOD, "-p", "*", user])
        if done.returncode != 0:
            raise HelperError(f"usermod 종료 {done.returncode}: {done.stderr.strip()[:160]}")

    def sshd_check(self) -> tuple[bool, str]:
        # ssh.socket starts sshd only on a connection, so its RuntimeDirectory /run/sshd may not
        # exist yet, and `sshd -t` refuses without the privilege separation directory.
        privsep = self.path("run/sshd")
        if not privsep.is_dir():
            privsep.mkdir(mode=0o755)
            if os.name == "posix":
                os.chmod(privsep, 0o755)
        done = self._run([SSHD, "-t"])
        return done.returncode == 0, done.stderr.strip()[:200]

    def reload_sshd(self) -> None:
        """Reload a running sshd; one that is not running reads the files when it starts."""
        if self._run([SYSTEMCTL, "is-active", "--quiet", SSH_UNIT]).returncode != 0:
            return
        done = self._run([SYSTEMCTL, "reload", SSH_UNIT])
        if done.returncode != 0:
            raise HelperError(f"{SSH_UNIT} reload 종료 {done.returncode}")

    def expire_timer(self, start: bool) -> None:
        """Start (a password without its expiry check is a HelperError) or stop (logged) the timer."""
        done = self._run([SYSTEMCTL, "--no-block", "start" if start else "stop", EXPIRE_TIMER])
        if done.returncode != 0:
            if start:
                raise HelperError(f"{EXPIRE_TIMER} start 종료 {done.returncode}")
            log(f"{EXPIRE_TIMER} stop 종료 {done.returncode}")

    def core_group(self) -> Optional[int]:
        try:
            import grp
            return grp.getgrnam(CORE_GROUP).gr_gid
        except (ImportError, KeyError):
            return None


def log(message: str) -> None:
    print(f"rosy-ssh-access: {message}", file=sys.stderr, flush=True)


@contextlib.contextmanager
def locked(system: System) -> Iterator[None]:
    """One helper at a time: the path unit's run and the expiry timer's may overlap."""
    try:
        import fcntl
    except ImportError:  # a Windows test host
        yield
        return
    descriptor = os.open(system.path(LOCK), os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def ensure_state_dir(system: System) -> None:
    directory = system.path(STATE_DIR)
    if directory.is_symlink():
        raise HelperError(f"/{STATE_DIR} 가 심볼릭 링크입니다")
    directory.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        os.chmod(directory, 0o755)


def _rotate_history(system: System) -> None:
    """Keep the newest half mebibyte, cut at a line, once the file nears HISTORY_MAX_BYTES."""
    path = system.path(HISTORY)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size <= HISTORY_MAX_BYTES - 4096:
            return
        keep = HISTORY_MAX_BYTES // 2
        os.lseek(descriptor, info.st_size - keep, os.SEEK_SET)
        tail = os.read(descriptor, keep)
    finally:
        os.close(descriptor)
    tail = tail[tail.find(b"\n") + 1:]
    write_atomic(path, tail.decode("utf-8", "replace"), 0o600)


def record(system: System, event: str, **fields: Any) -> None:
    _rotate_history(system)
    line = json.dumps({"at": stamp(system.now()), "event": event, **fields}, ensure_ascii=False,
                      sort_keys=True) + "\n"
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(system.path(HISTORY), flags, 0o600)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        os.write(descriptor, line.encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def trusted_now(system: System, seen: tuple[datetime, ...] = ()) -> datetime:
    """The time key expiry counts from: the clock, raised to the newest time seen before.

    The Pi has no RTC, so an offline boot may start in the past; the mark in clock.json
    keeps key expiry from running backwards then. A mark (or a seen time) more than
    MARK_AHEAD_LIMIT ahead of the clock is a clock that once ran ahead: it is ignored and
    reset, so it never deletes keys. Once NTP synchronized the clock, the mark is the clock.
    Written only when it rises MARK_STEP or is reset; a failed write is logged, never fatal.
    Temporary passwords do not use it: they expire by the wall clock or the boot clock.
    """
    now = system.now().astimezone(timezone.utc).replace(microsecond=0)
    stored = None
    raw = _read_bytes(system.path(CLOCK), 4096)
    if raw is not None:
        try:
            stored = parse_stamp(json.loads(raw.decode("utf-8"))["high_water"])
        except (ValueError, KeyError, TypeError, UnicodeDecodeError):
            log(f"/{CLOCK} 를 읽을 수 없어 새로 씁니다")
    if system.ntp_synced():
        floor = now
    else:
        limit = now + MARK_AHEAD_LIMIT
        floor = max([now] + [moment for moment in (stored, *seen) if moment is not None and moment <= limit])
    if stored is None or floor >= stored + MARK_STEP or floor < stored:
        try:
            write_atomic(system.path(CLOCK), json.dumps({"high_water": stamp(floor)}) + "\n", 0o600)
        except OSError as exc:
            log(f"/{CLOCK} 를 쓰지 못했습니다: {exc}")
    return floor


# --- keys ------------------------------------------------------------------------


ENTRY_KEYS = {"label", "type", "key", "fingerprint", "added_at", "expires_at", "added_by"}


def load_keys(system: System) -> list[dict]:
    path = system.path(KEYS)
    if not path.exists():
        return []
    raw = _read_bytes(path, 1 << 20)
    try:
        data = json.loads((raw or b"").decode("utf-8"))
        entries = data["keys"]
        if data.get("schema") != SCHEMA or not isinstance(entries, list) or len(entries) > MAX_KEYS:
            raise ValueError("shape")
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != ENTRY_KEYS:
                raise ValueError("entry")
            validate_label(entry["label"])
            if validate_public_key(f"{entry['type']} {entry['key']}") != (entry["type"], entry["key"]):
                raise ValueError("key")
            parse_stamp(entry["added_at"]), parse_stamp(entry["expires_at"])
            if not _printable(entry["added_by"], MAX_BY):
                raise ValueError("added_by")
        if len({entry["label"] for entry in entries}) != len(entries):
            raise ValueError("labels")
    except (ValueError, KeyError, TypeError, UnicodeDecodeError) as exc:
        raise HelperError(f"/{KEYS} 를 읽을 수 없습니다 ({exc})") from exc
    return entries


def authorized_text(entries: list[dict]) -> str:
    lines = []
    for entry in entries:
        expiry = parse_stamp(entry["expires_at"]).strftime("%Y%m%d%H%MZ")
        lines.append(f'expiry-time="{expiry}" {entry["type"]} {entry["key"]} rosy-managed:{entry["label"]}\n')
    return "".join(lines)


def save_keys(system: System, entries: list[dict]) -> None:
    """The managed file first: a revoke takes effect even if the record write fails after it."""
    text = authorized_text(entries)
    current = _read_bytes(system.path(AUTHORIZED), 1 << 20)
    if current is None or current.decode("utf-8", "replace") != text:
        write_atomic(system.path(AUTHORIZED), text, 0o644)
    document = json.dumps({"schema": SCHEMA, "keys": entries}, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    current = _read_bytes(system.path(KEYS), 1 << 20)
    if current is None or current.decode("utf-8", "replace") != document:
        write_atomic(system.path(KEYS), document, 0o600)


def prune_keys(system: System) -> list[dict]:
    """Drop keys past their expiry (sshd already refuses them) and keep the file in step."""
    entries = load_keys(system)
    now = trusted_now(system, tuple(parse_stamp(entry["added_at"]) for entry in entries))
    kept = [entry for entry in entries if parse_stamp(entry["expires_at"]) > now]
    save_keys(system, kept)
    for entry in entries:
        if entry not in kept:
            record(system, "expire", label=entry["label"], fingerprint=entry["fingerprint"])
    return kept


def public_row(entry: dict) -> dict:
    return {key: entry[key] for key in ("label", "type", "fingerprint", "added_at", "expires_at", "added_by")}


def add_key(system: System, request: dict) -> tuple[int, dict]:
    kind, blob = validate_public_key(request["public_key"])
    label = validate_label(request["label"])
    days = bounded_int(request["expires_days"], *EXPIRES_DAYS, "expires_days")
    entries = prune_keys(system)
    if any(entry["label"] == label for entry in entries):
        raise Refusal(409, "SSH_LABEL_EXISTS", f"라벨 {label} 이(가) 이미 있습니다")
    if any(entry["key"] == blob for entry in entries):
        raise Refusal(409, "SSH_KEY_EXISTS", "같은 공개키가 이미 다른 라벨로 등록되어 있습니다")
    if len(entries) >= MAX_KEYS:
        raise Refusal(409, "SSH_KEYS_FULL", f"관리 키는 최대 {MAX_KEYS}개입니다. 먼저 하나를 회수하세요")
    now = trusted_now(system)
    expires = (now + timedelta(days=days)).replace(second=0, microsecond=0)
    entry = {"label": label, "type": kind, "key": blob, "fingerprint": fingerprint(blob),
             "added_at": stamp(now), "expires_at": stamp(expires), "added_by": request["by"]}
    save_keys(system, entries + [entry])
    record(system, "add", label=label, fingerprint=entry["fingerprint"], expires_at=entry["expires_at"],
           by=request["by"])
    return 201, {"label": label, "fingerprint": entry["fingerprint"], "expires_at": entry["expires_at"]}


def revoke_key(system: System, request: dict) -> tuple[int, None]:
    label = validate_label(request["label"])
    entries = prune_keys(system)
    kept = [entry for entry in entries if entry["label"] != label]
    if len(kept) == len(entries):
        raise Refusal(404, "SSH_KEY_NOT_FOUND", f"라벨 {label} 인 키가 없습니다")
    save_keys(system, kept)
    gone = next(entry for entry in entries if entry["label"] == label)
    record(system, "revoke", label=label, fingerprint=gone["fingerprint"], by=request["by"])
    return 204, None


# --- temporary password ---------------------------------------------------------------


def password_state(system: System) -> dict:
    """{enabled, expires_at, lock_pending, ...}; `lock_pending` while a failed lock waits for its retry."""
    raw = _read_bytes(system.path(PASSWORD_STATE), 4096)
    try:
        data = json.loads((raw or b"{}").decode("utf-8"))
        pending = data.get("lock_pending") is True
        if data.get("enabled") is True:
            parse_stamp(data["expires_at"])
            return {**data, "lock_pending": pending}
    except (ValueError, KeyError, TypeError, AttributeError, UnicodeDecodeError):
        pending = False
    return {"enabled": False, "expires_at": None, "lock_pending": pending}


def _write_off_state(system: System, *, lock_pending: bool = False) -> None:
    state = {"enabled": False, "expires_at": None, **({"lock_pending": True} if lock_pending else {})}
    write_atomic(system.path(PASSWORD_STATE), json.dumps(state) + "\n", 0o600)


def password_expired(system: System, state: dict) -> bool:
    """By the wall clock, or by the boot clock (which NTP never steps), or because it is another boot."""
    if parse_stamp(state["expires_at"]) <= system.now():
        return True
    boot_id, deadline = state.get("boot_id"), state.get("boot_deadline")
    if not isinstance(boot_id, str) or not boot_id or type(deadline) not in (int, float):
        return True  # no boot bound (a state from before it existed): off at the next check
    return boot_id != system.boot_id() or system.boot_time() >= deadline


def _write_deny_dropin(system: System) -> None:
    write_atomic(system.path(PASSWORD_DROPIN), PASSWORD_DENY_TEXT, 0o644)


def lock_or_deny(system: System) -> None:
    """Shadow field `*`. If usermod fails: a Match block that refuses rosy's password, a reload,
    and the expiry timer, whose --expire run retries the lock; then the HelperError goes on."""
    try:
        system.lock_password(USER)
        return
    except HelperError as exc:
        failure = exc
    log(f"lock failed, denying the password in sshd instead: {failure}")
    for step, action in (("deny drop-in", lambda: _write_deny_dropin(system)),
                         ("state", lambda: _write_off_state(system, lock_pending=True)),
                         ("history", lambda: record(system, "password_deny", detail=str(failure)[:160])),
                         ("reload", system.reload_sshd),
                         ("retry timer", lambda: system.expire_timer(True))):
        try:
            action()
        except (HelperError, OSError) as exc:
            log(f"{step} after a failed lock: {exc}")
    raise failure


def password_off(system: System, reason: str, by: Optional[str] = None, *, force: bool = False) -> bool:
    """Lock first (no password matches any more), then drop the Match block and reload. True if it was on."""
    state = password_state(system)
    # A bare lock_pending (the deny block could not be written either) still needs the lock retried.
    was_on = state["enabled"] or state["lock_pending"] or system.path(PASSWORD_DROPIN).exists()
    if not was_on and not force:
        return False
    lock_or_deny(system)
    system.path(PASSWORD_DROPIN).unlink(missing_ok=True)
    _write_off_state(system)
    try:
        system.reload_sshd()
    except HelperError as exc:
        log(f"reload after password off: {exc}")
    system.expire_timer(False)
    if was_on:
        record(system, "password_off", reason=reason, **({"by": by} if by else {}))
    return was_on


def password_on(system: System, request: dict) -> tuple[int, dict]:
    minutes = bounded_int(request["minutes"], *PASSWORD_MINUTES, "minutes")
    password = generate_password()
    # The wall clock, not the key mark: a mark from a clock that ran ahead must not stretch it.
    # The boot clock bounds it too, whatever the wall clock does.
    expires = system.now() + timedelta(minutes=minutes)
    boot_id, boot_deadline = system.boot_id(), system.boot_time() + minutes * 60
    if not boot_id:
        # Without it the boot clock cannot bound the password: refuse rather than rely on the wall clock.
        raise HelperError(f"/{BOOT_ID} 를 읽을 수 없어 비밀번호를 켜지 않습니다")
    try:
        system.set_password(USER, password)
        write_atomic(system.path(PASSWORD_DROPIN), PASSWORD_DROPIN_TEXT, 0o644)
        ok, detail = system.sshd_check()
        if not ok:
            raise HelperError(f"sshd -t 가 설정을 거부했습니다: {detail}")
        write_atomic(system.path(PASSWORD_STATE),
                     json.dumps({"enabled": True, "expires_at": stamp(expires), "by": request["by"],
                                 "boot_id": boot_id, "boot_deadline": boot_deadline},
                                ensure_ascii=False) + "\n", 0o600)
        # The expiry check before sshd reads the block: a password is never live without it.
        system.expire_timer(True)
        system.reload_sshd()
    except (HelperError, OSError):
        password_rollback(system)
        raise
    record(system, "password_on", minutes=minutes, expires_at=stamp(expires), by=request["by"])
    return 200, {"user": USER, "password": password, "expires_at": stamp(expires)}


def password_rollback(system: System) -> None:
    """Nothing half-on: no Match block, no password that matches. Every step runs; none raises.

    The timer stops before the lock: a failed lock starts it again to retry."""
    for step, action in (("drop-in", lambda: system.path(PASSWORD_DROPIN).unlink(missing_ok=True)),
                         ("state", lambda: _write_off_state(system)),
                         ("timer", lambda: system.expire_timer(False)),
                         ("lock", lambda: lock_or_deny(system))):
        try:
            action()
        except (HelperError, OSError) as exc:
            log(f"rollback {step}: {exc}")


def expire_password(system: System) -> None:
    state = password_state(system)
    stale = not state["enabled"] and (system.path(PASSWORD_DROPIN).exists() or state["lock_pending"])
    if stale or (state["enabled"] and password_expired(system, state)):
        password_off(system, "expired")


# --- the run ----------------------------------------------------------------------


def ensure_keys_dropin(system: System) -> None:
    path = system.path(KEYS_DROPIN)
    current = _read_bytes(path, 64 * 1024)
    if current is not None and current.decode("utf-8", "replace") == KEYS_DROPIN_TEXT:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(path, KEYS_DROPIN_TEXT, 0o644)
    try:
        system.reload_sshd()
    except HelperError as exc:
        log(f"reload after the keys drop-in: {exc}")


def housekeeping(system: System, *, boot: bool = False) -> bool:
    """The password first, so nothing else that is broken (a corrupt keys.json) keeps it on.

    Each step on its own: a failure is logged and the next one still runs. False if any failed.
    """
    first = (("password off at boot", lambda: password_off(system, "boot", force=True)) if boot
             else ("password expiry", lambda: expire_password(system)))
    ok = True
    for step, action in (first, ("keys drop-in", lambda: ensure_keys_dropin(system)),
                         ("key expiry", lambda: prune_keys(system))):
        try:
            action()
        except (HelperError, OSError) as exc:
            log(f"{step}: {exc}")
            ok = False
    return ok


def handle(system: System, request: dict) -> dict:
    action = request["action"]
    try:
        if action == "list":
            status, result = 200, {"keys": [public_row(entry) for entry in load_keys(system)]}
        elif action == "add":
            status, result = add_key(system, request)
        elif action == "revoke":
            status, result = revoke_key(system, request)
        elif action == "password_on":
            status, result = password_on(system, request)
            if system.now().timestamp() > request["answer_by"] - ANSWER_MARGIN_S:
                # CORE has stopped waiting: the password would only sit in /run/rosy.
                password_off(system, "late", request["by"], force=True)
                raise HelperError(f"{CORE_WAIT_S:.0f} s 안에 답하지 못해 비밀번호를 되돌렸습니다")
        elif action == "password_off":
            password_off(system, "requested", request["by"])
            status, result = 204, None
        else:
            state = password_state(system)
            status, result = 200, {"enabled": state["enabled"], "expires_at": state["expires_at"],
                                   "lock_pending": state["lock_pending"]}
        error, message = None, ""
    except Invalid as exc:
        status, result, error, message = 422, None, "SSH_INVALID", str(exc)
    except Refusal as exc:
        status, result, error, message = exc.status, None, exc.code, exc.message
    except (HelperError, OSError) as exc:
        status, result, error, message = 503, None, "SSH_ACCESS_UNAVAILABLE", str(exc)[:300]
    return {"schema": SCHEMA, "request_id": request["request_id"], "status": status, "error": error,
            "message": message, "result": result}


def main(argv: Optional[list[str]] = None, *, system: Optional[System] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rosy-ssh-access",
        description="D-418 SSH access on CORE's request: managed keys and the temporary password.")
    parser.add_argument("--root", type=Path, default=Path("/"), help=argparse.SUPPRESS)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--expire", action="store_true", help="turn an expired password off (timer)")
    mode.add_argument("--boot", action="store_true", help="force the password off and install the drop-in (boot)")
    args = parser.parse_args(argv)
    if args.root == Path("/") and hasattr(os, "geteuid") and os.geteuid() != 0:
        log("run as root")
        return 1
    system = system or System(args.root)
    ensure_state_dir(system)
    with locked(system):
        if args.boot or args.expire:
            ok = housekeeping(system, boot=args.boot)
            print(json.dumps({"ssh_access": "boot" if args.boot else "expire", "ok": ok}), flush=True)
            return 0 if ok else 1
        housekeeping(system)
        for _ in range(MAX_REQUESTS_PER_RUN):
            path = system.path(REQUEST)
            if not os.path.lexists(path):
                break
            # Claimed by a rename, then read and removed: consumed before it is applied, so a
            # second trigger never repeats it, and one CORE writes meanwhile stays for the next
            # turn. An invalid or stale one goes too, so it never wakes the path unit again.
            claimed = system.path(CLAIMED)
            try:
                os.replace(path, claimed)
            except OSError as exc:
                log(f"request not claimed: {exc}")
                break
            request = read_request(claimed, system.now().timestamp())
            try:
                claimed.unlink()
            except OSError as exc:
                log(f"claimed request not removed: {exc}")
            if request is None:
                print(json.dumps({"ssh_access": "ignored"}), flush=True)
                continue
            response = handle(system, request)
            try:
                write_atomic(system.path(RESPONSE),
                             json.dumps(response, ensure_ascii=False, sort_keys=True) + "\n", 0o640,
                             system.core_group())
            except OSError as exc:
                log(f"response not written: {exc}")
                if request["action"] == "password_on" and response["status"] == 200:
                    # Nobody will receive it: off again.
                    try:
                        password_off(system, "undelivered", request["by"], force=True)
                    except (HelperError, OSError) as off_exc:
                        log(f"password off after an undelivered answer: {off_exc}")
                continue
            print(json.dumps({"ssh_access": request["action"], "status": response["status"],
                              "error": response["error"]}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
