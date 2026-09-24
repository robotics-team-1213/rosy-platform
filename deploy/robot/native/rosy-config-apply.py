#!/usr/bin/env python3
"""Apply /boot/firmware/rosy-config.yaml at boot, then scrub its passwords (D-176).

Runs as a root oneshot outside CORE (D-161). An invalid file applies nothing
and is reported on the console and in the black box; this tool never fails the
boot. Identity is never changed here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid
from typing import Callable

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import rosy_config  # noqa: E402
from rosy_config import APPLIED, ConfigError  # noqa: E402

try:
    from deploy.sd.personalization import derive_wpa_psk
except ModuleNotFoundError:  # installed image layout
    # The image installs deploy/sd beside this runtime: /opt/rosy/deploy/sd
    # next to /opt/rosy/native-runtime (build-native-payload.sh).
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from deploy.sd.personalization import derive_wpa_psk


Runner = Callable[[list[str]], str]
CARD_FILE = "boot/firmware/rosy-config.yaml"
CONNECTIONS = "etc/NetworkManager/system-connections"
APPLIED_STATE = "var/lib/rosy/config/applied.json"
STATUS = "run/rosy-boot/config-status.json"
_SCRUB_LINE = re.compile(r"^(\s*(?:-\s*)?password\s*:\s*)(?!\"<applied>\"\s*$).*$", re.MULTILINE)


def _run(command: list[str]) -> str:
    return subprocess.run(command, capture_output=True, text=True, timeout=30, check=False).stdout


def _write(path: Path, content: str, mode: int | None) -> None:
    """Atomic write through a random temp name (mkstemp) with the mode set first.

    ``mode=None`` leaves the mode alone: on the vfat boot partition every file
    is 0755 and chmod fails with EPERM, which would leave passwords on the card.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            if mode is not None and hasattr(os, "fchmod"):
                os.fchmod(handle.fileno(), mode)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    if hasattr(os, "O_DIRECTORY"):  # vfat loses an unsynced rename on power loss
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


def _profile_name(ssid: str) -> str:
    return "rosy-wifi-" + hashlib.sha256(ssid.encode("utf-8")).hexdigest()[:10]


def _wifi_profile(network: dict, psk: str) -> str:
    name = _profile_name(network["ssid"])
    return "\n".join([
        "[connection]",
        f"id={name}",
        f"uuid={uuid.uuid5(uuid.NAMESPACE_URL, 'rosy-wifi:' + network['ssid'])}",
        "type=wifi",
        "autoconnect=true",
        f"autoconnect-priority={network['priority']}",
        "",
        "[wifi]",
        "mode=infrastructure",
        f"ssid={network['ssid']}",
        "",
        "[wifi-security]",
        "key-mgmt=wpa-psk",
        f"psk={psk}",
        "",
        "[ipv4]",
        "method=auto",
        "",
        "[ipv6]",
        "method=auto",
        "",
    ])


def _existing_psk(path: Path) -> str | None:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("psk="):
                return line[4:]
    except OSError:
        return None
    return None


def _apply_wifi(root: Path, networks: list[dict], notes: list[str]) -> bool:
    directory = root / CONNECTIONS
    wanted = {}
    for network in networks:
        path = directory / f"{_profile_name(network['ssid'])}.nmconnection"
        if network["password"] == APPLIED:
            key_hex = _existing_psk(path)
            if key_hex is None:
                notes.append(f"wifi {network['ssid']}: password was already applied elsewhere; skipped")
                continue
        else:
            key_hex = derive_wpa_psk(network["ssid"], network["password"])
        wanted[path.name] = _wifi_profile(network, key_hex)
    changed = False
    # A skipped entry may be a renamed network whose old profile still holds
    # the only copy of its key; keep every profile rather than lose it.
    for stale in [] if notes else directory.glob("rosy-wifi-*.nmconnection"):
        if stale.name not in wanted:
            stale.unlink()
            changed = True
    for name, content in wanted.items():
        path = directory / name
        try:
            if path.read_text(encoding="utf-8") == content:
                continue
        except OSError:
            pass
        _write(path, content, 0o600)
        changed = True
    return changed


