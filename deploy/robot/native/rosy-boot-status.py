#!/usr/bin/env python3
"""Show the ROSY boot stage to people without CORE (D-174 T0).

Computes the stage from systemd and the first-boot state, then renders it to
independent sinks: /run/rosy-boot/boot-status.json, the board ACT LED, the
console banner (/run/rosy-boot/issue, linked from /etc/issue.d), an avahi
`_rosy._tcp` service and the boot-partition black box (D-175 L1). Each sink is
isolated: one failing never stops the others, and this tool never fails the boot.

It runs as root, so it writes only into root-owned directories and never through
a predictable temporary name: /run/rosy belongs to rosy-core, and a compromised
CORE must not be able to steer these writes (D-161).
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from typing import Callable
from xml.sax.saxutils import escape, quoteattr

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from rosy_boot_state import BOOT_UNITS, Stage, classify  # noqa: E402
import rosy_blackbox  # noqa: E402


Runner = Callable[[list[str]], str]
STATUS_DIR = "run/rosy-boot"
DEFAULT_API_PORT = 8080


def _run(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
    return result.stdout


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


RUNTIME_MODES = frozenset({"core", "motor", "hardware"})
#: hardware.json rows copied for the boot display (D-260): id, state and product flag only.
HARDWARE_FILE = f"{STATUS_DIR}/hardware.json"
DEVICE_STATES = frozenset({"ok", "no_response", "bus_missing", "driver_missing", "needs_human", "not_measured"})
MAX_DEVICES = 64
MAX_DEVICE_ID = 64


def _runtime_env(root: Path, key: str) -> str | None:
    """One value of /etc/rosy/runtime.env (0600, root reads it for the boot display)."""
    try:
        for line in (root / "etc/rosy/runtime.env").read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == key:
                return value.strip()
    except (OSError, UnicodeDecodeError):
        pass
    return None


def _api_port(root: Path) -> int:
    """Advertise the port CORE actually uses (wait-core-ready honours it too)."""
    value = _runtime_env(root, "ROSY_API_PORT")
    return int(value) if value and value.isdigit() else DEFAULT_API_PORT


def _runtime_mode(root: Path) -> str | None:
    """D-260: CORE's runtime mode, for the boot display that cannot read runtime.env."""
    value = _runtime_env(root, "ROSY_RUNTIME_MODE")
    return value if value in RUNTIME_MODES else None


#: D-260 M1: CORE's hand-over (api/v1/host.py STATUS_INPUTS_FILE) in rosy-core's /run/rosy.
STATUS_INPUTS_FILE = "run/rosy/status-inputs.json"
MAX_STATUS_INPUTS_BYTES = 16 * 1024
#: CORE rewrites it every 10 s; older than this means CORE is not running it any more.
STATUS_INPUTS_FRESH_S = 60.0


def _read_core_file(path: Path) -> dict | None:
    """A small JSON object CORE wrote: no symlink, no FIFO, bounded. CORE is less trusted than root."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_STATUS_INPUTS_BYTES:
            return None
        raw = os.read(descriptor, MAX_STATUS_INPUTS_BYTES + 1)
    except OSError:
        return None
    finally:
        os.close(descriptor)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _core_inputs(root: Path, now: datetime) -> dict | None:
    """D-260 M1: CORE's live SAF-005 warning and its overlaid device states, when fresh and valid."""
    data = _read_core_file(root / STATUS_INPUTS_FILE)
    if data is None or data.get("schema") != 1:
        return None
    try:
        written = datetime.fromisoformat(str(data.get("written_at")))
    except ValueError:
        return None
    if written.tzinfo is None or not -5.0 <= (now - written).total_seconds() <= STATUS_INPUTS_FRESH_S:
        return None
    warning = data.get("battery_warning_percent")
    if isinstance(warning, bool) or not isinstance(warning, (int, float)) or not 0 < warning <= 100:
        return None
    devices = _valid_rows(data.get("devices"))
    if devices is None:
        return None
    return {"battery_warning_percent": float(warning), "devices": devices}


def _device_states(root: Path) -> list[dict]:
    """D-260: the probe's rows reduced to id/state/product, for rosy-display (hardware.json is 0640).

    Evidence text stays in hardware.json. A row that does not validate drops the whole list.
    """
    data = _read_json(root / HARDWARE_FILE) or {}
    if data.get("schema") != 1:
        return []
    return _valid_rows(data.get("devices")) or []


