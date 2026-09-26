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
import time
from typing import Callable


try:
    from deploy.sd.personalization import (
        DeviceIdentity, generate_device_identity, operator_key_fingerprint,
        validate_device_identity, validate_provision_bundle,
    )
except ModuleNotFoundError:  # Installed image layout.
    sys.path.insert(0, "/opt/rosy")
    from deploy.sd.personalization import (
        DeviceIdentity, generate_device_identity, operator_key_fingerprint,
        validate_device_identity, validate_provision_bundle,
    )


SERIAL = re.compile(r"^[0-9a-f]{8,32}$")


def _write_atomic(path: Path, content: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # A unique temporary name: a manual run and the retry timer never share one.
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _json_atomic(path: Path, payload: dict, mode: int) -> None:
    _write_atomic(
        path,
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        mode,
    )


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
_NATIVE_RELEASE_CANDIDATES = (
    Path(__file__).resolve().parents[3] / "deploy/robot/native/native_release.py",  # checkout
    Path("/opt/rosy/native-runtime/native_release.py"),  # installed image
)


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
        self.new_device_setup = self.state_dir / "new-device-setup.json"

    def _inside(self, relative: str) -> Path:
        return self.root / relative.lstrip("/")

    def _existing(self, hardware_serial: str) -> dict | None:
        if not self.complete.is_file():
            if self.new_device_setup.exists():
                raise ValueError("new-device setup is missing its previous completion record")
            return None
        try:
            data = json.loads(self.complete.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("provisioning completion record is unreadable") from exc
        if self.new_device_setup.is_file():
            try:
                pending = json.loads(self.new_device_setup.read_text(encoding="utf-8"))
                identity = validate_device_identity(DeviceIdentity(**pending["device_identity"]))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise ValueError("new-device setup record is unreadable or invalid") from exc
            if (pending.get("schema_version") != 1
                    or pending.get("prior_device_uid") != data.get("device_uid")
                    or pending.get("prior_hardware_serial") != data.get("hardware_serial")):
                raise ValueError("new-device setup does not match the previous device")
            if pending.get("hardware_serial") != hardware_serial:
                _json_atomic(
                    self.state,
                    {"state": "PROVISIONING_HOLD", "reason": "setup_bound_to_different_board"},
                    0o600,
                )
                raise ValueError("new-device setup is bound to a different board")
            held = {"state": "NEW_DEVICE_SETUP", "reason": "hardware_changed"}
            try:
                current_state = json.loads(self.state.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                current_state = None
            if current_state != held:
                _json_atomic(self.state, held, 0o600)
            return {"ok": False, "state": "NEW_DEVICE_SETUP", "device_name": identity.device_name}
        if data.get("hardware_serial") != hardware_serial:
            return self._stage_new_device(data, hardware_serial)
        return {
            "ok": True,
            "state": "ALREADY_PROVISIONED",
            "device_name": data.get("device_name"),
        }

    def _stage_new_device(self, previous: dict, hardware_serial: str) -> dict:
        """Keep the previous installation inert and stage a fresh identity.

        The existing CORE gate still fails until the operator registers the new
        robot on a verified card. Site Wi-Fi and SSH remain available for that
        handoff; no old robot number, API token or Fleet credential is reused.
        """
        try:
            binding = json.loads(self.binding.read_text(encoding="utf-8"))
            raw_identity = json.loads(self._inside("etc/rosy/device-identity.json").read_text(encoding="utf-8"))
            identity = validate_device_identity(DeviceIdentity(**raw_identity))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError("previous device identity cannot be verified") from exc
        if (binding != {"hardware_serial": previous.get("hardware_serial"),
                        "device_uid": previous.get("device_uid")}
                or identity.device_uid != previous.get("device_uid")
                or identity.device_name != previous.get("device_name")
                or identity.model != "pinky_pro"):
            raise ValueError("previous device identity cannot be verified")
        if not self._inside(SITE_PROFILE_PATH).is_file():
            raise ValueError("site Wi-Fi profile is unavailable for new-device setup")
        fresh = generate_device_identity("pinky_pro", registered_names={previous["device_name"]})
        pending = {
            "schema_version": 1,
            "hardware_serial": hardware_serial,
            "prior_hardware_serial": previous["hardware_serial"],
            "prior_device_uid": previous["device_uid"],
            "device_identity": {
                "device_uid": fresh.device_uid,
                "device_name": fresh.device_name,
                "hostname": fresh.hostname,
                "model": fresh.model,
            },
        }
        _json_atomic(self.new_device_setup, pending, 0o600)
        _json_atomic(self.state, {"state": "NEW_DEVICE_SETUP", "reason": "hardware_changed"}, 0o600)
        return {"ok": False, "state": "NEW_DEVICE_SETUP", "device_name": fresh.device_name}

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
        # D-193 5: the card's credential is listed (and whoami answers) as `card`.
        overlay["auth"] = {**auth, "tokens": [{**record, "source": "card"}]}
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

    def _factory_signature(self, record: dict | None) -> dict | None:
        """Install the offline factory release signature, but only one that verifies (D-225 2.2).

        The image ships /opt/rosy/releases/<id> sealed and unsigned. Written
        next to it, the bundle's signature makes native_release verify() accept
        that release, so the robot can roll back or recover to it. verify()
        itself decides: if it still refuses the release, the signature is
        removed again and provisioning continues with the release unsigned,
        as it was before D-225 2.2. A re-run finds it already verified.
        """
        if record is None:
            return None
        release_id = record["release_id"]
        release = self._inside(f"opt/rosy/releases/{release_id}")
        signature = release / "SHA256SUMS.sig"
        result = {"release_id": release_id, "signed": False}
        written = False
        try:
            if release.is_symlink() or not release.is_dir():
                raise ValueError("factory release is not installed")
            manager = _native_release().NativeReleaseManager(
                root=self.root, public_key=self._inside(TRUSTED_RELEASE_KEY))
            try:
                manager.verify(release_id)
                return {**result, "signed": True}  # already signed: a retry, or never needed
            except ValueError:
                pass
            # A signature that does not verify is worth nothing; ours replaces it.
            # Stale temporaries of an interrupted write would be unlisted files.
            for stale in (signature, *release.glob(".SHA256SUMS.sig.*")):
                if stale.is_symlink() or stale.is_file():
                    stale.unlink()
            written = True
            _write_atomic(signature, record["sha256sums_sig_b64"] + "\n", 0o644)
            manager.verify(release_id)
            return {**result, "signed": True}
        except (OSError, ValueError, RuntimeError) as exc:
            if written:
                try:
                    signature.unlink(missing_ok=True)
                except OSError:
                    pass
            print(f"rosy-first-boot: factory release {release_id} stays unsigned: {exc}", file=sys.stderr)
            return {**result, "reason": str(exc)[:200]}

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
            # D-193 7: CORE refuses the shared dev tokens and ignores ROSY_DEV_AUTH.
            "ROSY_DEPLOYMENT=device",
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
        network_path = self._inside(SITE_PROFILE_PATH)
        _write_atomic(network_path, self._network_profile(payload), 0o600)
        _json_atomic(self._inside("etc/rosy/fleet-bootstrap.json"), payload["fleet"], 0o600)
        operator_fingerprints = self._operator(payload.get("operator"))
        if "ap" in payload["network"]:
            # D-176: the fallback AP and the console banner read this root-only file.
            _json_atomic(self._inside("etc/rosy/ap-credentials.json"), payload["network"]["ap"], 0o600)
        # D-191: validate_provision_bundle already refused a bundle without one.
        self._core_api(payload["core_api"]["record"])
        factory = self._factory_signature(payload.get("factory_release"))

        if not self.network_activate(SITE_PROFILE):
            # The site profile stays (0600, the bundle on the card holds the same
            # secret): NM autoconnect keeps trying it, rosy-network (D-176) hands
            # the radio back to it after the fallback AP, and
            # rosy-first-boot-retry.timer finishes provisioning once it is up.
            _json_atomic(self.state, HELD, 0o600)
            return {"ok": False, **HELD}

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
        if factory is not None:
            complete["factory_release"] = factory
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
    parser.add_argument(
        "--network", choices=("activate", "check"), default="activate",
        help="check: never start the site profile, only accept it once NM has it up "
             "(the retry timer must not take the single radio from the fallback AP)",
    )
    args = parser.parse_args(argv)
    network_activate = _default_network_activate
    if args.network == "check" and not (args.root / "var/lib/rosy/provisioning/complete.json").is_file():
        # The retry timer's run: until NM has the site profile up, change nothing
        # (no state.json, hostname, avahi restart or file rewrite every 30 s).
        profile = args.root / SITE_PROFILE_PATH
        if profile.is_file():
            # Re-read the kept profile from disk; this never touches the radio.
            _nmcli(["nmcli", "connection", "load", str(profile)], 15)
        if not site_wifi_up(SITE_PROFILE):
            print(json.dumps({"ok": False, **HELD}, sort_keys=True))
            return 1
        network_activate = lambda _profile: True  # noqa: E731 - just checked above
    try:
        result = FirstBootProvisioner(root=args.root, network_activate=network_activate).apply(
            bundle=args.bundle,
            hardware_serial=args.hardware_serial or _hardware_serial(args.root),
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        result = {"ok": False, "state": "PROVISIONING_HOLD", "reason": str(exc)}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())
