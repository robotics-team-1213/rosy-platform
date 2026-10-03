#!/usr/bin/env python3
"""Opt-in user discovery fallback for an already lingering Ubuntu site account."""

from __future__ import annotations

import argparse
import getpass
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

SYSTEM_UNITS = ("rosy-fleet-advertise.service", "rosy-overhead-advertise.service", "rosy-mdns-bridge.service")
ENABLED = ("rosy-user-fleet-advertise.service", "rosy-user-overhead-advertise.service",
           "rosy-user-mdns-bridge.timer")
LEGACY_USER_UNITS = ("rosy-site-fleet-mdns.service", "rosy-site-overhead-mdns.service")
SOURCE = Path(__file__).resolve().parent


class InstallError(ValueError):
    pass


def run(argv):
    return subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False)


def checked(runner, argv):
    result = runner(argv)
    if result.returncode:
        raise InstallError(f"host command failed: {argv[0]} {argv[1]}")
    return result.stdout.strip()


def preflight(runner=run, avahi_dir=Path("/etc/avahi/services"), user=None):
    user = user or getpass.getuser()
    if checked(runner, ["loginctl", "show-user", user, "--property=Linger", "--value"]) != "yes":
        raise InstallError("user fallback requires existing Linger=yes; it never enables linger")
    checked(runner, ["systemctl", "--user", "show-environment"])
    checked(runner, ["systemctl", "is-active", "--quiet", "avahi-daemon.service"])
    for unit in LEGACY_USER_UNITS:
        if runner(["systemctl", "--user", "is-active", "--quiet", unit]).returncode == 0:
            raise InstallError(f"user discovery already owns {unit}; stop it before installing fallback")
    for unit in SYSTEM_UNITS:
        active = runner(["systemctl", "is-active", "--quiet", unit]).returncode == 0
        if active:
            raise InstallError(f"system discovery owns {unit}; refusing competing user fallback")
    for name in ("rosy-fleet.service", "rosy-overhead.service"):
        path = avahi_dir / name
        if path.exists() and not path.is_symlink():
            metadata = path.stat()
            # A root 0600 XML is the known publisher defect: Avahi cannot read it.
            # Leave that failed system artifact untouched while explicit fallback runs.
            if metadata.st_uid == 0 and metadata.st_mode & 0o777 == 0o600 and path.is_file():
                continue
        if path.exists() or path.is_symlink():
            raise InstallError(f"system Avahi service {name} exists; refusing duplicate advertisement")


def write_file(path, data, mode):
    for entry in (path, *path.parents):
        if entry.is_symlink():
            raise InstallError("refusing symlink in installation destination")
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "posix" and path.parent.stat().st_uid != os.getuid():
        raise InstallError("installation directory must belong to the current user")
    temporary = path.with_name(path.name + ".new")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        os.chmod(temporary, mode)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def quote(value):
    if any(ord(char) < 32 for char in str(value)):
        raise InstallError("control character in unit path")
    return json.dumps(str(value)).replace("%", "%%")


def render_units(state):
    prefix = f"/usr/bin/python3 {quote(state / 'install-user-discovery.py')} --runtime"
    units = {}
    for role in ("fleet", "overhead", "bridge"):
        name = (f"rosy-user-{role}-advertise.service" if role != "bridge"
                else "rosy-user-mdns-bridge.service")
        service = ("[Unit]\nDescription=ROSY user discovery fallback\n\n[Service]\n"
                   f"Type={'oneshot' if role == 'bridge' else 'simple'}\n"
                   f"ExecStart={prefix} {role}\nNoNewPrivileges=yes\nUMask=0077\n"
                   "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6\n")
        if role != "bridge":
            service += "Restart=on-failure\nRestartSec=15s\n\n[Install]\nWantedBy=default.target\n"
        else:
            service += "TimeoutStartSec=60s\n"
        units[name] = service
    units["rosy-user-mdns-bridge.timer"] = (
        "[Unit]\nDescription=ROSY user discovery scan\n\n[Timer]\nOnBootSec=10s\n"
        "OnUnitInactiveSec=15s\nUnit=rosy-user-mdns-bridge.service\n\n[Install]\nWantedBy=timers.target\n")
    return units


def runtime_command(role, state, config):
    host, port = config["tls_host"], config["port"]
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.local", host):
        raise InstallError("TLS host must be the certificate's .local DNS name")
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise InstallError("invalid HTTPS port")
    if role == "bridge":
        return ["/usr/bin/python3", str(state / "mdns-bridge.py"), "--tls-host", host, "--port", str(port),
                "--ca-file", str(state / "site-ca.crt"), "--token-file", str(state / "discovery_token")]
    spec = importlib.util.spec_from_file_location("site_mdns", state / "fleet-mdns.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    service = ET.fromstring(module.render_service(port, role=role, tls_host=host)).find("service")
    txt = [node.text for node in service.findall("txt-record")]
    if not any(item.startswith("tls_host=") for item in txt):
        txt.append("tls_host=" + host)
    return ["/usr/bin/avahi-publish-service", "--host=" + host, "--no-fail", "ROSY " + role + " " + host,
            service.findtext("type"), str(port), *txt]


def install(home, ca, token, tls_host, port, *, runner=run,
            avahi_dir=Path("/etc/avahi/services"), user=None):
    preflight(runner, avahi_dir, user)
    state = home / ".local/share/rosy/site-discovery"
    config = {"tls_host": tls_host, "port": port}
    runtime_command("bridge", state, config)  # validate before any file or unit changes
    secret = token.read_bytes()
    if not re.fullmatch(rb"[\x21-\x7e]+\n?", secret):
        raise InstallError("selected discovery secret must be one printable ASCII token")
    write_file(state / "discovery_token", secret, 0o600)
    os.chmod(state, 0o700)
    write_file(state / "site-ca.crt", ca.read_bytes(), 0o644)
    write_file(state / "config.json", json.dumps(config).encode() + b"\n", 0o600)
    for name in ("install-user-discovery.py", "mdns-bridge.py", "fleet-mdns.py"):
        write_file(state / name, (SOURCE / name).read_bytes(), 0o644)
    units = render_units(state)
    for name, text in units.items():
        write_file(home / ".config/systemd/user" / name, text.encode(), 0o644)
    checked(runner, ["systemctl", "--user", "daemon-reload"])
    checked(runner, ["systemctl", "--user", "enable", "--now", *ENABLED])
    return list(units)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enable-user-fallback", action="store_true")
    parser.add_argument("--runtime", choices=("fleet", "overhead", "bridge"))
    parser.add_argument("--tls-host")
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--ca-file", type=Path)
    parser.add_argument("--token-file", type=Path)
    args = parser.parse_args()
    if os.name != "posix" or os.getuid() == 0:
        parser.error("run as the existing Ubuntu site user, without sudo")
    try:
        if args.runtime:
            preflight()
            config = json.loads((SOURCE / "config.json").read_text())
            argv = runtime_command(args.runtime, SOURCE, config)
            os.execv(argv[0], argv)
        if not args.enable_user_fallback or not args.tls_host or not args.ca_file or not args.token_file:
            parser.error("pass --enable-user-fallback --tls-host --ca-file --token-file explicitly")
        install(Path.home(), args.ca_file, args.token_file, args.tls_host, args.port)
        print("ROSY user discovery installed; inspect systemctl --user status rosy-user-mdns-bridge.service")
    except (InstallError, OSError, ValueError) as error:
        raise SystemExit(f"user discovery installation failed: {error}") from None


if __name__ == "__main__":
    main()
