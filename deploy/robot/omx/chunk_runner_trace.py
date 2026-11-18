"""The trace-file receipt a runner report carries: which bytes of the owner's trace this report covers (split out of `chunk_runner_run`)."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re


def trace_receipt(runner, command: str | None, reported_at: float, ok=None) -> dict | None:
    file, source = runner.trace_file, runner.trace_source
    if file is None:
        return None
    if command == "human-hold" or ok is False:
        return {"status": "aborted"}
    if (not isinstance(source, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", source)
            or not isinstance(runner.operating_context, dict)
            or not runner.operating_context.get("session_id")):
        return {"status": "unbound"}
    try:
        file.flush()
        opened, current = os.fstat(file.fileno()), Path(file.name).stat()
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            return {"status": "rotated"}
        start, end = runner.trace_cursor, opened.st_size
        if end < start:
            return {"status": "truncated"}
        if end - start > 1024 * 1024:
            return {"status": "segment_too_large"}
        with Path(file.name).open("rb") as reader:
            reader.seek(start)
            segment = reader.read(end - start)
        if len(segment) != end - start:
            return {"status": "source_changed"}
    except OSError:
        return {"status": "unavailable"}
    runner.trace_cursor = end
    runner.trace_sequence += 1
    return {"status": "ok", "source": source, "start": start, "end": end,
            "sha256": hashlib.sha256(segment).hexdigest(), "sequence": runner.trace_sequence,
            "session_id": runner.operating_context["session_id"],
            "library_sha256": runner._library_digest(), "command": command,
            "reported_at": reported_at}
