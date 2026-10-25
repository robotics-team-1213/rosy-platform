"""OS-owned state IO: admission must not import application provisioning code."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile

SERIAL = re.compile(r"^[0-9a-f]{8,32}$")


def _write_atomic(path: Path, content: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.chmod(temporary, mode)
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if os.name == "posix":
            parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _json_atomic(path: Path, payload: dict, mode: int) -> None:
    _write_atomic(path, json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", mode)
