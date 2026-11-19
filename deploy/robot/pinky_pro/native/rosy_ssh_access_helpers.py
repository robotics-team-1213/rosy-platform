"""Constants, validation, atomic file helpers, and key/state readers for rosy-ssh-access."""

from __future__ import annotations

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
import sys
import tempfile
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
TEMP_LOGIN_STATE = STATE_DIR + "/password.json"
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
TEMP_LOGIN_DROPIN = "etc/ssh/sshd_config.d/60-rosy-temp-password.conf"
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
TEMP_LOGIN_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
PRIVATE_NETWORKS = "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"

REQUEST_ID = re.compile(r"[0-9a-f]{16,64}")
MAX_REQUEST_BYTES = 4096
MAX_BY = 128
#: A request older than this (a path unit started late, a leftover file) does nothing.
REQUEST_MAX_AGE_S = 30.0
REQUEST_FUTURE_SKEW_S = 5.0
#: CORE waits at most this long (ssh_handoff.WAIT_S) and writes when it stops waiting as
#: `answer_by` (epoch seconds).
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
TEMP_LOGIN_DROPIN_TEXT = (
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

ENTRY_KEYS = {"label", "type", "key", "fingerprint", "added_at", "expires_at", "added_by"}


class Invalid(ValueError):
    """A value the contract does not allow (422)."""


class Refusal(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class HelperError(RuntimeError):
    """The machine refused (a command failed, a state file is unreadable): 503."""


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
    groups = ("".join(secrets.choice(TEMP_LOGIN_ALPHABET) for _ in range(4)) for _ in range(3))
    return "rosy-" + "-".join(groups)


def stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_stamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("not a time")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _printable(value: Any, limit: int) -> bool:
    return isinstance(value, str) and len(value) <= limit and value.isprintable()


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


def log(message: str) -> None:
    print(f"rosy-ssh-access: {message}", file=sys.stderr, flush=True)


@contextlib.contextmanager
def locked(system: Any) -> Iterator[None]:
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


def ensure_state_dir(system: Any) -> None:
    directory = system.path(STATE_DIR)
    if directory.is_symlink():
        raise HelperError(f"/{STATE_DIR} 가 심볼릭 링크입니다")
    directory.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        os.chmod(directory, 0o755)


def _rotate_history(system: Any) -> None:
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


def record(system: Any, event: str, **fields: Any) -> None:
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


def load_keys(system: Any) -> list[dict]:
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


def public_row(entry: dict) -> dict:
    return {key: entry[key] for key in ("label", "type", "fingerprint", "added_at", "expires_at", "added_by")}


def password_state(system: Any) -> dict:
    """{enabled, expires_at, lock_pending, ...}; `lock_pending` while a failed lock waits for its retry."""
    raw = _read_bytes(system.path(TEMP_LOGIN_STATE), 4096)
    try:
        data = json.loads((raw or b"{}").decode("utf-8"))
        pending = data.get("lock_pending") is True
        if data.get("enabled") is True:
            parse_stamp(data["expires_at"])
            return {**data, "lock_pending": pending}
    except (ValueError, KeyError, TypeError, AttributeError, UnicodeDecodeError):
        pending = False
    return {"enabled": False, "expires_at": None, "lock_pending": pending}


def password_expired(system: Any, state: dict) -> bool:
    """By the wall clock, or by the boot clock (which NTP never steps), or because it is another boot."""
    if parse_stamp(state["expires_at"]) <= system.now():
        return True
    boot_id, deadline = state.get("boot_id"), state.get("boot_deadline")
    if not isinstance(boot_id, str) or not boot_id or type(deadline) not in (int, float):
        return True  # no boot bound (a state from before it existed): off at the next check
    return boot_id != system.boot_id() or system.boot_time() >= deadline
