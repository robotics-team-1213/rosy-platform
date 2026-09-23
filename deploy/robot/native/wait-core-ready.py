#!/usr/bin/env python3
"""Bounded local readiness probe for rosy-core.service."""

from __future__ import annotations

import os
import signal
import sys
import time
import urllib.error
import urllib.request


PORT = os.environ.get("ROSY_API_PORT", "8080")
URL = f"http://127.0.0.1:{PORT}/api/v1"
TIMEOUT_SECONDS = float(os.environ.get("ROSY_CORE_READY_TIMEOUT_S", "45"))


def main() -> int:
    deadline = time.monotonic() + TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(URL, timeout=2) as response:
                if 200 <= response.status < 500:
                    return 0
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(1)
    print(f"CORE readiness timed out after {TIMEOUT_SECONDS:.1f}s", file=sys.stderr)
    return 1


def _stop_requested(signum, frame) -> None:
    # `systemctl stop` while the unit is still activating signals this probe too. A
    # control process killed by SIGINT/SIGTERM leaves the unit failed (Result=signal),
    # although the stop was requested. Abandon the wait cleanly instead.
    print("CORE readiness wait abandoned: stop requested", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    for _signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(_signum, _stop_requested)
    sys.exit(main())
