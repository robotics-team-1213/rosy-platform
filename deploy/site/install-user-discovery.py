#!/usr/bin/env python3
"""Opt-in user discovery fallback for an already lingering Ubuntu site account."""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import ssl
import subprocess
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
        "OnUnitInactiveSec=15s\nAccuracySec=1s\nUnit=rosy-user-mdns-bridge.service\n\n[Install]\n"
        "WantedBy=timers.target\n")
    return units


def verify_camera_peer(host, port, ca):
    """Read only the real receiver identity over the existing verified TLS anchor."""
    context = ssl.create_default_context(cafile=str(ca))
    context.verify_flags |= ssl.VERIFY_X509_STRICT
    anchors = context.get_ca_certs(binary_form=True)
    if len(anchors) != 1:
        raise InstallError("camera peer requires one existing site CA")
    with socket.create_connection(("127.0.0.1", port), timeout=5) as raw:
        with context.wrap_socket(raw, server_hostname=host) as secured:
            secured.settimeout(5)
            secured.sendall((f"GET /api/fleet/pairing/v2/identity HTTP/1.1\r\n"
                             f"Host: {host}:{port}\r\nConnection: close\r\n\r\n").encode("ascii"))
            response = http.client.HTTPResponse(secured)
            response.begin()
            if response.status != 200:
                raise InstallError("camera peer receiver identity unavailable")
            payload = response.read(16385)
    return camera_peer_binding(payload, host, anchors[0])


def camera_peer_binding(payload, host, anchor):
    """Capability verification is metadata only, never an approval or credential."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise InstallError("duplicate receiver identity field")
            result[key] = value
        return result
    profile = {"profile": "rosy.camera-peer/1", "audience": "fleet-camera-ingest",
               "device_kind": "overhead-camera", "source_role": "camera"}
    try:
        if len(payload) > 16384:
            raise ValueError("bounded receiver identity required")
        identity = json.loads(payload, object_pairs_hook=pairs)
        fields = {*profile, "receiver_id", "receiver_public_key", "receiver_key_sha256",
                  "tls_hostname", "tls_ca_pem", "tls_ca_sha256"}
        if not isinstance(identity, dict) or set(identity) != fields:
            raise ValueError("complete receiver identity required")
        if any(identity[key] != value for key, value in profile.items()):
            raise ValueError("camera receiver profile mismatch")
        key = base64.b64decode(identity["receiver_public_key"], validate=True)
        # Canonical P-256 SPKI, matching the fixed camera relationship wire.
        if (len(key) != 91 or key[:27] != bytes.fromhex(
                "30 59 30 13 06 07 2a 86 48 ce 3d 02 01 06 08 2a 86 48 ce 3d 03 01 07 03 42 00 04")
                or base64.b64encode(key).decode() != identity["receiver_public_key"]):
            raise ValueError("canonical receiver identity key required")
        digest = hashlib.sha256(key).hexdigest()
        if (identity["receiver_key_sha256"] != digest
                or identity["receiver_id"] != "fleet-" + digest[:32]
                or identity["tls_hostname"] != host
                or identity["tls_ca_sha256"] != hashlib.sha256(anchor).hexdigest()
                or ssl.PEM_cert_to_DER_cert(identity["tls_ca_pem"]) != anchor):
            raise ValueError("receiver identity or TLS anchor mismatch")
    except (ValueError, TypeError, KeyError) as error:
        raise InstallError("verified camera receiver capability unavailable") from error
    return {"receiver_id": identity["receiver_id"], "receiver_key_sha256": digest}


def runtime_command(role, state, config):
    host, port = config["tls_host"], config["port"]
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.local", host):
        raise InstallError("TLS host must be the certificate's .local DNS name")
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise InstallError("invalid HTTPS port")
    pair, camera_peer = config.get("pair", False), config.get("camera_peer", False)
    if type(pair) is not bool or type(camera_peer) is not bool or (camera_peer and not pair):
        raise InstallError("explicit boolean camera capability requires pairing")
    if role == "bridge":
        return ["/usr/bin/python3", str(state / "mdns-bridge.py"), "--tls-host", host, "--port", str(port),
                "--ca-file", str(state / "site-ca.crt"), "--token-file", str(state / "discovery_token")]
    spec = importlib.util.spec_from_file_location("site_mdns", state / "fleet-mdns.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if role == "overhead" and camera_peer:
        binding = verify_camera_peer(host, port, state / "site-ca.crt")
        if binding != config.get("camera_peer_binding"):
            raise InstallError("configured camera receiver identity changed")
    service = ET.fromstring(module.render_service(
        port, role=role, tls_host=host, pair=pair and role == "overhead",
        camera_peer=camera_peer and role == "overhead")).find("service")
    txt = [node.text for node in service.findall("txt-record")]
    if not any(item.startswith("tls_host=") for item in txt):
        txt.append("tls_host=" + host)
    return ["/usr/bin/avahi-publish-service", "--host=" + host, "--no-fail", "ROSY " + role + " " + host,
            service.findtext("type"), str(port), *txt]


def install(home, ca, token, tls_host, port, *, runner=run,
            avahi_dir=Path("/etc/avahi/services"), user=None, pair=False, camera_peer=False):
    if type(pair) is not bool or type(camera_peer) is not bool:
        raise InstallError("explicit boolean discovery capabilities required")
    preflight(runner, avahi_dir, user)
    state = home / ".local/share/rosy/site-discovery"
    config = {"tls_host": tls_host, "port": port}
    if pair or camera_peer:
        config.update(pair=pair, camera_peer=camera_peer)
    runtime_command("bridge", state, config)  # validate before any file or unit changes
    if camera_peer:
        config["camera_peer_binding"] = verify_camera_peer(tls_host, port, ca)
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
    parser.add_argument("--pair", action="store_true", help="advertise explicitly configured overhead pairing")
    parser.add_argument("--camera-peer", action="store_true", help="verify and advertise camera peer profile (requires --pair)")
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
        install(Path.home(), args.ca_file, args.token_file, args.tls_host, args.port,
                pair=args.pair, camera_peer=args.camera_peer)
        print("ROSY user discovery installed; inspect systemctl --user status rosy-user-mdns-bridge.service")
    except (InstallError, OSError, ValueError) as error:
        raise SystemExit(f"user discovery installation failed: {error}") from None


if __name__ == "__main__":
    main()
