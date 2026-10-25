"""Install and check the fixed portable PowerShell tool inside one staged test env."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import tarfile
import tempfile
from urllib.request import Request, urlopen


def _pins(path: Path) -> tuple[dict, bytes]:
    data = path.read_bytes()
    pin = json.loads(data)
    expected = {"version", "architecture", "size_bytes", "url", "sha256"}
    if not isinstance(pin, dict) or set(pin) != expected:
        raise ValueError("invalid PowerShell input fields")
    version = pin["version"]
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("invalid PowerShell version pin")
    url = f"https://github.com/PowerShell/PowerShell/releases/download/v{version}/powershell-{version}-linux-x64.tar.gz"
    if pin["url"] != url or pin["architecture"] != "x86_64":
        raise ValueError("unsupported PowerShell source or architecture")
    if type(pin["size_bytes"]) is not int or not 1 <= pin["size_bytes"] <= 128 * 1024**2:
        raise ValueError("invalid PowerShell size pin")
    if not isinstance(pin["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", pin["sha256"]):
        raise ValueError("invalid PowerShell SHA256 pin")
    if platform.system() != "Linux" or platform.machine() != pin["architecture"]:
        raise ValueError("SD test tools require native Linux x86_64")
    return pin, data


def _environment(root: Path) -> dict:
    state = root / "sd-state"
    return dict(os.environ, POWERSHELL_TELEMETRY_OPTOUT="1", POWERSHELL_DIAGNOSTICS_OPTOUT="1",
                DOTNET_CLI_TELEMETRY_OPTOUT="1", XDG_CACHE_HOME=str(state / "cache"),
                XDG_CONFIG_HOME=str(state / "config"), XDG_DATA_HOME=str(state / "data"),
                PSModuleAnalysisCachePath=str(state / "ModuleAnalysisCache"))


def ready(root: Path, pins: Path) -> None:
    pin, data = _pins(pins)
    root = root.resolve(strict=True)
    if (root / ".sd-pins").read_bytes() != data:
        raise ValueError("SD test tools pin snapshot differs")
    try:
        target = (root / "sd-tools").resolve(strict=True)
        binary = (target / "pwsh").resolve(strict=True)
        alias = (target / "powershell").resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError("PowerShell tool is missing or resolves outside the profile") from exc
    if not target.is_relative_to(root) or not binary.is_relative_to(target) or alias != binary:
        raise ValueError("PowerShell binary resolves outside the profile")
    try:
        result = subprocess.run([str(binary), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
                                 "$PSVersionTable.PSVersion.ToString()"], capture_output=True,
                                text=True, timeout=30, cwd=root, env=_environment(root))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("PowerShell version readiness failed") from exc
    if result.returncode or result.stdout.strip() != pin["version"]:
        raise ValueError("PowerShell version readiness failed")


def install(root: Path, pins: Path) -> None:
    pin, data = _pins(pins)
    root = root.resolve(strict=True)
    target = root / "sd-tools"
    if target.exists() or target.is_symlink():
        raise ValueError("SD test tools staging directory already exists")
    descriptor, filename = tempfile.mkstemp(prefix=".powershell-", suffix=".tgz", dir=root)
    archive_path = Path(filename)
    try:
        digest, size = hashlib.sha256(), 0
        request = Request(pin["url"], headers={"User-Agent": "ROSY-test-tools"})
        with os.fdopen(descriptor, "wb") as output, urlopen(request, timeout=60) as response:
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > pin["size_bytes"]:
                    raise ValueError("PowerShell archive size exceeds its pin")
                digest.update(chunk)
                output.write(chunk)
        if size != pin["size_bytes"] or digest.hexdigest() != pin["sha256"]:
            raise ValueError("PowerShell archive size/SHA256 differs from its pin")
        target.mkdir()
        try:
            with tarfile.open(archive_path, "r:gz") as archive:
                members, total = [], 0
                for member in archive:
                    members.append(member)
                    total += member.size
                    if len(members) > 10000 or total > 1024**3:
                        raise ValueError("PowerShell archive exceeds extraction budget")
                archive.extractall(target, members=members, filter="data")
        except (tarfile.TarError, OSError) as exc:
            raise ValueError("PowerShell archive extraction rejected") from exc
        binary = target / "pwsh"
        binary.chmod(binary.stat().st_mode | 0o111)
        (target / "powershell").symlink_to("pwsh")
        (root / ".sd-pins").write_bytes(data)
        ready(root, pins)
    finally:
        archive_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "ready"))
    parser.add_argument("root", type=Path)
    parser.add_argument("pins", type=Path)
    args = parser.parse_args()
    try:
        (install if args.action == "install" else ready)(args.root, args.pins)
    except (OSError, ValueError) as exc:
        print(f"[remote] SD test tools rejected: {exc}", flush=True)
        return 1
    print("[remote] SD test tools ready", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
