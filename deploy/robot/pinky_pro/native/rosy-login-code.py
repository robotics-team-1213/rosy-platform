#!/usr/bin/env python3
"""Issue one-time dashboard login codes as root, outside CORE (D-193).

CORE never generates a physical login code and never writes /run/rosy-boot
(D-161). This program does, as root, with no network:

* /run/rosy-boot/login-code.json, root:rosy-core 0640: the scrypt verifier
  CORE checks a code against (code id, role, salt, digest, boot id, monotonic
  deadline). No plaintext.
* /run/rosy-boot/login-display.txt, root:rosy-display 0640: the code and role
  for the LCD (rosy-boot-display), written like D-190's ap-display.txt.
* /run/rosy-boot/login.issue, 0600: the console banner, linked from
  /etc/issue.d/60-rosy-login.issue, for a board without an LCD.

The daemon (`--daemon`, rosy-login-code.service) issues one code after the
first CORE_READY of a boot, as `login.boot_code` says (off | operator |
administrator), then clears the three files when CORE signals that the code
was used or burned (/run/rosy/login-code-state.json, read strictly) or when it
expires. It never prints a code. The command `sudo rosy-login-code [--role R]
[--minutes N]` issues a code on demand and prints it only to its own terminal.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
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
import time
from typing import Callable

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

#: Same as core_api_web.api.v1.auth: 31 symbols without 0/O/1/I/L, 8 of them (~39.6 bit).
ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
CODE_LENGTH = 8
SCRYPT = {"name": "scrypt", "n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}
SCRYPT_MAXMEM = 64 * 1024 * 1024

STATUS_DIR = "run/rosy-boot"
CODE_FILE = f"{STATUS_DIR}/login-code.json"
DISPLAY_FILE = f"{STATUS_DIR}/login-display.txt"
ISSUE_FILE = f"{STATUS_DIR}/login.issue"
LOCK_FILE = f"{STATUS_DIR}/.login.lock"
BOOT_MARK = f"{STATUS_DIR}/.login-boot-issued"
BOOT_STATUS = f"{STATUS_DIR}/boot-status.json"
CORE_STATE = "run/rosy/login-code-state.json"
BOOT_ID = "proc/sys/kernel/random/boot_id"
DEFAULTS = "etc/rosy/defaults.yaml"
POLICY = "etc/rosy/login-policy.json"

CORE_GROUP = "rosy-core"
DISPLAY_GROUP = "rosy-display"
BOOT_CODE_POLICIES = ("off", "operator", "administrator")
CLI_ROLES = ("operator", "administrator")
DEFAULT_POLICY = {"boot_code": "operator", "minutes": 10}
MAX_MINUTES = 60
MAX_STATE_BYTES = 256
STATE_CODE_ID = re.compile(r"^[0-9a-f]{16}$")
POLL_S = 1.0
#: How long the LCD says the code was burned before the line goes away.
BURNED_NOTICE_S = 60.0
BURNED_MARK = "BURNED"

Runner = Callable[[list[str]], object]
GroupLookup = Callable[[str], "int | None"]


def generate_code(choice: Callable[[str], str] = secrets.choice) -> str:
    return "".join(choice(ALPHABET) for _ in range(CODE_LENGTH))


def format_code(code: str) -> str:
    return f"{code[:4]}-{code[4:]}"


def verifier(code: str, salt: bytes) -> bytes:
    """scrypt(N=2^14, r=8, p=1) of the 8 upper-case characters, as CORE computes it."""
    return hashlib.scrypt(code.encode("ascii"), salt=salt, n=SCRYPT["n"], r=SCRYPT["r"], p=SCRYPT["p"],
                          dklen=SCRYPT["dklen"], maxmem=SCRYPT_MAXMEM)


def group_id(name: str) -> int | None:
    try:
        import grp
        return grp.getgrnam(name).gr_gid
    except (ImportError, KeyError):
        return None


def _run(command: list[str]) -> object:
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None


def _write(path: Path, content: str, mode: int, group: int | None = None) -> None:
    """D-190 pattern (rosy-network.py): random temp name; group and mode set on the empty file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            # Group and mode are set on the still-empty 0600 file, before any content.
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


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load_policy(root: Path) -> dict:
    """Image defaults (`login` in defaults.yaml), then the applied rosy-config (login-policy.json)."""
    policy = dict(DEFAULT_POLICY)
    defaults = root / DEFAULTS
    if defaults.is_file():
        try:
            import rosy_config

            policy.update(rosy_config.load_defaults(defaults).get("login", {}))
        except Exception:  # a broken defaults file keeps the built-in policy
            pass
    applied = _read_json(root / POLICY)
    if applied.get("boot_code") in BOOT_CODE_POLICIES:
        policy["boot_code"] = applied["boot_code"]
    if policy.get("boot_code") not in BOOT_CODE_POLICIES:
        policy["boot_code"] = DEFAULT_POLICY["boot_code"]
    minutes = policy.get("minutes")
    if not isinstance(minutes, int) or isinstance(minutes, bool) or not 1 <= minutes <= MAX_MINUTES:
        policy["minutes"] = DEFAULT_POLICY["minutes"]
    return policy


