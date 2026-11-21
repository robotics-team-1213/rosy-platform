"""Lowercase SHA-256 syntax and bounded-memory file hashing."""

import hashlib
from pathlib import Path
import re


def is_sha256_hex(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def checkpoint_sha256(root: Path, paths=None, *, allow_symlinks: bool = True) -> str:
    """sha256 over sorted relative POSIX path + NUL + bytes (the OMX policy runner's checkpoint digest, D-854 2).

    paths=None hashes every file under root except those inside a .cache directory; a directory without files is a
    ValueError (a Hub ID would hash nothing). allow_symlinks=False refuses a root holding links (execution pins).
    An explicit paths list (registered policy files, relative to root) is hashed as given, sorted by path.
    """
    root = Path(root)
    if paths is None:
        if not allow_symlinks and (root.is_symlink() or any(p.is_symlink() for p in root.rglob('*'))):
            raise ValueError('a pinned checkpoint must not contain symlinks')
        files = sorted(p for p in root.rglob('*') if p.is_file() and '.cache' not in p.relative_to(root).parts) if root.is_dir() else []
        paths = [p.relative_to(root).as_posix() for p in files]
    if not paths:
        raise ValueError('a local checkpoint directory with files is required')
    digest = hashlib.sha256()
    for relative in sorted(paths):
        digest.update(relative.encode() + b'\0' + (root / relative).read_bytes())
    return digest.hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()
