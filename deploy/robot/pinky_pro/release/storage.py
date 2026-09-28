"""Disk headroom, staging cleanup and rotation for the release layout.

The device runs on one SD card, and running out of space there does not
present as "disk full" — it presents as an update that cannot start, or a
rollback with nothing to roll back to. So the budget in
docs/deployment/release-retention.md is part of recoverability, not
housekeeping, and this module is the part of it that runs.

Three rules shape everything here:

* Refuse an update that cannot finish. Half an unpacked bundle is worse than
  an update that never began, and the operator can act on a number.
* Delete nothing until an activation has completed. Cleaning up mid-activation
  can remove the release the rollback needs.
* Never delete a user's maps. Events rotate, backups rotate, maps warn.

Free space is read through an injected probe so the tests can put the device
at any fill level without one.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

GIB = 1024 ** 3

#: An update needs room for the bundle, its unpacked form, and the release it
#: becomes, plus a margin so activation is not the thing that fills the card.
#: 3 GB of bundle therefore asks for 8.5 GB — the number behind the 32 GB
#: minimum in release-retention.md section 2.
HEADROOM_MULTIPLIER = 2.5
HEADROOM_MARGIN_BYTES = 1 * GIB

#: Caps from release-retention.md section 2.
EVENTS_LIMIT_BYTES = 500 * 1024 * 1024
MAPS_LIMIT_BYTES = 1 * GIB
BACKUP_RETENTION = 3

DiskProbe = Callable[[Path], int]


def free_bytes(path: Path) -> int:
    """Free space on the filesystem holding ``path``.

    Walks up to the nearest existing ancestor: the directory being asked about
    may not exist yet on a fresh device, and its parent is on the same card.
    """
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return shutil.disk_usage(probe).free


@dataclass(frozen=True)
class Rejection:
    """Mirrors manifest.Rejection so callers handle one shape."""

    code: str
    field: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.code}] {self.field}: {self.detail}"


def _gib(value: float) -> str:
    return f"{value / GIB:.1f} GiB"


def required_headroom(bundle_bytes: int) -> int:
    """Space an update of this size needs before it may start."""
    return int(bundle_bytes * HEADROOM_MULTIPLIER) + HEADROOM_MARGIN_BYTES


def check_update_headroom(
    bundle_bytes: int,
    *,
    staging: Path,
    probe: DiskProbe = free_bytes,
) -> list[Rejection]:
    """Refuse an update that cannot finish, before anything is unpacked.

    The rejection carries both numbers. "Not enough space" is not actionable;
    "needs 8.5 GiB, has 6.2 GiB" tells an operator what card to fetch.
    """
    if bundle_bytes <= 0:
        return [
            Rejection(
                "UPDATE_BUNDLE_EMPTY",
                str(staging),
                f"bundle size must be positive, got {bundle_bytes}",
            )
        ]

    required = required_headroom(bundle_bytes)
    available = probe(staging)
    if available < required:
        return [
            Rejection(
                "UPDATE_INSUFFICIENT_SPACE",
                str(staging),
                f"needs {_gib(required)} free "
                f"({_gib(bundle_bytes)} bundle x {HEADROOM_MULTIPLIER} + "
                f"{_gib(HEADROOM_MARGIN_BYTES)} margin), has {_gib(available)}",
            )
        ]
    return []


def directory_size(path: Path) -> int:
    """Total size of the files under ``path``, symlinks not followed."""
    if not path.is_dir():
        return 0
    total = 0
    for entry in path.rglob("*"):
        if entry.is_symlink() or not entry.is_file():
            continue
        try:
            total += entry.stat().st_size
        except OSError:
            continue  # vanished mid-walk; it is not occupying space any more
    return total


def clear_staging(staging_root: Path, *, keep: Iterable[str] = ()) -> list[str]:
    """Remove staged releases once activation has finished with them.

    Called *after* an activation completes, never during one — cleaning up
    mid-activation can delete the tree a rollback is about to need.
    """
    if not staging_root.is_dir():
        return []

    protected = set(keep)
    removed: list[str] = []
    for entry in sorted(staging_root.iterdir()):
        if entry.name in protected or not entry.is_dir():
            continue
        shutil.rmtree(entry, ignore_errors=True)
        removed.append(entry.name)
    return removed


def rotate_directory(path: Path, *, limit_bytes: int) -> list[str]:
    """Delete oldest-first until the directory fits under its cap.

    Used for events, which are diagnostic and regenerate. Returns what was
    removed so the dashboard can say so rather than leaving a silent gap.
    """
    if not path.is_dir():
        return []

    files = sorted(
        (entry for entry in path.rglob("*") if entry.is_file() and not entry.is_symlink()),
        key=lambda entry: entry.stat().st_mtime,
    )
    total = sum(entry.stat().st_size for entry in files)
    removed: list[str] = []

    for entry in files:
        if total <= limit_bytes:
            break
        size = entry.stat().st_size
        try:
            entry.unlink()
        except OSError:
            continue
        total -= size
        removed.append(entry.relative_to(path).as_posix())
    return removed


def _backup_age(directory: Path) -> float:
    """When a backup was last written, by its newest file.

    Not the directory's own mtime: writing a file into a directory updates
    that directory, so every backup created in the same pass looks equally
    recent and the ordering falls to whatever iterdir happens to return. The
    newest file inside is what "how recent is this backup" actually means.
    """
    newest = 0.0
    for entry in directory.rglob("*"):
        if entry.is_file() and not entry.is_symlink():
            try:
                newest = max(newest, entry.stat().st_mtime)
            except OSError:
                continue
    return newest or directory.stat().st_mtime


def prune_backups(backups: Path, *, keep: int = BACKUP_RETENTION) -> list[str]:
    """Keep the newest ``keep`` backups, drop the rest."""
    if not backups.is_dir():
        return []

    directories = sorted(
        (entry for entry in backups.iterdir() if entry.is_dir()),
        key=_backup_age,
        reverse=True,
    )
    removed: list[str] = []
    for entry in directories[keep:]:
        shutil.rmtree(entry, ignore_errors=True)
        removed.append(entry.name)
    return removed


@dataclass(frozen=True)
class StorageReport:
    """What cleanup did, and what it deliberately refused to do."""

    staging_removed: list[str]
    events_removed: list[str]
    backups_removed: list[str]
    maps_bytes: int
    maps_over_limit: bool

    @property
    def warnings(self) -> list[str]:
        if not self.maps_over_limit:
            return []
        warning = (
            f"maps occupy {_gib(self.maps_bytes)}, over the "
            f"{_gib(MAPS_LIMIT_BYTES)} guidance — not deleted; maps are the "
            f"operator's own data, so this is a warning and never a cleanup"
        )
        return [warning]


def reclaim(
    layout,
    *,
    keep_staged: Iterable[str] = (),
    events_limit: int = EVENTS_LIMIT_BYTES,
    maps_limit: int = MAPS_LIMIT_BYTES,
    backup_retention: int = BACKUP_RETENTION,
) -> StorageReport:
    """Run every cleanup that is safe once an activation has completed.

    Maps are measured and never touched. Everything else here regenerates;
    a map does not, and a device that silently deletes a survey is worse than
    a device that runs out of space and says so.
    """
    maps_bytes = directory_size(layout.var / "maps")
    return StorageReport(
        staging_removed=clear_staging(layout.staging, keep=keep_staged),
        events_removed=rotate_directory(layout.var / "events", limit_bytes=events_limit),
        backups_removed=prune_backups(layout.backups, keep=backup_retention),
        maps_bytes=maps_bytes,
        maps_over_limit=maps_bytes > maps_limit,
    )