def _valid_rows(devices) -> list[dict] | None:
    """id/state/product rows, or None when any row does not validate."""
    if not isinstance(devices, list) or len(devices) > MAX_DEVICES:
        return None
    rows = []
    for device in devices:
        if not isinstance(device, dict):
            return None
        device_id, state, product = device.get("id"), device.get("state"), device.get("product")
        if not isinstance(device_id, str) or not device_id or len(device_id) > MAX_DEVICE_ID:
            return None
        if state not in DEVICE_STATES or type(product) is not bool:
            return None
        rows.append({"id": device_id, "state": state, "product": product})
    return rows


def gather(root: Path, run: Runner) -> dict:
    units = {}
    for unit in BOOT_UNITS:
        units[unit] = run(["systemctl", "show", "--property=ActiveState", "--value", unit]).strip() or "unknown"
    identity = _read_json(root / "etc/rosy/device-identity.json") or {}
    current = root / "opt/rosy/current"
    try:
        release_id = os.readlink(current).rsplit("/", 1)[-1]
    except OSError:
        release_id = None
    addresses = run(["hostname", "-I"]).split()
    ipv4 = [address for address in addresses if address.count(".") == 3]
    try:
        boot_id = (root / "proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    except OSError:
        boot_id = None
    return {
        "units": units,
        "provisioning": _read_json(root / "var/lib/rosy/provisioning/state.json"),
        "device_name": identity.get("device_name") or identity.get("hostname"),
        "release_id": release_id,
        "ipv4": ipv4,
        "boot_id": boot_id,
        "api_port": _api_port(root),
        "runtime_mode": _runtime_mode(root),
        # D-260 M1: CORE's inputs win while it keeps them fresh; otherwise the probe's rows
        # and the SAF-005 default (the display's), e.g. when CORE is down.
        **(_core_inputs(root, datetime.now(timezone.utc))
           or {"battery_warning_percent": None, "devices": _device_states(root)}),
        # D-176: written by rosy-network.py; mode/ssid/address only, never a secret.
        "network": {key: value for key, value in (_read_json(root / STATUS_DIR / "network.json") or {}).items()
                    if key in {"mode", "ssid", "address"}},
    }


def status_record(facts: dict, stage: Stage, now: datetime) -> dict:
    return {
        "schema_version": 1,
        "stage": stage.label,
        "failed_unit": stage.failed_unit,
        "detail": stage.detail,
        "device_name": facts.get("device_name"),
        "release_id": facts.get("release_id"),
        "ipv4": facts.get("ipv4") or [],
        "boot_id": facts.get("boot_id"),
        "api_port": facts.get("api_port", DEFAULT_API_PORT),
        "network": facts.get("network") or {},
        # D-260: the boot display's other two inputs, which it cannot read itself.
        "runtime_mode": facts.get("runtime_mode"),
        "devices": facts.get("devices") or [],
        "battery_warning_percent": facts.get("battery_warning_percent"),
        "units": facts.get("units") or {},
        "updated_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def render_issue(record: dict, ap_secret: str | None = None) -> str:
    name = str(record.get("device_name") or "rosy (unprovisioned)")
    address = ", ".join(str(a) for a in record.get("ipv4") or []) or "no IPv4 address"
    lines = [
        "",
        f"  ROSY {name}  release {record.get('release_id') or '?'}",
        f"  stage: {record['stage']}",
        f"  address: {address}",
    ]
    if record.get("detail"):
        lines.append(f"  detail: {record['detail']}")
    network = record.get("network") or {}
    if network.get("mode") == "ap":
        # Local, physical access only: the console is where a person reads this.
        lines.append(f"  Wi-Fi AP {network.get('ssid')}  password {ap_secret or '(see operator AP store)'}"
                     f"  -> ssh rosy@{network.get('address')}")
    if str(record["stage"]).startswith("FAILED"):
        lines.append(f"  see: journalctl -b -u {record.get('failed_unit')}")
    # agetty expands backslash escapes in issue files; keep the text literal.
    return ("\n".join(lines) + "\n\n").replace("\\", "\\\\")


def render_avahi(record: dict) -> str:
    txt = {
        "stage": str(record["stage"]),
        "release": str(record.get("release_id") or ""),
        "name": str(record.get("device_name") or ""),
        "network": str((record.get("network") or {}).get("mode") or "sta"),
    }
    records = "".join(
        f"    <txt-record>{escape(key)}={escape(value)}</txt-record>\n" for key, value in txt.items()
    )
    port = int(record.get("api_port") or DEFAULT_API_PORT)
    return (
        '<?xml version="1.0" standalone="no"?>\n'
        '<!DOCTYPE service-group SYSTEM "avahi-service.dtd">\n'
        "<service-group>\n"
        f"  <name replace-wildcards={quoteattr('yes')}>ROSY %h</name>\n"
        "  <service>\n"
        "    <type>_rosy._tcp</type>\n"
        f"    <port>{port}</port>\n"
        f"{records}"
        "  </service>\n"
        "</service-group>\n"
    )


def led_settings(stage: Stage) -> dict[str, str]:
    """ACT LED: heartbeat when ready, fast blink when failed, SD activity otherwise."""
    if stage.name == "CORE_READY":
        return {"trigger": "heartbeat"}
    if stage.name == "FAILED":
        return {"trigger": "timer", "delay_on": "100", "delay_off": "100"}
    return {"trigger": "mmc0"}


def _write_atomic(path: Path, content: str, mode: int = 0o644) -> bool:
    """Replace ``path`` unless it already holds ``content``; True when written.

    The temporary file comes from mkstemp (random name, O_EXCL) and its mode is
    set on the open descriptor, so no pre-planted link is ever followed.
    """
    try:
        if path.read_text(encoding="utf-8") == content:
            return False
    except (OSError, UnicodeDecodeError):
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            if hasattr(os, "fchmod"):
                os.fchmod(handle.fileno(), mode)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return True


def apply(root: Path, record: dict, stage: Stage, run: Runner) -> list[str]:
    errors: list[str] = []

    def sink(name: str, action: Callable[[], None]) -> None:
        try:
            action()
        except Exception as exc:  # one sink must never stop the others
            errors.append(f"{name}: {type(exc).__name__}: {exc}")

    sink("status", lambda: _write_atomic(root / STATUS_DIR / "boot-status.json",
                                         json.dumps(record, sort_keys=True, indent=2) + "\n"))

    def led() -> None:
        led_dir = root / "sys/class/leds/ACT"
        if not led_dir.is_dir():
            return
        settings = led_settings(stage)
        (led_dir / "trigger").write_text(settings["trigger"], encoding="ascii")
        for key in ("delay_on", "delay_off"):
            if key in settings:
                (led_dir / key).write_text(settings[key], encoding="ascii")

    sink("led", led)

    def issue() -> None:
        ap_login = None
        if (record.get("network") or {}).get("mode") == "ap":
            ap_login = (_read_json(root / "etc/rosy/ap-credentials.json") or {}).get("pass" + "word")
        # 0600: agetty reads it as root; CORE and other users must not.
        if _write_atomic(root / STATUS_DIR / "issue", render_issue(record, ap_login), 0o600):
            run(["agetty", "--reload"])

    sink("issue", issue)
    sink("avahi", lambda: _write_atomic(root / "etc/avahi/services/rosy.service", render_avahi(record)))

    def black_box() -> None:
        # D-175 L1: readable from the card alone; written only when it matters.
        boot_partition = root / "boot/firmware"
        if not boot_partition.is_dir() or not rosy_blackbox.needs_write(boot_partition, record):
            return
        tails = {}
        if stage.failed_unit:
            output = run(["journalctl", "-b", "-u", stage.failed_unit, "-n", str(rosy_blackbox.TAIL_LINES),
                          "--no-pager", "-o", "short-monotonic"])
            tails[stage.failed_unit] = output.splitlines()
        rosy_blackbox.write(boot_partition, record, tails)

    sink("blackbox", black_box)
    return errors


LOCK_NAME = ".run.lock"


@contextmanager
def run_lock(root: Path):
    """One run at a time, from gathering facts to the last sink (D-192 review).

    The timer, OnFailure= and rosy-boot-status-ready.service can overlap. A run
    that gathered while the runtime was still activating must not write after a
    later run that saw CORE_READY; holding the lock across gather and apply makes
    the last run to start the last to write. The lock file is root-owned under
    /run/rosy-boot, never /run/rosy (rosy-core's).
    """
    try:
        import fcntl
    except ImportError:  # host tests on Windows: no concurrent runs there
        yield
        return
    directory = root / STATUS_DIR
    directory.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(directory / LOCK_NAME, flags, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/"))
    args = parser.parse_args(argv)
    try:
        with run_lock(args.root):
            facts = gather(args.root, _run)
            stage = classify(facts["units"], facts["provisioning"])
            record = status_record(facts, stage, datetime.now(timezone.utc))
            errors = apply(args.root, record, stage, _run)
    except Exception as exc:  # never fail the boot over an indicator
        print(f"rosy-boot-status: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 0
    for error in errors:
        print(f"rosy-boot-status: sink {error}", file=sys.stderr)
    print(json.dumps({"stage": record["stage"], "sink_errors": len(errors)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
