#!/usr/bin/env python3
"""Filesystem, network and account helpers for the image firstboot entrypoint."""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import stat
import subprocess
import sys
import tempfile
import time
from typing import Callable
from os_state_io import SERIAL as SERIAL, _json_atomic as _json_atomic, _write_atomic as _write_atomic


try:
    from deploy.robot.pinky_pro.sd.personalization import (
        DeviceIdentity, generate_device_identity, operator_key_fingerprint,
        validate_device_identity, validate_provision_bundle,
    )
except ModuleNotFoundError:  # Installed image layout.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from deploy.sd.personalization import (
        DeviceIdentity, generate_device_identity, operator_key_fingerprint,
        validate_device_identity, validate_provision_bundle,
    )


NETWORK_HANDOFF_SCHEMA = 1


def _native_helper(name: str):
    candidates = (Path(__file__).resolve().parent,)
    for candidate in candidates:
        if (candidate / f'{name}.py').is_file():
            if str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
            source_helpers = candidate.parent / 'release'
            if (source_helpers / 'network_transaction.py').is_file():
                sys.path.insert(0, str(source_helpers))
            break
    return importlib.import_module(name)


def _handoff():
    return _native_helper('network_handoff')


def _observe_network(_profile_uuid: str) -> dict:
    _handoff()
    from nm_network import NMNetworkBackend
    return NMNetworkBackend().observe()


SITE_PROFILE = "rosy-site-sta"
# Site Wi-Fi activation budget. 2026-09-24, rosy-pinky-e4us (release
# 2026.09.24-010) on a phone hotspot: NM started the profile at 18.7 s, the
# first association failed at 44.0 s (25 s), NM's own autoconnect retry began
# at 77.6 s and was up at 84.9 s, 66 s after the first try. One failed attempt
# used to discard the profile and fail the boot. Three attempts of at most 30 s
# with 15 s pauses cover those 66 s almost twice over, and the 120 s ceiling
# matches the grace D-176 gives the site Wi-Fi before the fallback AP opens.
NETWORK_ATTEMPTS = 3
NETWORK_ATTEMPT_WAIT_S = 30
NETWORK_RETRY_PAUSE_S = 15
NETWORK_BUDGET_S = 120
# While NM is still associating on its own, poll instead of issuing `up`,
# which would restart the association it is in the middle of.
NETWORK_ACTIVATING_POLL_S = 5
SITE_PROFILE_PATH = f"etc/NetworkManager/system-connections/{SITE_PROFILE}.nmconnection"
HELD = {"state": "PROVISIONING_AP", "reason": "site_wifi_unreachable"}


def _nmcli(command: list[str], timeout: float) -> tuple[int, str]:
    """Run nmcli quietly; a hang or a missing binary is a failed attempt."""
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, check=False, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""
    return result.returncode, result.stdout


def _profile_state(profile: str, run: Callable[[list[str], float], tuple[int, str]]) -> str:
    """NM's GENERAL.STATE for the profile ("activated", "activating", ... or "")."""
    _code, output = run(["nmcli", "-t", "-f", "GENERAL.STATE", "connection", "show", profile], 15)
    return output.strip().rsplit(":", 1)[-1] if output.strip() else ""


def site_wifi_up(profile: str, run: Callable[[list[str], float], tuple[int, str]] = _nmcli) -> bool:
    """True when NetworkManager reports the profile activated (by us or by autoconnect)."""
    return _profile_state(profile, run) == "activated"


def activate_site_wifi(
    profile: str,
    *,
    run: Callable[[list[str], float], tuple[int, str]] = _nmcli,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    attempts: int = NETWORK_ATTEMPTS,
    attempt_wait_s: int = NETWORK_ATTEMPT_WAIT_S,
    pause_s: float = NETWORK_RETRY_PAUSE_S,
    budget_s: float = NETWORK_BUDGET_S,
) -> bool:
    """Bring the site profile up, retrying within a bounded budget.

    Before each attempt the profile state is checked, so an association NM's
    autoconnect finished during a pause counts and is not torn down, and one it
    is still making is waited for (within the budget) rather than restarted.
    """
    deadline = clock() + budget_s
    run(["nmcli", "connection", "reload"], 20)
    for attempt in range(attempts):
        if attempt:
            remaining = deadline - clock()
            if remaining <= 0:
                break
            sleep(min(pause_s, remaining))
        state = _profile_state(profile, run)
        while state == "activating" and deadline - clock() > 0:
            sleep(min(NETWORK_ACTIVATING_POLL_S, deadline - clock()))
            state = _profile_state(profile, run)
        if state == "activated":
            return True
        wait = int(min(attempt_wait_s, deadline - clock()))
        if wait < 1:
            break
        code, _output = run(["nmcli", "--wait", str(wait), "connection", "up", profile,
                             "ifname", "wlan0"], wait + 10)
        if code == 0:
            return True
    return site_wifi_up(profile, run)


