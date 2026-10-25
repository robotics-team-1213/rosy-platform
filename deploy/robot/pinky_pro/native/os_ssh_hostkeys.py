"""OS-owned SSH identity: generate once, project regular files before ssh starts."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from os_state_config import common_lock
from os_state_firstboot import _sync
from os_state_io import _write_atomic
from os_state_layout import COMMON, _path, _read

KEY = "ssh_host_ed25519_key"
FILES = {KEY: 0o600, KEY + ".pub": 0o644}


def _ssh_keygen(*args: str) -> str:
    result = subprocess.run(["/usr/bin/ssh-keygen", *args], capture_output=True, text=True,
                            timeout=15, check=False)
    if result.returncode or len(result.stdout) > 16384:
        raise ValueError("SSH host key generation/validation failed")
    return result.stdout


def _keys(directory: Path, owner: int) -> dict[str, str]:
    info = directory.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != owner
            or stat.S_IMODE(info.st_mode) != 0o700 or set(p.name for p in directory.iterdir()) != set(FILES)):
        raise ValueError("SSH host key directory differs")
    content = {}
    for name, mode in FILES.items():
        path = directory / name
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != mode:
            raise ValueError("SSH host key type/links/permissions differ")
        content[name] = _read(path, 16384, owner).decode("ascii")
    derived = _ssh_keygen("-y", "-P", "", "-f", str(directory / KEY)).split()
    public = content[KEY + ".pub"].split()
    if (len(derived) < 2 or derived[0] != "ssh-ed25519" or len(public) < 2
            or public[:2] != derived[:2]):
        raise ValueError("SSH host key pair differs")
    return content


def prepare(root: Path) -> str:
    root = Path(root).absolute()
    with common_lock(root) as shared:
        if shared is None:
            return "LEGACY"
        directory = _path(root, COMMON + "/ssh-hostkeys")
        if not directory.exists():
            if shared.validate_storage_state() != "FACTORY_EMPTY":
                raise ValueError("committed SSH host keys are missing")
            # Publish the pair as one durable directory; an orphan stage is never adopted.
            with tempfile.TemporaryDirectory(prefix=".ssh-hostkeys-", dir=directory.parent) as temporary:
                stage = Path(temporary)
                _ssh_keygen("-q", "-t", "ed25519", "-N", "", "-C", "rosy", "-f", str(stage / KEY))
                _keys(stage, root.stat().st_uid)
                for name in FILES:
                    descriptor = os.open(stage / name, os.O_RDONLY | os.O_NOFOLLOW)
                    try:
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
                _sync(stage)
                os.rename(stage, directory)
                _sync(directory.parent)
        content = _keys(directory, root.stat().st_uid)
        targets = {}
        for name, mode in FILES.items():
            target = _path(root, "etc/ssh/" + name)
            if target.exists():
                info = target.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValueError("root SSH host key type/links differ")
                _read(target, 16384, root.stat().st_uid)
            targets[name] = target
        for name, target in targets.items():
            _write_atomic(target, content[name], FILES[name])
    return "SSH_HOST_KEYS_READY"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/"))
    args = parser.parse_args(argv)
    try:
        print(prepare(args.root))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError):
        print("OS_SSH_HOST_KEYS_HOLD", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