def read_core_state(root: Path) -> dict | None:
    """CORE's used/burned signal, or None. CORE is untrusted here (D-161).

    No symlink (O_NOFOLLOW), regular files only (a FIFO would block), at most
    MAX_STATE_BYTES, a well-formed code id and a known state; anything else is
    ignored as if the file were not there.
    """
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) \
        | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(root / CORE_STATE, flags)
    except OSError:
        return None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_STATE_BYTES:
            return None
        raw = os.read(descriptor, MAX_STATE_BYTES + 1)
    except OSError:
        return None
    finally:
        os.close(descriptor)
    if len(raw) > MAX_STATE_BYTES:
        return None
    try:
        data = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    code_id, state = data.get("code_id"), data.get("state")
    if not isinstance(code_id, str) or not STATE_CODE_ID.fullmatch(code_id) or state not in {"used", "burned"}:
        return None
    return {"code_id": code_id, "state": state}


def render_issue(formatted: str, role: str, minutes: int) -> str:
    # agetty expands backslash escapes in issue files; this text has none.
    return (f"\n  ROSY dashboard login code {formatted}  ({role}, valid {minutes} min, one use)\n"
            "  Open the dashboard on the robot LAN and choose 'robot screen code'.\n\n")


class Issuer:
    """The one writer of the three login files; the daemon and the CLI share it."""

    def __init__(self, root: Path, *, clock: Callable[[], float] = time.monotonic, run: Runner | None = None,
                 group: GroupLookup | None = None) -> None:
        self.root = root
        self.clock = clock
        # Resolved at call time, so the module's _run / group_id can be replaced as one.
        self.run = run or (lambda command: _run(command))
        self.group = group or (lambda name: group_id(name))
        self.burned_until: float | None = None

    @contextmanager
    def lock(self):
        """flock on /run/rosy-boot/.login.lock: the daemon and a CLI call never interleave."""
        try:
            import fcntl
        except ImportError:  # Windows host tests: one writer at a time anyway
            yield
            return
        directory = self.root / STATUS_DIR
        directory.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(directory / Path(LOCK_FILE).name, flags, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            os.close(descriptor)

    def boot_id(self) -> str | None:
        try:
            return (self.root / BOOT_ID).read_text(encoding="ascii").strip() or None
        except OSError:
            return None

    def _reload_consoles(self) -> None:
        self.run(["agetty", "--reload"])

    def issue(self, role: str, minutes: int, issued_by: str) -> str | None:
        """Write a new code (replacing any other); the plaintext, or None when CORE could not read it."""
        core_group = self.group(CORE_GROUP)
        boot_id = self.boot_id()
        if core_group is None or boot_id is None:
            return None
        code = generate_code()
        salt = secrets.token_bytes(16)
        record = {
            "schema_version": 1,
            "code_id": secrets.token_hex(8),
            "role": role,
            "source": "pair-physical",
            "issued_by": issued_by,
            "kdf": {**SCRYPT, "salt": salt.hex()},
            "digest": verifier(code, salt).hex(),
            "boot_id": boot_id,
            "expires_monotonic": self.clock() + minutes * 60.0,
        }
        formatted = format_code(code)
        with self.lock():
            _write(self.root / CODE_FILE, json.dumps(record, sort_keys=True) + "\n", 0o640, core_group)
            self._display(f"{formatted}\n{role}\n")
            _write(self.root / ISSUE_FILE, render_issue(formatted, role, minutes), 0o600)
            self.burned_until = None
        self._reload_consoles()
        return code

    def _display(self, content: str | None) -> None:
        """The LCD's login line; never written where rosy-display does not exist (nobody could read it)."""
        display_group = self.group(DISPLAY_GROUP)
        if content is None or display_group is None:
            (self.root / DISPLAY_FILE).unlink(missing_ok=True)
            return
        _write(self.root / DISPLAY_FILE, content, 0o640, display_group)

    def current(self) -> dict | None:
        """The code this issuer wrote (root's own file), or None."""
        data = _read_json(self.root / CODE_FILE)
        if not STATE_CODE_ID.fullmatch(str(data.get("code_id", ""))):
            return None
        return data

    def clear(self, reason: str) -> None:
        """Remove the verifier, the display line and the banner. A burned code leaves a short notice."""
        (self.root / CODE_FILE).unlink(missing_ok=True)
        (self.root / ISSUE_FILE).unlink(missing_ok=True)
        if reason == "burned":
            self._display(f"{BURNED_MARK}\n")
            self.burned_until = self.clock() + BURNED_NOTICE_S
        else:
            self._display(None)
        self._reload_consoles()

    def poll(self) -> str | None:
        """One supervision step; the reason when the files were cleared."""
        now = self.clock()
        with self.lock():
            code = self.current()
            if self.burned_until is not None and now >= self.burned_until:
                self.burned_until = None
                if code is None:  # a CLI code issued since then owns the line now
                    self._display(None)
            if code is None:
                return None
            try:
                expired = code.get("boot_id") != self.boot_id() or now >= float(code["expires_monotonic"])
            except (KeyError, TypeError, ValueError):
                expired = True
            if expired:
                self.clear("expired")
                return "expired"
            signal = read_core_state(self.root)
            if signal is not None and signal["code_id"] == code["code_id"]:
                self.clear(signal["state"])
                return signal["state"]
        return None


def core_ready(root: Path) -> bool:
    return str(_read_json(root / BOOT_STATUS).get("stage") or "") == "CORE_READY"


def boot_step(issuer: Issuer) -> str | None:
    """Issue this boot's code once, at the first CORE_READY; the action taken, if any."""
    boot_id = issuer.boot_id()
    mark = issuer.root / BOOT_MARK
    try:
        if boot_id is not None and mark.read_text(encoding="ascii").strip() == boot_id:
            return None
    except OSError:
        pass
    if not core_ready(issuer.root):
        return None
    policy = load_policy(issuer.root)
    action = "off"
    if policy["boot_code"] != "off":
        action = "issued" if issuer.issue(policy["boot_code"], policy["minutes"], "boot") else "not-issued"
    # A restart of the daemon (Restart=always) never issues a second boot code.
    _write(mark, f"{boot_id}\n", 0o600)
    return action


def daemon(issuer: Issuer, *, once: bool = False, sleep: Callable[[float], None] = time.sleep) -> int:
    # A restarted daemon has lost its burned-notice timer; a notice with no code behind it goes.
    with issuer.lock():
        if issuer.current() is None:
            issuer._display(None)
    while True:
        try:
            action = boot_step(issuer)
            if action is not None:
                # Never the code: only what happened.
                print(json.dumps({"boot_code": action}), flush=True)
            cleared = issuer.poll()
            if cleared is not None:
                print(json.dumps({"cleared": cleared}), flush=True)
        except Exception as exc:  # keep supervising; the next poll retries
            print(f"rosy-login-code: {type(exc).__name__}", file=sys.stderr, flush=True)
        if once:
            return 0
        sleep(POLL_S)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rosy-login-code",
        description="Issue a one-time dashboard login code (D-193). The code is printed here only.")
    parser.add_argument("--role", choices=CLI_ROLES, default="operator")
    parser.add_argument("--minutes", type=int, default=DEFAULT_POLICY["minutes"],
                        help=f"lifetime, 1-{MAX_MINUTES} (default {DEFAULT_POLICY['minutes']})")
    parser.add_argument("--daemon", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--once", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--root", type=Path, default=Path("/"), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    issuer = Issuer(args.root)
    if args.daemon:
        return daemon(issuer, once=args.once)
    if not 1 <= args.minutes <= MAX_MINUTES:
        parser.error(f"--minutes must be 1-{MAX_MINUTES}")
    if args.root == Path("/") and hasattr(os, "geteuid") and os.geteuid() != 0:
        print("rosy-login-code: run as root (sudo rosy-login-code)", file=sys.stderr)
        return 1
    code = issuer.issue(args.role, args.minutes, "cli")
    if code is None:
        print("rosy-login-code: CORE's group or the boot id is missing; no code issued", file=sys.stderr)
        return 1
    print(f"Login code {format_code(code)}  ({args.role}, valid {args.minutes} min, one use)")
    print("Enter it in the dashboard login drawer under 'robot screen code'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