def _default_network_activate(profile: str) -> bool:
    return activate_site_wifi(profile)


def _default_hostname_apply(hostname: str) -> None:
    """Rename the running system and let avahi announce the new name (D-174 F2)."""
    if socket.gethostname() == hostname:
        return
    quiet = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
             "stderr": subprocess.DEVNULL, "check": False, "timeout": 20}
    if subprocess.run(["hostnamectl", "set-hostname", hostname], **quiet).returncode != 0:
        if subprocess.run(["hostname", hostname], **quiet).returncode != 0:
            raise OSError("could not set the live hostname")
    subprocess.run(["systemctl", "try-restart", "avahi-daemon.service"], **quiet)


OPERATOR_USER = "rosy"
# D-191: rosy-core.service runs with HOME=/var/lib/rosy/core and no ROSY_CONFIG,
# so core_common.config reads (and the dashboard writes) Path.home()/.rosy/rosy.yaml.
CORE_USER = "rosy-core"
CORE_HOME = "var/lib/rosy/core"
CORE_OVERLAY = f"{CORE_HOME}/.rosy/rosy.yaml"
_NOFOLLOW_FS = (hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_DIRECTORY")
                and os.open in os.supports_dir_fd and os.replace in os.supports_dir_fd)


def _open_directory(name: str, parent: int, *, create_mode: int) -> int:
    """Open (creating if missing) one directory under `parent`, never through a link."""
    created = False
    try:
        os.mkdir(name, create_mode, dir_fd=parent)
        created = True
    except FileExistsError:
        pass
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    except OSError as exc:
        # ELOOP: a symlink; ENOTDIR: something else in the way.
        raise ValueError(f"CORE config path component {name} is a symlink or not a directory") from exc
    if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ValueError(f"CORE config path component {name} is not a directory")
    if created:
        os.fchmod(descriptor, create_mode)  # the unit's UMask would narrow the mkdir mode
    return descriptor


def _decode_overlay(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("CORE config overlay is unreadable") from exc


def _read_regular(name: str, parent: int) -> str | None:
    """Read an existing regular file under `parent` without following a link."""
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ValueError("CORE config overlay is a symlink or cannot be opened") from exc
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("CORE config overlay is not a regular file")
        return _decode_overlay(stream.read())


def _default_operator_account(name: str) -> None:
    """Create the key-only operator login if it does not exist (D-174 F3)."""
    quiet = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
             "stderr": subprocess.DEVNULL, "check": False, "timeout": 30}
    if subprocess.run(["id", "-u", name], **quiet).returncode == 0:
        return
    # No password is set, so the account is locked for password logins.
    created = subprocess.run(
        ["useradd", "--create-home", "--shell", "/bin/bash",
         "--groups", "systemd-journal,adm", name], **quiet)
    if created.returncode != 0:
        raise OSError("could not create the operator account")


# D-225 2.2: the image ships its factory release unsigned; the bundle carries
# the offline signature over its SHA256SUMS.
TRUSTED_RELEASE_KEY = "etc/rosy/trusted-release-keys/rosy-release-2026-01.pem"
_NATIVE_RELEASE_CANDIDATES = (Path(__file__).with_name("native_release.py"),)


def _native_release():
    """native_release.py, loaded from the checkout or the image's native runtime."""
    import importlib.util

    path = next((candidate for candidate in _NATIVE_RELEASE_CANDIDATES if candidate.is_file()), None)
    if path is None:
        raise OSError("native_release.py is not installed")
    # The installed copy imports signing.py from its own directory.
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("rosy_native_release", path)
    if spec is None or spec.loader is None:
        raise OSError("native_release.py cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _system_account(name: str) -> dict | None:
    import pwd

    try:
        entry = pwd.getpwnam(name)
    except KeyError:
        return None
    return {"home": entry.pw_dir, "shell": entry.pw_shell, "uid": entry.pw_uid, "gid": entry.pw_gid}


