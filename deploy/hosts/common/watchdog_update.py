#!/usr/bin/env python3
"""Pack and apply signed, monotonically versioned PC watchdog updates."""

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.request import urlopen

if __package__:
    from .release.signing import sign_checksums, verify_signature
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent / "release"))
    from signing import sign_checksums, verify_signature

DOWNLOAD_URL = (
    "https://github.com/robotics-team-1213/rosy-platform/releases/download/"
    "host-watchdog-current/watchdog-update.bin"
)
PUBLIC_KEY = Path("/etc/rosy/watchdog-update.pub.pem")
ACTIVE_SCRIPT = Path("/var/lib/rosy-watchdog-update/active")
MAX_ASSET_BYTES = 64 * 1024
DOMAIN = b"ROSY PC watchdog update v1\n"
SHEBANG = b"#!/usr/bin/env bash\n"
VERSION_MARKER = b"# ROSY watchdog sequence "
SEQUENCE = re.compile(rb"[1-9][0-9]{0,17}")


def build_asset(private_key: Path, sequence: int, script: bytes) -> bytes:
    version = str(sequence).encode("ascii")
    if not SEQUENCE.fullmatch(version) or not script.startswith(SHEBANG):
        raise ValueError("invalid release sequence or watchdog shebang")
    message = DOMAIN + version + b"\n" + script
    asset = sign_checksums(message, private_key).strip().encode("ascii") + b"\n" + message
    if len(asset) > MAX_ASSET_BYTES:
        raise ValueError("watchdog release is too large")
    return asset


def _verified_script(asset: bytes, public_key: Path) -> tuple[int, bytes]:
    signature, _, message = asset.partition(b"\n")
    if len(asset) > MAX_ASSET_BYTES or len(signature) != 88 or not signature.isascii():
        raise ValueError("invalid watchdog signature envelope")
    if verify_signature(message, signature.decode("ascii"), public_key):
        raise ValueError("watchdog signature verification failed")
    sequence, _, script = message.removeprefix(DOMAIN).partition(b"\n")
    if not message.startswith(DOMAIN) or not SEQUENCE.fullmatch(sequence) or not script.startswith(SHEBANG):
        raise ValueError("invalid signed watchdog payload")
    return int(sequence), SHEBANG + VERSION_MARKER + sequence + b"\n" + script[len(SHEBANG):]


def _installed_sequence(active: Path) -> int:
    try:
        with active.open("rb") as current:
            shebang = current.readline(len(SHEBANG) + 1)
            marker = current.readline(len(VERSION_MARKER) + 20)
    except FileNotFoundError:
        return 0
    sequence = marker.removeprefix(VERSION_MARKER).removesuffix(b"\n")
    if shebang != SHEBANG or not marker.startswith(VERSION_MARKER) or not SEQUENCE.fullmatch(sequence):
        raise ValueError("installed watchdog sequence is invalid")
    return int(sequence)


def install_asset(asset: bytes, public_key: Path, active: Path) -> str:
    import fcntl

    sequence, script = _verified_script(asset, public_key)
    with (active.parent / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        installed = _installed_sequence(active)
        if sequence < installed:
            return f"ignored older sequence {sequence}"
        if sequence == installed:
            if active.read_bytes() != script:
                raise ValueError(f"installed sequence {sequence} has different content")
            return f"already installed {sequence}"
        result = subprocess.run(
            ["/bin/bash", "-n"], input=script, env={"PATH": "/usr/bin:/bin"},
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=5,
        )
        if result.returncode:
            raise ValueError("signed watchdog script has invalid shell syntax")
        staging = tempfile.NamedTemporaryFile(dir=active.parent, prefix=".watchdog-", delete=False)
        staged = Path(staging.name)
        try:
            with staging:
                staging.write(script)
                staging.flush()
                os.fchmod(staging.fileno(), 0o755)
                os.fsync(staging.fileno())
            os.replace(staged, active)
        finally:
            staged.unlink(missing_ok=True)
        directory = os.open(active.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return f"installed {sequence}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    pack = commands.add_parser("pack")
    pack.add_argument("--key", type=Path, required=True)
    pack.add_argument("--sequence", type=int, required=True)
    pack.add_argument("output", type=Path)
    commands.add_parser("apply")
    args = parser.parse_args()
    try:
        if args.command == "pack":
            script = Path(__file__).with_name("rosy-ssh-watchdog").read_bytes().replace(b"\r\n", b"\n")
            args.output.write_bytes(build_asset(args.key, args.sequence, script))
        else:
            with urlopen(DOWNLOAD_URL, timeout=20) as response:
                asset = response.read(MAX_ASSET_BYTES + 1)
            print(install_asset(asset, PUBLIC_KEY, ACTIVE_SCRIPT))
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"rosy-watchdog-update: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
