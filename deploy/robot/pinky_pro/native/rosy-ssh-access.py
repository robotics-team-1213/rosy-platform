#!/usr/bin/env python3
"""Manage the robot's SSH access as root, on an administrator's request through CORE (D-418).

CORE stays unprivileged (D-161). An administrator calls /api/v1/host/ssh/...,
CORE writes /run/rosy/ssh-access.request, and rosy-ssh-access.path starts this
program. It reads the request strictly, consumes it, validates everything again
on its own, applies it and writes /run/rosy/ssh-access.response
(root:rosy-core 0640), which CORE reads once and deletes.
Standard library only; run as `python3 -I -B`.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Optional

sys.dont_write_bytecode = True

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from rosy_ssh_access_helpers import (  # noqa: E402,F401
    ACTIONS,
    ANSWER_MARGIN_S,
    AUTHORIZED,
    BOOT_ID,
    CLAIMED,
    CLOCK,
    COMMAND_ENV,
    COMMAND_TIMEOUT_S,
    CORE_GROUP,
    CORE_WAIT_S,
    ECDSA_COORDINATE_BYTES,
    ENTRY_KEYS,
    EXPIRE_TIMER,
    EXPIRES_DAYS,
    HEADER_KEYS,
    HISTORY,
    HISTORY_MAX_BYTES,
    HelperError,
    Invalid,
    KEY_TYPES,
    KEYS,
    KEYS_DROPIN,
    KEYS_DROPIN_TEXT,
    LABEL,
    LOCK,
    MARK_AHEAD_LIMIT,
    MARK_STEP,
    MAX_BY,
    MAX_KEYS,
    MAX_REQUEST_BYTES,
    MAX_REQUESTS_PER_RUN,
    PASSWORD_DENY_TEXT,
    PASSWORD_MINUTES,
    PRIVATE_NETWORKS,
    PUBLIC_KEY,
    Refusal,
    REQUEST,
    REQUEST_FUTURE_SKEW_S,
    REQUEST_ID,
    REQUEST_MAX_AGE_S,
    RESPONSE,
    SCHEMA,
    SSH_UNIT,
    SSHD,
    STATE_DIR,
    SYSTEMCTL,
    TEMP_LOGIN_ALPHABET,
    TEMP_LOGIN_DROPIN,
    TEMP_LOGIN_DROPIN_TEXT,
    TEMP_LOGIN_STATE,
    TIMEDATECTL,
    USER,
    USERMOD,
    _printable,
    _read_bytes,
    _rotate_history,
    _ssh_strings,
    authorized_text,
    bounded_int,
    ensure_state_dir,
    fingerprint,
    generate_password,
    load_keys,
    locked,
    log,
    parse_stamp,
    password_expired,
    password_state,
    public_row,
    read_request,
    record,
    stamp,
    validate_label,
    validate_public_key,
    write_atomic,
)

CHPASSWD = "/usr/sbin/chpasswd"


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
        """timedated's NTPSynchronized: the kernel's STA_UNSYNC flag. Any failure means not synced."""
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


def trusted_now(system: System, seen: tuple[datetime, ...] = ()) -> datetime:
    """The time key expiry counts from: the clock, raised to the newest time seen before."""
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


def _write_off_state(system: System, *, lock_pending: bool = False) -> None:
    state = {"enabled": False, "expires_at": None, **({"lock_pending": True} if lock_pending else {})}
    write_atomic(system.path(TEMP_LOGIN_STATE), json.dumps(state) + "\n", 0o600)


def _write_deny_dropin(system: System) -> None:
    write_atomic(system.path(TEMP_LOGIN_DROPIN), PASSWORD_DENY_TEXT, 0o644)


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
    was_on = state["enabled"] or state["lock_pending"] or system.path(TEMP_LOGIN_DROPIN).exists()
    if not was_on and not force:
        return False
    lock_or_deny(system)
    system.path(TEMP_LOGIN_DROPIN).unlink(missing_ok=True)
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
    expires = system.now() + timedelta(minutes=minutes)
    boot_id, boot_deadline = system.boot_id(), system.boot_time() + minutes * 60
    if not boot_id:
        raise HelperError(f"/{BOOT_ID} 를 읽을 수 없어 비밀번호를 켜지 않습니다")
    try:
        system.set_password(USER, password)
        write_atomic(system.path(TEMP_LOGIN_DROPIN), TEMP_LOGIN_DROPIN_TEXT, 0o644)
        ok, detail = system.sshd_check()
        if not ok:
            raise HelperError(f"sshd -t 가 설정을 거부했습니다: {detail}")
        write_atomic(system.path(TEMP_LOGIN_STATE),
                     json.dumps({"enabled": True, "expires_at": stamp(expires), "by": request["by"],
                                 "boot_id": boot_id, "boot_deadline": boot_deadline},
                                ensure_ascii=False) + "\n", 0o600)
        system.expire_timer(True)
        system.reload_sshd()
    except (HelperError, OSError):
        password_rollback(system)
        raise
    record(system, "password_on", minutes=minutes, expires_at=stamp(expires), by=request["by"])
    return 200, {"user": USER, "password": password, "expires_at": stamp(expires)}


def password_rollback(system: System) -> None:
    """Nothing half-on: no Match block, no password that matches. Every step runs; none raises."""
    for step, action in (("drop-in", lambda: system.path(TEMP_LOGIN_DROPIN).unlink(missing_ok=True)),
                         ("state", lambda: _write_off_state(system)),
                         ("timer", lambda: system.expire_timer(False)),
                         ("lock", lambda: lock_or_deny(system))):
        try:
            action()
        except (HelperError, OSError) as exc:
            log(f"rollback {step}: {exc}")


def expire_password(system: System) -> None:
    state = password_state(system)
    stale = not state["enabled"] and (system.path(TEMP_LOGIN_DROPIN).exists() or state["lock_pending"])
    if stale or (state["enabled"] and password_expired(system, state)):
        password_off(system, "expired")


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
    """The password first, so nothing else that is broken (a corrupt keys.json) keeps it on."""
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
