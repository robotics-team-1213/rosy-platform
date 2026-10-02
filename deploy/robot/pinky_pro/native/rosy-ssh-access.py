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
* Audit: /var/lib/rosy/ssh/history.jsonl (root 0600): add, revoke, expire,
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
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import tempfile
from typing import Any, Iterator, Optional

sys.dont_write_bytecode = True

SCHEMA = 1
USER = "rosy"
#: CORE's side of the hand-over, in its own RuntimeDirectory (/run/rosy).
REQUEST = "run/rosy/ssh-access.request"
RESPONSE = "run/rosy/ssh-access.response"
STATE_DIR = "var/lib/rosy/ssh"
AUTHORIZED = STATE_DIR + "/authorized_keys"
KEYS = STATE_DIR + "/keys.json"
HISTORY = STATE_DIR + "/history.jsonl"
PASSWORD_STATE = STATE_DIR + "/password.json"
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
HEADER_KEYS = {"schema", "request_id", "action", "requested_at", "by"}
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
    return data


class System:
    """Everything that touches the machine. Tests replace it; paths are under `root`."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, relative: str) -> Path:
        return self.root / relative

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

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
        done = self._run([SYSTEMCTL, "--no-block", "start" if start else "stop", EXPIRE_TIMER])
        if done.returncode != 0:
            log(f"{EXPIRE_TIMER} {'start' if start else 'stop'} 종료 {done.returncode}")

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


def record(system: System, event: str, **fields: Any) -> None:
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
    now = system.now()
    entries = load_keys(system)
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
    now = system.now()
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
    raw = _read_bytes(system.path(PASSWORD_STATE), 4096)
    try:
        data = json.loads((raw or b"{}").decode("utf-8"))
        if data.get("enabled") is True:
            parse_stamp(data["expires_at"])
            return data
    except (ValueError, KeyError, TypeError, AttributeError, UnicodeDecodeError):
        pass
    return {"enabled": False, "expires_at": None}


def password_off(system: System, reason: str, by: Optional[str] = None, *, force: bool = False) -> bool:
    """Lock first (no password matches any more), then drop the Match block and reload. True if it was on."""
    was_on = password_state(system)["enabled"] or system.path(PASSWORD_DROPIN).exists()
    if not was_on and not force:
        return False
    system.lock_password(USER)
    system.path(PASSWORD_DROPIN).unlink(missing_ok=True)
    write_atomic(system.path(PASSWORD_STATE), json.dumps({"enabled": False, "expires_at": None}) + "\n", 0o600)
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
    expires = system.now() + timedelta(minutes=minutes)
    try:
        system.set_password(USER, password)
        write_atomic(system.path(PASSWORD_DROPIN), PASSWORD_DROPIN_TEXT, 0o644)
        ok, detail = system.sshd_check()
        if not ok:
            raise HelperError(f"sshd -t 가 설정을 거부했습니다: {detail}")
        write_atomic(system.path(PASSWORD_STATE),
                     json.dumps({"enabled": True, "expires_at": stamp(expires), "by": request["by"]},
                                ensure_ascii=False) + "\n", 0o600)
        system.reload_sshd()
    except HelperError:
        # Nothing half-on: no Match block, no password that matches.
        system.path(PASSWORD_DROPIN).unlink(missing_ok=True)
        write_atomic(system.path(PASSWORD_STATE), json.dumps({"enabled": False, "expires_at": None}) + "\n", 0o600)
        system.lock_password(USER)
        raise
    system.expire_timer(True)
    record(system, "password_on", minutes=minutes, expires_at=stamp(expires), by=request["by"])
    return 200, {"user": USER, "password": password, "expires_at": stamp(expires)}


def expire_password(system: System) -> None:
    state = password_state(system)
    stale_dropin = not state["enabled"] and system.path(PASSWORD_DROPIN).exists()
    if stale_dropin or (state["enabled"] and parse_stamp(state["expires_at"]) <= system.now()):
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


def housekeeping(system: System) -> None:
    ensure_state_dir(system)
    ensure_keys_dropin(system)
    prune_keys(system)
    expire_password(system)


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
        elif action == "password_off":
            password_off(system, "requested", request["by"])
            status, result = 204, None
        else:
            state = password_state(system)
            status, result = 200, {"enabled": state["enabled"], "expires_at": state["expires_at"]}
        error, message = None, ""
    except Invalid as exc:
        status, result, error, message = 422, None, "SSH_INVALID", str(exc)
    except Refusal as exc:
        status, result, error, message = exc.status, None, exc.code, exc.message
    except HelperError as exc:
        status, result, error, message = 503, None, "SSH_ACCESS_UNAVAILABLE", str(exc)
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
        if args.boot:
            ensure_keys_dropin(system)
            prune_keys(system)
            was_on = password_off(system, "boot", force=True)
            print(json.dumps({"ssh_access": "boot", "password_was_on": was_on}), flush=True)
            return 0
        request = None if args.expire else read_request(system.path(REQUEST), system.now().timestamp())
        if request is not None:
            # Consumed before it is applied: a second trigger never repeats it.
            system.path(REQUEST).unlink(missing_ok=True)
        housekeeping(system)
        if request is None:
            print(json.dumps({"ssh_access": "expire" if args.expire else "ignored"}), flush=True)
            return 0
        response = handle(system, request)
        write_atomic(system.path(RESPONSE), json.dumps(response, ensure_ascii=False, sort_keys=True) + "\n",
                     0o640, system.core_group())
        print(json.dumps({"ssh_access": request["action"], "status": response["status"],
                          "error": response["error"]}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
