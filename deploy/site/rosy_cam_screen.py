#!/usr/bin/env python3
"""Status or display wake for one explicitly identified, already paired Android camera."""

import argparse
import ipaddress
import json
import re
import subprocess
import sys
from pathlib import Path


class ScreenError(RuntimeError):
    pass


def command(args, runner, optional=False):
    try:
        result = runner(args, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        if optional:
            return ""
        raise ScreenError("ADB command unavailable or timed out") from None
    if result.returncode:
        if optional:
            return ""
        raise ScreenError("ADB command failed; private output suppressed")
    return result.stdout


def validate(config):
    fields = {"adb_path", "expected_serial", "expected_model"}
    if not isinstance(config, dict) or set(config) != fields:
        raise ScreenError("Config must contain adb_path, expected_serial and expected_model")
    if any(not isinstance(config[k], str) or not config[k].strip() for k in fields):
        raise ScreenError("Config values must be nonempty strings")
    if not re.fullmatch(r"[A-Za-z0-9]+", config["expected_serial"]):
        raise ScreenError("Expected serial must be an explicit alphanumeric device serial")
    return config


def devices(config, runner):
    rows = []
    for line in command([config["adb_path"], "devices"], runner).splitlines():
        if not line.strip() or line.startswith("List of devices"):
            continue
        fields = line.split()
        if len(fields) != 2 or fields[1] != "device":
            raise ScreenError("Untrusted, offline or unauthorized ADB connection; refused")
        rows.append(fields[0])
    if len(rows) != len(set(rows)):
        raise ScreenError("Duplicate ADB connection; refused")
    return rows


def identity(config, target, runner):
    prefix = [config["adb_path"], "-s", target, "shell", "getprop"]
    serial = command([*prefix, "ro.serialno"], runner).strip()
    model = command([*prefix, "ro.product.model"], runner).strip()
    if not serial or not model:
        raise ScreenError("Device identity unavailable; refused")
    return serial, model


def verified(config, runner):
    matches = []
    for target in devices(config, runner):
        serial, model = identity(config, target, runner)
        if serial == config["expected_serial"]:
            if model != config["expected_model"]:
                raise ScreenError("Expected device model mismatch; refused")
            matches.append(target)
    if len(matches) > 1:
        raise ScreenError("Multiple connections match the expected device; refused")
    return matches[0] if matches else None


def endpoint(address, port):
    try:
        ip = ipaddress.ip_address(address)
        number = int(port)
        if not 1 <= number <= 65535:
            return None
        return f"[{ip}]:{number}" if ip.version == 6 else f"{ip}:{number}"
    except ValueError:
        return None


def candidates(config, runner):
    expected = re.compile(r"^adb-" + re.escape(config["expected_serial"]) + r"-[A-Za-z0-9_-]+(?: \(\d+\))?$")
    def matches(name):
        # Avahi escapes bytes as decimal \DDD; duplicate services gain " (2)".
        decoded = re.sub(r"\\(\d{3})", lambda m: chr(int(m.group(1))), name)
        return expected.fullmatch(decoded)
    found = set()
    raw = command([config["adb_path"], "mdns", "services"], runner, optional=True)
    for line in raw.splitlines():
        fields = line.split()
        if len(fields) != 3 or fields[1] != "_adb-tls-connect._tcp":
            continue
        if not matches(fields[0].split(".", 1)[0]):
            continue
        address, _, port = fields[2].rpartition(":")
        value = endpoint(address.strip("[]"), port)
        if value:
            found.add(value)
    raw = command(["avahi-browse", "-rtp", "_adb-tls-connect._tcp"], runner, optional=True)
    for line in raw.splitlines():
        fields = line.split(";")
        if len(fields) < 9 or fields[0] != "=" or fields[4] != "_adb-tls-connect._tcp":
            continue
        if not matches(fields[3]):
            continue
        value = endpoint(fields[7], fields[8])
        if value:
            found.add(value)
    return sorted(found)


def execute(config, action, runner=subprocess.run):
    validate(config)
    if action not in {"status", "wake"}:
        raise ScreenError("Unsupported action")
    target = verified(config, runner)
    if target is None:
        discovered = candidates(config, runner)
        if not discovered:
            raise ScreenError("Expected paired camera not found; use official wireless pairing")
        for candidate in discovered:
            try:
                command([config["adb_path"], "connect", candidate], runner)
                serial, model = identity(config, candidate, runner)
            except ScreenError:
                # A stale advertised port can fail while another port is live.
                continue
            if (serial, model) != (config["expected_serial"], config["expected_model"]):
                raise ScreenError("Discovered device identity mismatch; refused")
            target = verified(config, runner)
            if target is not None:
                break
        if target is None:
            raise ScreenError("Expected camera is not an authorized connection")
    # Check again immediately before the action; discovery names are not identity proof.
    if identity(config, target, runner) != (config["expected_serial"], config["expected_model"]):
        raise ScreenError("Device identity changed; refused")
    if action == "wake":
        command([config["adb_path"], "-s", target, "shell", "input", "keyevent", "KEYCODE_WAKEUP"], runner)
        return {"status": "wake_sent", "model": config["expected_model"]}
    power = command([config["adb_path"], "-s", target, "shell", "dumpsys", "power"], runner)
    match = re.search(r"\bmWakefulness=(\w+)", power)
    return {"status": "connected", "model": config["expected_model"],
            "screen": match.group(1) if match else "unknown"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["status", "wake"])
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        result = execute(config, args.action)
    except (ScreenError, OSError, ValueError):
        # Never print config, ADB output, endpoint, pairing code or exception details.
        print(json.dumps({"status": "refused", "message": "Check private config, pairing and unique device identity"}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
