"""Durable replacement of the Fleet cell-task and safety ledger."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def write_ledger(path: Path, value: dict) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=path.parent, prefix=".rosy-pipeline-ledger-",
                                         suffix=".tmp", delete=False, encoding="utf-8") as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name == "posix":
            fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
