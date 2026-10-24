"""Atomic file operations shared by image-layer sync and boot continuity."""

import hashlib
import json
import os
from pathlib import Path
import shutil


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()

def _mode(path: Path) -> int:
    return path.stat().st_mode & 0o7777

def _install(source: Path, destination: Path, mode: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.rosy-sync.tmp")
    temporary.unlink(missing_ok=True)
    with source.open("rb") as reader, temporary.open("wb") as writer:
        shutil.copyfileobj(reader, writer)
        writer.flush()
        os.chmod(temporary, mode)
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            os.chown(temporary, 0, 0)
        os.fsync(writer.fileno())
    os.replace(temporary, destination)
    if os.name == "posix":
        descriptor = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

def _write_json(path: Path, payload: dict) -> None:
    """Write, fsync, rename, and fsync the folder: it survives a power loss."""
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    if os.name == "posix":
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
