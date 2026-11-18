#!/usr/bin/env python3
"""D-1035: per-arm lease so one owner at a time drives an arm (stdlib only).

One `<arm>.json` per arm under `ROSY_ARM_LEASES` (default `~/.local/state/rosy/arm-leases`).
A lease is live while it has not expired and its pid (if any) is alive on this host.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
from pathlib import Path
import socket
import sys
import time

try:
    import fcntl
except ImportError:  # Windows tests: no cross-process lock
    fcntl = None

SCHEMA = "rosy.omx-arm-lease.v1"


class LeaseHeld(RuntimeError):
    """Another owner holds a live lease on the arm."""


def lease_root(root=None) -> Path:
    return Path(root or os.environ.get("ROSY_ARM_LEASES") or Path.home() / ".local/state/rosy/arm-leases")


def default_owner() -> str:
    if os.environ.get("ROSY_ARM_LEASE_OWNER"):
        return os.environ["ROSY_ARM_LEASE_OWNER"]
    try:
        user = os.getlogin()
    except OSError:
        user = os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"
    client = (os.environ.get("SSH_CONNECTION") or "").split(" ")[0] or socket.gethostname()
    return f"{user}@{client}"


def _boot_id() -> str | None:
    """This boot's id (Linux): a pid recorded under another boot names a different process."""
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip() or None
    except OSError:
        return None


def _pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
    except PermissionError:
        return True
    except (OSError, ValueError):
        return False
    return True


def live(record: dict, now: float | None = None) -> bool:
    """A lease with a pid lives exactly as long as that process (a 35 min session must stay covered, review
    2026-11-17); a lease without one (claimed ahead of a job) lives until it expires."""
    if record.get("pid") is not None:
        if record.get("boot_id") and record["boot_id"] != _boot_id():
            return False  # rebooted since: that pid is gone, whatever now has its number (review 2026-11-17)
        return _pid_alive(record["pid"])
    now = time.time() if now is None else now
    return float(record.get("expires") or 0) > now


@contextlib.contextmanager
def _locked(arm: str, root: Path):
    root.mkdir(parents=True, exist_ok=True)
    with open(root / f"{arm}.lock", "a") as handle:
        if fcntl is not None:
            fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def _read(arm: str, root: Path) -> dict | None:
    try:
        return json.loads((root / f"{arm}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def claim(arm, owner=None, purpose="", ttl_s=1800, pid=None, revision=None, root=None, now=None) -> dict:
    """Take or refresh the arm's lease; LeaseHeld when another owner's lease is live."""
    owner = owner or default_owner()
    root = lease_root(root)
    now = time.time() if now is None else now
    with _locked(arm, root):
        old = _read(arm, root)
        if old and old.get("owner") != owner and live(old, now):
            until = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(float(old["expires"])))
            raise LeaseHeld(f"arm {arm} held by {old['owner']} for {old.get('purpose') or '-'} until {until}")
        same_live = bool(old and old.get("owner") == owner and live(old, now))
        holder = old.get("pid") if same_live and old.get("pid") is not None else pid  # never drop a live holder's pid
        record = {"schema": SCHEMA, "arm": arm, "owner": owner, "purpose": purpose,
                  "host": socket.gethostname(), "pid": holder, "boot_id": _boot_id(), "revision": revision,
                  "acquired": old["acquired"] if old and old.get("owner") == owner else now,
                  "expires": now + ttl_s}
        tmp = root / f"{arm}.json.tmp"
        tmp.write_text(json.dumps(record, indent=2), encoding="utf-8")
        os.replace(tmp, root / f"{arm}.json")
    return record


def release(arm, owner=None, root=None) -> bool:
    """Remove the lease only when it is this owner's."""
    owner = owner or default_owner()
    root = lease_root(root)
    with _locked(arm, root):
        old = _read(arm, root)
        if not old or old.get("owner") != owner:
            return False
        (root / f"{arm}.json").unlink(missing_ok=True)
        return True


def status(arm=None, root=None) -> dict:
    root = lease_root(root)
    arms = [arm] if arm else sorted(p.stem for p in root.glob("*.json")) if root.is_dir() else []
    out = {}
    for name in arms:
        record = _read(name, root)
        if record:
            out[name] = {**record, "live": live(record)}
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("status")
    st.add_argument("--arm")
    cl = sub.add_parser("claim")
    cl.add_argument("--arm", required=True)
    cl.add_argument("--owner")
    cl.add_argument("--purpose", default="")
    cl.add_argument("--ttl-s", type=float, default=1800)
    rl = sub.add_parser("release")
    rl.add_argument("--arm", required=True)
    rl.add_argument("--owner")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "status":
            result = status(args.arm)
        elif args.cmd == "claim":
            result = claim(args.arm, args.owner, args.purpose, args.ttl_s)
        else:
            result = {"released": release(args.arm, args.owner)}
    except LeaseHeld as exc:
        print(json.dumps({"error": str(exc)}))
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
