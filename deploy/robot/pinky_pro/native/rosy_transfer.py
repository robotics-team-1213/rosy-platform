"""Paced bulk downloads for the robot updater (network load). Standard library only.

``paced`` reads a response in chunks and sleeps so the transfer averages at most
``ROSY_UPDATE_LIMIT_KBPS`` kbit/s (default 2000, 0 = unlimited; an unreadable value uses the
default), leaving the site Wi-Fi to the robots' control traffic.
"""

from __future__ import annotations

import os
import time

LIMIT_ENV = "ROSY_UPDATE_LIMIT_KBPS"
DEFAULT_LIMIT_KBPS = 2000


def limit_kbps(environ=os.environ) -> int:
    raw = environ.get(LIMIT_ENV, "")
    return int(raw) if raw.isdigit() else DEFAULT_LIMIT_KBPS


def paced(response, limit: int | None = None, clock=time.monotonic, sleep=time.sleep):
    """Yield ``(bytes so far, chunk)`` from ``response.read`` at no more than ``limit`` kbit/s."""
    limit = limit_kbps() if limit is None else limit
    started, total = clock(), 0
    while chunk := response.read(64 * 1024 if limit > 0 else 1024 * 1024):
        total += len(chunk)
        yield total, chunk
        if limit > 0 and (ahead := total * 8 / (limit * 1000) - (clock() - started)) > 0:
            sleep(ahead)
