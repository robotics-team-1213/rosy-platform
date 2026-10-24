"""Secret-safe NetworkManager port for NetworkTransaction (no shell)."""

from __future__ import annotations

import ipaddress
import os
from pathlib import Path
import re
import subprocess
import uuid

from network_transaction import SITE_PROFILE, _secure_dir, _write


class NMError(RuntimeError):
    """Only stable codes cross the subprocess boundary; stderr may contain PSKs."""


def _escape(value):
    return value.replace("\\", "\\\\").replace(" ", "\\s").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")


class NMNetworkBackend:
    def __init__(self, *, root=Path("/"), runner=subprocess.run, interface="wlan0"):
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,15}", interface):
            raise ValueError("invalid interface")
        self.root = Path(root)
        self.runner = runner
        self.interface = interface

    def _run(self, arguments, *, timeout_s=10):
        try:
            result = self.runner(["nmcli", "--colors", "no", "--escape", "no", *arguments],
                                 capture_output=True, text=True, check=False,
                                 timeout=max(0.1, min(120, timeout_s)), env={**os.environ, "LC_ALL": "C"})
            if result.returncode:
                raise NMError("nm_command_failed")
            return result.stdout.rstrip("\r\n")
        except Exception:
            raise NMError("nm_command_failed") from None

    def _get(self, field, selector, *, timeout_s=10):
        return self._run(["-g", field, "connection", "show", *selector], timeout_s=timeout_s)

    def site_profile(self):
        listing = self._run(["-t", "-f", "UUID,NAME", "connection", "show"])
        matches = [line.split(":", 1)[0] for line in listing.splitlines()
                   if ":" in line and line.split(":", 1)[1] == SITE_PROFILE]
        if not matches:
            return None
        if len(matches) != 1:
            raise NMError("site_profile_ambiguous")
        profile_uuid = str(uuid.UUID(matches[0]))
        selector = ["uuid", profile_uuid]
        return {"uuid": profile_uuid, "name": SITE_PROFILE,
                "ssid": self._get("802-11-wireless.ssid", selector),
                "autoconnect": self._get("connection.autoconnect", selector),
                "autoconnect_priority": self._get("connection.autoconnect-priority", selector)}

    def _profile_path(self, candidate_uuid):
        candidate_uuid = str(uuid.UUID(candidate_uuid))
        directory = _secure_dir(self.root, "etc/NetworkManager/system-connections")
        return directory / ("rosy-candidate-" + candidate_uuid + ".nmconnection")

    def prepare(self, candidate_uuid, ssid, psk):
        from network_transaction import _valid

        if not _valid(ssid, psk):
            raise NMError("invalid_credentials")
        path = self._profile_path(candidate_uuid)
        if path.exists() or path.is_symlink():
            raise NMError("candidate_exists")
        temporary = path.with_name("." + path.name + "." + uuid.uuid4().hex)
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                network_secret_property = "psk"
                handle.write("[connection]\n"
                             f"id=rosy-candidate-{candidate_uuid}\nuuid={candidate_uuid}\n"
                             f"type=wifi\ninterface-name={self.interface}\nautoconnect=false\n"
                             "[wifi]\nmode=infrastructure\n"
                             # Byte lists avoid numeric-semicolon SSIDs being reinterpreted.
                             f"ssid={''.join(str(byte) + ';' for byte in ssid.encode('utf-8'))}\n"
                             "[wifi-security]\nkey-mgmt=wpa-psk\npsk-flags=0\n"
                             f"{network_secret_property}={_escape(psk)}\n"
                             "[ipv4]\nmethod=auto\n[ipv6]\nmethod=auto\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            if os.name == "posix":
                descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            try:
                self._run(["connection", "load", str(path)])
            except Exception:
                path.unlink(missing_ok=True)
                raise
        except Exception:
            raise NMError("candidate_prepare_failed") from None
        finally:
            temporary.unlink(missing_ok=True)

    def activate(self, profile_uuid, timeout_s):
        # Start asynchronously so observations and the claim heartbeat remain live.
        self._run(["--wait", "0", "connection", "up", "uuid", str(uuid.UUID(profile_uuid)),
                   "ifname", self.interface], timeout_s=timeout_s)

    def observe(self):
        raw = self._run(["-t", "-f", "GENERAL.CON-UUID,GENERAL.STATE,IP4.ADDRESS,IP4.GATEWAY",
                         "device", "show", self.interface], timeout_s=5)
        values = {}
        for line in raw.splitlines():
            key, separator, value = line.partition(":")
            if separator:
                values.setdefault(key.split("[", 1)[0], value)
        profile_uuid = values.get("GENERAL.CON-UUID")
        active = values.get("GENERAL.STATE", "").split(" ", 1)[0] == "100"
        ssid = None
        if active and profile_uuid and profile_uuid != "--":
            aps = self._run(["-t", "-f", "IN-USE,SSID", "device", "wifi", "list", "ifname",
                             self.interface, "--rescan", "no"], timeout_s=5)
            matches = [line.partition(":")[2] for line in aps.splitlines() if line.startswith("*:")]
            if len(matches) == 1:
                ssid = matches[0]
        address = values.get("IP4.ADDRESS")
        try:
            address = str(ipaddress.IPv4Interface(address).ip) if address else None
        except ValueError:
            address = None
        return {"uuid": profile_uuid if profile_uuid != "--" else None, "ssid": ssid,
                "interface": self.interface, "ipv4": address, "active": active,
                "default_route": None}

    def promote(self, candidate_uuid, previous):
        candidate_uuid = str(uuid.UUID(candidate_uuid))
        # UUID selectors keep partial promotion and retries unambiguous.
        self._run(["connection", "modify", "uuid", previous["uuid"],
                   "connection.id", "rosy-site-backup-" + previous["uuid"], "connection.autoconnect", "no"])
        self._run(["connection", "modify", "uuid", candidate_uuid,
                   "connection.id", SITE_PROFILE, "connection.autoconnect", "yes"])
        if self._get("connection.id", ["uuid", candidate_uuid]) != SITE_PROFILE:
            raise NMError("promotion_unverified")

    def restore(self, previous, timeout_s):
        expected = [previous["name"], previous.get("autoconnect", "yes"),
                    str(previous.get("autoconnect_priority", "0"))]
        current = self._get("connection.id,connection.autoconnect,connection.autoconnect-priority",
                            ["uuid", previous["uuid"]], timeout_s=min(10, timeout_s)).splitlines()
        if current != expected:
            self._run(["connection", "modify", "uuid", previous["uuid"], "connection.id", expected[0],
                       "connection.autoconnect", expected[1], "connection.autoconnect-priority", expected[2]],
                      timeout_s=min(10, timeout_s))
        self.activate(previous["uuid"], timeout_s)

    def discard(self, candidate_uuid):
        candidate_uuid = str(uuid.UUID(candidate_uuid))
        profiles = self._run(["-g", "UUID", "connection", "show"])
        if candidate_uuid in profiles.splitlines():
            self._run(["connection", "delete", "uuid", candidate_uuid])
        self._profile_path(candidate_uuid).unlink(missing_ok=True)

    def request_recovery(self):
        # The fallback owner consumes a request; this adapter never opens an AP.
        directory = _secure_dir(self.root, "var/lib/rosy/network")
        _write(directory / "recovery-request.json", {"source": "network-transaction"})
