#!/usr/bin/env python3
"""The interim exclusive robot claim (D-387 decision 4, D-406 decision 5).

``mkdir /run/rosy-claim`` is the atomic step: whoever creates the directory
holds the claim and writes ``claim.json`` = {holder, purpose, acquired_at,
expires_at, boot_id}. A claim that has expired, or that an earlier boot left
behind, may be cleared by exactly one party: ``rename`` to
``/run/rosy-claim.stale.<rand>`` succeeds for one caller only. The release push
(operator PC) and the on-device updater both hold it for their whole sequence.

    python3 rosy_claim.py acquire --holder H --purpose P --ttl-s N   # exit 3 = busy
    python3 rosy_claim.py release --holder H                         # exit 3 = not ours
    python3 rosy_claim.py show                                       # alias: status

Standard library only; it runs from /opt/rosy/native-runtime as root.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sys
import time

CLAIM_DIR = "run/rosy-claim"
CLAIM_FILE = "claim.json"
#: Serialises the stale check, the rename aside and the mkdir across parties (D-406 review M9).
LOCK_FILE = "run/rosy-claim.lock"
LOCK_WAIT_S = 10.0
BOOT_ID = "proc/sys/kernel/random/boot_id"
MAX_TTL_S = 24 * 3600
#: A claim directory without a readable claim.json is the winner's mkdir-to-write
#: window. Only after this long is it treated as abandoned.
UNWRITTEN_GRACE_S = 60.0
MAX_CLAIM_BYTES = 4096
HOLDER = re.compile(r"^[A-Za-z0-9._@:-]{1,64}$")


class ClaimBusy(RuntimeError):
    """Someone else holds a live claim. ``claim`` is theirs (None if unreadable)."""

    def __init__(self, claim: dict | None, message: str | None = None) -> None:
        holder = (claim or {}).get("holder")
        super().__init__(message or f"CLAIM_BUSY: held by {holder or 'an unknown holder'}")
        self.claim = claim


@contextlib.contextmanager
def _claim_lock(root: Path, wait_s: float = LOCK_WAIT_S):
    """Exclusive lock on /run/rosy-claim.lock, polled for up to ``wait_s``."""
    path = root / LOCK_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        deadline = time.monotonic() + wait_s
        while True:
            try:
                handle.seek(0)
                if os.name == "posix":
                    import fcntl

                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise ClaimBusy(None, "CLAIM_BUSY: the claim lock is held by another party") from None
                time.sleep(0.05)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "posix":
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_UN)
            else:
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def _z(moment: _dt.datetime) -> str:
    return moment.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_z(value: object) -> _dt.datetime | None:
    """A UTC timestamp written as ...Z or with an explicit offset; None when invalid."""
    if not isinstance(value, str):
        return None
    try:
        moment = _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def _now(now: _dt.datetime | None) -> _dt.datetime:
    return now if now is not None else _dt.datetime.now(_dt.timezone.utc)


def boot_id(root: Path) -> str | None:
    try:
        return (root / BOOT_ID).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _read(path: Path) -> dict | None:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path / CLAIM_FILE, flags)
    except OSError:
        return None
    try:
        raw = os.read(descriptor, MAX_CLAIM_BYTES + 1)
    except OSError:
        return None
    finally:
        os.close(descriptor)
    if len(raw) > MAX_CLAIM_BYTES:
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _stale(path: Path, claim: dict | None, now: _dt.datetime, current_boot: str | None) -> bool:
    expires = parse_z((claim or {}).get("expires_at"))
    if claim is None or expires is None:
        try:
            age = now.timestamp() - path.stat().st_mtime
        except OSError:
            return False
        return age > UNWRITTEN_GRACE_S
    if claim.get("boot_id") != current_boot:
        return True
    return now >= expires


def _move_aside(path: Path) -> bool:
    """Rename the claim away; only one caller can win this. Then delete it."""
    aside = path.with_name(f"{path.name}.stale.{secrets.token_hex(6)}")
    try:
        os.rename(path, aside)
    except OSError:
        return False
    shutil.rmtree(aside, ignore_errors=True)
    return True


def _write_claim(path: Path, claim: dict) -> None:
    temporary = path / f".{CLAIM_FILE}.tmp"
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(claim, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o644)
    os.replace(temporary, path / CLAIM_FILE)


def acquire(root: Path, holder: str, purpose: str, ttl_s: float, *,
            now: _dt.datetime | None = None, lock_wait_s: float = LOCK_WAIT_S) -> dict:
    """Take the claim or raise ClaimBusy. A stale claim is moved aside first."""
    if not HOLDER.fullmatch(holder or ""):
        raise ValueError("CLAIM_HOLDER_INVALID: 1-64 of [A-Za-z0-9._@:-]")
    if not isinstance(purpose, str) or len(purpose) > 200 or re.search(r"[\x00-\x1f\x7f]", purpose):
        raise ValueError("CLAIM_PURPOSE_INVALID: at most 200 printable characters")
    if isinstance(ttl_s, bool) or not 0 < ttl_s <= MAX_TTL_S:
        raise ValueError(f"CLAIM_TTL_INVALID: ttl must be in (0, {MAX_TTL_S}] seconds")
    moment = _now(now)
    current_boot = boot_id(root)
    path = root / CLAIM_DIR
    with _claim_lock(root, lock_wait_s):
        return _acquire_locked(path, holder, purpose, ttl_s, moment, current_boot)


def _acquire_locked(path: Path, holder: str, purpose: str, ttl_s: float,
                    moment: _dt.datetime, current_boot: str | None) -> dict:
    for _attempt in range(2):
        try:
            os.mkdir(path, 0o755)
        except FileExistsError:
            existing = _read(path)
            if not _stale(path, existing, moment, current_boot):
                raise ClaimBusy(existing) from None
            _move_aside(path)  # a loser simply retries the mkdir below
            continue
        claim = {
            "holder": holder,
            "purpose": purpose,
            "acquired_at": _z(moment),
            "expires_at": _z(moment + _dt.timedelta(seconds=ttl_s)),
            "boot_id": current_boot,
        }
        try:
            _write_claim(path, claim)
        except OSError:
            shutil.rmtree(path, ignore_errors=True)
            raise
        return claim
    raise ClaimBusy(_read(path))


def release(root: Path, holder: str) -> bool:
    """Drop the claim if ``holder`` holds it. False when absent or someone else's."""
    path = root / CLAIM_DIR
    with _claim_lock(root):
        existing = _read(path)
        if existing is None or existing.get("holder") != holder:
            return False
        return _move_aside(path)


