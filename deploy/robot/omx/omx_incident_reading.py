"""Reading an ended session's runner status rows and its 30 Hz trace (split from omx_incident for size, D-1047)."""
from __future__ import annotations

import json
from pathlib import Path


def rows(path, since=0.0):
    out = []
    p = Path(path) if path else None
    if not p or not p.is_file():
        return out
    with p.open("rb") as f:
        pos = f.seek(0, 2)
        carry, done = b"", False
        while pos > 0 and not done:
            start = max(0, pos - 65536)
            f.seek(start)
            buf = f.read(pos - start) + carry
            pos = start
            lines = buf.split(b"\n")
            carry = lines[0] if pos > 0 else b""
            for raw in reversed(lines[1:] if pos > 0 else lines):
                if not raw.strip():
                    continue
                try:
                    row = json.loads(raw.decode("utf-8", errors="replace"))
                except ValueError:
                    continue
                if row.get("t", since) < since:
                    done = True
                    break
                out.append(row)
    out.reverse()
    return out


def stop_reading(status: list) -> dict | None:
    """What the 30 Hz trace says of the session's last contact stop: too fast or blocked (cell_why). 2026-11-07: an hour of guessing
    with the answer on disk, and the explanation had no frames and no such fact."""
    import os
    import re

    import cell_why

    stops = [re.match(r"contact in (.+?):", str(r.get("error") or "")) for r in status]
    stops = [m.group(1) for m in stops if m and m.group(1) != "park"]  # a fold refused on what it holds follows the real stop
    path = os.environ.get("ROSY_CHUNK_TRACE")
    if not stops or not path or not Path(path).is_file():
        return None
    try:
        return {"chunk": stops[-1], **cell_why.read_motion(cell_why.last_run(cell_why.read_trace(path), stops[-1]))}
    except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:  # a damaged trace must not lose the report
        return {"chunk": stops[-1], "verdict": "undetermined", "why": f"trace unreadable: {type(exc).__name__}"}
