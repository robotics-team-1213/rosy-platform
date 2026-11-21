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
    if record.get("hold"):
        return True  # a runner left the arm held or unconfirmed: live until its owner releases it (record_session)
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


def claim(arm, owner=None, purpose="", ttl_s=1800, pid=None, revision=None, root=None, now=None,
          report_created=False, keep_live=False, with_previous=False):
    """Take or refresh the arm's lease; LeaseHeld when another owner's lease is live. With report_created,
    (record, created): created is False when this owner already held a live lease, decided under the lease lock.
    With keep_live, that live lease is returned as it is (pid and expiry unchanged): a caller that only needs
    cover must not shorten or re-pid a reservation someone else's job relies on. With with_previous (needs
    report_created), (record, created, old): old is what was in the file under the lock, or None."""
    owner = owner or default_owner()
    root = lease_root(root)
    now = time.time() if now is None else now
    with _locked(arm, root):
        old = _read(arm, root)
        if old and old.get("hold"):  # not even its owner: only release_hold (a person, after checking the arm) clears it
            raise LeaseHeld(f"arm {arm} lease held by {old['owner']}: {old['hold']} (cell_arm_lease.py release-hold)")
        if old and old.get("owner") != owner and live(old, now):
            until = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(float(old["expires"])))
            raise LeaseHeld(f"arm {arm} held by {old['owner']} for {old.get('purpose') or '-'} until {until}"
                            + (f" ({old['hold']}: a person releases it)" if old.get("hold") else ""))
        same_live = bool(old and old.get("owner") == owner and live(old, now))
        if same_live and keep_live:
            return (old, False, old) if with_previous else (old, False) if report_created else old
        holder = old.get("pid") if same_live and old.get("pid") is not None else pid  # never drop a live holder's pid
        record = {"schema": SCHEMA, "arm": arm, "owner": owner, "purpose": purpose,
                  "host": socket.gethostname(), "pid": holder, "boot_id": _boot_id(), "revision": revision,
                  "acquired": old["acquired"] if old and old.get("owner") == owner else now,
                  "expires": now + ttl_s}
        tmp = root / f"{arm}.json.tmp"
        tmp.write_text(json.dumps(record, indent=2), encoding="utf-8")
        os.replace(tmp, root / f"{arm}.json")
    return (record, not same_live, old) if with_previous else (record, not same_live) if report_created else record


def restore(arm, previous: dict, expect: dict, owner=None, root=None) -> bool:
    """Put back a pid-less reservation this owner's claim re-pid'd for one session (record_session): the same
    reservation, expiry and all, stays valid after the session. Only when the lease is still exactly the one this session's claim wrote (expect)."""
    owner = owner or default_owner()
    root = lease_root(root)
    if previous.get("owner") != owner or previous.get("pid") is not None or previous.get("hold"):
        return False
    with _locked(arm, root):
        current = _read(arm, root)
        if not current or current.get("owner") != owner or current.get("hold") or any(
                current.get(k) != expect.get(k) for k in ("pid", "acquired", "expires", "boot_id")):
            return False  # someone claimed, held or changed it since this session's claim: not ours to put back
        tmp = root / f"{arm}.json.tmp"
        tmp.write_text(json.dumps(previous, indent=2), encoding="utf-8")
        os.replace(tmp, root / f"{arm}.json")
    return True


def repid(arm, pid, owner=None, root=None) -> bool:
    """Tie this owner's live, unheld lease to another process (the session leader, which outlives its wrapper)."""
    owner = owner or default_owner()
    root = lease_root(root)
    with _locked(arm, root):
        old = _read(arm, root)
        if not old or old.get("owner") != owner or old.get("hold") or not live(old):
            return False
        tmp = root / f"{arm}.json.tmp"
        tmp.write_text(json.dumps({**old, "pid": pid}, indent=2), encoding="utf-8")
        os.replace(tmp, root / f"{arm}.json")
    return True


def hold(arm, reason: str, pid=None, owner=None, root=None) -> bool:
    """Mark this owner's lease held (live past its pid and expiry) for a runner record_session left on the arm."""
    owner = owner or default_owner()
    root = lease_root(root)
    with _locked(arm, root):
        old = _read(arm, root)
        if not old or old.get("owner") != owner:
            return False
        record = {**old, "pid": pid, "hold": reason, "held_at": time.time()}
        tmp = root / f"{arm}.json.tmp"
        tmp.write_text(json.dumps(record, indent=2), encoding="utf-8")
        os.replace(tmp, root / f"{arm}.json")
    return True


def release(arm, owner=None, root=None, *, hold=False) -> bool:
    """Remove the lease only when it is this owner's; a held lease only with hold=True (`release_hold`)."""
    owner = owner or default_owner()
    root = lease_root(root)
    with _locked(arm, root):
        old = _read(arm, root)
        if not old or old.get("owner") != owner or bool(old.get("hold")) != hold:
            return False
        (root / f"{arm}.json").unlink(missing_ok=True)
        return True


def release_hold(arm, owner=None, root=None) -> bool:
    """A person has supported and checked the arm: remove this owner's held lease."""
    return release(arm, owner, root, hold=True)


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
    rh = sub.add_parser("release-hold", help="after a person checked an arm a runner left held or unconfirmed")
    rh.add_argument("--arm", required=True)
    rh.add_argument("--owner")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "status":
            result = status(args.arm)
        elif args.cmd == "claim":
            result = claim(args.arm, args.owner, args.purpose, args.ttl_s)
        elif args.cmd == "release-hold":
            result = {"released": release_hold(args.arm, args.owner)}
        else:
            result = {"released": release(args.arm, args.owner)}
    except LeaseHeld as exc:
        print(json.dumps({"error": str(exc)}))
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
