"""Immutable release layout and the atomic activation record (WP-2).

The device has exactly one authoritative statement of what it is running:
``/var/lib/rosy/activation.json``. It names the release directory, the config
generation, the data generation and the runtime mode together, so those four
move as a set or not at all. Boot reads this record and derives every path
from it.

``current`` and ``previous`` are symlinks for operators and tooling. They are
derived display, never a boot input. A boot that trusted the symlink could
find it pointing at one release while the config generation belonged to
another — precisely the mixed state the activation record exists to prevent.

Everything under ``releases/<release-id>`` and each generation directory is
immutable once activated. Rollback works by pointing the activation record
back at a set that was never modified in place, so nothing here edits an
activated release.

Paths are injectable (:meth:`Layout.rooted`) so the whole mechanism runs
against a temporary directory in tests without a Raspberry Pi.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

ACTIVATION_SCHEMA_VERSION = 1

#: The only mode an activation may install. First boot, update and rollback
#: all come up core-only; motor and hardware are a separate field approval.
ACTIVATION_RUNTIME_MODE = "core"

VALID_RUNTIME_MODES = frozenset({"core", "motor", "hardware"})


class ActivationUnreadable(Exception):
    """The activation record is missing or cannot be interpreted."""


@dataclass(frozen=True)
class Layout:
    """Where the release machinery keeps things."""

    opt: Path
    etc: Path
    var: Path
    cache: Path

    @classmethod
    def default(cls) -> Layout:
        return cls(
            opt=Path("/opt/rosy"),
            etc=Path("/etc/rosy"),
            var=Path("/var/lib/rosy"),
            cache=Path("/var/cache/rosy"),
        )

    @classmethod
    def rooted(cls, root: Path) -> Layout:
        """The same layout under an arbitrary root, for tests and staging."""
        return cls(
            opt=root / "opt" / "rosy",
            etc=root / "etc" / "rosy",
            var=root / "var" / "lib" / "rosy",
            cache=root / "var" / "cache" / "rosy",
        )

    # --- releases ---------------------------------------------------------

    @property
    def releases(self) -> Path:
        return self.opt / "releases"

    def release(self, release_id: str) -> Path:
        return self.releases / release_id

    @property
    def current_link(self) -> Path:
        return self.opt / "current"

    @property
    def previous_link(self) -> Path:
        return self.opt / "previous"

    # --- generations ------------------------------------------------------

    @property
    def config_generations(self) -> Path:
        return self.etc / "generations"

    def config_generation(self, generation_id: str) -> Path:
        return self.config_generations / generation_id

    @property
    def data_generations(self) -> Path:
        return self.var / "data-generations"

    def data_generation(self, generation_id: str) -> Path:
        return self.data_generations / generation_id

    # --- device-owned state, outside every generation ---------------------

    @property
    def identity(self) -> Path:
        return self.etc / "identity.json"

    @property
    def trusted_keys(self) -> Path:
        return self.etc / "trusted-release-keys"

    @property
    def network(self) -> Path:
        return self.etc / "network"

    # --- release state ----------------------------------------------------

    @property
    def activation(self) -> Path:
        return self.var / "activation.json"

    @property
    def journal(self) -> Path:
        return self.var / "update-journal.json"

    @property
    def release_state(self) -> Path:
        return self.var / "release-state.json"

    @property
    def previous_activation(self) -> Path:
        """Host-owned rollback authority, committed before an activation journal completes."""
        return self.etc / "previous-activation.json"

    @property
    def recovery_hold(self) -> Path:
        """Set while the device is held for recovery; survives reboot."""
        return self.var / "recovery-hold.json"

    @property
    def backups(self) -> Path:
        return self.var / "backups"

    @property
    def staging(self) -> Path:
        return self.cache / "releases"

    def create_directories(self) -> None:
        """Create the fixed directories. Safe to call repeatedly."""
        for path in (
            self.releases,
            self.config_generations,
            self.trusted_keys,
            self.network,
            self.data_generations,
            self.var / "events",
            self.var / "maps",
            self.backups,
            self.staging,
        ):
            path.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class ActivationRecord:
    """What the device is running, as one indivisible statement."""

    schema_version: int
    release_id: str
    release_path: str
    config_generation: str
    data_generation: str
    runtime_mode: str
    activated_at: str

    @classmethod
    def create(
        cls,
        *,
        release_id: str,
        release_path: Path,
        config_generation: str,
        data_generation: str,
        runtime_mode: str = ACTIVATION_RUNTIME_MODE,
        activated_at: str | None = None,
    ) -> ActivationRecord:
        if runtime_mode not in VALID_RUNTIME_MODES:
            raise ValueError(f"unknown runtime mode {runtime_mode!r}")
        return cls(
            schema_version=ACTIVATION_SCHEMA_VERSION,
            release_id=release_id,
            release_path=str(release_path),
            config_generation=config_generation,
            data_generation=data_generation,
            runtime_mode=runtime_mode,
            activated_at=activated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )


def _fsync_directory(path: Path) -> None:
    """Flush a directory entry so a rename survives power loss.

    POSIX only. Windows cannot open a directory for fsync, and the build and
    test hosts there do not need the durability guarantee — the device does,
    and the device is Linux.
    """
    if os.name != "posix":
        return
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


#: Mode for state files the dashboard has to read. NamedTemporaryFile creates
#: at 0600 and os.replace preserves it, which left release-state.json
#: root-only — unreadable by CORE at uid 1000, the process meant to show it.
STATE_FILE_MODE = 0o644


def write_json_atomic(path: Path, payload: dict, *, mode: int = STATE_FILE_MODE) -> None:
    """Replace ``path`` in one step, or leave the old content untouched.

    The temporary file is created in the destination directory so the rename
    stays within one filesystem, and both the file and its directory are
    flushed before and after. A reader therefore sees the old document or the
    new one, never a truncated mixture.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    # Not a context manager at creation: the file must outlive the block so
    # it can be renamed into place, and it is closed explicitly below.
    handle = tempfile.NamedTemporaryFile(  # noqa: SIM115
        mode="w",
        encoding="utf-8",
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        if os.name == "posix":
            os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    _fsync_directory(path.parent)


def write_activation(layout: Layout, record: ActivationRecord) -> None:
    """Install ``record`` as the device's authoritative activation."""
    write_json_atomic(layout.activation, asdict(record))


def _check_contained(layout: Layout, data: dict, path: Path) -> None:
    """Refuse a record that points outside the directories it may name.

    The payload paths inside a bundle are already contained (see
    manifest.py), but the activation record is the higher-value target: it is
    what boot reads to decide which tree to run. A release_path anywhere on
    disk, or a generation id carrying "..", would let anything that can write
    this one file choose what the next boot executes.
    """
    for field in ("config_generation", "data_generation"):
        value = data[field]
        if not isinstance(value, str) or not value or value in {".", ".."} or "/" in value or "\\" in value:
            raise ActivationUnreadable(
                f"{path}: {field} must be a single directory name, got {value!r}"
            )

    release_path = data["release_path"]
    if not isinstance(release_path, str):
        raise ActivationUnreadable(f"{path}: release_path must be a string, got {release_path!r}")

    try:
        resolved = Path(release_path).resolve()
        root = layout.releases.resolve()
    except OSError as exc:  # pragma: no cover - unresolvable path
        raise ActivationUnreadable(f"{path}: release_path cannot be resolved: {exc}") from exc

    if resolved != root and root not in resolved.parents:
        raise ActivationUnreadable(
            f"{path}: release_path {release_path!r} is outside {root}"
        )


def read_activation(layout: Layout) -> ActivationRecord:
    """Read the authoritative activation record."""
    path = layout.activation
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ActivationUnreadable(f"{path}: {exc}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ActivationUnreadable(f"{path}: malformed JSON at line {exc.lineno}: {exc.msg}") from exc

    if not isinstance(data, dict):
        raise ActivationUnreadable(f"{path}: expected an object")

    version = data.get("schema_version")
    if version != ACTIVATION_SCHEMA_VERSION:
        raise ActivationUnreadable(
            f"{path}: activation schema {version!r} is not implemented "
            f"(expected {ACTIVATION_SCHEMA_VERSION})"
        )

    missing = [
        field
        for field in (
            "release_id",
            "release_path",
            "config_generation",
            "data_generation",
            "runtime_mode",
            "activated_at",
        )
        if field not in data
    ]
    if missing:
        raise ActivationUnreadable(f"{path}: missing fields {missing}")

    if data["runtime_mode"] not in VALID_RUNTIME_MODES:
        raise ActivationUnreadable(f"{path}: unknown runtime mode {data['runtime_mode']!r}")

    _check_contained(layout, data, path)

    return ActivationRecord(
        schema_version=version,
        release_id=data["release_id"],
        release_path=data["release_path"],
        config_generation=data["config_generation"],
        data_generation=data["data_generation"],
        runtime_mode=data["runtime_mode"],
        activated_at=data["activated_at"],
    )


@dataclass(frozen=True)
class ResolvedActivation:
    """Every path boot needs, derived from the record alone."""

    release: Path
    config_generation: Path
    data_generation: Path
    runtime_mode: str


def resolve_activation(layout: Layout, record: ActivationRecord) -> ResolvedActivation:
    """Derive the running paths from the record — never from the symlinks."""
    return ResolvedActivation(
        release=Path(record.release_path),
        config_generation=layout.config_generation(record.config_generation),
        data_generation=layout.data_generation(record.data_generation),
        runtime_mode=record.runtime_mode,
    )


def update_display_pointers(
    layout: Layout,
    *,
    current: str | None,
    previous: str | None,
) -> None:
    """Repoint the operator-facing ``current`` and ``previous`` symlinks.

    Cosmetic by design. Failure here must not fail an activation: the record
    has already been written, and the device boots correctly with the
    symlinks broken or absent.
    """
    for link, release_id in ((layout.current_link, current), (layout.previous_link, previous)):
        try:
            if link.is_symlink() or link.exists():
                link.unlink()
            if release_id is not None:
                link.parent.mkdir(parents=True, exist_ok=True)
                os.symlink(layout.release(release_id), link, target_is_directory=True)
        except OSError:
            # Windows without the privilege, a read-only mount, a stale entry.
            # None of it changes what the device will boot.
            continue


def freeze_tree(path: Path) -> None:
    """Drop write permission across an activated release or generation.

    Not a security boundary — root still writes — but it turns "edit the live
    release" from something that silently works into something that fails.
    Rollback depends on the previous set being byte-identical to what was
    activated.
    """
    if os.name != "posix":
        return
    read_only = ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
    for entry in sorted(path.rglob("*"), reverse=True):
        entry.chmod(entry.stat().st_mode & read_only)
    path.chmod(path.stat().st_mode & read_only)


def tree_fingerprint(path: Path) -> dict[str, str]:
    """Map every file under ``path`` to its sha256, for immutability checks."""
    import hashlib

    fingerprint: dict[str, str] = {}
    for entry in sorted(path.rglob("*")):
        if not entry.is_file():
            continue
        digest = hashlib.sha256(entry.read_bytes()).hexdigest()
        fingerprint[entry.relative_to(path).as_posix()] = digest
    return fingerprint
