"""Atomic native release pointers; standalone signature verification never imports this owner."""
import os
from pathlib import Path
import re

RELEASE_ID = re.compile(r"^[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]{3}$")


class SymlinkStore:
    """Linux implementation of the two atomic release pointers."""

    def __init__(self, base: Path, releases: Path) -> None:
        self.base = base
        self.releases = releases

    def _path(self, name: str) -> Path:
        if name not in {"current", "previous"}:
            raise ValueError("NATIVE_LINK_UNSAFE: unknown release link")
        return self.base / name

    def get(self, name: str) -> str | None:
        link = self._path(name)
        if not link.exists() and not link.is_symlink():
            return None
        if not link.is_symlink():
            raise ValueError(f"NATIVE_LINK_UNSAFE: {link} is not a symlink")
        resolved = link.resolve()
        if resolved.parent != self.releases.resolve() or not RELEASE_ID.fullmatch(resolved.name):
            raise ValueError(f"NATIVE_LINK_UNSAFE: {link} leaves the release store")
        return resolved.name

    def set(self, name: str, release_id: str | None) -> None:
        link = self._path(name)
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.exists() and not link.is_symlink():
            raise ValueError(f"NATIVE_LINK_UNSAFE: refusing to replace {link}")
        if release_id is None:
            link.unlink(missing_ok=True)
            return
        target = self.releases / release_id
        if target.is_symlink() or not target.is_dir() or target.resolve().parent != self.releases.resolve():
            raise ValueError("NATIVE_RELEASE_PATH: release link target is unsafe")
        temporary = link.with_name(f".{link.name}.new")
        temporary.unlink(missing_ok=True)
        temporary.symlink_to(target, target_is_directory=True)
        os.replace(temporary, link)
