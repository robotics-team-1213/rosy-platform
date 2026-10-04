"""D-411 A: read-only view of /var/lib/rosy/pilot-recordings for CORE (setgid rosy-core).

CORE never writes here. Listing reads session.json and manifest.json; the archive is an
uncompressed USTAR stream of manifest.json plus exactly the files the manifest names, each
checked to be a regular file inside the recording folder with the size the manifest says.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tarfile
from pathlib import Path
from typing import NamedTuple

from core_common.protocol.recording import (
    FETCHED_NAME, MANIFEST_NAME, SESSION_NAME, RecordingManifest, RecordingSummary, recording_id_ok)

_BLOCK = 512


def _folder_bytes(folder: Path) -> int:
    total = 0
    for dirpath, _dirs, names in os.walk(folder):
        for name in names:
            try:
                info = os.lstat(os.path.join(dirpath, name))
            except OSError:      # vanished mid-scan
                continue
            if stat.S_ISREG(info.st_mode):
                total += info.st_size
    return total


def _manifest(folder: Path) -> tuple[RecordingManifest, bytes] | None:
    try:
        raw = (folder / MANIFEST_NAME).read_bytes()
        return RecordingManifest.model_validate_json(raw), raw
    except (OSError, ValueError):
        return None


def _summary(folder: Path, meta: dict, active_id: str | None) -> dict:
    manifest = _manifest(folder)
    if folder.name == active_id:
        status = "recording"
    elif manifest is not None and manifest[0].id == folder.name:
        status = "complete"
    else:
        status = "incomplete"
    complete = status == "complete"
    ended = meta.get("ended_at")
    topics = meta.get("topics")
    return RecordingSummary(
        id=folder.name, started_at=meta["started_at"],
        ended_at=ended if isinstance(ended, str) else None,
        duration_s=manifest[0].duration_s if complete else None,
        bytes=_folder_bytes(folder),
        topics=tuple(str(t) for t in topics) if isinstance(topics, list) else (),
        status=status,
        manifest_sha256=hashlib.sha256(manifest[1]).hexdigest() if complete else None,
        fetched=(folder / FETCHED_NAME).is_file(),
        preview_mode=meta.get('preview_mode', 'raw'),
    ).model_dump()


def list_recordings(root: Path, *, active_id: str | None) -> list[dict]:
    """Newest first; RecordingSummary dicts. Folders that are not recordings are skipped."""
    root = Path(root)
    rows = []
    try:
        entries = list(root.iterdir())
    except OSError:
        return []
    for folder in entries:
        if not recording_id_ok(folder.name) or folder.is_symlink() or not folder.is_dir():
            continue
        try:
            meta = json.loads((folder / SESSION_NAME).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(meta, dict) or meta.get("mode") != "pilot" \
                or not isinstance(meta.get("started_at"), str):
            continue
        try:
            rows.append(_summary(folder, meta, active_id))
        except ValueError:       # a session.json the summary contract refuses
            continue
    rows.sort(key=lambda row: (row["started_at"], row["id"]), reverse=True)
    return rows


class Member(NamedTuple):
    """One tar member. `data` is set for manifest.json (streamed from the validated bytes);
    a file member is identified by (dev, ino) so a swap after the plan is caught."""
    arcname: str
    path: Path
    size: int
    mtime: float
    ident: tuple[int, int]
    data: bytes | None = None


def _open_nofollow(path: Path) -> int:
    """O_NOFOLLOW where the platform has it (Linux); Windows has no such flag."""
    return os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))


def _read_manifest(path: Path) -> tuple[bytes, os.stat_result]:
    fd = _open_nofollow(path)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise OSError(f"{path.name} is not a regular file")
        with os.fdopen(os.dup(fd), "rb") as handle:
            return handle.read(), info
    finally:
        os.close(fd)


def archive_plan(root: Path, recording_id: str) -> tuple[list[Member], int]:
    """Members for manifest.json then every manifest file, and the exact tar length.
    LookupError for an unknown/unsafe id, a symlinked folder, a missing or invalid manifest, a
    member that escapes the folder, is not a regular file, or whose size differs."""
    if not recording_id_ok(recording_id):
        raise LookupError("unknown recording")
    folder = Path(root) / recording_id
    if folder.is_symlink():
        raise LookupError("recording folder is a link")
    base = folder.resolve(strict=False)
    try:
        raw, manifest_info = _read_manifest(folder / MANIFEST_NAME)
        manifest = RecordingManifest.model_validate_json(raw)
    except (OSError, ValueError) as exc:
        raise LookupError("recording has no valid manifest") from exc
    if manifest.id != recording_id:
        raise LookupError("manifest names another recording")
    members = [Member(f"{recording_id}/{MANIFEST_NAME}", folder / MANIFEST_NAME, len(raw),
                      manifest_info.st_mtime, (0, 0), raw)]
    for item in manifest.files:
        path = folder / item.path
        try:
            info = os.lstat(path)                    # never follow a link
            inside = path.resolve(strict=True).is_relative_to(base)
        except OSError as exc:
            raise LookupError(f"member {item.path} is missing") from exc
        if not stat.S_ISREG(info.st_mode) or not inside or info.st_size != item.bytes:
            raise LookupError(f"member {item.path} changed or escapes the recording")
        members.append(Member(f"{recording_id}/{item.path}", path, item.bytes, info.st_mtime,
                              (info.st_dev, info.st_ino)))
    length = sum(_BLOCK + -(-m.size // _BLOCK) * _BLOCK for m in members) + 2 * _BLOCK
    return members, length


def _header(arcname: str, size: int, mtime: float) -> bytes:
    info = tarfile.TarInfo(arcname)
    info.size, info.mtime, info.mode, info.type = size, int(mtime), 0o640, tarfile.REGTYPE
    return info.tobuf(format=tarfile.USTAR_FORMAT, encoding="utf-8", errors="strict")


def _file_blocks(member: Member, chunk_size: int):
    fd = _open_nofollow(member.path)
    try:
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) != member.ident or info.st_size != member.size:
            raise OSError(f"{member.arcname} changed since the archive was planned")
        yield _header(member.arcname, member.size, member.mtime)
        sent = 0
        while sent < member.size:
            block = os.read(fd, min(chunk_size, member.size - sent))
            if not block:
                raise OSError(f"{member.arcname} shrank while streaming")
            sent += len(block)
            yield block
    finally:
        os.close(fd)


def iter_archive(members, chunk_size: int = 1 << 20):
    """Uncompressed USTAR stream (mcap is already zstd): header, data, pad, two zero blocks.
    OSError if a member changed since archive_plan: the stream then ends short of its length."""
    for member in members:
        if member.data is not None:
            yield _header(member.arcname, member.size, member.mtime)
            yield member.data
        else:
            yield from _file_blocks(member, chunk_size)
        if member.size % _BLOCK:
            yield b"\0" * (_BLOCK - member.size % _BLOCK)
    yield b"\0" * (2 * _BLOCK)
