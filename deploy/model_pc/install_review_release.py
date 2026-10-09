"""Install or reactivate a versioned Model PC review app without moving review state.

Run as the same user that owns rosy-review-v13.service. See README.md.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path


SERVICE = "rosy-review-v13.service"
APP = Path("learning/training/perception/dataset/review_app.py")
WEB = Path("learning/training/perception/dataset/review_app_web")


def check_source(source: Path, root: Path, state: Path) -> None:
    if (source == root or root in source.parents or source in state.parents
            or state in source.parents or state == root or root in state.parents):
        raise ValueError("source, release root, and review state must be separate")
    for required in (APP, WEB / "index.html", WEB / "pixels.html", Path("shared/web/shared-assets.json")):
        if not (source / required).is_file():
            raise ValueError(f"release source is missing {required}")
    for directory, dirs, files in os.walk(source):
        for name in dirs + files:
            entry = Path(directory) / name
            if entry.is_symlink():
                raise ValueError(f"release source contains a symlink: {entry}")
            if entry.name == "reviews.sqlite3":
                raise ValueError("release source contains review state")


def digest_tree(source: Path) -> str:
    digest = hashlib.sha256()
    for file in sorted(path for path in source.rglob("*") if path.is_file()):
        digest.update(file.relative_to(source).as_posix().encode() + b"\0")
        with file.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def unit_contents(current: Path, state: Path, python: Path, host: str, port: int) -> str:
    dataset = current / "learning/training/perception/dataset"
    paths = (
        current / "middleware/perception",
        current / "contracts/foundation",
        current / "learning/training/perception",
        dataset,
        current / "learning/training/perception/training",
    )
    for value in (current, state, python):
        if any(char.isspace() for char in str(value)):
            raise ValueError("systemd paths must not contain whitespace")
    return ("[Unit]\nDescription=ROSY v13 drivable review\nAfter=network-online.target\n"
            "Wants=network-online.target\n\n[Service]\nType=simple\n"
            f"WorkingDirectory={dataset}\nEnvironment=PYTHONPATH={':'.join(map(str, paths))}\n"
            f"ExecStart={python} {dataset / 'review_app.py'} --state {state} --port {port} --host {host}\n"
            "Restart=on-failure\nRestartSec=5\n\n[Install]\nWantedBy=default.target\n")


def run_systemctl(*args: str) -> None:
    subprocess.run(("systemctl", "--user", *args), check=True)


def check_live(host: str, port: int) -> None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(15):
        try:
            run_systemctl("is-active", "--quiet", SERVICE)
            with opener.open(f"http://{host}:{port}/api/workspace", timeout=3) as response:
                if not isinstance(json.load(response), dict):
                    raise ValueError("workspace response is not an object")
            with opener.open(f"http://{host}:{port}/pixels", timeout=3) as response:
                if response.status != 200:
                    raise ValueError("pixel review page is unavailable")
            return
        except (OSError, ValueError, subprocess.CalledProcessError):
            time.sleep(1)
    raise RuntimeError("review service did not pass workspace and pixel-page checks")


def switch(current: Path, target: Path) -> None:
    candidate = current.with_name(".current-next")
    if candidate.exists() or candidate.is_symlink():
        raise ValueError(f"stale switch link exists: {candidate}")
    candidate.symlink_to(target, target_is_directory=True)
    os.replace(candidate, current)


def install(source: Path | None, release: str, root: Path, state: Path | None,
            python: Path | None, host: str, port: int, unit: Path) -> Path:
    if not release or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for char in release) or release in (".", ".."):
        raise ValueError("release must be one safe path component")
    address = ipaddress.IPv4Address(host)
    allowed = ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
               "169.254.0.0/16", "100.64.0.0/10")
    if not any(address in ipaddress.ip_network(network) for network in allowed):
        raise ValueError("review host must be a private or Tailscale IPv4 address")
    if not 1 <= port <= 65535:
        raise ValueError("invalid port")
    root = root.expanduser().resolve()
    target = root / "releases" / release
    current = root / "current"
    if not unit.is_file():
        raise ValueError(f"existing service unit is missing: {unit}")
    if current.exists() and not current.is_symlink():
        raise ValueError("current must be a symlink")
    if current.is_symlink() and not current.exists():
        raise ValueError("current points to a missing release")
    if current.with_name(".current-next").exists() or current.with_name(".current-next").is_symlink():
        raise ValueError("a release switch is already pending")
    old_target = current.resolve() if current.is_symlink() else None
    old_unit = unit.read_bytes()
    if source is not None:
        if state is None or python is None:
            raise ValueError("new releases require --state and --python")
        source = source.expanduser().resolve(strict=True)
        state = state.expanduser().resolve(strict=True)
        # Keep the venv entrypoint: resolving it can silently select system Python.
        python = python.expanduser().absolute()
        if not (state / "reviews.sqlite3").is_file() or not python.is_file():
            raise ValueError("existing review database and Python executable are required")
        check_source(source, root, state)
        if target.exists():
            raise ValueError(f"release already exists: {target}")
        unit_text = unit_contents(current, state, python, host, port)
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = target.with_name(f".staging-{release}-{os.getpid()}")
        shutil.copytree(source, staging)
        source_digest = digest_tree(source)
        if digest_tree(staging) != source_digest:
            raise ValueError("staged release differs from source")
        (staging / "REVIEW_RELEASE.json").write_text(json.dumps({
            "release": release, "source_sha256": source_digest}, indent=2) + "\n", encoding="utf-8")
        env = os.environ.copy()
        env["PYTHONPATH"] = ":".join(str(staging / part) for part in (
            "middleware/perception", "contracts/foundation", "learning/training/perception",
            "learning/training/perception/dataset", "learning/training/perception/training"))
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        subprocess.run((str(python), "-c", "import review_app"), env=env, check=True)
        os.replace(staging, target)
    elif not (target / APP).is_file():
        raise ValueError(f"existing release is missing: {target}")
    else:
        unit_text = None
    if old_target == target and unit_text is None:
        return target
    try:
        if unit_text is not None:
            backup = root / "rosy-review-v13.service.before-managed"
            if not backup.exists():
                backup.write_bytes(old_unit)
            temporary = unit.with_name(unit.name + ".next")
            temporary.write_text(unit_text, encoding="utf-8")
            os.replace(temporary, unit)
        switch(current, target)
        run_systemctl("daemon-reload")
        run_systemctl("restart", SERVICE)
        check_live(host, port)
    except Exception:
        if old_target is None:
            current.unlink(missing_ok=True)
        else:
            switch(current, old_target)
        unit.write_bytes(old_unit)
        run_systemctl("daemon-reload")
        run_systemctl("restart", SERVICE)
        raise
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release", help="release name; omit --source to reactivate a prior release")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--python", type=Path)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--root", type=Path, default=Path.home() / "rosy-ml/review-v13-code")
    args = parser.parse_args()
    unit = Path.home() / ".config/systemd/user" / SERVICE
    try:
        release = install(args.source, args.release, args.root, args.state, args.python,
                          args.host, args.port, unit)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"review release failed: {exc}\n")
    print(f"active review release: {release}")


if __name__ == "__main__":
    main()
