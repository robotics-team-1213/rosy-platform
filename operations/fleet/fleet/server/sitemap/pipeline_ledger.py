"""Durable replacement of the Fleet cell-task and safety ledger."""
from __future__ import annotations

from contextlib import suppress
import json
import os
import tempfile
from pathlib import Path


class LedgerRollbackError(OSError):
    """Raised when restoring prior ledger bytes fails after os.replace + fsync failure."""


def _atomic_write_bytes(path: Path, data: bytes, prefix: str) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, prefix=prefix, suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_ledger(path: Path, value: dict) -> None:
    payload = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    previous = path.read_bytes() if path.is_file() else None
    _atomic_write_bytes(path, payload, ".rosy-pipeline-ledger-")
    if os.name == "posix":
        try:
            fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except Exception as exc:
            try:
                if previous is None:
                    path.unlink(missing_ok=True)
                else:
                    _atomic_write_bytes(path, previous, ".rosy-pipeline-rollback-")
            except Exception as rb_exc:
                raise LedgerRollbackError("ledger rollback failed after replace") from rb_exc
            raise exc
