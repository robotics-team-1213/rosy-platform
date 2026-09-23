#!/usr/bin/env python3
"""L2 diagnostics bundle for an operator with SSH (D-175).

``rosy-diag collect --out DIR`` writes one tar.gz that explains a boot without
CORE: this boot's journal of the ROSY units, their systemd status, provisioning
state, the release activation journal, the dmesg tail, a network summary (SSID
names, never keys), the boot-partition black box and ``manifest.json`` with
member hashes and the correlation keys (boot_id, release_id, device_name).

Standard library only; it runs from the installed native runtime. Every member
passes ``rosy_diag_redact.redact`` and no path that ``is_denied_path`` refuses
is ever read. The bundle is bounded (50 MiB uncompressed content) and never
overwrites an existing file.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
from typing import Callable

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from rosy_diag_redact import is_denied_path, redact  # noqa: E402


Runner = Callable[[list[str]], tuple[int, str]]
TOTAL_CAP_BYTES = 50 * 1024 * 1024
MEMBER_CAP_BYTES = 16 * 1024 * 1024
MANIFEST_RESERVE_BYTES = 256 * 1024
DMESG_LINES = 400
COMMAND_TIMEOUT_S = 60
TRUNCATED_MARK = "[rosy-diag: older content truncated to fit the bundle limit]\n"

# (member, argv, keep only the last N lines). Text output only; no -s/--show-secrets.
COMMANDS: tuple[tuple[str, list[str], int | None], ...] = (
    ("systemd/units.txt", ["systemctl", "list-units", "--all", "--no-pager", "--plain", "rosy-*"], None),
    ("systemd/status.txt", ["systemctl", "status", "--no-pager", "--full", "--lines=20", "rosy-*"], None),
    ("systemd/failed.txt", ["systemctl", "--failed", "--no-pager", "--plain"], None),
    ("network/addresses.txt", ["ip", "-brief", "address"], None),
    ("network/devices.txt", ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"], None),
    ("network/wifi.txt", ["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL", "device", "wifi", "list", "--rescan", "no"],
     None),
    ("kernel/dmesg-tail.txt", ["dmesg", "--ctime"], DMESG_LINES),
    # Largest last: whatever budget is left goes to the journal, newest lines kept.
    ("journal/rosy-units.txt", ["journalctl", "-b", "--no-pager", "-o", "short-monotonic", "-u", "rosy-*"], None),
)
FILE_GLOBS = (
    ("blackbox", "boot/firmware/rosy-diag", "*"),
    ("provisioning", "var/lib/rosy/provisioning", "*.json"),
    ("release", "var/lib/rosy/releases", "native-activation.json"),
)


def run_command(argv: list[str]) -> tuple[int, str]:
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, errors="replace",
                                   timeout=COMMAND_TIMEOUT_S, check=False)
    except FileNotFoundError:
        return 127, f"{argv[0]}: command not found\n"
    except subprocess.TimeoutExpired:
        return 124, f"{argv[0]}: timed out after {COMMAND_TIMEOUT_S} s\n"
    output = completed.stdout
    if completed.stderr:
        output += "\n[stderr]\n" + completed.stderr
    return completed.returncode, output


def _read_text(path: Path) -> str | None:
    try:
        return path.read_bytes().decode("utf-8", "replace")
    except OSError:
        return None


def correlation(root: Path) -> dict:
    boot_id = (_read_text(root / "proc/sys/kernel/random/boot_id") or "").strip() or None
    try:
        identity = json.loads(_read_text(root / "etc/rosy/device-identity.json") or "{}")
    except ValueError:
        identity = {}
    if not isinstance(identity, dict):
        identity = {}
    device_name = identity.get("device_name") or identity.get("hostname") \
        or (_read_text(root / "etc/hostname") or "").strip() or None
    try:
        release_id = os.readlink(root / "opt/rosy/current").replace("\\", "/").rsplit("/", 1)[-1]
    except OSError:
        release_id = None
    try:
        uptime = float((_read_text(root / "proc/uptime") or "").split()[0])
    except (IndexError, ValueError):
        uptime = None
    return {
        "boot_id": boot_id,
        "release_id": release_id,
        "device_name": device_name,
        "device_uid": identity.get("device_uid"),
        "uptime_s": uptime,
        "collected_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def _fit(text: str, budget: int) -> tuple[bytes, bool]:
    """Redact, then keep the newest whole lines that fit ``budget`` bytes."""
    mark = TRUNCATED_MARK.encode("utf-8")
    room = budget - len(mark)
    raw = text.encode("utf-8")
    if len(raw) <= budget:
        data = redact(text).encode("utf-8")
        if len(data) <= budget:
            return data, False
    elif room <= 0:
        return b"", True
    else:
        # Cut before redacting so a huge journal stays cheap; drop the partial line.
        raw = raw[-room:]
        raw = raw[raw.find(b"\n") + 1:]
        data = redact(raw.decode("utf-8", "replace")).encode("utf-8")
    if room <= 0:
        return b"", True
    while len(data) > room:  # redaction markers can make a line longer
        data = data[data.find(b"\n") + 1:] if b"\n" in data else b""
    return mark + data, True


def _bundle_name(corr: dict, now: datetime) -> str:
    device = re.sub(r"[^a-z0-9-]", "-", str(corr.get("device_name") or "unknown").lower())[:40]
    boot = re.sub(r"[^0-9a-f]", "", str(corr.get("boot_id") or ""))[:8] or "noboot"
    return f"rosy-diag-{device}-{boot}-{now.strftime('%Y%m%dT%H%M%SZ')}.tar.gz"


def _add(archive: tarfile.TarFile, name: str, data: bytes, mtime: float) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = 0o644
    info.mtime = int(mtime)
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    archive.addfile(info, io.BytesIO(data))


def collect(root: Path, run: Runner, out_dir: Path) -> Path:
    root = Path(root)
    out_dir = Path(out_dir)
    now = datetime.now(timezone.utc)
    corr = correlation(root)
    budget = TOTAL_CAP_BYTES - MANIFEST_RESERVE_BYTES
    members: list[tuple[str, bytes]] = []
    entries: list[dict] = []
    denied: list[str] = []
    missing: list[str] = []

    def add(name: str, text: str, source: str, **extra) -> None:
        nonlocal budget
        data, truncated = _fit(text, min(MEMBER_CAP_BYTES, budget))
        budget -= len(data)
        members.append((name, data))
        entry = {"name": name, "source": source, "size": len(data),
                 "sha256": hashlib.sha256(data).hexdigest(), **extra}
        if truncated:
            entry["truncated"] = True
        entries.append(entry)

    for prefix, directory, pattern in FILE_GLOBS:
        device_dir = "/" + directory
        if is_denied_path(device_dir):
            denied.append(device_dir)
            continue
        paths = sorted((root / directory).glob(pattern)) if (root / directory).is_dir() else []
        if not paths:
            missing.append(f"{device_dir}/{pattern}")
        for path in paths:
            device_path = f"{device_dir}/{path.name}"
            if is_denied_path(device_path):
                denied.append(device_path)
                continue
            if not path.is_file() or path.is_symlink():
                continue
            text = _read_text(path)
            if text is None:
                missing.append(device_path)
                continue
            add(f"{prefix}/{path.name}", text, device_path)

    for name, argv, tail in COMMANDS:
        code, output = run(argv)
        if tail is not None:
            output = "".join(output.splitlines(keepends=True)[-tail:])
        add(name, output, " ".join(argv), returncode=code)

    manifest = {
        "schema_version": 1,
        "tool": "rosy-diag collect",
        "decision": "D-175 L2",
        "correlation": corr,
        "limits": {"total_bytes": TOTAL_CAP_BYTES, "member_bytes": MEMBER_CAP_BYTES, "dmesg_lines": DMESG_LINES},
        "members": entries,
        "denied": sorted(denied),
        "missing": sorted(missing),
    }
    manifest_data = redact(json.dumps(manifest, indent=1, sort_keys=True) + "\n").encode("utf-8")

    out_dir.mkdir(parents=True, exist_ok=True)
    bundle = out_dir / _bundle_name(corr, now)
    with open(bundle, "xb") as handle:
        with tarfile.open(fileobj=handle, mode="w:gz") as archive:
            for name, data in members:
                _add(archive, name, data, now.timestamp())
            _add(archive, "manifest.json", manifest_data, now.timestamp())
    os.chmod(bundle, 0o644)
    return bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rosy-diag", description="ROSY diagnostics (D-175 L2)")
    commands = parser.add_subparsers(dest="command", required=True)
    collect_parser = commands.add_parser("collect", help="write a redacted diagnostics bundle")
    collect_parser.add_argument("--out", required=True, type=Path, help="directory for the new bundle")
    collect_parser.add_argument("--root", default=Path("/"), type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    bundle = collect(args.root, run_command, args.out)
    corr = correlation(args.root)
    print(json.dumps({
        "bundle": str(bundle),
        "bytes": bundle.stat().st_size,
        "boot_id": corr["boot_id"],
        "device_name": corr["device_name"],
        "release_id": corr["release_id"],
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
