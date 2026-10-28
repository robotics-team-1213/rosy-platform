"""Append operator keys through anchored directories, retaining sshd readability."""
from __future__ import annotations

import contextlib
import os
from pathlib import Path
import stat
import uuid


def merge_operator_keys(root: Path, keys: list[str]) -> None:
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    with contextlib.ExitStack() as opened:
        try:
            parent = os.open(root, directory_flags)
            opened.callback(os.close, parent)
            for name in ("home", "rosy", ".ssh"):
                parent = os.open(name, directory_flags, dir_fd=parent)
                opened.callback(os.close, parent)
            owner = os.fstat(parent)
            if owner.st_mode & 0o022:
                raise ValueError("operator key directory is writable by another principal")
            previous = None
            try:
                descriptor = os.open("authorized_keys", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            except FileNotFoundError:
                raw = b""
            else:
                with os.fdopen(descriptor, "rb") as stream:
                    previous = os.fstat(stream.fileno())
                    if (not stat.S_ISREG(previous.st_mode) or previous.st_nlink != 1
                            or previous.st_size > 64 * 1024 or previous.st_mode & 0o022
                            or previous.st_uid not in (owner.st_uid, Path(root).stat().st_uid)):
                        raise ValueError("operator key file type/owner/permissions differ")
                    raw = stream.read(64 * 1024 + 1)
            if len(raw) > 64 * 1024:
                raise ValueError("operator key file exceeds limit")
            existing = [line for line in raw.decode("utf-8").splitlines() if line.strip()]
            merged = existing + [key for key in keys if key not in existing]
            content = ("\n".join(merged) + "\n").encode("utf-8") if merged else b""
            if len(content) > 64 * 1024:
                raise ValueError("operator key file exceeds limit")
            if (previous is not None and raw == content and previous.st_uid == owner.st_uid
                    and previous.st_gid == owner.st_gid and stat.S_IMODE(previous.st_mode) == 0o600):
                return
            temporary = ".rosy-operator-keys-" + uuid.uuid4().hex
            try:
                descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                     0o600, dir_fd=parent)
                with os.fdopen(descriptor, "wb") as stream:
                    os.fchmod(stream.fileno(), 0o600)
                    os.fchown(stream.fileno(), owner.st_uid, owner.st_gid)
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, "authorized_keys", src_dir_fd=parent, dst_dir_fd=parent)
                os.fsync(parent)
            finally:
                try:
                    os.unlink(temporary, dir_fd=parent)
                except FileNotFoundError:
                    pass
        except (OSError, UnicodeError) as exc:
            raise ValueError("operator key path cannot be safely read or replaced") from exc
