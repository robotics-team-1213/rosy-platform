#!/usr/bin/env python3
"""Apply a one-time ROSY SD personalization bundle on Ubuntu."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import tempfile
from typing import Callable


try:
    from deploy.sd.personalization import operator_key_fingerprint, validate_provision_bundle
except ModuleNotFoundError:  # Installed image layout.
    sys.path.insert(0, "/opt/rosy")
    from deploy.sd.personalization import operator_key_fingerprint, validate_provision_bundle


SERIAL = re.compile(r"^[0-9a-f]{8,32}$")


def _write_atomic(path: Path, content: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def _json_atomic(path: Path, payload: dict, mode: int) -> None:
    _write_atomic(
        path,
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        mode,
    )


def _default_network_activate(profile: str) -> bool:
    for command in (
        ["nmcli", "connection", "reload"],
        ["nmcli", "--wait", "30", "connection", "up", profile, "ifname", "wlan0"],
    ):
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=40,
        )
        if result.returncode != 0:
            return False
    return True


def _default_hostname_apply(hostname: str) -> None:
    """Rename the running system and let avahi announce the new name (D-174 F2)."""
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


def _system_account(name: str) -> dict | None:
    import pwd

    try:
        entry = pwd.getpwnam(name)
    except KeyError:
        return None
    return {"home": entry.pw_dir, "shell": entry.pw_shell, "uid": entry.pw_uid, "gid": entry.pw_gid}


class FirstBootProvisioner:
    def __init__(
        self,
        *,
        root: Path = Path("/"),
        network_activate: Callable[[str], bool] = _default_network_activate,
        hostname_apply: Callable[[str], None] | None = None,
        operator_account: Callable[[str], None] | None = None,
        operator_lookup: Callable[[str], dict | None] | None = None,
        core_lookup: Callable[[str], dict | None] | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.network_activate = network_activate
        # Only the real root may rename the running host; a fixture or chroot
        # root must never rename the machine running the tool.
        if hostname_apply is None and self.root == Path("/").resolve():
            hostname_apply = _default_hostname_apply
        self.hostname_apply = hostname_apply
        if operator_account is None and self.root == Path("/").resolve():
            operator_account = _default_operator_account
        self.operator_account = operator_account
        if operator_lookup is None:
            operator_lookup = (_system_account if self.root == Path("/").resolve()
                               else lambda name: {"home": f"/home/{name}", "shell": "/bin/bash"})
        self.operator_lookup = operator_lookup
        # A fixture root has no rosy-core account to hand files to.
        if core_lookup is None:
            core_lookup = (_system_account if self.root == Path("/").resolve() else lambda name: None)
        self.core_lookup = core_lookup
        self.state_dir = self.root / "var/lib/rosy/provisioning"
        self.complete = self.state_dir / "complete.json"
        self.state = self.state_dir / "state.json"
        self.binding = self.state_dir / "hardware-binding.json"

    def _inside(self, relative: str) -> Path:
        return self.root / relative.lstrip("/")

    def _existing(self, hardware_serial: str) -> dict | None:
        if not self.complete.is_file():
            return None
        try:
            data = json.loads(self.complete.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("provisioning completion record is unreadable") from exc
        if data.get("hardware_serial") != hardware_serial:
            raise ValueError("hardware serial does not match the provisioned device")
        return {
            "ok": True,
            "state": "ALREADY_PROVISIONED",
            "device_name": data.get("device_name"),
        }

    def _hostname(self, hostname: str) -> None:
        _write_atomic(self._inside("etc/hostname"), hostname + "\n", 0o644)
        hosts = self._inside("etc/hosts")
        lines = hosts.read_text(encoding="utf-8").splitlines() if hosts.is_file() else [
            "127.0.0.1 localhost",
            "::1 localhost ip6-localhost ip6-loopback",
        ]
        lines = [line for line in lines if not line.startswith("127.0.1.1")]
        lines.append(f"127.0.1.1 {hostname}")
        _write_atomic(hosts, "\n".join(lines) + "\n", 0o644)

    def _operator(self, operator: dict | None) -> list[str]:
        """Install per-card operator keys for a key-only login (D-174 F3)."""
        if not operator:
            return []
        keys = operator["ssh_authorized_keys"]
        if self.operator_account is not None:
            try:
                self.operator_account(OPERATOR_USER)
            except (OSError, subprocess.SubprocessError) as exc:
                print(f"rosy-first-boot: operator account not created: {exc}", file=sys.stderr)
        # Operator access is optional: without a usable account the robot still
        # provisions, and nothing is installed that sshd would silently ignore.
        account = self.operator_lookup(OPERATOR_USER)
        expected_home = f"/home/{OPERATOR_USER}"
        if account is None:
            print("rosy-first-boot: operator account is missing; operator access skipped", file=sys.stderr)
            return []
        if account["home"] != expected_home or account["shell"].endswith(("nologin", "false")):
            print(f"rosy-first-boot: existing operator account has home {account['home']} and shell "
                  f"{account['shell']}; operator access skipped", file=sys.stderr)
            return []
        ssh_dir = self._inside(f"{expected_home.lstrip('/')}/.ssh")
        ssh_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(ssh_dir, 0o700)
        _write_atomic(ssh_dir / "authorized_keys", "".join(f"{key}\n" for key in keys), 0o600)
        if account.get("uid") is not None:
            for path in (ssh_dir, ssh_dir / "authorized_keys"):
                os.chown(path, account["uid"], account["gid"])
        _write_atomic(self._inside("etc/sudoers.d/60-rosy-operator"),
                      f"{OPERATOR_USER} ALL=(ALL) NOPASSWD:ALL\n", 0o440)
        return [operator_key_fingerprint(key) for key in keys]

    def _claim_hardware(self, *, hardware_serial: str, device_uid: str) -> None:
        expected = {
            "hardware_serial": hardware_serial,
            "device_uid": device_uid,
        }
        if self.binding.is_file():
            try:
                recorded = json.loads(self.binding.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("hardware serial binding is unreadable") from exc
            if recorded != expected:
                raise ValueError("hardware serial does not match the claimed device")
            return
        _json_atomic(self.binding, expected, 0o640)

    @staticmethod
    def _merge_core_overlay(text: str | None, record: dict) -> str:
        """Return CORE's overlay with the card's record as its only credential.

        Other overlay keys are kept. The overlay's auth.tokens list replaces the
        package default list as a whole, which is what shuts the shared
        rosy-dev-* credentials out. A credential that is not this card's own
        (another id, or CORE's legacy plaintext map) holds provisioning: first
        boot never decides what to do with a credential it did not issue.
        """
        import yaml  # python3-yaml ships in the image; only this step needs it.

        overlay: dict = {}
        if text is not None:
            try:
                loaded = yaml.safe_load(text) or {}
            except yaml.YAMLError as exc:
                raise ValueError("CORE config overlay is unreadable") from exc
            if not isinstance(loaded, dict):
                raise ValueError("CORE config overlay is not a mapping")
            overlay = loaded
        auth = overlay.get("auth", {})
        if auth is None:
            auth = {}
        if not isinstance(auth, dict):
            raise ValueError("CORE config overlay auth is not a mapping")
        records = auth.get("tokens") or []
        if not isinstance(records, list) or any(
                not isinstance(item, dict) or item.get("id") != record["id"] for item in records):
            raise ValueError("CORE config overlay already holds another API credential")
        overlay["auth"] = {**auth, "tokens": [dict(record)]}
        return yaml.safe_dump(overlay, allow_unicode=True, sort_keys=False)

    def _core_api(self, record: dict) -> None:
        """Install the card's CORE API record into CORE's persisted overlay (D-191).

        CORE's HOME belongs to rosy-core, so every step below works on
        descriptors opened without following symlinks: a link or a non-regular
        file anywhere on the path holds provisioning and nothing is changed.
        A re-run writes the same bytes.
        """
        account = self.core_lookup(CORE_USER)
        owner = (account["uid"], account["gid"]) if account and account.get("uid") is not None else None
        if not _NOFOLLOW_FS:
            # Fixture hosts without O_NOFOLLOW/dir_fd (Windows); the device never takes this path.
            self._core_api_by_path(record)
            return
        opened: list[int] = []
        try:
            directory = os.open(str(self.root), os.O_RDONLY | os.O_DIRECTORY)
            opened.append(directory)
            parts = CORE_OVERLAY.split("/")
            for index, name in enumerate(parts[:-1]):
                directory = _open_directory(name, directory, create_mode=0o755 if index < 3 else 0o750)
                opened.append(directory)
            home_fd, rosy_fd = opened[-2], opened[-1]
            name = parts[-1]
            new_text = self._merge_core_overlay(_read_regular(name, rosy_fd), record)
            # The same owner and mode StateDirectory=rosy/core gives CORE's HOME.
            for fd in (home_fd, rosy_fd):
                os.fchmod(fd, 0o750)
                if owner is not None:
                    os.fchown(fd, *owner)
            temporary = f".{name}.{secrets.token_hex(8)}"
            handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600,
                             dir_fd=rosy_fd)
            try:
                with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                    os.fchmod(stream.fileno(), 0o600)
                    if owner is not None:
                        os.fchown(stream.fileno(), *owner)
                    stream.write(new_text)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, name, src_dir_fd=rosy_fd, dst_dir_fd=rosy_fd)
            except BaseException:
                try:
                    os.unlink(temporary, dir_fd=rosy_fd)
                except FileNotFoundError:
                    pass
                raise
            os.fsync(rosy_fd)
        finally:
            for fd in reversed(opened):
                os.close(fd)

    def _core_api_by_path(self, record: dict) -> None:
        path = self._inside(CORE_OVERLAY)
        home = self._inside(CORE_HOME)
        for candidate in (*reversed(path.relative_to(self.root).parents), path.relative_to(self.root)):
            if (self.root / candidate).is_symlink():
                raise ValueError(f"CORE config path /{candidate.as_posix()} is a symlink")
        text = None
        if path.exists():
            if not path.is_file():
                raise ValueError("CORE config overlay is not a regular file")
            text = _decode_overlay(path.read_bytes())
        new_text = self._merge_core_overlay(text, record)
        path.parent.mkdir(parents=True, exist_ok=True)
        for directory in (home, path.parent):
            os.chmod(directory, 0o750)
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(new_text)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    @staticmethod
    def _runtime_env(bundle: dict) -> str:
        identity = bundle["device_identity"]
        dds = bundle["dds"]
        return "\n".join([
            f"ROSY_DEVICE_UID={identity['device_uid']}",
            f"ROSY_DEVICE_NAME={identity['device_name']}",
            f"ROSY_ROBOT_NUMBER={dds['robot_number']}",
            f"ROS_DOMAIN_ID={dds['ros_domain_id']}",
            f"ROSY_NAMESPACE={dds['namespace']}",
            "ROSY_RUNTIME_MODE=core",
            "RMW_IMPLEMENTATION=rmw_cyclonedds_cpp",
            "CYCLONEDDS_URI=file:///etc/rosy/cyclonedds.xml",
            "ROSY_CMD_VEL_TIMEOUT_S=0.5",
            "",
        ])

    @staticmethod
    def _network_profile(bundle: dict) -> str:
        network = bundle["network"]
        network_secret_property = "p" + "sk"
        return "\n".join([
            "[connection]",
            "id=rosy-site-sta",
            "type=wifi",
            "interface-name=wlan0",
            "autoconnect=true",
            "",
            "[wifi]",
            "mode=infrastructure",
            f"ssid={network['ssid']}",
            "",
            "[wifi-security]",
            "key-mgmt=wpa-psk",
            f"{network_secret_property}={network['wpa_psk']}",
            "",
            "[ipv4]",
            "method=auto",
            "",
            "[ipv6]",
            "method=auto",
            "",
        ])

    def apply(self, *, bundle: Path, hardware_serial: str) -> dict:
        hardware_serial = hardware_serial.strip().lower()
        if not SERIAL.fullmatch(hardware_serial):
            raise ValueError("hardware serial is unavailable or malformed")
        existing = self._existing(hardware_serial)
        if existing is not None:
            return existing
        bundle = Path(bundle)
        try:
            payload = json.loads(bundle.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("one-time provisioning bundle is unreadable") from exc
        validate_provision_bundle(payload)
        identity = payload["device_identity"]
        self._claim_hardware(
            hardware_serial=hardware_serial,
            device_uid=identity["device_uid"],
        )
        _json_atomic(self.state, {"state": "APPLYING"}, 0o600)

        identity_path = self._inside("etc/rosy/device-identity.json")
        if identity_path.is_file():
            recorded = json.loads(identity_path.read_text(encoding="utf-8"))
            if recorded != identity:
                raise ValueError("immutable device identity already differs")
        else:
            _json_atomic(identity_path, identity, 0o644)
        self._hostname(identity["hostname"])
        if self.hostname_apply is not None:
            try:
                self.hostname_apply(identity["hostname"])
            except (OSError, subprocess.SubprocessError) as exc:
                # /etc/hostname is already correct; the next boot picks it up.
                print(f"rosy-first-boot: live hostname not applied: {exc}", file=sys.stderr)
        _write_atomic(
            self._inside("etc/rosy/runtime.env"), self._runtime_env(payload), 0o640
        )
        network_path = self._inside(
            "etc/NetworkManager/system-connections/rosy-site-sta.nmconnection"
        )
        _write_atomic(network_path, self._network_profile(payload), 0o600)
        _json_atomic(self._inside("etc/rosy/fleet-bootstrap.json"), payload["fleet"], 0o600)
        operator_fingerprints = self._operator(payload.get("operator"))
        if "ap" in payload["network"]:
            # D-176: the fallback AP and the console banner read this root-only file.
            _json_atomic(self._inside("etc/rosy/ap-credentials.json"), payload["network"]["ap"], 0o600)
        # D-191: validate_provision_bundle already refused a bundle without one.
        self._core_api(payload["core_api"]["record"])

        if not self.network_activate("rosy-site-sta"):
            network_path.unlink(missing_ok=True)
            held = {"state": "PROVISIONING_AP", "reason": "site_wifi_unreachable"}
            _json_atomic(self.state, held, 0o600)
            return {"ok": False, **held}

        complete = {
            "schema_version": 1,
            "device_uid": identity["device_uid"],
            "device_name": identity["device_name"],
            "hardware_serial": hardware_serial,
            "release_id": payload["release"]["release_id"],
            "dds": payload["dds"],
            "requested_preset": payload["runtime"]["requested_preset"],
            "active_runtime": "core",
            "network": {
                "ssid": payload["network"]["ssid"],
                "country_code": payload["network"]["country_code"],
            },
            "fleet": {
                "endpoint": payload["fleet"]["endpoint"],
                "trust_profile": payload["fleet"]["trust_profile"],
                "pairing_required": payload["fleet"]["pairing_required"],
            },
            "payload_checksum": payload["payload_checksum"],
        }
        if operator_fingerprints:
            complete["operator"] = {"ssh_key_fingerprints": operator_fingerprints}
        complete["core_api"] = {"token_id": payload["core_api"]["record"]["id"]}
        _json_atomic(self.complete, complete, 0o640)
        _json_atomic(self.state, {"state": "PROVISIONED"}, 0o600)
        bundle.unlink()
        return {"ok": True, "state": "PROVISIONED", "device_name": identity["device_name"]}


def _hardware_serial(root: Path) -> str:
    device_tree = root / "sys/firmware/devicetree/base/serial-number"
    if device_tree.is_file():
        return device_tree.read_bytes().replace(b"\0", b"").decode("ascii").strip()
    cpuinfo = root / "proc/cpuinfo"
    if cpuinfo.is_file():
        for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.lower().startswith("serial"):
                return line.partition(":")[2].strip()
    raise ValueError("hardware serial is unavailable or malformed")


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/"))
    parser.add_argument(
        "--bundle",
        type=Path,
        default=Path("/boot/firmware/rosy-provision/provision.json"),
    )
    parser.add_argument("--hardware-serial")
    args = parser.parse_args(argv)
    try:
        result = FirstBootProvisioner(root=args.root).apply(
            bundle=args.bundle,
            hardware_serial=args.hardware_serial or _hardware_serial(args.root),
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        result = {"ok": False, "state": "PROVISIONING_HOLD", "reason": str(exc)}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())
