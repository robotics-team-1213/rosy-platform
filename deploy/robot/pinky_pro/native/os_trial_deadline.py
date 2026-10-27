"""Independent trial deadline; storage failure must not block the normal reboot request."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from os_bootloader import _dt, _snapshot


def committed(root: Path) -> bool:
    try:
        facts, state, _ = _snapshot(root)
        return facts["tryboot"] == 1 and state["pending"] is None
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        return False


def probe_committed(root: Path) -> bool:
    try:
        child = subprocess.Popen([sys.executable, "-I", "-B", str(Path(__file__).resolve()),
            "committed", "--root", str(root)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return False
    try:
        return child.wait(timeout=3) == 0
    except subprocess.TimeoutExpired:
        try:
            child.kill()
        except ProcessLookupError:
            pass
        # Waiting again could hang on uninterruptible storage I/O; PID1 will reap the child.
        return False


def _run(argv):
    subprocess.run(argv, check=True, timeout=15, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def expire(root: Path = Path("/"), *, probe=probe_committed, run=_run) -> bool:
    if root != Path("/") and run is _run:
        raise ValueError("deadline reboot requires the real root or an explicit test runner")
    trial = _dt(root, "tryboot")
    if trial == 0:
        return False
    if trial != 1:
        raise ValueError("OS_TRIAL_HOLD: unknown firmware trial flag")
    if probe(root):
        return False
    run(["systemctl", "--no-block", "reboot"])
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("expire", "committed"))
    parser.add_argument("--root", type=Path, default=Path("/"))
    args = parser.parse_args(argv)
    try:
        if args.command == "committed":
            return 0 if committed(args.root) else 1
        expire(args.root)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