def refresh(root: Path, holder: str, ttl_s: float, *, now: _dt.datetime | None = None) -> bool:
    """Push ``holder``'s claim expiry to now + ttl. False when it is not theirs (D-406 review M8)."""
    if isinstance(ttl_s, bool) or not 0 < ttl_s <= MAX_TTL_S:
        raise ValueError(f"CLAIM_TTL_INVALID: ttl must be in (0, {MAX_TTL_S}] seconds")
    path = root / CLAIM_DIR
    with _claim_lock(root):
        existing = _read(path)
        if existing is None or existing.get("holder") != holder:
            return False
        existing["expires_at"] = _z(_now(now) + _dt.timedelta(seconds=ttl_s))
        _write_claim(path, existing)
        return True


def check(root: Path, *, now: _dt.datetime | None = None) -> dict | None:
    """The live claim (read-only), or None when there is none or it is stale."""
    path = root / CLAIM_DIR
    if not path.is_dir():
        return None
    existing = _read(path)
    if _stale(path, existing, _now(now), boot_id(root)):
        return None
    return existing if existing is not None else {"holder": None, "purpose": "claim being written"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=Path("/"))
    sub = parser.add_subparsers(dest="command", required=True)
    take = sub.add_parser("acquire")
    take.add_argument("--holder", required=True)
    take.add_argument("--purpose", required=True)
    take.add_argument("--ttl-s", type=float, required=True)
    drop = sub.add_parser("release")
    drop.add_argument("--holder", required=True)
    sub.add_parser("show", aliases=["status"])
    args = parser.parse_args(argv)
    try:
        if args.command == "acquire":
            result, code = {"ok": True, "claim": acquire(args.root, args.holder, args.purpose, args.ttl_s)}, 0
        elif args.command == "release":
            # Nothing to release is fine; someone else's claim is refused (exit 3).
            released = release(args.root, args.holder)
            ok = released or not (args.root / CLAIM_DIR).exists()
            result, code = {"ok": ok, "released": released}, 0 if ok else 3
        else:
            result, code = {"ok": True, "claim": check(args.root)}, 0
    except ClaimBusy as exc:
        result, code = {"ok": False, "error": "CLAIM_BUSY", "claim": exc.claim}, 3
    except (ValueError, OSError) as exc:
        result, code = {"ok": False, "error": str(exc)}, 2
    print(json.dumps(result, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