def _scrub_card(card: Path, text: str, config: dict) -> None:
    expected = rosy_config.scrubbed(config)
    candidate = _SCRUB_LINE.sub(lambda m: m.group(1) + f'"{APPLIED}"', text)
    try:
        if rosy_config.parse(candidate) != expected:
            raise ConfigError("line scrub did not reproduce the scrubbed view")
    except ConfigError:
        import yaml

        candidate = ("# Rewritten by the robot after applying: passwords are now " + APPLIED + ".\n"
                     + yaml.safe_dump({"schema_version": 1, **expected}, sort_keys=False, allow_unicode=True))
    _write(card, candidate, None)


def apply(root: Path, run: Runner) -> dict:
    card = root / CARD_FILE
    if not card.is_file():
        return {"state": "absent"}
    text = card.read_text(encoding="utf-8", errors="replace")
    try:
        config = rosy_config.parse(text)
    except ConfigError as exc:
        result = {"state": "invalid", "error": str(exc)}
        _write(root / STATUS, json.dumps(result, sort_keys=True) + "\n", 0o600)
        return result

    view = rosy_config.scrubbed(config)
    digest = hashlib.sha256(json.dumps(view, sort_keys=True).encode("utf-8")).hexdigest()
    plaintext = any(n.get("password") not in (None, APPLIED) for n in config.get("wifi", [])) or \
        config.get("ap", {}).get("password") not in (None, APPLIED)
    state_path = root / APPLIED_STATE
    try:
        previous = json.loads(state_path.read_text(encoding="utf-8")).get("digest")
    except (OSError, ValueError):
        previous = None
    if digest == previous and not plaintext:
        return {"state": "unchanged"}

    notes: list[str] = []
    defaults = rosy_config.load_defaults(root / "etc/rosy/defaults.yaml") \
        if (root / "etc/rosy/defaults.yaml").is_file() else {"ap": {"mode": "fallback"}}
    merged = rosy_config.merge(defaults, config)

    wifi_changed = "wifi" in config and _apply_wifi(root, config["wifi"], notes)

    ap = merged.get("ap", {})
    policy = {"mode": ap.get("mode", "fallback"), "grace_seconds": ap.get("grace_seconds", 120),
              "hold_seconds": ap.get("hold_seconds", 600), "country": merged.get("country", "KR")}
    if "ssid" in ap:
        policy["ssid"] = ap["ssid"]
    _write(root / "etc/rosy/network-policy.json", json.dumps(policy, sort_keys=True) + "\n", 0o600)
    # D-193 8: the boot login code policy for rosy-login-code (root-only, like the AP policy).
    login_policy = {"boot_code": merged.get("login", {}).get("boot_code", "operator")}
    _write(root / "etc/rosy/login-policy.json", json.dumps(login_policy, sort_keys=True) + "\n", 0o600)
    if ap.get("password") not in (None, APPLIED):
        credentials_path = root / "etc/rosy/ap-credentials.json"
        try:
            credentials = json.loads(credentials_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            credentials = {}
        credentials["password"] = ap["password"]
        if "ssid" in ap:
            credentials["ssid"] = ap["ssid"]
        _write(credentials_path, json.dumps(credentials, sort_keys=True) + "\n", 0o600)

    if config.get("fleet"):
        fleet_path = root / "etc/rosy/fleet-bootstrap.json"
        try:
            fleet = json.loads(fleet_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            fleet = {"pairing_required": False}
        fleet.update(config["fleet"])
        _write(fleet_path, json.dumps(fleet, sort_keys=True) + "\n", 0o600)

    if config.get("operator_ssh_keys"):
        keys_path = root / "home/rosy/.ssh/authorized_keys"
        if keys_path.parent.is_dir():
            try:
                existing = [line for line in keys_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            except OSError:
                existing = []
            merged_keys = existing + [key for key in config["operator_ssh_keys"] if key not in existing]
            _write(keys_path, "\n".join(merged_keys) + "\n", 0o600)
        else:
            notes.append("operator_ssh_keys: the rosy account does not exist; keys not installed")

    if "timezone" in config:
        run(["timedatectl", "set-timezone", config["timezone"]])
    if wifi_changed:
        run(["nmcli", "connection", "reload"])
    if plaintext:
        _scrub_card(card, text, config)
    _write(state_path, json.dumps({"digest": digest}, sort_keys=True) + "\n", 0o600)
    result = {"state": "applied", "notes": notes, "wifi_changed": wifi_changed}
    _write(root / STATUS, json.dumps(result, sort_keys=True) + "\n", 0o600)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/"))
    args = parser.parse_args(argv)
    try:
        result = apply(args.root, _run)
    except Exception as exc:  # never fail the boot over operator configuration
        print(f"rosy-config: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 0
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
