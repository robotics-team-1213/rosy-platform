#!/usr/bin/env python3
"""Device-twin stand-in for a ROS launch (rosy-io, rosy-camera; twin only, never shipped).

Idles until SIGINT/SIGTERM, then takes STOP_DELAY_S to exit like a ROS launch
shutting its nodes down. That delay is what makes a target-only stop return
before rosy-core's queued stop job runs (the 2026-10-01 activation defect).
"""

from __future__ import annotations

import os
from pathlib import Path
import signal
import sys
import threading

STOP_DELAY_S = 1.5


def main() -> int:
    role = sys.argv[1] if len(sys.argv) > 1 else "node"
    release = (Path.cwd() / "install" / ".rosy-release").read_text(encoding="utf-8").strip()
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    print(f"twin {role} {release} pid={os.getpid()} cwd={os.getcwd()}", flush=True)
    stop.wait()
    threading.Event().wait(STOP_DELAY_S)
    print(f"twin {role} stopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
